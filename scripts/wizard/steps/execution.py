"""Step: execution mode and safety-related capabilities."""

from __future__ import annotations

from dataclasses import dataclass

from wizard.ui import ask_choice, ask_yes_no, print_header, print_info

LOCAL_SANDBOX = "deerflow.sandbox.local:LocalSandboxProvider"
CONTAINER_SANDBOX = "deerflow.community.aio_sandbox:AioSandboxProvider"


@dataclass
class ExecutionStepResult:
    sandbox_use: str
    include_bash_tool: bool
    include_write_tools: bool


def run_execution_step(step_label: str = "Step 3/4") -> ExecutionStepResult:
    print_header(f"{step_label} · Execution & Safety")
    print_info("Choose how much execution power DeerFlow should have in this workspace.")

    options = [
        "Local sandbox  —  workspace file tools",
        "Container sandbox  —  more isolated, requires Docker or Apple Container",
    ]
    sandbox_idx = ask_choice("Execution mode", options, default=0)
    sandbox_use = LOCAL_SANDBOX if sandbox_idx == 0 else CONTAINER_SANDBOX

    print()
    include_bash_tool = False
    if sandbox_use == CONTAINER_SANDBOX:
        include_bash_tool = ask_yes_no("Enable bash command execution?", default=False)
    else:
        print_info("Choose a container sandbox to use Bash.")

    include_write_tools = ask_yes_no(
        "Enable file write tools (write_file, str_replace)?", default=True
    )

    return ExecutionStepResult(
        sandbox_use=sandbox_use,
        include_bash_tool=include_bash_tool,
        include_write_tools=include_write_tools,
    )
