# Design Document

## Overview

This design addresses the MCP (Model Context Protocol) integration issue in DeerFlow where the `MultiServerMCPClient.get_tools()` method is being incorrectly called with `await`. The fix involves updating the code to use the proper async context manager pattern as documented in the langchain-mcp-adapters library.

## Architecture

The MCP integration follows a client-server architecture where:
- **MCP Servers**: External processes that provide tools and capabilities
- **MultiServerMCPClient**: The client that connects to multiple MCP servers
- **DeerFlow Agents**: Use the tools retrieved from MCP servers

The current issue is in the `collect_mcp_tools_info` function in `src/graph/nodes.py` where the client is not being used correctly.

## Components and Interfaces

### Current Problematic Implementation
```python
# INCORRECT - This causes the error
client = MultiServerMCPClient(mcp_servers)
tools = await client.get_tools()  # ERROR: get_tools() is not async
```

### Correct Implementation Pattern
```python
# CORRECT - Using async context manager
async with MultiServerMCPClient(mcp_servers) as client:
    tools = client.get_tools()  # No await needed inside context
```

### Key Components to Modify

1. **collect_mcp_tools_info function**: Main function that needs to be fixed
2. **_collect_tools_from_servers function**: Batch tool collection function
3. **_collect_tools_from_single_server function**: Single server tool collection
4. **Agent creation functions**: Functions that use MCP tools

## Data Models

### MCP Server Configuration
```python
{
    "server_name": {
        "transport": "stdio" | "sse" | "streamable_http",
        "command": str,  # For stdio transport
        "args": List[str],  # For stdio transport
        "url": str,  # For HTTP transports
        "env": Dict[str, str],  # Environment variables
        "enabled_tools": List[str]
    }
}
```

### Tool Information Structure
```python
{
    "name": str,
    "description": str,
    "server": str,
    "parameters": Dict[str, Any]
}
```

## Error Handling

### Connection Error Handling
- **MCPConnectionError**: For server connection failures
- **MCPTimeoutError**: For timeout scenarios
- **MCPParsingError**: For JSON parsing issues
- **MCPValidationError**: For tool validation failures

### Fallback Mechanisms
1. **Individual Server Failures**: Continue with other servers if one fails
2. **Complete MCP Failure**: Fall back to operating without MCP tools
3. **Tool Validation Failures**: Skip invalid tools, continue with valid ones

## Testing Strategy

### Unit Tests
1. Test correct async context manager usage
2. Test error handling for various failure scenarios
3. Test tool validation logic
4. Test fallback mechanisms

### Integration Tests
1. Test with actual MCP servers
2. Test multi-server scenarios
3. Test network failure scenarios
4. Test configuration validation

### Mock Testing
1. Mock MultiServerMCPClient for isolated testing
2. Mock network failures and timeouts
3. Mock invalid server responses

## Implementation Details

### Phase 1: Fix Core MCP Client Usage
- Update `collect_mcp_tools_info` to use async context manager
- Fix all instances of incorrect `await client.get_tools()` calls
- Ensure proper resource cleanup

### Phase 2: Improve Error Handling
- Add comprehensive error handling for connection failures
- Implement proper logging for debugging
- Add fallback mechanisms for graceful degradation

### Phase 3: Optimize Performance
- Implement connection pooling if needed
- Add caching for tool information
- Optimize concurrent server connections

## Configuration Changes

No configuration file changes are required. The fix is purely in the code implementation to use the correct API patterns.

## Dependencies

- **langchain-mcp-adapters**: Already present, using correct version
- **mcp**: Core MCP library (already present)
- No new dependencies required

## Migration Strategy

This is a bug fix that doesn't require migration. The changes are backward compatible and will immediately resolve the runtime error.

## Performance Considerations

- Using async context managers properly will improve resource management
- Connection pooling may be beneficial for high-frequency MCP tool usage
- Caching tool information can reduce repeated server queries

## Security Considerations

- MCP server connections should validate server certificates for HTTPS
- Environment variables containing secrets should be handled securely
- Tool execution should be sandboxed appropriately