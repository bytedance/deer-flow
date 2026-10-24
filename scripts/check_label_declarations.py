#!/usr/bin/env python3
"""Check that every label the triage workflow applies is declared in labels.yml.

``.github/labels.yml`` is the declarative source of truth for repository labels,
and ``.github/workflows/triage.yml`` applies labels by name at runtime. GitHub
rejects an ``addLabels`` call with **422** when *any* requested label does not
exist, and drops the whole batch -- so a label added to the workflow but
forgotten here makes labelling stop working silently instead of failing loudly.

This is the static guard for that pair: it extracts the label literals the
triage workflow can apply and asserts each one is declared in labels.yml.

The reader follows quoted literals through arrays, conditional values, variable
aliases, Sets and add/push mutations in each workflow script. Filter predicates,
log messages, YAML comments and JavaScript comments are not label sources. The
current AREA_RULES first-element map is supported; other map transformations,
computed calls/strings and unresolved values fail closed. This is not a general
JavaScript evaluator. The read-only ``skip-validation`` control is not applied.

Standard library only -- the check has to stay cheap enough to run on every PR.
Regression coverage: backend/tests/test_label_declarations.py.

Usage:
    python scripts/check_label_declarations.py
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path
from typing import NamedTuple

REPO_ROOT = Path(__file__).resolve().parent.parent
LABELS_FILE = REPO_ROOT / ".github" / "labels.yml"
TRIAGE_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "triage.yml"

# Only workflow JavaScript is inspected; YAML and JavaScript comments are not
# label sources. Regex literals must be tokens too, so their escaped slashes
# cannot be mistaken for the start of a comment.
SCRIPT = re.compile(r"^(?P<indent> *)script:\s*[|>][-+]?\s*(?:#.*)?$")
JS_TOKEN = re.compile(
    r"(?P<comment>//[^\n]*|/\*.*?\*/)"
    r"|(?P<string>'(?:\\.|[^'\\])*'|\"(?:\\.|[^\"\\])*\")"
    r"|(?P<template>`(?:\\.|[^`\\])*`)"
    r"|(?P<regex>/(?:\\.|\[(?:\\.|[^\]\\])*\]|[^/\\\n])+/[a-z]*)"
    r"|(?P<word>[$A-Za-z_][$\w]*)"
    r"|(?P<symbol>\.\.\.|===|!==|=>|==|!=|\S)",
    re.DOTALL,
)
DECLARED_NAME = re.compile(r"^\s*-\s+name:\s*(?P<value>.+?)\s*$")
PAIRS = {"(": ")", "[": "]", "{": "}"}


class Token(NamedTuple):
    kind: str
    value: str


def workflow_scripts(text: str) -> list[str]:
    scripts: list[str] = []
    lines = text.splitlines()
    for index, line in enumerate(lines):
        match = SCRIPT.match(line)
        if match is None:
            continue
        indent = len(match.group("indent"))
        body: list[str] = []
        for child in lines[index + 1 :]:
            if child.strip() and len(child) - len(child.lstrip(" ")) <= indent:
                break
            body.append(child)
        scripts.append("\n".join(body))
    return scripts


def group_end(tokens: list[Token], start: int) -> int:
    stack: list[str] = []
    for index in range(start, len(tokens)):
        token = tokens[index]
        if token.kind != "symbol":
            continue
        if token.value in PAIRS:
            stack.append(PAIRS[token.value])
        elif token.value in PAIRS.values():
            if not stack or token.value != stack.pop():
                break
            if not stack:
                return index
    raise ValueError("Cannot extract labels from an unbalanced JavaScript expression")


def expression_end(tokens: list[Token], start: int, separators: set[str]) -> int:
    index = start
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "symbol":
            if token.value in separators:
                break
            if token.value in PAIRS:
                index = group_end(tokens, index)
        index += 1
    return index


def literal_values(tokens: list[Token], bindings: dict[str, list[list[Token]]], seen: frozenset[str] = frozenset()) -> set[str]:
    """Follow literal-producing bindings, arrays, Sets and add/push mutations.

    This is a static reader for the workflow's data expressions, not a JavaScript
    evaluator. Conditions and filter predicates do not produce label values.
    Computed calls, concatenation and templates fail rather than claiming they
    have been checked.
    """
    if not tokens:
        return set()
    if tokens[0].value == "(" and group_end(tokens, 0) == len(tokens) - 1:
        return literal_values(tokens[1:-1], bindings, seen)
    comma = expression_end(tokens, 0, {","})
    if comma < len(tokens):
        return literal_values(tokens[:comma], bindings, seen) | literal_values(tokens[comma + 1 :], bindings, seen)
    question = expression_end(tokens, 0, {"?"})
    if question < len(tokens):
        colon = question + 1
        nested = 0
        while colon < len(tokens):
            token = tokens[colon]
            if token.kind == "symbol" and token.value in PAIRS:
                colon = group_end(tokens, colon)
            elif token.value == "?":
                nested += 1
            elif token.value == ":":
                if nested == 0:
                    break
                nested -= 1
            colon += 1
        if colon == len(tokens):
            raise ValueError("Cannot extract labels from an incomplete conditional")
        return literal_values(tokens[question + 1 : colon], bindings, seen) | literal_values(tokens[colon + 1 :], bindings, seen)

    values: set[str] = set()
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token.kind == "string":
            values.add(ast.literal_eval(token.value.replace(r"\/", "/")))
        elif token.kind == "template" or token.value == "+":
            raise ValueError("Cannot extract computed label strings; use quoted label literals")
        elif token.value == "." and index + 2 < len(tokens) and tokens[index + 1].value == "filter" and tokens[index + 2].value == "(":
            index = group_end(tokens, index + 2)
        elif token.value == "." and index + 2 < len(tokens) and tokens[index + 1].value == "map" and tokens[index + 2].value == "(":
            end = group_end(tokens, index + 2)
            callback = tokens[index + 3 : end]
            # AREA_RULES.map(([label]) => label) preserves the first literal
            # in each row. Arbitrary transformations need a real JS evaluator.
            shape = [item.value for item in callback]
            if len(shape) != 7 or shape[:2] != ["(", "["] or shape[3:6] != ["]", ")", "=>"] or shape[2] != shape[6]:
                raise ValueError("Cannot extract labels from a computed map transformation")
            index = end
        elif token.value in PAIRS and token.kind == "symbol":
            end = group_end(tokens, index)
            values |= literal_values(tokens[index + 1 : end], bindings, seen)
            index = end
        elif token.kind == "word" and (index == 0 or tokens[index - 1].value != "."):
            if index + 1 < len(tokens) and tokens[index + 1].value == "(" and token.value != "Set":
                raise ValueError(f"Cannot extract computed label call {token.value}()")
            if token.value in {"new", "Set"}:
                pass
            elif token.value not in bindings or token.value in seen:
                raise ValueError(f"Cannot extract unresolved label value {token.value}")
            else:
                for expression in bindings[token.value]:
                    values |= literal_values(expression, bindings, seen | {token.value})
        index += 1
    return values


def script_labels(script: str) -> set[str]:
    tokens = [Token(match.lastgroup, match.group()) for match in JS_TOKEN.finditer(script) if match.lastgroup != "comment"]
    bindings: dict[str, list[list[Token]]] = {}
    for index, token in enumerate(tokens):
        if token.kind != "word":
            continue
        if index + 1 < len(tokens) and tokens[index + 1].value == "=" and (index == 0 or tokens[index - 1].value != "."):
            end = expression_end(tokens, index + 2, {";"})
            bindings.setdefault(token.value, []).append(tokens[index + 2 : end])
        if index + 3 < len(tokens) and tokens[index + 1].value == "." and tokens[index + 2].value in {"push", "add", "unshift"} and tokens[index + 3].value == "(":
            end = group_end(tokens, index + 3)
            bindings.setdefault(token.value, []).append(tokens[index + 4 : end])

    labels: set[str] = set()
    for index, token in enumerate(tokens[:-1]):
        if token.value != "addLabels" or tokens[index + 1].value != "(":
            continue
        end = group_end(tokens, index + 1)
        found = False
        for argument in range(index + 2, end):
            key = tokens[argument]
            if key.value != "labels" and not (key.kind == "string" and ast.literal_eval(key.value) == "labels"):
                continue
            if tokens[argument + 1].value == ":":
                stop = expression_end(tokens, argument + 2, {",", "}"})
                expression = tokens[argument + 2 : stop]
            elif tokens[argument + 1].value in {",", "}"} and key.kind == "word":
                expression = [key]
            else:
                continue
            values = literal_values(expression, bindings)
            if not values:
                raise ValueError("Cannot extract label literals from addLabels; use a statically defined labels value")
            labels |= values
            found = True
            break
        if not found:
            raise ValueError("Cannot extract labels: addLabels has no supported labels argument")
    return labels


def declared_labels(path: Path) -> set[str]:
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = DECLARED_NAME.match(line)
        if match:
            names.add(match.group("value").strip().strip("'\""))
    return names


def applied_labels(path: Path) -> set[str]:
    labels: set[str] = set()
    for script in workflow_scripts(path.read_text(encoding="utf-8")):
        labels |= script_labels(script)
    return labels


def main() -> int:
    if not LABELS_FILE.is_file():
        sys.exit(f"Missing {LABELS_FILE}")
    if not TRIAGE_WORKFLOW.is_file():
        sys.exit(f"Missing {TRIAGE_WORKFLOW}")

    declared = declared_labels(LABELS_FILE)
    try:
        applied = applied_labels(TRIAGE_WORKFLOW)
    except (ValueError, SyntaxError) as error:
        sys.exit(f"Cannot extract labels from {TRIAGE_WORKFLOW}: {error}")

    # Guard the guards: a change that makes either extraction match nothing would
    # otherwise turn this check into a no-op that always passes.
    if len(declared) < 20:
        sys.exit(f"Only {len(declared)} labels parsed from {LABELS_FILE} -- the extraction is broken.")
    if not applied:
        sys.exit(f"No label literals found in {TRIAGE_WORKFLOW} -- the extraction is broken.")

    missing = sorted(applied - declared)
    if missing:
        print(
            f"{len(missing)} label(s) applied by {TRIAGE_WORKFLOW.name} are not declared in {LABELS_FILE.name}:",
            file=sys.stderr,
        )
        for name in missing:
            print(f"  - {name}", file=sys.stderr)
        print(
            "\nGitHub drops the whole addLabels batch with 422 when a label is missing, so add these under the matching section of labels.yml.",
            file=sys.stderr,
        )
        return 1

    print(f"OK -- {len(applied)} labels applied by {TRIAGE_WORKFLOW.name} are all declared.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
