"""One bounded scheduler, independent resource lanes and finite evidence-guided repairs."""
from __future__ import annotations
import asyncio
import errno
import hashlib
import json
import shutil
import tempfile
import time
from pathlib import Path
from voxlush.core.config import Config
from voxlush.core.files import atomic_json,digest
from voxlush.store.store import Store
from voxlush.store.sqlite import OperationalError
from voxlush.inference.client import PoolClient, request_body
from voxlush.inference import execution_state
from voxlush.themes.planner import runtime_task, task_for
from voxlush.pipeline.prompts import author_messages,extract_source,review_messages,parse_review,RUBRIC_VERSION
from voxlush.voxel.adapter import build,render
from voxlush.voxel.sandbox import SandboxError, probe_resource
from voxlush.dataset.archive import Archive
from voxlush.voxel.canonical import load_and_validate
from voxlush.dataset.dedup import features_from_asset

NETWORK = ("author","refine","review")
SHARED_SANDBOX = ("sandbox_unavailable", "sandbox_image_version_mismatch")


def shared_storage_failure(error):
    """Storage scope, not every file-related exception, stops paid dispatch."""
    return isinstance(error, OperationalError) or (
        isinstance(error, OSError)
        and error.errno in {errno.ENOSPC, errno.EDQUOT, errno.EROFS, errno.EIO, errno.ENODEV}
    )

class Scheduler:
    def __init__(self,store: Store,config: Config,client=None):
        self.store,self.config = store,config
        self.store.bind_config(config)
        self.client = client or PoolClient(max_connections=max(1,config.global_api_cap))
        self.archive = Archive(store.root)
        self.archive_lock = asyncio.Lock()
        self.active: dict[asyncio.Task,str] = {}
        self.active_campaigns: dict[asyncio.Task,str] = {}
        self.stopping = False
        self.task = None
        self.adaptive_cap = min(8,config.global_api_cap)
        self.window_started = time.monotonic()
        self.window_results = []
        self.blocked_endpoints = set()
        self.loop_error = None
        self.storage_failed = False
        self.snapshots = {}
        self.last_snapshot = 0
        self.backpressure = False
        self.queue_backpressure = False
        self.sandbox_fault = False
        self.next_resource_probe = 0
        self.next_receipt_poll = 0
        self.receipt_cursor = (0, '')
        self.round = 0

    def cap(self,campaign=None):
        if self.storage_failed:
            return 0
        return min(self.config.global_api_cap,self.adaptive_cap,campaign["api_cap"] if campaign else 512) if self.config.author or self.config.visual else 0

    async def start(self):
        self.store.apply_commands(self.config.sample_request_limit)
        await self.recover_responses()
        if self.config.allow_live and self.config.visual and self.config.visual.supports_images:
            self.store.resume_visual_reviews()
        for record in self.archive.pending_commits():
            if self.store.one("SELECT asset_id FROM assets WHERE sample_id=? AND revision=?",(record["sample_id"],record["revision"])):
                self.archive.acknowledge(record["commit_id"])
                continue
            sample = self.store.sample(record["sample_id"])
            if sample and sample["stage"] == "archive" and sample["status"] in ("ready","deferred"):
                claim = self.store.claim(sample["sample_id"],sample["revision"])
                if claim:
                    self.store.commit_asset(claim,record)
                    self.archive.acknowledge(record["commit_id"])
        self.store.restore_shutdown_campaigns()
        self.task = asyncio.create_task(self.run())

    async def stop(self,timeout=30):
        self.stopping = True
        # Closing this owner stops admission, not the user's durable run intent.
        if self.task:
            await self.task
        if self.active:
            done,pending = await asyncio.wait(list(self.active),timeout=timeout)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending,return_exceptions=True)
        await self.client.close()

    async def run(self):
        while not self.stopping:
            try:
                await self.tick()
            except Exception as e:
                # A failed sample callback or writable-store problem cannot kill owner silently.
                self.loop_error = type(e).__name__
                for c in self.store.campaigns():
                    if c["state"] == "running":
                        try:
                            self.store.set_campaign_state(c["campaign_id"],"blocked","store_or_scheduler_failure")
                        except Exception:
                            pass
            await asyncio.sleep(.2)

    def submit(self,coro,lane,campaign_id=None):
        task = asyncio.create_task(coro)
        self.active[task] = lane
        self.active_campaigns[task] = campaign_id

    async def tick(self):
        if self.stopping:
            return
        for task in list(self.active):
            if task.done():
                self.active.pop(task)
                self.active_campaigns.pop(task,None)
                try:
                    task.result()
                except (Exception,asyncio.CancelledError) as e:
                    self.loop_error = type(e).__name__
        self.store.apply_commands(self.config.sample_request_limit)
        self.store.reconcile_deadlines()
        if not self.storage_failed:
            if (time.monotonic() >= self.next_receipt_poll and 'reconcile' not in self.active.values()
                    and any(e and e.pool_receipts for e in (self.config.author,self.config.visual))):
                self.submit(self.recover_pool_receipts(),'reconcile')
            await self.recover_responses(pending_only=True)
        for c in self.store.campaigns():
            if c.get("reason_code") == "emergency_stop":
                for task,lane in list(self.active.items()):
                    if lane == "network" and self.active_campaigns.get(task) == c["campaign_id"]:
                        task.cancel()
        disk_ok = shutil.disk_usage(self.store.root).free >= self.config.disk_reserve_bytes
        queues = self.store.rows("SELECT stage,COUNT(*) n FROM samples WHERE status IN ('ready','running','deferred') GROUP BY stage")
        queued = {q["stage"]:q["n"] for q in queues}
        local_backlog = queued.get("build",0)+queued.get("render",0)
        high,low = self.config.render_workers*8,self.config.render_workers*3
        if local_backlog>high:
            self.queue_backpressure = True
        elif local_backlog<low:
            self.queue_backpressure = False
        await self.check_local_resource()
        self.backpressure = self.queue_backpressure or self.sandbox_fault
        if self.stopping:
            return
        self.adapt()
        for c0 in self.store.campaigns():
            c = self.store.campaign(c0["campaign_id"])
            if c['state'] == 'degraded' and c['reason_code'] == 'coverage_debt':
                if any(i['debt']>i['active'] and self.family_available(i) for i in self.store.coverage(c['campaign_id'])['items']):
                    self.store.set_campaign_state(c['campaign_id'],'running')
                    c = self.store.campaign(c['campaign_id'])
            if c["state"] == "running":
                reason = None
                if self.storage_failed:
                    reason = "storage_unavailable"
                elif not disk_ok:
                    reason = "disk_low_watermark"
                elif c["accepted_unique"]>=c["target"]:
                    self.store.set_campaign_state(c["campaign_id"],"completed","target_reached")
                    continue
                elif (c.get('composition_weights') and not self.config.is_qualified()
                      and c['accepted_unique']+c['provisional_pass']>=c['target']
                      and all(i['candidate_debt'] == 0 for i in self.store.composition_coverage(c['campaign_id'])['items'])):
                    self.store.set_campaign_state(c['campaign_id'],'completed','calibration_target_reached')
                    continue
                elif c["requests_used"]>=c["request_limit"]:
                    reason = "budget_exhausted"
                elif not self.config.allow_live:
                    # Offline local fixture jobs remain runnable; new author work stays explicit.
                    reason = "live_inference_disabled"
                elif self.config.author is None:
                    reason = "author_endpoint_missing"
                elif self.config.author.alias in self.blocked_endpoints:
                    reason = "endpoint_isolated"
                if reason:
                    self.store.set_campaign_state(c["campaign_id"],"blocked",reason)
                elif not self.backpressure:
                    self.plan(c)
        # Local stages use dedicated bounded lanes, including during drain/budget stop.
        for stage,limit in (("archive",self.config.archive_workers),("render",self.config.render_workers),("build",self.config.build_workers)):
            if self.sandbox_fault and stage in ("build", "render"):
                continue
            used = sum(lane == stage for lane in self.active.values())
            for row in self.store.ready([stage],limit=max(0,limit-used),allow_network=False) if limit>used else []:
                c = self.store.campaign(row["campaign_id"])
                if c["state"] == "paused":
                    continue
                claim = self.store.claim(row["sample_id"],row["revision"])
                if claim:
                    self.submit(self.local(claim),stage,claim["campaign_id"])
        # Missing visual capability remains visible even when live inference is disabled.
        if self.config.visual is None or not self.config.visual.supports_images:
            for row in self.store.rows("SELECT * FROM samples WHERE stage='review' AND status IN ('ready','deferred') LIMIT 32"):
                claim = self.store.claim(row["sample_id"],row["revision"])
                if claim:
                    self.store.finish(claim,status="awaiting_review",reason="awaiting_visual")
        if self.config.allow_live and disk_ok and not self.queue_backpressure and not self.storage_failed:
            used = sum(lane == "network" for lane in self.active.values())
            # Weighted rotating preferences borrow unused capacity; oldest work is periodically first.
            weights = ("author","refine","author","review","author","review","author")
            preference = weights[self.round % len(weights)]
            self.round += 1
            pools = {r['capacity_group']:r for r in self.store.rows("SELECT capacity_group,COUNT(*) n,SUM(status='outcome_unknown') unknown FROM attempts WHERE occupancy=1 GROUP BY capacity_group")}
            eligible = []
            for stage in NETWORK:
                if self.sandbox_fault and stage != 'review':
                    continue
                endpoint = self.config.visual if stage == 'review' else self.config.author
                if endpoint is None or endpoint.alias in self.blocked_endpoints or (stage == 'review' and not endpoint.supports_images):
                    continue
                pool = pools.get(endpoint.capacity_key(), {'n':0,'unknown':0})
                if not pool['unknown'] and pool['n'] < endpoint.provider_cap:
                    eligible.append(stage)
            rows = self.store.ready(eligible,limit=max(64,self.cap()*4)) if eligible else []
            if self.round%8:
                rows.sort(key=lambda s:(s["stage"]!=preference,s["updated_at"]))
            for row in rows:
                if used>=self.cap():
                    break
                endpoint = self.config.visual if row["stage"] == "review" else self.config.author
                if endpoint is None or (row["stage"] == "review" and not endpoint.supports_images):
                    claim = self.store.claim(row["sample_id"],row["revision"])
                    if claim:
                        self.store.finish(claim,status="awaiting_review",reason="awaiting_visual")
                    continue
                if endpoint.alias in self.blocked_endpoints:
                    continue
                claim = self.store.reserve(row["sample_id"],row["revision"],endpoint,self.cap(),self.config.sample_request_limit)
                if claim:
                    self.submit(self.network(claim,endpoint),"network",claim["campaign_id"])
                    used += 1
                elif row["request_count"]>=self.config.sample_request_limit:
                    claim = self.store.claim(row["sample_id"],row["revision"])
                    if claim:
                        self.store.finish(claim,status="rejected",reason="sample_request_limit")
        self.loss_control()
        if time.monotonic()-self.last_snapshot>1:
            self.last_snapshot = time.monotonic()
            for c in self.store.campaigns():
                self.snapshots[c["campaign_id"]] = self.store.overview(c["campaign_id"],self.cap(c))
                self.store.metric_snapshot(c["campaign_id"],self.cap(c))

    def plan(self,c):
        coverage = self.store.coverage(c["campaign_id"])
        calibration = bool(c.get('composition_weights')) and not self.config.is_qualified()
        if calibration:
            for row in coverage['items']:
                row['debt'] = max(0,row['debt']-row['provisional'])
        active = coverage["totals"]["active"]
        buffer = min(1024,max(64,4*self.cap(c)))
        if active>=buffer or c["sequence"]>=c["request_limit"]:
            return
        outstanding = c["target"]-c["accepted_unique"]-(c['provisional_pass'] if calibration else 0)-active
        if outstanding<=0:
            return
        candidates = [i for i in coverage["items"] if i["debt"]>i["active"] and self.family_available(i)]
        modes = {}
        if c.get('composition_weights'):
            modes = {scene:self.store.next_composition(c['campaign_id'],scene,qualified=not calibration)
                     for scene in ('architecture','hybrid')}
            candidates = [i for i in candidates if i['scene_type'] == 'natural' or modes.get(i['scene_type'])]
        if not candidates:
            return
        family = max(candidates,key=lambda i:((i["debt"]-i["active"])/max(1,i["target"]),-i["active"],i["family_id"]))
        contract = task_for(c,family["family_id"],c["sequence"],
                            "production" if self.config.is_qualified() else "calibration",
                            seed_id=self.store.next_seed(c['campaign_id'],family['family_id'],modes.get(family['scene_type'])),
                            composition_mode=modes.get(family['scene_type']))
        self.store.add_sample(runtime_task(contract))

    def family_available(self, family):
        return family['consecutive_failures'] < self.config.theme_zero_yield_limit or (
            family['active'] == 0 and family['last_failure_at']+self.config.theme_cooldown_seconds<=time.time())

    def loss_control(self):
        for c in self.store.campaigns():
            if c["state"] != "running":
                continue
            coverage = self.store.coverage(c["campaign_id"])
            totals = coverage["totals"]
            if not totals["active"] and totals["rejected"]+totals["duplicate"]>=self.config.zero_yield_limit and not c["accepted_unique"] and not c["provisional_pass"]:
                self.store.set_campaign_state(c["campaign_id"],"blocked","zero_yield_stop")
            elif not totals["active"] and all(i["debt"]<=0 or not self.family_available(i) for i in coverage["items"]):
                self.store.set_campaign_state(c["campaign_id"],"degraded","coverage_debt")

    def adapt(self):
        if time.monotonic()-self.window_started<120 or len(self.window_results)<30:
            return
        failures = sum(r.get("error_category") in ("rate_limited","service_busy") for r in self.window_results)/len(self.window_results)
        if failures>.05 or self.backpressure:
            self.adaptive_cap = min(self.config.global_api_cap,max(1,int(self.adaptive_cap*.7)))
        elif self.config.is_qualified() and sum(r.get("response_complete",False) for r in self.window_results)/len(self.window_results)>.95:
            self.adaptive_cap = min(self.config.global_api_cap,self.adaptive_cap*2 if self.adaptive_cap<32 else self.adaptive_cap+8)
        self.window_results.clear()
        self.window_started = time.monotonic()

    def work_dir(self,sample):
        return self.store.root/"work"/sample["sample_id"][:2]/sample["sample_id"]/f"v{sample['revision']:04d}"

    async def check_local_resource(self):
        waiting = self.store.one("SELECT 1 FROM samples WHERE status IN ('deferred','blocked') AND stage IN ('build','render') AND reason_code IN ('sandbox_unavailable','sandbox_image_version_mismatch') LIMIT 1")
        if not self.sandbox_fault and not waiting:
            return
        self.sandbox_fault = True
        if time.monotonic() < self.next_resource_probe:
            return
        self.next_resource_probe = time.monotonic() + 30
        try:
            # Trusted tiny container work; never an author request or sample retry.
            await asyncio.to_thread(probe_resource, self.config.model_dump())
        except Exception as exc:
            if shared_storage_failure(exc):
                self.storage_failed = True
            self.loop_error = type(exc).__name__
            return
        self.sandbox_fault = False
        self.store.resume_resource_tasks()

    def persist_json(self,path,value, *, ledger=False):
        try:
            atomic_json(path,value)
        except OSError as exc:
            # An unwritable request/response ledger prevents safe paid work.
            if ledger or shared_storage_failure(exc):
                self.storage_failed = True
            raise

    def response_failure(self, claim, error, reason="response_recovery_failed"):
        """Retry only the saved response's local application, with a durable limit."""
        self.loop_error = type(error).__name__
        changes = {}
        if self.storage_failed or shared_storage_failure(error):
            self.storage_failed = True
            reason = "storage_unavailable"
        else:
            used = claim['local_retries'] + 1
            changes['local_retries'] = used
            if isinstance(error, OSError):
                reason = "local_artifact_invalid"
            if used >= 3:
                reason = "response_recovery_exhausted"
        self.store.finish(claim,status="blocked",reason=reason,delay=30,
                          changes=changes,response_applied=False)
        self.store.record_local_failure(claim,reason,error)

    async def recover_responses(self, pending_only=False):
        for claim,result in self.store.recover(pending_only=pending_only):
            try:
                await self.consume(claim,result)
            except Exception as error:
                self.response_failure(claim,error)

    async def recover_pool_receipts(self):
        if time.monotonic() < self.next_receipt_poll:
            return
        self.next_receipt_poll = time.monotonic() + 30
        endpoints = {'author':self.config.author,'refine':self.config.author,'review':self.config.visual}
        groups = {e.capacity_key() for e in endpoints.values() if e and e.pool_receipts}
        if not groups:
            return
        placeholders = ','.join('?' for _ in groups)
        query = "SELECT * FROM attempts WHERE status='outcome_unknown' AND capacity_group IN ("+placeholders+") AND (started_at,attempt_id) > (?,?) ORDER BY started_at,attempt_id LIMIT 16"
        attempts = self.store.rows(query, (*groups,*self.receipt_cursor))
        if not attempts:
            self.receipt_cursor = (0, '')
            attempts = self.store.rows(query, (*groups,*self.receipt_cursor))
        for attempt in attempts:
            self.receipt_cursor = (attempt['started_at'],attempt['attempt_id'])
            endpoint = endpoints.get(attempt['role'])
            if not endpoint or not endpoint.pool_receipts or endpoint.capacity_key() != attempt['capacity_group']:
                continue
            try:
                request_path = self.store.root/attempt['response_path'].replace('.json','.request.json')
                request = json.loads(request_path.read_text())
                if not request.get('request_sha256') or not request.get('pool_receipts'):
                    continue  # No retroactive promises for historical, untracked POSTs.
                snapshot = self.store.one('SELECT config_json FROM config_snapshots WHERE config_hash=?', (attempt['runtime_config_hash'],))
                original = json.loads(snapshot['config_json'])['visual' if attempt['role']=='review' else 'author']
                if original['base_url'] != 'sha256:'+hashlib.sha256(endpoint.base_url.encode()).hexdigest():
                    continue
                original_endpoint = endpoint.model_copy(update={key:original[key] for key in (
                    'model','parameters','stream','completion','input_per_million','output_per_million')})
                result = await self.client.recover_receipt(original_endpoint,attempt['attempt_id'],attempt['role'],request['request_sha256'])
                if result:
                    path = (self.store.root/attempt['response_path']).with_suffix('.recovered.json')
                    self.persist_json(path,result,ledger=True)
                    self.store.recover_receipt(attempt['attempt_id'],result,path)
            except (OSError,ValueError,KeyError,TypeError) as error:
                self.loop_error = type(error).__name__
                if shared_storage_failure(error):
                    self.storage_failed = True
                if self.storage_failed:
                    break

    async def network(self,claim,endpoint):
        result = None
        request_started = False
        response_saved = False
        response_path = self.store.root/claim["attempt"]["response_path"]
        try:
            if self.storage_failed:
                raise OSError("response storage is unavailable")
            task = {**claim["task"], "phase": claim["creative_phase"]}
            directory = self.work_dir(claim)
            if claim["stage"] == "review":
                messages,_ = review_messages(task,Path(claim["build_path"]))
            else:
                source = Path(claim["source_path"]).read_text() if claim.get("source_path") else None
                feedback_path = directory.parent/"feedback.json"
                feedback = json.loads(feedback_path.read_text()) if feedback_path.exists() else None
                messages = author_messages(task,source,feedback,refine=claim["stage"] == "refine")
            request_path = self.store.root/claim["attempt"]["response_path"].replace(".json",".request.json")
            self.persist_json(request_path,{"messages":messages,"endpoint_alias":endpoint.alias,"model":endpoint.model,"parameters":endpoint.parameters,
                                           "stream":endpoint.stream,"pool_receipts":endpoint.pool_receipts,
                                           "request_sha256":hashlib.sha256(request_body(endpoint,messages)).hexdigest()},ledger=True)
            request_started = True
            result = await self.client.call(endpoint,messages,claim["attempt_id"],claim["stage"])
            # Durable response first. Crash here is recovered without a second POST.
            self.persist_json(response_path,result,ledger=True)
            response_saved = True
            self.store.settle(claim["attempt_id"],result)
            self.window_results.append({"error_category":result.get("error_category"),"response_complete":result.get("response_complete"),"elapsed_ms":result.get("elapsed_ms")})
            if len(self.window_results)>1024:
                del self.window_results[:len(self.window_results)-1024]
            await self.consume(claim,result)
        except (Exception,asyncio.CancelledError) as e:
            self.loop_error = type(e).__name__
            if shared_storage_failure(e):
                self.storage_failed = True
            if result is None:
                result = {"error_category":"outcome_unknown" if request_started else "not_sent",
                          "response_complete":False,"cost":None if request_started else 0}
            # A failed write cannot prevent accounting; a failed callback cannot
            # replace a complete response with an unknown outcome.
            if not response_saved:
                try:
                    self.persist_json(response_path,result,ledger=True)
                except OSError:
                    pass
            reason = "outcome_unknown" if execution_state(result) == "execution_unknown" else "storage_unavailable" if self.storage_failed else "finish_callback_failed"
            if isinstance(e, OSError) and not self.storage_failed and reason != "outcome_unknown":
                reason = "local_artifact_invalid"
            try:
                self.store.settle(claim["attempt_id"],result)
                if response_saved and result.get('response_complete'):
                    self.response_failure(claim,e,reason)
                else:
                    self.store.finish(claim,status="blocked",reason=reason,delay=1,response_applied=not request_started)
                    self.store.record_local_failure(claim, reason, e)
                if self.storage_failed:
                    for campaign in self.store.campaigns():
                        if campaign["state"] == "running":
                            self.store.set_campaign_state(campaign["campaign_id"],"blocked","storage_unavailable")
            except Exception as final_error:
                # If SQLite itself is unavailable, retain durable responses for
                # startup recovery and prevent further paid work in this owner.
                self.storage_failed = True
                self.loop_error = type(final_error).__name__

    async def consume(self,claim,result):
        category = result.get("error_category")
        if execution_state(result) == "execution_unknown":
            self.store.finish(claim,status="blocked",reason="outcome_unknown")
            return
        if not result.get("response_complete"):
            if category in ("endpoint_auth","endpoint_configuration","endpoint_quota"):
                endpoint = self.config.visual if claim["stage"] == "review" else self.config.author
                self.blocked_endpoints.add(endpoint.alias)
                self.store.finish(claim,status="blocked",reason=category)
            elif category in ("not_sent","rate_limited","service_busy") and claim["transport_retries"]<self.config.transport_retries:
                self.store.finish(claim,status="deferred",reason=category,delay=result.get("retry_after") or 2**(claim["transport_retries"]+1),changes={"transport_retries":claim["transport_retries"]+1})
            else:
                if claim['stage'] == 'review':
                    self.retry_review(claim,category or 'incomplete_review')
                else:
                    self.repair(claim,{"error_category":category or "incomplete_response"})
            return
        if claim["stage"] == "review":
            directory = Path(claim["build_path"])
            geometry = json.loads((directory/"geometry.json").read_text())
            hashes = [digest(directory/"previews"/f"view_{v}.webp") for v in ("a","b")]
            try:
                review = parse_review(result["content"],geometry["canonical_voxel_hash"],hashes,self.config.is_qualified(),task=claim['task'])
                self.persist_json(directory/"review.json",review)
            except (ValueError,KeyError,TypeError):
                self.retry_review(claim,'review_format')
                return
            self.store.record_review(claim,review)
            if review["passed"]:
                self.store.finish(claim,stage="archive",changes={"review_json":json.dumps(review),"local_retries":0})
            elif review['status'] == 'gray':
                # Assessor uncertainty is not a demonstrated author defect.
                self.retry_review(claim,'review_uncertain')
            else:
                self.repair(claim,review,visual=True)
        else:
            try:
                source = extract_source(result["content"])
            except (ValueError,SyntaxError) as e:
                self.repair(claim,{"error_category":"invalid_source","message":str(e)[:2000]})
                return
            directory = self.work_dir(claim)
            source_path = directory/"authored_source.py"
            try:
                directory.mkdir(parents=True,exist_ok=True)
                source_path.write_text(source)
            except OSError as exc:
                if shared_storage_failure(exc):
                    self.storage_failed = True
                raise
            self.store.finish(claim,stage="build",changes={"source_path":str(source_path),"source_hash":hashlib.sha256(source.encode()).hexdigest(),"local_retries":0})

    def retry_review(self, claim, reason):
        used = claim['review_format_retries']
        if used >= self.config.review_format_retries or claim['request_count'] >= self.config.sample_request_limit:
            self.store.finish(claim,status='awaiting_review',reason='review_uncertain' if reason == 'review_uncertain' else 'review_format_exhausted')
        else:
            self.store.finish(claim,stage='review',status='deferred',reason=reason,
                              changes={'review_format_retries':used+1})

    def repair(self,claim,evidence,visual=False):
        key = "visual_repairs" if visual else "geometry_repairs"
        limit = self.config.visual_repairs if visual else self.config.geometry_repairs
        fingerprint = hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest()
        identical = claim["identical_errors"]+1 if fingerprint == claim.get("error_fingerprint") else 1
        if claim[key]>=limit or identical>=2 or claim["request_count"]>=self.config.sample_request_limit:
            self.store.finish(claim,status="rejected",reason="same_error_no_progress" if identical>=2 else "repair_exhausted")
            return
        directory = self.work_dir(claim)
        self.persist_json(directory/'repair_evidence.json',evidence)
        self.persist_json(directory.parent/"feedback.json",evidence)
        self.store.finish(claim,stage="author",reason="visual_repair" if visual else "geometry_repair",changes={key:claim[key]+1,"error_fingerprint":fingerprint,"identical_errors":identical,"revision":claim["revision"]+1,"local_retries":0})

    def local_failure(self, claim, reason, *, retryable=True):
        """Environment work stays on the same source/revision and never costs a POST."""
        used = claim["local_retries"]
        if reason in SHARED_SANDBOX:
            self.sandbox_fault = True
            if used >= 3:
                # A passing probe must not cause infinite retries of a bad task.
                reason = "sandbox_recovery_exhausted"
                retryable = False
        retry = retryable and used < 2
        self.store.finish(claim,status="deferred" if retry else "blocked",reason=reason,
                          delay=2**(used+1) if retry else 0,changes={"local_retries":used+1})

    async def local(self,claim):
        try:
            directory = self.work_dir(claim)
            task = {**claim["task"], "phase": claim["creative_phase"]}
            if claim["stage"] == "build":
                directory = Path(claim["build_path"]) if claim.get("build_path") and Path(claim["build_path"]).is_relative_to(directory) else directory
                result = None
                if (directory/"geometry.json").exists():
                    try:
                        canonical = await asyncio.to_thread(load_and_validate,directory)
                        cached = json.loads((directory/"geometry.json").read_text())
                        if (cached.get("canonical_voxel_hash") == canonical["canonical_voxel_hash"]
                                and cached.get("phase") == task["phase"]):
                            result = cached
                    except (ValueError,OSError,KeyError) as exc:
                        if shared_storage_failure(exc):
                            raise
                if result is None:
                    # Recover partial local work into a new isolated destination.
                    output = directory
                    if any((directory/name).exists() for name in ("sample.json","voxels.npz","geometry.json")):
                        output = Path(tempfile.mkdtemp(prefix="retry-build-",dir=self.work_dir(claim)))
                    # Persist the local destination before execution, so restart
                    # can inspect it without overwriting the previous evidence.
                    self.store.set_build_path(claim,output)
                    result = await asyncio.to_thread(build,Path(claim["source_path"]).read_text(),task,output,self.config.model_dump())
                    directory = output
                if not result.get("passed"):
                    reasons = {v.get("rule") for v in result.get("violations",[])}
                    environment = reasons & {"sandbox_unavailable","sandbox_image_version_mismatch"}
                    if environment:
                        reason = sorted(environment)[0]
                        self.local_failure(claim,reason,retryable=reason == "sandbox_unavailable")
                    else:
                        self.repair(claim,result)
                elif task["phase"] == "skeleton":
                    self.store.finish(claim,stage="refine",changes={"build_path":str(directory),"revision":claim["revision"]+1,"creative_phase":"final","local_retries":0})
                else:
                    self.store.finish(claim,stage="render",changes={"build_path":str(directory),"local_retries":0})
            elif claim["stage"] == "render":
                directory = Path(claim["build_path"])
                await asyncio.to_thread(render,directory,self.config.model_dump())
                ids = []
                for name in ("view_a.webp","view_b.webp","contact.webp"):
                    p = directory/"previews"/name
                    ids.append(self.store.register_artifact(claim["sample_id"],p,name,digest(p)))
                if task.get("record_kind") == "fixture":
                    geometry = json.loads((directory/"geometry.json").read_text())
                    review = {"status":"pass","passed":True,"input_voxel_sha256":geometry["canonical_voxel_hash"],"image_sha256":[digest(directory/"previews"/f"view_{v}.webp") for v in ("a","b")],"evidence_kind":"fixture_mock","profile_qualified":False,"observed_tags":[]}
                    self.persist_json(directory/"review.json",review)
                    self.store.finish(claim,stage="archive",changes={"preview_artifact_id":ids[0],"review_json":json.dumps(review),"local_retries":0})
                else:
                    self.store.finish(claim,stage="review",changes={"preview_artifact_id":ids[0],"local_retries":0})
            elif claim["stage"] == "archive":
                async with self.archive_lock:
                    await self.archive_asset(claim)
        except Exception as e:
            reason = f"{claim['stage']}_failed"
            if shared_storage_failure(e):
                self.storage_failed = True
                reason = "storage_unavailable"
                self.store.finish(claim,status="blocked",reason=reason)
            elif isinstance(e,SandboxError):
                reason = e.reason
                self.local_failure(claim,e.reason,retryable=e.reason != "sandbox_image_version_mismatch")
            elif isinstance(e, OSError):
                reason = "local_artifact_invalid"
                self.local_failure(claim,reason,retryable=claim['stage'] == 'render')
            else:
                self.local_failure(claim,reason)
            self.store.record_local_failure(claim, reason, e)
            self.loop_error = type(e).__name__

    async def archive_asset(self,claim):
        task = claim["task"]
        directory = Path(claim["build_path"])
        geometry = json.loads((directory/"geometry.json").read_text())
        claim["profile_qualified"] = self.config.is_qualified()
        configs = self.store.sample_configs(claim['sample_id'])
        if not configs or any(item['profile_hash'] != self.config.profile_hash() for item in configs):
            claim['profile_qualified'] = False
        claim["record_kind"] = task.get("record_kind","calibration")
        claim["versions"] = {**geometry.get("versions",{}),"rubric":RUBRIC_VERSION}
        claim.update(self.store.attempt_provenance(claim["sample_id"]))
        claim["observed_tags"] = claim["review"].get("observed_tags",[])
        model = json.loads((directory/"sample.json").read_text()).get("model",{})
        claim["generator_declared"] = {"tags":model.get("actual_tags",[])}
        features = await asyncio.to_thread(features_from_asset,directory)
        duplicate = self.store.variant_of(geometry["canonical_voxel_hash"],features,claim["lineage_group"])
        claim["is_unique"] = duplicate is None
        claim["dedup_features"] = features
        claim["runtime_config_snapshot"] = {'initial':self.store.one("SELECT * FROM config_snapshots WHERE config_hash=?",(claim.get("runtime_config_hash"),)), 'attempts':configs}
        if duplicate:
            claim["lineage_group"] = duplicate["lineage_group"]
            claim["duplicate_cluster_id"] = duplicate["sample_id"]
        claim["repair_pairs"] = self.repair_pairs(claim,directory)
        record = await asyncio.to_thread(self.archive.prepare,claim,directory,claim["review"])
        self.store.commit_asset(claim,record)
        self.archive.acknowledge(record["commit_id"])
        # Archive records carry paths relative to the data root. Resolve them
        # through the Store root so a restart never scans an unrelated cwd.
        for file in (self.store.root / record["path"]).rglob("*"):
            if file.is_file():
                self.store.register_artifact(claim["sample_id"],file,file.relative_to(self.store.root / record["path"]).as_posix(),digest(file))

    def repair_pairs(self,claim,directory):
        pairs = []
        for revision in range(1,claim["revision"]):
            before = self.work_dir(claim).parent/f"v{revision:04d}"
            if not (before/"repair_evidence.json").is_file() or not (before/"authored_source.py").is_file():
                continue
            report = json.loads((before/"repair_evidence.json").read_text())
            # Passing skeletons and infrastructure failures are not bad examples.
            if report.get('passed') is not False or 'violations' not in report:
                continue
            pairs.append({"before_revision":revision,"after_revision":claim["revision"],
                          "lineage_group":claim["lineage_group"],
                          "before_source":(before/"authored_source.py").read_text(),
                          "after_source":(directory/"authored_source.py").read_text(),
                          "before_geometry":report,
                          "after_geometry":json.loads((directory/"geometry.json").read_text()),
                          "before_source_sha256":digest(before/"authored_source.py"),
                          "after_source_sha256":digest(directory/"authored_source.py"),
                          "before_voxel_sha256":report.get("canonical_voxel_hash"),
                          "after_voxel_sha256":json.loads((directory/"geometry.json").read_text()).get("canonical_voxel_hash"),
                          "quality_contract":claim["task"]["quality_contract"],"feedback":report})
        return pairs
