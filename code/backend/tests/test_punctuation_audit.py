from tools.audit_player_punctuation import _issues_for


def test_corner_quotes_are_reported_instead_of_a_false_clean_result():
    assert any("角引号" in issue for issue in _issues_for("蒋崇岳：「晚上老赵约你了吧。」"))
    assert any("角引号" in issue for issue in _issues_for("他说：「所谓『办妥』还要核实。」"))


def test_curly_quotes_and_urls_do_not_create_corner_quote_findings():
    assert _issues_for("他说：“所谓‘办妥’还要核实。”") == []
    assert _issues_for("https://example.test/a?q=1") == []
