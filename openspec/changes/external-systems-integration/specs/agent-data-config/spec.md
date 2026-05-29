## ADDED Requirements

### Requirement: Agent config.yaml data_tools declaration

Agent `config.yaml` SHALL support an optional `data_tools` field. This field SHALL declare which integration capability tools the Agent uses. The field SHALL be a list of tool names matching the tools defined in `deerflow/integrations/tools/`.

```yaml
name: monitoring-analysis
tool_groups:
  - monitoring:pro
skills:
  - data-analyst
data_tools:
  - monitoring_get_trend
  - monitoring_get_waveform
  - monitoring_get_alarm_history
  - health_get_assessment
  - asset_get_catalog
```

When `data_tools` is absent or empty, the Agent SHALL NOT receive any integration tools and SHALL NOT have a `<data_sources>` section injected into its System Prompt. This preserves backward compatibility for all existing Agents.

A wildcard value `"*"` SHALL mean "all available integration tools".

#### Scenario: Agent declares specific data_tools

- **WHEN** `monitoring-analysis/config.yaml` has `data_tools: [monitoring_get_trend, health_get_assessment]`
- **THEN** only those two tools are injected into the Agent's tool set
- **THEN** the `<data_sources>` prompt section only includes capabilities served by those tools

#### Scenario: Agent declares wildcard data_tools

- **WHEN** an Agent has `data_tools: ["*"]`
- **THEN** all registered integration tools are injected
- **THEN** the full `<data_sources>` prompt section is generated

#### Scenario: Agent omits data_tools

- **WHEN** `ai-report--daily/config.yaml` does not have a `data_tools` field
- **THEN** the Agent's tool set is unchanged (no integration tools added)
- **THEN** no `<data_sources>` section appears in the System Prompt
- **THEN** the Agent works exactly as before this change

#### Scenario: Agent declares empty data_tools

- **WHEN** an Agent has `data_tools: []`
- **THEN** behavior is identical to omitting the field entirely

#### Scenario: data_tools references non-existent tool

- **WHEN** `data_tools` includes `"nonexistent_tool"`
- **THEN** the unknown name is silently ignored (no error, no tool injected)
- **THEN** a `WARNING` is logged: `"Agent {name}: data_tools references unknown tool 'nonexistent_tool'"`

### Requirement: Integration tool injection filtered by data_tools

The `get_available_tools()` function in `deerflow/tools/tools.py` SHALL selectively inject integration tools based on the Agent's `data_tools` declaration. Tools SHALL NOT be globally registered for all Agents.

The injection SHALL occur after built-in tools and before MCP tools in the assembly order. Name-based deduplication with existing tools SHALL apply.

#### Scenario: Inject tools for Agent with data_tools

- **WHEN** `get_available_tools()` is called for an Agent with `data_tools: [monitoring_get_trend, health_get_assessment]`
- **THEN** the returned tool list includes those two tools
- **THEN** the returned tool list does NOT include `asset_get_catalog` or other undeclared tools

#### Scenario: No injection for Agent without data_tools

- **WHEN** `get_available_tools()` is called for an Agent without `data_tools`
- **THEN** no integration tools appear in the returned list

#### Scenario: Tool name conflict with existing tool

- **WHEN** an integration tool name matches an existing built-in tool name
- **THEN** the existing tool takes precedence
- **THEN** a `WARNING` is logged

#### Scenario: No integrations configured globally

- **WHEN** `integrations.enabled` is `false` or no systems are configured
- **THEN** no integration tools are injected regardless of Agent's `data_tools` declaration

### Requirement: System prompt data_sources section scoped by data_tools

The system SHALL inject a `<data_sources>` section into the Agent's system prompt via `apply_prompt_template()` in `deerflow/agents/lead_agent/prompt.py`. The section SHALL describe available integration capabilities scoped to the Agent's `data_tools` declaration.

A new `{data_sources_section}` placeholder SHALL be added to `SYSTEM_PROMPT_TEMPLATE` between `{skills_section}` and `{deferred_tools_section}`.

The scope SHALL be determined as follows:

- Agent has `data_tools: [tool_a, tool_b]` → prompt section includes only capabilities those tools access
- Agent has `data_tools: ["*"]` → prompt section includes all capabilities from all enabled systems
- Agent has no `data_tools` → no `<data_sources>` section injected (empty string)

The generated section SHALL include:

```xml
<data_sources>
你可以查询以下数据源来获取设备相关信息：

**{system_display_name}** ({system_type})
- {capability_key}: {description}
  → 适用于: {usage_hints}
...

**跨系统关联提示:**
- {entity_link_hints}

**使用方式:**
- {tool_descriptions}
</data_sources>
```

#### Scenario: Prompt scoped to Agent's data_tools

- **WHEN** Agent declares `data_tools: [monitoring_get_trend]`
- **THEN** the `<data_sources>` section only mentions `monitoring.trend` capability
- **THEN** other capabilities (e.g. `health.assessment`) are NOT mentioned

#### Scenario: Prompt with wildcard data_tools

- **WHEN** Agent declares `data_tools: ["*"]`
- **THEN** the `<data_sources>` section includes all capabilities from all enabled systems
- **THEN** cross-system entity link hints are included

#### Scenario: No prompt section for Agent without data_tools

- **WHEN** Agent has no `data_tools` field
- **THEN** `apply_prompt_template()` output does NOT contain `<data_sources>` tags

#### Scenario: Prompt section respects token budget

- **WHEN** full catalog exceeds `max_tokens=800`
- **THEN** the generated section is truncated to fit within budget
- **THEN** higher-reliability capabilities are preserved
