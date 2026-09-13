from __future__ import annotations

from collections import Counter
import os
from pathlib import Path
import unittest

from fastapi.testclient import TestClient

from serious_game_backend.api.app import create_app
from tests.test_doubles import build_test_container as build_container
from serious_game_backend.config import Settings
from tools.full_acceptance.ending_witnesses import load_contract_terms, load_witnesses
from tools.full_acceptance.persuasion import credible_group_replies


BACKEND_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = BACKEND_ROOT / "content" / "packages"
WITNESS_PROFILE_PATH = (
    PACKAGE_ROOT / "pkg_gameplay_v3" / "acceptance_route_profiles.json"
)
CONTRACT_GROUP_SCHEDULE = (
    (53, "npc_zhou_dashan"),
    (53, "npc_tan_laoliu"),
    (56, "npc_yuan_guilan"),
    (56, "npc_wu_xiuying"),
    (57, "npc_he_tiezhu"),
    (57, "npc_yang_bo"),
    (64, "npc_zhou_kuiyuan"),
    (68, "npc_zhou_mancang"),
    (71, "npc_ning_dehai"),
    (73, "npc_ma_changshun"),
    (77, "npc_lao_juetou"),
    (78, "npc_miao_xiwang"),
    (84, "npc_deng_shouben"),
)
DEMAND_OPPORTUNITY_BY_ID = {
    "demand_shi_wenbin": "opp_22_shi_wenbin_contact",
    "demand_zhou_mancang": "opp_03_zhou_mancang_contact",
    "demand_he_tiezhu": "opp_03_he_tiezhu_contact",
    "demand_miao_xiwang": "opp_03_miao_xiwang_contact",
    "demand_he_xingbang": "opp_46_he_xingbang_contact",
    "demand_gu_keming": "opp_59_gu_keming_contact",
}
PEOPLE_AXIS_DEMAND_IDS = {
    "归心": frozenset(DEMAND_OPPORTUNITY_BY_ID),
    "认可": frozenset((
        "demand_shi_wenbin",
        "demand_zhou_mancang",
        "demand_he_tiezhu",
        "demand_gu_keming",
    )),
}


class StoryRoutesV3Tests(unittest.TestCase):
    def build_runner(self, route_index: int) -> tuple[object, TestClient, str, dict[str, str]]:
        settings = Settings(
            environment="test",
            content_root=PACKAGE_ROOT,
            default_package_id="pkg_gameplay_v3",
            repository="memory",
            role_llm_provider="none",
        )
        container = build_container(settings)
        client = TestClient(create_app(settings, container=container))
        client.__enter__()
        headers = {"X-Account-ID": f"acct_story_route_{route_index}"}
        response = client.post(
            "/api/game/session",
            headers=headers,
            json={
                "client_request_id": f"story-route-{route_index}",
                "origin_id": ("technical", "grassroots", "integrity")[route_index % 3],
                "package_id": "pkg_gameplay_v3",
            },
        )
        self.assertEqual(201, response.status_code, response.text)
        return container, client, response.json()["session_id"], headers

    def action(self, client, session_id, headers, payload: dict) -> dict:
        response = client.post(
            f"/api/game/session/{session_id}/action",
            headers=headers,
            json=payload,
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def test_contract_route_ignores_historic_self_attested_facts(self) -> None:
        from unittest.mock import Mock
        client = Mock()
        terms = {"cash_amount": 36, "payment_day": 77,
                 **dict.fromkeys(("authorization_confirmed", "real_unit_viewed",
                     "ledger_disclosed", "old_case_resolved", "prior_payment_verified"), True)}
        self.set_contract_terms_for_route(client, "session", {}, "contract",
                                         state_version=9, terms=terms)
        payload = client.put.call_args.kwargs["json"]
        self.assertEqual({"state_version": 9, "cash_amount": 36, "payment_day": 77}, payload)
        self.assertTrue(terms["real_unit_viewed"])

    def test_opportunity_driver_does_not_end_a_conversation_twice_when_npc_closed_it(self) -> None:
        class Response:
            status_code = 200
            text = ""

            def __init__(self, payload: dict) -> None:
                self.payload = payload

            def json(self) -> dict:
                return self.payload

        class Client:
            def get(self, path: str, *, headers: dict[str, str]) -> Response:
                if path.endswith("/opportunities"):
                    return Response({"opportunities": [{
                        "opportunity_id": "opp_auto_close",
                        "npc_id": "npc_wang_fang",
                        "conversation_goal": "核实公开材料",
                        "cost_action_points": 1,
                        "cta_available": True,
                        "conversation_active": False,
                    }]})
                return Response({
                    "ledger": {"action_points": {"remaining": 8}}
                })

        calls: list[dict] = []
        results = iter((
            {
                "state_version": 2,
                "conversation": {"conversation_id": "conv-auto-close"},
                "visible_state": {"active_conversation": {
                    "conversation_id": "conv-auto-close"
                }},
            },
            {
                "state_version": 3,
                "completion_status": "completed",
                "visible_state": {"active_conversation": None},
            },
        ))
        original_action = self.action
        self.action = lambda client, session_id, headers, payload: (
            calls.append(payload) or next(results)
        )
        try:
            result, serial, completed = self.complete_one_available_opportunity(
                Client(),
                "session",
                {"X-Account-ID": "account"},
                {"state_version": 1},
                7,
            )
        finally:
            self.action = original_action
        self.assertTrue(completed)
        self.assertEqual(8, serial)
        self.assertEqual("completed", result["completion_status"])
        self.assertEqual(
            ["conversation_start", "free_text"],
            [item["input_mode"] for item in calls],
        )

    def end_day(self, client, session_id, headers, result: dict, key: str) -> dict:
        view = client.get(f"/api/game/session/{session_id}/view", headers=headers).json()
        if view["commands"].get("can_continue_story"):
            continued = client.post(f"/api/game/session/{session_id}/story/continue", headers=headers, json={
                "client_action_id": f"story-{key}", "state_version": result["state_version"],
            })
            self.assertEqual(200, continued.status_code, continued.text)
            result = continued.json()
        response = client.post(
            f"/api/game/session/{session_id}/end-day",
            headers=headers,
            json={"client_action_id": key, "state_version": result["state_version"]},
        )
        self.assertEqual(200, response.status_code, response.text)
        return response.json()

    def inspect_all_available_archives(
        self, client, session_id, headers, result: dict
    ) -> dict:
        if result.get("visible_state", {}).get("pending_decision"):
            return result
        while True:
            catalog = client.get(
                f"/api/game/session/{session_id}/actions", headers=headers
            )
            self.assertEqual(200, catalog.status_code, catalog.text)
            variant = next(
                item
                for action in catalog.json()["actions"]
                for item in action["variants"]
                if item["variant_id"] == "consult_county_archives"
            )
            unread = [
                item for item in variant["target_choices"]
                if item.get("read_status") != "read"
            ]
            if not unread:
                return result
            archive = unread[0]
            cost = int(archive.get("first_read_cost_action_points", 1))
            stored_state = client.get(
                f"/api/game/session/{session_id}", headers=headers
            )
            self.assertEqual(200, stored_state.status_code, stored_state.text)
            if int(
                stored_state.json()["ledger"]["action_points"]["remaining"]
            ) < cost:
                return result
            response = client.post(
                f"/api/game/session/{session_id}/governance/actions",
                headers=headers,
                json={
                    "state_version": result["state_version"],
                    "action_kind": "inspect_archives",
                    "variant_id": variant["variant_id"],
                    "location_id": variant["location_choices"][0]["location_id"],
                    "archive_ids": [archive["target_id"]],
                },
            )
            self.assertEqual(201, response.status_code, response.text)
            result = {**result, "state_version": response.json()["state_version"]}

    def complete_one_available_opportunity(
        self,
        client,
        session_id,
        headers,
        result: dict,
        serial: int,
        allowed_ids: set[str] | None = None,
    ) -> tuple[dict, int, bool]:
        response = client.get(
            f"/api/game/session/{session_id}/opportunities", headers=headers
        )
        self.assertEqual(200, response.status_code, response.text)
        opportunities = [
            item for item in response.json()["opportunities"]
            if item.get("cta_available") and not item.get("conversation_active")
            and (allowed_ids is None or item["opportunity_id"] in allowed_ids)
        ]
        if not opportunities:
            return result, serial, False
        state = client.get(
            f"/api/game/session/{session_id}", headers=headers
        )
        self.assertEqual(200, state.status_code, state.text)
        remaining = int(state.json()["ledger"]["action_points"]["remaining"])
        opportunity = opportunities[0]
        if remaining < int(opportunity["cost_action_points"]):
            return result, serial, False
        opportunity_id = opportunity["opportunity_id"]
        npc_id = opportunity["npc_id"]
        player_text = opportunity["conversation_goal"]
        if opportunity_id == "opp_03_zhou_kuiyuan_contact":
            player_text = (
                "请把迁坟的四件事说清楚：择地、择日、起灵和祭祀延续，"
                "我会按村里旧例逐项核对。"
            )
        elif opportunity_id == "opp_03_zhou_mancang_contact":
            player_text = (
                "你要求先摊什么账、再摆什么原始数据、最后才谈什么？"
                "请把你认可的三步顺序完整说清楚。"
            )
        started = self.action(client, session_id, headers, {
            "input_mode": "conversation_start",
            "client_action_id": f"witness-opportunity-{serial:04d}-start",
            "state_version": result["state_version"],
            "opportunity_id": opportunity_id,
            "target_npc_id": npc_id,
        })
        conversation_id = started["conversation"]["conversation_id"]
        talked = self.action(client, session_id, headers, {
            "input_mode": "free_text",
            "client_action_id": f"witness-opportunity-{serial:04d}-turn",
            "state_version": started["state_version"],
            "conversation_id": conversation_id,
            "opportunity_id": opportunity_id,
            "target_npc_id": npc_id,
            "player_text": player_text,
        })
        if (
            talked.get("completion_status") == "completed"
            or talked.get("visible_state", {}).get("active_conversation") is None
        ):
            closed = talked
        else:
            closed = self.action(client, session_id, headers, {
                "input_mode": "conversation_end",
                "client_action_id": f"witness-opportunity-{serial:04d}-end",
                "state_version": talked["state_version"],
                "conversation_id": conversation_id,
            })
        return closed, serial + 1, True

    def drain_optional_opportunities(
        self,
        container,
        client,
        session_id,
        headers,
        result: dict,
        profile,
        serial: int,
        allowed_ids: set[str] | None = None,
    ) -> tuple[dict, int]:
        while True:
            result, serial, completed = self.complete_one_available_opportunity(
                client, session_id, headers, result, serial, allowed_ids
            )
            if not completed:
                return result, serial
            result, serial = self.drain_profile_decisions(
                container,
                client,
                session_id,
                headers,
                result,
                profile,
                serial,
            )

    def review_contract_for_route(
        self,
        client,
        session_id: str,
        headers: dict[str, str],
        contract_id: str,
        draft_body: dict,
    ):
        return client.post(
            f"/api/game/session/{session_id}/governance/contracts/"
            f"{contract_id}/review",
            headers=headers,
            json={"state_version": draft_body["state_version"]},
        )

    def governance_turn_for_route(
        self,
        client,
        session_id: str,
        headers: dict[str, str],
        action_id: str,
        started_body: dict,
        *,
        player_text: str,
        client_action_id: str,
    ):
        return client.post(
            f"/api/game/session/{session_id}/governance/actions/{action_id}/turn",
            headers=headers,
            json={
                "state_version": started_body["state_version"],
                "player_text": player_text,
                "client_action_id": client_action_id,
            },
        )

    def set_contract_terms_for_route(
        self,
        client,
        session_id: str,
        headers: dict[str, str],
        contract_id: str,
        *,
        state_version: int,
        terms: dict,
    ):
        return client.put(
            f"/api/game/session/{session_id}/governance/contracts/"
            f"{contract_id}/terms",
            headers=headers,
            # Historic route profiles carry self-attested facts. They are not
            # evidence and must not be sent by the player-route driver.
            json={"state_version": state_version, **{
                key: value for key, value in terms.items()
                if key not in {"authorization_confirmed", "real_unit_viewed",
                    "ledger_disclosed", "old_case_resolved", "prior_payment_verified"}
            }},
        )

    def group_conversation_turn_for_route(
        self,
        client,
        session_id: str,
        headers: dict[str, str],
        body: dict,
    ):
        return client.post(
            f"/api/game/session/{session_id}/group-conversation/turn",
            headers=headers,
            json=body,
        )

    def sign_contracts_toward_target(
        self,
        client,
        session_id,
        headers,
        result: dict,
        *,
        target_signed: int,
        contract_terms: dict[str, dict],
        processed_representatives: set[str],
    ) -> dict:
        state = client.get(f"/api/game/session/{session_id}", headers=headers)
        self.assertEqual(200, state.status_code, state.text)
        current = int(state.json()["ledger"]["signed_households"]["signed"])
        story_day = int(state.json()["story"]["day"])
        if current >= target_signed:
            return result
        eligible = [
            representative
            for available_day, representative in CONTRACT_GROUP_SCHEDULE
            if available_day <= story_day
            and representative not in processed_representatives
        ]
        for representative in eligible:
            if current >= target_signed:
                break
            live_state = client.get(
                f"/api/game/session/{session_id}", headers=headers
            )
            self.assertEqual(200, live_state.status_code, live_state.text)
            if int(
                live_state.json()["ledger"]["action_points"]["remaining"]
            ) < (2 if representative == "npc_lao_juetou" else 1):
                return result
            catalog_response = client.get(
                f"/api/game/session/{session_id}/actions", headers=headers
            )
            self.assertEqual(200, catalog_response.status_code, catalog_response.text)
            household_action = next(
                item for item in catalog_response.json()["actions"]
                if item["action_id"] == "household_visit"
            )
            variant = next((
                item for item in household_action["variants"]
                if representative in {
                    choice["target_id"] for choice in item.get("target_choices", [])
                }
            ), None)
            if representative != "npc_lao_juetou":
                variant = next((item for item in household_action["variants"]
                    if item["variant_id"] == "contract_negotiation"
                    and representative in {choice["target_id"] for choice in item.get("target_choices", [])}), variant)
            if variant is None or not variant.get("available", True):
                continue
            started = client.post(
                f"/api/game/session/{session_id}/governance/actions",
                headers=headers,
                json={
                    "state_version": result["state_version"],
                    "action_kind": "household_visit",
                    "variant_id": variant["variant_id"],
                    "location_id": variant["location_choices"][0]["location_id"],
                    "target_ids": [representative],
                    "topic": "逐户合同与正式签约",
                },
            )
            self.assertEqual(201, started.status_code, started.text)
            started_body = started.json()
            action_id = started_body["action"]["action_instance_id"]
            # Resume actual drafts rather than creating a second contract when
            # the household previously asked for evidence or clarification.
            overview = client.get(f"/api/game/session/{session_id}/governance", headers=headers)
            self.assertEqual(200, overview.status_code, overview.text)
            existing = overview.json()
            batch_ids = {b["batch_id"] for b in existing.get("contract_batches", [])
                         if b["representative_npc_id"] == representative}
            pending_contracts = [c for c in existing.get("contracts", [])
                                 if c["batch_id"] in batch_ids and c["status"] != "signed"]
            if pending_contracts:
                confirmed_body = {"state_version": started_body["state_version"],
                                  "contracts": pending_contracts}
            else:
                turn = self.governance_turn_for_route(
                    client,
                    session_id,
                    headers,
                    action_id,
                    started_body,
                    player_text=(
                        "我正式向你代表的每一户分别发起合同，请逐户核对条款并签约。"
                    ),
                    client_action_id=f"witness-contract-{action_id}",
                )
                self.assertEqual(200, turn.status_code, turn.text)
                turn_body = turn.json()
                proposal = turn_body.get("contract_batch_proposal")
                if proposal is None:
                    finished = client.post(
                        f"/api/game/session/{session_id}/governance/actions/{action_id}/finish",
                        headers=headers,
                        json={"state_version": turn_body["state_version"]},
                    )
                    self.assertEqual(200, finished.status_code, finished.text)
                    result = finished.json()
                    continue
                confirmed = client.post(
                    f"/api/game/session/{session_id}/governance/contract-batches/"
                    f"{proposal['batch_id']}/confirm",
                    headers=headers,
                    json={"state_version": turn_body["state_version"], "confirmed": True},
                )
                self.assertEqual(200, confirmed.status_code, confirmed.text)
                confirmed_body = confirmed.json()
            state_version = confirmed_body["state_version"]
            all_resolved = True
            for contract in confirmed_body["contracts"]:
                if current >= target_signed:
                    break
                household_id = contract["household_id"]
                self.assertIn(household_id, contract_terms)
                terms = dict(contract_terms[household_id])
                terms["payment_day"] = story_day
                for field in ("move_out_day", "housing_delivery_day"):
                    terms[field] = max(story_day, int(terms[field]))
                if story_day > 75:
                    terms["public_window_reward"] = False
                drafted = self.set_contract_terms_for_route(
                    client,
                    session_id,
                    headers,
                    contract["contract_id"],
                    state_version=state_version,
                    terms=terms,
                )
                self.assertEqual(200, drafted.status_code, drafted.text)
                draft_body = drafted.json()
                self.assertEqual("not_required", draft_body["contract"]["audit_status"])
                if household_id == "LAO-01" and terms.get("housing_resource_id"):
                    # Perform a present-tense invitation through the real action
                    # route. The NPC decides; the application records a viewing
                    # only after acceptance. Never patch a verified fact here.
                    viewing = self.governance_turn_for_route(
                        client, session_id, headers, action_id, draft_body,
                        player_text="我们现在去看合同中这套可交付房源，您愿意一起去看吗？",
                        client_action_id=f"witness-viewing-{contract['contract_id']}",
                    )
                    self.assertEqual(200, viewing.status_code, viewing.text)
                    draft_body = {**draft_body,
                        "state_version": viewing.json()["state_version"]}
                live = client.get(f"/api/game/session/{session_id}", headers=headers)
                self.assertEqual(200, live.status_code, live.text)
                if int(live.json()["ledger"]["action_points"]["remaining"]) < int(
                    draft_body["contract"].get("review_cost_action_points", 1)
                ):
                    # Preserve the saved draft and resume on a later day. New
                    # signing attempts now have an explicit authoritative fee.
                    state_version = draft_body["state_version"]
                    all_resolved = False
                    break
                reviewed = self.review_contract_for_route(
                    client,
                    session_id,
                    headers,
                    contract["contract_id"],
                    draft_body,
                )
                self.assertEqual(200, reviewed.status_code, reviewed.text)
                review_body = reviewed.json()
                if review_body["contract"]["status"] == "accepted":
                    signed = client.post(
                        f"/api/game/session/{session_id}/governance/contracts/"
                        f"{contract['contract_id']}/sign",
                        headers=headers,
                        json={
                            "state_version": review_body["state_version"],
                            "confirmed": True,
                        },
                    )
                    self.assertEqual(200, signed.status_code, signed.text)
                    review_body = signed.json()
                state_version = review_body["state_version"]
                status = review_body["contract"]["status"]
                self.assertIn(status, {"signed", "explanation_requested", "counteroffered", "rejected"},
                              f"{household_id}: {review_body['contract'].get('review_reason')}")
                if status != "signed":
                    print(f"deferred D{story_day} {household_id}: {status}: "
                          f"{review_body['contract'].get('review_reason')}", flush=True)
                    all_resolved = False
                    continue
                current += 1
            finished = client.post(
                f"/api/game/session/{session_id}/governance/actions/{action_id}/finish",
                headers=headers,
                json={"state_version": state_version},
            )
            self.assertEqual(200, finished.status_code, finished.text)
            result = finished.json()
            if all_resolved:
                processed_representatives.add(representative)
        return result

    def drain_required_group_conversation(
        self, client, session_id, headers, result: dict, key: str
    ) -> dict:
        round_index = 0
        while result["visible_state"].get("active_group_conversation"):
            round_index += 1
            self.assertLessEqual(round_index, 40, "forced conversation did not settle")
            active_group = result["visible_state"]["active_group_conversation"]
            resolved = active_group.get("phase") == "resolved"
            body = {
                "state_version": result["state_version"],
                "client_action_id": f"{key}-group-{round_index:02d}",
            }
            if not resolved:
                replies = credible_group_replies(active_group)
                body["player_text"] = replies[(round_index - 1) % len(replies)]
            if resolved:
                response = client.post(
                    f"/api/game/session/{session_id}/group-conversation/finish",
                    headers=headers,
                    json=body,
                )
            else:
                response = self.group_conversation_turn_for_route(
                    client,
                    session_id,
                    headers,
                    body,
                )
            self.assertEqual(200, response.status_code, response.text)
            result = response.json()
        return result

    def choose_option(self, pending: dict, route_index: int, decision_index: int) -> dict:
        available = [item for item in pending["options"] if item.get("available", True)]
        if route_index == 0:
            selected = available[0]
        elif route_index == 1:
            selected = available[-1]
        else:
            selected = available[decision_index % len(available)]
        parameters = {}
        if pending.get("input_kind") == "allocation":
            fields = pending["input_schema"]["fields"]
            total = int(pending["input_schema"]["total"])
            target = (0, len(fields) - 1, len(fields) // 2)[route_index]
            parameters = {
                "allocations": {
                    field: total if position == target else 0
                    for position, field in enumerate(fields)
                }
            }
        return {"option_id": selected["option_id"], "parameters": parameters}

    def choose_profile_option(self, pending: dict, profile) -> dict:
        decision_id = pending["decision_id"]
        self.assertIn(
            decision_id,
            profile.decision_policy,
            f"{profile.route_id} has no policy for {decision_id}",
        )
        configured = profile.decision_policy[decision_id]
        if isinstance(configured, dict):
            option_id = str(configured["option_id"])
            parameters = dict(configured.get("parameters", {}))
        else:
            option_id = str(configured)
            parameters = {}
        available = {
            item["option_id"]: item
            for item in pending["options"]
            if item.get("available", True)
        }
        self.assertIn(
            option_id,
            available,
            f"{profile.route_id} chose unavailable {decision_id}:{option_id}",
        )
        if pending.get("input_kind") == "allocation" and not parameters:
            fields = pending["input_schema"]["fields"]
            total = int(pending["input_schema"]["total"])
            ordered = option_id.split("_")
            allocations = {field: 0 for field in fields}
            allocations[ordered[0] if ordered[0] in allocations else fields[0]] = total
            parameters = {"allocations": allocations}
        return {"option_id": option_id, "parameters": parameters}

    def drain_profile_decisions(
        self, container, client, session_id, headers, result: dict, profile, serial: int
    ) -> tuple[dict, int]:
        pending = result["visible_state"].get("pending_decision")
        while pending is not None:
            stored = container.sessions.get_owned(session_id, headers["X-Account-ID"])
            self.assertTrue(any(
                item.decision_id == pending["decision_id"]
                and item.presentation_phase == "decision"
                for item in stored.narrative_feed
            ))
            choice = self.choose_profile_option(pending, profile)
            result = self.action(client, session_id, headers, {
                "input_mode": "decision",
                "client_action_id": f"{profile.route_id}-decision-{serial:03d}",
                "state_version": result["state_version"],
                "decision_id": pending["decision_id"],
                **choice,
            })
            serial += 1
            pending = result["visible_state"].get("pending_decision")
        return result, serial

    def reach_day_three_with_profile(
        self, container, client, session_id, headers, profile
    ) -> tuple[dict, int]:
        session = container.sessions.get_owned(session_id, headers["X-Account-ID"])
        pending = session.pending_decision
        self.assertIsNotNone(pending)
        result = {
            "state_version": session.state_version,
            "visible_state": {"pending_decision": {
                "decision_id": pending.decision_id,
                "input_kind": pending.input_kind,
                "input_schema": pending.input_schema,
                "options": [
                    {"option_id": item.option_id, "available": item.available}
                    for item in pending.options
                ],
            }},
        }
        result, serial = self.drain_profile_decisions(
            container, client, session_id, headers, result, profile, 0
        )
        result = self.inspect_all_available_archives(
            client, session_id, headers, result
        )
        result = self.end_day(
            client, session_id, headers, result, f"{profile.route_id}-end-d1"
        )
        result, serial = self.drain_profile_decisions(
            container, client, session_id, headers, result, profile, serial
        )
        result = self.inspect_all_available_archives(
            client, session_id, headers, result
        )
        started = self.action(client, session_id, headers, {
            "input_mode": "conversation_start",
            "client_action_id": f"{profile.route_id}-wu-start",
            "state_version": result["state_version"],
            "opportunity_id": "opp_d02_wu_xiuying_first_talk",
            "target_npc_id": "npc_wu_xiuying",
        })
        conversation_id = started["conversation"]["conversation_id"]
        talked = self.action(client, session_id, headers, {
            "input_mode": "free_text",
            "client_action_id": f"{profile.route_id}-wu-talk",
            "state_version": started["state_version"],
            "conversation_id": conversation_id,
            "opportunity_id": "opp_d02_wu_xiuying_first_talk",
            "target_npc_id": "npc_wu_xiuying",
            "player_text": "请把柳林村各户真正担心的事告诉我。",
        })
        closed = self.action(client, session_id, headers, {
            "input_mode": "conversation_end",
            "client_action_id": f"{profile.route_id}-wu-end",
            "state_version": talked["state_version"],
            "conversation_id": conversation_id,
        })
        return self.end_day(
            client, session_id, headers, closed, f"{profile.route_id}-end-d2"
        ), serial

    def drain_decisions(
        self,
        container,
        client,
        session_id,
        headers,
        result: dict,
        route_index: int,
        decision_index: int,
    ) -> tuple[dict, int]:
        pending = result["visible_state"].get("pending_decision")
        while pending is not None:
            stored = container.sessions.get_owned(session_id, headers["X-Account-ID"])
            self.assertTrue(
                any(
                    item.decision_id == pending["decision_id"]
                    and item.presentation_phase == "decision"
                    for item in stored.narrative_feed
                ),
                f"{pending['decision_id']} became actionable before its display node",
            )
            choice = self.choose_option(pending, route_index, decision_index)
            result = self.action(
                client,
                session_id,
                headers,
                {
                    "input_mode": "decision",
                    "client_action_id": f"route-{route_index}-decision-{decision_index:03d}",
                    "state_version": result["state_version"],
                    "decision_id": pending["decision_id"],
                    **choice,
                },
            )
            decision_index += 1
            pending = result["visible_state"].get("pending_decision")
        return result, decision_index

    def reach_day_three(self, container, client, session_id, headers, route_index: int) -> tuple[dict, int]:
        session = container.sessions.get_owned(session_id, headers["X-Account-ID"])
        result = {"state_version": session.state_version, "visible_state": {"pending_decision": {
            "decision_id": session.pending_decision.decision_id,
            "input_kind": session.pending_decision.input_kind,
            "input_schema": session.pending_decision.input_schema,
            "options": [
                {"option_id": item.option_id, "available": item.available}
                for item in session.pending_decision.options
            ],
        }}}
        result, decision_index = self.drain_decisions(
            container, client, session_id, headers, result, route_index, 0
        )
        result = self.end_day(client, session_id, headers, result, f"route-{route_index}-end-d1")
        result, decision_index = self.drain_decisions(
            container, client, session_id, headers, result, route_index, decision_index
        )
        started = self.action(client, session_id, headers, {
            "input_mode": "conversation_start",
            "client_action_id": f"route-{route_index}-wu-start",
            "state_version": result["state_version"],
            "opportunity_id": "opp_d02_wu_xiuying_first_talk",
            "target_npc_id": "npc_wu_xiuying",
        })
        conversation_id = started["conversation"]["conversation_id"]
        talked = self.action(client, session_id, headers, {
            "input_mode": "free_text",
            "client_action_id": f"route-{route_index}-wu-talk",
            "state_version": started["state_version"],
            "conversation_id": conversation_id,
            "opportunity_id": "opp_d02_wu_xiuying_first_talk",
            "target_npc_id": "npc_wu_xiuying",
            "player_text": "请把柳林村各户真正担心的事告诉我。",
        })
        closed = self.action(client, session_id, headers, {
            "input_mode": "conversation_end",
            "client_action_id": f"route-{route_index}-wu-end",
            "state_version": talked["state_version"],
            "conversation_id": conversation_id,
        })
        return (
            self.end_day(client, session_id, headers, closed, f"route-{route_index}-end-d2"),
            decision_index,
        )

    def test_three_distinct_fake_routes_reach_d90_without_semantic_leaks(self) -> None:
        route_sequences = []
        for route_index in range(3):
            container, client, session_id, headers = self.build_runner(route_index)
            result, decision_index = self.reach_day_three(
                container, client, session_id, headers, route_index
            )
            visited_days = [3]
            for story_day in range(3, 91):
                if result["visible_state"]["status"] == "ended":
                    break
                result = self.drain_required_group_conversation(
                    client,
                    session_id,
                    headers,
                    result,
                    f"route-{route_index}-day-{story_day:02d}",
                )
                result, decision_index = self.drain_decisions(
                    container,
                    client,
                    session_id,
                    headers,
                    result,
                    route_index,
                    decision_index,
                )
                result = self.end_day(
                    client,
                    session_id,
                    headers,
                    result,
                    f"route-{route_index}-end-{story_day:02d}",
                )
                visited_days.append(result["visible_state"]["story"]["day"])

            self.assertEqual("ended", result["visible_state"]["status"])
            self.assertEqual(90, result["visible_state"]["story"]["day"])
            self.assertEqual(list(range(3, 91)), visited_days)
            stored = container.sessions.get_owned(session_id, headers["X-Account-ID"])
            content_ids = [
                item.content_instance_id
                for item in stored.narrative_feed
                if item.content_instance_id
            ]
            self.assertEqual(len(content_ids), len(set(content_ids)))
            sequence = tuple(
                (item["decision_id"], item["option_id"])
                for item in stored.logs
                if item.get("type") == "decision"
            )
            self.assertGreaterEqual(len(sequence), 70)
            choice_by_decision = dict(sequence)
            if route_index == 0:
                self.assertEqual("b", choice_by_decision["dp2_01"])
                d30_morning = [
                    item.text
                    for item in stored.narrative_feed
                    if item.story_day == 30 and item.kind == "morning_card"
                ]
                self.assertEqual(
                    [
                        "县城茶楼昨晚有人订了包间，订到子夜。",
                        "柳林村昨夜有人挨家串门，说的还是苗喜旺那笔钱。",
                    ],
                    d30_morning,
                )
            if route_index == 1:
                self.assertEqual("d", choice_by_decision["dp2_01"])
                d18_text = "\n".join(
                    item.text for item in stored.narrative_feed if item.story_day == 18
                )
                self.assertIn("赵建国", d18_text)
                self.assertIn("钱伟没有登门", d18_text)
                self.assertNotIn("钱伟坐在你办公室", d18_text)
                self.assertNotIn(
                    "县城茶楼昨晚有人订了包间",
                    "\n".join(
                        item.text
                        for item in stored.narrative_feed
                        if item.story_day in {29, 30}
                    ),
                )
                self.assertEqual(
                    [],
                    [
                        item.text
                        for item in stored.narrative_feed
                        if item.story_day == 30 and item.kind == "morning_card"
                    ],
                )
            route_sequences.append(sequence)
            player_text = "\n".join(item.text for item in stored.narrative_feed)
            for marker in (
                "开启旗标", "关闭旗标", "本节点", "状态量", "结局轴",
                "代码照此算", "行动点重置", "轴 T", "flag_",
            ):
                self.assertNotIn(marker, player_text)
            client.__exit__(None, None, None)

        self.assertEqual(3, len(set(route_sequences)))

    def replay_published_witness(
        self, route_index: int, profile, contract_terms: dict[str, dict]
    ) -> dict:
        print(f"replaying {profile.route_id}", flush=True)
        container, client, session_id, headers = self.build_runner(route_index)
        try:
            return self._replay_published_witness(
                container,
                client,
                session_id,
                headers,
                profile,
                contract_terms,
            )
        finally:
            client.__exit__(None, None, None)

    def _replay_published_witness(
        self,
        container,
        client,
        session_id: str,
        headers: dict[str, str],
        profile,
        contract_terms: dict[str, dict],
    ) -> dict:
        result, serial = self.reach_day_three_with_profile(
            container, client, session_id, headers, profile
        )
        target_signed = int(
            profile.daily_action_policy[0]["target_signed_households"]
        )
        processed_representatives: set[str] = set()
        people_axis = str(
            profile.conversation_strategies.get("people_axis", "route_default")
        )
        selected_demand_ids = PEOPLE_AXIS_DEMAND_IDS.get(
            people_axis, frozenset()
        )
        for story_day in range(3, 91):
            if result["visible_state"]["status"] == "ended":
                break
            result = self.drain_required_group_conversation(
                client,
                session_id,
                headers,
                result,
                f"{profile.route_id}-day-{story_day:02d}",
            )
            # A profile may legally choose an evidence-gated option that was
            # opened by the previous day's archive release.  Acquire all
            # currently available evidence before attempting that decision.
            result = self.inspect_all_available_archives(
                client, session_id, headers, result
            )
            result, serial = self.drain_profile_decisions(
                container,
                client,
                session_id,
                headers,
                result,
                profile,
                serial,
            )
            allowed_opportunity_ids = {
                "opp_d53_tan_laoliu_paid_recovery",
                "opp_d55_yuan_guilan_paid_recovery",
            }
            configured_grave_choice = profile.decision_policy.get("dp5_03")
            if configured_grave_choice == "a":
                allowed_opportunity_ids.add("opp_03_zhou_kuiyuan_contact")
            allowed_opportunity_ids.update(
                DEMAND_OPPORTUNITY_BY_ID[demand_id]
                for demand_id in selected_demand_ids
            )
            result, serial = self.drain_optional_opportunities(
                container,
                client,
                session_id,
                headers,
                result,
                profile,
                serial,
                allowed_opportunity_ids,
            )
            result = self.inspect_all_available_archives(
                client, session_id, headers, result
            )
            result = self.sign_contracts_toward_target(
                client,
                session_id,
                headers,
                result,
                target_signed=target_signed,
                contract_terms=contract_terms,
                processed_representatives=processed_representatives,
            )
            result = self.end_day(
                client,
                session_id,
                headers,
                result,
                f"{profile.route_id}-end-{story_day:02d}",
            )
        ending = result["visible_state"]["ending"]
        stored_session = container.sessions.get_owned(
            session_id, headers["X-Account-ID"]
        )
        witness = {
            "route_id": profile.route_id,
            "expected_main": profile.target_main_ending_ids[0],
            "expected_sub": profile.target_sub_ending_ids[0],
            "story_day": result["visible_state"]["story"]["day"],
            "main_ending_id": ending["main_ending_id"],
            "sub_ending_id": ending["sub_ending_id"],
            "ledger": result["visible_state"]["ledger"]["signed_households"],
            "axes": ending["axes"],
            "people_score_evidence": self.people_score_evidence(stored_session),
            "signed_contracts": sorted(
                contract.household_id
                for contract in stored_session.household_contracts.values()
                if contract.status == "signed"
            ),
            "demand_status_counts": dict(Counter(
                str(item.get("status", "unknown"))
                for item in stored_session.npc_demand_states.values()
            )),
            "people_flags": sorted(
                stored_session.flags
                & {
                    "吴秀英同盟", "困难户帮扶", "样板签约", "最后一公里攻坚成功",
                    "额外补偿", "毛坯据实", "血铅补实", "俯身接怨", "民生优先",
                    "秀英寒心", "越级上访", "虚假签约", "强制施压", "样板充数",
                    "面子优先", "压制媒体", "宗族对立", "暴力驱逐", "掘坟结怨",
                }
            ),
        }
        print(
            f"completed {profile.route_id}: {ending['main_ending_id']}/"
            f"{ending['sub_ending_id']}",
            flush=True,
        )
        return witness

    @staticmethod
    def people_score_evidence(session) -> dict:
        from serious_game_backend.application.ending_service import EndingAxisProjector
        positive = sorted(session.flags & EndingAxisProjector.POSITIVE_PEOPLE_FLAGS)
        negative = sorted(session.flags & EndingAxisProjector.NEGATIVE_PEOPLE_FLAGS)
        heavy = sorted(session.flags & EndingAxisProjector.HEAVY_PEOPLE_FLAGS)
        return {"score": len(positive) - len(negative) - 2 * len(heavy),
                "positive": positive, "negative": negative, "heavy": heavy}

    def test_every_published_ending_witness_replays_through_formal_api(self) -> None:
        from tools.run_story_routes_v3_isolated import run_isolated

        output = os.environ.get("STORY_ROUTES_V3_SUMMARY")
        summary = run_isolated(
            worker_count=8,
            output_path=Path(output) if output else None,
        )
        self.assertEqual(95, summary["route_count"])
        self.assertEqual(24, summary["main_ending_count"])
        self.assertEqual(95, summary["sub_ending_count"])


if __name__ == "__main__":
    unittest.main()
