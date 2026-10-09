"""Operator CLI. Live campaign controls go through the API owner."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from voxlush.core.config import Config, load_config


def _config(value: str | None) -> Config:
    return load_config(value) if value else load_config()


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def _api_client(config: Config) -> httpx.Client:
    base_url = os.getenv("VOXLUSH_API_URL")
    if not base_url:
        if config.host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError("set VOXLUSH_API_URL to the protected API URL for remote services")
        host = f"[{config.host}]" if ":" in config.host else config.host
        base_url = f"http://{host}:{config.port}"
    parsed = urlsplit(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("VOXLUSH_API_URL must be an http(s) URL without credentials, query, or fragment")
    headers = {}
    token = os.getenv(config.auth_token_env)
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=base_url.rstrip("/"), headers=headers, timeout=10)


def command_doctor(config: Config) -> int:
    from voxlush.voxel.adapter import doctor
    result = {"config": config.public(), "voxel": doctor(config.model_dump(mode="json"))}
    _print(result)
    return 0 if result["voxel"].get("ready", False) else 2


def command_serve(config: Config) -> int:
    import uvicorn
    from voxlush.api.app import create_app
    uvicorn.run(create_app(config), host=config.host, port=config.port,
                reload=False, lifespan="on", log_level="info")
    return 0


def command_campaign(args, config: Config) -> int:
    with _api_client(config) as client:
        if args.action == "create":
            result = client.post("/api/v1/campaigns", json={
                "campaign_id": args.campaign_id,
                "name": args.name,
                "target": args.target,
                "request_limit": args.request_limit,
                "api_cap": args.api_cap,
                "scene_weights": {"architecture": .6, "natural": .25, "hybrid": .15},
            })
            result.raise_for_status()
            _print(result.json())
            return 0

        campaign_response = client.get("/api/v1/campaigns")
        campaign_response.raise_for_status()
        campaign = next((item for item in campaign_response.json()["items"]
                         if item["campaign_id"] == args.campaign_id), None)
        if not campaign:
            raise ValueError("campaign not found")
        payload = {"api_cap": args.api_cap} if args.action == "set_cap" else {}
        if args.action == "retry":
            payload["sample_id"] = args.sample_id
        if args.action == 'reconcile_execution':
            payload = {'attempt_id':args.attempt_id,'outcome':args.outcome,'evidence':args.evidence}
        command_id = args.command_id or uuid.uuid4().hex
        response = client.post("/api/v1/commands", json={
            "command_id": command_id,
            "campaign_id": args.campaign_id,
            "action": args.action,
            "expected_config_revision": campaign["config_revision"],
            "payload": payload,
        })
        response.raise_for_status()
        result = response.json()
        deadline = time.monotonic() + 10
        while result["status"] == "queued" and time.monotonic() < deadline:
            time.sleep(.1)
            response = client.get(f"/api/v1/commands/{command_id}")
            response.raise_for_status()
            result = response.json()
        _print(result)
        return 0 if result["status"] != "rejected" else 2


def _store(config: Config):
    from voxlush.store.store import Store
    return Store(config.data_root)


def command_import(args, config: Config) -> int:
    from voxlush.dataset.legacy import import_legacy
    from voxlush.store.store import Store
    store = None if args.dry_run else Store(config.data_root)
    try:
        _print(import_legacy(Path(args.source), store=store, dry_run=args.dry_run))
        return 0
    finally:
        if store:
            store.close()


def command_export(args, config: Config) -> int:
    from voxlush.dataset.export import export
    store = _store(config)
    try:
        _print(export(store, config.data_root, args.campaign, Path(args.output), args.include_provisional))
        return 0
    finally:
        store.close()


def command_backup(args, config: Config) -> int:
    from voxlush.dataset.backup import backup
    store = _store(config)
    try:
        _print(backup(store, config.data_root, Path(args.output)))
        return 0
    finally:
        store.close()


def command_gallery(args, config: Config) -> int:
    from voxlush.dataset.gallery import blind_gallery
    store = _store(config)
    try:
        _print(blind_gallery(store, config.data_root, args.campaign, Path(args.output), count=args.count, seed=args.seed))
        return 0
    finally:
        store.close()


def command_restore(args) -> int:
    from voxlush.dataset.backup import restore_backup
    _print(restore_backup(Path(args.source), Path(args.destination)))
    return 0


def command_verify(args) -> int:
    from voxlush.dataset.export import verify_release
    _print(verify_release(Path(args.path)))
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="voxlush", description="Voxlush Gen operator controls")
    p.add_argument("--config", help="脱敏 JSON 配置")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor")
    sub.add_parser("serve")

    camp = sub.add_parser("campaign")
    camp_sub = camp.add_subparsers(dest="action", required=True)
    create = camp_sub.add_parser("create")
    create.add_argument("campaign_id")
    create.add_argument("name")
    create.add_argument("target", type=int)
    create.add_argument("--request-limit", type=int, default=800)
    create.add_argument("--api-cap", type=int, default=8)
    for action in ("start", "pause", "resume", "drain", "emergency_stop", "set_cap", "retry", "reconcile_execution"):
        command = camp_sub.add_parser(action)
        command.add_argument("campaign_id")
        command.add_argument("--command-id")
        command.add_argument("--api-cap", type=int, default=0)
        if action == "retry":
            command.add_argument("--sample-id", required=True)
        if action == 'reconcile_execution':
            command.add_argument('--attempt-id',required=True)
            command.add_argument('--outcome',choices=('completed','cancelled'),required=True)
            command.add_argument('--evidence',required=True)

    imp = sub.add_parser("import-legacy")
    imp.add_argument("--source", required=True)
    imp.add_argument("--dry-run", action="store_true")
    exp = sub.add_parser("export")
    exp.add_argument("--campaign", required=True)
    exp.add_argument("--output", required=True)
    exp.add_argument("--include-provisional", action="store_true")
    gallery = sub.add_parser('blind-gallery')
    gallery.add_argument('--campaign', required=True)
    gallery.add_argument('--output', required=True)
    gallery.add_argument('--count', type=int, default=100)
    gallery.add_argument('--seed', type=int, default=0)
    backup_parser = sub.add_parser("backup")
    backup_parser.add_argument("--output", required=True)
    restore = sub.add_parser("restore")
    restore.add_argument("--source", required=True)
    restore.add_argument("--destination", required=True)
    verify = sub.add_parser("verify-release")
    verify.add_argument("path")
    return p


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "doctor":
            return command_doctor(_config(args.config))
        if args.command == 'blind-gallery':
            return command_gallery(args, _config(args.config))
        if args.command == "serve":
            return command_serve(_config(args.config))
        if args.command == "campaign":
            return command_campaign(args, _config(args.config))
        if args.command == "import-legacy":
            return command_import(args, _config(args.config))
        if args.command == "export":
            return command_export(args, _config(args.config))
        if args.command == "backup":
            return command_backup(args, _config(args.config))
        if args.command == "restore":
            return command_restore(args)
        if args.command == "verify-release":
            return command_verify(args)
        return 2
    except (httpx.HTTPError, OSError, ValueError) as exc:
        print(f"voxlush: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
