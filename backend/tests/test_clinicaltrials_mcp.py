"""Unit tests for the ClinicalTrials.gov MCP server."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Add the clinicaltrials MCP server directory to sys.path so we can import directly
CLINICALTRIALS_DIR = str(Path(__file__).resolve().parent.parent.parent / "mcp_servers" / "clinicaltrials")
if CLINICALTRIALS_DIR not in sys.path:
    sys.path.insert(0, CLINICALTRIALS_DIR)

from clinicaltrials_mcp.api_client import ClinicalTrialsAPIError, ClinicalTrialsClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(json_data, status_code=200):
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


SAMPLE_SEARCH_RESPONSE = {
    "studies": [
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT06000696",
                    "briefTitle": "Study of Pembrolizumab in Breast Cancer",
                    "officialTitle": "A Phase 3 Study of Pembrolizumab Plus Chemotherapy",
                },
                "statusModule": {
                    "overallStatus": "RECRUITING",
                    "startDateStruct": {"date": "2023-09-01"},
                    "completionDateStruct": {"date": "2027-12-31"},
                },
                "designModule": {
                    "studyType": "INTERVENTIONAL",
                    "phases": ["PHASE3"],
                    "enrollmentInfo": {"count": 500},
                },
                "descriptionModule": {
                    "briefSummary": "This study evaluates pembrolizumab combined with chemotherapy for advanced breast cancer.",
                },
                "conditionsModule": {
                    "conditions": ["Breast Cancer", "Triple Negative Breast Neoplasms"],
                },
                "armsInterventionsModule": {
                    "interventions": [
                        {"type": "DRUG", "name": "Pembrolizumab"},
                        {"type": "DRUG", "name": "Paclitaxel"},
                    ],
                },
                "sponsorCollaboratorsModule": {
                    "leadSponsor": {"name": "Merck Sharp & Dohme LLC"},
                },
            },
            "hasResults": False,
        },
        {
            "protocolSection": {
                "identificationModule": {
                    "nctId": "NCT04852770",
                    "briefTitle": "Diabetes Prevention Program",
                },
                "statusModule": {
                    "overallStatus": "COMPLETED",
                    "startDateStruct": {"date": "2021-01-15"},
                    "completionDateStruct": {"date": "2023-06-30"},
                },
                "designModule": {
                    "studyType": "OBSERVATIONAL",
                    "phases": [],
                    "enrollmentInfo": {"count": 200},
                },
                "descriptionModule": {
                    "briefSummary": "Observational study of diabetes prevention strategies.",
                },
                "conditionsModule": {
                    "conditions": ["Type 2 Diabetes"],
                },
                "armsInterventionsModule": {},
                "sponsorCollaboratorsModule": {
                    "leadSponsor": {"name": "NIH"},
                },
            },
            "hasResults": True,
        },
    ],
    "totalCount": 2,
}

SAMPLE_STUDY_RESPONSE = {
    "protocolSection": {
        "identificationModule": {
            "nctId": "NCT06000696",
            "briefTitle": "Study of Pembrolizumab in Breast Cancer",
            "officialTitle": "A Phase 3 Randomized Study of Pembrolizumab Plus Chemotherapy",
            "organization": {"orgStudyId": "MK-3475-001"},
        },
        "statusModule": {
            "overallStatus": "RECRUITING",
            "startDateStruct": {"date": "2023-09-01"},
            "primaryCompletionDateStruct": {"date": "2026-06-30"},
            "completionDateStruct": {"date": "2027-12-31"},
            "studyFirstPostDateStruct": {"date": "2023-08-01"},
            "lastUpdatePostDateStruct": {"date": "2024-03-15"},
        },
        "designModule": {
            "studyType": "INTERVENTIONAL",
            "phases": ["PHASE3"],
            "enrollmentInfo": {"count": 500, "type": "ESTIMATED"},
        },
        "descriptionModule": {
            "briefSummary": "This study evaluates pembrolizumab combined with chemotherapy.",
            "detailedDescription": "A detailed description of the study protocol.",
        },
        "conditionsModule": {
            "conditions": ["Breast Cancer"],
            "keywords": ["breast", "immunotherapy"],
        },
        "armsInterventionsModule": {
            "interventions": [
                {
                    "type": "DRUG",
                    "name": "Pembrolizumab",
                    "description": "200mg IV every 3 weeks",
                    "armGroupLabels": ["Experimental"],
                },
            ],
            "armGroups": [
                {
                    "label": "Experimental",
                    "type": "EXPERIMENTAL",
                    "description": "Pembrolizumab + chemotherapy",
                },
            ],
        },
        "eligibilityModule": {
            "eligibilityCriteria": "Inclusion: Age >= 18\nExclusion: Prior immunotherapy",
            "sex": "ALL",
            "minimumAge": "18 Years",
            "maximumAge": "N/A",
            "healthyVolunteers": "No",
        },
        "contactsLocationsModule": {
            "locations": [
                {
                    "facility": "Cancer Center",
                    "city": "New York",
                    "state": "New York",
                    "country": "United States",
                    "status": "RECRUITING",
                },
            ],
        },
        "sponsorCollaboratorsModule": {
            "leadSponsor": {"name": "Merck Sharp & Dohme LLC", "class": "INDUSTRY"},
            "collaborators": [{"name": "NCI", "class": "NIH"}],
        },
        "oversightModule": {
            "oversightHasDmc": True,
            "isFdaRegulatedDrug": True,
            "isFdaRegulatedDevice": False,
        },
        "outcomesModule": {
            "primaryOutcomes": [
                {
                    "measure": "Overall Survival",
                    "timeFrame": "Up to 5 years",
                    "description": "Time from randomization to death",
                },
            ],
            "secondaryOutcomes": [
                {
                    "measure": "Progression-Free Survival",
                    "timeFrame": "Up to 3 years",
                    "description": "Time from randomization to progression or death",
                },
            ],
        },
        "referencesModule": {
            "references": [
                {"pmid": "12345678", "citation": "Smith et al. Nature 2023", "type": "RESULT"},
            ],
        },
    },
    "derivedSection": {
        "conditionBrowseModule": {
            "meshes": [
                {"term": "Breast Neoplasms"},
            ],
        },
    },
    "hasResults": False,
}

SAMPLE_STATS_RESPONSE = {
    "totalStudies": 500000,
    "studiesByStatus": {
        "RECRUITING": 50000,
        "COMPLETED": 300000,
    },
}


# ---------------------------------------------------------------------------
# TestClinicalTrialsClient
# ---------------------------------------------------------------------------

class TestClinicalTrialsClient:
    """Tests for the ClinicalTrialsClient API wrapper."""

    @pytest.fixture()
    def client(self):
        return ClinicalTrialsClient()

    @pytest.mark.asyncio
    async def test_search_studies_basic(self, client):
        mock_resp = _mock_response(SAMPLE_SEARCH_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.search_studies(condition="breast cancer")

        assert len(result["studies"]) == 2
        assert result["studies"][0]["nctId"] == "NCT06000696"
        assert result["studies"][0]["status"] == "RECRUITING"
        assert result["studies"][0]["title"] == "Study of Pembrolizumab in Breast Cancer"
        assert "Breast Cancer" in result["studies"][0]["conditions"]
        assert result["totalCount"] == 2

    @pytest.mark.asyncio
    async def test_search_studies_with_status_filter(self, client):
        mock_resp = _mock_response(SAMPLE_SEARCH_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.search_studies(condition="cancer", overall_status="RECRUITING")

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["filter.overallStatus"] == "RECRUITING"

    @pytest.mark.asyncio
    async def test_search_studies_with_phase_filter(self, client):
        mock_resp = _mock_response(SAMPLE_SEARCH_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.search_studies(condition="cancer", phase="PHASE3")

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["filter.phase"] == "PHASE3"

    @pytest.mark.asyncio
    async def test_search_studies_invalid_status(self, client):
        with pytest.raises(ClinicalTrialsAPIError, match="Invalid status"):
            await client.search_studies(condition="cancer", overall_status="INVALID")

    @pytest.mark.asyncio
    async def test_search_studies_invalid_phase(self, client):
        with pytest.raises(ClinicalTrialsAPIError, match="Invalid phase"):
            await client.search_studies(condition="cancer", phase="PHASE99")

    @pytest.mark.asyncio
    async def test_search_studies_invalid_study_type(self, client):
        with pytest.raises(ClinicalTrialsAPIError, match="Invalid study type"):
            await client.search_studies(condition="cancer", study_type="INVALID")

    @pytest.mark.asyncio
    async def test_search_studies_page_size_clamped(self, client):
        mock_resp = _mock_response(SAMPLE_SEARCH_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.search_studies(condition="cancer", page_size=5000)

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["pageSize"] == 1000

    @pytest.mark.asyncio
    async def test_search_studies_with_sort(self, client):
        mock_resp = _mock_response(SAMPLE_SEARCH_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.search_studies(condition="cancer", sort="EnrollmentCount:desc")

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["sort"] == "EnrollmentCount:desc"

    @pytest.mark.asyncio
    async def test_search_studies_invalid_sort(self, client):
        with pytest.raises(ClinicalTrialsAPIError, match="Invalid sort field"):
            await client.search_studies(condition="cancer", sort="InvalidField:desc")

    @pytest.mark.asyncio
    async def test_search_studies_multiple_query_params(self, client):
        mock_resp = _mock_response(SAMPLE_SEARCH_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.search_studies(
                condition="cancer",
                intervention="pembrolizumab",
                sponsor="Merck",
                location="United States",
            )

        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"]
        assert params["query.cond"] == "cancer"
        assert params["query.intr"] == "pembrolizumab"
        assert params["query.spons"] == "Merck"
        assert params["query.locn"] == "United States"

    @pytest.mark.asyncio
    async def test_search_studies_interventions_parsed(self, client):
        mock_resp = _mock_response(SAMPLE_SEARCH_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.search_studies(condition="breast cancer")

        interventions = result["studies"][0]["interventions"]
        assert len(interventions) == 2
        assert interventions[0]["type"] == "DRUG"
        assert interventions[0]["name"] == "Pembrolizumab"

    @pytest.mark.asyncio
    async def test_get_study_basic(self, client):
        mock_resp = _mock_response(SAMPLE_STUDY_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_study("NCT06000696")

        assert result["nctId"] == "NCT06000696"
        assert result["status"] == "RECRUITING"
        assert result["studyType"] == "INTERVENTIONAL"
        assert result["phases"] == ["PHASE3"]
        assert "Breast Cancer" in result["conditions"]
        assert result["sponsor"]["lead"]["name"] == "Merck Sharp & Dohme LLC"

    @pytest.mark.asyncio
    async def test_get_study_eligibility(self, client):
        mock_resp = _mock_response(SAMPLE_STUDY_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_study("NCT06000696")

        elig = result["eligibility"]
        assert "Age >= 18" in elig["criteria"]
        assert elig["sex"] == "ALL"
        assert elig["minAge"] == "18 Years"

    @pytest.mark.asyncio
    async def test_get_study_outcomes(self, client):
        mock_resp = _mock_response(SAMPLE_STUDY_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_study("NCT06000696")

        assert len(result["primaryOutcomes"]) == 1
        assert result["primaryOutcomes"][0]["measure"] == "Overall Survival"
        assert len(result["secondaryOutcomes"]) == 1

    @pytest.mark.asyncio
    async def test_get_study_locations(self, client):
        mock_resp = _mock_response(SAMPLE_STUDY_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_study("NCT06000696")

        assert len(result["locations"]) == 1
        assert result["locations"][0]["city"] == "New York"
        assert result["locations"][0]["country"] == "United States"

    @pytest.mark.asyncio
    async def test_get_study_mesh_terms(self, client):
        mock_resp = _mock_response(SAMPLE_STUDY_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_study("NCT06000696")

        assert "Breast Neoplasms" in result["meshTerms"]

    @pytest.mark.asyncio
    async def test_get_study_invalid_nct_id(self, client):
        with pytest.raises(ClinicalTrialsAPIError, match="Invalid NCT ID"):
            await client.get_study("INVALID123")

    @pytest.mark.asyncio
    async def test_get_study_not_found(self, client):
        mock_resp = _mock_response({}, status_code=404)
        mock_resp.raise_for_status = MagicMock()  # Don't raise for 404, client checks
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(ClinicalTrialsAPIError, match="Not found"):
                await client.get_study("NCT99999999")

    @pytest.mark.asyncio
    async def test_get_study_sizes(self, client):
        mock_resp = _mock_response(SAMPLE_STATS_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.get_study_sizes()

        assert result["totalStudies"] == 500000


# ---------------------------------------------------------------------------
# TestClinicalTrialsTools
# ---------------------------------------------------------------------------

class TestClinicalTrialsTools:
    """Tests for the MCP tool wrapper functions."""

    @pytest.mark.asyncio
    async def test_search_studies_returns_json(self):
        from clinicaltrials_mcp import clinicaltrials_search_studies

        mock_resp = _mock_response(SAMPLE_SEARCH_RESPONSE)
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await clinicaltrials_search_studies(condition="breast cancer")

        parsed = json.loads(result)
        assert "studies" in parsed
        assert "totalCount" in parsed

    @pytest.mark.asyncio
    async def test_get_study_returns_json(self):
        from clinicaltrials_mcp import clinicaltrials_get_study

        mock_resp = _mock_response(SAMPLE_STUDY_RESPONSE)
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await clinicaltrials_get_study(nct_id="NCT06000696")

        parsed = json.loads(result)
        assert "nctId" in parsed
        assert parsed["nctId"] == "NCT06000696"

    @pytest.mark.asyncio
    async def test_get_stats_returns_json(self):
        from clinicaltrials_mcp import clinicaltrials_get_stats

        mock_resp = _mock_response(SAMPLE_STATS_RESPONSE)
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await clinicaltrials_get_stats()

        parsed = json.loads(result)
        assert "totalStudies" in parsed

    @pytest.mark.asyncio
    async def test_tool_error_wrapping(self):
        from clinicaltrials_mcp import clinicaltrials_search_studies

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("Connection timed out"),
        ):
            result = await clinicaltrials_search_studies(condition="cancer")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "timed out" in parsed["error"]

    @pytest.mark.asyncio
    async def test_page_size_clamping_in_tool(self):
        from clinicaltrials_mcp import clinicaltrials_search_studies

        mock_resp = _mock_response(SAMPLE_SEARCH_RESPONSE)
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
        ) as mock_get:
            await clinicaltrials_search_studies(condition="cancer", page_size=5000)

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["pageSize"] == 1000


# ---------------------------------------------------------------------------
# TestClinicalTrialsMcpConfig
# ---------------------------------------------------------------------------

class TestClinicalTrialsMcpConfig:
    """Tests for the clinicaltrials entry in extensions_config.json."""

    def test_extensions_config_has_clinicaltrials(self):
        config_path = Path(__file__).resolve().parent.parent.parent / "extensions_config.json"
        with open(config_path) as f:
            config = json.load(f)

        ct = config["mcpServers"]["clinicaltrials"]
        assert ct["enabled"] is True
        assert ct["type"] == "stdio"
        assert ct["command"] == "clinicaltrials-mcp"
