# Requirements Document

## Introduction

The DeerFlow project has an MCP (Model Context Protocol) integration issue where the `MultiServerMCPClient.get_tools()` method is being incorrectly called with `await`, causing the error "object list can't be used in 'await' expression". The MCP integration needs to be fixed to properly use the langchain-mcp-adapters library according to its documented patterns.

## Requirements

### Requirement 1

**User Story:** As a developer using DeerFlow, I want the MCP integration to work correctly so that I can use MCP tools in my research workflows without encountering runtime errors.

#### Acceptance Criteria

1. WHEN the system attempts to collect MCP tools THEN it SHALL use the correct async context manager pattern with `async with MultiServerMCPClient`
2. WHEN the MCP client is initialized THEN it SHALL properly handle the connection lifecycle using context managers
3. WHEN MCP tools are retrieved THEN the system SHALL not attempt to await non-async methods
4. WHEN MCP servers are configured THEN the system SHALL successfully connect and retrieve available tools

### Requirement 2

**User Story:** As a system administrator, I want proper error handling for MCP connections so that the system gracefully handles connection failures and provides meaningful error messages.

#### Acceptance Criteria

1. WHEN an MCP server connection fails THEN the system SHALL log appropriate error messages and continue operation
2. WHEN MCP tool collection fails THEN the system SHALL fall back to operating without MCP tools
3. WHEN invalid MCP server configurations are provided THEN the system SHALL validate and report configuration errors
4. WHEN network timeouts occur THEN the system SHALL handle them gracefully with appropriate retry logic

### Requirement 3

**User Story:** As a developer, I want the MCP integration to follow the documented patterns from langchain-mcp-adapters so that the code is maintainable and follows best practices.

#### Acceptance Criteria

1. WHEN using MultiServerMCPClient THEN the code SHALL use the `async with` context manager pattern
2. WHEN retrieving tools THEN the code SHALL call `client.get_tools()` without await inside the context manager
3. WHEN handling multiple MCP servers THEN the code SHALL properly manage concurrent connections
4. WHEN the MCP client is no longer needed THEN the context manager SHALL properly clean up resources