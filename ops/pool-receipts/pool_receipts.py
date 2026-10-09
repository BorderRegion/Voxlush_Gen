"""Opt-in durable receipts; EOF/deadline/disconnect never certify termination."""
import hashlib
import json
import os
import re
import time
from pathlib import Path

TERMINAL = {'stop', 'length', 'tool_calls', 'function_call', 'content_filter'}
HEADER_NAMES = {'x-request-id', 'nvcf-reqid', 'nvcf-status', 'x-correlation-id'}
MAX_BYTES = 16 * 1024 * 1024


def root():
    value = os.environ.get('API_POOL_RECEIPT_DIR')
    if not value:
        raise OSError('receipt storage is not configured')
    return Path(value)


def key(value):
    if not re.fullmatch('[a-f0-9]{32}', value or ''):
        raise ValueError('request ID must be a 32-digit hex identifier')
    return value


def read(value):
    return json.loads((root() / (key(value) + '.json')).read_text())


def raw_path(value):
    return root() / (key(value) + '.body')


class Receipt:
    def __init__(self, value, body):
        self.id = key(value)
        directory = root()
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        # Never reuse a dispatched ID, including after worker restarts.
        self.lock = directory / (self.id + '.lock')
        with self.lock.open('xb') as f:
            f.write(hashlib.sha256(body).hexdigest().encode())
            f.flush()
            os.fsync(f.fileno())
        self.path = directory / (self.id + '.json')
        self.data = {'schema':'pool.receipt.v1', 'request_id':self.id,
                     'request_sha256':hashlib.sha256(body).hexdigest(),
                     'state':'reserved', 'execution_state':'not_sent',
                     'upstream_posts':0, 'created_at':time.time(),
                     'cost':None, 'billing_status':'unknown', 'downstream_disconnected':False}
        self.file = None
        self.buffer = b''
        self.size = 0
        self.finish_reason = None
        self.done = False
        self.error = False
        self.content = False
        self.save()

    def save(self):
        temporary = self.path.with_suffix('.tmp')
        with temporary.open('w') as f:
            json.dump(self.data, f, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        temporary.replace(self.path)
        fd = os.open(self.path.parent, os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def dispatch(self, source_id=None):
        if self.data['upstream_posts']:
            raise RuntimeError('a receipt permits only one upstream POST')
        self.data.update(state='dispatched', execution_state='execution_unknown', upstream_posts=1)
        if source_id is not None:
            self.data['source_sha256'] = hashlib.sha256(source_id.encode()).hexdigest()
        self.save()  # Durable before any possibly billable call.

    def headers(self, response):
        self.data.update(http_status=response.status_code,
                         upstream_headers={k.lower():v for k,v in response.headers.items() if k.lower() in HEADER_NAMES})
        self.save()
        self.file = raw_path(self.id).open('xb')

    def absorb(self, obj):
        if not isinstance(obj,dict):
            return
        self.error |= bool(obj.get('error'))
        if isinstance(obj.get('id'),str):
            self.data['model_response_id'] = obj['id']
        if isinstance(obj.get('usage'),dict):
            self.data['usage'] = obj['usage']
        for choice in obj.get('choices',[]) or []:
            if not isinstance(choice,dict) or choice.get('index',0) != 0:
                continue
            reason = choice.get('finish_reason')
            if reason in TERMINAL:
                self.finish_reason = reason
            delta = choice.get('delta') or choice.get('message') or {}
            self.content |= isinstance(delta,dict) and bool(delta.get('content'))

    def chunk(self, value, stream=True):
        self.size += len(value)
        if self.size > MAX_BYTES:
            raise OSError('receipt response byte limit exceeded')
        self.file.write(value)
        self.buffer += value
        if stream:
            while b'\n' in self.buffer:
                line,self.buffer = self.buffer.split(b'\n',1)
                if line.startswith(b'data:'):
                    data = line[5:].strip()
                    if data == b'[DONE]':
                        self.done = True
                    else:
                        try:
                            self.absorb(json.loads(data))
                        except (ValueError,TypeError):
                            self.error = True

    def disconnected(self):
        if not self.data['downstream_disconnected']:
            self.data['downstream_disconnected'] = True
            self.save()

    def end(self, failure=None, stream=True):
        if not stream and self.buffer:
            try:
                self.absorb(json.loads(self.buffer))
            except (ValueError,TypeError):
                self.error = True
        if self.file:
            self.file.flush()
            os.fsync(self.file.fileno())
            self.file.close()
            self.file = None
            self.data['body_sha256'] = hashlib.sha256(raw_path(self.id).read_bytes()).hexdigest()
        terminated = self.finish_reason in TERMINAL
        self.data.update(state='settled', ended_at=time.time(), finish_reason=self.finish_reason,
                         execution_state='terminated' if terminated else self.data['execution_state'],
                         response_complete=bool(terminated and self.finish_reason == 'stop' and self.content
                                                and not self.error and (self.done or not stream) and not failure),
                         failure=failure, response_bytes=self.size)
        self.save()
