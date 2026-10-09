from typing import Literal
from pydantic import Field,model_validator
from voxlush.core.config import StrictModel
from voxlush.themes.composition import CompositionMode, DEFAULT_WEIGHTS, export_selection, scene_weights as composition_scene_weights, validate_weights

class CampaignCreate(StrictModel):
    campaign_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    name: str = Field(min_length=1,max_length=100)
    target: int = Field(gt=0,le=1000000)
    request_limit: int = Field(gt=0,le=10000000)
    api_cap: int = Field(ge=0,le=512)
    scene_weights: dict[str,float] = Field(default_factory=lambda:{"architecture":.6,"natural":.25,"hybrid":.15})
    cost_limit: float | None = Field(default=None,gt=0)
    composition_weights: dict[CompositionMode,float] = Field(default_factory=lambda:dict(DEFAULT_WEIGHTS))

    @model_validator(mode="after")
    def weights(self):
        if set(self.scene_weights)-{"architecture","natural","hybrid"} or any(v<0 for v in self.scene_weights.values()) or sum(self.scene_weights.values())<=0:
            raise ValueError("valid nonnegative scene weights are required")
        validate_weights(self.composition_weights)
        for scene, weight in self.scene_weights.items():
            if weight > 0:
                composition_scene_weights(self.composition_weights, scene)
        return self

class CommandCreate(StrictModel):
    command_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    campaign_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    action: Literal["start","resume","drain","pause","emergency_stop","set_cap","retry","reconcile_execution"]
    expected_config_revision: int = Field(ge=1)
    payload: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def command_payload(self):
        if self.action == "set_cap":
            cap = self.payload.get("api_cap")
            if type(cap) is not int or not 0 <= cap <= 512:
                raise ValueError("set_cap requires an integer api_cap between 0 and 512")
        if self.action == 'reconcile_execution':
            if (self.payload.get('outcome') not in ('completed','cancelled') or
                not isinstance(self.payload.get('attempt_id'),str) or
                not isinstance(self.payload.get('evidence'),str) or not self.payload['evidence'].strip() or
                len(self.payload['evidence'])>2000):
                raise ValueError('reconciliation requires attempt_id, confirmed completed/cancelled outcome and evidence')
        return self

class CommandResult(StrictModel):
    command_id: str
    status: Literal["queued","applied","rejected"]
    reason: str | None = None
    campaign_id: str
    action: str

class ExportCreate(StrictModel):
    export_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,100}$")
    campaign_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    include_provisional: bool = False
    composition_modes: list[CompositionMode] | None = None
    composition_weights: dict[CompositionMode,float] | None = None
    composition_count: int | None = Field(default=None,gt=0,le=1000000)

    @model_validator(mode='after')
    def selection(self):
        export_selection(self.composition_modes,self.composition_weights,self.composition_count)
        return self

class SessionCreate(StrictModel):
    token: str = Field(min_length=1,max_length=512)

class Queue(StrictModel):
    stage: str
    ready: int
    running: int
    oldest_wait_seconds: float

class Overview(StrictModel):
    campaign_id: str
    state: str
    reason_code: str | None
    target: int
    accepted_unique: int
    provisional_pass: int
    active_requests: int
    unknown_occupancy: int
    effective_cap: int
    configured_cap: int
    requests_used: int
    requests_limit: int
    cost_known: float | None
    cost_unknown: int
    reserved_cost: float
    accepted_per_hour: float | None
    window_seconds: float
    queues: list[Queue]
    event_cursor: int
    server_time: float
    schema_version: str

class SampleSummary(StrictModel):
    sample_id: str
    campaign_id: str
    stage: str
    status: str
    reason_code: str | None
    theme_seed_id: str
    scene_type: str
    composition_mode: CompositionMode | None = None
    revision: int
    updated_at: float
    preview_artifact_id: str | None

class SamplePage(StrictModel):
    items: list[SampleSummary]
    next_cursor: str | None
