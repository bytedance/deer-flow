# Orchestration scripts (`scripts/`)

Scripts behind the root `Makefile`: local start and stop (`serve.sh`), Docker
development (`docker.sh`), production deployment (`deploy.sh`), setup and
diagnosis (`setup_wizard.py`, `doctor.py`, `support_bundle.py`), static analysis
and repository checks. Each script documents its own flags; run it with `--help`
or read its header.

## Verify

```bash
cd backend
python -m pytest tests -q -k "serve or deploy or compose or doctor or dotenv or script or wizard or support_bundle"
```

The shell suites run the real scripts against stub `docker` and `uv` binaries.
Cases marked for real Compose run only when a `docker` CLI is installed.

## Portability

- **Make recipes call `.sh` files through `RUN_SHELL_SCRIPT`**, and a script that
  calls a sibling script prefixes it with `bash`. A source archive,
  `core.fileMode=false` or a non-POSIX filesystem does not keep executable bits.
- **Host pnpm calls go through `scripts/pnpm.py`.** It chooses the launcher by
  Python's `os.name`, not by the invoking shell, so native Windows, MSYS and POSIX
  each get the right one.
- **Shell filters stay compatible with GNU and BSD sed**, because macOS ships
  the BSD tools. `sandbox-mode.sh` uses Bash and awk only.
- **Lookups that run before the environment exists use the standard library
  only.** Config detection, label checks and the dotenv helpers run before
  `uv sync`.
- **Python entry points guard their stream encoding.** Windows consoles and
  redirected CI logs are not UTF-8 by default, and embedded or captured streams
  have no `reconfigure`. Read config and credential JSON with or without a BOM,
  as the runtime loader does.

## Config and dotenv

- **Act on the file the Gateway would load.** `doctor.py` and `config-upgrade.sh`
  ask the harness for the resolved config path. A fixed `config.yaml` path
  diagnoses or upgrades the wrong file when an override is set.
- **Never source a dotenv file.** Parse it and quote path arguments. A dotenv
  value overrides nothing that the shell exported, including an exported empty
  value.
- **`deploy.sh` lets Compose parse `.env`.** Compose accepts forms that a
  `KEY=VALUE` grep misses, so the script asks `docker compose config` what a key
  resolves to. Do not export a value the script read from `.env`: that shadows
  Compose's own parsing, and `make up` then replaces the operator's secret with a
  generated one.
- **Secrets resolve shell, then `.env`, then the persisted file, then a new
  value.** A failing probe stops the script; it does not guess.
- **One dotenv selection per deployment.** `DEER_FLOW_COMPOSE_ENV_FILE` is
  resolved once, and Compose interpolation, service env files, secret probes and
  extras detection all use that path.
- **Do not seed production `.env` from the examples.** `.env.example` holds
  placeholder API keys that the production Gateway would receive. Both compose
  files mark the env files optional so a fresh checkout still starts and stops.
- **Support bundles export no secrets** and show an external runtime home as
  `{DEER_FLOW_HOME}`.
- **Doctor does not echo model credentials.** Obvious sample key values fail the
  model readiness check even when the environment variable is nonempty.

## Start, stop, clean

- **Validate before you stop anything.** `serve.sh` resolves the bind host and
  config first, so a bad value cannot tear down a running stack.
- **`down` skips secret and permission checks.** Permission damage in the runtime
  home must not prevent teardown.
- **`make clean` deletes the runtime home**, which the compose stacks mount. It
  refuses while the Gateway container runs, and it stops sandbox containers
  before the delete because their thread mounts live in that tree.
- **Match container names exactly.** Docker's `name=` filter is a substring match.
  `cleanup-containers.sh` verifies the anchored prefix afterwards, so it cannot
  remove another project's container.
- **Runtime commands use `uv run --no-sync`**, which keeps installed extras such
  as database drivers.
- **Browser sessions need a single Gateway worker process.** They are
  process-local, so launchers keep `WEB_CONCURRENCY` unset or `1`.
- **The multi-instance dev harness keeps IM channels disabled** unless asked.
  Credentials saved through the UI could otherwise connect a real bot later.

## Checks and analysis

- **Skill review waivers take effect from the base revision only.** The head
  manifest is validated but cannot authorize a finding in its own pull request.
  Blockers are never waivable.
- **`detect-blocking-io` is a static approximation.** It resolves calls by name
  inside one file and over-reports on purpose. The strict gate is the runtime
  suite `make test-blocking-io`; `scan_changed_blocking_io.py` limits the static
  findings to a diff.
- **`detect-thread-boundaries --runtime-config` imports configured tools and
  models.** It does not call models or external services.
