# Contributing to Agent Tester

Thanks for helping. This guide covers the local setup, the checks every change
must pass, and how the code is organised.

## Development setup

Requirements: Python 3.10+, Node 20+, Docker (optional, for the full stack).

```bash
make setup   # creates .venv, installs Python + Node dependencies
make dev     # mock agent :9999, API :8000 (auto-reload), UI :3000 (hot reload)
```

Open http://localhost:3000 and click **Run the 30-second demo** to exercise
the whole path.

## Before you open a pull request

```bash
make check   # ruff lint + format check, eslint, tsc, all tests
```

CI runs the same steps on Python 3.10 and 3.12, builds the Docker images and
smoke-tests the stack.

- **Tests are required** for behaviour changes. Runner logic is tested with
  `httpx.MockTransport` (`tester/tests`); API tests run the real app against a
  temporary SQLite database and the in-process mock agent (`controller/backend/tests`).
- **Changed a model in `tester/agent_tester/models.py`?** Run `make schemas`
  and commit the regenerated `shared/schemas/*.json`. A test fails if they drift.
- **Changed the database schema?** New columns must be nullable or have a
  `server_default` so the additive migrator in `controller/backend/app/db.py`
  can upgrade existing databases. Renames and drops need a real migration;
  open an issue first.
- **UI changes:** include a screenshot in the PR, and check both light and dark
  themes and a narrow (mobile) viewport.
- Update `CHANGELOG.md` under *Unreleased*.

## Layout

| Path | What lives there |
| --- | --- |
| `tester/agent_tester/` | The evaluation engine and CLI. Pure library; no database, no web framework. |
| `controller/backend/app/` | FastAPI API, persistence, run orchestration. Imports the engine. |
| `controller/frontend/` | Next.js UI. Talks only to its own `/api/*` proxy. |
| `mocks/` | Mock agents for demos and tests. |
| `presets/`, `datasets/samples/` | Contract templates and sample data shipped in the image. |
| `shared/schemas/` | JSON Schemas generated from the Pydantic models. |
| `docs/` | User documentation. |

## Style

- Python: `ruff` (lint + format), type hints on public functions, docstrings
  that say *why*.
- TypeScript: strict mode, no UI component libraries; shared primitives live
  in `components/ui.tsx` and `components/overlays.tsx`, styles in
  `app/globals.css` tokens.
- Error messages should say what went wrong **and** what to do about it.

## Commit messages

Use the imperative mood ("Add poll retry for 429") and explain the reason in
the body when it isn't obvious.
