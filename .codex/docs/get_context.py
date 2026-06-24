#!/usr/bin/env python3
"""
Get detailed information for a specific file or folder path.

Usage:
    python .codex/docs/get_context.py <file_or_folder_path>

The script reads from .codex/docs/files.json and .codex/docs/folders.json
and returns context for the provided path. Pass any file or folder path.

For files:
- Detailed description of the file
- Semantic tags, entities handled, and key behaviors
- Related files with semantic explanations
- Tests that exercise this file
- Historical insights (bugs, fixes, lessons learned)

For folders:
- Folder role and responsibility in the codebase
- Key files and why they matter
- Cross-cutting behaviors and distilled insights
"""

import json
import random
import sys
from pathlib import Path


def normalize_path(path):
    """Normalize a file path for comparison."""
    return str(Path(path).as_posix())


def load_files_data(docs_dir):
    """Load files data from JSON file."""
    files_json = docs_dir / "files.json"
    if not files_json.exists():
        return {}

    try:
        with open(str(files_json), "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print("Error loading files.json: {}".format(e), file=sys.stderr)
        return {}


def load_folders_data(docs_dir):
    """Load folders data from JSON file."""
    folders_json = docs_dir / "folders.json"
    if not folders_json.exists():
        return {}
    try:
        with open(str(folders_json), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data.get("folders", {})
    except (json.JSONDecodeError, IOError) as e:
        print("Error loading folders.json: {}".format(e), file=sys.stderr)
        return {}


def _render_description(file_data):
    description = file_data.get("description", "")
    if not description:
        return ""
    return "### Description\n{}".format(description)


def _render_edit_checklist(file_data):
    checklist = file_data.get("edit_checklist", {})
    if not checklist:
        return ""
    lines = ["### Edit Checklist"]
    tests_to_run = checklist.get("tests_to_run", [])
    if tests_to_run:
        lines.append("Tests to run: {}".format(
            ", ".join("`{}`".format(c) for c in tests_to_run)))
    data_constants = checklist.get("data_constants_to_check", [])
    if data_constants:
        lines.append("Data/constants: {}".format(
            ", ".join("`{}`".format(c) for c in data_constants)))
    if checklist.get("owns_authoritative_data"):
        lines.append("WARNING: Owns authoritative data - single source of truth.")
    if checklist.get("public_api_surface"):
        lines.append("WARNING: Public API surface - changes may affect consumers.")
    return "\n".join(lines)


def _render_insights(file_data):
    insights = file_data.get("insights", [])
    if not insights:
        return ""
    if len(insights) > 15:
        insights = random.sample(insights, 15)
    lines = ["### Historical Insights"]
    for insight in insights:
        category = insight.get("category", "")
        title = insight.get("title", "")
        if category and title:
            lines.append("- [{}] {}".format(category, title))
        elif title:
            lines.append("- {}".format(title))
        if insight.get("problem"):
            lines.append("  Problem: {}".format(insight["problem"]))
        if insight.get("root_cause"):
            lines.append("  Root cause: {}".format(insight["root_cause"]))
        if insight.get("solution"):
            lines.append("  Solution: {}".format(insight["solution"]))
        commits = insight.get("commits", [])
        if commits:
            lines.append("  Commits: {}".format(
                ", ".join("`{}`".format(c) for c in commits)))
        constructs = insight.get("constructs", [])
        if constructs:
            lines.append("  Constructs: {}".format(
                ", ".join("`{}`".format(c) for c in constructs)))
    return "\n".join(lines)


def _render_key_constructs(file_data):
    key_constructs = file_data.get("key_constructs", [])
    if not key_constructs:
        return ""
    capped = key_constructs[:8]
    lines = ["### Key Constructs"]
    for c in capped:
        name = c.get("name", "")
        ctype = c.get("type", "")
        purpose = c.get("purpose", "")
        lines.append("- **{}** ({}): {}".format(name, ctype, purpose))
        reasoning = c.get("reasoning", "")
        if reasoning:
            lines.append("  {}".format(reasoning))
        callers = c.get("callers", [])
        if callers:
            by_file = {}
            for caller in callers:
                f = caller.get("file", "")
                ln = caller.get("line", "")
                if f not in by_file:
                    by_file[f] = []
                if ln and ln not in by_file[f]:
                    by_file[f].append(ln)
            for f in sorted(by_file):
                line_nums = ", ".join(str(ln) for ln in sorted(by_file[f], key=lambda x: int(x) if str(x).isdigit() else 0))
                lines.append("  - `{}`: called at lines {}".format(f, line_nums))
    if len(key_constructs) > 8:
        lines.append("(+{} more constructs)".format(
            len(key_constructs) - 8))
    return "\n".join(lines)


def _render_tests(file_data):
    tests = file_data.get("tests", {})
    if not tests:
        return ""
    lines = ["### Tests"]
    exercised_by = tests.get("exercised_by", [])
    if exercised_by:
        lines.append("Files: {}".format(
            ", ".join("`{}`".format(f) for f in exercised_by)))
    test_functions = tests.get("test_functions", [])
    if test_functions:
        lines.append("Functions: {}".format(
            ", ".join("`{}`".format(f) for f in test_functions)))
    example_cmd = tests.get("example_command", "")
    if example_cmd:
        lines.append("Run: `{}`".format(example_cmd))
    relevant_snippets = tests.get("relevant_snippets", [])
    if relevant_snippets:
        for s in relevant_snippets:
            lines.append("- `{}` L{}: {}".format(
                s.get("file", ""),
                s.get("lines", ""),
                s.get("description", "")))
    return "\n".join(lines)


def _render_related_files(file_data):
    related_files = file_data.get("related_files", [])
    if not related_files:
        return ""
    lines = ["### Related Files"]
    for rf in related_files:
        path = rf.get("path", "")
        rel = rf.get("relationship", "")
        reason = rf.get("reason_to_check", "")
        co = " [co-change]" if rf.get("likely_co_change") else ""
        entry = "`{}`{}".format(path, co)
        if rel:
            entry += " | Rel: {}".format(rel)
        if reason:
            entry += " | Check: {}".format(reason)
        lines.append("- {}".format(entry))
    return "\n".join(lines)


def _render_semantic_overview(file_data):
    semantic_tags = file_data.get("semantic_tags", [])
    handles_entities = file_data.get("handles_entities", [])
    key_behaviors = file_data.get("key_behaviors", [])
    if not (semantic_tags or handles_entities or key_behaviors):
        return ""
    lines = ["### Semantic Overview"]
    if semantic_tags:
        lines.append("Tags: {}".format(
            ", ".join("`{}`".format(t) for t in semantic_tags)))
    if handles_entities:
        lines.append("Entities: {}".format(
            ", ".join("`{}`".format(e) for e in handles_entities)))
    if key_behaviors:
        for b in key_behaviors:
            lines.append("- {}".format(b))
    return "\n".join(lines)


def _render_pitfalls(file_data):
    pitfalls = file_data.get("pitfalls", [])
    if not pitfalls:
        return ""
    lines = ["### Pitfalls"]
    for p in pitfalls:
        mistake = p.get("mistake", "")
        consequence = p.get("consequence", "")
        prevention = p.get("prevention", "")
        lines.append("- {}".format(mistake))
        if consequence:
            lines.append("  Consequence: {}".format(consequence))
        if prevention:
            lines.append("  Prevention: {}".format(prevention))
    return "\n".join(lines)


def _render_reading_guide(file_data):
    guide = file_data.get("reading_guide", {})
    if not guide:
        return ""
    lines = ["### Reading Guide"]
    start_here = guide.get("start_here", "")
    if start_here:
        lines.append("Start: `{}`".format(start_here))
    key_sections = guide.get("key_sections", [])
    if key_sections:
        lines.append("Key: {}".format(", ".join(key_sections)))
    skip_sections = guide.get("skip_unless_needed", [])
    if skip_sections:
        lines.append("Skip: {}".format(", ".join(skip_sections)))
    return "\n".join(lines)


def _render_folder_description(folder_data):
    description = folder_data.get("description", "")
    if not description:
        return ""
    return "### Description\n{}".format(description)


def _render_folder_key_files(folder_data):
    key_files = folder_data.get("key_files", [])
    if not key_files:
        return ""
    lines = ["### Key Files"]
    for kf in key_files[:10]:
        if isinstance(kf, dict):
            path = kf.get("path", "")
            why = kf.get("why", "")
            if path:
                lines.append("- `{}`: {}".format(path, why or "key file"))
        else:
            lines.append("- `{}`".format(kf))
    return "\n".join(lines)


def _render_folder_behaviors(folder_data):
    behaviors = folder_data.get("key_behaviors", [])
    if not behaviors:
        return ""
    lines = ["### Key Behaviors"]
    for b in behaviors:
        lines.append("- {}".format(b))
    return "\n".join(lines)


def _render_folder_insights(folder_data):
    insights = folder_data.get("insights", [])
    if not insights:
        return ""
    if len(insights) > 15:
        insights = random.sample(insights, 15)
    lines = ["### Insights"]
    for ins in insights:
        if isinstance(ins, dict):
            title = ins.get("title", "")
            category = ins.get("category", "")
            problem = ins.get("problem", "")
            solution = ins.get("solution", "")
            if category and title:
                lines.append("- [{}] {}".format(category, title))
            elif title:
                lines.append("- {}".format(title))
            if problem:
                lines.append("  Problem: {}".format(problem))
            if solution:
                lines.append("  Solution: {}".format(solution))
        else:
            lines.append("- {}".format(ins))
    return "\n".join(lines)


def _render_folder_construct_relationships(folder_data):
    rels = folder_data.get("construct_relationships", [])
    if not rels:
        return ""
    lines = ["### Construct Relationships"]
    for r in rels:
        lines.append("- {}".format(r))
    return "\n".join(lines)


def _render_folder_notable_relationships(folder_data):
    rels = folder_data.get("notable_relationships", [])
    if not rels:
        return ""
    lines = ["### Notable Relationships"]
    for r in rels:
        lines.append("- {}".format(r))
    return "\n".join(lines)


def _render_folder_recommendations(folder_data):
    recs = folder_data.get("recommendations", [])
    if not recs:
        return ""
    lines = ["### Recommendations"]
    for r in recs:
        lines.append("- {}".format(r))
    return "\n".join(lines)


_FOLDER_SECTIONS = [
    (1, _render_folder_description),
    (1, _render_folder_key_files),
    (1, _render_folder_behaviors),
    (1, _render_folder_insights),
    (2, _render_folder_construct_relationships),
    (2, _render_folder_notable_relationships),
    (2, _render_folder_recommendations),
]


def format_folder_context(folder_path, folder_data):
    """Format folder context as markdown."""
    display_path = folder_path if folder_path != "." else "(root)"
    parts = ["# Folder: {}\n".format(display_path)]
    tier = folder_data.get("tier", "")
    if tier:
        parts.append("Tier: {}\n".format(tier))
    for priority in (1, 2):
        fns = [fn for p, fn in _FOLDER_SECTIONS if p == priority]
        for render_fn in fns:
            section = render_fn(folder_data)
            if section:
                parts.append("\n" + section)
    return "".join(parts)


def get_folder_context(folder_path, docs_dir):
    """Get and format context for a folder path."""
    project_root = docs_dir.parent.parent.resolve()
    path_obj = Path(folder_path).absolute()
    if project_root in path_obj.parents or path_obj == project_root:
        try:
            folder_path = str(path_obj.relative_to(project_root).as_posix())
        except ValueError:
            pass
    folder_path = folder_path.rstrip("/").replace("\\", "/") or "."
    folders = load_folders_data(docs_dir)
    if not folders:
        return False, "# Folder Context: {}\n\nNo folders.json data available.".format(folder_path)
    folder_path_norm = normalize_path(folder_path)
    folder_context = folders.get(folder_path_norm) or folders.get(folder_path)
    if not folder_context:
        for key in folders:
            if normalize_path(key) == folder_path_norm or normalize_path(key).rstrip("/") == folder_path_norm:
                folder_context = folders[key]
                break
    if not folder_context:
        return False, "# Folder Context: {}\n\nNo information found for this folder in folders.json.".format(folder_path)
    return True, format_folder_context(folder_path, folder_context)


_SECTIONS = [
    (1, _render_description),
    (1, _render_edit_checklist),
    (1, _render_insights),
    (2, _render_key_constructs),
    (2, _render_tests),
    (3, _render_related_files),
    (3, _render_semantic_overview),
    (3, _render_pitfalls),
    (4, _render_reading_guide),
]


def format_file_context(file_path, file_data):
    """Format file context as markdown."""
    parts = ["# {}\n".format(file_path)]

    for priority in (1, 2, 3, 4):
        tier_fns = [fn for p, fn in _SECTIONS if p == priority]
        for render_fn in tier_fns:
            section = render_fn(file_data)
            if section:
                parts.append("\n" + section)

    return "".join(parts)


def get_file_context(file_path, docs_dir):
    """Get and format context for a file path."""
    project_root = docs_dir.parent.parent.resolve()

    # Convert absolute path to relative path if it's within the project root
    file_path_obj = Path(file_path).absolute()
    if project_root in file_path_obj.parents:
        file_path = str(file_path_obj.relative_to(project_root))

    files_data = load_files_data(docs_dir)
    if not files_data:
        return False, "# File Context: {}\n\nNo files.json data available.".format(
            file_path
        )

    files = files_data.get("files", {})
    file_path_norm = normalize_path(file_path)

    file_context = files.get(file_path_norm) or files.get(file_path)

    if not file_context:
        for key in files:
            if normalize_path(key) == file_path_norm:
                file_context = files[key]
                break

    if not file_context:
        return (
            False,
            "# File Context: {}\n\nNo information found for this file in files.json.".format(
                file_path
            ),
        )

    return True, format_file_context(file_path, file_context)


def main():
    """Main entry point.

    Supports two modes:
    1. Hook mode: Reads JSON from stdin (PostToolUse hook format)
    2. Standalone mode: Takes a file or folder path as command-line argument
    """
    if len(sys.argv) >= 2:
        path_arg = sys.argv[1]
        script_path = Path(__file__).resolve()
        docs_dir = script_path.parent
        success, output = get_file_context(path_arg, docs_dir)
        if not success:
            success_f, output_f = get_folder_context(path_arg, docs_dir)
            if success_f:
                print(output_f)
                return
            print(output)
            sys.exit(1)
        print(output)
        return

    # Otherwise, try hook mode: read JSON from stdin
    try:
        input_data = json.load(sys.stdin)

        # Check if this looks like hook input (has hook_event_name or tool_response)
        if "hook_event_name" in input_data or "tool_response" in input_data:
            # Extract file path from tool response (PostToolUse has tool_response)
            tool_response = input_data.get("tool_response", {})
            file_path = tool_response.get("filePath") or tool_response.get("file_path")

            # Fallback to tool_input if not in response
            if not file_path:
                tool_input = input_data.get("tool_input", {})
                file_path = tool_input.get("target_file") or tool_input.get("file_path")

            if file_path:
                script_path = Path(__file__).resolve()
                docs_dir = script_path.parent

                success, file_context = get_file_context(file_path, docs_dir)

                if not success:
                    output = {
                        "decision": "block",
                        "reason": "No information found for this file in files.json. Proceed as normal.",
                    }
                    print(json.dumps(output))
                    sys.exit(0)

                # Output JSON with additional context for Claude
                output = {
                    "decision": "block",
                    "reason": "Relevant information about the file you are reading was found. Appending it to the conversation.",
                    "hookSpecificOutput": {
                        "hookEventName": "PostToolUse",
                        "additionalContext": file_context,
                    },
                }

                print(json.dumps(output))
                sys.exit(0)
    except (json.JSONDecodeError, ValueError, OSError):
        # Not valid JSON or not hook input
        pass

    # If we get here, neither mode worked
    print("Usage: python get_context.py <file_or_folder_path>", file=sys.stderr)
    sys.exit(2)


if __name__ == "__main__":
    main()
