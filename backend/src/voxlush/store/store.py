"""Single transactional writer. All durable state transitions are centralized here."""
from __future__ import annotations
import fcntl
import hashlib
import json
import threading
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from voxlush.store import sqlite as sqlite3
from voxlush.themes.planner import FAMILIES, SEEDS, apportion, family_targets
from voxlush.themes.composition import DEFAULT_WEIGHTS, MODES, export_selection, requested_mode, scene_weights as composition_scene_weights, validate_weights
from voxlush.store.migrations import migrate
from voxlush.inference import execution_state

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
        migrate(self.db)
        self.runtime_config_hash = None
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

    def bind_config(self, config):
        snapshot = config.snapshot()
        key = hashlib.sha256(dump(snapshot).encode()).hexdigest()
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO config_snapshots VALUES(?,?,?,?)", (key,config.profile_hash(),dump(snapshot),time.time()))
            self.runtime_config_hash = key
            for row in db.execute("SELECT * FROM campaigns").fetchall():
                if row['runtime_config_hash'] != key:
                    db.execute("UPDATE campaigns SET runtime_config_hash=?,config_revision=config_revision+? WHERE campaign_id=?",
                               (key,int(row['runtime_config_hash'] is not None),row['campaign_id']))
                    self._config_history(db,row['campaign_id'])
            # Role disambiguates old aliases shared by author and visual endpoints.
            for endpoint, roles in ((config.author, ('author','refine')), (config.visual, ('review',))):
                if endpoint:
                    marks = ','.join('?' for _ in roles)
                    db.execute(f"UPDATE attempts SET capacity_group=? WHERE capacity_group=? AND role IN ({marks})",
                               (endpoint.capacity_key(),'legacy:'+endpoint.alias,*roles))

    def _config_history(self, db, campaign_id):
        c = db.execute("SELECT * FROM campaigns WHERE campaign_id=?",(campaign_id,)).fetchone()
        if c['runtime_config_hash']:
            settings = {k:c[k] for k in ('target','request_limit','api_cap','scene_weights','cost_limit','composition_weights')}
            db.execute("INSERT OR IGNORE INTO config_history VALUES(?,?,?,?,?)",
                       (campaign_id,c['config_revision'],c['runtime_config_hash'],dump(settings),time.time()))
            self._event(db,campaign_id,'config_revision',{'revision':c['config_revision'],'config_hash':c['runtime_config_hash']})

    def create_campaign(self, campaign_id, name, target, request_limit, api_cap, scene_weights,
                        cost_limit=None, composition_weights=None):
        now = time.time()
        family_targets(target, scene_weights)
        weights = validate_weights(DEFAULT_WEIGHTS if composition_weights is None else composition_weights)
        for scene, weight in scene_weights.items():
            if weight > 0:
                composition_scene_weights(weights, scene)
        with self.transaction() as db:
            old = db.execute("SELECT * FROM campaigns WHERE campaign_id=?", (campaign_id,)).fetchone()
            if old:
                expected = (name, target, request_limit, api_cap, dump(scene_weights), cost_limit)
                actual = tuple(old[k] for k in ("name","target","request_limit","api_cap","scene_weights","cost_limit"))
                if expected != actual:
                    raise ValueError("campaign id reused with different configuration")
                if old['composition_weights'] is not None and json.loads(old['composition_weights']) != weights:
                    raise ValueError('campaign id reused with different composition weights')
            else:
                db.execute("INSERT INTO campaigns(campaign_id,name,target,request_limit,api_cap,scene_weights,cost_limit,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (campaign_id,name,target,request_limit,api_cap,dump(scene_weights),cost_limit,now,now))
                self._event(db,campaign_id,"campaign_created",{"target":target})
                db.execute("UPDATE campaigns SET runtime_config_hash=? WHERE campaign_id=?",(self.runtime_config_hash,campaign_id))
                db.execute('UPDATE campaigns SET composition_weights=? WHERE campaign_id=?',(dump(weights),campaign_id))
                self._config_history(db,campaign_id)
        return self.campaign(campaign_id)

    def campaign(self, campaign_id):
        c = self.one("SELECT * FROM campaigns WHERE campaign_id=?", (campaign_id,))
        if c:
            c["scene_weights"] = json.loads(c["scene_weights"])
            c['composition_weights'] = json.loads(c['composition_weights']) if c['composition_weights'] else None
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
                            self._config_history(db,c['campaign_id'])
                    elif action == "reconcile_execution":
                        payload = json.loads(cmd['payload'])
                        try:
                            self._reconcile_execution(db,c['campaign_id'],payload.get('attempt_id'),payload.get('outcome'),payload.get('evidence'))
                        except ValueError as exc:
                            reason = str(exc)
                    elif action == "retry":
                        payload = json.loads(cmd["payload"])
                        sample_id = payload.get("sample_id")
                        s = db.execute("SELECT * FROM samples WHERE sample_id=? AND campaign_id=?",
                                       (sample_id, c["campaign_id"])).fetchone() if isinstance(sample_id, str) else None
                        if not s:
                            reason = "sample_not_found"
                        elif c["state"] != "running":
                            reason = "campaign_not_running"
                        elif s["reason_code"] == "phase_recovery_required":
                            reason = "phase_recovery_required"
                        elif s["status"] not in ("rejected", "blocked", "deferred") or s["lease_token"]:
                            reason = "sample_not_retryable"
                        elif db.execute("SELECT 1 FROM attempts WHERE attempt_id=? AND status='complete' AND response_applied=0",(s['attempt_id'],)).fetchone():
                            db.execute("UPDATE samples SET reason_code='response_pending',next_ready_at=0 WHERE sample_id=?",(sample_id,))
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

    def restore_shutdown_campaigns(self):
        """Only older service shutdowns wrote this unambiguous reason.

        New owners retain campaign state. User drain/pause never has this reason;
        queued user controls must be applied before calling this recovery method.
        """
        with self.transaction() as db:
            for c in db.execute("SELECT campaign_id FROM campaigns WHERE state='draining' AND reason_code='shutdown'").fetchall():
                db.execute("UPDATE campaigns SET state='running',reason_code=NULL,updated_at=? WHERE campaign_id=?", (time.time(),c['campaign_id']))
                self._event(db,c['campaign_id'],'shutdown_recovered',{'state':'running'})

    def resume_resource_tasks(self):
        """A successful local probe requeues unchanged work, retaining retry limits."""
        with self.transaction() as db:
            rows = db.execute("SELECT sample_id,campaign_id FROM samples WHERE status IN ('deferred','blocked') AND stage IN ('build','render') AND reason_code IN ('sandbox_unavailable','sandbox_image_version_mismatch') AND local_retries<=3 AND lease_token IS NULL").fetchall()
            for row in rows:
                db.execute("UPDATE samples SET status='ready',reason_code='resource_recovered',next_ready_at=0,updated_at=? WHERE sample_id=?", (time.time(),row['sample_id']))
                self._event(db,row['campaign_id'],'resource_recovered',{},row['sample_id'])

    def record_local_failure(self, claim, reason, error):
        with self.transaction() as db:
            self._event(db,claim['campaign_id'],'local_failure',
                        {'reason':reason,'exception':type(error).__name__,
                         'errno':getattr(error,'errno',None),'detail':str(error)[-2000:]},claim['sample_id'])

    def set_campaign_state(self, campaign_id, state, reason=None):
        with self.transaction() as db:
            db.execute("UPDATE campaigns SET state=?,reason_code=?,updated_at=? WHERE campaign_id=?",
                       (state,reason,time.time(),campaign_id))
            self._event(db,campaign_id,"campaign_state",{"state":state,"reason_code":reason})

    def add_sample(self, task, source_path=None):
        now = time.time()
        mode = requested_mode(task)
        with self.transaction() as db:
            db.execute("INSERT OR IGNORE INTO samples(sample_id,campaign_id,theme_seed_id,family_id,scene_type,task_json,stage,status,source_path,last_progress_at,updated_at,created_at,lineage_group) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (task["sample_id"],task["campaign_id"],task["theme_seed_id"],task.get("theme_family_id","unknown"),task["scene_type"],dump(task),"build" if source_path else "author","ready",source_path,now,now,now,task.get("lineage_group",task["sample_id"])))
            if db.execute("SELECT changes()").fetchone()[0]:
                db.execute("UPDATE campaigns SET sequence=sequence+1 WHERE campaign_id=?",(task["campaign_id"],))
                db.execute("UPDATE samples SET runtime_config_hash=?,creative_phase=?,composition_mode=? WHERE sample_id=?",
                           (self.runtime_config_hash,'skeleton' if task.get('generation_mode') == 'two_stage' else 'final',mode,task['sample_id']))
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

    def list_samples(self, campaign_id=None, cursor=None, limit=50, status=None, stage=None, q=None, composition_mode=None):
        where = ["sample_id>?"]
        args = [cursor or ""]
        for column,value in (("campaign_id",campaign_id),("status",status),("stage",stage),("composition_mode",composition_mode)):
            if value:
                where.append(column+"=?")
                args.append(value)
        if q:
            where.append("(sample_id LIKE ? OR theme_seed_id LIKE ?)")
            args.extend([q[:100]+"%",q[:100]+"%"])
        limit = max(1,min(limit,100))
        args.append(limit+1)
        rows = self.rows("SELECT sample_id,campaign_id,stage,status,reason_code,theme_seed_id,scene_type,composition_mode,revision,updated_at,preview_artifact_id FROM samples WHERE "+" AND ".join(where)+" ORDER BY sample_id LIMIT ?",args)
        return {"items":rows[:limit],"next_cursor":rows[limit-1]["sample_id"] if len(rows)>limit else None}

    def ready(self, stages, limit=32, allow_network=True):
        marks = ",".join("?" for _ in stages)
        network = "s.stage IN ('author','refine','review') AND c.state='running' AND c.requests_used<c.request_limit AND c.api_cap>0 AND (SELECT COUNT(*) FROM attempts a WHERE a.campaign_id=c.campaign_id AND a.occupancy=1)<c.api_cap" if allow_network else "0"
        local = "s.stage IN ('build','render','archive') AND c.state IN ('running','draining','completed','blocked','degraded')"
        return self.rows(f"SELECT s.* FROM samples s JOIN campaigns c USING(campaign_id) WHERE s.status IN ('ready','deferred') AND s.next_ready_at<=? AND s.stage IN ({marks}) AND (({network}) OR ({local})) ORDER BY s.updated_at LIMIT ?",
                         [time.time(),*stages,max(0,min(limit,1024))])

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
            if db.execute("SELECT 1 FROM attempts WHERE attempt_id=? AND response_applied=0",(s['attempt_id'],)).fetchone():
                return None
            active = db.execute("SELECT COUNT(*) FROM attempts WHERE occupancy=1").fetchone()[0]
            route_active = db.execute("SELECT COUNT(*) FROM attempts WHERE occupancy=1 AND capacity_group=?",(endpoint.capacity_key(),)).fetchone()[0]
            campaign_active = db.execute("SELECT COUNT(*) FROM attempts WHERE occupancy=1 AND campaign_id=?",(s["campaign_id"],)).fetchone()[0]
            if db.execute("SELECT 1 FROM attempts WHERE occupancy=1 AND capacity_group=? AND status='outcome_unknown' LIMIT 1",(endpoint.capacity_key(),)).fetchone():
                return None  # Unconfirmed execution isolates this pool, never the financial ledger.
            if active >= hard_cap or campaign_active >= c["api_cap"] or route_active >= endpoint.provider_cap:
                return None
            if c["requests_used"] >= c["request_limit"] or s["request_count"] >= sample_limit:
                return None
            reserve_cost = endpoint.cost_upper_bound
            if c["cost_limit"] is not None and (reserve_cost is None or c["cost_known"]+c["reserved_cost"]+reserve_cost > c["cost_limit"]):
                db.execute("UPDATE campaigns SET state='blocked',reason_code='cost_budget_exhausted' WHERE campaign_id=?",(s["campaign_id"],))
                self._event(db,s["campaign_id"],"campaign_state",{"state":"blocked","reason_code":"cost_budget_exhausted"})
                return None
            recent = db.execute("SELECT COUNT(*),COALESCE(SUM(reserved_tokens),0) FROM attempts WHERE capacity_group=? AND started_at>?",(endpoint.capacity_key(),now-60)).fetchone()
            if (endpoint.rpm and recent[0]>=endpoint.rpm) or (endpoint.tpm and recent[1]+endpoint.reservation_tokens>endpoint.tpm):
                return None
            path = f"runs/{s['campaign_id']}/responses/{aid}.json"
            db.execute("INSERT INTO attempts(attempt_id,sample_id,campaign_id,revision,lease_token,role,endpoint_alias,status,reserved_cost,billing_status,response_path,started_at,reserved_tokens) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (aid,sample_id,s["campaign_id"],revision,token,s["stage"],endpoint.alias,"running",reserve_cost,"reserved",path,now,endpoint.reservation_tokens))
            db.execute("UPDATE attempts SET capacity_group=?,execution_deadline=?,execution_evidence=?,runtime_config_hash=? WHERE attempt_id=?",
                       (endpoint.capacity_key(),now+endpoint.server_max_execution_seconds if endpoint.server_max_execution_seconds else None,
                        endpoint.execution_contract_ref,self.runtime_config_hash,aid))
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
            unknown = execution_state(result) == "execution_unknown"
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

    def set_build_path(self, claim, path):
        with self.transaction() as db:
            db.execute("UPDATE samples SET build_path=? WHERE sample_id=? AND revision=? AND lease_token=?",
                       (Path(path).relative_to(self.root).as_posix(),claim['sample_id'],claim['revision'],claim['lease_token']))
            if not db.execute("SELECT changes()").fetchone()[0]:
                raise ValueError("stale build lease")

    def recover_receipt(self, attempt_id, result, response_path):
        """Settle a verified single execution without resetting identity or budgets."""
        evidence = result.get('receipt_evidence', {})
        if (execution_state(result) != 'terminated' or evidence.get('request_id') != attempt_id
                or evidence.get('schema') != 'pool.receipt.v1' or evidence.get('upstream_posts') != 1):
            raise ValueError('verified_receipt_required')
        relative = Path(response_path).relative_to(self.root).as_posix()
        with self.transaction() as db:
            a = db.execute('SELECT * FROM attempts WHERE attempt_id=?', (attempt_id,)).fetchone()
            if not a or a['status'] != 'outcome_unknown':
                return False
            cost = result.get('cost')
            if a['settled_cost'] is not None and cost is None:
                return False  # Do not replace an observed partial bill with missing usage.
            old_unknown, new_unknown = a['settled_cost'] is None, cost is None
            release = (a['reserved_cost'] or 0) if old_unknown and not new_unknown else 0
            summary = {k:v for k,v in result.items() if k not in {'raw','content'}}
            db.execute("UPDATE attempts SET status='complete',occupancy=0,settled_cost=?,billing_status=?,result_json=?,response_path=?,response_applied=0,execution_evidence=? WHERE attempt_id=?",
                       (cost,'unknown_reserved' if new_unknown else 'actual',dump(summary),relative,dump(evidence),attempt_id))
            db.execute('UPDATE campaigns SET cost_known=cost_known+?,cost_unknown=cost_unknown+?,reserved_cost=MAX(0,reserved_cost-?) WHERE campaign_id=?',
                       ((cost or 0)-(a['settled_cost'] or 0),int(new_unknown)-int(old_unknown),release,a['campaign_id']))
            db.execute("UPDATE samples SET status='blocked',reason_code='response_pending',next_ready_at=0 WHERE attempt_id=? AND revision=? AND stage=? AND status='blocked' AND reason_code='outcome_unknown'",
                       (attempt_id,a['revision'],a['role']))
            self._event(db,a['campaign_id'],'receipt_recovered',evidence,a['sample_id'])
            return True

    def finish(self, claim, *, stage=None, status="ready", reason=None, changes=None, delay=0, response_applied=True):
        allowed = {"source_path","source_hash","build_path","review_json","geometry_repairs","visual_repairs","review_format_retries","transport_retries","error_fingerprint","identical_errors","revision","preview_artifact_id","creative_phase","local_retries"}
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
                if response_applied and claim.get('attempt_id'):
                    db.execute("UPDATE attempts SET response_applied=1 WHERE attempt_id=? AND revision=? AND role=?",(claim['attempt_id'],claim['revision'],claim['stage']))
                if status in ('accepted','provisional_pass','rejected'):
                    self._family_outcome(db,claim,status != 'rejected')
                self._event(db,claim["campaign_id"],"transition",{"stage":updates["stage"],"status":status,"reason_code":reason,"creative_phase":changes.get("creative_phase",claim.get("creative_phase"))},claim["sample_id"])
        return ok

    def _family_outcome(self, db, sample, success):
        db.execute("INSERT INTO family_health VALUES(?,?,?,?) ON CONFLICT(campaign_id,family_id) DO UPDATE SET failures=CASE WHEN ? THEN 0 ELSE failures+1 END,last_failure_at=excluded.last_failure_at",
                   (sample['campaign_id'],sample['family_id'],0 if success else 1,0 if success else time.time(),int(success)))

    def _reconcile_execution(self, db, campaign_id, attempt_id, outcome, evidence):
        if outcome not in ('completed','cancelled','server_deadline') or not isinstance(evidence,str) or not evidence.strip() or len(evidence)>2000:
            raise ValueError('execution_confirmation_required')
        a = db.execute("SELECT * FROM attempts WHERE attempt_id=? AND campaign_id=?",(attempt_id,campaign_id)).fetchone()
        if not a or a['status'] != 'outcome_unknown':
            raise ValueError('attempt_not_unknown')
        if a['occupancy']:
            db.execute("UPDATE attempts SET occupancy=0,execution_evidence=? WHERE attempt_id=?",(dump({'outcome':outcome,'evidence':evidence}),attempt_id))
            self._event(db,campaign_id,'execution_reconciled',{'attempt_id':attempt_id,'outcome':outcome,'evidence':evidence},a['sample_id'])
        # Financial uncertainty and original POST identity remain unchanged.

    def reconcile_deadlines(self):
        with self.transaction() as db:
            for a in db.execute("SELECT * FROM attempts WHERE occupancy=1 AND status='outcome_unknown' AND execution_deadline<=?",(time.time(),)).fetchall():
                self._reconcile_execution(db,a['campaign_id'],a['attempt_id'],'server_deadline',a['execution_evidence'])

    def recover(self, pending_only=False):
        # Only unresolved indexed records; never reconstruct finalized arrays.
        # Restart batches beyond the first 1024 are processed by later ticks.
        # Never reclaim an HTTP request owned by the current scheduler.
        eligibility = "(s.status='blocked' AND s.reason_code IN ('finish_callback_failed','response_pending','response_recovery_failed','local_artifact_invalid') AND s.next_ready_at<=?) OR (s.status='running' AND COALESCE(s.lease_owner,'')!=?)" if pending_only else "s.status IN ('running','blocked') AND COALESCE(s.reason_code,'')!='response_recovery_exhausted'"
        running = self.rows("SELECT a.* FROM attempts a JOIN samples s ON s.attempt_id=a.attempt_id AND s.revision=a.revision AND s.stage=a.role WHERE a.response_applied=0 AND COALESCE(s.reason_code,'')!='phase_recovery_required' AND ("+eligibility+") LIMIT 1024",(time.time(),self.owner) if pending_only else ())
        replay = []
        for a in running:
            with self.transaction() as db:
                token = uuid.uuid4().hex
                db.execute("UPDATE samples SET status='running',lease_token=?,lease_owner=?,lease_until=? WHERE sample_id=? AND attempt_id=? AND revision=? AND stage=?",
                           (token,self.owner,time.time()+600,a['sample_id'],a['attempt_id'],a['revision'],a['role']))
            s = self.sample(a['sample_id'])
            if not s or s['lease_token'] != token:
                continue
            response = self.root / a["response_path"]
            if response.is_file():
                try:
                    result = json.loads(response.read_text())
                    if not isinstance(result,dict):
                        raise ValueError("invalid durable response")
                    if a["status"] == "running":
                        self.settle(a["attempt_id"],result)
                    replay.append((s,result))
                except (OSError,ValueError):
                    self.settle(a["attempt_id"],{"error_category":"outcome_unknown","cost":None})
                    self.finish(s,status="blocked",reason="response_unavailable" if a['status']=='complete' else "outcome_unknown",response_applied=a['status']!='complete')
            else:
                self.settle(a["attempt_id"],{"error_category":"outcome_unknown","cost":None})
                self.finish(s,status="blocked",reason="response_unavailable" if a['status']=='complete' else "outcome_unknown",response_applied=a['status']!='complete')
        with self.transaction() as db:
            if not pending_only:
                db.execute("UPDATE samples SET status='ready',lease_token=NULL,lease_owner=NULL,lease_until=NULL,reason_code='recovered_local' WHERE status='running' AND stage IN ('build','render','archive')")
            if running:
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

    def sample_configs(self, sample_id):
        return self.rows("SELECT a.attempt_id,a.runtime_config_hash,s.profile_hash,s.config_json FROM attempts a LEFT JOIN config_snapshots s ON a.runtime_config_hash=s.config_hash WHERE a.sample_id=? ORDER BY a.started_at",(sample_id,))

    def dedup_candidates(self, features):
        return self.rows("SELECT a.sample_id,a.lineage_group,a.canonical_voxel_hash,a.path,f.upright_hash FROM dedup_features f JOIN assets a USING(asset_id) WHERE f.rotation_hash=? OR f.quantized_hash=? LIMIT 32",
                         (features["rotation_occupancy_sha256"],features["geometry_quant_sha256"]))

    def variant_of(self, geometry_hash, features, lineage):
        exact = self.asset_exists(geometry_hash)
        if exact:
            return exact
        related = self.one("SELECT * FROM assets WHERE lineage_group=? AND is_current=1 ORDER BY accepted_unique DESC,created_at LIMIT 1",(lineage,))
        if related:
            return related
        upright = self.one("SELECT a.* FROM dedup_features f JOIN assets a USING(asset_id) WHERE f.upright_hash=? ORDER BY a.accepted_unique DESC,a.created_at LIMIT 1",(features['upright_equivalence_sha256'],))
        if upright:
            return upright
        # Upgrade only legacy exact rotation candidates, without scanning final assets.
        from voxlush.dataset.dedup import features_from_asset
        while True:
            legacy = self.rows("SELECT a.*,f.upright_hash FROM dedup_features f JOIN assets a USING(asset_id) WHERE f.rotation_hash=? AND f.upright_hash IS NULL LIMIT 32",(features['rotation_occupancy_sha256'],))
            if not legacy:
                break
            for candidate in legacy:
                current = features_from_asset(self.root/candidate['path'])
                self.register_dedup(candidate['asset_id'],current)
                if current['upright_equivalence_sha256'] == features['upright_equivalence_sha256']:
                    return candidate
        return None

    def register_dedup(self, asset_id, features):
        with self.transaction() as db:
            self._dedup(db,asset_id,features)

    def _dedup(self, db, asset_id, features):
        db.execute("INSERT INTO dedup_features VALUES(?,?,?,?,?,?) ON CONFLICT(asset_id) DO UPDATE SET upright_hash=excluded.upright_hash,features_json=excluded.features_json",
                   (asset_id,features['translation_occupancy_sha256'],features['rotation_occupancy_sha256'],features['geometry_quant_sha256'],dump(features),features.get('upright_equivalence_sha256')))

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
            aid = f"{claim['sample_id']}:v{claim['revision']:04d}"
            manifest = record["manifest_json"]
            if isinstance(manifest,str):
                manifest = json.loads(manifest)
            if manifest.get('composition',{}).get('requested_mode') != s['composition_mode']:
                raise ValueError('archive composition differs from planned sample')
            features = record.get('dedup_features')
            duplicate = self.asset_exists(record['canonical_voxel_hash']) or self.one('SELECT sample_id FROM assets WHERE lineage_group=? AND is_current=1 LIMIT 1',(manifest['lineage']['group_id'],))
            if not duplicate and features:
                duplicate = self.one('SELECT a.sample_id FROM dedup_features f JOIN assets a USING(asset_id) WHERE f.upright_hash=? LIMIT 1',(features['upright_equivalence_sha256'],))
            if duplicate and manifest['lineage']['is_unique']:
                raise ValueError('archive decision changed before commit; immutable manifest cannot be demoted')
            if not manifest['lineage']['is_unique']:
                if accepted or manifest['lifecycle'] != 'duplicate':
                    raise ValueError('inconsistent variant manifest')
                status,reason = 'rejected','duplicate'
            else:
                status,reason = ('accepted',None) if accepted else ('provisional_pass','unqualified_model_profile')
            if accepted != (manifest['lifecycle'] == 'accepted'):
                raise ValueError('inconsistent archive acceptance')
            db.execute("INSERT INTO assets VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (aid,claim["sample_id"],claim["revision"],claim["campaign_id"],str(record["path"]),dump(manifest),record["canonical_voxel_hash"],record.get("annotation_hash"),int(accepted),1,status,manifest['lineage']['group_id'],time.time()))
            if features:
                self._dedup(db,aid,features)
            db.execute("UPDATE samples SET status=?,reason_code=?,lineage_group=?,lease_token=NULL,lease_owner=NULL,lease_until=NULL,updated_at=? WHERE sample_id=?",
                (status,reason,manifest['lineage']['group_id'],time.time(),claim["sample_id"]))
            self._family_outcome(db,s,status != 'rejected')
            counter = "accepted_unique" if accepted else "provisional_pass" if status == "provisional_pass" else None
            if counter:
                db.execute(f"UPDATE campaigns SET {counter}={counter}+1 WHERE campaign_id=?",(claim["campaign_id"],))
            if accepted:
                minute = int(time.time()//60)*60
                db.execute("INSERT INTO metrics_minute(campaign_id,minute,accepted) VALUES(?,?,1) ON CONFLICT(campaign_id,minute) DO UPDATE SET accepted=accepted+1",(claim["campaign_id"],minute))
            self._event(db,claim["campaign_id"],"archive_commit",{"asset_id":aid,"accepted_unique":accepted,"duplicate_of":duplicate['sample_id'] if duplicate else None},claim["sample_id"])
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
        stats = {r['family_id']:r for r in self.rows("SELECT family_id,SUM(accepted) accepted,SUM(active) active,SUM(rejected) rejected,SUM(duplicate) duplicate,SUM(provisional) provisional FROM seed_stats WHERE campaign_id=? GROUP BY family_id",(campaign_id,))}
        health = {r['family_id']:r for r in self.rows("SELECT * FROM family_health WHERE campaign_id=?",(campaign_id,))}
        items = []
        for fid,f in FAMILIES.items():
            s = stats.get(fid,{})
            accepted = s.get("accepted",0)
            items.append({"family_id":fid,"name":f["name_zh"],"scene_type":f["scene_type"],"target":targets.get(fid,0),"accepted":accepted,"active":s.get("active",0),"rejected":s.get("rejected",0),"duplicate":s.get("duplicate",0),"debt":max(0,targets.get(fid,0)-accepted),"qualification":"unqualified","reason_code":"unqualified_model_profile"})
            items[-1].update(consecutive_failures=health.get(fid,{}).get('failures',0),last_failure_at=health.get(fid,{}).get('last_failure_at',0))
            items[-1]['provisional'] = s.get('provisional',0)
        return {"items":items,"totals":{k:sum(i[k] for i in items) for k in ("target","accepted","active","rejected","duplicate","debt","provisional")},
                'seeds':self.rows('SELECT * FROM seed_stats WHERE campaign_id=?',(campaign_id,))}

    def composition_coverage(self, campaign_id, *, diagnostics=False):
        c = self.campaign(campaign_id)
        if not c:
            return {'items':[]}
        stats = {(s['scene_type'],s['composition_mode']):s for s in self.rows(
            'SELECT * FROM composition_stats WHERE campaign_id=?',(campaign_id,))}
        targets = {}
        if c['composition_weights']:
            for scene, count in apportion(c['target'],c['scene_weights']).items():
                if scene != 'natural':
                    targets.update({(scene,mode):n for mode,n in apportion(count,composition_scene_weights(c['composition_weights'],scene)).items()})
        items = []
        for scene, mode in sorted(set(targets) | set(stats)):
            s = stats.get((scene,mode),{})
            row = {'scene_type':scene,'composition_mode':mode or None,'target':targets.get((scene,mode),0),
                   **{k:s.get(k,0) for k in ('tasks','active','accepted','provisional','rejected','duplicate','requests','visual_reviewed','visual_pass')}}
            row.update(debt=max(0,row['target']-row['accepted']),
                       candidate_debt=max(0,row['target']-row['accepted']-row['provisional']),
                       candidate_archives=row['accepted']+row['provisional'],
                       archive_rate=(row['accepted']+row['provisional'])/row['tasks'] if row['tasks'] else None,
                       average_requests=row['requests']/row['tasks'] if row['tasks'] else None,
                       visual_pass_rate=row['visual_pass']/row['visual_reviewed'] if row['visual_reviewed'] else None)
            if diagnostics:
                row['failures'] = self.rows('''SELECT reason_code,COUNT(*) count FROM samples WHERE campaign_id=?
                    AND scene_type=? AND composition_mode IS ? AND reason_code IS NOT NULL
                    AND status IN ('rejected','blocked','awaiting_review') GROUP BY reason_code''',(campaign_id,scene,mode or None))
            items.append(row)
        return {'items':items,'weights':c['composition_weights'],
                'rate_basis':'archive_rate = unique candidate or accepted / all tasks; visual = last valid image verdict per reviewed task'}

    def next_composition(self, campaign_id, scene_type, *, qualified):
        rows = [r for r in self.composition_coverage(campaign_id)['items']
                if r['scene_type'] == scene_type and r['composition_mode'] in MODES]
        for r in rows:
            r['pending_debt'] = r['debt' if qualified else 'candidate_debt'] - r['active']
        rows = [r for r in rows if r['pending_debt'] > 0]
        return max(rows,key=lambda r:(r['pending_debt']/max(1,r['target']),r['pending_debt'],r['composition_mode']))['composition_mode'] if rows else None

    def record_review(self, claim, review):
        with self.transaction() as db:
            db.execute('UPDATE samples SET review_json=? WHERE sample_id=? AND revision=? AND lease_token=?',
                       (dump(review),claim['sample_id'],claim['revision'],claim['lease_token']))

    def next_seed(self, campaign_id, family_id, composition_mode=None):
        progress = {r['theme_seed_id']:r for r in self.rows('SELECT * FROM seed_stats WHERE campaign_id=? AND family_id=?',(campaign_id,family_id))}
        def priority(seed):
            row = progress.get(seed['id'],{})
            return (row.get('accepted',0)+row.get('active',0),row.get('planned',0),seed['id'])
        return min((s for s in SEEDS if s['family_id'] == family_id
                    and (composition_mode is None or composition_mode in s.get('composition_modes', MODES))),key=priority)['id']

    def overview(self,campaign_id,effective_cap=0):
        c = self.campaign(campaign_id)
        if not c:
            return None
        queues = self.rows("SELECT stage,SUM(status IN ('ready','deferred')) ready,SUM(status='running') running,MIN(CASE WHEN status IN ('ready','deferred') THEN updated_at END) oldest FROM samples WHERE campaign_id=? AND status IN ('ready','running','deferred') GROUP BY stage",(campaign_id,))
        for q in queues:
            q["oldest_wait_seconds"] = max(0,time.time()-(q.pop("oldest") or time.time()))
        active = self.one("SELECT SUM(status='running') active,SUM(status='outcome_unknown') unknown FROM attempts WHERE occupancy=1 AND campaign_id=?",(campaign_id,))
        now = time.time()
        window = min(3600,max(0,now-c["created_at"]))
        n = self.one("SELECT COUNT(*) n FROM assets WHERE campaign_id=? AND accepted_unique=1 AND created_at>?",(campaign_id,now-3600))["n"]
        return {"campaign_id":campaign_id,"state":c["state"],"reason_code":c["reason_code"],"target":c["target"],"accepted_unique":c["accepted_unique"],"provisional_pass":c["provisional_pass"],"active_requests":active["active"] or 0,"unknown_occupancy":active["unknown"] or 0,"effective_cap":effective_cap,"configured_cap":c["api_cap"],"requests_used":c["requests_used"],"requests_limit":c["request_limit"],"cost_known":c["cost_known"] if c["requests_used"] and c["cost_unknown"] == 0 else None,"cost_unknown":c["cost_unknown"],"reserved_cost":c["reserved_cost"],"accepted_per_hour":n*3600/window if window>=60 and n else None,"window_seconds":window,"queues":queues,"event_cursor":self.one("SELECT COALESCE(MAX(event_id),0) n FROM events WHERE campaign_id=?",(campaign_id,))["n"],"server_time":now,"schema_version":"voxlush.events.v1"}

    def metric_snapshot(self,campaign_id,cap):
        active = self.one("SELECT COUNT(*) n FROM attempts WHERE status='running' AND campaign_id=?",(campaign_id,))["n"]
        with self.transaction() as db:
            db.execute("INSERT INTO metrics_minute(campaign_id,minute,active_requests,effective_cap) VALUES(?,?,?,?) ON CONFLICT(campaign_id,minute) DO UPDATE SET active_requests=excluded.active_requests,effective_cap=excluded.effective_cap",(campaign_id,int(time.time()//60)*60,active,cap))

    def create_export(self,export_id,campaign_id,include_provisional,composition_modes=None,composition_weights=None,composition_count=None):
        selection = export_selection(composition_modes,composition_weights,composition_count)
        with self.transaction() as db:
            old = db.execute("SELECT * FROM exports WHERE export_id=?",(export_id,)).fetchone()
            if old and (old["campaign_id"] != campaign_id or old["include_provisional"] != int(include_provisional)):
                raise ValueError("export id reused with different input")
            if old and export_selection(**{k.removeprefix('composition_'):v for k,v in json.loads(old['composition_selection']).items()}) != selection:
                raise ValueError('export id reused with different composition selection')
            db.execute("INSERT OR IGNORE INTO exports(export_id,campaign_id,include_provisional,created_at,composition_selection) VALUES(?,?,?,?,?)",(export_id,campaign_id,int(include_provisional),time.time(),dump(selection)))
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
