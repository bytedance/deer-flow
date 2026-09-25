"""Real multi-process harness for the shared MCP lifecycle protocol.

Each module in this package drives *genuinely independent processes*
(independent module globals, independent ``MCPSessionPool`` singletons) that
share one ``extensions_config.json`` file and one sidecar lock inode.
"""
