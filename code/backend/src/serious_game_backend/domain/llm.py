from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class SelectionOption:
    choice_id: str
    label: str
    description: str = ""

    def __post_init__(self) -> None:
        if not self.choice_id.strip() or not self.label.strip():
            raise ValueError("selection option requires a choice_id and label")


@dataclass(frozen=True, slots=True)
class SelectionTask:
    task_id: str
    role_id: str
    role_name: str
    instruction: str
    options: tuple[SelectionOption, ...]
    context: str = ""
    selection_mode: str = "single"
    minimum_choices: int = 1
    maximum_choices: int = 1
    session_id: str = ""
    account_id: str = ""
    operation_id: str = ""
    story_day: int = 0
    prompt_version: str = "selection-v1"

    def __post_init__(self) -> None:
        choice_ids = tuple(option.choice_id for option in self.options)
        if not self.task_id.strip() or not self.role_id.strip() or not self.options:
            raise ValueError("selection task requires task, role, and options")
        if len(choice_ids) != len(set(choice_ids)):
            raise ValueError("selection choice IDs must be unique")
        if self.selection_mode not in {"single", "multiple"}:
            raise ValueError("selection mode must be single or multiple")
        if not 0 <= self.minimum_choices <= self.maximum_choices <= len(self.options):
            raise ValueError("selection cardinality is outside the available options")
        if self.selection_mode == "single" and (
            self.minimum_choices != 1 or self.maximum_choices != 1
        ):
            raise ValueError("single selection requires exactly one choice")


@dataclass(frozen=True, slots=True)
class SelectionResult:
    choice_id: str | None = None
    choice_ids: tuple[str, ...] = ()

    @property
    def selected_ids(self) -> tuple[str, ...]:
        return (self.choice_id,) if self.choice_id is not None else self.choice_ids


@dataclass(frozen=True, slots=True)
class ExpressionTask:
    task_id: str
    role_id: str
    role_name: str
    confirmed_choice_ids: tuple[str, ...]
    choice_summaries: dict[str, str]
    allowed_facts: tuple[str, ...]
    persona: str
    context: str
    forbidden_text_signatures: tuple[str, ...] = ()
    forbidden_repeat_signatures: tuple[str, ...] = ()
    session_id: str = ""
    account_id: str = ""
    operation_id: str = ""
    story_day: int = 0
    maximum_characters: int = 500
    style_constraints: tuple[str, ...] = (
        "使用自然、简短、口语化的中文",
        "控制在2至4句，每句只表达一个明确意思",
        "不要堆叠括号舞台动作",
        "不要推断未提供的职责、事实、数字或承诺",
    )
    prompt_version: str = "expression-v1"
    character_dialogue: bool = False

    def __post_init__(self) -> None:
        if not self.task_id.strip() or not self.role_id.strip():
            raise ValueError("expression task requires task and role")
        if not self.confirmed_choice_ids:
            raise ValueError("expression task requires confirmed choices")
        if any(choice_id not in self.choice_summaries for choice_id in self.confirmed_choice_ids):
            raise ValueError("expression choice summary is missing")
        if self.maximum_characters < 1:
            raise ValueError("expression maximum length must be positive")


@dataclass(frozen=True, slots=True)
class ExpressionResult:
    text: str


@dataclass(frozen=True, slots=True)
class RoleTurnContext:
    session_id: str
    npc_id: str
    player_text: str
    story_day: int
    opportunity_id: str
    account_id: str = ""
    operation_id: str = ""
    allowed_fact_ids: tuple[str, ...] = ()
    required_disclosure_ids: tuple[str, ...] = ()
    npc_name: str = ""
    npc_state_tier: str = "deep"
    role_setting: str = ""
    big_five: dict[str, int] = field(default_factory=dict)
    prompt_template: str = ""
    prompt_version: str = "role-turn-v2"
    allowed_fact_texts: dict[str, str] = field(default_factory=dict)
    allowed_fact_markers: dict[str, tuple[str, ...]] = field(default_factory=dict)
    forbidden_fact_markers: tuple[str, ...] = ()
    forbidden_fact_signatures: dict[str, tuple[str, ...]] = field(default_factory=dict)
    memory_items: tuple[str, ...] = ()
    relationship_context: dict[str, str] = field(default_factory=dict)
    recent_visible_change_reasons: tuple[str, ...] = ()
    unresolved_commitments: tuple[str, ...] = ()
    unresolved_demands: tuple[str, ...] = ()
    conversation_turn_count: int = 0
    conversation_history: tuple[dict[str, str], ...] = ()
    conversation_opening: str = ""
    conversation_goal: str = ""
    visible_world_context: dict = field(default_factory=dict)
    player_reference_materials: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RoleTurnResult:
    npc_id: str
    dialogue: str
    input_relevance: str = "relevant"
    portrait_state: str = "neutral"
    attitude_direction: str = "none"
    attitude_band: str = "none"
    anxiety_direction: str = "none"
    anxiety_band: str = "none"
    disclosure_id: str | None = None
    flag_candidates: tuple[str, ...] = ()
    will_share_with: tuple[str, ...] = ()
    memory_candidate: str | None = None
    risk_notes: tuple[str, ...] = ()
    conversation_state: str = "continue"
    exit_narrative: str | None = None


@dataclass(frozen=True, slots=True)
class ValidatedRoleTurn:
    npc_id: str
    dialogue: str
    portrait_state: str
    attitude_delta: int
    anxiety_delta: int
    input_relevance: str = "relevant"
    disclosure_id: str | None = None
    memory_candidate: str | None = None
    will_share_with: tuple[str, ...] = ()
    risk_notes: tuple[str, ...] = ()
    conversation_state: str = "continue"
    exit_narrative: str | None = None


@dataclass(frozen=True, slots=True)
class NightAgentContext:
    session_id: str
    account_id: str
    operation_id: str
    story_day: int
    scene_id: str
    phase: str
    npc_id: str
    npc_name: str
    role_setting: str
    big_five: dict[str, int]
    counterpart_ids: tuple[str, ...]
    counterpart_names: dict[str, str] = field(default_factory=dict)
    counterpart_roles: dict[str, str] = field(default_factory=dict)
    transcript: tuple[dict[str, str], ...] = ()
    round_index: int = 0
    scene_goal: str = ""
    private_context: str = ""
    allowed_actions: tuple[dict, ...] = ()
    allowed_topics: tuple[str, ...] = ()
    forbidden_disclosure_markers: tuple[str, ...] = ()
    max_contacts: int = 0
    minimum_contacts: int = 0
    player_text: str = ""
    memory_items: tuple[str, ...] = ()
    unresolved_commitments: tuple[str, ...] = ()
    relationship_context: dict[str, str] = field(default_factory=dict)
    public_expression_context: str = ""
    reference_context: str = ""
    participant_state: str = "active"
    allowed_dialogue_acts: tuple[str, ...] = ()
    all_other_participants_settled: bool = False
    allowed_followup_type: str = ""
    allowed_followup_plans: tuple[dict, ...] = ()
    followup_required: bool = False
    model_id: str = ""
    prompt_version: str = "night-agent-v1"


@dataclass(frozen=True, slots=True)
class NightAgentResult:
    npc_id: str
    model_id: str
    dialogue: str | None = None
    action_id: str | None = None
    contact_ids: tuple[str, ...] = ()
    contact_response: str | None = None
    initiate_followup: bool = False
    followup_plan_id: str | None = None
    followup_type: str | None = None
    participant_ids: tuple[str, ...] = ()
    agenda: str = ""
    demands: tuple[str, ...] = ()
    urgency: str = "none"
    target_ids: tuple[str, ...] = ()
    topic_ids: tuple[str, ...] = ()
    rationale: str = ""
    dialogue_act: str | None = None
    stance: str | None = None
    topic_settled: bool = False
    memory_candidate: str | None = None
    reason_code: str | None = None


@dataclass(frozen=True, slots=True)
class GovernanceLLMContext:
    session_id: str
    account_id: str
    operation_id: str
    story_day: int
    task: str
    actor_id: str
    actor_name: str
    actor_profile: str
    payload: dict
    prompt_version: str = "governance-workflow-v1"
    actor_context: dict = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class GovernanceLLMResult:
    task: str
    data: dict
    model_id: str
