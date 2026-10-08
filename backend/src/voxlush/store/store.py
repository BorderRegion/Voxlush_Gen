"""Single transactional writer. All durable state transitions are centralized here."""
from __future__ import annotations
import fcntl
import json
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from voxlush.store import sqlite as sqlite3
from voxlush.themes.planner import FAMILIES, family_targets

SCHEMA = """
CREATE TABLE IF NOT EXISTS campaigns (
 campaign_id TEXT PRIMARY KEY,name TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'idle',reason_code TEXT,
 target INTEGER NOT NULL,request_limit INTEGER NOT NULL,api_cap INTEGER NOT NULL,scene_weights TEXT NOT NULL,
 config_revision INTEGER NOT NULL DEFAULT 1,accepted_unique INTEGER NOT NULL DEFAULT 0,
 provisional_pass INTEGER NOT NULL DEFAULT 0,requests_used INTEGER NOT NULL DEFAULT 0,
 cost_known REAL NOT NULL DEFAULT 0,cost_unknown INTEGER NOT NULL DEFAULT 0,reserved_cost REAL NOT NULL DEFAULT 0,
 cost_limit REAL,sequence INTEGER NOT NULL DEFAULT 0,created_at REAL NOT NULL,updated_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS samples (
 sample_id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL REFERENCES campaigns(campaign_id),
 theme_seed_id TEXT NOT NULL,family_id TEXT NOT NULL,scene_type TEXT NOT NULL,task_json TEXT NOT NULL,
 stage TEXT NOT NULL,status TEXT NOT NULL,reason_code TEXT,revision INTEGER NOT NULL DEFAULT 1,
 source_path TEXT,source_hash TEXT,build_path TEXT,lease_token TEXT,lease_owner TEXT,lease_until REAL,
 next_ready_at REAL NOT NULL DEFAULT 0,last_progress_at REAL NOT NULL,updated_at REAL NOT NULL,
 created_at REAL NOT NULL,request_count INTEGER NOT NULL DEFAULT 0,geometry_repairs INTEGER NOT NULL DEFAULT 0,
 visual_repairs INTEGER NOT NULL DEFAULT 0,transport_retries INTEGER NOT NULL DEFAULT 0,
 error_fingerprint TEXT,identical_errors INTEGER NOT NULL DEFAULT 0,attempt_id TEXT,review_json TEXT,
 preview_artifact_id TEXT,lineage_group TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS samples_ready ON samples(status,next_ready_at,stage,updated_at);
CREATE INDEX IF NOT EXISTS samples_campaign ON samples(campaign_id,status,family_id);
CREATE INDEX IF NOT EXISTS samples_queue ON samples(campaign_id,stage,status,updated_at);
CREATE TABLE IF NOT EXISTS attempts (
 attempt_id TEXT PRIMARY KEY,sample_id TEXT NOT NULL,campaign_id TEXT NOT NULL,revision INTEGER NOT NULL,
 lease_token TEXT NOT NULL,role TEXT NOT NULL,endpoint_alias TEXT NOT NULL,status TEXT NOT NULL,
 reserved_cost REAL,settled_cost REAL,billing_status TEXT NOT NULL,response_path TEXT NOT NULL,
 result_json TEXT,started_at REAL NOT NULL,finished_at REAL,occupancy INTEGER NOT NULL DEFAULT 1,
 reserved_tokens INTEGER NOT NULL DEFAULT 0);
CREATE INDEX IF NOT EXISTS attempts_sample ON attempts(sample_id,started_at);
CREATE INDEX IF NOT EXISTS attempts_active ON attempts(status,occupancy,campaign_id);
CREATE TABLE IF NOT EXISTS commands (
 command_id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL,action TEXT NOT NULL,expected_config_revision INTEGER,
 payload TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'queued',reason TEXT,created_at REAL NOT NULL,applied_at REAL);
CREATE INDEX IF NOT EXISTS commands_pending ON commands(status,created_at);
CREATE TABLE IF NOT EXISTS events (
 event_id INTEGER PRIMARY KEY AUTOINCREMENT,campaign_id TEXT NOT NULL,sample_id TEXT,kind TEXT NOT NULL,
 payload TEXT NOT NULL,created_at REAL NOT NULL);
CREATE INDEX IF NOT EXISTS events_campaign ON events(campaign_id,event_id);
CREATE INDEX IF NOT EXISTS events_sample ON events(sample_id,event_id);
CREATE TABLE IF NOT EXISTS assets (
 asset_id TEXT PRIMARY KEY,sample_id TEXT NOT NULL,revision INTEGER NOT NULL,campaign_id TEXT NOT NULL,
 path TEXT NOT NULL,manifest_json TEXT NOT NULL,canonical_voxel_hash TEXT NOT NULL,annotation_hash TEXT,
 accepted_unique INTEGER NOT NULL DEFAULT 0,is_current INTEGER NOT NULL DEFAULT 1,status TEXT NOT NULL,
 lineage_group TEXT NOT NULL,created_at REAL NOT NULL,UNIQUE(sample_id,revision));
CREATE UNIQUE INDEX IF NOT EXISTS assets_exact ON assets(canonical_voxel_hash)
 WHERE accepted_unique=1 AND is_current=1;
CREATE INDEX IF NOT EXISTS assets_campaign ON assets(campaign_id,accepted_unique,sample_id);
CREATE TABLE IF NOT EXISTS dedup_features (
 asset_id TEXT PRIMARY KEY,translation_hash TEXT NOT NULL,rotation_hash TEXT NOT NULL,
 quantized_hash TEXT NOT NULL,features_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS dedup_rotation ON dedup_features(rotation_hash);
CREATE INDEX IF NOT EXISTS dedup_quantized ON dedup_features(quantized_hash);
CREATE TABLE IF NOT EXISTS artifacts (
 artifact_id TEXT PRIMARY KEY,sample_id TEXT,path TEXT NOT NULL,name TEXT NOT NULL,sha256 TEXT);
CREATE INDEX IF NOT EXISTS artifacts_sample ON artifacts(sample_id);
CREATE TABLE IF NOT EXISTS metrics_minute (
 campaign_id TEXT NOT NULL,minute INTEGER NOT NULL,accepted INTEGER NOT NULL DEFAULT 0,
 requests INTEGER NOT NULL DEFAULT 0,active_requests INTEGER NOT NULL DEFAULT 0,effective_cap INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(campaign_id,minute));
CREATE TABLE IF NOT EXISTS exports (
 export_id TEXT PRIMARY KEY,campaign_id TEXT NOT NULL,include_provisional INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL DEFAULT 'queued',path TEXT,result_json TEXT,reason TEXT,created_at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY,value TEXT NOT NULL);
"""

def dump(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)

class OwnerBusy(RuntimeError):
    pass

class Store:
    def __init__(self, data_root: Path, *, acquire_lock=True):
        self.root = Path(data_root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.owner = uuid.uuid4().hex
        self._mutex = threading.RLock()
        self._lock = None
        if acquire_lock:
            self._lock = (self.root / "owner.lock").open("a+")
            try:
                fcntl.flock(self._lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as e:
                self._lock.close()
                raise OwnerBusy("another Store/scheduler owns this data root") from e
        version = tuple(map(int, sqlite3.sqlite_version.split(".")))
        if version < (3, 51, 3) and version not in ((3, 50, 7), (3, 44, 6)):
            raise RuntimeError(f"SQLite {sqlite3.sqlite_version} lacks documented WAL-reset fix")
        self.db = sqlite3.connect(self.root / "runtime.db", isolation_level=None, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.execute("PRAGMA busy_timeout=5000")
        self.db.executescript(SCHEMA)
        self.db.execute("INSERT OR IGNORE INTO meta VALUES('schema','1')")
        if self.db.execute("SELECT value FROM meta WHERE key='schema'").fetchone()[0] != "1":
            raise RuntimeError("unsupported schema: migration required")
        self.db.execute("INSERT OR REPLACE INTO meta VALUES('sqlite_version',?)", (sqlite3.sqlite_version,))

    @contextmanager
    def transaction(self):
        with self._mutex:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield self.db
                self.db.execute("COMMIT")
            except BaseException:
                self.db.execute("ROLLBACK")
                raise

    def close(self):
        with self._mutex:
            self.db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self.db.close()
        if self._lock:
            self._lock.close()

    def rows(self, sql, parameters=()):
        with self._mutex:
            return [dict(row) for row in self.db.execute(sql, parameters)]

    def one(self, sql, parameters=()):
        r = self.rows(sql, parameters)
        return r[0] if r else None

    def _event(self, db, campaign_id, kind, payload, sample_id=None):
        db.execute("INSERT INTO events(campaign_id,sample_id,kind,payload,created_at) VALUES(?,?,?,?,?)",
                   (campaign_id, sample_id, kind, dump(payload), time.time()))

    def create_campaign(self, campaign_id, name, target, request_limit, api_cap, scene_weights,
                        cost_limit=None):
        now = time.time()
        family_targets(target, scene_weights)
        with self.transaction() as db:
            old = db.execute("SELECT * FROM campaigns WHERE campaign_id=?", (campaign_id,)).fetchone()
            if old:
                expected = (name, target, request_limit, api_cap, dump(scene_weights), cost_limit)
                actual = tuple(old[k] for k in ("name","target","request_limit","api_cap","scene_weights","cost_limit"))
                if expected != actual:
                    raise ValueError("campaign id reused with different configuration")
            else:
                db.execute("INSERT INTO campaigns(campaign_id,name,target,request_limit,api_cap,scene_weights,cost_limit,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (campaign_id,name,target,request_limit,api_cap,dump(scene_weights),cost_limit,now,now))
                self._event(db,campaign_id,"campaign_created",{"target":target})
        return self.campaign(campaign_id)

    def campaign(self, campaign_id):
        c = self.one("SELECT * FROM campaigns WHERE campaign_id=?", (campaign_id,))
        if c:
            c["scene_weights"] = json.loads(c["scene_weights"])
        return c

    def campaigns(self):
        return self.rows("SELECT * FROM campaigns ORDER BY created_at")

    def command(self, value):
        with self.transaction() as db:
            old = db.execute("SELECT * FROM commands WHERE command_id=?", (value["command_id"],)).fetchone()
            if old:
                if any(old[k] != value[k] for k in ("campaign_id","action","expected_config_revision")) or old["payload"] != dump(value.get("payload",{})):
                    raise ValueError("idempotency key reused with different command")
            else:
                db.execute("INSERT INTO commands(command_id,campaign_id,action,expected_config_revision,payload,created_at) VALUES(?,?,?,?,?,?)",
                    (value["command_id"],value["campaign_id"],value["action"],value["expected_config_revision"],dump(value.get("payload",{})),time.time()))
        return self.get_command(value["command_id"])

    def get_command(self, command_id):
        return self.one("SELECT command_id,status,reason,campaign_id,action FROM commands WHERE command_id=?",(command_id,))

    def apply_commands(self, sample_request_limit=8):
        with self.transaction() as db:
            for cmd in db.execute("SELECT * FROM commands WHERE status='queued' ORDER BY created_at LIMIT 100").fetchall():
                c = db.execute("SELECT * FROM campaigns WHERE campaign_id=?",(cmd["campaign_id"],)).fetchone()
                reason = None
                state = None
                if not c:
                    reason = "campaign_not_found"
                elif cmd["expected_config_revision"] != c["config_revision"]:
                    reason = "stale_config_revision"
                else:
                    action = cmd["action"]
                    states = {"start":"running","resume":"running","pause":"paused","drain":"draining","emergency_stop":"paused"}
                    if action in states:
                        state = states[action]
                    elif action == "set_cap":
                        cap = json.loads(cmd["payload"]).get("api_cap")
                        if not isinstance(cap,int) or isinstance(cap,bool) or not 0 <= cap <= 512:
                            reason = "invalid_cap"
                        else:
                            db.execute("UPDATE campaigns SET api_cap=?,config_revision=config_revision+1 WHERE campaign_id=?",(cap,c["campaign_id"]))
                    elif action == "retry":
                        payload = json.loads(cmd["payload"])
                        sample_id = payload.get("sample_id")
                        s = db.execute("SELECT * FROM samples WHERE sample_id=? AND campaign_id=?",
                                       (sample_id, c["campaign_id"])).fetchone() if isinstance(sample_id, str) else None
                        if not s:
                            reason = "sample_not_found"
                        elif c["state"] != "running":
                            reason = "campaign_not_running"
                        elif s["status"] not in ("rejected", "blocked", "deferred") or s["lease_token"]:
                            reason = "sample_not_retryable"
                        elif db.execute("SELECT 1 FROM attempts WHERE sample_id=? AND status IN ('running','outcome_unknown') LIMIT 1",
                                        (sample_id,)).fetchone():
                            reason = "attempt_outcome_unresolved"
                        elif c["requests_used"] >= c["request_limit"]:
                            reason = "campaign_request_budget_exhausted"
                        elif s["status"] == "rejected" and s["request_count"] >= sample_request_limit:
                            reason = "sample_request_budget_exhausted"
                        elif s["status"] == "blocked" and (s["stage"] not in ("build", "render", "archive") or
                                                              s["reason_code"] == "outcome_unknown"):
                            reason = "blocked_stage_not_retryable"
                        else:
                            stage = "author" if s["status"] == "rejected" else s["stage"]
                            revision = s["revision"] + int(s["status"] == "rejected")
                            clear = s["status"] == "rejected"
                            db.execute("UPDATE samples SET stage=?,status='ready',reason_code=NULL,revision=?,source_path=CASE WHEN ? THEN NULL ELSE source_path END,source_hash=CASE WHEN ? THEN NULL ELSE source_hash END,build_path=CASE WHEN ? THEN NULL ELSE build_path END,next_ready_at=0,updated_at=? WHERE sample_id=?",
                                       (stage, revision, int(clear), int(clear), int(clear), time.time(), sample_id))
                            self._event(db, c["campaign_id"], "sample_retry", {"command_id": cmd["command_id"],
                                "stage": stage, "revision": revision}, sample_id)
                    else:
                        reason = "unsupported_command"
                    if state:
                        db.execute("UPDATE campaigns SET state=?,reason_code=?,updated_at=? WHERE campaign_id=?",
                            (state,"emergency_stop" if action == "emergency_stop" else None,time.time(),c["campaign_id"]))
                db.execute("UPDATE commands SET status=?,reason=?,applied_at=? WHERE command_id=?",
                    ("rejected" if reason else "applied",reason,time.time(),cmd["command_id"]))
                self._event(db,cmd["campaign_id"],"command",{"command_id":cmd["command_id"],"reason":reason,"state":state})

    def set_campaign_state(self, campaign_id, state, reason=None):
        with self.transaction() as db:
            db.execute("UPDATE campaigns SET state=?,reason_code=?,updated_at=? WHERE campaign_id=?",
                       (state,reason,time.time(),campaign_id))
            self._event(db,campaign_id,"campaign_state",{"state":state,"reason_code":reason})

    def add_sample(self, task, source_path=None):
        now = time.time()
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO samples(sample_id,campaign_id,theme_seed_id,family_id,scene_type,task_json,stage,status,source_path,last_progress_at,updated_at,created_at,lineage_group) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (task["sample_id"],task["campaign_id"],task["theme_seed_id"],task.get("theme_family_id","unknown"),task["scene_type"],dump(task),"build" if source_path else "author","ready",source_path,now,now,now,task.get("lineage_group",task["sample_id"])))
            if db.execute("SELECT changes()").fetchone()[0]:
                db.execute("UPDATE campaigns SET sequence=sequence+1 WHERE campaign_id=?",(task["campaign_id"],))
                self._event(db,task["campaign_id"],"sample_created",{},task["sample_id"])
        return self.sample(task["sample_id"])

    def sample(self, sample_id):
        r = self.one("SELECT * FROM samples WHERE sample_id=?",(sample_id,))
        if r:
            r["task"] = json.loads(r.pop("task_json"))
            r["review"] = json.loads(r["review_json"]) if r.get("review_json") else None
            for key in ("source_path", "build_path"):
                if r.get(key) and not Path(r[key]).is_absolute():
                    r[key] = str(self.root / r[key])
        return r

    def list_samples(self, campaign_id=None, cursor=None, limit=50, status=None, stage=None, q=None):
        where = ["sample_id>?"]
        args = [cursor or ""]
        for column,value in (("campaign_id",campaign_id),("status",status),("stage",stage)):
            if value:
                where.append(column+"=?")
                args.append(value)
        if q:
            where.append("(sample_id LIKE ? OR theme_seed_id LIKE ?)")
            args.extend([q[:100]+"%",q[:100]+"%"])
        limit = max(1,min(limit,100))
        args.append(limit+1)
        rows = self.rows("SELECT sample_id,campaign_id,stage,status,reason_code,theme_seed_id,scene_type,revision,updated_at,preview_artifact_id FROM samples WHERE "+" AND ".join(where)+" ORDER BY sample_id LIMIT ?",args)
        return {"items":rows[:limit],"next_cursor":rows[limit-1]["sample_id"] if len(rows)>limit else None}

    def ready(self, stages, limit=32, allow_network=True):
        marks = ",".join("?" for _ in stages)
        return self.rows(f"SELECT s.* FROM samples s JOIN campaigns c USING(campaign_id) WHERE s.status IN ('ready','deferred') AND s.next_ready_at<=? AND s.stage IN ({marks}) AND c.state IN ('running','draining','completed','blocked','degraded') ORDER BY s.updated_at LIMIT ?",
                         [time.time(),*stages,min(limit,1024)])

    def claim(self, sample_id, revision, lease_seconds=600):
        token = uuid.uuid4().hex
        now = time.time()
        with self.transaction() as db:
            db.execute("UPDATE samples SET status='running',lease_token=?,lease_owner=?,lease_until=?,updated_at=? WHERE sample_id=? AND revision=? AND status IN ('ready','deferred') AND next_ready_at<=? AND campaign_id IN (SELECT campaign_id FROM campaigns WHERE state IN ('running','draining','completed','blocked','degraded'))",
                (token,self.owner,now+lease_seconds,now,sample_id,revision,now))
            if not db.execute("SELECT changes()").fetchone()[0]:
                return None
        return self.sample(sample_id)

    def reserve(self, sample_id, revision, endpoint, hard_cap, sample_limit):
        now = time.time()
        token, aid = uuid.uuid4().hex,uuid.uuid4().hex
        with self.transaction() as db:
            s = db.execute("SELECT * FROM samples WHERE sample_id=?",(sample_id,)).fetchone()
            if not s or s["revision"] != revision or s["status"] not in ("ready","deferred") or s["next_ready_at"]>now:
                return None
            c = db.execute("SELECT * FROM campaigns WHERE campaign_id=?",(s["campaign_id"],)).fetchone()
            if c["state"] != "running":
                return None
            active = db.execute("SELECT COALESCE(SUM(occupancy),0) FROM attempts").fetchone()[0]
            route_active = db.execute("SELECT COALESCE(SUM(occupancy),0) FROM attempts WHERE endpoint_alias=?",(endpoint.alias,)).fetchone()[0]
            campaign_active = db.execute("SELECT COALESCE(SUM(occupancy),0) FROM attempts WHERE campaign_id=?",(s["campaign_id"],)).fetchone()[0]
            if active >= hard_cap or campaign_active >= c["api_cap"] or route_active >= endpoint.provider_cap:
                return None
            if c["requests_used"] >= c["request_limit"] or s["request_count"] >= sample_limit:
                return None
            reserve_cost = endpoint.cost_upper_bound
            if c["cost_limit"] is not None and (reserve_cost is None or c["cost_known"]+c["reserved_cost"]+reserve_cost > c["cost_limit"]):
                db.execute("UPDATE campaigns SET state='blocked',reason_code='cost_budget_exhausted' WHERE campaign_id=?",(s["campaign_id"],))
                self._event(db,s["campaign_id"],"campaign_state",{"state":"blocked","reason_code":"cost_budget_exhausted"})
                return None
            recent = db.execute("SELECT COUNT(*),COALESCE(SUM(reserved_tokens),0) FROM attempts WHERE started_at>? AND endpoint_alias=?",(now-60,endpoint.alias)).fetchone()
            if (endpoint.rpm and recent[0]>=endpoint.rpm) or (endpoint.tpm and recent[1]+endpoint.reservation_tokens>endpoint.tpm):
                return None
            path = f"runs/{s['campaign_id']}/responses/{aid}.json"
            db.execute("INSERT INTO attempts(attempt_id,sample_id,campaign_id,revision,lease_token,role,endpoint_alias,status,reserved_cost,billing_status,response_path,started_at,reserved_tokens) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (aid,sample_id,s["campaign_id"],revision,token,s["stage"],endpoint.alias,"running",reserve_cost,"reserved",path,now,endpoint.reservation_tokens))
            db.execute("UPDATE campaigns SET requests_used=requests_used+1,reserved_cost=reserved_cost+? WHERE campaign_id=?",(reserve_cost or 0,s["campaign_id"]))
            db.execute("UPDATE samples SET status='running',lease_token=?,lease_owner=?,lease_until=?,attempt_id=?,request_count=request_count+1,updated_at=? WHERE sample_id=?",
                (token,self.owner,now+endpoint.total_timeout+30,aid,now,sample_id))
            minute = int(now//60)*60
            db.execute("INSERT INTO metrics_minute(campaign_id,minute,requests) VALUES(?,?,1) ON CONFLICT(campaign_id,minute) DO UPDATE SET requests=requests+1",(s["campaign_id"],minute))
            self._event(db,s["campaign_id"],"reserved",{"attempt_id":aid,"role":s["stage"]},sample_id)
        result = self.sample(sample_id)
        result["attempt"] = self.one("SELECT * FROM attempts WHERE attempt_id=?",(aid,))
        return result

    def settle(self, attempt_id, result):
        with self.transaction() as db:
            a = db.execute("SELECT * FROM attempts WHERE attempt_id=?",(attempt_id,)).fetchone()
            if not a or a["status"] != "running":
                return False
            unknown = result.get("error_category") == "outcome_unknown"
            cost = result.get("cost")
            release = 0 if cost is None else a["reserved_cost"] or 0
            billing = "unknown_reserved" if cost is None else "actual"
            summary = {k:v for k,v in result.items() if k not in {"raw", "content"}}
            db.execute("UPDATE attempts SET status=?,occupancy=?,settled_cost=?,billing_status=?,result_json=?,finished_at=? WHERE attempt_id=?",
                ("outcome_unknown" if unknown else "complete",int(unknown),cost,billing,dump(summary),time.time(),attempt_id))
            db.execute("UPDATE campaigns SET cost_known=cost_known+?,cost_unknown=cost_unknown+?,reserved_cost=MAX(0,reserved_cost-?) WHERE campaign_id=?",
                (cost or 0,int(cost is None),release,a["campaign_id"]))
            self._event(db,a["campaign_id"],"settled",{"attempt_id":attempt_id,"billing_status":billing},a["sample_id"])
            return True

    def finish(self, claim, *, stage=None, status="ready", reason=None, changes=None, delay=0):
        allowed = {"source_path","source_hash","build_path","review_json","geometry_repairs","visual_repairs","transport_retries","error_fingerprint","identical_errors","revision","preview_artifact_id"}
        changes = changes or {}
        changes = dict(changes)
        for key in ("source_path", "build_path"):
            if changes.get(key):
                path = Path(changes[key])
                if path.is_absolute():
                    changes[key] = path.relative_to(self.root).as_posix()
        if changes.keys() - allowed:
            raise ValueError("unsupported transition fields")
        updates = {"stage":stage or claim["stage"],"status":status,"reason_code":reason,"lease_token":None,
            "lease_owner":None,"lease_until":None,"updated_at":time.time(),"last_progress_at":time.time(),"next_ready_at":time.time()+delay,**changes}
        with self.transaction() as db:
            columns = ",".join(k+"=?" for k in updates)
            db.execute("UPDATE samples SET "+columns+" WHERE sample_id=? AND revision=? AND lease_token=?",
                [*updates.values(),claim["sample_id"],claim["revision"],claim["lease_token"]])
            ok = bool(db.execute("SELECT changes()").fetchone()[0])
            if ok:
                self._event(db,claim["campaign_id"],"transition",{"stage":updates["stage"],"status":status,"reason_code":reason},claim["sample_id"])
        return ok

    def recover(self):
        # Only unresolved indexed records; never reconstruct finalized arrays.
        running = self.rows("SELECT a.* FROM attempts a JOIN samples s ON s.sample_id=a.sample_id AND s.lease_token=a.lease_token WHERE s.status='running' AND s.stage IN ('author','refine','review')")
        replay = []
        for a in running:
            response = self.root / a["response_path"]
            if response.is_file():
                try:
                    result = json.loads(response.read_text())
                    if not isinstance(result,dict):
                        raise ValueError("invalid durable response")
                    if a["status"] == "running":
                        self.settle(a["attempt_id"],result)
                    s = self.sample(a["sample_id"])
                    if s and s["lease_token"] == a["lease_token"]:
                        replay.append((s,result))
                except (OSError,ValueError):
                    self.settle(a["attempt_id"],{"error_category":"outcome_unknown","cost":None})
                    s = self.sample(a["sample_id"])
                    if s:
                        self.finish(s,status="blocked",reason="outcome_unknown")
            else:
                self.settle(a["attempt_id"],{"error_category":"outcome_unknown","cost":None})
                s = self.sample(a["sample_id"])
                if s:
                    self.finish(s,status="blocked",reason="outcome_unknown")
        with self.transaction() as db:
            db.execute("UPDATE samples SET status='ready',lease_token=NULL,lease_owner=NULL,lease_until=NULL,reason_code='recovered_local' WHERE status='running' AND stage IN ('build','render','archive')")
            self._event(db,"system","recovery",{"responses":len(replay),"unknown":len(running)-len(replay)})
        return replay

    def resume_visual_reviews(self):
        with self.transaction() as db:
            waiting = db.execute("SELECT campaign_id,COUNT(*) n FROM samples WHERE stage='review' AND status='awaiting_review' AND reason_code='awaiting_visual' AND lease_token IS NULL GROUP BY campaign_id").fetchall()
            if not waiting:
                return
            db.execute("UPDATE samples SET status='ready',reason_code=NULL,next_ready_at=0,updated_at=?,last_progress_at=? WHERE stage='review' AND status='awaiting_review' AND reason_code='awaiting_visual' AND lease_token IS NULL",(time.time(),time.time()))
            for row in waiting:
                self._event(db,row["campaign_id"],"visual_endpoint_available",{"reviews_resumed":row["n"]})

    def rebase_paths(self, old_root, new_root=None):
        """Upgrade legacy absolute local references after a restore, centrally."""
        old_root = Path(old_root)
        with self.transaction() as db:
            for row in db.execute("SELECT sample_id,source_path,build_path FROM samples WHERE source_path IS NOT NULL OR build_path IS NOT NULL").fetchall():
                for key in ("source_path", "build_path"):
                    if row[key] and Path(row[key]).is_absolute():
                        relative = Path(row[key]).relative_to(old_root).as_posix()
                        db.execute(f"UPDATE samples SET {key}=? WHERE sample_id=?",(relative,row["sample_id"]))

    def attempt_provenance(self, sample_id):
        attempts = self.rows("SELECT * FROM attempts WHERE sample_id=? ORDER BY started_at",(sample_id,))
        results = [json.loads(a["result_json"] or "{}") for a in attempts]
        usage = {"model_requests":len(attempts),"cost_known":sum(a["settled_cost"] or 0 for a in attempts) if attempts else None,
                 "cost_unknown_reserved":sum(a["reserved_cost"] or 0 for a in attempts if a["settled_cost"] is None) if attempts else None,
                 "currency":None}
        for key, token in (("input_tokens","prompt_tokens"),("output_tokens","completion_tokens")):
            values = [r.get("usage",{}).get(token) for r in results]
            usage[key] = sum(values) if values and all(type(v) is int for v in values) else None
        values = [r.get("usage",{}).get("completion_tokens_details",{}).get("reasoning_tokens") for r in results]
        usage["reasoning_tokens"] = sum(values) if values and all(type(v) is int for v in values) else None
        return {"usage":usage,"request_refs":[a["response_path"] for a in attempts],
                "endpoint_alias":results[-1].get("endpoint_alias") if results else None,
                "requested_model":results[-1].get("requested_model") if results else None,
                "reported_model":results[-1].get("reported_model") if results else None}

    def dedup_candidates(self, features):
        return self.rows("SELECT a.sample_id,a.lineage_group,a.canonical_voxel_hash FROM dedup_features f JOIN assets a USING(asset_id) WHERE f.rotation_hash=? OR f.quantized_hash=? LIMIT 32",
                         (features["rotation_occupancy_sha256"],features["geometry_quant_sha256"]))

    def register_dedup(self, asset_id, features):
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO dedup_features VALUES(?,?,?,?,?)",(asset_id,features["translation_occupancy_sha256"],features["rotation_occupancy_sha256"],features["geometry_quant_sha256"],dump(features)))

    @contextmanager
    def backup_snapshot(self):
        with self._mutex:
            if self.one("SELECT COUNT(*) n FROM campaigns WHERE state='running'")["n"] or self.one("SELECT COUNT(*) n FROM samples WHERE status='running' OR lease_token IS NOT NULL")["n"] or self.one("SELECT COUNT(*) n FROM attempts WHERE status='running'")["n"]:
                raise ValueError("pause/drain and finish active work before consistent backup")
            yield

    def asset_exists(self, geometry_hash):
        return self.one("SELECT * FROM assets WHERE canonical_voxel_hash=? AND is_current=1 ORDER BY accepted_unique DESC LIMIT 1",(geometry_hash,))

    def commit_asset(self, claim, record):
        with self.transaction() as db:
            existing = db.execute("SELECT * FROM assets WHERE sample_id=? AND revision=?",(claim["sample_id"],claim["revision"])).fetchone()
            if existing:
                return dict(existing)
            s = db.execute("SELECT * FROM samples WHERE sample_id=? AND revision=? AND lease_token=?",(claim["sample_id"],claim["revision"],claim["lease_token"])).fetchone()
            if not s:
                raise ValueError("stale archive lease")
            accepted = bool(record.get("accepted_unique"))
            duplicate = db.execute("SELECT sample_id FROM assets WHERE canonical_voxel_hash=? AND is_current=1 LIMIT 1",(record["canonical_voxel_hash"],)).fetchone()
            if duplicate:
                accepted = False
                status,reason = "rejected","duplicate"
            else:
                status,reason = ("accepted",None) if accepted else ("provisional_pass","unqualified_model_profile")
            aid = f"{claim['sample_id']}:v{claim['revision']:04d}"
            manifest = record["manifest_json"]
            if isinstance(manifest,str):
                manifest = json.loads(manifest)
            db.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (aid,claim["sample_id"],claim["revision"],claim["campaign_id"],str(record["path"]),dump(manifest),record["canonical_voxel_hash"],record.get("annotation_hash"),int(accepted),1,status,claim["lineage_group"],time.time()))
            db.execute("UPDATE samples SET status=?,reason_code=?,lease_token=NULL,lease_owner=NULL,lease_until=NULL,updated_at=? WHERE sample_id=?",
                (status,reason,time.time(),claim["sample_id"]))
            counter = "accepted_unique" if accepted else "provisional_pass" if status == "provisional_pass" else None
            if counter:
                db.execute(f"UPDATE campaigns SET {counter}={counter}+1 WHERE campaign_id=?",(claim["campaign_id"],))
            if accepted:
                minute = int(time.time()//60)*60
                db.execute("INSERT INTO metrics_minute(campaign_id,minute,accepted) VALUES(?,?,1) ON CONFLICT(campaign_id,minute) DO UPDATE SET accepted=accepted+1",(claim["campaign_id"],minute))
            self._event(db,claim["campaign_id"],"archive_commit",{"asset_id":aid,"accepted_unique":accepted,"duplicate_of":duplicate[0] if duplicate else None},claim["sample_id"])
        return self.one("SELECT * FROM assets WHERE asset_id=?",(aid,))

    def register_artifact(self,sample_id,path,name,sha256=None):
        path = Path(path).resolve()
        relative = str(path.relative_to(self.root))
        aid = uuid.uuid5(uuid.NAMESPACE_URL,relative).hex
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO artifacts VALUES(?,?,?,?,?)",(aid,sample_id,relative,name,sha256))
        return aid

    def iter_assets(self,campaign_id,include_provisional=False):
        cursor = ""
        while True:
            rows = self.rows("SELECT * FROM assets WHERE campaign_id=? AND is_current=1 AND (accepted_unique=1 OR (? AND status='provisional_pass')) AND sample_id>? ORDER BY sample_id LIMIT 128",
                            (campaign_id,int(include_provisional),cursor))
            if not rows:
                break
            for r in rows:
                r["manifest_json"] = json.loads(r["manifest_json"])
                yield r
            cursor = rows[-1]["sample_id"]

    def coverage(self,campaign_id):
        c = self.campaign(campaign_id)
        if not c:
            return {"items":[],"totals":{}}
        targets = family_targets(c["target"],c["scene_weights"])
        stats = {r["family_id"]:r for r in self.rows("SELECT family_id,SUM(status='accepted') accepted,SUM(status IN ('ready','running','deferred','awaiting_review')) active,SUM(status='rejected' AND COALESCE(reason_code,'')!='duplicate') rejected,SUM(COALESCE(reason_code,'')='duplicate') duplicate FROM samples WHERE campaign_id=? GROUP BY family_id",(campaign_id,))}
        items = []
        for fid,f in FAMILIES.items():
            s = stats.get(fid,{})
            accepted = s.get("accepted",0)
            items.append({"family_id":fid,"name":f["name_zh"],"scene_type":f["scene_type"],"target":targets.get(fid,0),"accepted":accepted,"active":s.get("active",0),"rejected":s.get("rejected",0),"duplicate":s.get("duplicate",0),"debt":max(0,targets.get(fid,0)-accepted),"qualification":"unqualified","reason_code":"unqualified_model_profile"})
        return {"items":items,"totals":{k:sum(i[k] for i in items) for k in ("target","accepted","active","rejected","duplicate","debt")}}

    def overview(self,campaign_id,effective_cap=0):
        c = self.campaign(campaign_id)
        if not c:
            return None
        queues = self.rows("SELECT stage,SUM(status IN ('ready','deferred')) ready,SUM(status='running') running,MIN(CASE WHEN status IN ('ready','deferred') THEN updated_at END) oldest FROM samples WHERE campaign_id=? AND status IN ('ready','running','deferred') GROUP BY stage",(campaign_id,))
        for q in queues:
            q["oldest_wait_seconds"] = max(0,time.time()-(q.pop("oldest") or time.time()))
        active = self.one("SELECT SUM(status='running') active,SUM(status='outcome_unknown' AND occupancy=1) unknown FROM attempts WHERE campaign_id=?",(campaign_id,))
        now = time.time()
        window = min(3600,max(0,now-c["created_at"]))
        n = self.one("SELECT COUNT(*) n FROM assets WHERE campaign_id=? AND accepted_unique=1 AND created_at>?",(campaign_id,now-3600))["n"]
        return {"campaign_id":campaign_id,"state":c["state"],"reason_code":c["reason_code"],"target":c["target"],"accepted_unique":c["accepted_unique"],"provisional_pass":c["provisional_pass"],"active_requests":active["active"] or 0,"unknown_occupancy":active["unknown"] or 0,"effective_cap":effective_cap,"configured_cap":c["api_cap"],"requests_used":c["requests_used"],"requests_limit":c["request_limit"],"cost_known":c["cost_known"] if c["requests_used"] and c["cost_unknown"] == 0 else None,"cost_unknown":c["cost_unknown"],"reserved_cost":c["reserved_cost"],"accepted_per_hour":n*3600/window if window>=60 and n else None,"window_seconds":window,"queues":queues,"event_cursor":self.one("SELECT COALESCE(MAX(event_id),0) n FROM events WHERE campaign_id=?",(campaign_id,))["n"],"server_time":now,"schema_version":"voxlush.events.v1"}

    def metric_snapshot(self,campaign_id,cap):
        active = self.one("SELECT COUNT(*) n FROM attempts WHERE status='running' AND campaign_id=?",(campaign_id,))["n"]
        with self.transaction() as db:
            db.execute("INSERT INTO metrics_minute(campaign_id,minute,active_requests,effective_cap) VALUES(?,?,?,?) ON CONFLICT(campaign_id,minute) DO UPDATE SET active_requests=excluded.active_requests,effective_cap=excluded.effective_cap",(campaign_id,int(time.time()//60)*60,active,cap))

    def create_export(self,export_id,campaign_id,include_provisional):
        with self.transaction() as db:
            old = db.execute("SELECT * FROM exports WHERE export_id=?",(export_id,)).fetchone()
            if old and (old["campaign_id"] != campaign_id or old["include_provisional"] != int(include_provisional)):
                raise ValueError("export id reused with different input")
            db.execute("INSERT OR IGNORE INTO exports(export_id,campaign_id,include_provisional,created_at) VALUES(?,?,?,?)",(export_id,campaign_id,int(include_provisional),time.time()))
        return self.one("SELECT * FROM exports WHERE export_id=?",(export_id,))

    def finish_export(self,export_id,status,result=None,reason=None,path=None):
        with self.transaction() as db:
            db.execute("UPDATE exports SET status=?,result_json=?,reason=?,path=? WHERE export_id=?",(status,dump(result) if result else None,reason,str(path) if path else None,export_id))

    def backup_db(self,destination):
        with self._mutex:
            target = sqlite3.connect(str(destination))
            try:
                self.db.backup(target)
            finally:
                target.close()

    def register_legacy(self,record):
        sid = record["sample_id"]
        task = record.get("task") or {"sample_id":sid,"campaign_id":"legacy","theme_seed_id":"legacy","scene_type":"architecture","quality_contract":"legacy","lineage_group":sid}
        task["campaign_id"] = "legacy"
        self.create_campaign("legacy","Legacy unverified",1,1,0,{"architecture":1})
        if self.sample(sid):
            return False
        self.add_sample(task)
        with self.transaction() as db:
            db.execute("UPDATE samples SET status='blocked',reason_code='legacy_complete_unverified' WHERE sample_id=?",(sid,))
            self._event(db,"legacy","legacy_import",record,sid)
        return True
