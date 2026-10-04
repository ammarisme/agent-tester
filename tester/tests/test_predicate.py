import pytest

from agent_tester.predicate import PredicateError, parse_predicate


@pytest.mark.parametrize(
    ("expr", "payload", "expected"),
    [
        ("status in ['DONE','FAILED']", {"status": "DONE"}, True),
        ("status in ['DONE','FAILED']", {"status": "RUNNING"}, False),
        ("$.status not in ['RUNNING']", {"status": "DONE"}, True),
        ("status == 'DONE'", {"status": "DONE"}, True),
        ('status != "DONE"', {"status": "DONE"}, False),
        ("result.state == 'ok'", {"result": {"state": "ok"}}, True),
        ("done", {"done": True}, True),
        ("done", {"done": False}, False),
        ("done", {}, False),
        ("progress == 100", {"progress": 100}, True),
        ("status in ['DONE']", "not json", False),
        ("status != 'DONE'", {}, True),
    ],
)
def test_evaluate(expr, payload, expected):
    assert parse_predicate(expr).evaluate(payload) is expected


@pytest.mark.parametrize("expr", ["", "status in 'DONE'", "status == [unclosed", "== 1"])
def test_invalid(expr):
    with pytest.raises(PredicateError):
        parse_predicate(expr)
