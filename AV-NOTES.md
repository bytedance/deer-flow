# AV Overlay -- Anomalous-Ventures fork of bytedance/deer-flow

This is a fork of [bytedance/deer-flow](https://github.com/bytedance/deer-flow), maintained by Anomalous-Ventures to integrate the agent harness into the **STAX** Kubernetes platform.

The upstream README documents what DeerFlow is and how to run it locally. This file documents what's **different** in this fork.

---

## What's different from upstream

| File | Purpose | Why we added it |
|------|---------|-----------------|
| `.github/workflows/build-images.yml` | Matrix build of `gateway` / `frontend` / `provisioner` images, pushed to `harbor.spooty.io` via the AV ARC pool. | Upstream's `container.yaml` only builds the all-in-one sandbox image; the agent components themselves are expected to run from `pip install`. We need pinned multi-arch images for K8s. |
| `.github/workflows/upstream-sync.yml` | Weekly cron + manual dispatch that fetches `bytedance/deer-flow:main`, cherry-picks AV-only commits on top, and opens a PR. | Keeps the fork rebaseable without manual `git fetch upstream` work. |
| `AV-NOTES.md` | This file. | Make the overlay self-documenting; new contributors don't have to grep workflows to understand the delta. |

Anything else (source tree, configs, upstream workflows like `e2e-tests.yml` / `lint-check.yml`) is unmodified from upstream and follows the upstream contributor guide.

## How this fork integrates with STAX

- **Pulumi stack:** [`pulumi/stacks/27-deer-flow`](https://github.com/Anomalous-Ventures/stax/tree/main/pulumi/stacks/27-deer-flow) in the `Anomalous-Ventures/stax` repo deploys the gateway / frontend / provisioner images built here into the `llm` namespace, with isolated sandbox pods in `deer-flow-sandboxes`.
- **Bootstrap state:** [`pulumi/stacks/27-deer-flow/BOOTSTRAP_STATUS.md`](https://github.com/Anomalous-Ventures/stax/blob/main/pulumi/stacks/27-deer-flow/BOOTSTRAP_STATUS.md) is the live source of truth for what's deployed, what's blocked, and what helper script unblocks each phase.
- **QA:** Sentinel TestPlan at [`Anomalous-Ventures/sentinel/plans/deer-flow.yaml`](https://github.com/Anomalous-Ventures/sentinel/blob/main/plans/deer-flow.yaml) is the merge gate (9 checkpoints, 4 hard-fail covering health/UI/gateway-API/echo-task, 5 soft-fail covering langfuse/sandbox/searxng/litellm/ollama).
- **Wiki page:** [.github wiki -- Deer-Flow](https://github.com/Anomalous-Ventures/.github/wiki/Deer-Flow) for the high-level overview.

## Upstream rebase policy

The `upstream-sync.yml` workflow runs every Monday 07:00 UTC and on manual dispatch. It opens a PR titled `chore: upstream sync YYYYMMDD` if the fork is behind. Review pattern:

1. Check the PR's diff for any breaking changes in components STAX depends on (gateway HTTP API, provisioner contract, frontend `data-testid` selectors used by Sentinel).
2. If selectors change, update `Anomalous-Ventures/sentinel/plans/deer-flow.yaml` in the **same** merge.
3. Merge fast -- keeping this fork close to upstream minimizes cherry-pick conflicts.

## Don't do here

- Don't add product features. Push those upstream first; we want a thin overlay.
- Don't add deployment manifests (Helm / Kustomize). All deploy logic lives in `Anomalous-Ventures/stax`.
- Don't add cloud / paid model providers. STAX is local-models-only via Ollama / vLLM / LiteLLM.
