"""Native SkillScan rule specs.

Rule definitions intentionally live in Python constants so Phase 1 has no YAML
parser or external scanner dependency.
"""

from __future__ import annotations

from dataclasses import dataclass

from deerflow.skills.skillscan.models import FindingCategory, FindingConfidence, FindingSeverity


@dataclass(frozen=True)
class RuleSpec:
    rule_id: str
    category: FindingCategory
    severity: FindingSeverity
    confidence: FindingConfidence
    message: str
    remediation: str
    analyzer: str


_SPECS = [
    RuleSpec("package-path-traversal", "package", "CRITICAL", "HIGH", "Archive member path traverses outside the skill root.", "Remove parent-directory traversal from the package path.", "package"),
    RuleSpec("package-absolute-path", "package", "CRITICAL", "HIGH", "Archive member path is absolute.", "Use relative paths inside the skill archive.", "package"),
    RuleSpec("package-symlink", "package", "HIGH", "HIGH", "Package contains a symlink entry.", "Remove symlinks from the skill package.", "package"),
    RuleSpec("package-nested-skill-md", "package", "CRITICAL", "HIGH", "Package contains a nested SKILL.md file.", "Keep exactly one SKILL.md at the skill root.", "package"),
    RuleSpec("package-oversized-total", "package", "CRITICAL", "HIGH", "Package total uncompressed size exceeds the limit.", "Remove large files or split assets out of the skill package.", "package"),
    RuleSpec("package-oversized-file", "package", "CRITICAL", "HIGH", "Package contains a file that exceeds the per-file size limit.", "Remove or shrink the oversized file.", "package"),
    RuleSpec("package-executable-binary", "package", "CRITICAL", "HIGH", "Package contains an executable binary.", "Remove binary executables from the skill package.", "package"),
    RuleSpec("package-nested-archive", "package", "HIGH", "HIGH", "Package contains a nested archive file.", "Unpack and review nested archives before packaging the skill.", "package"),
    RuleSpec("package-hidden-sensitive-file", "package", "HIGH", "HIGH", "Package contains a hidden sensitive file.", "Remove hidden credential or package-manager config files.", "package"),
    RuleSpec("package-git-directory", "package", "MEDIUM", "HIGH", "Package contains a .git directory.", "Package only source files needed by the skill, excluding repository metadata.", "package"),
    RuleSpec("secret-private-key", "secret", "CRITICAL", "HIGH", "Private key material is embedded in skill content.", "Move private keys to a managed secret store and remove them from the skill.", "secrets"),
    RuleSpec("secret-cloud-token", "secret", "CRITICAL", "HIGH", "High-confidence cloud or API token is embedded in skill content.", "Move tokens to environment variables or a secret store.", "secrets"),
    RuleSpec("secret-env-assignment", "secret", "HIGH", "MEDIUM", "Secret-like assignment contains a non-placeholder value.", "Replace hardcoded credentials with documented runtime configuration.", "secrets"),
    RuleSpec("declaration-prompt-override", "declaration", "HIGH", "HIGH", "SKILL.md contains a prompt override phrase.", "Rephrase examples so they describe unsafe text instead of instructing the agent to follow it.", "declaration"),
    RuleSpec("declaration-sensitive-capability", "declaration", "HIGH", "MEDIUM", "SKILL.md declares a sensitive capability.", "Make the capability explicit, narrow, and justified, or remove it.", "declaration"),
    RuleSpec("declaration-sensitive-path", "declaration", "HIGH", "HIGH", "SKILL.md references sensitive host or credential paths.", "Remove references to sensitive host paths unless they are harmless documentation.", "declaration"),
    RuleSpec("declaration-external-endpoint", "declaration", "MEDIUM", "MEDIUM", "SKILL.md declares an external network endpoint.", "Document why the endpoint is needed and prefer HTTPS.", "declaration"),
    RuleSpec("python-dynamic-exec", "code", "CRITICAL", "HIGH", "Python dynamic code execution primitive is used in a skill file.", "Remove dynamic execution and replace it with explicit typed logic.", "python_ast"),
    RuleSpec("python-shell-exec", "code", "CRITICAL", "HIGH", "Python shell execution primitive is used in a skill file.", "Use subprocess with a fixed argument list and shell=False, or remove shell execution.", "python_ast"),
    RuleSpec("python-cloud-metadata-access", "network_resource", "CRITICAL", "HIGH", "Python code accesses a cloud metadata endpoint.", "Remove cloud metadata access from the skill.", "python_ast"),
    RuleSpec(
        "python-sensitive-exfil",
        "code",
        "CRITICAL",
        "MEDIUM",
        "Python code reads a sensitive path and uses an outbound network sink in the same file.",
        "Remove the sensitive read or network sink, and keep credential access outside skills.",
        "python_ast",
    ),
    RuleSpec(
        "python-env-dump-exfil",
        "code",
        "CRITICAL",
        "MEDIUM",
        "Python code reads the process environment in bulk and uses an outbound network sink in the same file.",
        "Avoid bulk environment reads and never send environment data over the network.",
        "python_ast",
    ),
    RuleSpec("python-reverse-shell", "code", "CRITICAL", "HIGH", "Python code matches a reverse-shell shape.", "Remove reverse-shell behavior from the skill.", "python_ast"),
    RuleSpec("python-dynamic-import", "code", "HIGH", "MEDIUM", "Python dynamically imports a non-literal module.", "Use explicit imports or a constrained allowlist.", "python_ast"),
    RuleSpec("python-subprocess", "code", "HIGH", "MEDIUM", "Python invokes subprocess without shell=True.", "Review subprocess usage and keep arguments fixed and minimal.", "python_ast"),
    RuleSpec("python-sensitive-path-read", "code", "HIGH", "MEDIUM", "Python reads a sensitive path.", "Remove sensitive host-path access from the skill.", "python_ast"),
    RuleSpec("python-unsafe-deserialization", "code", "MEDIUM", "MEDIUM", "Python uses unsafe deserialization.", "Use safe loaders or trusted typed formats.", "python_ast"),
    RuleSpec("shell-reverse-shell", "code", "CRITICAL", "HIGH", "Shell script contains a reverse-shell idiom.", "Remove reverse-shell behavior from the skill.", "shell_patterns"),
    RuleSpec("shell-sensitive-exfil", "code", "CRITICAL", "MEDIUM", "Shell script reads sensitive paths and sends data over the network.", "Remove sensitive reads or outbound transfer commands.", "shell_patterns"),
    RuleSpec("shell-curl-pipe-shell", "code", "HIGH", "HIGH", "Shell script pipes remote content into a shell.", "Download, verify, and execute reviewed code explicitly instead.", "shell_patterns"),
    RuleSpec("shell-destructive-command", "code", "HIGH", "HIGH", "Shell script contains an unmistakably destructive command.", "Remove destructive commands from skill scripts.", "shell_patterns"),
    RuleSpec("shell-env-dump", "code", "MEDIUM", "MEDIUM", "Shell script dumps the environment.", "Avoid bulk environment dumps in skills.", "shell_patterns"),
    RuleSpec("network-cloud-metadata", "network_resource", "CRITICAL", "HIGH", "Skill content references a cloud metadata service.", "Remove cloud metadata access from the skill.", "network_resource"),
    RuleSpec("resource-fork-bomb", "network_resource", "CRITICAL", "HIGH", "Skill content contains a fork-bomb pattern.", "Remove resource-exhaustion payloads.", "network_resource"),
    RuleSpec("network-cleartext-http", "network_resource", "MEDIUM", "MEDIUM", "Skill content references a non-local cleartext HTTP endpoint.", "Use HTTPS or document why cleartext local development is required.", "network_resource"),
    RuleSpec("network-local-http", "network_resource", "LOW", "MEDIUM", "Skill content references a local HTTP endpoint.", "Confirm the local endpoint is expected for this skill.", "network_resource"),
]

RULES: dict[str, RuleSpec] = {spec.rule_id: spec for spec in _SPECS}


def get_rule(rule_id: str) -> RuleSpec:
    return RULES[rule_id]
