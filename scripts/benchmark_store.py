"""Explicit synthetic load job; loopback only, temporary root, no model credentials.

Run: .venv/bin/python scripts/benchmark_store.py --output /tmp/voxlush-scale.json
"""
import argparse
import asyncio
import json
import platform
import resource
import statistics
import tempfile
import time
from pathlib import Path

from voxlush.core.config import Config, Endpoint
from voxlush.pipeline.scheduler import Scheduler
from voxlush.store.store import Store, dump
from voxlush.store.sqlite import sqlite_version
from voxlush.themes.planner import SEEDS, runtime_task, task_for


def rss_mb():
    for line in Path('/proc/self/status').read_text().splitlines():
        if line.startswith('VmRSS:'):
            return int(line.split()[1])/1024


def summary(values):
    ordered = sorted(values)
    return {'n':len(values),'median_ms':round(statistics.median(values),3),
            'p95_ms':round(ordered[min(len(ordered)-1,int(.95*len(ordered)))],3),
            'max_ms':round(max(values),3)}


async def run(args):
    with tempfile.TemporaryDirectory(prefix='voxlush-scale-') as root:
        store = Store(Path(root))
        campaign = store.create_campaign('history','Synthetic history',args.samples,10000000,512,{'natural':1})
        task = runtime_task(task_for(campaign,'geology',0,'fixture'))
        stamp = time.time()-86400
        started = time.perf_counter()
        with store.transaction() as db:
            db.executemany("INSERT INTO samples(sample_id,campaign_id,theme_seed_id,family_id,scene_type,task_json,stage,status,last_progress_at,updated_at,created_at,lineage_group) VALUES(?,'history',?,?,?,?,'author','rejected',?,?,?,?)",
                           ((f'h{i:07}',SEEDS[i%len(SEEDS)]['id'],SEEDS[i%len(SEEDS)]['family_id'],SEEDS[i%len(SEEDS)]['scene_type'],dump(task),stamp,stamp,stamp,f'h{i:07}') for i in range(args.samples)))
            db.executemany("INSERT INTO events(campaign_id,sample_id,kind,payload,created_at) VALUES('history',?,'synthetic','{}',?)",
                           ((f'h{i%args.samples:07}',stamp) for i in range(args.events)))
            db.executemany("INSERT INTO attempts(attempt_id,sample_id,campaign_id,revision,lease_token,role,endpoint_alias,status,billing_status,response_path,started_at,finished_at,occupancy,capacity_group,response_applied) VALUES(?,?,'history',1,'fixture','author','fixture','complete','actual','synthetic',?,?,0,'fixture',1)",
                           ((f'a{i:08}',f'h{i%args.samples:07}',stamp,stamp+1) for i in range(args.attempts)))
        seed_seconds = time.perf_counter()-started
        timings = {key:[] for key in ('overview','page','coverage','ready','idle_tick','loaded_tick','reserve','settle','response_apply')}
        memory = []
        cfg = Config(data_root=store.root,allow_live=False,author=Endpoint(base_url='http://127.0.0.1:1',model='fixture'))
        scheduler = Scheduler(store,cfg)
        for _ in range(args.rounds):
            for name,fn in (('overview',lambda:store.overview('history')),
                            ('page',lambda:store.list_samples('history',limit=50)),
                            ('coverage',lambda:store.coverage('history')),
                            ('ready',lambda:store.ready(['author','review'],limit=64))):
                start = time.perf_counter()
                fn()
                timings[name].append((time.perf_counter()-start)*1000)
            start = time.perf_counter()
            await scheduler.tick()
            timings['idle_tick'].append((time.perf_counter()-start)*1000)
            memory.append(rss_mb())
        await scheduler.client.close()

        active = peak = posts = 0
        async def handle(reader,writer):
            nonlocal active,peak,posts
            counted = False
            try:
                header = await reader.readuntil(b'\r\n\r\n')
                length = next(int(line.split(b':',1)[1]) for line in header.split(b'\r\n') if line.lower().startswith(b'content-length:'))
                await reader.readexactly(length)
                active += 1
                counted = True
                peak = max(peak,active)
                posts += 1
                number = posts
                await asyncio.sleep(.01+(number%5)*.005)
                if number%31 == 0:
                    body = b'{"error":"synthetic busy"}'
                    header = b'HTTP/1.1 429 Fixture\r\nRetry-After: 1\r\n'
                else:
                    body = b'data: {"choices":[{"delta":{"content":"x=1"},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n'
                    header = b'HTTP/1.1 200 Fixture\r\nContent-Type: text/event-stream\r\n'
                writer.write(header+f'Content-Length: {len(body)}\r\nConnection: close\r\n\r\n'.encode()+body)
                await writer.drain()
            finally:
                if counted:
                    active -= 1
                writer.close()
                await writer.wait_closed()

        server = await asyncio.start_server(handle,'127.0.0.1',0,backlog=1024)
        port = server.sockets[0].getsockname()[1]
        ladders = []
        for cap in (128,256,512):
            endpoint = Endpoint(base_url=f'http://127.0.0.1:{port}/v1',model='loopback-fixture',provider_cap=cap,total_timeout=120)
            cfg = Config(data_root=store.root,allow_live=True,global_api_cap=cap,author=endpoint)
            scheduler = Scheduler(store,cfg)
            scheduler.adaptive_cap = cap
            cid = f'load{cap}'
            c = store.create_campaign(cid,'Loopback load',cap+1,cap+1,cap,{'natural':1})
            store.set_campaign_state(cid,'running')
            peak,posts = 0,0
            for i in range(cap+1):
                store.add_sample(runtime_task(task_for(c,'geology',i,'fixture')))
            reserve = store.reserve
            def timed_reserve(*values):
                start = time.perf_counter()
                claim = reserve(*values)
                timings['reserve'].append((time.perf_counter()-start)*1000)
                return claim
            store.reserve = timed_reserve
            start = time.perf_counter()
            await scheduler.tick()
            timings['loaded_tick'].append((time.perf_counter()-start)*1000)
            store.reserve = reserve
            reserved = store.one('SELECT COUNT(*) n FROM attempts WHERE occupancy=1')['n']
            assert len(scheduler.active) == reserved == cap
            settle,consume = store.settle,scheduler.consume
            def timed_settle(*values):
                start = time.perf_counter()
                result = settle(*values)
                timings['settle'].append((time.perf_counter()-start)*1000)
                return result
            async def timed_consume(*values):
                start = time.perf_counter()
                result = await consume(*values)
                timings['response_apply'].append((time.perf_counter()-start)*1000)
                return result
            store.settle,scheduler.consume = timed_settle,timed_consume
            start = time.perf_counter()
            await asyncio.gather(*scheduler.active)
            store.settle = settle
            elapsed = time.perf_counter()-start
            remaining = store.one('SELECT COUNT(*) n FROM attempts WHERE occupancy=1')['n']
            assert posts == cap and peak <= cap and remaining == 0
            ladders.append({'cap':cap,'posts':posts,'reserved_peak':reserved,'server_peak':peak,
                            'dispatch_tick_ms':round(timings['loaded_tick'][-1],3),
                            'remaining_occupancy':remaining,'seconds':round(elapsed,3),
                            'rss_mb':round(rss_mb(),2)})
            store.set_campaign_state(cid,'paused')
            # End synthetic source fixtures without running geometry containers.
            with store.transaction() as db:
                db.execute("UPDATE samples SET status='rejected',reason_code='benchmark_teardown' WHERE campaign_id=?",(cid,))
            await scheduler.client.close()
        server.close()
        await server.wait_closed()
        start = time.perf_counter()
        assert store.recover() == []
        recovery_ms = (time.perf_counter()-start)*1000
        plans = {}
        for key,sql in {
            'occupancy':'SELECT COUNT(*) FROM attempts WHERE occupancy=1',
            'rpm':"SELECT COUNT(*),SUM(reserved_tokens) FROM attempts WHERE capacity_group='fixture' AND started_at>1",
            'coverage':"SELECT family_id,SUM(accepted),SUM(active) FROM seed_stats WHERE campaign_id='history' GROUP BY family_id",
        }.items():
            plans[key] = store.rows('EXPLAIN QUERY PLAN '+sql)
        result = {'schema_version':'voxlush.scale_fixture.v1','scope':'synthetic metadata and real loopback HTTP/SSE; no paid calls or quality evidence',
                  'python':platform.python_version(),'sqlite':sqlite_version,'machine':platform.machine(),
                  'rows':{'samples':args.samples,'events':args.events,'attempts':args.attempts},
                  'seed_seconds':round(seed_seconds,2),'timings':{k:summary(v) for k,v in timings.items()},
                  'rss_query_window_mb':{'min':round(min(memory),2),'max':round(max(memory),2),'last':round(memory[-1],2)},
                  'peak_rss_mb':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,2),
                  'recovery_ms':round(recovery_ms,3),'loopback_ladders':ladders,'query_plans':plans}
        store.close()
        Path(args.output).write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps(result,indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True)
    parser.add_argument('--samples',type=int,default=100000)
    parser.add_argument('--events',type=int,default=1000000)
    parser.add_argument('--attempts',type=int,default=300000)
    parser.add_argument('--rounds',type=int,default=60)
    asyncio.run(run(parser.parse_args()))
