<!-- Authored by @ggnnggez, opened for feedback as
     https://github.com/bytedance/deer-flow/issues/4573. -->

# RFC: An Extension System for Cross-Cutting Concerns

**Status:** Draft for feedback ([#4573](https://github.com/bytedance/deer-flow/issues/4573)).
**Affects:** `backend/packages/extension-api/` (new package), `backend/packages/harness/deerflow/extensions/` (new), plus small hook-site additions in the lead/subagent builders, the run worker, the subagent executor, and the Gateway app/lifespan. `config.example.yaml` gains one top-level key.

## TL;DR

DeerFlow's middleware chain is where every cross-cutting concern lands. A default
local lead-agent build assembles **24 middlewares** today, and the documented chain
enumerates **35 positions** once optional ones are counted. Every new concern — token
accounting, audit, progress guards, policy hooks — is one more entry in a chain that
every user pays for, and whose ordering everyone must reason about together.

Meanwhile, a downstream user who wants to add their *own* cross-cutting behaviour has
no seam to add it at. They fork, and they edit the files DeerFlow changes most often.

This RFC proposes an **extension system**: a small public contract package that a
third party depends on, a `plugins:` list that loads their package at startup, and a
fixed set of contribution points they can attach to — without touching core code, and
without appearing anywhere in this repository.

The goal is not to add features. It is to **stop the chain from growing** for concerns
that only some users want, and to make community secondary development a supported
path rather than a fork.

## 1. Why now: two problems that share one cause

### 1.1 The middleware chain absorbs everything

Read the chain in [backend/AGENTS.md](../../backend/AGENTS.md#middleware-chain). It is a
carefully ordered list, and the care is real — several entries carry comments explaining
that they must sit immediately before or after a specific sibling, and the ordering is
pinned by tests.

That design is correct for the concerns that belong to DeerFlow itself. The problem is
that it is also the only available answer for concerns that *don't*:

- Ordering is global. Adding one entry means re-reasoning about a 24-to-35 item chain.
- Cost is global. A middleware that only one deployment needs is still constructed and
  still runs a hook for everyone.
- The list is a shared review surface. Every optional concern competes for space in the
  same file, and every reviewer has to hold the whole ordering in their head.

There is a real, healthy pressure to say "no" to niche middleware. But saying no leaves
the requester with only one option, which is the second problem.

### 1.2 Secondary development means forking the hottest files

Today, wiring a cross-cutting concern into DeerFlow touches the agent builders, the run
worker, the subagent executor, and the Gateway lifespan. Those are precisely the files
with the highest upstream change rate.

The consequence is not "some merge conflicts". It is that a downstream fork's
maintenance cost is **proportional to upstream's velocity**, in exactly the areas where
upstream is most active. Every rebase re-litigates the same insertion points. In
practice this pushes serious downstream users toward stale forks — which is bad for
them, and bad for us, because their fixes and their field experience never come back.

### 1.3 What exists already, and why it is not enough

`extensions.middlewares` in `extensions_config.json` / `config.yaml` already loads
middleware classes by path. It is genuine prior art and this RFC does not remove it.
Its documented limits are the shape of the gap:

- Zero-argument `AgentMiddleware` classes only — no configuration reaches them.
- One fixed insertion point, near the end of the chain. A concern that must observe the
  *final* model request, or the *raw* tool return, cannot express that.
- No lead-only vs subagent-only distinction.
- Middleware only. Nothing for run lifecycle, out-of-graph model calls, HTTP routes, or
  anything needing startup and shutdown.

So the mechanism covers "I have a simple middleware and I don't mind where it goes". The
requests that keep arriving are mostly the other kind.

## 2. What this proposes

Four ideas, none of them large on their own.

**A separate contract package.** `deerflow-extension-api` (import:
`deerflow_extension_api`) holds everything an extension needs, and **must never import
`deerflow`**. That single rule is what lets an extension be released independently on
its own cadence: it depends on the contract, not on the harness. A test enforces the
rule in CI.

**Explicit loading, operator-owned.** A top-level `plugins:` list in `config.yaml` names
entry points as `module.path:install`. An installed package does nothing until it is
listed. The list lives in `config.yaml` rather than the API-writable
`extensions_config.json` on purpose: a list that causes code to be imported must not be
reachable from an HTTP endpoint.

**Contribution points instead of edits.** A fixed, reviewed set of places an extension
may attach — §3. Adding a contribution point is a deliberate act with a review; using
one is not.

**Semantic placement instead of indexes.** A middleware declares *what it needs to
observe*, not *where to sit* — §4. This is what keeps the chain free to be
restructured without breaking released extensions.

### 2.1 Two phases, so registration cannot have side effects

Loading is split in two:

1. **Registration.** The host calls `install(registry, config)`. The `registry` is
   write-only — it hands out no host capabilities at all. An extension therefore
   *structurally* cannot touch the runtime during registration; there is nothing to
   touch.
2. **Runtime.** Later, the host hands real dependencies to whatever registered as a
   service, through a narrow `ExtensionRuntimeDeps` object.

The reason for the split is reviewability: "what can an extension do at import time?"
has a one-word answer — nothing — instead of an audit.

Notably, extensions never see `AppConfig`. They get a narrow projection of the limits
the host actually enforces. Exposing `AppConfig` would pin every extension to the
harness release cadence, which would defeat the point of the separate package.

### 2.2 Failure isolation

Contributed middlewares are wrapped so that an extension's own failure degrades to a
diagnostic and the call proceeds. The wrapper never masks a failure of the underlying
model or tool call, and never replays one — a third-party observer must not be able to
cause a second provider call or a duplicated tool side effect. LangGraph's
interrupt/resume control-flow signal is always re-raised unchanged.

Diagnostics are attributed: every registration carries the entry-point string that
produced it, so a conflict or a failure names the responsible package.

## 3. The contribution points

Five, grouped by what they are for. Three are behaviour protocols; two are values the
host takes ownership of.

### Contributors — participate in the agent

| Point | Protocol | What it can do |
| --- | --- | --- |
| Middlewares | `MiddlewareContributor` | Return middlewares plus their placement, per agent build |
| Task lifecycle | `TaskLifecycleContributor` | Observe an agent execution starting and stopping |

`TaskLifecycleContributor` deserves a note: **lead runs and subagent runs are the same
type of event.** They share one `TaskInfo`, distinguished by a `kind` field, so an
extension writes one code path for both. The outcome is keyed on *success* — only an
explicitly successful run reports completed, so an unanticipated terminal state degrades
to failed rather than being reported as a clean finish.

### Observers — see what middleware cannot

| Point | Protocol | What it can do |
| --- | --- | --- |
| System model calls | `SystemModelCallObserver` | Observe model calls made *outside* the agent graph |

This one exists because a meaningful share of DeerFlow's model traffic never passes
through the middleware chain. Title generation, memory extraction, goal evaluation, and
summarization all call a model outside the graph. An observability extension that only
saw the chain would silently miss them.

The observer is notified on **both** the success and the failure path. A system call
that failed is precisely the event worth seeing, so notifying only on success would
hide the interesting half.

### Host-owned values

| Point | Type | What it can do |
| --- | --- | --- |
| Routers | `APIRouter` values | Contribute HTTP endpoints |
| Services | `ExtensionService` | Own resources across the Gateway's lifetime |

Routers are constructed **eagerly**, during registration, so the Gateway can detect path
conflicts and freeze its OpenAPI surface before it serves. Contributed routers mount
after every host router and cannot take a path the Gateway already serves; a conflict is
reported and the router is refused rather than silently shadowed.

Since registration has no capabilities, a routed extension registers the same object as
a service, binds its dependencies when the service starts, and resolves them per request
through FastAPI's `Depends`. Until they are bound — and after shutdown clears them — its
routes report unavailable rather than answering with half-built state.

Services start and stop in the Gateway lifespan. Stop is reverse-order, bounded, and
fail-open: a Gateway that cannot shut down is worse than a lost observation.

## 4. Placement: declare the guarantee, not the index

A middleware occupies one index in a list, but that index only means something on the
hook chain it actually implements — so "outermost" means different things on the model
axis and the tool axis. Asking extensions for an index would leak the chain's current
shape into every released extension.

Instead a contribution declares one of five placements:

| Placement | The guarantee it asks for |
| --- | --- |
| `MODEL_LOGICAL` | Outer of retry and error handling — fires once per logical decision |
| `MODEL_PHYSICAL` | Inner of every request transform — fires once per real provider call |
| `TOOL_VISIBLE` | Outer of truncation and sanitization — sees what the model finally reads |
| `TOOL_RAW` | Adjacent to the callable boundary — sees the tool's own return |
| `STANDARD` | No before/after requirement |

The mapping from placement to a real position lives in a host-owned anchor table, so
restructuring the chain is a change to one table rather than a break for every extension.

Because a guarantee is a claim about behaviour, it is tested as one: the placement tests
assert each promise against the **real** lead and subagent chains. Nothing else can catch
the failure mode — appending a new request-transforming middleware inner of an anchor
leaves the types, the anchor table, and the version constraints all valid while the
promise silently stops holding.

## 5. Core flow, end to end

```
config.yaml: plugins: [ {use: "pkg:install", config: {...}} ]
        │
        ▼
  load_extensions()            once, at startup, in config order
        │                      resolve entry point → call install(registry, config)
        ▼
  install(registry, config)    registration phase: write-only, no capabilities
        │                      registry.middlewares/task_lifecycle/
        │                      system_model_observer/routers/service
        ▼
  LoadedExtensions             immutable; every entry carries its source string
        │
        ├──► agent build ──► placement resolved against the real chain,
        │                    each contribution wrapped for isolation
        ├──► run / subagent ──► task start … task stop
        ├──► out-of-graph model calls ──► observers notified (success and failure)
        └──► Gateway ──► routers mounted after host routes;
                         services start in lifespan, stop in reverse
```

Load order is the config list order — explicit and reproducible, which matters because
placement ties can only be broken deterministically if load order is.

Failure policy is **fail-open by default**: a broken extension is skipped with a
diagnostic and the Gateway still starts. An operator can set `required: true` per entry
to make a load failure a startup failure instead — for packages whose absence changes
behaviour rather than only observability.

## 6. What this is not

- **Not a plugin marketplace.** No discovery, no auto-loading, no sandboxing. An
  extension is trusted operator-installed code, exactly like a configured middleware
  class today.
- **Not a replacement for `extensions.middlewares`.** That mechanism keeps working,
  untouched.
- **Not a stable 1.0 contract yet.** The current surface is deliberately
  observational — contributors and observers. The version is `0.1` and the compatibility
  window says so: pre-1.0, minors may break.
- **Not a place for decision-making hooks, yet.** Everything here observes. A
  contribution that could *deny* or *alter* a decision needs a fail-**closed** policy
  and its own review; the isolation wrapper's fail-open behaviour is correct only for
  observation. Authorization and guardrails already own that space through their own
  provider protocols.

## 7. Cost to this repository

Worth stating plainly, since the motivation is partly "stop paying for optional things":

- One new package (contract only, no logic) and one new module directory (the host side).
- Small additions at the hook sites: a task-lifecycle notification around lead and
  subagent runs, an observation wrapper at four out-of-graph model call sites, and the
  extension load plus router/service wiring in the Gateway.
- Zero-extension cost is a design constraint, not an aspiration: every hook site
  short-circuits on a precomputed flag before constructing any payload, so a deployment
  with no `plugins:` allocates nothing and the chain is unchanged.

In exchange, the next "can we add a middleware for X?" has a second possible answer.

## 8. Open questions for reviewers

1. **Are five contribution points the right five?** They cover the requests we have
   seen. The obvious candidates for a sixth are frontend surface and persistence —
   both deliberately out of scope here.
2. **Is fail-open the right default?** It favours availability over completeness of
   observation. `required: true` exists as the per-entry escape hatch, but the default
   is a judgment call worth challenging.
3. **How stable should `0.1` feel?** The contract is designed so that growth is additive
   (every protocol method has a default, every optional field has a default). The
   question is when to commit to `1.0`.
4. **Should placement be extensible?** Today the anchor table is host-owned and the five
   placements are fixed. That is deliberate — a placement is a promise the host has to
   keep — but it does mean a genuinely new observation point requires an upstream change.
