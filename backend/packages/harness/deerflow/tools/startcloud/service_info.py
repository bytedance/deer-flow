"""Service catalog and comparison for the Start-Cloud marketplace."""

from langchain_core.tools import tool

CATALOG = {
    "vaultwarden": {
        "name": "Vaultwarden",
        "category": "Password Manager",
        "replaces": "Bitwarden, 1Password, LastPass",
        "savings": "1Password: $7.99/user/mo → Free (self-hosted)",
        "port": 8003,
        "url": "https://vault.david.sprintsolo.dev",
        "features": [
            "Password vault with browser extension",
            "Secure password generation",
            "Organization sharing",
            "Two-factor authentication (TOTP, WebAuthn)",
            "Emergency access",
            "Secure notes & attachments",
        ],
        "sso": True,
        "status": "installed",
    },
    "teable": {
        "name": "Teable",
        "category": "Spreadsheet / Database",
        "replaces": "Airtable, Google Sheets (advanced), NocoDB",
        "savings": "Airtable: $20/user/mo → Free (self-hosted)",
        "port": 8002,
        "url": "https://teable.david.sprintsolo.dev",
        "features": [
            "Airtable-like spreadsheet interface on PostgreSQL",
            "Multiple views (Grid, Gallery, Kanban, Form, Calendar)",
            "Full REST API (48+ modules, OpenAPI spec)",
            "OIDC SSO (free, Keycloak compatible)",
            "Direct PostgreSQL access via credentials API",
            "Automation with HTTP webhooks",
            "20 field types (Formula, Rollup, Link, etc.)",
            "OAuth 2.0 + Personal Access Tokens for API",
        ],
        "sso": True,
        "status": "installed",
    },
    "twenty": {
        "name": "Twenty CRM",
        "category": "CRM",
        "replaces": "Salesforce, HubSpot, Pipedrive",
        "savings": "HubSpot Starter: $20/user/mo → Free (self-hosted)",
        "port": 3002,
        "url": "https://crm.david.sprintsolo.dev",
        "features": [
            "Contact & company management",
            "Deal pipeline",
            "Email integration",
            "Activity timeline",
            "Custom objects & fields",
            "GraphQL API",
        ],
        "sso": True,
        "status": "installed",
    },
    "outline": {
        "name": "Outline",
        "category": "Wiki / Knowledge Base",
        "replaces": "Notion, Confluence",
        "savings": "Notion: $10/user/mo → Free (self-hosted)",
        "features": [
            "Markdown editor",
            "Team knowledge base",
            "Document templates",
            "Search & collections",
            "Integrations (Slack, etc.)",
        ],
        "sso": True,
        "status": "available",
    },
    "plane": {
        "name": "Plane",
        "category": "Project Management",
        "replaces": "Jira, Linear, Asana",
        "savings": "Linear: $10/user/mo → Free (self-hosted)",
        "features": [
            "Issue tracking",
            "Sprints & cycles",
            "Roadmaps",
            "Custom workflows",
            "Time tracking",
        ],
        "sso": True,
        "status": "available",
    },
    "mattermost": {
        "name": "Mattermost",
        "category": "Team Chat",
        "replaces": "Slack, Microsoft Teams",
        "savings": "Slack Pro: $8.75/user/mo → Free (self-hosted)",
        "features": [
            "Channels & direct messages",
            "File sharing",
            "Voice & video calls",
            "Integrations & bots",
            "Thread support",
        ],
        "sso": True,
        "status": "available",
    },
}


@tool
def service_info(query: str = "") -> str:
    """Get information about available open-source services in the Start-Cloud marketplace.

    Args:
        query: Optional search query. Can be:
               - A service name (e.g., 'vaultwarden', 'nocodb')
               - A category (e.g., 'CRM', 'chat', 'password')
               - 'compare' to see cost savings vs SaaS
               - 'installed' to see currently running services
               - 'available' to see services that can be added
               - Empty string for full catalog overview
    """
    query_lower = query.lower().strip()

    # Specific service lookup
    if query_lower in CATALOG:
        svc = CATALOG[query_lower]
        lines = [
            f"=== {svc['name']} ===",
            f"Category: {svc['category']}",
            f"Replaces: {svc['replaces']}",
            f"Cost savings: {svc['savings']}",
            f"SSO Support: {'Yes' if svc['sso'] else 'No'}",
            f"Status: {svc['status'].upper()}",
        ]
        if "url" in svc:
            lines.append(f"URL: {svc['url']}")
        lines.append("\nFeatures:")
        for f in svc["features"]:
            lines.append(f"  • {f}")
        return "\n".join(lines)

    # Cost comparison
    if query_lower == "compare":
        lines = ["=== SaaS Cost Comparison (30-person team) ===\n"]
        for key, svc in CATALOG.items():
            if svc["status"] == "installed":
                lines.append(f"{svc['name']} ({svc['category']})")
                lines.append(f"  Replaces: {svc['replaces']}")
                lines.append(f"  Savings: {svc['savings']}")
                lines.append("")
        lines.append("Start-Cloud: Server hosting ~$20-50/mo (all services combined)")
        lines.append("vs SaaS total: ~$1,000+/mo for 30 users")
        return "\n".join(lines)

    # Filter by status
    if query_lower in ("installed", "available"):
        services = {k: v for k, v in CATALOG.items() if v["status"] == query_lower}
        lines = [f"=== {query_lower.upper()} Services ===\n"]
        for key, svc in services.items():
            lines.append(f"{'🟢' if svc['status'] == 'installed' else '⚪'} {svc['name']} — {svc['category']}")
            lines.append(f"   Replaces: {svc['replaces']}")
            if "url" in svc:
                lines.append(f"   URL: {svc['url']}")
            lines.append("")
        return "\n".join(lines)

    # Category search
    for key, svc in CATALOG.items():
        if query_lower and query_lower in svc["category"].lower():
            return service_info.invoke(key)

    # Full catalog
    lines = ["=== Start-Cloud Service Catalog ===\n"]
    lines.append("INSTALLED:")
    for key, svc in CATALOG.items():
        if svc["status"] == "installed":
            lines.append(f"  🟢 {svc['name']} — {svc['category']} (port {svc['port']})")
    lines.append("\nAVAILABLE (can be added):")
    for key, svc in CATALOG.items():
        if svc["status"] == "available":
            lines.append(f"  ⚪ {svc['name']} — {svc['category']}")
    lines.append("\nUse service_info('service_name') for details on any service.")
    lines.append("Use service_info('compare') for SaaS cost comparison.")
    return "\n".join(lines)
