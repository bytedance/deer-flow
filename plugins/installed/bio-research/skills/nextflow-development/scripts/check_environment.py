#!/usr/bin/env python3
"""
Pre-flight environment validation for nf-core pipelines.

Checks Docker, Nextflow, Java, system resources, and network connectivity.
Run this BEFORE attempting any pipeline execution.

Usage:
    python check_environment.py
    python check_environment.py --json
"""

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass, field, asdict
from typing import List, Optional


@dataclass
class CheckResult:
    """Result of a single environment check."""
    name: str
    passed: bool
    message: str
    details: Optional[str] = None
    fix: Optional[str] = None


@dataclass
class EnvironmentReport:
    """Complete environment validation report."""
    ready: bool
    checks: List[CheckResult] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)

    def to_dict(self):
        return {
            "ready": self.ready,
            "checks": [asdict(c) for c in self.checks],
            "recommendations": self.recommendations
        }


def check_docker() -> CheckResult:
    """Check Docker availability, daemon status, and permissions."""
    if not shutil.which("docker"):
        return CheckResult(
            name="Docker",
            passed=False,
            message="Docker not found in PATH",
            fix="Install Docker: https://docs.docker.com/get-docker/"
        )

    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=15
        )

        if result.returncode != 0:
            stderr_lower = result.stderr.lower()
            if "permission denied" in stderr_lower:
                return CheckResult(
                    name="Docker",
                    passed=False,
                    message="Docker permission denied",
                    details="Cannot connect to Docker daemon",
                    fix="sudo usermod -aG docker $USER && newgrp docker"
                )
            elif "cannot connect" in stderr_lower or "is the docker daemon running" in stderr_lower:
                return CheckResult(
                    name="Docker",
                    passed=False,
                    message="Docker daemon not running",
                    details=result.stderr[:200] if result.stderr else None,
                    fix="sudo systemctl start docker"
                )
            else:
                return CheckResult(
                    name="Docker",
                    passed=False,
                    message="Docker error",
                    details=result.stderr[:200] if result.stderr else None,
                    fix="Check Docker installation and daemon status"
                )

        return CheckResult(
            name="Docker",
            passed=True,
            message="Docker is available and running"
        )

    except subprocess.TimeoutExpired:
        return CheckResult(
            name="Docker",
            passed=False,
            message="Docker command timed out",
            fix="Check Docker daemon status: sudo systemctl status docker"
        )
    except Exception as e:
        return CheckResult(
            name="Docker",
            passed=False,
            message=f"Docker check failed: {str(e)}"
        )


def check_nextflow() -> CheckResult:
    """Check Nextflow installation and version (requires >= 23.04)."""
    if not shutil.which("nextflow"):
        return CheckResult(
            name="Nextflow",
            passed=False,
            message="Nextflow not found in PATH",
            fix="curl -s https://get.nextflow.io | bash && mv nextflow ~/bin/ && export PATH=$HOME/bin:$PATH"
        )

    try:
        result = subprocess.run(
            ["nextflow", "-version"],
            capture_output=True,
            text=True,
            timeout=30
        )

        output = result.stdout + result.stderr
        version_line = output.strip().split('\n')[0] if output else ""

        import re
        match = re.search(r'(\d+)\.(\d+)\.(\d+)', version_line)

        if match:
            major, minor, patch = int(match.group(1)), int(match.group(2)), int(match.group(3))
            version_str = f"{major}.{minor}.{patch}"

            # Require version >= 23.04
            if major > 23 or (major == 23 and minor >= 4):
                return CheckResult(
                    name="Nextflow",
                    passed=True,
                    message=f"Nextflow {version_str} installed",
                    details=version_line
                )
            else:
                return CheckResult(
                    name="Nextflow",
                    passed=False,
                    message=f"Nextflow {version_str} is outdated (requires >= 23.04)",
                    details=version_line,
                    fix="nextflow self-update"
                )

        return CheckResult(
            name="Nextflow",
            passed=True,
            message="Nextflow installed (version unknown)",
            details=version_line
        )

    except subprocess.TimeoutExpired:
        return CheckResult(
            name="Nextflow",
            passed=False,
            message="Nextflow command timed out",
            fix="Check Nextflow installation"
        )
    except Exception as e:
        return CheckResult(
            name="Nextflow",
            passed=False,
            message=f"Nextflow check failed: {str(e)}"
        )


def check_java() -> CheckResult:
    """Check Java version (requires >= 11)."""
    if not shutil.which("java"):
        return CheckResult(
            name="Java",
            passed=False,
            message="Java not found in PATH",
            fix="Install Java 11+: sudo apt install openjdk-11-jdk"
        )

    try:
        result = subprocess.run(
            ["java", "-version"],
            capture_output=True,
            text=True,
            timeout=10
        )

        # Java version is typically in stderr
        output = result.stderr or result.stdout
        import re
        match = re.search(r'version "(\d+)', output)

        if match:
            version = int(match.group(1))
            version_line = output.strip().split('\n')[0]

            if version >= 11:
                return CheckResult(
                    name="Java",
                    passed=True,
                    message=f"Java {version} installed",
                    details=version_line
                )
            else:
                return CheckResult(
                    name="Java",
                    passed=False,
                    message=f"Java {version} is too old (requires >= 11)",
                    details=version_line,
                    fix="Install Java 11+: sudo apt install openjdk-11-jdk"
                )

        return CheckResult(
            name="Java",
            passed=True,
            message="Java installed",
            details=output.strip().split('\n')[0] if output else None
        )

    except Exception as e:
        return CheckResult(
            name="Java",
            passed=False,
            message=f"Java check failed: {str(e)}"
        )


def check_resources() -> CheckResult:
    """Check system resources (CPU, memory, disk)."""
    try:
        # CPU cores
        cpu_count = os.cpu_count() or 1

        # Memory
        mem_gb = 0
        try:
            # Linux: read from /proc/meminfo
            with open('/proc/meminfo', 'r') as f:
                for line in f:
                    if line.startswith('MemTotal:'):
                        mem_kb = int(line.split()[1])
                        mem_gb = mem_kb / (1024 * 1024)
                        break
        except (FileNotFoundError, PermissionError):
            # macOS: use sysctl
            try:
                result = subprocess.run(
                    ['sysctl', '-n', 'hw.memsize'],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    mem_gb = int(result.stdout.strip()) / (1024**3)
            except:
                pass

        # Disk space (current directory)
        disk_gb = 0
        try:
            statvfs = os.statvfs('.')
            disk_gb = (statvfs.f_frsize * statvfs.f_bavail) / (1024**3)
        except:
            pass

        details = f"CPUs: {cpu_count}, Memory: {mem_gb:.1f}GB, Disk: {disk_gb:.1f}GB available"

        # Check minimums
        warnings = []
        if cpu_count < 4:
            warnings.append(f"Low CPU count ({cpu_count}). Consider --max_cpus {cpu_count}")
        if 0 < mem_gb < 8:
            warnings.append(f"Low memory ({mem_gb:.1f}GB). Use --max_memory '{int(mem_gb)}GB'")
        if 0 < disk_gb < 50:
            warnings.append(f"Low disk space ({disk_gb:.1f}GB). Pipelines need ~100GB for human data")

        if warnings:
            return CheckResult(
                name="Resources",
                passed=True,
                message="Resources available (with warnings)",
                details=details,
                fix="; ".join(warnings)
            )

        return CheckResult(
            name="Resources",
            passed=True,
            message="Sufficient resources available",
            details=details
        )

    except Exception as e:
        return CheckResult(
            name="Resources",
            passed=True,  # Don't fail on resource check errors
            message=f"Could not fully check resources: {str(e)}"
        )


def check_network() -> CheckResult:
    """Check network connectivity to Docker Hub and nf-core."""
    try:
        import urllib.request

        # User-Agent header to avoid 403 from sites that block default Python agent
        headers = {'User-Agent': 'nf-core-helper/1.0'}

        # Try Docker Hub
        try:
            req = urllib.request.Request("https://hub.docker.com", headers=headers)
            urllib.request.urlopen(req, timeout=10)
            docker_hub_ok = True
        except:
            docker_hub_ok = False

        # Try nf-core (for pipeline downloads)
        try:
            req = urllib.request.Request("https://nf-co.re", headers=headers)
            urllib.request.urlopen(req, timeout=10)
            nfcore_ok = True
        except:
            nfcore_ok = False

        if docker_hub_ok and nfcore_ok:
            return CheckResult(
                name="Network",
                passed=True,
                message="Network connectivity OK (Docker Hub & nf-core reachable)"
            )
        elif docker_hub_ok:
            return CheckResult(
                name="Network",
                passed=True,
                message="Docker Hub reachable (nf-core.re not reachable)",
                details="Pipeline downloads may still work via GitHub"
            )
        else:
            return CheckResult(
                name="Network",
                passed=False,
                message="Cannot reach Docker Hub",
                fix="Check network connection. Containers require Docker Hub access."
            )

    except Exception as e:
        return CheckResult(
            name="Network",
            passed=False,
            message=f"Network check failed: {str(e)}",
            fix="Check network connection and proxy settings"
        )


def run_all_checks() -> EnvironmentReport:
    """Run all environment checks and return comprehensive report."""
    checks = [
        check_docker(),
        check_nextflow(),
        check_java(),
        check_resources(),
        check_network(),
    ]

    # Critical checks that must pass
    critical_checks = ["Docker", "Nextflow", "Java"]
    ready = all(c.passed for c in checks if c.name in critical_checks)

    # Build recommendations
    recommendations = []
    for check in checks:
        if not check.passed and check.fix:
            recommendations.append(f"{check.name}: {check.fix}")
        elif check.passed and check.fix:  # Warnings
            recommendations.append(f"{check.name} (warning): {check.fix}")

    return EnvironmentReport(
        ready=ready,
        checks=checks,
        recommendations=recommendations
    )


def print_report(report: EnvironmentReport):
    """Print human-readable report to stdout."""
    print("\n" + "=" * 50)
    print("  nf-core Environment Check")
    print("=" * 50 + "\n")

    for check in report.checks:
        status = "\033[92m[PASS]\033[0m" if check.passed else "\033[91m[FAIL]\033[0m"
        print(f"{status} {check.name}: {check.message}")

        if check.details:
            print(f"       {check.details}")

        if not check.passed and check.fix:
            print(f"       \033[93mFix:\033[0m {check.fix}")
        elif check.passed and check.fix:  # Warning
            print(f"       \033[93mWarning:\033[0m {check.fix}")

    print()
    if report.ready:
        print("\033[92m✓ Environment is READY for nf-core pipelines.\033[0m")
    else:
        print("\033[91m✗ Environment is NOT READY. Please address the issues above.\033[0m")

    if report.recommendations:
        print("\n--- Recommendations ---")
        for i, rec in enumerate(report.recommendations, 1):
            print(f"  {i}. {rec}")

    print()


def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Check environment for nf-core pipeline execution",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python check_environment.py           # Human-readable output
    python check_environment.py --json    # JSON output for parsing
        """
    )
    parser.add_argument("--json", action="store_true",
                        help="Output results as JSON")

    args = parser.parse_args()

    report = run_all_checks()

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        print_report(report)

    sys.exit(0 if report.ready else 1)


if __name__ == "__main__":
    main()
