import json

import httpx

from agent_tester.engine import evaluate_case, run_job
from agent_tester.models import DatasetRef, EvalJob, EvalOptions

from .conftest import echo_contract, echo_handler, make_agent, make_case


async def test_sync_success_with_expectations(mock_client):
    client = mock_client(echo_handler)
    agent = make_agent(echo_contract())
    r = await evaluate_case(
        client, agent, make_case(input={"message": "hi"}, expected={"contains": "hi"})
    )
    assert r.outcome_class == "success"
    assert r.passed is True
    assert r.final_text == "Echo: hi"
    assert r.status_code == 200
    step = r.trajectory["steps"][0]
    assert step["request_body"] == {"message": "hi"}
    assert step["status_code"] == 200


async def test_4xx_is_agent_error_even_if_body_matches(mock_client):
    # Regression: 4xx used to be classed "success" whenever assertions passed.
    client = mock_client(lambda req: httpx.Response(404, json={"reply": "Echo: hi"}))
    r = await evaluate_case(
        client,
        make_agent(echo_contract()),
        make_case(input={"message": "hi"}, expected={"contains": "hi"}),
    )
    assert r.outcome_class == "agent_error"
    assert r.passed is False
    assert r.error.startswith("HTTP 404")


async def test_timeout_and_transport_errors(mock_client):
    def slow(req):
        raise httpx.ReadTimeout("slow", request=req)

    def refused(req):
        raise httpx.ConnectError("connection refused", request=req)

    agent = make_agent(echo_contract())
    case = make_case(input={"message": "x"})
    assert (await evaluate_case(mock_client(slow), agent, case)).outcome_class == "timeout"
    r = await evaluate_case(
        mock_client(refused), make_agent(echo_contract("http://localhost:1/x")), case
    )
    assert r.outcome_class == "transport_error"
    assert "host.docker.internal" in r.error


async def test_template_problems_are_config_errors(mock_client):
    r = await evaluate_case(
        mock_client(echo_handler), make_agent(echo_contract()), make_case(input={})
    )
    assert r.outcome_class == "config_error"
    assert "invoke.body_template.message" in r.error


async def test_missing_extract_is_warned(mock_client):
    client = mock_client(lambda req: httpx.Response(200, json={"other": 1}))
    r = await evaluate_case(client, make_agent(echo_contract()), make_case(input={"message": "x"}))
    assert r.final_text is None
    assert any("final_text" in w for w in r.trajectory["warnings"])


async def test_numeric_extracts_become_metrics(mock_client):
    contract = echo_contract()
    contract["extract"]["tokens"] = "$.tokens"
    r = await evaluate_case(
        mock_client(echo_handler), make_agent(contract), make_case(input={"message": "x"})
    )
    assert r.metrics["tokens"] == 3.0
    assert "latency_ms" in r.metrics


async def test_secrets_are_scrubbed_everywhere(mock_client, monkeypatch):
    monkeypatch.setenv("AGENT_KEY", "super-secret-value")
    contract = echo_contract("http://agent.test/chat?key=${AGENT_KEY}")
    contract["invoke"]["headers"] = {"X-Custom": "${AGENT_KEY}"}
    client = mock_client(lambda req: httpx.Response(200, json={"reply": f"you sent {req.url}"}))
    r = await evaluate_case(client, make_agent(contract), make_case(input={"message": "x"}))
    dumped = json.dumps(r.model_dump())
    assert "super-secret-value" not in dumped
    assert "***" in r.final_text


async def test_poll_until_done(mock_client):
    state = {"polls": 0}

    def handler(req):
        if req.method == "POST":
            return httpx.Response(202, json={"id": "j1", "status": "RUNNING"})
        state["polls"] += 1
        done = state["polls"] >= 2
        return httpx.Response(
            200, json={"status": "DONE" if done else "RUNNING", "out": "ok" if done else None}
        )

    contract = {
        "invoke": {"url": "http://a/jobs", "body_template": "{{ input }}"},
        "poll": {
            "url_template": "http://a/jobs/{{ extracted.job_id }}",
            "interval_s": 0.05,
            "timeout_s": 5,
            "done_when": "status in ['DONE','FAILED']",
            "extract": {"final_text": "$.out"},
        },
        "extract": {"job_id": "$.id"},
    }
    r = await evaluate_case(mock_client(handler), make_agent(contract), make_case(input={"q": 1}))
    assert r.outcome_class == "success", r.error
    assert r.final_text == "ok"
    assert r.metrics["n_polls"] == 2
    assert [s["phase"] for s in r.trajectory["steps"]] == ["invoke", "poll", "poll"]
    assert r.trajectory["steps"][1]["url"] == "http://a/jobs/j1"


async def test_poll_failed_state_and_timeout(mock_client):
    contract = {
        "invoke": {"url": "http://a/jobs"},
        "poll": {
            "url_template": "http://a/jobs/1",
            "interval_s": 0.05,
            "timeout_s": 0.3,
            "done_when": "status == 'DONE'",
        },
    }

    def failed(req):
        return httpx.Response(200, json={"status": "FAILED"})

    def stuck(req):
        return httpx.Response(200, json={"status": "RUNNING"})

    r = await evaluate_case(mock_client(failed), make_agent(contract), make_case())
    assert r.outcome_class == "agent_error" and "terminal failure" in r.error
    r = await evaluate_case(mock_client(stuck), make_agent(contract), make_case())
    assert r.outcome_class == "timeout"


async def test_run_job_repeats_order_and_progress(mock_client):
    job = EvalJob(
        agents=[make_agent(echo_contract(), name="x"), make_agent(echo_contract(), name="y")],
        dataset=DatasetRef(
            cases=[
                make_case(id="c1", input={"message": "1"}),
                make_case(id="c2", input={"message": "2"}),
            ]
        ),
        options=EvalOptions(repeats=2, concurrency=3),
    )
    seen = []
    results = await run_job(
        job,
        client=mock_client(echo_handler),
        on_result=lambda r, done, total: seen.append((done, total)),
    )
    keys = [(r.agent_id, r.case_id, r.trial) for r in results.case_results]
    assert keys == [(a, c, t) for a in "xy" for c in ("c1", "c2") for t in (0, 1)]
    assert seen[-1] == (8, 8)
    assert set(results.summary) == {"x", "y"}
    assert results.summary["x"]["consistency"]["pass_all_trials_rate"] == 1.0


async def test_scoring_can_be_disabled(mock_client):
    job = EvalJob(
        agents=[make_agent(echo_contract())],
        dataset=DatasetRef(cases=[make_case(input={"message": "a"}, expected={"contains": "zzz"})]),
        options={"pass_fail_mode": False},
    )
    r = (await run_job(job, client=mock_client(echo_handler))).case_results[0]
    assert r.outcome_class == "success" and r.passed is None
