# Knowledge MCP Search Strategies

Query patterns for gathering organizational context during plugin customization.

## Finding Tool Names

**Source control:**
- Search: "GitHub" OR "GitLab" OR "Bitbucket"
- Search: "pull request" OR "merge request"
- Look for: repository links, CI/CD mentions

**Project management:**
- Search: "Asana" OR "Jira" OR "Linear" OR "Monday"
- Search: "sprint" AND "tickets"
- Look for: task links, project board mentions

**Chat:**
- Search: "Slack" OR "Teams" OR "Discord"
- Look for: channel mentions, integration discussions

**Analytics:**
- Search: "Datadog" OR "Grafana" OR "Mixpanel"
- Search: "monitoring" OR "observability"
- Look for: dashboard links, alert configurations

**Design:**
- Search: "Figma" OR "Sketch" OR "Adobe XD"
- Look for: design file links, handoff discussions

**CRM:**
- Search: "Salesforce" OR "HubSpot"
- Look for: deal mentions, customer record links

## Finding Organization Values

**Workspace/project IDs:**
- Search for existing integrations or bookmarked links
- Look for admin/setup documentation

**Team conventions:**
- Search: "story points" OR "estimation"
- Search: "workflow" OR "ticket status"
- Look for engineering process docs

**Channel/team names:**
- Search: "standup" OR "engineering" OR "releases"
- Look for channel naming patterns

## When Knowledge MCPs Are Unavailable

If no knowledge MCPs are configured, skip automatic discovery and proceed directly to AskUserQuestion for all categories. Note: AskUserQuestion always includes a Skip button and a free-text input box for custom answers, so do not include `None` or `Other` as options.
