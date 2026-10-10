from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class NarrativeBlock:
    block_id: str
    kind: str
    text: str
    speaker: str | None = None
    scene_id: str | None = None
    presentation_phase: str | None = None
    origin_ids: frozenset[str] = frozenset()
    required_flags: frozenset[str] = frozenset()
    required_any_flags: frozenset[str] = frozenset()
    forbidden_flags: frozenset[str] = frozenset()

    def is_visible(self, *, origin_id: str, flags: set[str]) -> bool:
        return (
            (not self.origin_ids or origin_id in self.origin_ids)
            and self.required_flags.issubset(flags)
            and (not self.required_any_flags or bool(self.required_any_flags & flags))
            and not bool(self.forbidden_flags & flags)
        )


@dataclass(frozen=True, slots=True)
class OriginDefinition:
    origin_id: str
    title: str
    description: str


@dataclass(frozen=True, slots=True)
class FactDefinition:
    fact_id: str
    title: str
    text: str
    category: str = "fact"
    source_line: int = 0
    source_label: str = "剧情中已确认"
    related_npc_ids: tuple[str, ...] = ()
    use_hint: str = "可在后续会谈、调查和决策中作为已掌握材料引用。"
    disclosure_tier: int = 2
    owner_npc_ids: tuple[str, ...] = ()
    acquisition_methods: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True, slots=True)
class ScriptedEffects:
    metric_deltas: dict[str, tuple[int, int]] = field(default_factory=dict)
    ledger_deltas: dict[str, tuple[int, int]] = field(default_factory=dict)
    open_flags: frozenset[str] = frozenset()
    close_flags: frozenset[str] = frozenset()
    state_assignments: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ConditionalEffectDefinition:
    effects: ScriptedEffects
    replace_base: bool = False
    required_flags: frozenset[str] = frozenset()
    required_any_flags: frozenset[str] = frozenset()
    forbidden_flags: frozenset[str] = frozenset()
    required_state_values: dict[str, str] = field(default_factory=dict)
    forbidden_state_values: dict[str, frozenset[str]] = field(default_factory=dict)
    minimum_ledger_values: dict[str, int] = field(default_factory=dict)
    required_fact_ids: frozenset[str] = frozenset()

    def matches(
        self,
        flags: set[str],
        state_values: dict[str, str],
        ledger_values: dict[str, int] | None = None,
        known_fact_ids: set[str] | None = None,
    ) -> bool:
        ledger_values = ledger_values or {}
        return (
            self.required_flags.issubset(flags)
            and self.required_fact_ids.issubset(known_fact_ids or set())
            and (not self.required_any_flags or bool(self.required_any_flags & flags))
            and not bool(self.forbidden_flags & flags)
            and all(state_values.get(key) == value for key, value in self.required_state_values.items())
            and all(state_values.get(key) not in values for key, values in self.forbidden_state_values.items())
            and all(
                ledger_values.get(key, 0) >= minimum
                for key, minimum in self.minimum_ledger_values.items()
            )
        )


@dataclass(frozen=True, slots=True)
class AvailabilityClause:
    required_flags: frozenset[str] = frozenset()
    required_any_flags: frozenset[str] = frozenset()
    forbidden_flags: frozenset[str] = frozenset()
    required_state_values: dict[str, str] = field(default_factory=dict)
    forbidden_state_values: dict[str, frozenset[str]] = field(default_factory=dict)
    minimum_ledger_values: dict[str, int] = field(default_factory=dict)
    maximum_ledger_values: dict[str, int] = field(default_factory=dict)

    def matches(
        self,
        flags: set[str],
        state_values: dict[str, str],
        ledger_values: dict[str, int] | None = None,
    ) -> bool:
        ledger_values = ledger_values or {}
        return (
            self.required_flags.issubset(flags)
            and (not self.required_any_flags or bool(self.required_any_flags & flags))
            and not bool(self.forbidden_flags & flags)
            and all(state_values.get(key) == value for key, value in self.required_state_values.items())
            and all(state_values.get(key) not in values for key, values in self.forbidden_state_values.items())
            and all(ledger_values.get(key, 0) >= value for key, value in self.minimum_ledger_values.items())
            and all(ledger_values.get(key, 0) <= value for key, value in self.maximum_ledger_values.items())
        )


@dataclass(frozen=True, slots=True)
class DecisionOptionDefinition:
    option_id: str
    text: str
    consequence: str
    effects: ScriptedEffects = field(default_factory=ScriptedEffects)
    required_flags: frozenset[str] = frozenset()
    required_any_flags: frozenset[str] = frozenset()
    forbidden_flags: frozenset[str] = frozenset()
    required_state_values: dict[str, str] = field(default_factory=dict)
    forbidden_state_values: dict[str, frozenset[str]] = field(default_factory=dict)
    minimum_ledger_values: dict[str, int] = field(default_factory=dict)
    maximum_ledger_values: dict[str, int] = field(default_factory=dict)
    availability_any: tuple[AvailabilityClause, ...] = ()
    required_fact_ids: frozenset[str] = frozenset()
    required_any_fact_ids: frozenset[str] = frozenset()
    unlock_requirements: tuple[dict[str, str], ...] = ()
    unavailable_reason: str = "条件不足"
    conditional_effects: tuple[ConditionalEffectDefinition, ...] = ()

    def is_available(
        self,
        flags: set[str],
        state_values: dict[str, str],
        ledger_values: dict[str, int] | None = None,
        known_fact_ids: set[str] | None = None,
    ) -> bool:
        ledger_values = ledger_values or {}
        known_fact_ids = known_fact_ids or set()
        return (
            self.required_flags.issubset(flags)
            and (not self.required_any_flags or bool(self.required_any_flags & flags))
            and not bool(self.forbidden_flags & flags)
            and all(state_values.get(key) == value for key, value in self.required_state_values.items())
            and all(state_values.get(key) not in values for key, values in self.forbidden_state_values.items())
            and all(ledger_values.get(key, 0) >= value for key, value in self.minimum_ledger_values.items())
            and all(ledger_values.get(key, 0) <= value for key, value in self.maximum_ledger_values.items())
            and self.required_fact_ids.issubset(known_fact_ids)
            and (
                not self.required_any_fact_ids
                or bool(self.required_any_fact_ids & known_fact_ids)
            )
            and (
                not self.availability_any
                or any(item.matches(flags, state_values, ledger_values) for item in self.availability_any)
            )
        )


@dataclass(frozen=True, slots=True)
class DecisionTextVariant:
    required_flags: frozenset[str] = frozenset()
    forbidden_flags: frozenset[str] = frozenset()
    title: str | None = None
    prompt: str | None = None
    option_texts: dict[str, str] = field(default_factory=dict)
    option_consequences: dict[str, str] = field(default_factory=dict)
    scene_id: str | None = None
    required_fact_ids: frozenset[str] = frozenset()

    def matches(self, flags: set[str], known_fact_ids: set[str] | None = None) -> bool:
        return self.required_fact_ids.issubset(known_fact_ids or set()) and self.required_flags.issubset(flags) and not bool(
            self.forbidden_flags & flags
        )


@dataclass(frozen=True, slots=True)
class DecisionDefinition:
    decision_id: str
    story_day: int
    title: str
    prompt: str
    scene_id: str | None
    options: tuple[DecisionOptionDefinition, ...]
    followup_blocks: tuple[NarrativeBlock, ...] = ()
    action_point_cost: int = 0
    cost_source: str = "interrupt"
    skippable: bool = False
    input_kind: str = "choice"
    input_schema: dict = field(default_factory=dict)
    required_flags: frozenset[str] = frozenset()
    required_any_flags: frozenset[str] = frozenset()
    forbidden_flags: frozenset[str] = frozenset()
    early_day: int | None = None
    early_required_flags: frozenset[str] = frozenset()
    presentation_blocks: tuple[NarrativeBlock, ...] = ()
    text_variants: tuple[DecisionTextVariant, ...] = ()

    def option(self, option_id: str) -> DecisionOptionDefinition | None:
        return next((item for item in self.options if item.option_id == option_id), None)

    def is_available(self, flags: set[str]) -> bool:
        return (
            self.required_flags.issubset(flags)
            and (not self.required_any_flags or bool(self.required_any_flags & flags))
            and not bool(self.forbidden_flags & flags)
        )

    def is_due_early(self, story_day: int, flags: set[str]) -> bool:
        return (
            self.early_day == story_day
            and bool(self.early_required_flags)
            and self.early_required_flags.issubset(flags)
        )

    def text_variant(self, flags: set[str], known_fact_ids: set[str] | None = None) -> DecisionTextVariant | None:
        return next((item for item in self.text_variants if item.matches(flags, known_fact_ids)), None)

    def visible_title(self, flags: set[str], known_fact_ids: set[str] | None = None) -> str:
        variant = self.text_variant(flags, known_fact_ids)
        return variant.title if variant is not None and variant.title else self.title

    def visible_prompt(self, flags: set[str], known_fact_ids: set[str] | None = None) -> str:
        variant = self.text_variant(flags, known_fact_ids)
        return variant.prompt if variant is not None and variant.prompt else self.prompt

    def visible_scene_id(self, flags: set[str], known_fact_ids: set[str] | None = None) -> str | None:
        variant = self.text_variant(flags, known_fact_ids)
        return variant.scene_id if variant is not None and variant.scene_id else self.scene_id

    def visible_option_text(self, option: DecisionOptionDefinition, flags: set[str], known_fact_ids: set[str] | None = None) -> str:
        variant = self.text_variant(flags, known_fact_ids)
        return (
            variant.option_texts.get(option.option_id, option.text)
            if variant is not None
            else option.text
        )

    def visible_consequence(self, option: DecisionOptionDefinition, flags: set[str], known_fact_ids: set[str] | None = None) -> str:
        variant = self.text_variant(flags, known_fact_ids)
        return (
            variant.option_consequences.get(option.option_id, option.consequence)
            if variant is not None
            else option.consequence
        )


@dataclass(frozen=True, slots=True)
class StoryDayDefinition:
    beat_id: str
    story_day: int
    chapter: int
    day_mode: str
    title: str
    allow_actions: bool = True
    allow_end_day: bool = True
    end_day_requires_flags: frozenset[str] = frozenset()
    opening_blocks: tuple[NarrativeBlock, ...] = ()
    opening_decision_id: str | None = None
    decision_ids: tuple[str, ...] = ()
    night_blocks: tuple[NarrativeBlock, ...] = ()
    night_effects: ScriptedEffects = field(default_factory=ScriptedEffects)
    night_conditional_effects: tuple[ConditionalEffectDefinition, ...] = ()


@dataclass(frozen=True, slots=True)
class VisibleNarrativeEntry:
    cursor: int
    story_day: int
    kind: str
    text: str
    speaker: str | None = None
    content_instance_id: str | None = None
    block_id: str | None = None
    beat_id: str | None = None
    decision_id: str | None = None
    scene_id: str | None = None
    presentation_phase: str = "scene"
    day_sequence: int = 1
    read_gate: str = "advance"
