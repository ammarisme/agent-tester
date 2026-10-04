"""``agent-tester`` command line.

Exit codes (stable, documented in docs/cli.md):
    0  run completed and all gates passed
    1  run completed but a quality gate failed
    2  invalid input (contract, dataset, job, flags)
    3  run failed or results could not be delivered to --callback-url
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx
from pydantic import BaseModel, TypeAdapter, ValidationError

from agent_tester._version import __version__
from agent_tester.dataset import DatasetParseError, load_dataset, parse_cases
from agent_tester.engine import run_job
from agent_tester.models import (
    AgentContract,
    AgentSpec,
    Case,
    DatasetRef,
    EvalJob,
    EvalOptions,
    RunResults,
)
from agent_tester.report import Progress, check_gates, junit_xml, render_summary, summary_line

EXIT_OK, EXIT_GATE, EXIT_INPUT, EXIT_RUN = 0, 1, 2, 3


class InputError(Exception):
    pass


def _err(msg: str) -> None:
    print(f"error: {msg}", file=sys.stderr)


def _read_json_source(source: str) -> Any:
    try:
        if source.startswith(("http://", "https://")):
            resp = httpx.get(source, timeout=60.0, follow_redirects=True)
            resp.raise_for_status()
            return resp.json()
        return json.loads(Path(source).read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise InputError(f"file not found: {source}") from exc
    except json.JSONDecodeError as exc:
        raise InputError(f"{source}: invalid JSON at line {exc.lineno}: {exc.msg}") from exc
    except httpx.HTTPError as exc:
        raise InputError(f"could not fetch {source}: {exc}") from exc


def _format_validation(exc: ValidationError, source: str) -> str:
    lines = [f"{source} is invalid:"]
    for e in exc.errors():
        loc = ".".join(str(p) for p in e["loc"])
        lines.append(f"  - {loc or '(root)'}: {e['msg']}")
    return "\n".join(lines)


def load_agent_file(path: str) -> AgentSpec:
    """Accepts a preset-style file ({name, contract, params}) or a bare contract."""
    raw = _read_json_source(path)
    if not isinstance(raw, dict):
        raise InputError(f"{path}: expected a JSON object")
    try:
        if "contract" in raw:
            return AgentSpec.model_validate(
                {
                    "id": raw.get("id") or Path(path).stem,
                    "name": raw.get("name") or Path(path).stem,
                    "contract": raw["contract"],
                    "params": raw.get("params") or {},
                }
            )
        return AgentSpec(
            id=Path(path).stem, name=Path(path).stem, contract=AgentContract.model_validate(raw)
        )
    except ValidationError as exc:
        raise InputError(_format_validation(exc, path)) from exc


def _parse_params(pairs: list[str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise InputError(f"--param expects KEY=VALUE, got {pair!r}")
        try:
            out[key] = json.loads(value)
        except json.JSONDecodeError:
            out[key] = value
    return out


def _build_job(args: argparse.Namespace) -> EvalJob:
    if args.job:
        raw = _read_json_source(args.job)
        try:
            job = EvalJob.model_validate(raw)
        except ValidationError as exc:
            raise InputError(_format_validation(exc, args.job)) from exc
        overrides = {
            k: v
            for k, v in {
                "concurrency": args.concurrency,
                "repeats": args.repeats,
                "score_expectations": False if args.no_score else None,
            }.items()
            if v is not None
        }
        if overrides:
            try:
                job.options = EvalOptions.model_validate({**job.options.model_dump(), **overrides})
            except ValidationError as exc:
                raise InputError(_format_validation(exc, "options")) from exc
        return job

    if not args.agent or not args.dataset:
        raise InputError("provide --job, or both --agent and --dataset")
    agents = [load_agent_file(p) for p in args.agent]
    overrides = _parse_params(args.param or [])
    for agent in agents:
        agent.params = {**agent.params, **overrides}
    ids = [a.id for a in agents]
    if len(set(ids)) != len(ids):
        raise InputError(
            "two --agent files resolve to the same id; give them distinct ids or file names"
        )
    opts: dict[str, Any] = {}
    if args.concurrency is not None:
        opts["concurrency"] = args.concurrency
    if args.repeats is not None:
        opts["repeats"] = args.repeats
    if args.no_score:
        opts["score_expectations"] = False
    try:
        options = EvalOptions.model_validate(opts)
    except ValidationError as exc:
        raise InputError(_format_validation(exc, "options")) from exc
    kwargs: dict[str, Any] = {
        "agents": agents,
        "dataset": DatasetRef(uri=args.dataset),
        "options": options,
    }
    if args.run_id:
        kwargs["run_id"] = args.run_id
    return EvalJob(**kwargs)


async def _post_callback(url: str, payload: dict[str, Any]) -> None:
    headers = {}
    token = os.environ.get("AGENT_TESTER_CALLBACK_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(timeout=60.0) as client:
        for attempt in range(3):
            try:
                resp = await client.post(url, json=payload, headers=headers)
                resp.raise_for_status()
                return
            except httpx.HTTPError:
                if attempt == 2:
                    raise
                await asyncio.sleep(2**attempt)


def _write(path: str, text: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(text, encoding="utf-8")


async def _cmd_run(args: argparse.Namespace) -> int:
    try:
        job = _build_job(args)
    except InputError as exc:
        _err(str(exc))
        return EXIT_INPUT
    callback = args.callback_url or job.callback_url

    try:
        cases = await load_dataset(job.dataset)
    except (DatasetParseError, OSError, ValueError, httpx.HTTPError) as exc:
        _err(f"could not load dataset: {exc}")
        if callback:
            await _report_failure(callback, job.run_id, f"could not load dataset: {exc}")
        return EXIT_INPUT
    if not cases:
        _err("dataset has no cases")
        return EXIT_INPUT

    total = len(job.agents) * len(cases) * job.options.repeats
    if not args.quiet:
        print(
            f"agent-tester {__version__} · {len(job.agents)} agent(s) × {len(cases)} case(s) × "
            f"{job.options.repeats} trial(s) = {total} evaluations",
            file=sys.stderr,
        )

    progress = Progress(enabled=not args.quiet)
    try:
        results = await run_job(
            job,
            cases=cases,
            on_result=lambda r, done, tot: progress.update(r.outcome_class, done, tot),
        )
    except Exception as exc:
        progress.close()
        _err(f"run failed: {exc}")
        if callback:
            await _report_failure(callback, job.run_id, str(exc))
        return EXIT_RUN
    progress.close()

    gates = check_gates(
        results,
        fail_under=args.fail_under,
        max_error_rate=args.max_error_rate,
        max_p95_ms=args.max_p95_ms,
    )
    payload = results.model_dump(mode="json")
    if args.out:
        _write(args.out, json.dumps(payload, indent=2, ensure_ascii=False))
    if args.junit:
        _write(args.junit, junit_xml(results))

    if args.format == "json":
        print(json.dumps(summary_line(results)))
    elif not args.quiet:
        render_summary(results, gates)

    code = EXIT_GATE if any(not g.ok for g in gates) else EXIT_OK
    if callback:
        try:
            await _post_callback(callback, payload)
        except httpx.HTTPError as exc:
            _err(f"results callback to {callback} failed: {exc}")
            return EXIT_RUN
    return code


async def _report_failure(callback: str, run_id: str, message: str) -> None:
    failed = RunResults(run_id=run_id, status="failed", error=message, tester_version=__version__)
    try:
        await _post_callback(callback, failed.model_dump(mode="json"))
    except httpx.HTTPError as exc:
        _err(f"could not report failure to {callback}: {exc}")


def _cmd_validate(args: argparse.Namespace) -> int:
    ok = True
    for path in args.agent or []:
        try:
            spec = load_agent_file(path)
            print(f"✓ agent {path} ({spec.name})")
        except InputError as exc:
            ok = False
            _err(str(exc))
    for path in args.dataset or []:
        try:
            cases = parse_cases(Path(path).read_text(encoding="utf-8"), path)
            print(f"✓ dataset {path} ({len(cases)} cases)")
        except FileNotFoundError:
            ok = False
            _err(f"file not found: {path}")
        except DatasetParseError as exc:
            ok = False
            _err(f"{path}:")
            for e in exc.errors:
                where = f"line {e['line']}: " if e.get("line") else ""
                print(f"  - {where}{e['message']}", file=sys.stderr)
    for path in args.job or []:
        try:
            EvalJob.model_validate(_read_json_source(path))
            print(f"✓ job {path}")
        except InputError as exc:
            ok = False
            _err(str(exc))
        except ValidationError as exc:
            ok = False
            _err(_format_validation(exc, path))
    if not (args.agent or args.dataset or args.job):
        _err("nothing to validate; pass --agent, --dataset or --job")
        return EXIT_INPUT
    return EXIT_OK if ok else EXIT_INPUT


SCHEMAS: dict[str, type[BaseModel]] = {
    "contract": AgentContract,
    "case": Case,
    "job": EvalJob,
    "results": RunResults,
}


def json_schema(name: str) -> dict[str, Any]:
    if name == "dataset":
        schema = TypeAdapter(list[Case]).json_schema()
        schema["title"] = "Dataset"
        schema["description"] = (
            "A JSON dataset: an array of cases (JSONL files hold one case per line)."
        )
        return schema
    return SCHEMAS[name].model_json_schema()


def _cmd_schema(args: argparse.Namespace) -> int:
    schema = json_schema(args.name)
    print(json.dumps(schema, indent=2))
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-tester",
        description="Statistical evaluation runner for HTTP agents.",
        epilog="Docs: docs/cli.md · exit codes: 0 ok, 1 gate failed, 2 bad input, 3 run/callback failed",
    )
    parser.add_argument("--version", action="version", version=f"agent-tester {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    run = sub.add_parser("run", help="Evaluate agents against a dataset")
    src = run.add_argument_group("what to run")
    src.add_argument(
        "--job", metavar="PATH|URL", help="Full EvalJob JSON (as produced by the controller)"
    )
    src.add_argument(
        "--agent",
        action="append",
        metavar="PATH",
        help="Agent file ({name, contract, params}); repeatable",
    )
    src.add_argument(
        "--dataset", metavar="PATH|URL", help="Dataset file or URL (JSON, JSONL or CSV)"
    )
    src.add_argument(
        "--param",
        action="append",
        metavar="KEY=VALUE",
        help="Override agent.params.KEY for every --agent (e.g. base_url=http://localhost:9999)",
    )
    src.add_argument("--run-id", help="Explicit run id (default: random UUID)")

    opt = run.add_argument_group("evaluation")
    opt.add_argument("--concurrency", type=int, help="Parallel requests (default 8)")
    opt.add_argument(
        "--repeats", type=int, help="Trials per case, to measure consistency (default 1)"
    )
    opt.add_argument(
        "--no-score", action="store_true", help="Ignore 'expected'; report outcome classes only"
    )

    out = run.add_argument_group("output")
    out.add_argument("--out", metavar="PATH", help="Write full results JSON")
    out.add_argument("--junit", metavar="PATH", help="Write JUnit XML for CI test reporting")
    out.add_argument("--format", choices=["text", "json"], default="text", help="Stdout format")
    out.add_argument("--quiet", "-q", action="store_true", help="No progress or summary")
    out.add_argument("--callback-url", help="POST results JSON here when done")

    gates = run.add_argument_group("quality gates (exit 1 when violated)")
    gates.add_argument("--fail-under", type=float, metavar="RATE", help="Minimum pass rate, 0–1")
    gates.add_argument(
        "--max-error-rate", type=float, metavar="RATE", help="Maximum error rate, 0–1"
    )
    gates.add_argument("--max-p95-ms", type=float, metavar="MS", help="Maximum latency p95 in ms")

    val = sub.add_parser("validate", help="Check agent, dataset or job files without running")
    val.add_argument("--agent", action="append", metavar="PATH")
    val.add_argument("--dataset", action="append", metavar="PATH")
    val.add_argument("--job", action="append", metavar="PATH")

    sch = sub.add_parser("schema", help="Print the JSON Schema for a file type")
    sch.add_argument("name", choices=sorted([*SCHEMAS, "dataset"]))
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_parser().parse_args(argv)
    for flag in ("fail_under", "max_error_rate"):
        value = getattr(args, flag, None)
        if value is not None and not 0 <= value <= 1:
            _err(f"--{flag.replace('_', '-')} must be between 0 and 1 (got {value})")
            raise SystemExit(EXIT_INPUT)
    if args.command == "run":
        code = asyncio.run(_cmd_run(args))
    elif args.command == "validate":
        code = _cmd_validate(args)
    else:
        code = _cmd_schema(args)
    raise SystemExit(code)


if __name__ == "__main__":
    main()
