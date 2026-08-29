"""Model-facing subagent report contract (RFC #4651 PR3).

Layer 1 receipt verification is inert unless the subagent actually cites:
a hallucinating or lazy subagent that reports "done" with zero citations is
exactly the case the parent-side verifier cannot distinguish from clean work.
This module owns the prompt-layer text that closes the adoption gap:

- :func:`build_report_contract_section` — injected by the executor into every
  subagent's system prompt (built-in and custom alike), so the citation and
  verifiable-handle requirements never depend on the config author remembering
  them. The citation clause only makes sense while receipts render, so it
  follows ``verification.receipts_enabled``.
- :func:`render_acceptance_criteria_section` — rendered by the executor into
  the subagent's ``SystemMessage`` when the lead attaches
  ``acceptance_criteria``. The criteria deliberately do NOT travel in the task
  ``HumanMessage`` (that message is classed as genuine user input and framed
  as untrusted input), but they are still model-supplied untrusted data, so
  each criterion is neutralized via ``neutralize_untrusted_tags`` before it is
  interpolated: a criterion cannot close the ``<acceptance_criteria>`` block
  or open a framework authority tag.

Both are pure functions over the single-owner citation format in
``tool_receipt.py`` so prompt text can never drift from the verifier.
"""

from __future__ import annotations

#: Bounds for model-supplied acceptance criteria before they enter a subagent
#: prompt. Criteria are model-supplied (ultimately user-influenceable) data, so
#: hygiene is twofold: neutralize framework/injection tags, then cap size.
MAX_ACCEPTANCE_CRITERIA = 20
MAX_CRITERION_CHARS = 500

_HANDLES_LINE = "- Attach a verifiable handle to every deliverable: absolute file path, URL, record ID, or HTTP status."
_HONESTY_LINE = "- State explicitly what failed, was skipped, or remains uncertain — never claim an action you did not execute."


def build_report_contract_section(*, receipts_enabled: bool = True) -> str:
    """Return the ``<report_contract>`` system-prompt section for a subagent.

    When receipts are enabled the contract makes ``[rN]`` citation of the
    execution record mandatory for action claims and states the consequences
    (mismatched anchors, unknown ids, UNVERIFIED for uncited claims) in the
    verifier's own neutral vocabulary — never as a promise of acceptance.
    """
    lines = [
        "<report_contract>",
        "Your final report is a SELF-REPORT. The delegating agent cross-checks it against your execution record and treats uncorroborated action claims as unverified.",
        "",
    ]
    if receipts_enabled:
        # Lazy import: the executor package is imported in cycles with
        # ``deerflow.agents``; resolving the citation format at call time keeps
        # module init order-independent (same pattern as the receipt harvest).
        # The fallback literals only serve contexts where that module is not
        # importable at all (e.g. cycle-breaking test doubles).
        try:
            from deerflow.agents.middlewares.tool_receipt import format_citation, receipt_id

            anchored_example = format_citation(receipt_id(3), "write_file")
            bare_example = format_citation(receipt_id(1))
        except Exception:  # pragma: no cover - defensive against import doubles
            anchored_example = "[r3 write_file]"
            bare_example = "[r1]"
        lines.append(
            f"- Cite a receipt id from the Tool receipts ledger (e.g. {anchored_example}) for every claim about an action you took: "
            "file written, command run, page fetched, request sent. Anchor each citation to the specific call that performed "
            "the action — a citation whose tool label does not match the claim is flagged as failed, and an id absent from "
            "the ledger is flagged as unknown."
        )
        lines.append(_HANDLES_LINE)
        lines.append(_HONESTY_LINE + " A completed report whose action claims carry no receipt citation is flagged UNVERIFIED.")
        lines.append(f"- Receipt citations ({bare_example}) attest your own tool calls only; keep the [citation:Title](URL) format for external web sources.")
    else:
        lines.append(_HANDLES_LINE)
        lines.append(_HONESTY_LINE)
    lines.append("</report_contract>")
    return "\n".join(lines)


def render_acceptance_criteria_section(acceptance_criteria: list[str] | None) -> str:
    """Render lead-supplied acceptance criteria for the subagent SystemMessage.

    Returns "" when there is nothing usable. Entries are stripped, empties
    dropped, the list/item sizes capped, and each entry neutralized via
    :func:`neutralize_untrusted_tags` before interpolation — the criteria are
    model-supplied text crossing into another agent's context, so a criterion
    that closes the ``<acceptance_criteria>`` block or opens a framework
    authority tag must not gain system authority.
    """
    if not acceptance_criteria:
        return ""
    # Lazy import: the executor package is imported in cycles with
    # ``deerflow.agents``; resolving the sanitizer at call time keeps module
    # init order-independent (same pattern as build_report_contract_section).
    from deerflow.agents.middlewares.input_sanitization_middleware import neutralize_untrusted_tags

    criteria: list[str] = []
    for criterion in acceptance_criteria:
        if not isinstance(criterion, str):
            continue
        cleaned = criterion.strip()[:MAX_CRITERION_CHARS].strip()
        if cleaned:
            criteria.append(neutralize_untrusted_tags(cleaned))
        if len(criteria) >= MAX_ACCEPTANCE_CRITERIA:
            break
    if not criteria:
        return ""
    items = "\n".join(f"- {criterion}" for criterion in criteria)
    return (
        "<acceptance_criteria>\n"
        "The delegating agent will judge your result against these criteria. Address each one explicitly in your final "
        "report, with receipt citations or verifiable handles as evidence:\n"
        f"{items}\n"
        "</acceptance_criteria>"
    )
