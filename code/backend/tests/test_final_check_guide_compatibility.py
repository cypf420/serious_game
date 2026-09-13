from pathlib import Path

from serious_game_backend.config import Settings
from serious_game_backend.domain.events import PendingDecision, VisibleDecisionOption
from serious_game_backend.infrastructure.repositories.codec import decode_session, encode_session
from tests.test_doubles import build_test_container


def test_optional_decision_guides_survive_save_and_old_save_without_guides():
    root = Path(__file__).resolve().parents[1]
    runtime = build_test_container(Settings(
        environment="test", repository="memory", role_llm_provider="none",
        content_root=root / "content" / "packages", default_package_id="pkg_gameplay_v3",
    ))
    session = runtime.game_sessions.start_session(
        account_id="guide-compat", package_id="pkg_gameplay_v3",
        client_request_id="guide-compat-start", origin_id="mayor",
    )
    step = {"label": "查阅原件", "archive_id": "archive_test_original"}
    session.pending_decision = PendingDecision(
        event_instance_id="guide-event", decision_id="guide-decision", option_ids=("a",),
        options=(VisibleDecisionOption("a", "使用原件", False, "尚未取得", next_steps=(step,)),),
    )
    snapshot = encode_session(session)
    restored = decode_session(snapshot)
    assert restored.pending_decision.options[0].next_steps[0] == step
    del snapshot["pending_decision"]["options"][0]["next_steps"]
    legacy = decode_session(snapshot)
    assert legacy.pending_decision.options[0].next_steps == ()
    assert legacy.pending_decision.options[0].available is False
