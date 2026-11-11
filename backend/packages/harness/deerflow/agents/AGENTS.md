# Agents (`deerflow/agents/`)

The lead agent factory, its system prompt, the thread state and its reducers.
Scoped guides: [middlewares](middlewares/AGENTS.md), [memory](memory/AGENTS.md),
[task continuity](task_continuity/AGENTS.md). Runtime options and state fields
are in `lead_agent/agent.py` and `thread_state.py`.

## Verify

```bash
cd backend
python -m pytest tests -q -k "lead_agent or thread_state or assembly or prompt"
```

## Lead agent

- **`make_lead_agent(config)` is the published `langgraph.json` entry point.**
  Keep its signature and its bare-graph return type. The Gateway calls
  `assemble_lead_agent`, which also returns the descriptor and the effective
  model.
- **A consumer unwraps through `runtime/runs/worker.py::_agent_graph`**, because
  a third-party factory can return a bare graph.
- **The graph and the assembly descriptor receive the same rendered prompt and
  the same middleware objects.** Observers then describe the graph that runs.
- **Skill `allowed_tools` in the descriptor is exported metadata.** It never
  filters tools. Omitted, declared empty and non-empty are three states.
- **A custom graph integration supplies the runtime `run_id`.** Without it, the
  delegation cap counts the thread's whole ledger and logs a warning.
- **One `SubagentRuntime` is shared per capacity boundary** when you build the
  graph directly with `create_deerflow_agent`.

## Prompt trust

- **Framework authority uses the system channel. Text that a user or a model can
  influence goes into the sanitized `HumanMessage` data channel.** Do not
  interpolate an untrusted value into system text; escaping tags does not
  neutralize an instruction written in natural language.
- **The locale preference is request-only human data.** The static system prompt
  stays independent of it, and an explicit language request from the user wins.
- **`lead_prompt_overlay` is literal operator text.** Do not template-format it or
  source it from the run context.

## Thread state

- **`merge_message_writes` keeps the public `add_messages` behavior in full.**
  LangGraph's private delta reducer omits part of it and cannot replace it. The
  differential tests cover the parity.
- **Reducers encode rules that a plain overwrite breaks**: the active goal
  survives ordinary updates, and a terminal delegation status is never
  downgraded. Read the reducer before you write its field.

## Import hygiene

- **The package roots of `deerflow.agents` and `deerflow.subagents` load the graph
  and the executor lazily.** A module that needs only a type, a config or a
  registry imports the concrete submodule. An eager import at the package root
  pulls the tool graph into every state and schema import.
- **`deerflow.agents:make_lead_agent` is a real module-level function**, because
  LangGraph Server resolves factories from the module dictionary. Its heavy
  imports stay inside the function.
