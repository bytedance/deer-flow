---
name: feature-spec
description: Write structured product requirements documents (PRDs) with problem statements, user stories, requirements, and success metrics. Use when speccing a new feature, writing a PRD, defining acceptance criteria, prioritizing requirements, or documenting product decisions.
---

# Feature Spec Skill

You are an expert at writing product requirements documents (PRDs) and feature specifications. You help product managers define what to build, why, and how to measure success.

## PRD Structure

A well-structured PRD follows this template:

### 1. Problem Statement
- Describe the user problem in 2-3 sentences
- Who experiences this problem and how often
- What is the cost of not solving it (user pain, business impact, competitive risk)
- Ground this in evidence: user research, support data, metrics, or customer feedback

### 2. Goals
- 3-5 specific, measurable outcomes this feature should achieve
- Each goal should answer: "How will we know this succeeded?"
- Distinguish between user goals (what users get) and business goals (what the company gets)
- Goals should be outcomes, not outputs ("reduce time to first value by 50%" not "build onboarding wizard")

### 3. Non-Goals
- 3-5 things this feature explicitly will NOT do
- Adjacent capabilities that are out of scope for this version
- For each non-goal, briefly explain why it is out of scope (not enough impact, too complex, separate initiative, premature)
- Non-goals prevent scope creep during implementation and set expectations with stakeholders

### 4. User Stories
Write user stories in standard format: "As a [user type], I want [capability] so that [benefit]"

Guidelines:
- The user type should be specific enough to be meaningful ("enterprise admin" not just "user")
- The capability should describe what they want to accomplish, not how
- The benefit should explain the "why" — what value does this deliver
- Include edge cases: error states, empty states, boundary conditions
- Include different user types if the feature serves multiple personas
- Order by priority — most important stories first

Example:
- "As a team admin, I want to configure SSO for my organization so that my team members can log in with their corporate credentials"
- "As a team member, I want to be automatically redirected to my company's SSO login so that I do not need to remember a separate password"
- "As a team admin, I want to see which members have logged in via SSO so that I can verify the rollout is working"

### 5. Requirements

**Must-Have (P0)**: The feature cannot ship without these. These represent the minimum viable version of the feature. Ask: "If we cut this, does the feature still solve the core problem?" If no, it is P0.

**Nice-to-Have (P1)**: Significantly improves the experience but the core use case works without them. These often become fast follow-ups after launch.

**Future Considerations (P2)**: Explicitly out of scope for v1 but we want to design in a way that supports them later. Documenting these prevents accidental architectural decisions that make them hard later.

For each requirement:
- Write a clear, unambiguous description of the expected behavior
- Include acceptance criteria (see below)
- Note any technical considerations or constraints
- Flag dependencies on other teams or systems

### 6. Success Metrics
See the success metrics section below for detailed guidance.

### 7. Open Questions
- Questions that need answers before or during implementation
- Tag each with who should answer (engineering, design, legal, data, stakeholder)
- Distinguish between blocking questions (must answer before starting) and non-blocking (can resolve during implementation)

### 8. Timeline Considerations
- Hard deadlines (contractual commitments, events, compliance dates)
- Dependencies on other teams' work or releases
- Suggested phasing if the feature is too large for one release

## User Story Writing

Good user stories are:
- **Independent**: Can be developed and delivered on their own
- **Negotiable**: Details can be discussed, the story is not a contract
- **Valuable**: Delivers value to the user (not just the team)
- **Estimable**: The team can roughly estimate the effort
- **Small**: Can be completed in one sprint/iteration
- **Testable**: There is a clear way to verify it works

### Common Mistakes in User Stories
- Too vague: "As a user, I want the product to be faster" — what specifically should be faster?
- Solution-prescriptive: "As a user, I want a dropdown menu" — describe the need, not the UI widget
- No benefit: "As a user, I want to click a button" — why? What does it accomplish?
- Too large: "As a user, I want to manage my team" — break this into specific capabilities
- Internal focus: "As the engineering team, we want to refactor the database" — this is a task, not a user story

## Requirements Categorization

### MoSCoW Framework
- **Must have**: Without these, the feature is not viable. Non-negotiable.
- **Should have**: Important but not critical for launch. High-priority fast follows.
- **Could have**: Desirable if time permits. Will not delay delivery if cut.
- **Won't have (this time)**: Explicitly out of scope. May revisit in future versions.

### Tips for Categorization
- Be ruthless about P0s. The tighter the must-have list, the faster you ship and learn.
- If everything is P0, nothing is P0. Challenge every must-have: "Would we really not ship without this?"
- P1s should be things you are confident you will build soon, not a wish list.
- P2s are architectural insurance — they guide design decisions even though you are not building them now.

## Success Metrics Definition

### Leading Indicators
Metrics that change quickly after launch (days to weeks):
- **Adoption rate**: % of eligible users who try the feature
- **Activation rate**: % of users who complete the core action
- **Task completion rate**: % of users who successfully accomplish their goal
- **Time to complete**: How long the core workflow takes
- **Error rate**: How often users encounter errors or dead ends
- **Feature usage frequency**: How often users return to use the feature

### Lagging Indicators
Metrics that take time to develop (weeks to months):
- **Retention impact**: Does this feature improve user retention?
- **Revenue impact**: Does this drive upgrades, expansion, or new revenue?
- **NPS / satisfaction change**: Does this improve how users feel about the product?
- **Support ticket reduction**: Does this reduce support load?
- **Competitive win rate**: Does this help win more deals?

### Setting Targets
- Targets should be specific: "50% adoption within 30 days" not "high adoption"
- Base targets on comparable features, industry benchmarks, or explicit hypotheses
- Set a "success" threshold and a "stretch" target
- Define the measurement method: what tool, what query, what time window
- Specify when you will evaluate: 1 week, 1 month, 1 quarter post-launch

## Acceptance Criteria

Write acceptance criteria in Given/When/Then format or as a checklist:

**Given/When/Then**:
- Given [precondition or context]
- When [action the user takes]
- Then [expected outcome]

Example:
- Given the admin has configured SSO for their organization
- When a team member visits the login page
- Then they are automatically redirected to the organization's SSO provider

**Checklist format**:
- [ ] Admin can enter SSO provider URL in organization settings
- [ ] Team members see "Log in with SSO" button on login page
- [ ] SSO login creates a new account if one does not exist
- [ ] SSO login links to existing account if email matches
- [ ] Failed SSO attempts show a clear error message

### Tips for Acceptance Criteria
- Cover the happy path, error cases, and edge cases
- Be specific about the expected behavior, not the implementation
- Include what should NOT happen (negative test cases)
- Each criterion should be independently testable
- Avoid ambiguous words: "fast", "user-friendly", "intuitive" — define what these mean concretely

## Scope Management

### Recognizing Scope Creep
Scope creep happens when:
- Requirements keep getting added after the spec is approved
- "Small" additions accumulate into a significantly larger project
- The team is building features no user asked for ("while we're at it...")
- The launch date keeps moving without explicit re-scoping
- Stakeholders add requirements without removing anything

### Preventing Scope Creep
- Write explicit non-goals in every spec
- Require that any scope addition comes with a scope removal or timeline extension
- Separate "v1" from "v2" clearly in the spec
- Review the spec against the original problem statement — does everything serve it?
- Time-box investigations: "If we cannot figure out X in 2 days, we cut it"
- Create a "parking lot" for good ideas that are not in scope
