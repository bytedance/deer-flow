# Releasing DeerFlow

DeerFlow releases are **tag-driven**: pushing a `v*` git tag triggers the
publishing workflows. There is no separate release script that bumps versions —
the maintainer bumps the version sources, updates the changelog, commits, and
tags. The helper scripts below keep the version sources in lockstep, and CI
gates the release on them agreeing with the tag.

## Version sources

A release version must appear, identically, in four places:

| File                                   | Field                |
| -------------------------------------- | -------------------- |
| `backend/pyproject.toml`               | `version = "X.Y.Z"`  |
| `frontend/package.json`                | `"version": "X.Y.Z"` |
| `deploy/helm/deer-flow/Chart.yaml`     | `version: X.Y.Z`     |
| `deploy/helm/deer-flow/Chart.yaml`     | `appVersion: "X.Y.Z"`|

Plus the git tag `vX.Y.Z` itself, which is the canonical release identifier.

Container images are tagged from the git tag (not from these files), and the
Helm chart version is validated against the tag — so if any source lags the
tag, the release is blocked (see [Version gate](#version-gate)).

## Helper scripts

- `scripts/bump_version.sh <version>` — set all four fields at once, then
  self-verify. Tolerates a leading `v` (e.g. `v2.2.0`).
  ```bash
  scripts/bump_version.sh 2.2.0
  ```
- `scripts/verify_versions.sh [version]` — check that all sources agree. With
  no argument it requires mutual equality; with an argument it requires every
  source to equal it. Exits non-zero on mismatch. Run it locally before tagging
  to catch drift early:
  ```bash
  scripts/verify_versions.sh 2.2.0
  ```

## Release procedure

1. **Bump the version** across all sources:
   ```bash
   scripts/bump_version.sh 2.2.0
   ```
2. **Update `CHANGELOG.md`**: rename the `## [Unreleased]` section to
   `## [2.2.0] — YYYY-MM-DD` (note the em dash `—`), and add a link reference
   at the bottom of the file:
   ```
   [2.2.0]: https://github.com/bytedance/deer-flow/releases/tag/v2.2.0
   ```
   Start a fresh `## [Unreleased]` section above it for the next cycle.
3. **Commit** the version + changelog changes:
   ```bash
   git add -A
   git commit -m "release: v2.2.0"
   ```
4. **Tag and push**:
   ```bash
   git tag v2.2.0
   git push origin v2.2.0
   ```
   Pushing the tag triggers the publishing workflows (below).

## What CI publishes on a `v*` tag

- `.github/workflows/container.yaml` — builds and pushes `backend`,
  `frontend`, and `provisioner` images to `ghcr.io`, tagged with the release
  version (and `latest` on the default branch).
- `.github/workflows/chart.yaml` — packages the Helm chart and pushes it as an
  OCI artifact to `ghcr.io`. Users install with:
  ```bash
  helm install deer-flow oci://ghcr.io/<owner>/deer-flow --version 2.2.0
  ```

## Nightly builds

`.github/workflows/nightly.yaml` runs on a schedule (and `workflow_dispatch`)
to publish the same three images plus the chart from unreleased `main`. It is
**not** gated by the version check (there is no `v*` tag) and it does **not**
touch the `latest` tag, which stays pinned to the last `v*` release. Every job
is gated on `github.repository == 'bytedance/deer-flow'`, so it only runs on
the upstream repo - a scheduled run or manual dispatch on a fork skips all jobs.

Artifacts (under the running repo's owner, where `<date>` is `YYYYMMDD`):

- Images: `ghcr.io/<owner>/deer-flow-{backend,frontend,provisioner}:nightly`
  (rolling, overwritten each run) and `:nightly-<date>` (pinned to a day, but
  mutable within it - a same-day re-dispatch overwrites it). For a truly
  immutable pin, use `:sha-<short>`.
- Chart: `oci://ghcr.io/<owner>/deer-flow`, version `<base>-nightly.<date>-<sha>`
  (e.g. `2.2.0-nightly.20260710-77a3652`). The short SHA makes each dispatch's
  chart version unique, so a same-day re-dispatch re-publishes cleanly (OCI
  chart versions are immutable and otherwise can't be overwritten). The
  packaged chart defaults `image.registry=ghcr.io/<owner>` and
  `image.tag=nightly`, so installing it pulls the matching nightly images with
  no values overrides:
  ```bash
  helm install deer-flow oci://ghcr.io/<owner>/deer-flow \
    --version 2.2.0-nightly.20260710-77a3652
  ```

The chart version is patched in-workflow only - `Chart.yaml` and `values.yaml`
in the repo are never modified.

## Version gate

Both publishing workflows call `.github/workflows/verify-versions.yml` as their
first job. It runs `scripts/verify_versions.sh` against the tag (minus the
`v`). If any of the four version sources doesn't match the tag, the verify job
fails and **all** publish jobs are skipped — no images, no chart.

When it fails, the job annotation names the offending file and suggests the
fix:

```
::error::frontend/package.json is '2.1.0' but expected '2.2.0'.
Tip: run scripts/bump_version.sh 2.2.0 to align all sources.
```

## Pre-releases (RCs)

Pre-release tags like `v2.2.0-rc1` are valid `v*` tags and trigger the same
workflows. The version sources must equal the full pre-release string
(`2.2.0-rc1`) — the gate compares exact strings. Use the same procedure with
the rc version:

```bash
scripts/bump_version.sh 2.2.0-rc1
# update CHANGELOG, commit, tag v2.2.0-rc1, push
```

## Recovering from a failed gate

If the gate failed because a source was forgotten:

1. Run `scripts/bump_version.sh <version>` to align the sources.
2. Amend or add a follow-up commit.
3. Delete and re-create the tag, then push it:
   ```bash
   git tag -d v2.2.0
   git tag v2.2.0
   git push origin :refs/tags/v2.2.0
   git push origin v2.2.0
   ```

Re-pushing the tag re-triggers the workflows. Because the gate blocks **all**
artifacts when it fails, nothing was published under the bad tag, so re-tagging
is safe — no images or chart were pushed to overwrite.

## Post-release

Optionally draft a **GitHub Release** from the tag, pasting the corresponding
`CHANGELOG.md` section as the release notes. The changelog link references
point at these release URLs.
