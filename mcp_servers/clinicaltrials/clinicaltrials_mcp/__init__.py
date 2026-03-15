"""ClinicalTrials.gov MCP Server.

Exposes ClinicalTrials.gov API v2 (study search, details, statistics) via MCP tools.
No authentication required. Rate limit: ~50 requests/minute per IP.
"""

import json
import sys

from mcp.server.fastmcp import FastMCP

from clinicaltrials_mcp.api_client import ClinicalTrialsAPIError, ClinicalTrialsClient

mcp = FastMCP("clinicaltrials")
client = ClinicalTrialsClient()


@mcp.tool()
async def clinicaltrials_search_studies(
    condition: str | None = None,
    intervention: str | None = None,
    term: str | None = None,
    titles: str | None = None,
    outcome: str | None = None,
    sponsor: str | None = None,
    lead: str | None = None,
    patient: str | None = None,
    location: str | None = None,
    study_id: str | None = None,
    overall_status: str | None = None,
    phase: str | None = None,
    study_type: str | None = None,
    geo: str | None = None,
    advanced_filter: str | None = None,
    sort: str | None = None,
    page_size: int = 20,
    page_token: str | None = None,
) -> str:
    """Search ClinicalTrials.gov for clinical studies matching criteria.

    At least one search parameter should be provided for meaningful results.
    The database contains 500,000+ studies. No authentication required.

    Args:
        condition: Disease or condition (e.g., "breast cancer", "diabetes type 2")
        intervention: Drug, device, or procedure (e.g., "pembrolizumab", "stent")
        term: Full-text search across all fields
        titles: Search within study titles only
        outcome: Search by outcome measures
        sponsor: Sponsor or collaborator organization (e.g., "Pfizer", "NIH")
        lead: Lead sponsor or principal investigator
        patient: Patient-relevant search terms
        location: Geographic location name (e.g., "Switzerland", "Boston")
        study_id: Search by study ID (NCT number or other identifiers)
        overall_status: Comma-separated recruitment statuses. Valid values:
            RECRUITING, NOT_YET_RECRUITING, ENROLLING_BY_INVITATION,
            ACTIVE_NOT_RECRUITING, COMPLETED, SUSPENDED, TERMINATED, WITHDRAWN
        phase: Comma-separated trial phases. Valid values:
            EARLY_PHASE1, PHASE1, PHASE2, PHASE3, PHASE4, NA
        study_type: Study type filter. Valid values:
            INTERVENTIONAL, OBSERVATIONAL, EXPANDED_ACCESS
        geo: Geographic distance filter. Format: "distance(lat,lon,distance)".
            Example: "distance(46.5197,6.6323,50mi)" for 50 miles around Lausanne.
        advanced_filter: Advanced filter using AREA syntax.
            Example: "AREA[LastUpdatePostDate]RANGE[2024-01-01,MAX]"
        sort: Sort results. Format: "FieldName:asc" or "FieldName:desc".
            Fields: LastUpdatePostDate, EnrollmentCount, StartDate,
            StudyFirstPostDate, NumericId
        page_size: Results per page (max 1000, default 20)
        page_token: Pagination token from a previous response's nextPageToken
    """
    try:
        page_size = max(1, min(page_size, 1000))
        result = await client.search_studies(
            condition=condition,
            intervention=intervention,
            term=term,
            titles=titles,
            outcome=outcome,
            sponsor=sponsor,
            lead=lead,
            patient=patient,
            location=location,
            study_id=study_id,
            overall_status=overall_status,
            phase=phase,
            study_type=study_type,
            geo=geo,
            advanced_filter=advanced_filter,
            sort=sort,
            page_size=page_size,
            page_token=page_token,
        )
        return json.dumps(result, ensure_ascii=False)
    except (ClinicalTrialsAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def clinicaltrials_get_study(
    nct_id: str,
) -> str:
    """Get full details for a specific clinical study by its NCT identifier.

    Returns comprehensive information including protocol, eligibility criteria,
    interventions, outcomes, locations, sponsor details, and results if available.

    Args:
        nct_id: ClinicalTrials.gov identifier (e.g., "NCT04852770", "NCT06000696").
            Must start with "NCT" followed by digits.
    """
    try:
        result = await client.get_study(nct_id=nct_id)
        return json.dumps(result, ensure_ascii=False)
    except (ClinicalTrialsAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def clinicaltrials_get_stats(
) -> str:
    """Get database size statistics from ClinicalTrials.gov.

    Returns counts of studies by status, phase, and other aggregate metrics.
    Useful for understanding the scope and composition of the registry.
    """
    try:
        result = await client.get_study_sizes()
        return json.dumps(result, ensure_ascii=False)
    except (ClinicalTrialsAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


def main():
    """Entry point for the clinicaltrials-mcp CLI."""
    print("ClinicalTrials.gov MCP server starting...", file=sys.stderr)
    mcp.run(transport="stdio")
