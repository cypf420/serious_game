from __future__ import annotations

import argparse
from collections import Counter
import json
import os
from pathlib import Path
import time

from serious_game_backend.config import Settings
from serious_game_backend.domain.llm import (
    ExpressionTask,
    GovernanceLLMContext,
    NightAgentContext,
    SelectionOption,
    SelectionTask,
)
from serious_game_backend.infrastructure.llm.openai_compatible import (
    OpenAICompatibleRoleLLMGateway,
)
from serious_game_backend.infrastructure.repositories.memory import (
    InMemoryLLMCallAuditRepository,
)


CAPABILITIES = (
    "single_choice",
    "multiple_choice",
    "expression",
    "night_followup",
    "contract_rendering",
    "document_rendering",
)


def validate_reliability_report(report: dict) -> None:
    """Fail closed unless every real-model capability clears both thresholds."""

    if int(report.get("fake_calls", 0)):
        raise ValueError("Fake calls are forbidden in the live reliability matrix")
    audit_providers = report.get("audit_providers")
    if not isinstance(audit_providers, dict) or not audit_providers:
        raise ValueError("provider audit evidence is missing")
    unexpected_providers = sorted(
        str(provider)
        for provider, count in audit_providers.items()
        if int(count) > 0 and str(provider) != "openai_compatible"
    )
    if unexpected_providers:
        raise ValueError(
            "unexpected provider audit evidence: " + ", ".join(unexpected_providers)
        )
    capabilities = report.get("capabilities")
    if not isinstance(capabilities, dict):
        raise ValueError("capability results are missing")
    missing = sorted(set(CAPABILITIES) - set(capabilities))
    if missing:
        raise ValueError("missing capabilities: " + ", ".join(missing))
    failures: list[str] = []
    for capability in CAPABILITIES:
        result = capabilities[capability]
        if int(result.get("total", 0)) <= 0:
            failures.append(f"{capability}: no real calls")
            continue
        first_rate = float(result.get("first_attempt_success_rate", 0.0))
        corrected_rate = float(result.get("corrected_success_rate", 0.0))
        if first_rate < 0.95:
            failures.append(f"{capability}: first attempt {first_rate:.3%} < 95%")
        if corrected_rate < 0.99:
            failures.append(f"{capability}: corrected {corrected_rate:.3%} < 99%")
    if failures:
        raise ValueError("; ".join(failures))


def run_capability(gateway, capability: str, index: int) -> None:
    common = {
        "session_id": "live_choice_expression_matrix",
        "account_id": "live_acceptance",
        "story_day": 55,
    }
    operation_id = f"live:{capability}:{index:03d}"
    if capability == "single_choice":
        gateway.select(SelectionTask(
            task_id=capability,
            role_id="npc_wu_xiuying",
            role_name="吴秀英",
            instruction="从两个合法办理方案中选择一个。",
            options=(
                SelectionOption("explain_policy", "先解释公开政策"),
                SelectionOption("verify_ledger", "先核对公开台账"),
            ),
            operation_id=operation_id,
            **common,
        ))
        return
    if capability == "multiple_choice":
        gateway.select(SelectionTask(
            task_id=capability,
            role_id="npc_zhang_li",
            role_name="张立",
            instruction="从三项公开材料中选择一至两项复核。",
            options=(
                SelectionOption("progress_ledger", "签约进度台账"),
                SelectionOption("public_notice", "公开告知书"),
                SelectionOption("responsibility_list", "整改责任清单"),
            ),
            selection_mode="multiple",
            minimum_choices=1,
            maximum_choices=2,
            operation_id=operation_id,
            **common,
        ))
        return
    if capability == "expression":
        gateway.express(ExpressionTask(
            task_id=capability,
            role_id="npc_wu_xiuying",
            role_name="吴秀英",
            confirmed_choice_ids=("verify_ledger",),
            choice_summaries={"verify_ledger": "先核对已经公开的36户台账"},
            allowed_facts=("柳林村共有36户。", "台账已向村民公开。"),
            persona="村民代表，说话直接克制。",
            context="县长询问下一步先做什么。",
            operation_id=operation_id,
            **common,
        ))
        return
    if capability == "night_followup":
        gateway.run_night_turn(NightAgentContext(
            operation_id=operation_id,
            scene_id="night_d55_environment_evidence",
            phase="followup_initiation",
            npc_id="npc_shi_wenbin",
            npc_name="石文斌",
            role_setting="环境干部，只依据登记材料发言。",
            big_five={},
            counterpart_ids=("npc_ke_qinian",),
            scene_goal="核对复检、治疗和证据保管落实情况。",
            allowed_followup_plans=({
                "plan_id": "followup_d55_environment",
                "label": "次日汇报复检和治疗落实",
                "followup_type": "cadre_meeting",
                "participant_ids": ["npc_shi_wenbin", "npc_ke_qinian"],
                "agenda": "核对复检治疗和证据保管。",
                "demands": ["明确责任和期限"],
                "urgency": "critical",
            },),
            followup_required=True,
            **common,
        ))
        return
    if capability == "contract_rendering":
        gateway.run_governance_task(GovernanceLLMContext(
            operation_id=operation_id,
            task="draft_contract",
            actor_id="contract_writer",
            actor_name="合同文书模型",
            actor_profile="只转写已经确认的合同条款。",
            payload={
                "contract_id": f"contract-live-{index:03d}",
                "household_id": "WU-01",
                "signatory_name": "吴秀英",
                "term_sheet": {
                    "policy_document_id": "doc_compensation_policy_v1",
                    "cash_amount": 45,
                    "budget_envelope": "property_land",
                    "housing_resource_id": "housing_d1_80",
                    "service_allocations": {"medical_retest": 1},
                    "payment_day": 56,
                    "move_out_day": 65,
                    "housing_delivery_day": 66,
                },
            },
            **common,
        ))
        return
    if capability == "document_rendering":
        gateway.run_governance_task(GovernanceLLMContext(
            operation_id=operation_id,
            task="draft_document",
            actor_id="document_writer",
            actor_name="行政文书模型",
            actor_profile="只转写已经确认的会议决议。",
            payload={
                "meeting_id": f"meeting-live-{index:03d}",
                "document_type": "专项调查通知",
                "title": "柳林村搬迁专项调查通知",
                "resolution": {
                    "decision": "开展专项调查",
                    "target_scope": "柳林村36户",
                    "responsible_ids": ["npc_zhao_jianguo"],
                    "deadline_day": 60,
                    "public_scope": ["专班"],
                    "resource_authorization_limits": {"risk_reserve": 10},
                },
            },
            **common,
        ))
        return
    raise ValueError(f"unknown capability: {capability}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repetitions", type=int, default=20)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    settings = Settings.from_env()
    settings.validate()
    if settings.role_llm_provider != "openai_compatible":
        raise SystemExit("live matrix requires ROLE_LLM_PROVIDER=openai_compatible")
    api_key = os.getenv(settings.role_llm_api_key_env, "").strip()
    if not api_key:
        raise SystemExit("configured real API key is missing")

    audits = InMemoryLLMCallAuditRepository()
    gateway = OpenAICompatibleRoleLLMGateway(settings, api_key, audits)
    outcomes: list[dict] = []
    started = time.perf_counter()
    for index in range(args.repetitions):
        for capability in CAPABILITIES:
            operation_id = f"live:{capability}:{index:03d}"
            before = len(audits.list_for_session("live_choice_expression_matrix"))
            try:
                run_capability(gateway, capability, index)
                error_code = None
                succeeded = True
            except Exception as exc:  # live acceptance must record all failures
                error_code = getattr(exc, "code", type(exc).__name__)
                succeeded = False
            new_audits = audits.list_for_session(
                "live_choice_expression_matrix"
            )[before:]
            successful_audit = next(
                (item for item in reversed(new_audits) if item.status == "succeeded"),
                None,
            )
            outcomes.append({
                "capability": capability,
                "iteration": index + 1,
                "succeeded": succeeded,
                "first_attempt": bool(
                    succeeded
                    and successful_audit is not None
                    and successful_audit.retry_count == 0
                ),
                "attempts": len(new_audits),
                "error_code": error_code,
                "operation_id": operation_id,
            })

    totals = Counter(item["capability"] for item in outcomes)
    succeeded = Counter(
        item["capability"] for item in outcomes if item["succeeded"]
    )
    first = Counter(
        item["capability"] for item in outcomes if item["first_attempt"]
    )
    audit_records = audits.list_for_session("live_choice_expression_matrix")
    audit_providers = Counter(item.provider for item in audit_records)
    report = {
        "provider": "openai_compatible",
        "model": settings.role_llm_model,
        "audit_providers": dict(audit_providers),
        "fake_calls": sum(
            count
            for provider, count in audit_providers.items()
            if "fake" in provider.casefold()
        ),
        "repetitions": args.repetitions,
        "logical_tasks": len(outcomes),
        "elapsed_seconds": round(time.perf_counter() - started, 3),
        "first_attempt_success_rate": round(
            sum(first.values()) / len(outcomes), 6
        ),
        "corrected_success_rate": round(
            sum(succeeded.values()) / len(outcomes), 6
        ),
        "capabilities": {
            capability: {
                "first_attempt": first[capability],
                "succeeded": succeeded[capability],
                "total": totals[capability],
                "first_attempt_success_rate": round(
                    first[capability] / totals[capability], 6
                ),
                "corrected_success_rate": round(
                    succeeded[capability] / totals[capability], 6
                ),
            }
            for capability in CAPABILITIES
        },
        "failures": [item for item in outcomes if not item["succeeded"]],
    }
    if args.output_dir is not None:
        args.output_dir.mkdir(parents=True, exist_ok=False)
        (args.output_dir / "capability-matrix.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    try:
        validate_reliability_report(report)
    except ValueError as exc:
        print(f"reliability gate failed: {exc}", flush=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
