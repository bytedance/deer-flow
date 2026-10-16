"""Deterministic package resource graph checks."""

from __future__ import annotations

import posixpath
import re
from collections.abc import Set as AbstractSet
from pathlib import PurePosixPath
from typing import Any

from deerflow.skills.package_paths import is_eval_fixture_path
from deerflow.skills.review.models import make_finding, normalize_relative_path

_CODE_SPAN_RE = re.compile(r"`([^`]+)`")
_PATH_TOKEN_RE = re.compile(r"(?<![\w./-])(?:references|scripts|templates|assets|evals)/[A-Za-z0-9._~/%+#-]+")
_RESOURCE_DIRS = {"references", "scripts", "templates", "assets", "evals"}


def build_resource_graph(snapshot: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    files = {str(entry["path"]): entry for entry in snapshot.get("files", [])}
    nodes = [{"path": path, "kind": files[path].get("kind", "unknown")} for path in sorted(files)]
    edges: set[tuple[str, str]] = set()
    missing: set[tuple[str, str]] = set()
    escaping: set[tuple[str, str]] = set()

    for path, entry in files.items():
        if is_eval_fixture_path(path):
            continue
        if entry.get("kind") != "text":
            continue
        content = str(entry.get("content") or "")
        for raw_ref in _extract_references(content):
            resolved = _resolve_reference(path, raw_ref, files.keys())
            if resolved is None:
                continue
            if resolved == "__ESCAPES__":
                escaping.add((path, raw_ref))
            elif resolved in files:
                edges.add((path, resolved))
            else:
                missing.add((path, resolved))

    referenced = {target for _, target in edges}
    resource_paths = {path for path in files if PurePosixPath(path).parts and PurePosixPath(path).parts[0] in _RESOURCE_DIRS}
    orphans = sorted(resource_paths - referenced - {"evals/evals.json", "evals/trigger_eval_set.json"})
    orphans = [path for path in orphans if not is_eval_fixture_path(path)]

    findings: list[dict[str, Any]] = []
    for source, target in sorted(missing):
        findings.append(
            make_finding(
                "resource.missing",
                severity="warning",
                path=source,
                message=f"Referenced resource does not exist: {target}",
                remediation="Add the referenced file, correct the path, or remove the stale reference.",
                evidence=target,
            )
        )
    for source, raw_ref in sorted(escaping):
        findings.append(
            make_finding(
                "resource.escaping-link",
                severity="warning",
                path=source,
                message=f"Reference escapes the package boundary: {raw_ref}",
                remediation="Keep skill references package-relative and inside the skill directory.",
                evidence=raw_ref,
            )
        )
    for orphan in orphans:
        findings.append(
            make_finding(
                "resource.unreferenced",
                severity="warning",
                path=orphan,
                message="Resource is not reachable from SKILL.md or another referenced resource.",
                remediation="Reference the file with read-when guidance or remove it from the package.",
            )
        )

    graph = {
        "nodes": nodes,
        "edges": [{"source": source, "target": target} for source, target in sorted(edges)],
        "orphans": orphans,
    }
    return graph, findings


# Trailing sentence punctuation a resource path can legitimately be followed
# by in prose (".", "?", "!") but that is never part of a package-relative
# path. "." in particular is also a valid path character, so it must only be
# stripped from the very end — e.g. "references/setup.md." -> "references/setup.md"
# while "references/config.yaml" keeps its extension.
_TRAILING_SENTENCE_PUNCTUATION = ".?!"


def _quoted_title_end(content: str, terminator: int) -> int:
    """Return the index just past a ``](target "title")`` closing paren, or -1.

    The optional markdown title is ``\\s+"[^"]*"``: whitespace, a quoted string
    (possibly empty), then the closing paren.
    """
    length = len(content)
    quote = terminator
    while quote < length and content[quote].isspace():
        quote += 1
    if quote >= length or content[quote] != '"':
        return -1
    closing = content.find('"', quote + 1)
    if closing < 0 or closing + 1 >= length or content[closing + 1] != ")":
        return -1
    return closing + 2


def _extract_references(content: str) -> set[str]:
    refs: set[str] = set()
    # Markdown link syntax fixes the fragment semantics: the text after '#'
    # in a link target is ALWAYS a URL fragment, never part of the filename
    # — a link to a file literally named "faq.md#pricing" would have to
    # percent-encode it. So links always strip the fragment, and their full
    # construct is blanked out of the residual text: the code-span and
    # bare-path passes below are literal-path contexts where '#' may be
    # part of a real filename, and they must never see link-internal text.
    # Trailing sentence punctuation is still stripped here (#5739).
    #
    # The link scan is opener-driven instead of a regex: `finditer` over
    # `!?\\[[^\\]]*]\\(([^)\\s]+)(?:\\s+"[^"]*")?\\)` re-scans the same target
    # run from every candidate opener, which is quadratic on content dense in
    # "](" closers whose run never completes (#5714: "[a](" + "x]([" * 16_000
    # + "b y)" took 11 s). The scan below reproduces `finditer` exactly — the
    # regex engine's own start-position scan — while skipping provably
    # match-less regions whole, so each character is visited a constant number
    # of times and the scan stays linear:
    # - `[^\\]]*` cannot cross "]", so the only viable "]" for an opener is
    #   the first one after it; no backtracking can rescue a failed "](".
    # - Every opener sharing that first "]" fails the target run identically,
    #   so a failed run is skipped whole instead of retried inside; only
    #   openers past the last "]" before the terminator may still match and
    #   are retried individually.
    length = len(content)
    spans: list[tuple[int, int]] = []
    position = 0
    while True:
        # A match can only start at "[" (or at the "!" of "!["): this is the
        # regex engine's start-position scan, one candidate at a time.
        opener = content.find("[", position)
        if opener < 0:
            break
        start = opener - 1 if opener > 0 and content[opener - 1] == "!" else opener
        closer = content.find("]", opener + 1)
        if closer < 0:
            # No "]" anywhere later: no opener at/after this one can match.
            break
        if closer + 1 >= length or content[closer + 1] != "(":
            # Every "[" in [opener, closer) shares this same first "]" and
            # fails the "(" check identically: skip them all. This keeps the
            # scan linear on opener-dense input ("[" * n + "]" * n).
            position = closer + 1
            continue
        # The target is a maximal run of non-")"/non-whitespace characters.
        target = closer + 2
        terminator = target
        while terminator < length and content[terminator] != ")" and not content[terminator].isspace():
            terminator += 1
        if terminator == target:
            # "[]()" / "[]( x)": the target needs at least one character;
            # every "[" in [opener, closer) fails the same way.
            position = target
            continue
        if terminator < length and content[terminator] == ")":
            end = terminator + 1
        else:
            end = _quoted_title_end(content, terminator)
            if end < 0:
                # Failed target run. Openers up to the last "]" before the
                # terminator share this same failure (their target run ends
                # at the same terminator with the same title verdict), but an
                # opener after that "]" may still match — its target run
                # starts past the terminator — so only the provably failing
                # prefix is skipped.
                position = content.rfind("]", closer, terminator) + 1
                continue
        refs.add(content[target:terminator].split("#", 1)[0].rstrip(_TRAILING_SENTENCE_PUNCTUATION))
        spans.append((start, end))
        position = end
    # Blank matched spans by position, not by text: `str.replace` blanks an
    # unrelated later occurrence of the same text once spans can overlap
    # consumed text, and it re-scans the whole residual per match (O(n*m) in
    # link count). Spans are non-overlapping and ordered, so a single pass
    # over them blanks each exactly once.
    parts: list[str] = []
    cursor = 0
    for span_start, span_end in spans:
        parts.append(content[cursor:span_start])
        parts.append(" " * (span_end - span_start))
        cursor = span_end
    parts.append(content[cursor:])
    residual = "".join(parts)
    for match in _CODE_SPAN_RE.finditer(residual):
        token = match.group(1).strip()
        if "/" in token:
            refs.add(token.rstrip(_TRAILING_SENTENCE_PUNCTUATION))
    for match in _PATH_TOKEN_RE.finditer(residual):
        refs.add(match.group(0).rstrip(_TRAILING_SENTENCE_PUNCTUATION))
    return refs


def _resolve_reference(
    source_path: str,
    raw_ref: str,
    files: AbstractSet[str] | None = None,
) -> str | None:
    ref = raw_ref.strip().strip("\"'")
    if not ref or ref.startswith("#") or re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", ref):
        return None
    try:
        if ref.startswith("/"):
            return "__ESCAPES__"
        base = PurePosixPath(source_path).parent
        if "://" in ref:
            return None
        if "#" in ref:
            pre_hash, fragment = ref.split("#", 1)
            # A '..' segment in the post-'#' text must never participate in
            # normalization: it would collapse the hash-bearing segment and
            # retarget the edge ("faq.md#/../other.md" must resolve to
            # faq.md). Any other fragment gets its chance first: the whole
            # token may name a real package file — '#' is legal in file AND
            # directory names ("references/C#.md", "references/C#/readme.md"),
            # from nested sources too ("../C#.md"). Only when the
            # canonicalized whole token matches no file does the suffix
            # become a section fragment and get stripped.
            if "/.." in f"/{fragment}" or fragment.startswith(".."):
                ref = pre_hash
            elif files is not None and posixpath.normpath((base / ref).as_posix()) in files:
                return normalize_relative_path((base / ref).as_posix())
            else:
                ref = pre_hash
        return normalize_relative_path((base / ref).as_posix())
    except ValueError:
        return "__ESCAPES__"
