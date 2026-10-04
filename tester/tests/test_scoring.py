import pytest
from pydantic import ValidationError

from agent_tester.models import Expectations
from agent_tester.scoring import score


def run(expected, text="Echo: hi", response=None, extracted=None, latency=10.0):
    return score(
        Expectations.model_validate(expected),
        final_text=text,
        response=response,
        extracted=extracted or {},
        latency_ms=latency,
    )


def test_no_expectations_is_unscored():
    assert score(None, final_text="x", response=None, extracted={}, latency_ms=1) == (None, [])
    assert run({}) == (None, [])


def test_contains_and_not_contains():
    assert run({"contains": ["Echo", "hi"]}) == (True, [])
    ok, failures = run({"contains": "nope", "not_contains": ["Echo"]})
    assert ok is False
    assert failures == ["contains: missing 'nope'", "not_contains: found 'Echo'"]


def test_equals_string_and_json():
    assert run({"equals": "Echo: hi"})[0] is True
    assert run({"equals": {"a": 1}}, text='{"a": 1}')[0] is True
    ok, failures = run({"equals": "other"})
    assert not ok
    assert "expected 'other', got 'Echo: hi'" in failures[0]


def test_equals_null_is_a_real_expectation():
    assert run({"equals": None}, text="null")[0] is True


def test_regex():
    assert run({"regex": r"^Echo:\s+h"})[0] is True
    assert run({"regex": "^nope"})[1] == ["regex: /^nope/ did not match"]


def test_jsonpath_against_response_and_extracted():
    response = {"data": {"status": "ok", "n": 2}}
    assert run(
        {"jsonpath_equals": {"$.data.status": "ok", "tokens": 3}},
        response=response,
        extracted={"tokens": 3},
    )[0]
    ok, failures = run({"jsonpath_equals": {"$.data.n": 3, "$.missing": 1}}, response=response)
    assert not ok
    assert failures[0] == "jsonpath_equals: $.data.n expected 3, got 2"
    assert failures[1].startswith("jsonpath_equals: $.missing not found")


def test_latency_budget():
    assert run({"max_latency_ms": 100}, latency=50)[0] is True
    assert "took 150 ms, budget 100 ms" in run({"max_latency_ms": 100}, latency=150)[1][0]


def test_unknown_keys_and_bad_regex_rejected():
    with pytest.raises(ValidationError):
        Expectations.model_validate({"contain": ["typo"]})
    with pytest.raises(ValidationError):
        Expectations.model_validate({"regex": "("})
