---
name: bootstrap
description: >-
  Generate a personalized SOUL.md through a warm, adaptive onboarding conversation.
  Trigger when the user wants to create, set up, or initialize their AI partner's
  identity — e.g., "create my SOUL.md", "bootstrap my agent", "set up my AI
  partner", "define who you are", "let's do onboarding", "personalize this AI",
  "make you mine", or when a SOUL.md is missing. Also trigger for updates:
  "update my SOUL.md", "change my AI's personality", "tweak the soul".
---

# Bootstrap Soul

A conversational onboarding skill. Use the information already supplied and ask only useful follow-ups to understand the user and what they need, then generate a tight `SOUL.md` that defines their AI partner.

## Architecture

```
bootstrap/
├── SKILL.md                          ← You are here. Core logic and flow.
├── templates/SOUL.template.md        ← Output template. Read before generating.
└── references/conversation-guide.md  ← Detailed conversation strategies. Read at start.
```

**Before your first response**, read both:
1. `references/conversation-guide.md` — how to run each phase
2. `templates/SOUL.template.md` — what you're building toward

## Ground Rules

- **One phase at a time.** 1–3 questions max per round. Never dump everything upfront.
- **Converse, don't interrogate.** React genuinely — surprise, humor, curiosity, gentle pushback. Mirror their energy and vocabulary.
- **Progressive warmth.** Each round should feel more informed than the last. By Phase 3, the user should feel understood.
- **Adapt pacing.** Terse user → probe with warmth. Verbose user → acknowledge, distill, advance.
- **Never expose the template.** The user is having a conversation, not filling out a form.

## Conversation Phases

The conversation has 4 phases. Each phase may span 1–3 rounds depending on how much the user shares. Skip or merge phases if the user volunteers information early.

| Phase | Goal | Key Extractions |
|-------|------|-----------------|
| **1. Hello** | Language + first impression | Preferred language |
| **2. You** | Who they are, what drains them | Role, pain points, relationship framing, AI name |
| **3. Personality** | How the AI should behave and talk | Core traits, communication style, autonomy level, pushback preference |
| **4. Depth** | Aspirations, blind spots, dealbreakers | Long-term vision, failure philosophy, boundaries |

Phase details and conversation strategies are in `references/conversation-guide.md`.

## Extraction Tracker

Use these fields as optional discovery prompts. Include only information the user supplies or confirms; an update may need only one field. Do not require personal details unrelated to the requested customization.

| Field | Include when supported | Source Phase |
|-------|------------------------|-------------|
| Preferred language | ✅ | 1 |
| User's name | ✅ | 2 |
| User's role / context | ✅ | 2 |
| AI name | ✅ | 2 |
| Relationship framing | ✅ | 2 |
| Core traits (supported behavioral rules) | ✅ | 3 |
| Communication style | ✅ | 3 |
| Pushback / honesty preference | ✅ | 3 |
| Autonomy level | ✅ | 3 |
| Failure philosophy | ✅ | 4 |
| Long-term vision | nice-to-have | 4 |
| Blind spots / boundaries | nice-to-have | 4 |

Generate when there is enough information for the requested customization. Skip answered questions, respect the user's desired pace, and leave unknown preferences unspecified instead of inventing them.

## Generation

Once you have enough information:

1. Read `templates/SOUL.template.md` if you haven't already.
2. Adapt the SOUL.md template to the supported preferences and requested scope.
3. Present it warmly and ask for confirmation. Frame it as "here's [Name] on paper — does this feel right?"
4. Iterate until the user confirms.
5. Call the `setup_agent` tool with the confirmed SOUL.md content and a one-line description:
   ```
   setup_agent(soul="<full SOUL.md content>", description="<one-line description>")
   ```
   The tool will persist the SOUL.md and finalize the agent setup automatically.
6. After the tool returns successfully, confirm: "✅ [Name] is officially real."

**Generation rules:**
- Write the final SOUL.md in the user's requested language, otherwise use the established conversation language.
- Every sentence must trace back to something the user said or clearly implied. No generic filler.
- Core Traits are **behavioral rules**, not adjectives. Write "argue position, push back, speak truth not comfort" — not "honest and brave."
- Voice must match the user. Blunt user → blunt SOUL.md. Expressive user → let it breathe.
- Total SOUL.md should be under 300 words. Density over length.
- Include growth or personalization preferences only when supported by the user. They do not grant permission for personal questions or external actions.
- You **must** call `setup_agent` — do not write the file manually with bash tools.
- If `setup_agent` returns an error, report it to the user and do not claim success.
