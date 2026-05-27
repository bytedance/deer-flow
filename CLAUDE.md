# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

For detailed backend guidance, see [backend/CLAUDE.md](backend/CLAUDE.md).
For detailed frontend guidance, see [frontend/CLAUDE.md](frontend/CLAUDE.md).

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore

## Personal Assistant UX

The system implements a "warm assistant" persona with industrial domain awareness:

**Assistant Persona**: System prompt includes `<assistant_persona>` section with tone grading (Normal/Attention/Warning/Emergency), empathy guidelines, and language-following rules. The persona adapts tone based on severity of findings.

**Greeting API**: `GET /api/threads/{thread_id}/greeting` returns personalized greetings with context-aware suggestions. Features:

- Language detection (zh-CN/en-US) from user's last message
- Alert-aware greetings when active anomalies exist
- Equipment priority sorting (critical > important > general)
- Closure ticket status follow-ups
- Preventive maintenance reminders (14-day window)

**Empathetic Error Handling**: Backend maps exceptions to `ErrorCategory` enum (`network_issue`, `timeout`, `service_unavailable`, `data_not_found`, `permission_denied`, `rate_limited`). Frontend renders expandable error cards with retry buttons for retryable categories.

**Care Loop Follow-up**: After analysis completion, assistant summarizes findings and offers 1-2 next actions. `pendingFollowUp` facts are stored in memory and surfaced in subsequent greetings.

**Assistant Status Indicators**: Status text derives from active tool calls (data tools → "正在查询数据…", report tools → "正在生成报告…", analysis tools → "正在分析…").

**Assistant Avatar**: Message bubbles display agent avatar icon and display name from agent config. Falls back to default BotIcon when no custom icon is set.
