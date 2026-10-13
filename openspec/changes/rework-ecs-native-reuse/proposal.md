# Rework ECS execution around native DeerFlow

## Why
User requires all B/C/combined features and approved native-first reimplementation. Previous Fleet duplicated or overextended native mechanisms.

## What Changes
- B uses native ordinary MCP task tracking and notifications with a standalone execution backend.
- C uses native Gateway runtime, persistence, events and ownership, with fixed-pool scheduling/outbound transport adapters.
- Dependencies augment native goals and notification admission; cancel/STOP/resource invariants remain.
- Preserve old branch and unrelated fork changes; cloud deployment stays suspended.

## Capabilities
### New Capabilities
- native-execution-reuse: trusted native MCP scope, B/C execution adapters and same-goal dependency continuation.

## Impact
Isolated codex/ecs-native-reuse branch. Phased plan in docs/superpowers/plans/2026-10-08-ecs-native-reuse-implementation.md. Default native path stays functional; no deployment in current phase.
