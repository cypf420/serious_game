from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

import tools.run_real_v3_routes as real_routes_module
from serious_game_backend.config import Settings
from serious_game_backend.domain.errors import RoleLLMUnavailableError
from serious_game_backend.infrastructure.script_packages.file_loader import (
    FileScriptPackageLoader,
)
from tools.full_acceptance.ending_witnesses import load_witnesses
from tools.run_full_acceptance import run_stages, workspace_fingerprint
from tools.build_full_acceptance_report import build_ending_operation_markdown
from tools.run_browser_acceptance import validate_browser_report
from tools.run_real_feature_workflows import (
    _drain_group_conversations,
    _with_recovery_decision_policy,
    validate_feature_workflow_report,
)
from tools.run_real_night_matrix import (
    FOLLOWUP_PLAN_IDS,
    aggregate_night_matrix_summary,
    _post_group,
    _profile_for_plan,
    _resolve_prior_group,
    _strategy_texts,
)
from tools.run_real_v3_routes import (
    build_route_run_metadata,
    build_route_summary,
    execute_route_profiles,
    build_ending_operation_record,
    credible_group_replies,
    load_completed_route_evidence,
    prepare_output_run,
    select_route_profiles,
    validate_resume_metadata,
    validate_profile_catalog,
    validate_real_runner_settings,
    validate_route_result,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = BACKEND_ROOT / "content" / "packages" / "pkg_gameplay_v3"
PROFILE_PATH = PACKAGE_ROOT / "acceptance_route_profiles.json"


def test_group_reply_strategy_prefers_specific_agenda_over_generic_material_word() -> None:
    environmental = credible_group_replies({
        "agenda": "环保复核、儿童治疗与原始材料保管",
    })
    assert any("第三方检测" in item and "县医院" in item for item in environmental)
    assert all("纪检人员" not in item for item in environmental)

    public = credible_group_replies({
        "agenda": "公开监督、记者查阅与材料更正",
    })
    assert any("公开" in item and "记者" in item for item in public)
    assert all("纪检人员" not in item for item in public)


def test_environment_reply_covers_treatment_and_evidence_custody() -> None:
    replies = credible_group_replies({
        "agenda": "环保复核、儿童治疗与原始材料保管",
    })
    combined = "".join(replies)

    assert "县医院负责儿童复检和转诊" in combined
    assert "第三方机构负责双份盲检" in combined
    assert "每次交接都登记去向" in combined


def test_contract_review_retries_unavailable_model_only_after_state_restoration(
    tmp_path: Path,
) -> None:
    draft_state = {
        "state_version": 17,
        "visible_state": {
            "status": "active",
            "story": {"day": 71},
            "ledger": {"signed_households": {"signed": 4}},
        },
    }

    class Response:
        def __init__(self, status_code: int, payload: dict) -> None:
            self.status_code = status_code
            self._payload = payload
            self.content = b"response"
            self.text = str(payload)

        def json(self) -> dict:
            return self._payload

    class Client:
        def __init__(self) -> None:
            self.post_count = 0

        def post(self, *_args, **_kwargs) -> Response:
            self.post_count += 1
            if self.post_count == 1:
                return Response(503, {
                    "error": {
                        "code": "ROLE_LLM_UNAVAILABLE",
                        "message": "模型服务暂时不可用",
                    },
                })
            return Response(200, {
                **draft_state,
                "contract": {"contract_id": "contract-1", "status": "accepted"},
            })

        def get(self, *_args, **_kwargs) -> Response:
            return Response(200, draft_state)

    runner = real_routes_module.RealRouteRunner(
        Settings(environment="test"), tmp_path
    )
    client = Client()

    response = runner.review_contract_for_route(
        client,
        "session-1",
        {"X-Account-ID": "account-1"},
        "contract-1",
        draft_state,
    )

    assert response.status_code == 200
    assert client.post_count == 2
    assert runner.operation_retries_by_session["session-1"] == [{
        "operation": "contract-review:contract-1",
        "attempt": 1,
        "state_version": 17,
        "state_restored": True,
        "error_code": "ROLE_LLM_UNAVAILABLE",
    }]


def test_contract_review_survives_three_consecutive_transient_outages(
    tmp_path: Path,
) -> None:
    state = {
        "state_version": 17,
        "visible_state": {"status": "active", "story": {"day": 67}},
    }

    class Response:
        content = b"response"

        def __init__(self, status_code: int, payload: dict) -> None:
            self.status_code = status_code
            self.payload = payload
            self.text = str(payload)

        def json(self) -> dict:
            return self.payload

    class Client:
        def __init__(self) -> None:
            self.post_count = 0

        def get(self, *_args, **_kwargs) -> Response:
            return Response(200, state)

        def post(self, *_args, **_kwargs) -> Response:
            self.post_count += 1
            if self.post_count <= 3:
                return Response(503, {
                    "error": {"code": "ROLE_LLM_UNAVAILABLE"},
                })
            return Response(200, {
                **state,
                "contract": {"contract_id": "contract-1", "status": "accepted"},
            })

    runner = real_routes_module.RealRouteRunner(
        Settings(environment="test"), tmp_path, retry_delays=(0, 0, 0, 0, 0)
    )
    client = Client()

    response = runner.review_contract_for_route(
        client,
        "session-1",
        {"X-Account-ID": "account-1"},
        "contract-1",
        state,
    )

    assert response.status_code == 200
    assert client.post_count == 4
    assert len(runner.operation_retries_by_session["session-1"]) == 3
    assert all(
        item["state_restored"] is True
        for item in runner.operation_retries_by_session["session-1"]
    )


def test_route_start_retries_transient_capability_probe_outages(
    tmp_path: Path,
) -> None:
    expected = (object(), object(), "session-1", {"X-Account-ID": "account-1"})

    class Runner(real_routes_module.RealRouteRunner):
        def __init__(self) -> None:
            super().__init__(
                Settings(environment="test"),
                tmp_path,
                retry_delays=(0, 0, 0, 0, 0),
            )
            self.build_attempts = 0

        def build_real_runner(self, route_index: int):
            self.build_attempts += 1
            if self.build_attempts <= 3:
                raise RoleLLMUnavailableError("HTTP 503")
            return expected

    runner = Runner()

    result = runner.build_real_runner_with_retry(56)

    assert result == expected
    assert runner.build_attempts == 4
    assert runner.capability_probe_retries == [
        {"route_index": 56, "attempt": 1, "error_code": "ROLE_LLM_UNAVAILABLE"},
        {"route_index": 56, "attempt": 2, "error_code": "ROLE_LLM_UNAVAILABLE"},
        {"route_index": 56, "attempt": 3, "error_code": "ROLE_LLM_UNAVAILABLE"},
    ]


def test_governance_turn_retries_with_retry_flag_after_state_restoration(
    tmp_path: Path,
) -> None:
    state = {
        "state_version": 8,
        "visible_state": {
            "status": "active",
            "story": {"day": 67},
            "active_governance_action": {"action_instance_id": "action-1"},
        },
    }

    class Response:
        content = b"response"

        def __init__(self, status_code: int, payload: dict) -> None:
            self.status_code = status_code
            self.payload = payload
            self.text = str(payload)

        def json(self) -> dict:
            return self.payload

    class Client:
        def __init__(self) -> None:
            self.payloads: list[dict] = []

        def get(self, *_args, **_kwargs) -> Response:
            return Response(200, state)

        def post(self, *_args, **kwargs) -> Response:
            self.payloads.append(dict(kwargs["json"]))
            if len(self.payloads) == 1:
                return Response(503, {
                    "error": {"code": "ROLE_LLM_UNAVAILABLE"},
                })
            return Response(200, {**state, "governance_turn": {"text": "同意核对"}})

    runner = real_routes_module.RealRouteRunner(
        Settings(environment="test"), tmp_path
    )
    client = Client()
    response = runner.governance_turn_for_route(
        client,
        "session-1",
        {"X-Account-ID": "account-1"},
        "action-1",
        state,
        player_text="请逐户核对合同",
        client_action_id="contract-action-turn-1",
    )

    assert response.status_code == 200
    assert [item["retry"] for item in client.payloads] == [False, True]
    assert runner.operation_retries_by_session["session-1"][0][
        "state_restored"
    ] is True


def test_group_conversation_turn_retries_unavailable_model_atomically(
    tmp_path: Path,
) -> None:
    state = {
        "state_version": 40,
        "visible_state": {
            "status": "active",
            "story": {"day": 40},
            "active_group_conversation": {
                "conversation_id": "group-d40",
                "phase": "active",
            },
        },
    }

    class Response:
        content = b"response"

        def __init__(self, status_code: int, payload: dict) -> None:
            self.status_code = status_code
            self.payload = payload
            self.text = str(payload)

        def json(self) -> dict:
            return self.payload

    class Client:
        def __init__(self) -> None:
            self.payloads: list[dict] = []

        def get(self, *_args, **_kwargs) -> Response:
            return Response(200, state)

        def post(self, *_args, **kwargs) -> Response:
            self.payloads.append(dict(kwargs["json"]))
            if len(self.payloads) == 1:
                return Response(503, {
                    "error": {"code": "ROLE_LLM_UNAVAILABLE"},
                })
            return Response(200, {
                **state,
                "group_turn": {"text": "我会逐户说明迁坟和安置安排。"},
            })

    runner = real_routes_module.RealRouteRunner(
        Settings(environment="test"), tmp_path
    )
    client = Client()
    response = runner.group_conversation_turn_for_route(
        client,
        "session-1",
        {"X-Account-ID": "account-1"},
        {
            "state_version": 40,
            "client_action_id": "ending-03c-day-40-group-01",
            "player_text": "我会逐户给出方案。",
        },
    )

    assert response.status_code == 200
    assert [item["retry"] for item in client.payloads] == [False, True]
    assert runner.operation_retries_by_session["session-1"] == [{
        "operation": "ending-03c-day-40-group-01",
        "attempt": 1,
        "state_version": 40,
        "state_restored": True,
        "error_code": "ROLE_LLM_UNAVAILABLE",
    }]


def test_night_matrix_retries_real_retryable_response_with_full_dto_fingerprint() -> None:
    state = {
        "state_version": 40,
        "visible_state": {
            "status": "active",
            "story": {"day": 40},
            "active_group_conversation": {"conversation_id": "group-d40"},
        },
    }

    class Response:
        content = b"response"

        def __init__(self, status_code: int, payload: dict) -> None:
            self.status_code = status_code
            self.payload = payload
            self.text = str(payload)

        def json(self) -> dict:
            return self.payload

    class Client:
        def __init__(self) -> None:
            self.posts = 0

        def post(self, *_args, **_kwargs) -> Response:
            self.posts += 1
            if self.posts == 1:
                return Response(503, {"error": {"code": "ROLE_LLM_RESPONSE_RETRYABLE"}})
            return Response(200, state)

        def get(self, *_args, **_kwargs) -> Response:
            return Response(200, state)

    recoveries: list[dict] = []
    result = _post_group(
        Client(), "session-night", {"X-Account-ID": "account-night"}, state,
        player_text="我会尽快研究，但现在不能给出责任人。",
        action_id="night-invalid-response-1",
        recovery_log=recoveries,
    )

    assert result == state
    assert recoveries[0]["operation"] == "night-invalid-response-1"
    assert recoveries[0]["error_code"] == "ROLE_LLM_RESPONSE_RETRYABLE"
    assert recoveries[0]["state_restored"] is True
    assert len(recoveries[0]["before_public_state_sha256"]) == 64
    assert recoveries[0]["before_public_state_sha256"] == recoveries[0]["after_public_state_sha256"]


def test_night_matrix_aborts_before_retry_when_any_public_dto_field_changes() -> None:
    state = {
        "state_version": 40,
        "visible_state": {
            "status": "active", "story": {"day": 40},
            "indicators": {"public_trust": "高"},
            "active_group_conversation": {"conversation_id": "group-d40"},
        },
    }
    changed = {
        **state,
        "visible_state": {**state["visible_state"], "indicators": {"public_trust": "低"}},
    }

    class Response:
        content = b"response"
        def __init__(self, status_code: int, payload: dict) -> None:
            self.status_code, self.payload, self.text = status_code, payload, str(payload)
        def json(self) -> dict:
            return self.payload

    class Client:
        def __init__(self) -> None:
            self.posts = 0
        def post(self, *_args, **_kwargs) -> Response:
            self.posts += 1
            return Response(503, {"error": {"code": "ROLE_LLM_RESPONSE_RETRYABLE"}})
        def get(self, *_args, **_kwargs) -> Response:
            return Response(200, changed)

    recoveries: list[dict] = []
    client = Client()
    with pytest.raises(AssertionError, match="changed the authoritative state"):
        _post_group(client, "session-night", {"X-Account-ID": "account-night"}, state,
                    player_text="请说明责任。", action_id="night-state-change-1",
                    recovery_log=recoveries)
    assert client.posts == 1
    assert recoveries[0]["state_restored"] is False
    assert recoveries[0]["before_public_state_sha256"] != recoveries[0]["after_public_state_sha256"]


def test_night_matrix_does_not_retry_invalid_response_502() -> None:
    state = {"state_version": 40, "visible_state": {"status": "active"}}

    class Response:
        content = b"response"
        status_code = 502
        text = "invalid model response"
        def json(self) -> dict:
            return {"error": {"code": "ROLE_LLM_INVALID_RESPONSE"}}

    class Client:
        def __init__(self) -> None:
            self.posts = 0
        def post(self, *_args, **_kwargs) -> Response:
            self.posts += 1
            return Response()
        def get(self, *_args, **_kwargs) -> Response:
            raise AssertionError("502 must not enter outer retry recovery")

    client = Client()
    with pytest.raises(AssertionError, match="HTTP 502"):
        _post_group(client, "session-night", {"X-Account-ID": "account-night"}, state,
                    player_text="请说明责任。", action_id="night-invalid-1", recovery_log=[])
    assert client.posts == 1


def test_resolve_prior_group_explicitly_passes_recovery_log_to_retrying_turn() -> None:
    initial = {"state_version": 40, "visible_state": {"active_group_conversation": {
        "phase": "active", "followup_plan_id": "followup_d10_county_reporting",
    }}}
    settled = {"state_version": 41, "visible_state": {"active_group_conversation": None}}

    class Response:
        content = b"response"
        def __init__(self, status_code: int, payload: dict) -> None:
            self.status_code, self.payload, self.text = status_code, payload, str(payload)
        def json(self) -> dict:
            return self.payload

    class Client:
        def __init__(self) -> None:
            self.posts = 0
        def post(self, *_args, **_kwargs) -> Response:
            self.posts += 1
            if self.posts == 1:
                return Response(503, {"error": {"code": "ROLE_LLM_RESPONSE_RETRYABLE"}})
            return Response(200, settled)
        def get(self, *_args, **_kwargs) -> Response:
            return Response(200, initial)

    recovery_log: list[dict] = []
    assert _resolve_prior_group(Client(), "session-night", {"X-Account-ID": "account-night"},
                                initial, "prior", recovery_log=recovery_log) == settled
    assert recovery_log[0]["operation"] == "prior-turn-01"


def test_night_matrix_summary_aggregates_multiple_codes_and_validator_rejects_inconsistency() -> None:
    from tools.run_real_night_matrix import validate_night_matrix_report

    def case(plan_id: str, strategy: str, count: int, codes: dict[str, int]) -> dict:
        return {"plan_id": plan_id, "strategy": strategy, "provider": "openai_compatible",
                "fake_calls": 0, "template_fallback_count": 0, "silent_fallback_count": 0,
                "partial_commit_count": 0, "triggered_legally": True, "model_audits": 1,
                "failed_model_audit_count": count, "failed_model_audit_error_codes": codes,
                "failed_calls": [], "transcript": [{"speaker_type": "npc"}],
                "participant_states": [{"npc_id": "npc"}], "morning_card": "done",
                "memory_check": True, "memory_count": 1,
                "resolved": strategy == "credible", "finished": strategy == "credible",
                "resolved_after_turn": 2 if strategy == "credible" else None,
                "ordinary_contact_combinations": ["scene:a->b"], "legal_no_contact_count": 0,
                "technical_failure_count": 0}
    cases = [case(plan, strategy, 0, {}) for plan in FOLLOWUP_PLAN_IDS for strategy in ("credible", "vague", "contradictory", "injection")]
    def recovery(code: str = "ROLE_LLM_RESPONSE_RETRYABLE") -> dict:
        return {
            "error_code": code,
            "state_restored": True,
            "before_public_state_sha256": "a" * 64,
            "after_public_state_sha256": "a" * 64,
        }

    cases[0].update(
        failed_model_audit_count=3,
        failed_model_audit_error_codes={
            "ROLE_LLM_RESPONSE_RETRYABLE": 2,
            "ROLE_LLM_UNAVAILABLE": 1,
        },
        failed_calls=[recovery(), recovery()],
    )
    report = aggregate_night_matrix_summary(cases, Settings(environment="test"))
    validate_night_matrix_report(report)
    assert report["failed_model_audit_error_codes"] == {"ROLE_LLM_RESPONSE_RETRYABLE": 2, "ROLE_LLM_UNAVAILABLE": 1}
    report["failed_model_audit_count"] = 2
    with pytest.raises(AssertionError, match="failed audit count"):
        validate_night_matrix_report(report)
    report["failed_model_audit_count"] = 3
    report["cases"][0]["failed_calls"] = [{"error_code": "ROLE_LLM_RESPONSE_RETRYABLE"}]
    with pytest.raises(AssertionError, match="recovery audit is incomplete"):
        validate_night_matrix_report(report)
    report["cases"][0]["failed_calls"] = []
    with pytest.raises(AssertionError, match="retryable.*recovery"):
        validate_night_matrix_report(report)
    report["cases"][0]["failed_calls"] = [
        {**recovery(), "state_restored": False}, recovery(),
    ]
    with pytest.raises(AssertionError, match="was not restored"):
        validate_night_matrix_report(report)
    report["cases"][0]["failed_calls"] = [
        {**recovery(), "after_public_state_sha256": "b" * 64}, recovery(),
    ]
    with pytest.raises(AssertionError, match="hashes disagree"):
        validate_night_matrix_report(report)


def test_feature_workflow_group_turn_uses_real_runner_model_write_hook() -> None:
    initial = {
        "state_version": 40,
        "visible_state": {
            "active_group_conversation": {
                "conversation_id": "group-d40",
                "phase": "active",
                "agenda": "迁坟与安置",
            },
        },
    }
    completed = {
        "state_version": 41,
        "visible_state": {"active_group_conversation": None},
    }

    class Response:
        status_code = 200
        content = b"response"
        text = "ok"

        def json(self) -> dict:
            return completed

    class Client:
        def post(self, *_args, **_kwargs):
            raise AssertionError("feature workflow bypassed the real runner hook")

    class Runner:
        def __init__(self) -> None:
            self.calls: list[dict] = []

        def group_conversation_turn_for_route(
            self, _client, session_id, headers, body
        ) -> Response:
            self.calls.append({
                "session_id": session_id,
                "headers": headers,
                "body": dict(body),
            })
            return Response()

    runner = Runner()
    result = _drain_group_conversations(
        Client(),
        "session-1",
        {"X-Account-ID": "account-1"},
        initial,
        "feature-group-d40",
        runner,
    )

    assert result == completed
    assert len(runner.calls) == 1
    assert runner.calls[0]["body"]["state_version"] == 40
    assert runner.calls[0]["body"]["client_action_id"].startswith(
        "feature-group-d40-01"
    )
    assert runner.calls[0]["body"]["player_text"]


def test_contract_terms_retry_does_not_add_unsupported_retry_field(
    tmp_path: Path,
) -> None:
    state = {
        "state_version": 21,
        "visible_state": {
            "status": "active",
            "story": {"day": 67},
        },
    }

    class Response:
        content = b"response"

        def __init__(self, status_code: int, payload: dict) -> None:
            self.status_code = status_code
            self.payload = payload
            self.text = str(payload)

        def json(self) -> dict:
            return self.payload

    class Client:
        def __init__(self) -> None:
            self.payloads: list[dict] = []

        def get(self, *_args, **_kwargs) -> Response:
            return Response(200, state)

        def put(self, *_args, **kwargs) -> Response:
            self.payloads.append(dict(kwargs["json"]))
            if len(self.payloads) == 1:
                return Response(503, {
                    "error": {"code": "ROLE_LLM_RESPONSE_RETRYABLE"},
                })
            return Response(200, {**state, "contract": {"status": "draft"}})

    runner = real_routes_module.RealRouteRunner(
        Settings(environment="test"), tmp_path
    )
    client = Client()
    response = runner.set_contract_terms_for_route(
        client,
        "session-1",
        {"X-Account-ID": "account-1"},
        "contract-1",
        state_version=21,
        terms={"cash_amount": 100},
    )

    assert response.status_code == 200
    assert len(client.payloads) == 2
    assert all("retry" not in item for item in client.payloads)
    assert runner.operation_retries_by_session["session-1"][0][
        "state_restored"
    ] is True


def test_d29_night_matrix_uses_a_legal_protection_trigger_choice() -> None:
    profiles = {item.route_id: item for item in load_witnesses(PROFILE_PATH)}
    profile = _profile_for_plan(profiles, "followup_d29_zhao_protection")
    assert profile.decision_policy["dp2_01"] == "d"
    assert profile.decision_policy["dp2_02"] == "b"
    assert profile.route_id.endswith("-d29-protection")


def test_inventory_profile_can_answer_recovery_decisions_it_unlocks() -> None:
    base_profile = load_witnesses(PROFILE_PATH)[0]
    profile = _with_recovery_decision_policy(base_profile)

    assert profile.decision_policy["dp5_04_recovery"] == "a"
    assert profile.decision_policy["dp5_05_recovery"] == "b"


@pytest.mark.parametrize(
    "script",
    (
        "run_real_failure_matrix.py",
        "run_real_feature_workflows.py",
        "run_real_night_matrix.py",
        "run_real_v3_routes.py",
    ),
)
def test_real_acceptance_scripts_are_directly_executable_from_backend_root(
    script: str,
) -> None:
    environment = os.environ.copy()
    environment["PYTHONPATH"] = "src"
    completed = subprocess.run(
        (sys.executable, f"tools/{script}", "--help"),
        cwd=BACKEND_ROOT,
        env=environment,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--output-dir" in completed.stdout


def test_real_route_runner_forwards_acceptance_transport_to_container(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = lambda *_args: {}  # noqa: E731 - stable identity for this wiring test
    resolver = lambda *_args: []  # noqa: E731 - stable identity for this wiring test
    captured: dict[str, object] = {}

    def capture_container(_settings, **kwargs):
        captured.update(kwargs)
        raise RuntimeError("container captured")

    monkeypatch.setattr(real_routes_module, "build_container", capture_container)
    runner = real_routes_module.RealRouteRunner(
        Settings(environment="test"),
        tmp_path,
        player_llm_transport=transport,
        player_llm_resolver=resolver,
    )

    with pytest.raises(RuntimeError, match="container captured"):
        runner.build_real_runner(1)

    assert captured["player_llm_transport"] is transport
    assert captured["player_llm_resolver"] is resolver


def test_every_forced_night_plan_has_specific_credible_player_replies() -> None:
    for plan_id in FOLLOWUP_PLAN_IDS:
        replies = _strategy_texts(plan_id, "credible")
        assert len(replies) >= 2
        assert len(set(replies)) == len(replies)
        assert all(len(reply) >= 30 for reply in replies)


def test_real_runner_refuses_fake_provider_fallback_and_missing_key() -> None:
    with pytest.raises(SystemExit, match="requires openai_compatible"):
        validate_real_runner_settings(
            Settings(role_llm_provider="fake"), api_key="real-key-present"
        )
    with pytest.raises(SystemExit, match="refuses Fake fallback"):
        validate_real_runner_settings(
            Settings(
                role_llm_provider="openai_compatible",
                role_llm_fallback_to_fake=True,
            ),
            api_key="real-key-present",
        )
    with pytest.raises(SystemExit, match="API key is missing"):
        validate_real_runner_settings(
            Settings(role_llm_provider="openai_compatible"), api_key=""
        )


def test_real_runner_requires_a_complete_profile_catalog() -> None:
    package = FileScriptPackageLoader().load(PACKAGE_ROOT)
    profiles = load_witnesses(PROFILE_PATH)

    validate_profile_catalog(profiles, package)

    with pytest.raises(ValueError, match="95"):
        validate_profile_catalog(profiles[:-1], package)


def test_real_runner_defaults_to_all_95_profiles() -> None:
    profiles = load_witnesses(PROFILE_PATH)

    selected = select_route_profiles(profiles, None)

    assert len(selected) == 95
    assert [index for index, _profile in selected] == list(range(95))


def test_real_runner_rejects_unknown_and_duplicate_selected_route_ids() -> None:
    profiles = load_witnesses(PROFILE_PATH)

    with pytest.raises(ValueError, match="unknown route ID"):
        select_route_profiles(profiles, ["route-ending-01a,route-does-not-exist"])
    with pytest.raises(ValueError, match="duplicate route ID"):
        select_route_profiles(profiles, ["route-ending-01a", "route-ending-01a"])


def test_real_runner_selects_exactly_three_requested_catalog_routes() -> None:
    profiles = load_witnesses(PROFILE_PATH)
    route_ids = [
        "route-ending-01a",
        "route-ending-08a",
        "route-ending-23a",
    ]

    selected = select_route_profiles(
        profiles, ["route-ending-01a,route-ending-08a", "route-ending-23a"]
    )

    assert [profile.route_id for _index, profile in selected] == route_ids
    assert [index for index, _profile in selected] == [0, 32, 88]


def test_real_runner_executes_only_the_three_selected_profiles(tmp_path: Path) -> None:
    profiles = load_witnesses(PROFILE_PATH)
    selected = select_route_profiles(
        profiles,
        ["route-ending-01a,route-ending-08a,route-ending-23a"],
    )
    calls: list[tuple[int, str]] = []

    class Runner:
        def run_profile(self, index, profile, _contract_terms):
            calls.append((index, profile.route_id))
            return _passing_route_result(profile)

    route_root = tmp_path / "routes"
    route_root.mkdir()
    routes = execute_route_profiles(
        selected_profiles=selected,
        completed={},
        runner=Runner(),
        root=tmp_path,
        route_root=route_root,
        contract_terms={},
    )

    assert calls == [
        (0, "route-ending-01a"),
        (32, "route-ending-08a"),
        (88, "route-ending-23a"),
    ]
    assert [route["route_id"] for route in routes] == [item[1] for item in calls]
    assert sorted(path.stem for path in route_root.glob("route-*.json")) == [
        "route-ending-01a",
        "route-ending-08a",
        "route-ending-23a",
    ]


def test_subset_summary_cannot_claim_full_acceptance() -> None:
    profiles = load_witnesses(PROFILE_PATH)
    selected_ids = [profile.route_id for profile in profiles[:3]]
    routes = [_passing_route_result(profile) for profile in profiles[:3]]

    report = build_route_summary(
        profiles=profiles,
        selected_route_ids=selected_ids,
        routes=routes,
        provider="openai_compatible",
        model="test-model",
        no_archive_route=None,
        provenance={"git_sha": "a", "workspace_fingerprint": "b", "v3_hash": "c"},
    )

    assert report["scope"] == "selected_subset"
    assert report["catalog_profile_count"] == 95
    assert report["executed_count"] == 3
    assert report["selected_route_ids"] == selected_ids
    assert report["not_full_acceptance"] is True
    assert report["profile_count"] == 3


def test_resume_metadata_is_bound_to_exact_selection_and_provenance() -> None:
    metadata = build_route_run_metadata(
        selected_route_ids=["route-ending-01a", "route-ending-08a"],
        catalog_profile_count=95,
        provenance={"git_sha": "a", "workspace_fingerprint": "b", "v3_hash": "c"},
    )
    validate_resume_metadata(metadata, metadata)

    changed = {**metadata, "selected_route_ids": ["route-ending-01a"]}
    with pytest.raises(ValueError, match="selection or provenance mismatch"):
        validate_resume_metadata(metadata, changed)


def test_resume_loads_only_route_evidence_that_still_passes_contract(
    tmp_path: Path,
) -> None:
    profiles = load_witnesses(PROFILE_PATH)
    profile = profiles[0]
    route_root = tmp_path / "routes"
    route_root.mkdir()
    result = _passing_route_result(profile)
    (route_root / f"{profile.route_id}.json").write_text(
        __import__("json").dumps(result), encoding="utf-8"
    )

    completed = load_completed_route_evidence(route_root, profiles)

    assert completed == {profile.route_id: result}


def test_real_runner_refuses_reused_evidence_directories(tmp_path: Path) -> None:
    run_root = prepare_output_run(tmp_path, run_id="fixed-run")

    assert run_root == tmp_path / "fixed-run"
    with pytest.raises(FileExistsError):
        prepare_output_run(tmp_path, run_id="fixed-run")


def _passing_route_result(profile) -> dict[str, object]:
    return {
        "route_id": profile.route_id,
        "story_day": 90,
        "status": "ended",
        "main_ending_id": profile.target_main_ending_ids[0],
        "sub_ending_id": profile.target_sub_ending_ids[0],
        "visited_days": list(range(1, 91)),
        "llm_audits": 12,
        "providers": {"openai_compatible": 12},
        "fake_calls": 0,
        "template_fallback_count": 0,
        "silent_fallback_count": 0,
        "partial_commit_count": 0,
        "mutation_interface": "http_api_only",
        "failed_calls": [],
    }


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("main_ending_id", "ending_99", "main ending"),
        ("sub_ending_id", "ending_99z", "sub ending"),
        ("visited_days", [1, 2, 4, 90], "D1-D90"),
        ("llm_audits", 0, "model audit"),
        ("fake_calls", 1, "Fake"),
        ("template_fallback_count", 1, "template fallback"),
        ("silent_fallback_count", 1, "silent fallback"),
        ("partial_commit_count", 1, "partial commit"),
        ("mutation_interface", "database_write", "direct state"),
    ),
)
def test_real_runner_rejects_invalid_route_evidence(
    field: str,
    value: object,
    message: str,
) -> None:
    profile = load_witnesses(PROFILE_PATH)[0]
    result = _passing_route_result(profile)
    result[field] = value

    with pytest.raises(AssertionError, match=message):
        validate_route_result(profile, result)


def test_real_runner_rejects_retry_without_state_restoration_evidence() -> None:
    profile = load_witnesses(PROFILE_PATH)[0]
    result = _passing_route_result(profile)
    result["failed_calls"] = [{
        "operation": "end-d10",
        "state_restored": False,
    }]

    with pytest.raises(AssertionError, match="state restoration"):
        validate_route_result(profile, result)


def test_ending_operation_record_preserves_player_actions_and_mechanism_effects() -> None:
    profile = load_witnesses(PROFILE_PATH)[0]
    result = {
        **_passing_route_result(profile),
        "axes": {"integrity": "clean"},
        "decision_choices": [{"story_day": 1, "decision_id": "dp1", "option_id": "a"}],
        "archive_reads": [{"story_day": 2, "archive_id": "archive-1", "new_fact_ids": ["fact-1"]}],
        "conversations": [{"story_day": 3, "npc_id": "npc-1", "completion_status": "completed"}],
        "governance_actions": [{"story_day": 4, "action_kind": "household_visit", "status": "completed"}],
        "contracts": [{"signed_day": 5, "household_id": "WU-01", "status": "signed"}],
        "administrative_documents": [{"story_day": 6, "document_id": "doc-1", "status": "published"}],
        "group_conversations": [{"story_day": 10, "conversation_id": "group-1", "phase": "resolved"}],
        "known_fact_ids": ["fact-1"],
        "night_logs": [{"story_day": 10, "created_followup_plan_ids": ["followup-1"]}],
    }

    record = build_ending_operation_record(profile, result)

    assert record["route_id"] == profile.route_id
    assert [item["mechanism"] for item in record["operation_sequence"]] == [
        "decision", "archive", "conversation", "governance_action", "contract",
        "document", "forced_night_conversation",
    ]
    assert record["mechanism_effects"]["red_head_documents"]["published_count"] == 1
    assert record["mechanism_effects"]["contracts"]["signed_households"] == ["WU-01"]
    assert record["ending_state"]["axes"] == {"integrity": "clean"}

    markdown = build_ending_operation_markdown([{"operation_record": record}])
    assert f"## {profile.route_id}" in markdown
    assert "红头文件" in markdown
    assert "D6 | 红头文件" in markdown
    assert "WU-01" in markdown


def test_feature_workflow_report_requires_every_published_system() -> None:
    complete = {
        "provider": "openai_compatible",
        "fake_calls": 0,
        "server_default_accounts": 1,
        "personal_api_accounts": 1,
        "account_gateway_isolation": True,
        "archive_ids": [f"archive-{index}" for index in range(11)],
        "fact_acquisition_path_ids": [f"fact-path-{index}" for index in range(27)],
        "opportunity_ids": [f"opportunity-{index}" for index in range(32)],
        "npc_ids": [f"npc-{index}" for index in range(29)],
        "map_location_ids": [f"map-{index}" for index in range(8)],
        "household_ids": [f"household-{index}" for index in range(36)],
        "governance_action_families": [
            "inspect_archives",
            "household_visit",
            "cadre_interview",
            "leadership_meeting",
        ],
        "meeting_completed": True,
        "contract_completed": True,
        "document_completed": True,
        "save_load_completed": True,
        "review_completed": True,
        "contract_review_statuses": ["signed"],
    }

    validate_feature_workflow_report(complete)

    incomplete = {**complete, "household_ids": complete["household_ids"][:-1]}
    with pytest.raises(AssertionError, match="36 households"):
        validate_feature_workflow_report(incomplete)

    stale = {**complete, "contract_review_statuses": ["accepted"]}
    with pytest.raises(AssertionError, match="signed"):
        validate_feature_workflow_report(stale)


def test_default_acceptance_stage_scripts_exist() -> None:
    tools_root = BACKEND_ROOT / "tools"
    assert (tools_root / "run_browser_acceptance.py").is_file()
    assert (tools_root / "build_full_acceptance_report.py").is_file()


def test_browser_acceptance_parallelizes_routes_before_the_visual_inventory() -> None:
    source = (BACKEND_ROOT / "tools" / "run_browser_acceptance.py").read_text(
        encoding="utf-8"
    )
    assert "ThreadPoolExecutor" in source
    assert 'FULL_E2E_SHARD_TOTAL' in source
    assert 'e2e/full-game.spec.ts' in source
    assert 'e2e/visual-matrix.spec.ts' in source
    assert source.index('e2e/full-game.spec.ts') < source.index('e2e/visual-matrix.spec.ts')


def test_workspace_fingerprint_is_stable_and_bound_to_head() -> None:
    repository = BACKEND_ROOT.parents[1]
    first = workspace_fingerprint(repository)
    second = workspace_fingerprint(repository)

    assert first == second
    assert len(first["workspace_fingerprint"]) == 64
    assert len(first["git_commit"]) >= 7


def test_browser_report_rejects_skipped_or_missing_execution() -> None:
    passing = {
        "suites": [{
            "specs": [{
                "tests": [{"status": "expected"}, {"status": "expected"}],
            }],
        }],
    }
    assert validate_browser_report(passing, expected_tests=2)["passed"] == 2
    with pytest.raises(AssertionError, match="skipped"):
        validate_browser_report({
            "suites": [{"specs": [{"tests": [{"status": "skipped"}]}]}],
        }, expected_tests=1)
    with pytest.raises(AssertionError, match="expected at least"):
        validate_browser_report(passing, expected_tests=3)


def test_full_acceptance_stops_after_the_first_failed_stage() -> None:
    calls: list[str] = []

    def executor(name: str, command: tuple[str, ...]) -> int:
        calls.append(name)
        return 3 if name == "features" else 0

    with pytest.raises(SystemExit, match="features"):
        run_stages(
            (
                ("capabilities", ("python", "capabilities.py")),
                ("features", ("python", "features.py")),
                ("routes", ("python", "routes.py")),
            ),
            executor=executor,
        )

    assert calls == ["capabilities", "features"]
