from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class HouseholdSettlementEntry:
    """一笔可审计的真实签约入账事件。

    D75 前历史户数由冻结快照承接；D76-D89 的每次新增必须逐笔记录。
    """

    entry_id: str
    household_group_id: str
    household_count: int
    signed_day: int
    entry_batch: str
    entry_type: str
    source_node_id: str
    policy_version: str
    eligibility_registered_day: int
    early_reward_paid: bool = False
    validity_status: str = "valid"
    contract_id: str | None = None
    household_id: str | None = None
    resource_details: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.household_count <= 0:
            raise ValueError("household_count must be positive")
        if not 1 <= self.signed_day <= 89:
            raise ValueError("signed_day must be between 1 and 89")
        if self.entry_batch not in {"first_batch", "post75_confirmation"}:
            raise ValueError("invalid entry_batch")
        if self.validity_status not in {"valid", "void"}:
            raise ValueError("invalid validity_status")
        if self.entry_batch == "post75_confirmation":
            if not 76 <= self.signed_day <= 89:
                raise ValueError("post75 confirmation must use a D76-D89 date")
            if self.early_reward_paid:
                raise ValueError("post75 confirmation cannot receive early reward")


@dataclass(frozen=True, slots=True)
class D75SettlementSnapshot:
    """D75 夜间硬结算完成后的不可变首批快照与收口白名单。"""

    locked_day: int
    first_batch_signed_count: int
    pending_group_limits: dict[str, int] = field(default_factory=dict)
    policy_version: str = ""
    legacy_migrated: bool = False

    def __post_init__(self) -> None:
        if self.locked_day != 75:
            raise ValueError("D75 snapshot must be locked on day 75")
        if not 0 <= self.first_batch_signed_count <= 36:
            raise ValueError("first_batch_signed_count is outside 0-36")
        if any(value <= 0 for value in self.pending_group_limits.values()):
            raise ValueError("pending group limits must be positive")
