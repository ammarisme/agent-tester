from __future__ import annotations

import asyncio
import csv
import io
import json

from app.config import settings

from .conftest import MOCK_BASE, echo_contract, make_agent, make_dataset


async def wait_for_run(client, run_id: str) -> dict:
    await client.app.state.runs.wait(run_id)
    return (await client.get(f"/api/runs/{run_id}")).json()


# ── meta ─────────────────────────────────────────────────────────────


async def test_health_and_meta(client):
    assert (await client.get("/api/health")).json()["status"] == "ok"
    meta = (await client.get("/api/meta")).json()
    assert meta["runner_mode"] == "inprocess"
    assert "success" in meta["outcome_classes"]


async def test_presets_are_valid_and_demo_first(client):
    presets = (await client.get("/api/presets")).json()
    assert presets[0]["category"] == "demo"
    for p in presets:
        resp = await client.post(
            "/api/agents",
            json={"name": p["name"], "contract": p["contract"], "params": p["params"]},
        )
        assert resp.status_code == 201, (p["id"], resp.text)


async def test_demo_is_idempotent(client):
    first = (await client.post("/api/demo")).json()
    second = (await client.post("/api/demo")).json()
    assert first == second
    assert len((await client.get("/api/agents")).json()) == 2


# ── agents ───────────────────────────────────────────────────────────


async def test_agent_crud(client):
    agent = await make_agent(client)
    assert agent["params"] == {"base_url": MOCK_BASE}
    resp = await client.patch(
        f"/api/agents/{agent['id']}", json={"name": "renamed", "enabled": False}
    )
    assert resp.json()["name"] == "renamed" and resp.json()["enabled"] is False
    dup = (await client.post(f"/api/agents/{agent['id']}/duplicate")).json()
    assert dup["name"] == "renamed (copy)"
    assert (await client.delete(f"/api/agents/{agent['id']}")).status_code == 204
    assert (await client.get(f"/api/agents/{agent['id']}")).status_code == 404


async def test_invalid_contract_reports_locations(client):
    bad = {"invoke": {"url": "", "method": "FETCH"}, "extract": {"x": "$$bad["}, "extra": 1}
    resp = await client.post("/api/agents", json={"name": "x", "contract": bad})
    assert resp.status_code == 422
    body = resp.json()
    locs = {e["loc"] for e in body["errors"]}
    assert {"contract.invoke.url", "contract.invoke.method", "contract.extra"} <= locs
    assert body["detail"] == "contract is invalid"


async def test_literal_credentials_are_rejected(client):
    contract = echo_contract()
    contract["invoke"]["headers"]["Authorization"] = "Bearer sk-live-123456"
    resp = await client.post("/api/agents", json={"name": "x", "contract": contract})
    assert resp.status_code == 422
    assert resp.json()["errors"][0]["loc"] == "contract.invoke.headers.Authorization"
    contract["invoke"]["headers"]["Authorization"] = "Bearer ${AGENT_API_KEY}"
    assert (
        await client.post("/api/agents", json={"name": "x", "contract": contract})
    ).status_code == 201


async def test_dry_run_returns_trajectory(client):
    resp = await client.post(
        "/api/agents/test",
        json={
            "contract": echo_contract(),
            "params": {"base_url": MOCK_BASE},
            "input": {"message": "ping"},
            "expected": {"contains": "ping"},
        },
    )
    assert resp.status_code == 200, resp.text
    r = resp.json()
    assert r["outcome_class"] == "success" and r["passed"] is True
    assert r["final_text"] == "Echo: ping"
    assert r["trajectory"]["steps"][0]["url"] == f"{MOCK_BASE}/v1/chat"
    assert r["metrics"]["tokens"] == 2


async def test_dry_run_config_error_is_a_result_not_a_500(client):
    r = (
        await client.post("/api/agents/test", json={"contract": echo_contract(), "input": {}})
    ).json()
    assert r["outcome_class"] == "config_error"


# ── datasets ─────────────────────────────────────────────────────────


async def test_parse_preview_reports_line_errors(client):
    text = '{"id": "a"}\n{oops\n{"id": "a"}\n'
    r = (
        await client.post("/api/datasets/parse", json={"text": text, "filename": "x.jsonl"})
    ).json()
    assert r["count"] == 0 and r["format"] == "jsonl"
    assert [e["line"] for e in r["errors"]] == [2, 3]
    ok = (await client.post("/api/datasets/parse", json={"text": "id,message\n1,hi\n"})).json()
    assert ok["format"] == "csv" and ok["preview"][0]["input"] == {"message": "hi"}


async def test_import_replace_append_and_export(client):
    ds = await make_dataset(client)
    files = {"file": ("more.jsonl", b'{"id": "c", "input": {"message": "x"}, "tags": ["new"]}\n')}
    resp = await client.post(f"/api/datasets/{ds['id']}/import?mode=append", files=files)
    assert resp.json()["case_count"] == 3
    assert resp.json()["tags"] == ["new", "smoke"]
    clash = await client.post(f"/api/datasets/{ds['id']}/import?mode=append", files=files)
    assert clash.status_code == 409
    resp = await client.post(f"/api/datasets/{ds['id']}/import", files=files)
    assert resp.json()["case_count"] == 1

    bad = {"file": ("bad.jsonl", b'{"id": "z", "expected": {"contain": "x"}}\n')}
    resp = await client.post(f"/api/datasets/{ds['id']}/import", files=bad)
    assert resp.status_code == 422 and resp.json()["errors"][0]["line"] == 1

    page = (await client.get(f"/api/datasets/{ds['id']}/cases?q=c")).json()
    assert page["total"] == 1 and page["items"][0]["id"] == "c"
    export = await client.get(f"/api/datasets/{ds['id']}/export")
    assert json.loads(export.text.strip())["id"] == "c"


async def test_uri_dataset_requires_http(client):
    resp = await client.post(
        "/api/datasets", json={"name": "x", "source_type": "uri", "uri": "file:///etc/passwd"}
    )
    assert resp.status_code == 422


# ── runs ─────────────────────────────────────────────────────────────


async def test_run_lifecycle_results_and_exports(client):
    agent = await make_agent(client)
    ds = await make_dataset(client)
    resp = await client.post(
        "/api/runs",
        json={
            "name": "nightly",
            "agent_ids": [agent["id"]],
            "dataset_id": ds["id"],
            "options": {"repeats": 2},
        },
    )
    assert resp.status_code == 201, resp.text
    run = await wait_for_run(client, resp.json()["id"])
    assert run["status"] == "completed", run["error"]
    assert run["progress"] == {"completed": 4, "total": 4}
    assert run["agents"] == [{"id": agent["id"], "name": "echo"}]
    s = run["summary"][agent["id"]]
    assert s["pass_rate"] == 0.5 and s["trials"] == 2
    assert s["consistency"]["flaky_cases"] == 0

    page = (await client.get(f"/api/runs/{run['id']}/results?outcome=failed_assert")).json()
    assert page["total"] == 2
    row = page["items"][0]
    assert row["failures"] == ["contains: missing 'nope'"]
    detail = (await client.get(f"/api/runs/{run['id']}/results/{row['id']}")).json()
    assert detail["input"] == {"message": "yo"} and detail["trajectory"]["steps"]

    csv_text = (await client.get(f"/api/runs/{run['id']}/export?format=csv")).text
    assert len(list(csv.DictReader(io.StringIO(csv_text)))) == 4
    assert "<testsuites" in (await client.get(f"/api/runs/{run['id']}/export?format=junit")).text
    exported = (await client.get(f"/api/runs/{run['id']}/export")).json()
    assert len(exported["case_results"]) == 4

    listing = (await client.get("/api/runs?q=nightly")).json()
    assert listing["total"] == 1

    rerun = (await client.post(f"/api/runs/{run['id']}/rerun")).json()
    assert (await wait_for_run(client, rerun["id"]))["status"] == "completed"


async def test_run_validation_messages(client):
    agent = await make_agent(client)
    empty = (await client.post("/api/datasets", json={"name": "empty"})).json()
    resp = await client.post(
        "/api/runs", json={"agent_ids": [agent["id"]], "dataset_id": empty["id"]}
    )
    assert resp.status_code == 422 and "no cases" in resp.json()["errors"][0]["message"]
    resp = await client.post(
        "/api/runs",
        json={"agent_ids": [agent["id"]], "dataset_uri": "http://x", "options": {"concurrency": 0}},
    )
    assert resp.json()["errors"][0]["loc"] == "options.concurrency"
    resp = await client.post("/api/runs", json={"agent_ids": ["nope"], "dataset_uri": "http://x"})
    assert "not found" in resp.json()["errors"][0]["message"]


async def test_cancel_running_run(client, monkeypatch):
    import app.services.runner as runner_mod

    started = asyncio.Event()

    async def slow_run_job(job, **kwargs):
        started.set()
        await asyncio.sleep(30)

    monkeypatch.setattr(runner_mod, "run_job", slow_run_job)
    agent = await make_agent(client)
    ds = await make_dataset(client)
    run = (
        await client.post("/api/runs", json={"agent_ids": [agent["id"]], "dataset_id": ds["id"]})
    ).json()
    await asyncio.wait_for(started.wait(), 5)
    resp = await client.post(f"/api/runs/{run['id']}/cancel")
    assert resp.json()["status"] == "cancelled"
    assert (await client.post(f"/api/runs/{run['id']}/cancel")).status_code == 409
    assert (await client.delete(f"/api/runs/{run['id']}")).status_code == 204


async def test_failed_dataset_fetch_marks_run_failed(client):
    agent = await make_agent(client)
    run = (
        await client.post(
            "/api/runs",
            json={"agent_ids": [agent["id"]], "dataset_uri": f"{MOCK_BASE}/missing.jsonl"},
        )
    ).json()
    done = await wait_for_run(client, run["id"])
    assert done["status"] == "failed" and "404" in done["error"]


async def test_ingest_from_docker_runner(client):
    agent = await make_agent(client)
    ds = await make_dataset(client)
    run = (
        await client.post("/api/runs", json={"agent_ids": [agent["id"]], "dataset_id": ds["id"]})
    ).json()
    await wait_for_run(client, run["id"])
    payload = {
        "run_id": run["id"],
        "status": "completed",
        "case_results": [
            {
                "agent_id": agent["id"],
                "agent_name": "echo",
                "case_id": "z",
                "outcome_class": "success",
            }
        ],
        "summary": {},
    }
    assert (
        await client.post(f"/api/runs/{run['id']}/results", json={**payload, "run_id": "x"})
    ).status_code == 400
    assert (await client.post(f"/api/runs/{run['id']}/results", json=payload)).json() == {
        "ok": True
    }
    assert (await client.get(f"/api/runs/{run['id']}/results")).json()["total"] == 1


# ── auth ─────────────────────────────────────────────────────────────


async def test_api_token(client, monkeypatch):
    monkeypatch.setattr(settings, "api_token", "t0ken")
    assert (await client.get("/api/health")).status_code == 200
    assert (await client.get("/api/agents")).status_code == 401
    assert (
        await client.get("/api/agents", headers={"Authorization": "Bearer wrong"})
    ).status_code == 401
    assert (
        await client.get("/api/agents", headers={"Authorization": "Bearer t0ken"})
    ).status_code == 200


async def test_extra_case_fields_reach_templates(client):
    contract = echo_contract()
    contract["invoke"]["body_template"] = {"message": "{{ case.locale }}: {{ input.message }}"}
    agent = await make_agent(client, contract=contract)
    ds = await make_dataset(client, cases=[{"id": "x", "input": {"message": "hi"}, "locale": "de"}])
    run = (
        await client.post("/api/runs", json={"agent_ids": [agent["id"]], "dataset_id": ds["id"]})
    ).json()
    await wait_for_run(client, run["id"])
    row = (await client.get(f"/api/runs/{run['id']}/results")).json()["items"][0]
    assert row["final_text_preview"] == "Echo: de: hi"
