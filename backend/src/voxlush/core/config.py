"""Validated configuration; capabilities and authorization are explicit."""
from __future__ import annotations
import hashlib
import json
import os
from urllib.parse import urlsplit
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

class Endpoint(StrictModel):
    alias: str = "author"
    base_url: str
    model: str
    api_key_env: str = "VOXLUSH_API_KEY"
    stream: bool = True
    completion: Literal["finish_and_done", "finish", "nonstream"] = "finish_and_done"
    parameters: dict = Field(default_factory=lambda: {"max_tokens": 12000})
    provider_cap: int = Field(default=8, ge=0, le=512)
    capacity_pool: str | None = Field(default=None, min_length=1, max_length=100)
    server_max_execution_seconds: float | None = Field(default=None, gt=0)
    execution_contract_ref: str | None = Field(default=None, min_length=1, max_length=500)
    supports_images: bool = False
    pool_receipts: bool = False
    connect_timeout: float = Field(default=10, gt=0)
    first_content_timeout: float = Field(default=90, gt=0,
        description="Seconds to the first nonempty answer or reasoning delta; heartbeats do not count.")
    idle_timeout: float = Field(default=60, gt=0,
        description="Maximum gap between answer or reasoning progress, also the HTTP read timeout.")
    total_timeout: float = Field(default=240, gt=0)
    rpm: int | None = Field(default=None, gt=0)
    tpm: int | None = Field(default=None, gt=0)
    reservation_tokens: int = Field(default=16000, gt=0)
    cost_upper_bound: float | None = Field(default=None, ge=0)
    input_per_million: float | None = Field(default=None, ge=0)
    output_per_million: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def capability(self):
        if (self.server_max_execution_seconds is None) != (self.execution_contract_ref is None):
            raise ValueError("server execution deadline requires a documented dispatch-to-stop contract")
        parsed = urlsplit(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("endpoint base_url must be an absolute http(s) URL")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("endpoint URL cannot contain credentials, query parameters, or fragments")
        if not self.api_key_env.isidentifier() or not self.api_key_env.isupper():
            raise ValueError("api_key_env must be an uppercase environment variable name")
        if not self.stream and self.completion != "nonstream":
            raise ValueError("non-stream endpoint requires completion=nonstream")
        if self.stream and self.completion == "nonstream":
            raise ValueError("stream endpoint requires an explicit stream completion contract")
        if "messages" in self.parameters or "model" in self.parameters or "stream" in self.parameters:
            raise ValueError("parameters cannot override model/messages/stream")
        try:
            json.dumps(self.parameters,allow_nan=False)
        except (TypeError,ValueError) as exc:
            raise ValueError("endpoint parameters must contain finite JSON-compatible values") from exc
        return self

    def capacity_key(self):
        # Same service shares capacity unless its documented pools are explicit.
        return hashlib.sha256((self.capacity_pool or self.base_url.rstrip('/')).encode()).hexdigest()

class Qualification(StrictModel):
    qualified: bool = False
    profile_hash: str | None = None
    evidence_path: str | None = None
    human_reviewed: int = Field(default=0, ge=0)
    human_pass: int = Field(default=0, ge=0)

class Config(StrictModel):
    schema_version: str = "voxlush.config.v1"
    data_root: Path = Path("./data")
    host: str = "127.0.0.1"
    port: int = Field(default=8740, ge=1, le=65535)
    auth_token_env: str = "VOXLUSH_ADMIN_TOKEN"
    allow_live: bool = False
    global_api_cap: int = Field(default=8, ge=0, le=512)
    unknown_execution_policy: Literal["isolate_pool", "continue_new_tasks"] = "isolate_pool"
    unknown_backoff_seconds: float = Field(default=30, ge=1, le=3600,
        description="Pause new calls after an unknown result in continue_new_tasks mode; not a remote execution deadline.")
    build_workers: int = Field(default=1, ge=1, le=8)
    render_workers: int = Field(default=1, ge=1, le=8)
    archive_workers: int = Field(default=1, ge=1, le=2)
    local_memory_mb: int = Field(default=4096, ge=1024)
    disk_reserve_bytes: int = Field(default=1073741824, ge=0)
    sample_request_limit: int = Field(default=8, ge=1, le=16)
    geometry_repairs: int = Field(default=2, ge=0, le=3)
    visual_repairs: int = Field(default=1, ge=0, le=2)
    review_format_retries: int = Field(default=1, ge=0, le=2)
    transport_retries: int = Field(default=1, ge=0, le=2)
    zero_yield_limit: int = Field(default=64, ge=1)
    theme_zero_yield_limit: int = Field(default=8, ge=1)
    theme_cooldown_seconds: float = Field(default=300, gt=0)
    author: Endpoint | None = None
    visual: Endpoint | None = None
    qualification: Qualification = Field(default_factory=Qualification)
    frontend_dist: Path | None = None

    @model_validator(mode="after")
    def memory(self):
        endpoints = [e for e in (self.author, self.visual) if e]
        if len(endpoints) == 2 and endpoints[0].capacity_key() == endpoints[1].capacity_key():
            if any(getattr(endpoints[0], k) != getattr(endpoints[1], k) for k in ('provider_cap', 'rpm', 'tpm')):
                raise ValueError("roles sharing a capacity pool must agree on its cap/RPM/TPM")
        if (self.build_workers + self.render_workers) * 1024 > self.local_memory_mb:
            raise ValueError("local workers need at least 1024 MiB each plus host headroom")
        if self.host not in ("127.0.0.1", "localhost", "::1") and not os.getenv(self.auth_token_env):
            raise ValueError("remote bind requires admin token and TLS protected reverse proxy")
        return self

    def profile_hash(self) -> str:
        from voxlush.inference import STREAM_POLICY_VERSION
        from voxlush.pipeline.prompts import PROMPT_VERSION, RUBRIC_HASH
        from voxlush.voxel.adapter import versions
        def identity(endpoint):
            if endpoint is None:
                return None
            return {"route":hashlib.sha256(endpoint.base_url.encode()).hexdigest(),
                    **endpoint.model_dump(include={"model", "parameters", "stream", "completion", "supports_images",
                                                   "first_content_timeout", "idle_timeout", "total_timeout"}),
                    **({'pool_receipts':True} if endpoint.pool_receipts else {})}
        fields = {"author": identity(self.author), "visual": identity(self.visual),
                  "prompt": PROMPT_VERSION, "rubric": RUBRIC_HASH, "quality_runtime":versions(),
                  "stream_policy": STREAM_POLICY_VERSION}
        return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()

    def snapshot(self) -> dict:
        """Freeze routing identities and settings without addresses or secret values."""
        def redact(value):
            if isinstance(value, dict):
                return {k:("[redacted]" if (k.lower() in {'token','key','credential'} or k.lower().endswith('_token') or
                           any(word in k.lower() for word in ("secret", "password", "authorization", "api_key")))
                           else redact(v)) for k,v in value.items()}
            if isinstance(value, list):
                return [redact(v) for v in value]
            return value
        value = redact(self.model_dump(mode="json"))
        for role in ("author", "visual"):
            if value[role]:
                value[role]["base_url"] = "sha256:" + hashlib.sha256(value[role]["base_url"].encode()).hexdigest()
        value["profile_hash"] = self.profile_hash()
        return value

    def is_qualified(self) -> bool:
        q = self.qualification
        if not (q.qualified and q.profile_hash == self.profile_hash() and q.human_reviewed >= 100
                and q.human_pass / max(1, q.human_reviewed) >= .96 and q.evidence_path):
            return False
        try:
            evidence = json.loads(Path(q.evidence_path).read_text())
            return (evidence.get("profile_hash") == q.profile_hash and
                    evidence.get("status") == "qualified" and evidence.get("human_reviewed") == q.human_reviewed)
        except (OSError, ValueError):
            return False

    def public(self) -> dict:
        d = self.model_dump(mode="json")
        d["model_qualified"] = self.is_qualified()
        d["profile_hash"] = self.profile_hash()
        d["auth_required"] = bool(os.getenv(self.auth_token_env))
        return d


def load_config(path: str | Path | None = None) -> Config:
    c = Config.model_validate_json(Path(path).read_text()) if path else Config()
    c.data_root = c.data_root.expanduser().resolve()
    return c
