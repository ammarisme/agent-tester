# Deployment

The controller is one container that runs the API (FastAPI, port 8000) and the web UI (Next.js, port 3000). The UI talks to the API through a same-origin proxy at `/api`. State lives in one SQLite file.

## Docker Compose

```bash
cp .env.example .env
docker compose up --build
```

The default Compose file runs:

| Service | Purpose | Port (host) |
| --- | --- | --- |
| `controller` | UI and API. Runs evaluations in-process. | `UI_PORT` (UI, default 3000) and `API_PORT` (API, default 8000) |
| `mock-agent` | Mock HTTP agents for the demo and smoke tests. | `MOCK_PORT` (default 9999) |

The default setup uses the in-process runner: it needs no Docker socket and no `HOST_PROJECT_DIR`. The controller runs as a non-root user (uid 10001), stores its database in the named volume `agent-tester-data` mounted at `/data`, and maps `host.docker.internal` to the Docker host so contracts can reach services running there. The Compose file also defines a `tester` service (profile `cli`) for one-off [CLI](cli.md) runs.

To run each evaluation in its own container instead, add the overlay file and give it the absolute path of the project directory:

```bash
HOST_PROJECT_DIR=$PWD docker compose \
  -f docker-compose.yml -f docker-compose.docker-runner.yml up --build
```

See [Runner modes](#runner-modes).

Environment variables for the controller go in `.env`. This includes the secrets your contracts reference, such as `AGENT_API_KEY`, because the in-process runner resolves `${VAR}` from the controller's environment.

## Controller environment variables

All settings are read from the environment (names are case-insensitive) and from a `.env` file in the controller's working directory. Code defaults for paths are relative to the repository root (`<repo>`) when running from source. The controller image overrides some of them; those values are listed as image defaults.

### Storage

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_PATH` | `<repo>/data/agent_tester.db`; image: `/data/agent_tester.db` | SQLite database file. The parent directory is created if missing. |
| `DATABASE_URL` | unset | A SQLAlchemy async database URL. Overrides `DATABASE_PATH`. Only SQLite is tested; see [Persistence](#persistence). Contracts can never read this variable. |

### HTTP

| Variable | Default | Purpose |
| --- | --- | --- |
| `API_TOKEN` | unset | When set, every `/api` route except `/api/health` requires `Authorization: Bearer <token>`. Contracts can never read this variable. |
| `CORS_ORIGINS` | empty | Comma-separated origins allowed to call the API from a browser. The bundled UI uses its same-origin proxy and does not need this; set it only for other browser clients. |
| `MAX_UPLOAD_MB` | `20` | Maximum dataset upload size. Larger uploads get HTTP 413. |

### Execution

| Variable | Default | Purpose |
| --- | --- | --- |
| `RUNNER_MODE` | `inprocess` | `inprocess` or `docker`. See [Runner modes](#runner-modes). |
| `MAX_CONCURRENT_RUNS` | `2` | Runs executing at once (minimum 1). Further runs wait as `queued`. |
| `TEST_REQUEST_TIMEOUT_S` | `30` | Time limit for the agent editor's **Test request** (`POST /api/agents/test`). Full runs use each contract's own timeouts. |
| `ALLOW_LITERAL_SECRETS` | `false` | When `true`, agents may be saved with literal credential values in headers. See [Security](security.md#literal-credential-rejection). |
| `AGENT_TESTER_SECRET_PATTERN` | unset | Read by the engine, not the controller settings. A regular expression; if set, contracts may only read environment variables whose full name matches. Strongly recommended for shared deployments. |

### Bundled content

| Variable | Default | Purpose |
| --- | --- | --- |
| `PRESETS_DIR` | `<repo>/presets`; image: `/app/presets` | Directory of `*.json` contract templates shown under **New agent**. Invalid files are skipped with a warning. |
| `SAMPLES_DIR` | `<repo>/datasets/samples`; image: `/app/datasets/samples` | Directory containing `smoke.jsonl`, used by the demo. |
| `DEMO_AGENT_URL` | unset | Base URL for the demo agents. When set, it replaces `base_url` in the demo presets when **Run the 30-second demo** creates them. The presets default to `http://mock-agent:9999`. |

### Docker runner only

| Variable | Default | Purpose |
| --- | --- | --- |
| `HOST_PROJECT_DIR` | empty | Absolute path of the project directory **on the Docker host**. Required in docker mode; the overlay refuses to start without it. |
| `COMPOSE_PROJECT_DIR` | `/workspace` | Where the project directory is mounted inside the controller container. |
| `JOBS_DIR` | `<repo>/data/jobs`; image: `/data/jobs`; docker overlay: `/workspace/data/jobs` | Where job files are written for tester containers. Must be inside `COMPOSE_PROJECT_DIR` so the host path can be derived and mounted. |
| `COMPOSE_FILE` | `docker-compose.yml` | Compose file, relative to `HOST_PROJECT_DIR`, that defines the tester service. Only this one file is passed to `docker compose run`. |
| `TESTER_SERVICE` | `tester` | Name of the tester service in that Compose file. |
| `PUBLIC_API_BASE` | `http://controller:8000` | Base URL at which tester containers reach the controller API to post results. |

### Logging

| Variable | Default | Purpose |
| --- | --- | --- |
| `LOG_LEVEL` | `INFO` | Python log level for the controller. |

## UI proxy

The UI's `/api/*` route forwards every request to the API. It reads its configuration at request time, so one image works in any deployment.

| Variable | Default | Purpose |
| --- | --- | --- |
| `API_INTERNAL_URL` | `http://127.0.0.1:8000` (also set in the image) | Where the proxy sends API requests. |
| `API_TOKEN` | unset | If set, the proxy adds `Authorization: Bearer <API_TOKEN>` to requests that do not already carry an `Authorization` header. |

In the standard container the UI and API share an environment, so setting `API_TOKEN` once configures both.

Because the proxy attaches the token, **anyone who can reach the UI can use the whole API**. The token protects the API port, not the UI. See [Running behind SSO](#running-behind-sso).

If the proxy cannot reach the API it returns HTTP 502 with `The UI cannot reach the controller API at <url>. Check that it is running.`, and the UI shows **API unreachable**.

## Runner modes

| | In-process (`RUNNER_MODE=inprocess`, default) | Docker (`RUNNER_MODE=docker`) |
| --- | --- | --- |
| Where evaluations run | Inside the controller process, as background tasks | In a new tester container per run, started with `docker compose run --rm` |
| Live progress and partial results | Yes: results are written in batches about every 0.5 s | No: results arrive when the tester finishes |
| Secrets come from | The controller's environment | The tester container's environment |
| Docker socket | Not needed | Must be mounted into the controller |
| `HOST_PROJECT_DIR` | Not needed | Required |
| Isolation | Agent traffic, templating and response parsing share the controller process | Each run is isolated in a throwaway container |
| Cancel | Stops the run; results so far are kept and summarized | Terminates the tester process; the run is marked cancelled |

Use the in-process runner unless you need evaluations isolated from the controller. Be aware that mounting the Docker socket gives the controller control of the Docker host.

How the Docker runner works:

1. The controller writes the job to `JOBS_DIR/<run id>.json`.
2. It runs `docker compose -f <HOST_PROJECT_DIR>/<COMPOSE_FILE> --project-directory <HOST_PROJECT_DIR> run --rm -v <job file on host>:/job.json:ro <TESTER_SERVICE> run --job /job.json --quiet`.
3. The tester posts results to `<PUBLIC_API_BASE>/api/runs/<run id>/results`. When `API_TOKEN` is set, the controller passes it to the tester as `AGENT_TESTER_CALLBACK_TOKEN`.
4. If the tester exits without posting results, the run is marked `failed` with the exit code and the last line of its stderr.

What the overlay changes for the controller: it builds the image with `WITH_DOCKER_CLI=true` (the Docker CLI and Compose plugin are not in the default image), runs the container as root because the Docker socket is root-owned, mounts `/var/run/docker.sock`, mounts the project read-only at `/workspace` and `./data/jobs` at `/workspace/data/jobs`, and sets `RUNNER_MODE=docker`, `HOST_PROJECT_DIR`, `COMPOSE_PROJECT_DIR`, `JOBS_DIR` and `PUBLIC_API_BASE`. The tester containers read `.env` through the `tester` service's `env_file`, so contract secrets in `.env` reach them.

## Persistence

All state (agents, datasets, runs and results with trajectories) is in one SQLite database at `DATABASE_PATH`. Mount its directory as a volume.

- **WAL mode.** The database uses write-ahead logging (`journal_mode=WAL`) so the UI can read while a run writes, with a 5-second busy timeout and foreign keys enabled. Next to the database you will see `-wal` and `-shm` files; they are part of the database.
- **Backups.** Use SQLite's online backup API, which is consistent while the controller runs. With the default Compose setup (the image has Python but not the `sqlite3` CLI):

  ```bash
  docker compose exec controller python -c \
    "import sqlite3; s = sqlite3.connect('/data/agent_tester.db'); d = sqlite3.connect('/data/backup.db'); s.backup(d); d.close()"
  docker compose cp controller:/data/backup.db "./agent-tester-$(date +%F).db"
  ```

  Outside Docker, `sqlite3 data/agent_tester.db ".backup 'backup.db'"` does the same. Alternatively stop the controller and copy the database file together with its `-wal` and `-shm` files. Copying only the main file of a running database can lose recent writes.
- **Migrations.** On startup the controller creates missing tables and adds missing columns (`ALTER TABLE ... ADD COLUMN`). Upgrades that only add columns need no action. There is no mechanism for renaming or dropping columns, and no downgrade; back up before upgrading.
- **Other databases.** `DATABASE_URL` accepts any SQLAlchemy async URL, but only SQLite is tested, and a driver for another database is not installed by default. The WAL settings apply only to SQLite.
- **Size.** Trajectories include response bodies, truncated to `body_truncate_chars` (default 32000 characters) per response. Lower it in run options if the database grows too fast, and delete old runs you no longer need.

## Scaling

- **Runs.** `MAX_CONCURRENT_RUNS` (default 2) runs execute at once; the rest wait as `queued` in submission order.
- **Requests.** Each run's `concurrency` option (default 8, up to 256) limits requests in flight across all agents in that run. The controller can therefore have up to `MAX_CONCURRENT_RUNS × concurrency` requests in flight. Size this for the agents under test as well as the controller: too much concurrency shows up as `agent_error` (429, 503) or `timeout` results.
- **One instance.** Run a single controller instance per database. Run queueing and cancellation are held in memory, and on startup the controller marks every `queued` or `running` run in the database as failed. A second instance sharing the database would fail the first one's runs.
- **Restarts.** A run that is queued or running when the controller stops is marked `failed` on the next start with `The controller restarted before this run finished. Re-run it.` Use **Re-run** (`POST /api/runs/{id}/rerun`).
- **Large or many evaluations in CI** are better run with the [CLI](cli.md), which needs no controller.

## Running behind SSO

The controller has no user accounts. For a shared deployment:

1. Set `API_TOKEN` to a long random value.
2. Put the UI (port 3000) behind your SSO reverse proxy (for example oauth2-proxy, or your ingress controller's authentication). Because the UI proxy injects the token, the UI must never be reachable without SSO.
3. Do not expose the API port (8000) publicly. If automation needs it, expose it only on an internal network; it is protected by the token.
4. If your SSO proxy forwards its own `Authorization` header upstream, the UI proxy will pass that header through instead of adding the token, and the API returns 401. Configure the SSO proxy not to forward `Authorization` to the UI.
5. Set `AGENT_TESTER_SECRET_PATTERN` so that contracts can read only the variables intended for them.

The UI sets `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff` and `Referrer-Policy: same-origin`.

See [Security](security.md) for the full threat model.

## Health check

`GET /api/health` returns `{"status": "ok", "version": "..."}` after running a query against the database. It never requires the token. Use it through the UI (`http://<host>:3000/api/health`, which also checks the proxy) or directly on port 8000.

The controller image already declares a Docker `HEALTHCHECK` against `http://127.0.0.1:8000/api/health` (every 15 seconds). For Kubernetes or a load balancer, probe the same path. The container exits if either the API or the UI process dies, so the orchestrator can restart it.
