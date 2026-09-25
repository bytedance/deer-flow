"""Real multi-process acceptance harness for the shared MCP lifecycle protocol.

Each module in this package exists so the acceptance matrix in
``docs/superpowers/specs/2026-09-25-mcp-shared-lifecycle-generation.md`` section 9
can be exercised with *genuinely independent processes* (independent module
globals, independent ``MCPSessionPool`` singletons) sharing one
``extensions_config.json`` file and one sidecar lock inode.
"""
