from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from serious_game_backend.domain.action import ActionCommand
from serious_game_backend.domain.enums import ActionInputMode


class StartSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    client_request_id: str = Field(min_length=8, max_length=128)
    package_id: str | None = Field(default=None, min_length=1, max_length=128)
    # Kept as a tolerated legacy field so older clients can still start a game.
    # New games always use the fixed mayor identity selected by the server.
    origin_id: str | None = Field(default=None, min_length=1, max_length=64)


class ActionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    input_mode: ActionInputMode
    client_action_id: str = Field(min_length=8, max_length=128)
    state_version: int = Field(ge=1)
    action_id: str | None = None
    opportunity_id: str | None = None
    player_text: str | None = Field(default=None, max_length=4000)
    target_npc_id: str | None = None
    target_ids: list[str] = Field(default_factory=list, max_length=64)
    quote_id: str | None = Field(default=None, min_length=8, max_length=128)
    conversation_id: str | None = Field(default=None, min_length=8, max_length=128)
    decision_id: str | None = None
    option_id: str | None = None
    ordered_option_ids: list[str] = Field(default_factory=list)
    parameters: dict[str, Any] = Field(default_factory=dict)
    retry: bool = False

    @model_validator(mode="after")
    def validate_union(self) -> "ActionRequest":
        if self.input_mode is ActionInputMode.TOOL:
            if not self.action_id or not self.opportunity_id:
                raise ValueError("tool 模式必须提供 opportunity_id 和 action_id")
            if any((self.decision_id, self.option_id, self.player_text,
                    self.target_npc_id, self.conversation_id,
                    self.ordered_option_ids, self.parameters, self.target_ids,
                    self.quote_id)):
                raise ValueError("tool 模式包含了不允许的字段")
        elif self.input_mode is ActionInputMode.RESOURCE_ACTION:
            if not self.action_id or not self.quote_id:
                raise ValueError("resource_action 模式必须提供 action_id 和 quote_id")
            if any((self.opportunity_id, self.player_text, self.target_npc_id,
                    self.conversation_id, self.decision_id, self.option_id,
                    self.ordered_option_ids)):
                raise ValueError("resource_action 模式包含了不允许的字段")
            if len(self.target_ids) != len(set(self.target_ids)):
                raise ValueError("target_ids 不能包含重复项")
        elif self.input_mode is ActionInputMode.CONVERSATION_START:
            if not self.opportunity_id or not self.target_npc_id:
                raise ValueError(
                    "conversation_start 模式必须提供 opportunity_id 和 target_npc_id"
                )
            if any((self.player_text, self.conversation_id, self.action_id,
                    self.decision_id, self.option_id, self.ordered_option_ids,
                    self.parameters, self.target_ids, self.quote_id)):
                raise ValueError("conversation_start 模式包含了不允许的字段")
        elif self.input_mode is ActionInputMode.FREE_TEXT:
            if (
                not self.opportunity_id
                or not self.target_npc_id
                or not self.conversation_id
                or not (self.player_text or "").strip()
            ):
                raise ValueError(
                    "free_text 模式必须提供 conversation_id、opportunity_id、target_npc_id 和 player_text"
                )
            if any((self.decision_id, self.option_id, self.action_id,
                    self.ordered_option_ids, self.parameters, self.target_ids,
                    self.quote_id)):
                raise ValueError("free_text 模式包含了不允许的字段")
        elif self.input_mode is ActionInputMode.CONVERSATION_END:
            if not self.conversation_id:
                raise ValueError("conversation_end 模式必须提供 conversation_id")
            if any((self.action_id, self.opportunity_id, self.player_text,
                    self.target_npc_id, self.decision_id, self.option_id,
                    self.ordered_option_ids, self.parameters, self.target_ids,
                    self.quote_id)):
                raise ValueError("conversation_end 模式包含了不允许的字段")
        elif self.input_mode is ActionInputMode.DECISION:
            if not self.decision_id or not (
                self.option_id or self.ordered_option_ids or self.parameters
            ):
                raise ValueError(
                    "decision 模式必须提供 decision_id，以及 option_id、ordered_option_ids 或 parameters"
                )
            if (self.action_id or self.opportunity_id or self.player_text
                    or self.target_npc_id or self.conversation_id or self.target_ids
                    or self.quote_id):
                raise ValueError("decision 模式不能提供工具、会谈或自由文本字段")
            if len(self.ordered_option_ids) != len(set(self.ordered_option_ids)):
                raise ValueError("ordered_option_ids 不能包含重复项")
        elif self.input_mode is ActionInputMode.OVERTIME:
            if set(self.parameters) != {"points"}:
                raise ValueError("overtime 模式只接受 points 参数")
            if self.parameters.get("points") not in {1, 2, 3}:
                raise ValueError("加班点数只能为 1、2 或 3")
            if any((self.action_id, self.opportunity_id, self.player_text,
                    self.target_npc_id, self.conversation_id, self.decision_id,
                    self.option_id, self.ordered_option_ids, self.target_ids,
                    self.quote_id)):
                raise ValueError("overtime 模式包含了不允许的字段")
        return self

    def to_command(self) -> ActionCommand:
        return ActionCommand(
            input_mode=self.input_mode,
            client_action_id=self.client_action_id,
            state_version=self.state_version,
            action_id=self.action_id,
            opportunity_id=self.opportunity_id,
            player_text=self.player_text,
            target_npc_id=self.target_npc_id,
            target_ids=tuple(self.target_ids),
            quote_id=self.quote_id,
            conversation_id=self.conversation_id,
            decision_id=self.decision_id,
            option_id=self.option_id,
            ordered_option_ids=tuple(self.ordered_option_ids),
            parameters=self.parameters,
            retry=self.retry,
        )


class ActionQuoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    action_id: str = Field(min_length=1, max_length=128)
    state_version: int = Field(ge=1)
    target_ids: list[str] = Field(default_factory=list, max_length=64)
    parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("target_ids")
    @classmethod
    def unique_targets(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("target_ids 不能包含重复项")
        return values


class EndDayRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    client_action_id: str = Field(min_length=8, max_length=128)
    state_version: int = Field(ge=1)
    retry: bool = False
    # Transitional compatibility only. True is invalid, so there is no
    # player-triggered rest branch in the settlement logic.
    active_rest: Literal[False] | None = None


class GroupConversationTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    state_version: int = Field(ge=1)
    player_text: str = Field(min_length=1, max_length=2000)
    client_action_id: str | None = Field(default=None, min_length=8, max_length=128)
    retry: bool = False


class GroupConversationFinishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    state_version: int = Field(ge=1)
    client_action_id: str = Field(min_length=8, max_length=128)
    retry: bool = False


class GovernanceActionStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    state_version: int = Field(ge=1)
    action_kind: str = Field(
        pattern="^(household_visit|cadre_interview|leadership_meeting|inspect_archives)$"
    )
    variant_id: str | None = Field(default=None, min_length=1, max_length=128)
    location_id: str | None = Field(default=None, min_length=1, max_length=128)
    opportunity_id: str | None = Field(default=None, min_length=1, max_length=128)
    map_entry_id: str | None = Field(default=None, min_length=1, max_length=256)
    target_ids: list[str] = Field(default_factory=list, max_length=8)
    topic: str = Field(default="", max_length=500)
    archive_ids: list[str] = Field(default_factory=list, max_length=32)
    proposed_document_type: str | None = Field(
        default=None, min_length=1, max_length=128
    )
    lead_npc_id: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def unique_governance_targets(self) -> "GovernanceActionStartRequest":
        if len(self.target_ids) != len(set(self.target_ids)):
            raise ValueError("target_ids不能重复")
        if len(self.archive_ids) != len(set(self.archive_ids)):
            raise ValueError("archive_ids不能重复")
        return self


class GovernanceTurnRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    state_version: int = Field(ge=1)
    player_text: str = Field(min_length=1, max_length=4000)
    client_action_id: str | None = Field(default=None, min_length=8, max_length=128)
    retry: bool = False


class GovernanceFinishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state_version: int = Field(ge=1)


class NPCDemandDispositionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state_version: int = Field(ge=1)
    transition: Literal[
        "acknowledged", "committed", "satisfied", "lawfully_refused", "breached"
    ]


class MeetingTurnRequest(GovernanceTurnRequest):
    addressed_npc_id: str | None = Field(default=None, max_length=128)


class MeetingResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state_version: int = Field(ge=1)
    adopt: bool
    resolution: dict[str, Any]


class DocumentEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    state_version: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=30000)


class DocumentCountersignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    state_version: int = Field(ge=1)
    npc_id: str = Field(min_length=1, max_length=128)


class DocumentPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    state_version: int = Field(ge=1)
    scope: list[str] = Field(min_length=1, max_length=32)


class ContractBatchConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state_version: int = Field(ge=1)
    confirmed: bool


class ContractTermsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    state_version: int = Field(ge=1)
    acknowledge_legacy_text: bool = False
    policy_document_id: str = Field(min_length=1, max_length=128)
    cash_amount: int = Field(ge=0, le=8000)
    auto_arrange: bool = False
    budget_envelope: str = Field(default="property_land", min_length=1, max_length=128)
    housing_resource_id: str | None = Field(default=None, max_length=128)
    service_allocations: dict[str, int] = Field(default_factory=dict)
    payment_day: int = Field(default=1, ge=1, le=90)
    move_out_day: int = Field(default=1, ge=1, le=90)
    housing_delivery_day: int | None = Field(default=None, ge=1, le=90)
    transition_months: int = Field(default=0, ge=0, le=12)
    public_window_reward: bool | None = None
    approval_document_ids: list[str] = Field(default_factory=list, max_length=16)
    authorization_confirmed: bool = False
    real_unit_viewed: bool = False
    ledger_disclosed: bool = False
    old_case_resolved: bool = False
    prior_payment_verified: bool = False

    def term_sheet(self) -> dict:
        return self.model_dump(exclude={"state_version", "acknowledge_legacy_text"})


class ContractEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    state_version: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=30000)


class ContractStateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state_version: int = Field(ge=1)
    expected_contract_version: int | None = Field(default=None, ge=1)


class ContractSignRequest(ContractStateRequest):
    confirmed: bool


class ManualSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    client_action_id: str = Field(min_length=8, max_length=128)
    state_version: int = Field(ge=1)
    slot_number: int = Field(ge=1, le=5)
    display_name: str = Field(min_length=1, max_length=128)
    overwrite: bool = False


class LoadSnapshotRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    client_action_id: str = Field(min_length=8, max_length=128)
    state_version: int = Field(ge=1)
    snapshot_id: str = Field(min_length=8, max_length=128)
    confirmed: bool = False


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=256)


class RegisterRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    username: str = Field(min_length=3, max_length=32)
    password: str = Field(min_length=8, max_length=256)

    @field_validator("username")
    @classmethod
    def validate_username(cls, value: str) -> str:
        if any(character.isspace() for character in value):
            raise ValueError("用户名不能包含空白字符")
        if any(ord(character) < 32 for character in value):
            raise ValueError("用户名包含非法控制字符")
        return value


class PlayerLLMConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    mode: Literal["personal", "server_default"]
    base_url: str | None = Field(default=None, max_length=2048)
    api_key: str | None = Field(default=None, max_length=1024)
    model: str | None = Field(default=None, max_length=256)

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "PlayerLLMConfigurationRequest":
        if self.mode == "personal":
            if not self.base_url or not self.api_key or not self.model:
                raise ValueError("个人 API 必须填写 Base URL、API Key 和模型名")
        elif any((self.base_url, self.api_key, self.model)):
            raise ValueError("服务器默认模式不能携带个人 API 字段")
        return self


class ConsentSignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    consent_version: str = Field(min_length=1, max_length=128)
    scopes: list[str] = Field(min_length=1, max_length=8)


class ConsentWithdrawRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    reason: str | None = Field(default=None, max_length=500)


class SubjectRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_type: str = Field(pattern="^(access|erase)$")
    reason: str | None = Field(default=None, max_length=1000)


class ExportRequestBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    purpose: str = Field(min_length=3, max_length=1000)
    fields: list[str] = Field(min_length=1, max_length=16)
    conditions: dict[str, str | int | None] = Field(default_factory=dict)
    minimum_cell_size: int = Field(default=5, ge=5, le=100)


class GovernancePurposeBody(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    purpose: str = Field(min_length=3, max_length=1000)


class RetentionRunBody(GovernancePurposeBody):
    cutoff_at: str = Field(min_length=20, max_length=64)
    policy_version: str = Field(min_length=1, max_length=128)
