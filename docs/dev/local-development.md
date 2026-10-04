# Local development stack

Status: **local development only** (KAN-19, owner LR 10). Nothing here deploys anything. Hosting is undecided and
needs Ojas Sharma's approval; no public deployment, paid resource or account is part of this change.

## What `make dev` runs

| Piece | How | Address (loopback only) | Present today? |
|---|---|---|---|
| PostgreSQL 18 | Docker Compose service `db` ([`infrastructure/docker-compose.yml`](../../infrastructure/docker-compose.yml)) | `127.0.0.1:5432` (`POSTGRES_HOST_PORT`) | yes |
| API (FastAPI) | `python -m uvicorn app.main:app --reload` in `apps/api` | `http://127.0.0.1:8000` (`API_PORT`) | **after LR 04's scaffold PR** |
| Web (Next.js) | `npm run dev -- -H 127.0.0.1 -p 3000` in `apps/web` | `http://127.0.0.1:3000` (`WEB_PORT`) | **after LR 05's PR** |

Until `apps/api` / `apps/web` exist, `make dev` starts the database and prints which part was skipped and why. Those
two commands are conventions inferred from the sprint brief (FastAPI under `apps/api/app/`, Next.js under
`apps/web/`); if the scaffolds differ, set `API_CMD` / `WEB_CMD` in your own `.env` (they run in the app directory)
or change `scripts/dev/dev.sh` in the scaffold PR.

No Redis, broker or observability backend is started: the sprint brief names none (events use a PostgreSQL outbox,
telemetry is JSON on stdout). Add a service to the compose file only with a concrete need.

## First run

```bash
make doctor      # which tools are present (docker compose, python3, node, npm), which scaffolds exist
make dev         # creates .env on first run (random local DB password), starts the DB, then api + web if present
```

Prerequisites: Docker with Compose v2 (daemon running), Python 3.11+ for `apps/api`, Node.js and npm for `apps/web`,
bash and make (Windows: WSL2). `make install` installs app dependencies once the scaffolds exist
(`packages/contract/pyproject.toml` from LR 03, `apps/api/pyproject.toml` with a `dev` extra, `apps/web/package-lock.json`).

## Commands

| Command | Effect |
|---|---|
| `make help` | list targets |
| `make env` | create `.env` from `.env.example` with a random `POSTGRES_PASSWORD` (never overwrites; never prints it) |
| `make db-up` / `make db-down` | start (waits for the healthcheck) / stop the database; data is kept |
| `make db-logs` / `make db-psql` | follow logs / open `psql` inside the container |
| `make db-reset CONFIRM=yes` | **delete** the local database volume `liferescue_pgdata` (refuses without `CONFIRM=yes`) |
| `make dev` | database + apps; Ctrl-C stops the apps, the database keeps running (`make down`) |
| `SKIP_DB=1 make dev` | run apps only, against a PostgreSQL you provide through `DATABASE_URL` |
| `make lint` / `make test` | run linters / tests of the apps that exist (mirrors the proposed CI jobs) |
| `make lint-infra` | shellcheck the dev scripts and validate the compose file (each skipped if the tool is missing) |
| `make compose-config` | `docker compose config` with the placeholder env |

## Configuration and secrets

* `.env.example` is the committed template and contains **placeholders only**. `.env` is gitignored (patterns `.env`
  and `.env.*` with `!.env.example`). Never commit `.env`, never paste its contents into chat, issues or logs.
* `POSTGRES_PASSWORD` in your `.env` is random and local; the database only listens on `127.0.0.1`. If you change
  it after the volume exists, PostgreSQL keeps the old password: run `make db-reset CONFIRM=yes` or change it inside
  the database.
* `DATABASE_URL` is derived from the `POSTGRES_*` values when unset. Set it yourself to choose a driver prefix
  (for example `postgresql+psycopg://...`).
* `NEBIUS_API_KEY` / `TAVILY_API_KEY` are empty in the template. Real keys belong to the credential broker
  (`packages/secrets`, KAN-45); until it is wired, put a key only in your local `.env`. The default
  `MODEL_PROVIDER=mock` needs no key and no network.
* Test database: the first start of an empty volume also creates `POSTGRES_TEST_DB` (default `liferescue_test`) so
  automated tests never touch development data.

## Database roles

The container's `POSTGRES_USER` is the bootstrap **superuser** of this throw-away local database. Application code
should connect with a least-privilege role created by the migrations (SECURITY-REQUIREMENTS A6; LR 04's task), not with
this user, so that the code paths match a later deployment. The default/random password exists only in the local `.env`.

## Safety properties of the compose file

* Image pinned by tag **and** digest (`postgres:18.6-alpine3.24@sha256:...`); upgrade procedure is in the file.
* Port published as `127.0.0.1:<port>:5432` - not reachable from other hosts.
* Named volume `liferescue_pgdata`; for PostgreSQL 18 images it mounts at `/var/lib/postgresql`.
* Healthcheck (`pg_isready`) with start period; `docker compose up --wait` blocks until healthy.
* `POSTGRES_PASSWORD` is required (`${VAR:?}`), so the stack cannot start with an empty password.
* `no-new-privileges`, bounded json-file logs (10 MB x 3).

## Validation status of this change

See `LR10-infra-report.md` in the sprint analysis folder: `docker compose config`, shellcheck, `make -n` and a fake-app
run of `dev.sh` were executed; a real `docker compose up` was **not** (no Docker daemon on the authoring machine), so
container start, the healthcheck and the init script have not been exercised yet. First person with Docker: run
`make db-up && make db-psql` and report.

## Troubleshooting

* *port 5432 already in use*: set `POSTGRES_HOST_PORT=55432` in `.env`.
* *"docker daemon not reachable"*: start Docker Desktop / the docker service.
* *API skipped: uvicorn not importable*: `make install-api` (after the LR 04 scaffold lands).
* *Data directory errors after changing the image major version*: `make db-reset CONFIRM=yes` (development data only).
