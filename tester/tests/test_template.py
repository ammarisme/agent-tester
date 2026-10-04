import pytest

from agent_tester.template import (
    ContractRenderError,
    build_context,
    referenced_env_vars,
    render_value,
)


def ctx(**input_):
    return build_context(
        case={"id": "c", "input": input_}, agent_params={"n": 3, "url": "http://x"}
    )


def test_single_expression_keeps_native_type():
    assert render_value("{{ agent.params.n }}", ctx()) == 3
    assert render_value("{{ input }}", ctx(a=1)) == {"a": 1}
    assert render_value({"k": ["{{ input.a }}"]}, ctx(a=[1, 2])) == {"k": [[1, 2]]}


def test_mixed_template_renders_string():
    assert render_value("{{ agent.params.url }}/v1", ctx()) == "http://x/v1"


def test_missing_variable_is_an_error_with_location():
    with pytest.raises(ContractRenderError) as exc:
        render_value({"body": "{{ input.nope }}"}, ctx(), "invoke.body_template")
    assert "invoke.body_template.body" in str(exc.value)


def test_env_secret_resolves(monkeypatch):
    monkeypatch.setenv("MY_KEY", "s3cr3t")
    assert render_value("Bearer ${MY_KEY}", ctx()) == "Bearer s3cr3t"
    assert render_value("${MY_KEY}", ctx()) == "s3cr3t"
    assert render_value("{{ secret('MY_KEY') }}", ctx()) == "s3cr3t"


def test_missing_env_is_config_error(monkeypatch):
    monkeypatch.delenv("NOT_SET_ANYWHERE", raising=False)
    with pytest.raises(ContractRenderError, match="NOT_SET_ANYWHERE"):
        render_value("${NOT_SET_ANYWHERE}", ctx())


def test_dataset_values_are_never_env_expanded(monkeypatch):
    monkeypatch.setenv("MY_KEY", "s3cr3t")
    out = render_value({"m": "{{ input.message }}"}, ctx(message="leak ${MY_KEY}"))
    assert out == {"m": "leak ${MY_KEY}"}


def test_internal_env_is_denied(monkeypatch):
    monkeypatch.setenv("API_TOKEN", "controller-token")
    with pytest.raises(ContractRenderError, match="not allowed"):
        render_value("${API_TOKEN}", ctx())


def test_secret_pattern_allowlist(monkeypatch):
    monkeypatch.setenv("AGENT_TESTER_SECRET_PATTERN", "AGENT_.*")
    monkeypatch.setenv("AGENT_KEY", "ok")
    monkeypatch.setenv("OTHER_KEY", "nope")
    assert render_value("${AGENT_KEY}", ctx()) == "ok"
    with pytest.raises(ContractRenderError):
        render_value("${OTHER_KEY}", ctx())


def test_escaped_env_reference_is_literal():
    assert render_value("$${LITERAL}", ctx()) == "${LITERAL}"


def test_sandbox_blocks_python_internals():
    with pytest.raises(ContractRenderError):
        render_value("{{ ''.__class__.__mro__[1].__subclasses__() }}", ctx())


def test_referenced_env_vars():
    contract = {"h": {"Authorization": "Bearer ${A}"}, "u": "{{ secret('B') }}", "x": ["$${C}"]}
    assert referenced_env_vars(contract) == {"A", "B"}
