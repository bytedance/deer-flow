#!/usr/bin/env python3
"""DeerFlow Interactive Setup Wizard.

Usage:
    uv run python scripts/setup_wizard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the scripts/ directory importable so wizard.* works
sys.path.insert(0, str(Path(__file__).resolve().parent))


def _is_interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def main() -> int:
    try:
        if not _is_interactive():
            print(
                "Non-interactive environment detected.\n"
                "Please edit config.yaml and .env directly, or run 'make setup' in a terminal."
            )
            return 1

        from wizard.ui import (
            ask_yes_no,
            bold,
            cyan,
            green,
            print_header,
            print_info,
            print_success,
            yellow,
        )
        from wizard.writer import write_config_yaml, write_env_file

        project_root = Path(__file__).resolve().parents[1]
        config_path = project_root / "config.yaml"
        env_path = project_root / ".env"

        print()
        print(bold("Welcome to DeerFlow Setup!"))
        print("This wizard will help you configure DeerFlow in a few minutes.")
        print()

        if config_path.exists():
            print(yellow("Existing configuration detected."))
            print()
            should_reconfigure = ask_yes_no("Do you want to reconfigure?", default=False)
            if not should_reconfigure:
                print()
                print_info("Keeping existing config. Run 'make doctor' to verify your setup.")
                return 0
            print()

        total_steps = 4

        from wizard.steps.llm import run_llm_step

        llm = run_llm_step(f"Step 1/{total_steps}")

        from wizard.steps.search import run_search_step

        search = run_search_step(f"Step 2/{total_steps}")
        search_provider = search.search_provider
        search_api_key = search.search_api_key
        fetch_provider = search.fetch_provider
        fetch_api_key = search.fetch_api_key

        from wizard.steps.execution import run_execution_step

        execution = run_execution_step(f"Step 3/{total_steps}")

        print_header(f"Step {total_steps}/{total_steps} · Writing configuration")

        write_config_yaml(
            config_path,
            provider_use=llm.provider.use,
            model_name=llm.model_name,
            display_name=f"{llm.provider.display_name} / {llm.model_name}",
            api_key_field=llm.provider.api_key_field,
            env_var=llm.provider.env_var,
            extra_model_config=llm.provider.extra_config or None,
            base_url=llm.base_url,
            search_use=search_provider.use if search_provider else None,
            search_tool_name=search_provider.tool_name if search_provider else "web_search",
            search_extra_config=search_provider.extra_config if search_provider else None,
            web_fetch_use=fetch_provider.use if fetch_provider else None,
            web_fetch_tool_name=fetch_provider.tool_name if fetch_provider else "web_fetch",
            web_fetch_extra_config=fetch_provider.extra_config if fetch_provider else None,
            sandbox_use=execution.sandbox_use,
            allow_host_bash=execution.allow_host_bash,
            include_bash_tool=execution.include_bash_tool,
            include_write_tools=execution.include_write_tools,
        )
        print_success(f"Config written to: {config_path.relative_to(project_root)}")

        if not env_path.exists():
            env_example = project_root / ".env.example"
            if env_example.exists():
                import shutil
                shutil.copyfile(env_example, env_path)

        env_pairs: dict[str, str] = {}
        if llm.api_key:
            env_pairs[llm.provider.env_var] = llm.api_key
        if search_api_key and search_provider and search_provider.env_var:
            env_pairs[search_provider.env_var] = search_api_key
        if fetch_api_key and fetch_provider and fetch_provider.env_var:
            env_pairs[fetch_provider.env_var] = fetch_api_key

        if env_pairs:
            write_env_file(env_path, env_pairs)
            print_success(f"API keys written to: {env_path.relative_to(project_root)}")

        frontend_env = project_root / "frontend" / ".env"
        frontend_env_example = project_root / "frontend" / ".env.example"
        if not frontend_env.exists() and frontend_env_example.exists():
            import shutil
            shutil.copyfile(frontend_env_example, frontend_env)
            print_success("frontend/.env created from example")

        print_header("Setup complete!")
        print(f"  {green('✓')} LLM:        {llm.provider.display_name} / {llm.model_name}")
        if search_provider:
            print(f"  {green('✓')} Web search: {search_provider.display_name}")
        else:
            print(f"  {'—':>3} Web search: not configured")
        if fetch_provider:
            print(f"  {green('✓')} Web fetch:  {fetch_provider.display_name}")
        else:
            print(f"  {'—':>3} Web fetch:  not configured")
        sandbox_label = "Local sandbox" if execution.sandbox_use.endswith("LocalSandboxProvider") else "Container sandbox"
        print(f"  {green('✓')} Execution:  {sandbox_label}")
        if execution.include_bash_tool:
            bash_label = "enabled"
            if execution.allow_host_bash:
                bash_label += " (host bash)"
            print(f"  {green('✓')} Bash:       {bash_label}")
        else:
            print(f"  {'—':>3} Bash:       disabled")
        if execution.include_write_tools:
            print(f"  {green('✓')} File write: enabled")
        else:
            print(f"  {'—':>3} File write: disabled")
        print()
        print("Next steps:")
        print(f"  {cyan('make install')}    # Install dependencies (first time only)")
        print(f"  {cyan('make dev')}        # Start DeerFlow")
        print()
        print(f"Run {cyan('make doctor')} to verify your setup at any time.")
        print()
        return 0
    except KeyboardInterrupt:
        print("\n\nSetup cancelled.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
