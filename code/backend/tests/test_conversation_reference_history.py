from tests.test_conversation_references import conversation


def test_player_reference_metadata_survives_completion_and_history_api(conversation):
    helper, started = conversation
    session = helper.container.sessions.get_owned(helper.session_id, "acct_m2")
    document = next(iter(session.administrative_documents.values()))
    document.status = "published"
    helper.container.sessions.save(session, expected_version=session.state_version)
    result = helper.action(dict(input_mode="free_text", client_action_id="ref-history-turn",
        state_version=started["state_version"], conversation_id=started["conversation"]["conversation_id"],
        opportunity_id="opp_d02_wu_xiuying_first_talk", target_npc_id="npc_wu_xiuying",
        player_text="请核对这份补偿方案。", reference_ids=[f"document:{document.document_id}"]))
    current = helper.container.sessions.get_owned(helper.session_id, "acct_m2")
    if current.active_conversation:
        helper.action(dict(input_mode="conversation_end", client_action_id="ref-history-end",
            state_version=result["state_version"], conversation_id=started["conversation"]["conversation_id"]))
    response = helper.client.get(f"/api/game/session/{helper.session_id}/conversations", headers=helper.headers)
    assert response.status_code == 200, response.text
    transcript = response.json()["items"][0]["transcript"]
    player = next(t for t in transcript if t["speaker_type"] == "player")
    assert player["references"] == [{"id": f"document:{document.document_id}",
        "title": document.title, "version": document.version, "status": "published"}]
    assert all("references" not in t for t in transcript if t["speaker_type"] == "npc")
