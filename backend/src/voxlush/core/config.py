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
    supports_images: bool = False
    connect_timeout: float = Field(default=10, gt=0)
    first_content_timeout: float = Field(default=90, gt=0)
    idle_timeout: float = Field(default=60, gt=0)
    total_timeout: float = Field(default=240, gt=0)
    rpm: int | None = Field(default=None, gt=0)
    tpm: int | None = Field(default=None, gt=0)
    reservation_tokens: int = Field(default=16000, gt=0)
    cost_upper_bound: float | None = Field(default=None, ge=0)
    input_per_million: float | None = Field(default=None, ge=0)
    output_per_million: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def capability(self):
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
    build_workers: int = Field(default=1, ge=1, le=8)
    render_workers: int = Field(default=1, ge=1, le=8)
    archive_workers: int = Field(default=1, ge=1, le=2)
    local_memory_mb: int = Field(default=4096, ge=1024)
    disk_reserve_bytes: int = Field(default=1073741824, ge=0)
    sample_request_limit: int = Field(default=8, ge=1, le=16)
    geometry_repairs: int = Field(default=2, ge=0, le=3)
    visual_repairs: int = Field(default=1, ge=0, le=2)
    transport_retries: int = Field(default=1, ge=0, le=2)
    zero_yield_limit: int = Field(default=64, ge=1)
    theme_zero_yield_limit: int = Field(default=8, ge=1)
    author: Endpoint | None = None
    visual: Endpoint | None = None
    qualification: Qualification = Field(default_factory=Qualification)
    frontend_dist: Path | None = None

    @model_validator(mode="after")
    def memory(self):
        if (self.build_workers + self.render_workers) * 1024 > self.local_memory_mb:
            raise ValueError("local workers need at least 1024 MiB each plus host headroom")
        if self.host not in ("127.0.0.1", "localhost", "::1") and not os.getenv(self.auth_token_env):
            raise ValueError("remote bind requires admin token and TLS protected reverse proxy")
        return self

    def profile_hash(self) -> str:
        fields = {"author": self.author.model_dump() if self.author else None,
                  "visual": self.visual.model_dump() if self.visual else None,
                  "prompt": "voxlush.prompt.v2", "rubric": "voxlush.visual.v1"}
        return hashlib.sha256(json.dumps(fields, sort_keys=True).encode()).hexdigest()

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
