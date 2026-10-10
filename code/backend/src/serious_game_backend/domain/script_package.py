from __future__ import annotations

from dataclasses import dataclass

from serious_game_backend.domain.action import ActionRule, ResourceActionDefinition
from serious_game_backend.domain.enums import ActionCostTier, NPCStateTier
from serious_game_backend.domain.interaction_opportunity import InteractionOpportunity
from serious_game_backend.domain.story import (
    DecisionDefinition,
    FactDefinition,
    OriginDefinition,
    StoryDayDefinition,
)


@dataclass(frozen=True, slots=True)
class CalendarSegment:
    day_start: int
    day_end: int
    chapter: int
    cost_tier: ActionCostTier

    def contains(self, story_day: int) -> bool:
        return self.day_start <= story_day <= self.day_end


@dataclass(frozen=True, slots=True)
class FixedEventRule:
    event_id: str
    story_day: int
    title: str
    visible_summary: str
    trigger_type: str = "fixed"
    required_flags: frozenset[str] = frozenset()
    required_any_flags: frozenset[str] = frozenset()
    forbidden_flags: frozenset[str] = frozenset()
    forbidden_event_ids: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class MapLocationDefinition:
    location_id: str
    name: str
    description: str
    unlock_day: int
    linked_opportunity_ids: tuple[str, ...] = ()
    linked_event_ids: tuple[str, ...] = ()
    linked_action_ids: tuple[str, ...] = ()
    required_flags: frozenset[str] = frozenset()


@dataclass(frozen=True, slots=True)
class MainEndingDefinition:
    ending_id: str
    order: int
    name: str
    tone: str
    condition: dict
    free_axis: str
    sub_ending_ids: tuple[str, ...]
    text: str = ""
    source_line: int = 0


@dataclass(frozen=True, slots=True)
class SubEndingDefinition:
    sub_ending_id: str
    main_ending_id: str
    axis: str
    axis_value: str
    title: str
    text: str = ""
    source_line: int = 0


@dataclass(frozen=True, slots=True)
class EndingAppendixDefinition:
    appendix_id: str
    title: str
    source: str


@dataclass(frozen=True, slots=True)
class ContentCatalogEntry:
    content_id: str
    chapter: int
    source_line: int


@dataclass(frozen=True, slots=True)
class ArchiveInvestigationDefinition:
    archive_id: str
    title: str
    category: str
    unlock_day: int
    content: str
    evidence_level: str
    confidentiality: str
    result_fact_ids: tuple[str, ...]
    strategic_uses: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MetricBand:
    minimum: int
    maximum: int
    label: str


@dataclass(frozen=True, slots=True)
class BigFiveProfile:
    openness: int
    conscientiousness: int
    extraversion: int
    agreeableness: int
    neuroticism: int

    def __post_init__(self) -> None:
        for field_name in (
            "openness",
            "conscientiousness",
            "extraversion",
            "agreeableness",
            "neuroticism",
        ):
            value = getattr(self, field_name)
            if type(value) is not int:
                raise TypeError(f"{field_name} must be an integer")
            if not 0 <= value <= 100:
                raise ValueError(f"{field_name} must be between 0 and 100")

    def as_dict(self) -> dict[str, int]:
        return {
            "openness": self.openness,
            "conscientiousness": self.conscientiousness,
            "extraversion": self.extraversion,
            "agreeableness": self.agreeableness,
            "neuroticism": self.neuroticism,
        }


@dataclass(frozen=True, slots=True)
class NPCProfileStub:
    npc_id: str
    name: str
    state_tier: NPCStateTier
    profile_id: str | None = None
    initial_attitude: int = 50
    initial_anxiety: int = 50
    role_setting: str = ""
    big_five: BigFiveProfile | None = None
    source_line: int = 0


@dataclass(frozen=True, slots=True)
class HouseholdDefinition:
    """逐户测算底表；隐藏户群字段不得直接进入普通玩家 DTO。"""

    household_id: str
    representative_group: str
    representative_npc: str
    group_index: int
    is_shadow_household: bool
    registered_population: int
    actual_residents: int
    resettlement_population: int
    residential_structure: str
    legal_residential_area_m2: float
    homestead_recognized_m2: float
    homestead_over_m2: float
    contracted_land_mu: float
    other_land_mu: float
    other_land_note: str | None
    business_area_m2: float
    attachments_profile: str
    grave_or_shrine_profile: str
    hardship_tags: tuple[str, ...]
    medical_tags: tuple[str, ...]
    employment_startup_tags: tuple[str, ...]
    resettlement_preference: str
    ownership_status: str
    signing_lock_flag: str | None


@dataclass(frozen=True, slots=True)
class LimitedHouseholdSignatory:
    """仅在逐户合同中出场的签约人，不进入完整 NPC 主线与关系网。"""

    household_id: str
    name: str
    role_setting: str
    initial_position: str
    core_concern: str
    acceptance_condition: str
    refusal_trigger: str
    counteroffer_focus: str


@dataclass(frozen=True, slots=True)
class NPCDemandDefinition:
    """NPC 的单一核心处置目标；资源和状态只能由权威服务改写。"""

    demand_id: str
    npc_id: str
    title: str
    category: str
    description: str
    legal_disposition: str
    discover: dict
    commit: dict
    satisfy: dict
    consequences: dict


@dataclass(frozen=True, slots=True)
class ScriptPackage:
    package_id: str
    package_version: str
    content_hash: str
    status: str
    title: str
    action_rules: dict[str, ActionRule]
    calendar_segments: tuple[CalendarSegment, ...]
    fixed_events: tuple[FixedEventRule, ...]
    metric_bands: dict[str, tuple[MetricBand, ...]]
    npc_profiles: tuple[NPCProfileStub, ...]
    story_days: dict[int, StoryDayDefinition]
    decisions: dict[str, DecisionDefinition]
    origins: dict[str, OriginDefinition]
    facts: dict[str, FactDefinition]
    public_briefing: dict
    resource_actions: dict[str, ResourceActionDefinition]
    households: tuple[HouseholdDefinition, ...]
    initial_state: dict
    limited_household_signatories: tuple[LimitedHouseholdSignatory, ...] = ()
    npc_demands: tuple[NPCDemandDefinition, ...] = ()
    governance_config: dict | None = None
    gameplay_schema_version: int = 1
    origin_npc_attitude_modifiers: dict[str, dict[str, int]] | None = None
    trust_rules: dict | None = None
    npc_relationships: tuple[dict, ...] = ()
    relationship_subnetworks: dict[str, dict] | None = None
    npc_discovery_rules: dict | None = None
    night_agent_scenes: tuple[dict, ...] = ()
    night_agent_actions: dict[str, dict] | None = None
    night_agent_hard_outcomes: dict[str, dict] | None = None
    npc_social_roles: dict[str, tuple[str, ...]] | None = None
    interaction_opportunities: tuple[InteractionOpportunity, ...] = ()
    registered_flags: frozenset[str] = frozenset()
    map_locations: tuple[MapLocationDefinition, ...] = ()
    main_endings: tuple[MainEndingDefinition, ...] = ()
    sub_endings: tuple[SubEndingDefinition, ...] = ()
    ending_appendices: tuple[EndingAppendixDefinition, ...] = ()
    decision_catalog: tuple[ContentCatalogEntry, ...] = ()
    event_catalog: tuple[ContentCatalogEntry, ...] = ()
    source_sha256: str = ""
    role_turn_prompt: str = ""
    role_turn_prompt_version: str = "role-turn-v2"
    story_acceptance_matrix: tuple[dict, ...] = ()
    archive_investigations: tuple[ArchiveInvestigationDefinition, ...] = ()

    def action_cost_tier(self, story_day: int) -> ActionCostTier:
        matches = [item for item in self.calendar_segments if item.contains(story_day)]
        if len(matches) != 1:
            raise ValueError(f"story day {story_day} must match exactly one calendar segment")
        return matches[0].cost_tier

    def chapter_for(self, story_day: int) -> int:
        matches = [item for item in self.calendar_segments if item.contains(story_day)]
        if len(matches) != 1:
            raise ValueError(f"story day {story_day} must match exactly one calendar segment")
        return matches[0].chapter

    def story_day(self, story_day: int) -> StoryDayDefinition | None:
        return self.story_days.get(story_day)

    def contract_batch_for_representative(
        self,
        representative_npc: str,
    ) -> tuple[HouseholdDefinition, ...]:
        """返回代表户本人及其n个关联户；每一项后续仍生成独立合同。"""

        members = tuple(sorted(
            (
                item
                for item in self.households
                if item.representative_npc == representative_npc
            ),
            key=lambda item: item.group_index,
        ))
        if not members:
            raise KeyError(f"代表人物没有关联家庭：{representative_npc}")
        return members

    def limited_signatory_for(
        self,
        household_id: str,
    ) -> LimitedHouseholdSignatory | None:
        return next(
            (
                item
                for item in self.limited_household_signatories
                if item.household_id == household_id
            ),
            None,
        )
