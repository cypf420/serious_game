from __future__ import annotations

from dataclasses import replace

from serious_game_backend.application.scripted_delta_resolver import ScriptedDeltaResolver
from serious_game_backend.application.resource_availability import (
    unencumbered_budget,
)
from serious_game_backend.domain.errors import (
    ActionUnavailableError,
    ContentValidationError,
)
from serious_game_backend.domain.game_session import GameSession
from serious_game_backend.domain.game_state import SCORE_FIELDS
from serious_game_backend.domain.household_settlement import (
    D75SettlementSnapshot,
    HouseholdSettlementEntry,
)
from serious_game_backend.domain.script_package import ScriptPackage
from serious_game_backend.domain.story import ScriptedEffects


class ScriptedEffectService:
    """只执行剧本包声明的硬结算；区间按 session seed 稳定解析。"""

    _RESOURCE_AUTHORITIES = frozenset({"player_choice", "player_action"})

    _POST75_GROUP_RULES = {
        "dp6_02:b": (
            "lao_juetou",
            "acceptance_period_confirmation",
            "老倔头已入账",
        ),
        "dp6_03:a": (
            "miao_xiwang",
            "acceptance_period_confirmation",
            "苗喜旺已入账",
        ),
        "ev6_01:a": (
            "ning_dehai",
            "procedure_correction",
            "宁德海已入账",
        ),
    }
    _GROUP_LABELS = {
        "lao_juetou": "老倔头户",
        "miao_xiwang": "苗喜旺户",
        "ning_dehai": "宁德海户群",
        "deng_shouben": "邓守本户",
        "he_tiezhu": "何铁柱户群",
        "zhou_dashan": "周大山户群",
    }
    _POST75_NARRATIVES = {
        "lao_juetou": "实际安置条件完成核验后，老倔头按真实日期签署协议，进入验收期确认台账。",
        "miao_xiwang": "旧预签文件已按本期统一方案重新说明，苗喜旺签署正式协议，进入验收期确认台账。",
        "ning_dehai": "两户代签材料已撤销并由本人重新核验、签署，宁德海户群进入程序补正台账。",
        "deng_shouben": "安置房与医疗兜底落实到书面材料后，邓守本自愿签署协议，进入验收期确认台账。",
        "he_tiezhu": "血铅善后作为独立公共责任落实后，何铁柱与关联户按真实日期签署搬迁协议。",
        "zhou_dashan": "此前登记在办的祠堂用地手续依法办结后，周大山与关联户按真实日期完成签署。",
    }

    def __init__(self, resolver: ScriptedDeltaResolver) -> None:
        self._resolver = resolver

    def apply(
        self,
        session: GameSession,
        package: ScriptPackage,
        effects: ScriptedEffects,
        *,
        source_id: str,
        resource_authority: str = "none",
        resource_reference: str | None = None,
    ) -> None:
        blocked_contract_flags = frozenset(
            flag
            for flag in effects.open_flags
            if flag.endswith(("已入账", "已签"))
        ) if bool(
            (package.governance_config or {}).get(
                "contract_signing_authoritative", False
            )
        ) else frozenset()
        effective_open_flags = effects.open_flags - blocked_contract_flags
        unknown_flags = (
            effective_open_flags | effects.close_flags
        ) - package.registered_flags
        if unknown_flags:
            raise ContentValidationError(
                "硬结算引用未注册旗标",
                details={"flags": sorted(unknown_flags), "source_id": source_id},
            )

        allowed_state_values = {
            "lead_roster_disposition": {
                "未获取", "己方封存", "呈交上级", "交给记者", "被销毁"
            }
        }
        for key, value in effects.state_assignments.items():
            if key not in allowed_state_values or value not in allowed_state_values[key]:
                raise ContentValidationError(
                    "硬结算尝试写入未登记的多值状态",
                    details={"field": key, "value": value, "source_id": source_id},
                )

        if blocked_contract_flags:
            session.logs.append({
                "type": "legacy_contract_flag_suppressed",
                "source_id": source_id,
                "story_day": session.game_state.story_day,
                "flags": sorted(blocked_contract_flags),
                "note": "进入拟约不等于已签约或已入账",
                "visible_to_player": False,
            })

        attitude_group = {
            "蒋崇岳背书", "蒋崇岳默许", "蒋崇岳弃保", "蒋崇岳否决",
            "flag_jiang_endorses", "flag_jiang_acquiesces",
            "flag_jiang_abandons", "flag_jiang_veto",
        }
        opened_attitudes = effective_open_flags & attitude_group
        if len(opened_attitudes) > 1:
            raise ContentValidationError(
                "同一结算不能同时开启多个蒋崇岳立场",
                details={"flags": sorted(opened_attitudes), "source_id": source_id},
            )

        updates: dict[str, int] = {}
        for field_name, (minimum, maximum) in effects.metric_deltas.items():
            if field_name == "fatigue":
                continue  # Legacy packages may still declare the retired metric.
            if field_name not in SCORE_FIELDS:
                raise ContentValidationError(
                    "硬结算尝试写入未授权字段",
                    details={"field": field_name, "source_id": source_id},
                )
            delta = self._resolver.resolve(
                minimum,
                maximum,
                random_seed=session.random_seed,
                source_id=f"{source_id}:{field_name}",
            )
            current = getattr(session.game_state, field_name)
            updates[field_name] = max(0, min(100, current + delta))

        ledger_bounds = {
            "budget_remaining": (0, None),
            "signed_households": (0, session.game_state.total_households),
            "reported_signed_households": (0, session.game_state.total_households),
        }
        budget_change: dict | None = None
        for field_name, (minimum, maximum) in effects.ledger_deltas.items():
            if field_name == "chapter_overtime_count":
                continue  # Retired mechanic; never reintroduce it from old content.
            if field_name not in ledger_bounds:
                raise ContentValidationError(
                    "硬结算尝试写入未授权台账字段",
                    details={"field": field_name, "source_id": source_id},
                )
            delta = self._resolver.resolve(
                minimum,
                maximum,
                random_seed=session.random_seed,
                source_id=f"{source_id}:{field_name}",
            )
            if field_name == "budget_remaining" and (
                resource_authority not in self._RESOURCE_AUTHORITIES
                or not resource_reference
            ):
                raise ContentValidationError(
                    "资源变化缺少允许的玩家选择来源",
                    details={
                        "field": field_name,
                        "source_id": source_id,
                        "resource_authority": resource_authority,
                        "required_authorities": sorted(
                            self._RESOURCE_AUTHORITIES
                        ),
                    },
                )
            if (
                field_name == "signed_households"
                and bool(
                    (package.governance_config or {}).get(
                        "contract_signing_authoritative", False
                    )
                )
            ):
                session.logs.append({
                    "type": "scripted_signing_intent",
                    "source_id": source_id,
                    "story_day": session.game_state.story_day,
                    "proposed_household_delta": delta,
                    "note": "剧情节点不再替代逐户合同签署",
                    "visible_to_player": False,
                })
                continue
            if field_name == "signed_households" and session.game_state.story_day >= 76:
                updates[field_name] = self._apply_post75_settlement(
                    session,
                    package,
                    effects,
                    source_id=source_id,
                    household_delta=delta,
                )
                continue
            lower, upper = ledger_bounds[field_name]
            value = max(lower, getattr(session.game_state, field_name) + delta)
            updates[field_name] = min(upper, value) if upper is not None else value
            if field_name == "budget_remaining":
                before = session.game_state.budget_remaining
                after = updates[field_name]
                if delta < 0:
                    actual_spend = before - after
                    spendable = unencumbered_budget(session)
                    if actual_spend > spendable:
                        raise ActionUnavailableError(
                            "本次选择会占用已经向合同或文件承诺的预算",
                            details={
                                "required": actual_spend,
                                "available_unencumbered": spendable,
                                "ledger_remaining": before,
                                "source_id": resource_reference,
                            },
                        )
                    updates["budget_paid"] = session.game_state.budget_paid + actual_spend
                elif delta > 0:
                    actual_income = after - before
                    updates["budget_approved_adjustments"] = (
                        session.game_state.budget_approved_adjustments + actual_income
                    )
                budget_change = {
                    "entry_id": (
                        f"resource:{session.game_state.story_day}:"
                        f"{len(session.resource_ledger_entries) + 1}"
                    ),
                    "story_day": session.game_state.story_day,
                    "change_kind": (
                        "payment" if after < before else "approved_adjustment"
                    ),
                    "source_type": resource_authority,
                    "source_id": resource_reference,
                    "script_source_id": source_id,
                    "resource_id": "budget_remaining",
                    "delta": after - before,
                    "before": before,
                    "after": after,
                    "payment_status": (
                        "paid" if after < before else "available"
                    ),
                }

        if updates:
            session.game_state = replace(session.game_state, **updates)
        if budget_change is not None:
            session.resource_ledger_entries.append(budget_change)
        session.flags.difference_update(effects.close_flags)
        if opened_attitudes:
            session.flags.difference_update(attitude_group - opened_attitudes)
        session.flags.update(effective_open_flags)
        session.state_values.update(effects.state_assignments)
        session.logs.append({
            "type": "scripted_effect",
            "source_id": source_id,
            "story_day": session.game_state.story_day,
            "authority": "script",
            "visible_to_player": False,
        })

    def freeze_d75_roster(
        self,
        session: GameSession,
        package: ScriptPackage,
    ) -> D75SettlementSnapshot:
        """必须在 D75 夜间所有硬结算完成后调用。"""
        if session.d75_settlement_snapshot is not None:
            return session.d75_settlement_snapshot
        if session.game_state.story_day != 75:
            raise ContentValidationError(
                "首批签约名册只能在 D75 夜间冻结",
                details={"story_day": session.game_state.story_day},
            )
        snapshot = D75SettlementSnapshot(
            locked_day=75,
            first_batch_signed_count=session.game_state.signed_households,
            pending_group_limits=self._post75_pending_limits(session.flags),
            policy_version=package.package_version,
        )
        session.d75_settlement_snapshot = snapshot
        session.logs.append({
            "type": "d75_roster_locked",
            "story_day": 75,
            "first_batch_signed_count": snapshot.first_batch_signed_count,
            "pending_group_ids": sorted(snapshot.pending_group_limits),
            "early_signup_reward_closed": True,
            "ordinary_campaign_closed": True,
            "visible_to_player": False,
        })
        session.append_narrative(
            story_day=75,
            kind="settlement_notice",
            text=(
                "D75 首批进度名册与提前签约奖励资格已经冻结。"
                "D76 至 D89 只处理此前登记的未决事项，全部按真实日期进入验收期台账。"
            ),
            content_instance_id="settlement:d75_roster_locked",
        )
        return snapshot

    def _apply_post75_settlement(
        self,
        session: GameSession,
        package: ScriptPackage,
        effects: ScriptedEffects,
        *,
        source_id: str,
        household_delta: int,
    ) -> int:
        if household_delta == 0:
            return session.game_state.signed_households
        if household_delta < 0:
            raise ContentValidationError(
                "D75 后真实签约台账不允许通过剧情节点扣减",
                details={"source_id": source_id, "delta": household_delta},
            )
        day = session.game_state.story_day
        if day > 89:
            raise ContentValidationError(
                "D90 只读最终签约台账，不得新增户数",
                details={"source_id": source_id, "story_day": day},
            )
        if session.d75_settlement_snapshot is None:
            self._migrate_legacy_snapshot(session, package)

        audited_before = session.audited_signed_households()
        if audited_before != session.game_state.signed_households:
            raise ContentValidationError(
                "真实签约总数与D75分批台账不一致",
                details={
                    "source_id": source_id,
                    "aggregate": session.game_state.signed_households,
                    "audited": audited_before,
                },
            )
        group_id, entry_type = self._post75_rule(
            source_id=source_id,
            effects=effects,
        )
        snapshot = session.d75_settlement_snapshot
        assert snapshot is not None
        limit = snapshot.pending_group_limits.get(group_id)
        if limit is None:
            raise ContentValidationError(
                "D75 后入账户群未在首批冻结时登记",
                details={"source_id": source_id, "household_group_id": group_id},
            )
        already_entered = sum(
            item.household_count
            for item in session.household_settlement_entries
            if item.household_group_id == group_id
            and item.validity_status == "valid"
        )
        if household_delta > limit - already_entered:
            raise ContentValidationError(
                "D75 后入账超过该户群冻结额度",
                details={
                    "source_id": source_id,
                    "household_group_id": group_id,
                    "limit": limit,
                    "already_entered": already_entered,
                    "requested": household_delta,
                },
            )
        entry_id = f"post75:{day}:{source_id}:{group_id}"
        duplicate = next(
            (
                item
                for item in session.household_settlement_entries
                if item.entry_id == entry_id
            ),
            None,
        )
        if duplicate is not None:
            if duplicate.household_count != household_delta:
                raise ContentValidationError(
                    "同一验收期签约事件被复用为不同户数",
                    details={"entry_id": entry_id},
                )
            return session.game_state.signed_households

        new_total = audited_before + household_delta
        if new_total > session.game_state.total_households:
            raise ContentValidationError(
                "真实签约事件将导致户数超过36户",
                details={"source_id": source_id, "new_total": new_total},
            )
        session.household_settlement_entries.append(HouseholdSettlementEntry(
            entry_id=entry_id,
            household_group_id=group_id,
            household_count=household_delta,
            signed_day=day,
            entry_batch="post75_confirmation",
            entry_type=entry_type,
            source_node_id=source_id,
            policy_version=package.package_version,
            eligibility_registered_day=75,
            early_reward_paid=False,
        ))
        session.append_narrative(
            story_day=day,
            kind="settlement_confirmation",
            text=self._POST75_NARRATIVES[group_id],
            content_instance_id=f"settlement:{entry_id}",
        )
        session.logs.append({
            "type": "household_settlement",
            "entry_id": entry_id,
            "story_day": day,
            "household_group_id": group_id,
            "household_count": household_delta,
            "entry_batch": "post75_confirmation",
            "entry_type": entry_type,
            "source_id": source_id,
            "early_reward_paid": False,
            "visible_to_player": False,
        })
        return new_total

    def _migrate_legacy_snapshot(
        self,
        session: GameSession,
        package: ScriptPackage,
    ) -> None:
        """兼容旧开发存档：保总数，但明确标记首批来源无法追溯。"""
        if session.game_state.story_day < 76:
            raise ContentValidationError("D75 快照尚未生成")
        session.d75_settlement_snapshot = D75SettlementSnapshot(
            locked_day=75,
            first_batch_signed_count=session.game_state.signed_households,
            pending_group_limits=self._post75_pending_limits(session.flags),
            policy_version=package.package_version,
            legacy_migrated=True,
        )
        session.logs.append({
            "type": "legacy_d75_snapshot_migrated",
            "story_day": session.game_state.story_day,
            "unattributed_signed_count": session.game_state.signed_households,
            "visible_to_player": False,
        })

    @classmethod
    def _post75_rule(
        cls,
        *,
        source_id: str,
        effects: ScriptedEffects,
    ) -> tuple[str, str]:
        exact = cls._POST75_GROUP_RULES.get(source_id)
        if exact is not None and exact[2] in effects.open_flags:
            return exact[0], exact[1]
        if (
            source_id.startswith("dp6_07:")
            and "邓守本已入账" in effects.open_flags
        ):
            return "deng_shouben", "acceptance_period_confirmation"
        if source_id.startswith("night_d86:branch_"):
            if "何铁柱已入账" in effects.open_flags:
                return "he_tiezhu", "cross_chapter_redemption"
            if "周大山归心已入账" in effects.open_flags:
                return "zhou_dashan", "cross_chapter_redemption"
        raise ContentValidationError(
            "D75 后签约事件不在冻结白名单节点中",
            details={
                "source_id": source_id,
                "open_flags": sorted(effects.open_flags),
            },
        )

    @staticmethod
    def _post75_pending_limits(flags: set[str]) -> dict[str, int]:
        pending: dict[str, int] = {}
        if "老倔头已入账" not in flags:
            pending["lao_juetou"] = 1
        if "苗喜旺已入账" not in flags:
            pending["miao_xiwang"] = 1
        if not {"宁德海已入账", "宁德海线已锁死"} & flags:
            pending["ning_dehai"] = 2
        if "邓守本已入账" not in flags:
            pending["deng_shouben"] = 1
        if (
            "何铁柱已入账" not in flags
            and bool({"何铁柱已冷", "何铁柱肯再谈", "空头承诺已出口"} & flags)
        ):
            pending["he_tiezhu"] = 4
        if (
            "周大山归心已入账" not in flags
            and "祖坟被冒犯" not in flags
            and "周大山肯等" in flags
        ):
            pending["zhou_dashan"] = (
                4 if "周大山预付已入账" in flags else 6
            )
        return pending
