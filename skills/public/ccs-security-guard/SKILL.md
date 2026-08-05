# CCS Security Guard

Runtime command verification for DeerFlow agents using CCS (Credential & Compliance Standard).

## Description

This skill provides IETF-standardized security verification for all commands executed by DeerFlow agents. It intercepts shell commands and validates them against CCS security rules before execution.

## Capabilities

- **RCE Protection**: Block dangerous shell commands (rm -rf, chmod 777, fork bombs)
- **SSRF Prevention**: Block requests to internal/cloud metadata endpoints (169.254.169.254, localhost)
- **Credential Leak Detection**: Prevent exposure of secrets, API keys, and sensitive files
- **Sub-millisecond Overhead**: P50 ≈ 7.5μs in-process verification

## Usage

Import and use the `verify_command` function before executing any shell command:

```python
from scripts.verify import verify_command

# Verify before execution
allowed, reason = verify_command("rm -rf /")
if not allowed:
    raise SecurityError(f"Command blocked: {reason}")
```

## Standards & References

- **IETF Internet-Draft**: [draft-correctover-ccs-00](https://datatracker.ietf.org/doc/draft-correctover-ccs/)
- **PyPI Package**: [ccs-verifier v0.4.1](https://pypi.org/project/ccs-verifier/)
- **DOI**: 10.5281/zenodo.21783723

## Requirements

```bash
pip install ccs-verifier
```
