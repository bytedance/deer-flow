# Private SearXNG search

The official `searxng/searxng:latest` image serves HTML and JSON on port 8080.
The overlay publishes only `${BIND_HOST:-127.0.0.1}:${SEARXNG_PORT:-8088}:8080`,
matching DeerFlow's default SearXNG URL, `http://localhost:8088`.
Brave, Bing, Mojeek, Qwant, Startpage, Wikipedia, and DuckDuckGo are enabled;
a block at one provider can still leave results from the others. Availability
and rate limits depend on the providers and your server's outbound IP.

## Local Gateway

From the repository root:

```sh
export SEARXNG_SECRET="$(openssl rand -hex 32)"
make searxng-up
curl -fsS 'http://127.0.0.1:8088/search?q=test&format=json'
# Keep SEARXNG_SECRET exported for subsequent Compose commands, including stop.
make searxng-down
```

Store the generated secret in your own private environment configuration for
reuse; do not commit it. Compose rejects an unset or empty `SEARXNG_SECRET`.
SearXNG reads this variable as its server secret; no secret is embedded in the
read-only settings file. The limiter is disabled for private use, so no Redis
or limiter configuration is needed. Keep the loopback default unless you have
provided access control for a deliberately shared instance.

Enable the commented SearXNG `web_search` tool in `config.yaml`, replacing any
other `web_search` entry (see `config.example.yaml`):

```yaml
- name: web_search
  group: web
  use: deerflow.community.searxng.tools:web_search_tool
  base_url: http://localhost:8088
```

Restart the Gateway after changing its tool configuration. If you override
`SEARXNG_PORT`, update the local tool's `base_url` accordingly.

## Docker Gateway

Container `localhost` refers to the Gateway itself. Merge this overlay into
the **same Compose project** as the Gateway, then configure the tool with
`base_url: http://searxng:8080`. The service joins both `deer-flow` (production)
and `deer-flow-dev` (development), allowing Docker DNS to resolve `searxng`.
It does not modify the base services. Do not run the standalone Make target
at the same time: both instances would claim host port 8088.

For example, after starting the usual stack, use its project name (shown by
`docker compose ls`) and the same environment used by the stack launcher:

```sh
export SEARXNG_SECRET="$(openssl rand -hex 32)"
export DEER_FLOW_ROOT="$PWD"
export DEER_FLOW_REPO_ROOT="$PWD"
export DEER_FLOW_CONFIG_PATH="${DEER_FLOW_CONFIG_PATH:-$PWD/config.yaml}"
export DEER_FLOW_EXTENSIONS_CONFIG_PATH="${DEER_FLOW_EXTENSIONS_CONFIG_PATH:-$PWD/extensions_config.json}"
export DEER_FLOW_HOME="${DEER_FLOW_HOME:-$PWD/backend/.deer-flow}"
# Replace deer-flow with your existing stack's Compose project name.
docker compose -p deer-flow -f docker/docker-compose.yaml \
  -f docker/docker-compose.searxng.yaml up -d searxng
```

For development, replace `docker/docker-compose.yaml` with
`docker/docker-compose-dev.yaml` and use the development stack's project name.
Use the same two files and project name with `stop searxng` to stop just search;
`down` on a merged project also removes the rest of the stack.
The standalone `make searxng-down` affects only its separate `deer-flow-searxng`
project. A standalone instance's Docker network is not the Gateway's network.

If the Gateway uses HTTP proxies, include `searxng` in both `NO_PROXY` and
`no_proxy` in the environment used to start/recreate the Gateway. Use the
container URL even if you change the published host port; its internal port
remains 8080. The loopback host publication is not a portable route from Linux
containers via `host.docker.internal`.

## Verification

Offline deployment tests:

```sh
cd backend
uv run pytest tests/test_searxng_compose.py tests/test_compose_default_bind_host.py -q
```

With the daemon running, inspect the live result engines:

```sh
curl -fsS 'http://127.0.0.1:8088/search?q=test&format=json' \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(sorted({e for r in d["results"] for e in r.get("engines", [r.get("engine")]) if e}))'
```

The configured engine list is not proof of live results. Check `unresponsive_engines`
in the JSON response when providers fail. The image follows upstream `latest`;
validate a new image before updating a deployment that needs reproducibility.
