# Skill usage in answer details

The answer toolbar shows skills that the lead agent actually loaded during that
answer's run. A skill catalog entry, a mention in answer text, a failed read, or
a client-supplied claim does not count as usage. Shell reads and subagent loads
are outside this evidence path. Messages without captured usage omit the entry.

## Capture and history

`skill_usage.py` makes display-only snapshots after successful configured skill
reads and explicit slash activation. The read boundary discards tool-supplied
skill metadata and stamps only successful messages from the configured read
tool and requested `SKILL.md` path, including matching ToolMessages inside a
`Command`. The output-budget middleware checks that producer and path again,
then updates and registers the snapshot after any externalization or truncation,
so the bounded display snapshot and its hash describe the final model-visible
output. Slash activation stamps the first AI response that received it.
Each snapshot carries the canonical path, category, name, description, loaded
content, SHA-256, activation mode, and a partial flag for range or truncated
reads. Content is bounded to 100,000 characters. The snapshot never authorizes
a tool or secret, and Gateway strips it from external messages.

Both producers register with `runtime.context["__run_journal"]`. A tool-end
callback can serialize output before middleware adds metadata, so the journal
keeps the first snapshot per path in load order (up to 64 skills) and copies the
cumulative list to `additional_kwargs.skill_usages` on canonical lead AI answers
without tool calls. This survives pagination and checkpoint compaction of
earlier load messages. Native subagents do not receive the lead journal. Provider
messages are unchanged; replay does not replace the original snapshot list;
closing the journal releases it. The existing message run ID owns run scope,
and serialization/history must preserve the display kwargs.

## Presentation

`core/skills/usage.ts` groups server-owned snapshots by run, deduplicating by
path in first-load order. The terminal `skill_usages` aggregate takes precedence
over singular snapshots. The menu anchors on the run's last assistant bubble;
when live run IDs are absent, visible human and clarification-result boundaries
separate runs, including continuations whose human replies are hidden.

Answer details use the generic `workspace/message-details` menu, provider, and
panel. Add later detail types with a descriptor (`id`, `title`, `content`,
optional `actions`) instead of a separate drawer. `ChatBox` renders the detail
inside its resizable desktop group or mobile sheet, closing other panels on
selection. Heavy content loads on interaction. Hover opens the Skills menu;
selecting a name focuses the captured `SKILL.md` heading, and explicit close
restores focus to its trigger. A partial snapshot shows a notice. Copy returns
the original Markdown, including frontmatter. Package-relative links and images
stay inert because the snapshot has no trustworthy live package destination.
