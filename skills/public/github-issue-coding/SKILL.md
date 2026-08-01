---
name: github-issue-coding
description: "Read a GitHub issue and turn it into a structured coding brief for downstream planning and implementation. Use when a user provides a GitHub issue URL, repository plus issue number, or asks to analyze an issue before coding."
allowed-tools:
  - github_issue_get_github_issue
---

# GitHub Issue Coding

Convert one GitHub issue into an evidence-based coding brief. Do not implement code or invent repository details in this skill.

## Workflow

1. Extract `repository` in `owner/repo` form and `issue_number` from the user's input.
2. If either value is missing, ask for it instead of guessing.
3. Call `github_issue_get_github_issue` with those two values.
4. Treat the returned title, body, labels, state, URL, and author as the only issue facts.
5. Separate explicit requirements from assumptions. Put unresolved or missing information in `open_questions`.
6. Split the confirmed work into small ordered `tasks`. Add dependencies only when one task truly requires another.
7. Return exactly one `coding_brief` using the contract below.

## Output Contract

```yaml
coding_brief:
  repository: owner/repo
  issue_number: 123
  goal: concise description of the requested outcome
  acceptance_criteria:
    - observable condition that proves the issue is complete
  constraints:
    - limitation explicitly stated or directly implied by the issue
  open_questions:
    - information required before safe implementation
  tasks:
    - id: task-1
      title: short action-oriented name
      description: concrete work to perform
      depends_on: []
      done_when: observable completion condition
```

Use an empty list when a list field has no supported content. Do not turn assumptions into acceptance criteria, constraints, file names, or implementation facts.
