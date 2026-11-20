"""Answer-prompt rendering for the live QA comparison.

Rendering is pinned by the committed template (hash-checked by the config) and
by this module: retained facts are sorted by their historical protocol fact IDs
(``gold_{case}`` / ``d_{case}_{index}_{source}``), each fact renders as
``[{fact_id}]`` followed by its content on the next line, fact blocks are
joined with a blank line, and the ``CURRENT DATE`` line is omitted when the
case has no question date.
"""

from __future__ import annotations

from dataclasses import dataclass

from .policy import PolicyResult
from .pool import PreparedCase

_SYSTEM_HEADER = "SYSTEM:\n"
_USER_SEPARATOR = "\n\nUSER:\n"
_CURRENT_DATE_PLACEHOLDER = "{{CURRENT_DATE_SECTION}}"
_STORED_MEMORY_PLACEHOLDER = "{{STORED_MEMORY}}"
_QUESTION_PLACEHOLDER = "{{QUESTION}}"


@dataclass(frozen=True)
class AnswerTask:
    row_id: str
    case_id: str
    source: str
    scenario: str
    policy: str
    capacity: int
    kept_fact_ids: tuple[str, ...]
    messages: tuple[dict[str, str], ...]


def split_prompt_template(template: str) -> tuple[str, str]:
    if not template.startswith(_SYSTEM_HEADER) or _USER_SEPARATOR not in template:
        raise ValueError("The answer prompt template must contain SYSTEM: and USER: sections")
    system_part, user_part = template.removeprefix(_SYSTEM_HEADER).split(_USER_SEPARATOR, 1)
    for placeholder in (_CURRENT_DATE_PLACEHOLDER, _STORED_MEMORY_PLACEHOLDER, _QUESTION_PLACEHOLDER):
        if placeholder not in user_part:
            raise ValueError(f"The answer prompt template is missing {placeholder}")
    return system_part.strip("\n"), user_part.strip("\n")


def render_answer_messages(template: str, *, question: str, question_date: str | None, retained_facts: list[tuple[str, str]]) -> tuple[dict[str, str], ...]:
    if not retained_facts:
        raise ValueError("Rendering requires at least one retained fact")
    system_part, user_part = split_prompt_template(template)
    ordered = sorted(retained_facts, key=lambda fact: fact[0])
    if len({fact_id for fact_id, _ in ordered}) != len(ordered):
        raise ValueError("Retained facts must have unique IDs")
    current_date_section = f"CURRENT DATE: {question_date}\n" if question_date else ""
    stored_memory = "\n\n".join(f"[{fact_id}]\n{content}" for fact_id, content in ordered)
    user = user_part.replace(_CURRENT_DATE_PLACEHOLDER, current_date_section).replace(_STORED_MEMORY_PLACEHOLDER, stored_memory).replace(_QUESTION_PLACEHOLDER, question)
    return ({"role": "system", "content": system_part}, {"role": "user", "content": user})


def build_answer_task(case: PreparedCase, result: PolicyResult, template: str) -> AnswerTask:
    if result.case_id != case.case_id:
        raise ValueError(f"policy result {result.case_id!r} does not belong to case {case.case_id!r}")
    kept = set(result.kept_fact_ids)
    retained_facts = [(str(fact["id"]), str(fact["content"])) for fact in case.facts if str(fact["id"]) in kept]
    if len(retained_facts) != len(kept):
        raise ValueError(f"case {case.case_id!r} is missing content for kept facts")
    messages = render_answer_messages(template, question=case.question, question_date=case.question_date, retained_facts=retained_facts)
    return AnswerTask(
        row_id=f"{case.case_id}__{result.policy}",
        case_id=case.case_id,
        source=case.source,
        scenario=case.scenario,
        policy=result.policy,
        capacity=result.capacity,
        kept_fact_ids=result.kept_fact_ids,
        messages=messages,
    )
