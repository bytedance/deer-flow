---
name: xproof
description: Certify any agent output on the MultiversX blockchain for proof-of-existence and accountability. Use when the agent produces a report, analysis, research finding, or any output that needs to be independently verifiable. Creates an immutable, timestamped record using the xProof 4W framework (Who, What, When, Why). Requires only curl and sha256sum.
---

# xProof — Prove Your Work On-Chain

## Overview

This skill certifies agent outputs on the [MultiversX](https://multiversx.com) blockchain using [xProof](https://xproof.app). Every certification creates an immutable, publicly verifiable proof-of-existence — anchored on-chain, not stored by xProof.

Use this skill whenever the agent produces an output that matters: a research report, a data analysis, a recommendation, a decision. The blockchain proof means anyone can verify *what* was produced, *when* it was produced, and *who* produced it — without trusting the agent.

## When to Use This Skill

- After generating a research report, analysis, or summary
- Before delivering a final output to a user or downstream system
- When the agent needs to prove it produced something at a specific time
- When accountability or auditability is required
- When another agent or human needs to verify the agent's output independently

## How It Works

1. Hash the output content with SHA-256 (the content never leaves the agent)
2. Submit the hash to the xProof API with 4W metadata
3. xProof anchors the hash on MultiversX mainnet
4. A permanent `proof_id` and `transaction_hash` are returned
5. Anyone can verify the proof independently at `https://xproof.app/proof/<proof_id>`

## Setup

Get a free API key (10 certifications included):

```bash
curl -s -X POST https://xproof.app/api/agent/register \
  -H "Content-Type: application/json" \
  -d '{"agent_name": "my-deerflow-agent"}' | jq .
```

Save the `api_key` from the response. Set it as an environment variable:

```bash
export XPROOF_API_KEY="pm_..."
```

## Certify an Output

### Using curl and sha256sum (zero dependencies)

```bash
# 1. Hash the content
CONTENT="Q3 revenue analysis: $4.2M, up 15% YoY"
HASH=$(echo -n "$CONTENT" | sha256sum | cut -d' ' -f1)

# 2. Certify on-chain
curl -s -X POST https://xproof.app/api/proof \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $XPROOF_API_KEY" \
  -d "{
    \"file_hash\": \"$HASH\",
    \"file_name\": \"q3-analysis.json\",
    \"author\": \"deerflow-agent\",
    \"metadata\": {
      \"who\": \"deerflow-agent\",
      \"what\": \"$HASH\",
      \"when\": \"$(date -u +%Y-%m-%dT%H:%M:%S.000Z)\",
      \"why\": \"Quarterly earnings certification\",
      \"framework\": \"deerflow\"
    }
  }" | jq .
```

Response:
```json
{
  "id": "proof-abc123",
  "fileHash": "a1b2c3...",
  "transactionHash": "0xdeadbeef...",
  "verifyUrl": "https://xproof.app/proof/proof-abc123",
  "explorerUrl": "https://explorer.multiversx.com/transactions/0xdeadbeef..."
}
```

### Using the Python SDK

```bash
pip install xproof
```

```python
from xproof.integrations.deerflow import XProofDeerFlowSkill

skill = XProofDeerFlowSkill(api_key="pm_...")

# Plain text
result = skill._run("My research findings")

# With metadata
result = skill._run('{"content": "Q3 analysis", "why": "Quarterly review"}')
```

### Using the LangChain callback (DeerFlow uses LangGraph internally)

```python
from xproof.integrations.langchain import XProofCallbackHandler

handler = XProofCallbackHandler(api_key="pm_...")
# Pass to your LangGraph/LangChain config — all LLM calls and tool invocations auto-certify
```

## Batch Certification

Certify up to 50 outputs in a single API call:

```bash
curl -s -X POST https://xproof.app/api/batch \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $XPROOF_API_KEY" \
  -d '{
    "files": [
      {"file_hash": "abc123...", "file_name": "report-1.json"},
      {"file_hash": "def456...", "file_name": "report-2.json"}
    ]
  }' | jq .
```

## Verify a Proof

Anyone can verify a proof — no API key needed:

```bash
curl -s https://xproof.app/api/proof/<proof_id> | jq .
```

Or visit: `https://xproof.app/proof/<proof_id>`

## The 4W Framework

Every certification answers four questions:

| Question | Field | Description |
|----------|-------|-------------|
| **WHO** | `who` | Which agent produced the output |
| **WHAT** | `what` | SHA-256 hash of the content (the content itself stays private) |
| **WHEN** | `when` | Blockchain timestamp — written by the chain, not the agent |
| **WHY** | `why` | Context: why was this output produced |

## Payment Options

- **API key**: Get 10 free certifications via `/api/agent/register`. Purchase more at $0.05/cert.
- **x402**: Pay per-request with USDC on Base — no account needed. Machine-native.

## Links

- [xProof website](https://xproof.app)
- [API documentation](https://xproof.app/docs)
- [MCP endpoint](https://xproof.app/mcp)
- [Python SDK on PyPI](https://pypi.org/project/xproof/)
- [npm SDK](https://www.npmjs.com/package/@xproof/xproof)
- [GitHub](https://github.com/jasonxkensei/xproof)
