from __future__ import annotations
import asyncio
import hmac
import json
import os
import secrets
import time
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI,HTTPException,Query,Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse,JSONResponse,StreamingResponse
from voxlush.api.models import CampaignCreate,CommandCreate,CommandResult,ExportCreate,SessionCreate,Overview,SamplePage
from voxlush.core.config import Config
from voxlush.core.files import safe_path,digest
from voxlush.store.store import Store
from voxlush.pipeline.scheduler import Scheduler
from voxlush.dataset.export import export


def create_app(config: Config,*,start_scheduler=True):
    sessions = {}
    streams = 0
    @asynccontextmanager
    async def lifespan(app):
        store = Store(config.data_root)
        scheduler = Scheduler(store,config)
        app.state.store,app.state.scheduler = store,scheduler
        if start_scheduler:
            await scheduler.start()
        async def exports_loop():
            while not exports_stopping.is_set():
                pending = store.one("SELECT * FROM exports WHERE status IN ('queued','running') ORDER BY created_at LIMIT 1")
                if pending:
                    eid = pending["export_id"]
                    out = store.root/"releases"/eid
                    store.finish_export(eid,"running",path=out)
                    try:
                        result = await asyncio.to_thread(export,store,store.root,pending["campaign_id"],out,bool(pending["include_provisional"]))
                        result = result if isinstance(result,dict) else {"result":str(result)}
                        candidates = sorted(out.glob("*.tar")) + sorted(out.glob("*.json"))
                        result["artifacts"] = [{"name":p.name,"artifact_id":store.register_artifact(None,p,p.name,digest(p))} for p in candidates]
                        store.finish_export(eid,"complete",result=result,path=out)
                    except Exception as e:
                        store.finish_export(eid,"failed",reason=str(e)[:1000],path=out)
                try:
                    await asyncio.wait_for(exports_stopping.wait(), timeout=.5)
                except TimeoutError:
                    pass
        exports_stopping = asyncio.Event()
        exporter = asyncio.create_task(exports_loop())
        try:
            yield
        finally:
            if start_scheduler:
                await scheduler.stop()
            else:
                await scheduler.client.close()
            exports_stopping.set()
            await exporter
            store.close()

    app = FastAPI(title="Voxlush Gen",version="1.0.0",lifespan=lifespan,openapi_url="/api/v1/openapi.json")

    @app.middleware("http")
    async def access(request,call_next):
        token = os.getenv(config.auth_token_env)
        path = request.url.path
        if request.method not in ("GET","HEAD","OPTIONS"):
            origin = request.headers.get("origin")
            if origin and origin != f"{request.url.scheme}://{request.headers.get('host')}":
                return JSONResponse({"code":"origin_rejected","message":"Same origin required","retryable":False},status_code=403)
            if not origin and request.client and request.client.host not in ("127.0.0.1","::1","testclient") and not request.headers.get("authorization"):
                return JSONResponse({"code":"origin_required","message":"Origin required","retryable":False},status_code=403)
        protected = path.startswith("/api/v1/") and path not in ("/api/v1/session","/api/v1/health/live")
        if protected and token:
            cookie = request.cookies.get("voxlush_session","")
            bearer = request.headers.get("authorization","").removeprefix("Bearer ")
            if not (sessions.get(cookie,0)>time.time() or (bearer and hmac.compare_digest(token,bearer))):
                return JSONResponse({"code":"authentication_required","message":"登录后访问","retryable":False},status_code=401)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'"
        return response

    @app.exception_handler(ValueError)
    async def value_error(request,exc):
        return JSONResponse({"code":"invalid_operation","message":str(exc),"retryable":False,"request_id":secrets.token_hex(8),"details":{}},status_code=409)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request,exc):
        # Invalid input can contain Infinity/NaN or secrets; never echo it into JSON.
        errors = [{"loc":e["loc"],"message":e["msg"],"type":e["type"]} for e in exc.errors()]
        return JSONResponse({"code":"invalid_request","message":"Request validation failed","retryable":False,
                             "request_id":secrets.token_hex(8),"details":{"errors":errors}},status_code=422)

    def store():
        return app.state.store

    @app.post("/api/v1/session")
    def session(value: SessionCreate):
        token = os.getenv(config.auth_token_env)
        if not token or not hmac.compare_digest(token,value.token):
            raise HTTPException(401,"Invalid token")
        for key in list(sessions):
            if sessions[key]<time.time():
                sessions.pop(key)
        if len(sessions)>=32:
            sessions.pop(next(iter(sessions)))
        key = secrets.token_urlsafe(32)
        sessions[key] = time.time()+86400
        response = JSONResponse({"authenticated":True})
        response.set_cookie("voxlush_session",key,httponly=True,samesite="strict",max_age=86400)
        return response

    @app.get("/api/v1/health/live")
    def live():
        return {"status":"live","version":"1.0.0"}

    @app.get("/api/v1/health/ready")
    def ready():
        scheduler = app.state.scheduler
        return {"status":"ready" if not scheduler.loop_error else "degraded","scheduler_owner":store().owner,
                "reason_code":scheduler.loop_error,"model_qualified":config.is_qualified(),"allow_live":config.allow_live}

    @app.get("/api/v1/config")
    def get_config():
        return {**config.public(),"campaign_defaults":{"target":100,"request_limit":800,"api_cap":config.global_api_cap,"scene_weights":{"architecture":.6,"natural":.25,"hybrid":.15}}}

    @app.post("/api/v1/config/validate")
    def validate_config(value: dict):
        try:
            candidate = Config.model_validate(value)
            return {"valid":True,"errors":[],"profile_hash":candidate.profile_hash(),"paid_requests":0}
        except ValueError as e:
            errors = e.errors(include_input=False,include_url=False) if hasattr(e,"errors") else [{"message":str(e)}]
            return {"valid":False,"errors":[{"loc":r.get("loc"),"message":r.get("msg",r.get("message"))} for r in errors]}

    @app.get("/api/v1/campaigns")
    def campaigns():
        return {"items":store().campaigns()}

    @app.post("/api/v1/campaigns")
    def new_campaign(value: CampaignCreate):
        if value.api_cap>config.global_api_cap:
            raise ValueError("campaign cap exceeds configured authorization")
        return store().create_campaign(**value.model_dump())

    @app.post("/api/v1/commands",response_model=CommandResult)
    def new_command(value: CommandCreate):
        if value.action == "set_cap" and value.payload.get("api_cap",0)>config.global_api_cap:
            raise ValueError("cap exceeds configured authorization")
        return store().command(value.model_dump())

    @app.get("/api/v1/commands/{command_id}",response_model=CommandResult)
    def command(command_id: str):
        result = store().get_command(command_id)
        if not result:
            raise HTTPException(404,"command not found")
        return result

    @app.get("/api/v1/overview",response_model=Overview)
    def overview(campaign_id: str):
        result = app.state.scheduler.snapshots.get(campaign_id) or store().overview(campaign_id,app.state.scheduler.cap(store().campaign(campaign_id)))
        if not result:
            raise HTTPException(404,"campaign not found")
        return result

    @app.get("/api/v1/samples",response_model=SamplePage)
    def samples(campaign_id: str | None=None,cursor: str | None=None,limit: int=Query(50,ge=1,le=100),status: str | None=None,stage: str | None=None,q: str | None=Query(None,max_length=100)):
        return store().list_samples(campaign_id,cursor,limit,status,stage,q)

    @app.get("/api/v1/samples/{sample_id}")
    def sample(sample_id: str):
        result = store().sample(sample_id)
        if not result:
            raise HTTPException(404,"sample not found")
        result["artifacts"] = store().rows("SELECT artifact_id,name FROM artifacts WHERE sample_id=? ORDER BY name",(sample_id,))
        result["events"] = store().rows("SELECT event_id,kind,payload,created_at FROM events WHERE sample_id=? ORDER BY event_id DESC LIMIT 100",(sample_id,))
        result["attempts"] = store().rows("SELECT attempt_id,role,endpoint_alias,status,billing_status,started_at,finished_at FROM attempts WHERE sample_id=? ORDER BY started_at DESC LIMIT 16",(sample_id,))
        result.pop("lease_token",None)
        return result

    @app.get("/api/v1/artifacts/{artifact_id}")
    def artifact(artifact_id: str):
        r = store().one("SELECT * FROM artifacts WHERE artifact_id=?",(artifact_id,))
        if not r:
            raise HTTPException(404,"artifact not found")
        path = safe_path(store().root,r["path"])
        if not path.is_file():
            raise HTTPException(410,"artifact missing")
        if r["sha256"] and digest(path)!=r["sha256"]:
            raise HTTPException(409,"artifact hash mismatch")
        return FileResponse(path,filename=path.name,headers={"Cache-Control":"private, max-age=3600","ETag":r["sha256"] or ""})

    @app.get("/api/v1/coverage")
    def coverage(campaign_id: str):
        result = store().coverage(campaign_id)
        for item in result["items"]:
            item["qualification"] = "qualified" if config.is_qualified() else "unqualified"
            if config.is_qualified():
                item["reason_code"] = "coverage_debt" if item["debt"] else None
        return result

    @app.get("/api/v1/metrics")
    def metrics(campaign_id: str):
        return {"items":store().rows("SELECT * FROM metrics_minute WHERE campaign_id=? ORDER BY minute DESC LIMIT 60",(campaign_id,))}

    @app.get("/api/v1/events")
    async def events(request: Request,campaign_id: str,after: int=0):
        nonlocal streams
        if streams>=32:
            raise HTTPException(429,"SSE client capacity")
        if not store().campaign(campaign_id):
            raise HTTPException(404,"campaign not found")
        streams += 1
        async def feed():
            nonlocal streams
            last = after
            first = True
            try:
                while not await request.is_disconnected():
                    snapshot = app.state.scheduler.snapshots.get(campaign_id)
                    if snapshot is None:
                        snapshot = store().overview(campaign_id,app.state.scheduler.cap(store().campaign(campaign_id)))
                    cursor = snapshot["event_cursor"]
                    event = "reset" if first and (last>cursor or (last and cursor-last>10000)) else "snapshot"
                    value = {**snapshot,"event_id":cursor}
                    yield f"id: {cursor}\nevent: {event}\ndata: {json.dumps(value)}\n\n"
                    last,first = cursor,False
                    await asyncio.sleep(1)
            finally:
                streams -= 1
        return StreamingResponse(feed(),media_type="text/event-stream",headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})

    @app.post("/api/v1/exports")
    def new_export(value: ExportCreate):
        if not store().campaign(value.campaign_id):
            raise HTTPException(404,"campaign not found")
        return store().create_export(**value.model_dump())

    @app.get("/api/v1/exports/{export_id}")
    def get_export(export_id: str):
        r = store().one("SELECT * FROM exports WHERE export_id=?",(export_id,))
        if not r:
            raise HTTPException(404,"export not found")
        if r["result_json"]:
            r["result"] = json.loads(r.pop("result_json"))
        return r

    dist = config.frontend_dist or Path(__file__).resolve().parents[4]/"frontend"/"dist"
    @app.get("/{path:path}")
    def frontend(path: str):
        if path.startswith("api/") or not dist.is_dir():
            raise HTTPException(404,"frontend build unavailable" if not dist.is_dir() else "route not found")
        file = safe_path(dist,path) if path else dist/"index.html"
        return FileResponse(file if file.is_file() else dist/"index.html")
    return app
