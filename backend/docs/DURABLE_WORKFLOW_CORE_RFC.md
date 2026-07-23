# RFC: Native Durable Workflow Runtime Layer For DeerFlow Core

Status: upstream submission draft
Date: 2026-06-29

This RFC frames the product and runtime direction for a native Durable Workflow
Runtime Layer in DeerFlow core. The implementation can still be reviewed as
separate PR groups, but the design should be evaluated as one coherent runtime
foundation for real-world agent work.

## Summary

DeerFlow should add a native Durable Workflow Runtime Layer in core.

The goal is not to replace LangGraph, and not to turn DeerFlow into a clone of
Temporal, Restate, or Hatchet. The goal is to give DeerFlow a configurable,
native workflow runtime foundation for human-agent collaboration, multi-agent
coordination, observability, recovery, and daily work operations.

## Why DeerFlow Needs This In Core

For agents to be useful in daily work, users need more than a single chat turn
or a single run.

In real work, humans and agents need to understand:

- which work was received;
- which workflow or run is active;
- which work is waiting for human input;
- which work completed;
- which work failed or lost execution after a gateway restart;
- what happened over time;
- how an external request, DeerFlow thread, run, checkpoint, and event timeline
  relate to each other.

Workflow is the shared control surface between humans and agents. Without
durable workflow identity and lifecycle, an agent system easily stays at the
level of personal assistance or one-off automation. It is much harder to use it
as a reliable work system for individuals, small teams, or larger deployments.

## Multi-Agent Work Needs Durable Workflow

DeerFlow already positions itself as a super agent harness with sub-agents,
skills, memory, sandbox execution, channels, and long-running tasks. That makes
durable workflow identity more important, not less.

When users create multiple agents, each agent may have different skills, roles,
tools, and operating characteristics. A lead or coordinator agent needs a
runtime-level way to:

- delegate work to other agents;
- know which agent is handling which part of the work;
- track parallel branches;
- support workflows that loop through several attempts;
- know which step is waiting for a human, another agent, or an external system;
- detect when a delegated agent failed, stopped, or did not return a result;
- retry or resume without losing the whole work context.

Without durable workflow state, the lead agent can get stuck when a child agent
dies or when one branch never completes. It also becomes much harder to improve
individual agents, because operators cannot see where the work got stuck, which
agent owned it, which input caused the failure, or which loop needs redesign.

Durable workflow state gives DeerFlow better operational visibility: where the
work is, who or what is handling it, which step failed, what can be retried, and
which agent needs improvement.

## Current Gap In Agent Systems

Many agent systems focus primarily on personal-assistant use cases. When users
want to apply agents to team work or daily operations, they often need to add an
external workflow engine such as Temporal, Restate, or Hatchet.

Those systems are powerful, especially for large teams and complex production
infrastructure. But for individuals, small teams, and open-source users, making
an external workflow engine mandatory creates a high adoption cost:

- more infrastructure;
- more integration work;
- more operational complexity;
- slower experimentation;
- harder adoption for smaller communities.

DeerFlow can fill this gap with a native Durable Workflow Runtime Layer in core:
close enough to DeerFlow's agent runtime to be useful out of the box, and
generic enough for different deployments to configure and extend.

## Existing DeerFlow Runtime Foundation

DeerFlow already has a strong LangGraph-based runtime foundation:

- LangGraph checkpointer for graph/thread checkpoint state.
- LangGraph store for runtime and cross-thread memory.
- RunManager / RunRepository for run identity, status, cancellation, and
  multitask behavior.
- RunEventStore for ordered run event streams.
- Gateway execution through process-local asyncio tasks and agent streaming.
- Channel adapters for external message sources.

The gap is not LangGraph checkpointing.

LangGraph should continue to own graph execution, checkpoint state, checkpoint
writes, interrupt payloads, graph-local memory, and resume mechanics.

The missing layer is a DeerFlow-owned durable workflow runtime layer so every
external message, API request, dashboard request, or delegated agent task can
have stable identity, idempotency, runtime refs, status, event timeline, and
recovery visibility.

## Proposed Core Layer

Add a native Durable Workflow Runtime Layer in DeerFlow core, configurable and
feature-gated, with these foundation primitives:

- `workflow_id`
- `external_message_ref`
- source/channel metadata
- `thread_id`
- `run_id`
- checkpoint refs
- `idempotency_key`
- workflow status
- append-only workflow events
- created/updated timestamps
- generic metadata

The runtime layer owns:

- durable workflow intake;
- idempotent create-or-get;
- workflow refs bound to existing DeerFlow runs;
- workflow event projection over the existing RunEventStore;
- recovery visibility for orphaned active workflows;
- waiting/resume refs for human-in-the-loop workflows;
- worker lease primitives when deployments need scaled execution, without
  requiring every deployment to run a separate worker service.

The layer can later grow toward:

- multi-agent delegation records;
- branch/child workflow visibility;
- clearer retries, loops, waits, and resume refs;
- worker leasing/concurrency controls;
- richer timelines and operator-facing recovery hints;
- clean integration boundaries so users are not locked out of external workflow
  engines when they need them.

## Value For DeerFlow Users And The Community

A native durable workflow layer helps DeerFlow apply to real work:

- Personal users can manage workflows that last longer than one chat turn.
- Small teams can use DeerFlow immediately without starting with Temporal,
  Restate, or Hatchet.
- Operators can inspect status and history after a gateway restart.
- Integration developers get one intake contract for API, dashboard, and
  channel messages.
- Multi-agent builders get a foundation for lead-agent delegation, branch
  tracking, retry/resume, and failure analysis.
- Maintainers get a clear core abstraction for later modules such as Work Module
  and WorkBoard.
- Enterprise teams can still integrate Temporal, Restate, or Hatchet when they
  need stronger orchestration, because DeerFlow core does not lock users into a
  single execution model.

## Added Value: Work Module And WorkBoard

Work Module and WorkBoard should not be required for the Durable Workflow
Runtime Layer to work. They are added value once DeerFlow has durable workflow
identity, lifecycle, refs, and events.

For individuals or small teams, WorkBoard can provide a simple built-in work
management surface inside DeerFlow. It can act as a lightweight PM tool for
teams that do not already have a dedicated system.

For teams that already use Trello, ClickUp, Jira, Plane, or internal systems,
Work Module can provide shared work primitives and external refs so those teams
can build their own integrations more cleanly.

Durable Workflow Runtime Layer is the foundation. Work Module standardizes work
objects above it. WorkBoard gives users a simple built-in surface to use those
objects immediately.

## LangGraph Boundary

This proposal does not replace LangGraph durability.

LangGraph owns:

- graph execution;
- checkpoint state;
- checkpoint writes;
- interrupt payloads;
- graph-local memory;
- replay/resume mechanics.

DeerFlow Durable Workflow Runtime Layer owns:

- workflow intake identity;
- idempotency;
- source/channel refs;
- deterministic run/checkpoint binding records;
- workflow status projection;
- workflow lifecycle events;
- recovery visibility;
- human-agent and multi-agent observability.

DeerFlow workflow rows store refs to LangGraph state, not checkpoint payloads.

## Relationship To Temporal, Restate, And Hatchet

Temporal, Restate, and Hatchet are useful systems for durable execution,
retries, leases, idempotency, and recovery at larger scale.

DeerFlow core should still have its own native Durable Workflow Runtime Layer so
users can begin using durable agent work without external infrastructure.

This does not block larger teams from integrating Temporal, Restate, or Hatchet
when they need them. DeerFlow only needs clear identity, lifecycle, refs, and
event boundaries so users are not locked into one operational model.

## Non-goals

This RFC does not propose:

- full deterministic replay like Temporal;
- durable handler replay like Restate;
- a DAG builder or visual workflow definition engine;
- a hard dependency on any external workflow engine;
- a hard dependency on Work Module or WorkBoard;
- domain-specific PM semantics;
- AICOS-specific concepts.

## Submission And Review Shape

The implementation should be submitted as a package that shows the complete
runtime value, but reviewed in two clear groups.

For the current open GitHub PRs, the Core Runtime Package maps to:

- **PR 1 / #3813: RFC and runtime contracts.**
- **PR 2 / #3814: Workflow store and lifecycle events.**
- **PR 3 / #3815: Workflow read APIs and timeline projection.**
- **PR 4 / #3816: Existing run wrapper and trace UI.**
- **PR 5 / #3848: Recovery and orphan reconciliation.**

This is the first landing target because normal DeerFlow runs become
inspectable durable workflows without requiring Work Module or WorkBoard. PR
#3814 intentionally keeps store and events together for the current submission
so the package is not split into tiny, low-context fragments. If maintainers
prefer a finer split, #3814 can be split into separate store and event PRs
before final review.

PR 6-10 form the Hardening/Scale Package: deterministic binding,
channel/dashboard intake adoption, waiting/resume refs, and worker-readiness.
The current open branches cover those areas; exact numbering can be adjusted if
maintainers ask to split one hardening item further.

Code should remain split into small, reviewable PRs. The submit narrative should
not be split into tiny unrelated fragments: maintainers need to see the
end-to-end durable core value and the explicit boundary around what the core is
not trying to become.
