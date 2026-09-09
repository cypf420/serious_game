import unittest
from unittest.mock import Mock

from terminal_client.app import TerminalApp


class ContractWorkflowTests(unittest.TestCase):
    def app(self, contract, choices):
        api = Mock()
        api.get_governance.return_value = {"state_version": 5, "contracts": [contract]}
        api.get_contract.return_value = {"state_version": 5, "contract": contract}
        output = []
        app = TerminalApp(api, output_fn=output.append)
        app._require_session = Mock(return_value="session")
        app._select = Mock(side_effect=choices)
        return app, api, output

    def test_existing_preview_submits_without_save_audit_or_text_edit(self):
        contract = {"contract_id": "c", "status": "draft", "term_sheet": {"cash_amount": 27},
                    "contract_text": "第83日", "can_review": True}
        app, api, output = self.app(contract, [0])
        api.review_contract.return_value = {"state_version": 6, "contract": {
            **contract, "status": "signed", "review_decision": "accept",
            "review_reason": "同意", "resource_hold_status": "已分配"}}
        app._process_contract("c")
        api.review_contract.assert_called_once()
        api.set_contract_terms.assert_not_called()
        api.edit_contract_text.assert_not_called()
        self.assertIn("第83日", "".join(output))

    def test_blocked_feedback_offers_modification_without_reroll(self):
        contract = {"contract_id": "c", "status": "rejected", "term_sheet": {"cash_amount": 27},
                    "contract_text": "正文", "can_review": False,
                    "review_version": 2, "review_reason": "想再谈谈"}
        app, api, output = self.app(contract, [1])
        app._process_contract("c")
        api.review_contract.assert_not_called()
        api.set_contract_terms.assert_not_called()
        self.assertIn("方案第2版", "".join(output))

    def test_legacy_cancel_does_not_convert(self):
        contract = {"contract_id": "c", "status": "draft", "legacy_draft": True,
                    "contract_text": "特殊承诺 D83"}
        app, api, output = self.app(contract, [None])
        app._process_contract("c")
        api.set_contract_terms.assert_not_called()
        api.review_contract.assert_not_called()
        self.assertIn("特殊承诺 D83", "".join(output))

    def test_signed_original_is_shown_without_changes(self):
        contract = {"contract_id": "c", "status": "signed", "contract_text": "历史 D83 原文",
                    "resource_hold_status": "已分配"}
        app, api, output = self.app(contract, [])
        app._process_contract("c")
        self.assertIn("历史 D83 原文", output)
        api.set_contract_terms.assert_not_called()
        api.review_contract.assert_not_called()

    def test_legacy_confirmation_is_sent_with_saved_scheme(self):
        contract = {"contract_id": "c", "status": "draft", "legacy_draft": True,
                    "contract_text": "旧约定"}
        app, api, _ = self.app(contract, [0, 0, 0, 1, None])
        api.get_governance.return_value.update(
            documents=[{"document_id": "policy", "document_type": "compensation_policy", "status": "published"}],
            resources={"budget_envelopes": {"housing_delivery": {"available": 2000}}, "resource_pools": []},
        )
        app.state = {"story": {"day": 10}}
        app._input_contract_integer = Mock(side_effect=[27, 83, 83, 0])
        app._prompt_service_allocations = Mock(return_value={})
        app._prompt_approval_documents = Mock(return_value=[])
        api.set_contract_terms.return_value = {"state_version": 6, "contract": {
            **contract, "legacy_draft": False, "can_review": True}}
        app._process_contract("c")
        terms = api.set_contract_terms.call_args.kwargs["term_sheet"]
        self.assertIs(terms["acknowledge_legacy_text"], True)
        self.assertEqual(10, terms["payment_day"])
        self.assertNotIn("authorization_confirmed", terms)
        api.edit_contract_text.assert_not_called()
