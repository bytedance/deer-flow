"""Async HTTP client for the ClinicalTrials.gov API v2."""

import logging
import os
import sys
import time
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

# All logging to stderr (stdout reserved for JSON-RPC)
logging.basicConfig(
    stream=sys.stderr,
    level=getattr(logging, os.environ.get("CLINICALTRIALS_MCP_LOG_LEVEL", "WARNING").upper(), logging.WARNING),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("clinicaltrials-mcp")

BASE_URL = "https://clinicaltrials.gov/api/v2"

# Valid enum values
OVERALL_STATUSES = frozenset({
    "RECRUITING", "NOT_YET_RECRUITING", "ENROLLING_BY_INVITATION",
    "ACTIVE_NOT_RECRUITING", "SUSPENDED", "TERMINATED",
    "COMPLETED", "WITHDRAWN", "AVAILABLE", "NO_LONGER_AVAILABLE",
    "TEMPORARILY_NOT_AVAILABLE", "APPROVED_FOR_MARKETING",
    "WITHHELD", "UNKNOWN",
})

PHASES = frozenset({
    "EARLY_PHASE1", "PHASE1", "PHASE2", "PHASE3", "PHASE4", "NA",
})

STUDY_TYPES = frozenset({
    "INTERVENTIONAL", "OBSERVATIONAL", "EXPANDED_ACCESS",
})

SORT_OPTIONS = frozenset({
    "LastUpdatePostDate", "EnrollmentCount", "StartDate",
    "StudyFirstPostDate", "NumericId",
})


class ClinicalTrialsAPIError(Exception):
    """Raised when the ClinicalTrials.gov API returns an error."""


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient failures worth retrying."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (429, 500, 502, 503, 504):
        return True
    return False


class ClinicalTrialsClient:
    """Async client for the ClinicalTrials.gov API v2."""

    def __init__(self) -> None:
        self._http = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)
        self._enum_cache: dict[str, list[dict[str, Any]]] | None = None
        self._enum_cache_time: float = 0.0

    async def close(self) -> None:
        await self._http.aclose()

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a GET request with retry logic."""
        logger.debug(f"GET {path} params={params}")
        resp = await self._http.get(path, params={k: v for k, v in (params or {}).items() if v is not None})
        if resp.status_code == 404:
            raise ClinicalTrialsAPIError(f"Not found: {path}")
        resp.raise_for_status()
        return resp.json()

    async def search_studies(
        self,
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
        nct_ids: str | None = None,
        geo: str | None = None,
        advanced_filter: str | None = None,
        sort: str | None = None,
        page_size: int = 20,
        page_token: str | None = None,
        count_total: bool = True,
        fields: str | None = None,
    ) -> dict[str, Any]:
        """Search for clinical studies with various filters.

        Returns a list of studies matching the criteria.
        """
        params: dict[str, Any] = {
            "format": "json",
            "markupFormat": "markdown",
            "pageSize": min(max(1, page_size), 1000),
            "countTotal": str(count_total).lower(),
        }

        if condition:
            params["query.cond"] = condition
        if intervention:
            params["query.intr"] = intervention
        if term:
            params["query.term"] = term
        if titles:
            params["query.titles"] = titles
        if outcome:
            params["query.outc"] = outcome
        if sponsor:
            params["query.spons"] = sponsor
        if lead:
            params["query.lead"] = lead
        if patient:
            params["query.patient"] = patient
        if location:
            params["query.locn"] = location
        if study_id:
            params["query.id"] = study_id

        # Validate and apply enum filters
        if overall_status:
            statuses = [s.strip() for s in overall_status.split(",")]
            invalid = [s for s in statuses if s not in OVERALL_STATUSES]
            if invalid:
                raise ClinicalTrialsAPIError(
                    f"Invalid status values: {invalid}. Valid: {sorted(OVERALL_STATUSES)}"
                )
            params["filter.overallStatus"] = overall_status

        if phase:
            phases = [p.strip() for p in phase.split(",")]
            invalid = [p for p in phases if p not in PHASES]
            if invalid:
                raise ClinicalTrialsAPIError(
                    f"Invalid phase values: {invalid}. Valid: {sorted(PHASES)}"
                )
            params["filter.phase"] = phase

        if study_type:
            if study_type not in STUDY_TYPES:
                raise ClinicalTrialsAPIError(
                    f"Invalid study type: {study_type}. Valid: {sorted(STUDY_TYPES)}"
                )
            params["filter.studyType"] = study_type

        if nct_ids:
            params["filter.ids"] = nct_ids

        if geo:
            params["filter.geo"] = geo

        if advanced_filter:
            params["filter.advanced"] = advanced_filter

        if sort:
            # Sort format: "FieldName:asc" or "FieldName:desc"
            field_name = sort.split(":")[0] if ":" in sort else sort
            if field_name not in SORT_OPTIONS:
                raise ClinicalTrialsAPIError(
                    f"Invalid sort field: {field_name}. Valid: {sorted(SORT_OPTIONS)}"
                )
            params["sort"] = sort

        if page_token:
            params["pageToken"] = page_token

        if fields:
            params["fields"] = fields

        body = await self._get("/studies", params)

        studies = body.get("studies", [])
        result: dict[str, Any] = {"studies": []}

        for study in studies:
            protocol = study.get("protocolSection", {})
            id_module = protocol.get("identificationModule", {})
            status_module = protocol.get("statusModule", {})
            design_module = protocol.get("designModule", {})
            desc_module = protocol.get("descriptionModule", {})
            conditions_module = protocol.get("conditionsModule", {})
            arms_module = protocol.get("armsInterventionsModule", {})
            contacts_module = protocol.get("contactsLocationsModule", {})
            eligibility_module = protocol.get("eligibilityModule", {})
            sponsor_module = protocol.get("sponsorCollaboratorsModule", {})

            record = {
                "nctId": id_module.get("nctId", ""),
                "title": id_module.get("briefTitle", ""),
                "officialTitle": id_module.get("officialTitle", ""),
                "status": status_module.get("overallStatus", ""),
                "startDate": status_module.get("startDateStruct", {}).get("date", ""),
                "completionDate": status_module.get("completionDateStruct", {}).get("date", ""),
                "studyType": design_module.get("studyType", ""),
                "phases": design_module.get("phases", []),
                "enrollment": design_module.get("enrollmentInfo", {}).get("count"),
                "briefSummary": (desc_module.get("briefSummary") or "")[:500],
                "conditions": conditions_module.get("conditions", []),
                "interventions": [
                    {"type": i.get("type", ""), "name": i.get("name", "")}
                    for i in arms_module.get("interventions", [])
                ],
                "sponsor": sponsor_module.get("leadSponsor", {}).get("name", ""),
                "hasResults": study.get("hasResults", False),
            }
            result["studies"].append(record)

        if "totalCount" in body:
            result["totalCount"] = body["totalCount"]
        if "nextPageToken" in body:
            result["nextPageToken"] = body["nextPageToken"]

        return result

    async def get_study(self, nct_id: str, fields: str | None = None) -> dict[str, Any]:
        """Get full details for a specific study by NCT ID."""
        if not nct_id.startswith("NCT"):
            raise ClinicalTrialsAPIError(f"Invalid NCT ID format: {nct_id}. Must start with 'NCT'.")

        params: dict[str, Any] = {"format": "json"}
        if fields:
            params["fields"] = fields

        body = await self._get(f"/studies/{nct_id}", params)

        protocol = body.get("protocolSection", {})
        results_section = body.get("resultsSection", {})
        derived = body.get("derivedSection", {})

        id_module = protocol.get("identificationModule", {})
        status_module = protocol.get("statusModule", {})
        design_module = protocol.get("designModule", {})
        desc_module = protocol.get("descriptionModule", {})
        conditions_module = protocol.get("conditionsModule", {})
        arms_module = protocol.get("armsInterventionsModule", {})
        eligibility_module = protocol.get("eligibilityModule", {})
        contacts_module = protocol.get("contactsLocationsModule", {})
        sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
        oversight_module = protocol.get("oversightModule", {})
        outcomes_module = protocol.get("outcomesModule", {})
        references_module = protocol.get("referencesModule", {})

        result: dict[str, Any] = {
            "nctId": id_module.get("nctId", ""),
            "orgStudyId": id_module.get("organization", {}).get("orgStudyId", ""),
            "briefTitle": id_module.get("briefTitle", ""),
            "officialTitle": id_module.get("officialTitle", ""),
            "status": status_module.get("overallStatus", ""),
            "startDate": status_module.get("startDateStruct", {}).get("date", ""),
            "primaryCompletionDate": status_module.get("primaryCompletionDateStruct", {}).get("date", ""),
            "completionDate": status_module.get("completionDateStruct", {}).get("date", ""),
            "studyFirstPostDate": status_module.get("studyFirstPostDateStruct", {}).get("date", ""),
            "lastUpdatePostDate": status_module.get("lastUpdatePostDateStruct", {}).get("date", ""),
            "studyType": design_module.get("studyType", ""),
            "phases": design_module.get("phases", []),
            "enrollment": design_module.get("enrollmentInfo", {}),
            "briefSummary": desc_module.get("briefSummary", ""),
            "detailedDescription": desc_module.get("detailedDescription", ""),
            "conditions": conditions_module.get("conditions", []),
            "keywords": conditions_module.get("keywords", []),
            "interventions": [
                {
                    "type": i.get("type", ""),
                    "name": i.get("name", ""),
                    "description": i.get("description", ""),
                    "armGroupLabels": i.get("armGroupLabels", []),
                }
                for i in arms_module.get("interventions", [])
            ],
            "armGroups": [
                {
                    "label": a.get("label", ""),
                    "type": a.get("type", ""),
                    "description": a.get("description", ""),
                }
                for a in arms_module.get("armGroups", [])
            ],
            "eligibility": {
                "criteria": eligibility_module.get("eligibilityCriteria", ""),
                "sex": eligibility_module.get("sex", ""),
                "minAge": eligibility_module.get("minimumAge", ""),
                "maxAge": eligibility_module.get("maximumAge", ""),
                "healthyVolunteers": eligibility_module.get("healthyVolunteers", ""),
            },
            "sponsor": {
                "lead": sponsor_module.get("leadSponsor", {}),
                "collaborators": sponsor_module.get("collaborators", []),
            },
            "oversight": {
                "hasDmc": oversight_module.get("oversightHasDmc", False),
                "isFdaRegulated": oversight_module.get("isFdaRegulatedDrug", False) or oversight_module.get("isFdaRegulatedDevice", False),
            },
            "primaryOutcomes": [
                {"measure": o.get("measure", ""), "timeFrame": o.get("timeFrame", ""), "description": o.get("description", "")}
                for o in outcomes_module.get("primaryOutcomes", [])
            ],
            "secondaryOutcomes": [
                {"measure": o.get("measure", ""), "timeFrame": o.get("timeFrame", ""), "description": o.get("description", "")}
                for o in outcomes_module.get("secondaryOutcomes", [])
            ],
            "locations": [
                {
                    "facility": loc.get("facility", ""),
                    "city": loc.get("city", ""),
                    "state": loc.get("state", ""),
                    "country": loc.get("country", ""),
                    "status": loc.get("status", ""),
                }
                for loc in contacts_module.get("locations", [])
            ],
            "references": [
                {"pmid": r.get("pmid", ""), "citation": r.get("citation", ""), "type": r.get("type", "")}
                for r in references_module.get("references", [])
            ],
            "meshTerms": [
                t.get("term", "") for t in derived.get("conditionBrowseModule", {}).get("meshes", [])
            ],
            "hasResults": body.get("hasResults", False),
        }

        # Include results summary if available
        if results_section:
            participant_flow = results_section.get("participantFlowModule", {})
            baseline = results_section.get("baselineCharacteristicsModule", {})
            adverse = results_section.get("adverseEventsModule", {})

            result["resultsSummary"] = {
                "participantFlow": participant_flow.get("preAssignmentDetails", ""),
                "hasSeriousAdverseEvents": bool(adverse.get("seriousEvents", [])),
                "hasOtherAdverseEvents": bool(adverse.get("otherEvents", [])),
            }

        return result

    async def get_study_sizes(self) -> dict[str, Any]:
        """Get size statistics about the ClinicalTrials.gov database."""
        body = await self._get("/stats/size")
        return body

    async def get_field_values(self, fields: str) -> dict[str, Any]:
        """Get possible values for enumerated fields."""
        params: dict[str, Any] = {"format": "json"}
        body = await self._get("/stats/fieldValues/" + fields, params)
        return body

    async def get_api_version(self) -> dict[str, Any]:
        """Get the current API version information."""
        body = await self._get("/version")
        return body
