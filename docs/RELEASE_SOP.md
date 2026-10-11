# DeerFlow Release SOP

Standard operating procedure for cutting a DeerFlow release. The goal is a
self-consistent release: **every merged milestone PR is documented in English
*and* Chinese**, a curated release-notes file ships, and the tree is bumped to
the next development version.

---

## 0. Prerequisites

- Work on the release branch (e.g. `2.0.0-release`); `main` is the merge target.
- `gh` CLI authenticated; working tree clean.

## 1. Gather the complete PR + contributor list

```bash
VER=2.0.0
REPO=bytedance/deer-flow

# All merged milestone PRs: number, title, labels
gh search prs --repo $REPO --milestone "$VER" --merged --limit 300 \
  --json number,title,labels \
  --jq 'sort_by(.number) | .[] | "#\(.number)\t\(.title)\t\([.labels[].name]|join(","))"' \
  > /tmp/milestone_details.txt

# Sorted PR numbers + total count
gh search prs --repo $REPO --milestone "$VER" --merged --limit 300 \
  --json number --jq '[.[].number]|sort|.[]' > /tmp/milestone_prs.txt
wc -l /tmp/milestone_prs.txt   # <-- this is the authoritative merged-PR count

# Contributors (login -> display name via `gh api users/<login>`)
gh search prs --repo $REPO --milestone "$VER" --merged --limit 300 \
  --json author --jq '[.[].author.login]'
```

## 2. Update `CHANGELOG.md` (Keep a Changelog)

1. **Find the gap** — diff milestone PRs vs already-cited ones:

   ```bash
   grep -oE '\[#[0-9]+\]' CHANGELOG.md | grep -oE '[0-9]+' | sort -n -u > /tmp/changelog_prs.txt
   comm -23 /tmp/milestone_prs.txt /tmp/changelog_prs.txt   # the missing PRs
   ```

2. **Categorize** each missing PR (by its conventional-commit title/labels) into
   the existing sections:

   - `⚠ Breaking changes`
   - `Added` — Agents & runtime / Models & integrations / Observability / Skills
   - `Performance`
   - `Security`
   - `Fixed` — Runtime-gateway-persistence / Agents-subagents-middleware /
     Memory-tracing / Tools-sandbox-MCP / Skills-channels / Auth / Frontend /
     Build-deploy-scripts-config
   - `Changed`
   - `Documentation`
   - `Internal`

   Match the existing entry style: `- **scope:** Description. ([#NNNN])`.

3. **Update the intro count** — `with **N merged pull requests**` must equal the
   `wc -l` total from step 1.

4. **Rebuild the reference block** — keep everything up to and including the
   `[2.0.0]: https://github.com/bytedance/deer-flow/releases/tag/v2.0.0` line,
   then append a globally-sorted `[#NNNN]: …/pull/NNNN` list for every cited PR:

   ```bash
   { cat /tmp/changelog_prs.txt; comm -23 /tmp/milestone_prs.txt /tmp/changelog_prs.txt; } \
     | sort -n | uniq | while read n; do
       printf '[#%s]: https://github.com/bytedance/deer-flow/pull/%s\n' "$n" "$n"
     done > /tmp/refs.txt
   # then splice /tmp/refs.txt after the release-tag line
   ```

## 3. Update `CHANGELOG_zh.md`

Mirror the English structure exactly and translate the new entries (keep
code/terminals like `sandbox reducer`, `ContextVar` in English where the zh file
already does). Rebuild its reference block the same way as step 2.4.

## 4. Update `docs/RELEASE_NOTES_vX.Y.Z.md` (curated, not exhaustive)

- **Highlights** — big features only (new providers, tools, channels, config toggles).
- **Performance / Security / Notable fixes / Deploy & ops** — grouped one-liners.
- **Thanks** — accurate contributor count + an alphabetically-sorted
  `@handle — Name` list. Clean up any duplicated headers or empty
  `Full Changelog:` links.
- Update both counts (merged PRs, contributors).

## 5. Verify (do NOT skip)

```bash
python3 - <<'PY'
import re
def analyze(path):
    t = open(path).read()
    m = "[2.0.0]: https://github.com/bytedance/deer-flow/releases/tag/v2.0.0"
    body, _, refs = t.partition(m)
    cited   = set(int(n) for n in re.findall(r"\[#(\d+)\]", body))
    defined = set(int(n) for n in re.findall(r"^\[#(\d+)\]:", refs, re.M))
    return cited, defined

en_c, en_d = analyze("CHANGELOG.md")
zh_c, zh_d = analyze("CHANGELOG_zh.md")
ms = set(int(l) for l in open("/tmp/milestone_prs.txt"))

print("milestone missing in zh:", sorted(ms - zh_c) or "✓")
print("orphans:",  sorted(zh_c - zh_d) or "✓", "| unused:", sorted(zh_d - zh_c) or "✓")
print("EN/ZH cited parity:", "✓" if en_c == zh_c else "DIFF")
PY
```

Must hold:
- **Full milestone coverage** — every merged milestone PR is cited.
- **No orphan / unused** reference links.
- **EN ⇄ ZH cited sets are identical.**
- All cited PRs are valid.

## 6. Bump to the next development version (e.g. `2.0.0` → `2.1.0`)

The project version lives in **five** places:

| File | What |
|------|------|
| `backend/pyproject.toml` | root `deer-flow` |
| `backend/packages/harness/pyproject.toml` | `deerflow-harness` |
| `frontend/package.json` | `deer-flow-frontend` |
| `backend/uv.lock` | `deer-flow` + `deerflow-harness` `[[package]]` entries |

> `frontend/pnpm-lock.yaml` does **not** store our project version — leave it
> alone (its `2.0.0` hits are third-party deps like `cffi`).

Then confirm no project-version leftovers:

```bash
git grep -nI '2\.0\.0' -- . \
  ':(exclude)CHANGELOG.md' ':(exclude)CHANGELOG_zh.md' ':(exclude)docs/RELEASE_NOTES_v2.0.0.md' \
  ':(exclude)backend/uv.lock' ':(exclude)frontend/pnpm-lock.yaml'
# expect: only unrelated dependency pins remain
```

## 7. Publish

1. Commit the docs + version bump.
2. Tag `vX.Y.Z`.
3. Cut the GitHub release using `docs/RELEASE_NOTES_vX.Y.Z.md` as the body.
4. Merge the release branch back to `main`.

---

## Key invariants

- **Two CHANGELOGs stay in lock-step** — same cited PR set, same reference definitions.
- **The intro count == number of merged milestone PRs** (verified, not guessed).
- **References are globally sorted and complete** — every `[#NNNN]` cited has a
  definition and vice-versa.
- **Release notes cite only real PRs**; companion PRs paired in the CHANGELOG are fine.
- **Version lives in 5 spots** — bumping a subset leaves the tree inconsistent.
