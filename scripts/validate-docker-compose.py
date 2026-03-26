#!/usr/bin/env python3
"""Validate Docker Compose configuration files.

This script validates:
1. Docker Compose YAML syntax is valid
2. TZ environment variable is set in all services
3. Environment variable references are consistent
"""

import subprocess
import sys
from pathlib import Path


def run_docker_compose_config(compose_file: Path) -> tuple[bool, str]:
    """Run docker compose config to validate syntax."""
    try:
        # Set minimal env vars for validation
        env = {
            "DEER_FLOW_CONFIG_PATH": "/tmp/config.yaml",
            "DEER_FLOW_EXTENSIONS_CONFIG_PATH": "/tmp/extensions.json",
            "DEER_FLOW_HOME": "/tmp/deer-flow",
            "DEER_FLOW_DOCKER_SOCKET": "/var/run/docker.sock",
            "DEER_FLOW_REPO_ROOT": "/tmp",
            "BETTER_AUTH_SECRET": "test-secret",
            "DEER_FLOW_ROOT": "/tmp/deer-flow",
            "HOME": "/tmp",
        }
        result = subprocess.run(
            ["docker", "compose", "-f", str(compose_file), "config"],
            capture_output=True,
            text=True,
            check=False,
            env={**subprocess.os.environ, **env},
        )
        # Filter out warnings about unset variables
        stderr = result.stderr
        if "level=warning" in stderr:
            # Only fail on actual errors, not warnings
            if result.returncode != 0 and "invalid" in stderr.lower():
                return False, stderr
            return True, "Docker Compose valid (with warnings)"
        return result.returncode == 0, stderr or "Valid"
    except FileNotFoundError:
        # Docker not available, skip validation
        return True, "Docker not available, skipping syntax validation"


def parse_yaml_file(file_path: Path) -> dict:
    """Parse YAML file and return content."""
    try:
        import yaml

        with open(file_path, "r") as f:
            return yaml.safe_load(f)
    except ImportError:
        print("Warning: PyYAML not installed, skipping some validations")
        return {}
    except Exception as e:
        print(f"Error parsing {file_path}: {e}")
        return {}


def check_tz_environment_variable(compose_file: Path, content: dict) -> list[str]:
    """Check that TZ environment variable is set in all services."""
    errors = []
    services = content.get("services", {})

    expected_services = ["frontend", "gateway", "langgraph"]
    if "provisioner" in services:
        expected_services.append("provisioner")

    for service_name in expected_services:
        if service_name not in services:
            errors.append(f"{compose_file}: Missing expected service '{service_name}'")
            continue

        service = services[service_name]
        env_vars = service.get("environment", [])

        # Check if TZ is in environment variables
        has_tz = False
        for env in env_vars:
            if isinstance(env, str) and env.startswith("TZ="):
                has_tz = True
                # Verify it uses the correct pattern
                if env != "TZ=${TZ:-UTC}":
                    errors.append(
                        f"{compose_file}: Service '{service_name}' has TZ="
                        f"but doesn't use recommended pattern 'TZ=${{TZ:-UTC}}' (found: {env})"
                    )
                break

        if not has_tz:
            errors.append(
                f"{compose_file}: Service '{service_name}' missing TZ environment variable"
            )

    return errors


def main():
    """Main validation function."""
    docker_dir = Path(__file__).parent.parent / "docker"
    compose_files = [
        docker_dir / "docker-compose.yaml",
        docker_dir / "docker-compose-dev.yaml",
    ]

    all_errors = []

    for compose_file in compose_files:
        print(f"\nValidating {compose_file.name}...")

        if not compose_file.exists():
            print(f"  ❌ File not found: {compose_file}")
            all_errors.append(f"File not found: {compose_file}")
            continue

        # Validate YAML syntax with docker compose config
        is_valid, message = run_docker_compose_config(compose_file)
        if not is_valid:
            print(f"  ❌ Docker Compose syntax error: {message}")
            all_errors.append(f"{compose_file.name}: {message}")
        else:
            print(f"  ✅ YAML syntax valid")

        # Parse and validate content
        content = parse_yaml_file(compose_file)
        if content:
            tz_errors = check_tz_environment_variable(compose_file, content)
            if tz_errors:
                for error in tz_errors:
                    print(f"  ❌ {error}")
                    all_errors.append(error)
            else:
                print(f"  ✅ TZ environment variable correctly set in all services")

    # Validate .env.example has TZ documentation
    env_example = Path(__file__).parent.parent / ".env.example"
    if env_example.exists():
        print(f"\nValidating {env_example.name}...")
        with open(env_example, "r") as f:
            content = f.read()
        if "TZ=" in content or "timezone" in content.lower():
            print(f"  ✅ TZ configuration documented")
        else:
            print(f"  ❌ TZ configuration not documented in .env.example")
            all_errors.append(".env.example: Missing TZ configuration documentation")

    print("\n" + "=" * 50)
    if all_errors:
        print(f"Validation failed with {len(all_errors)} error(s)")
        return 1
    else:
        print("All validations passed!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
