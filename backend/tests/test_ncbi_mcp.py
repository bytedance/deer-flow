"""Unit tests for the NCBI E-utilities MCP server."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

# Add the ncbi MCP server directory to sys.path so we can import directly
NCBI_DIR = str(Path(__file__).resolve().parent.parent.parent / "mcp_servers" / "ncbi")
if NCBI_DIR not in sys.path:
    sys.path.insert(0, NCBI_DIR)

from ncbi_mcp.api_client import NCBIAPIError, NCBIClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_response(json_data=None, text_data=None, status_code=200, content_type="application/json"):
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.headers = {"content-type": content_type}
    if json_data is not None:
        resp.json.return_value = json_data
    if text_data is not None:
        resp.text = text_data
    else:
        resp.text = json.dumps(json_data) if json_data else ""
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


SAMPLE_SEARCH_RESPONSE = {
    "esearchresult": {
        "count": "1542",
        "retmax": "3",
        "retstart": "0",
        "idlist": ["39109882", "39095432", "39088745"],
        "querytranslation": "breast cancer[All Fields] AND immunotherapy[All Fields]",
        "webenv": "",
        "querykey": "",
    }
}

SAMPLE_SUMMARY_RESPONSE = {
    "result": {
        "uids": ["39109882", "39095432"],
        "39109882": {
            "uid": "39109882",
            "pubdate": "2024 Mar",
            "source": "Nature Medicine",
            "title": "Immunotherapy advances in breast cancer treatment",
            "authors": [
                {"name": "Smith J", "authtype": "Author"},
                {"name": "Doe A", "authtype": "Author"},
            ],
            "volume": "30",
            "issue": "3",
            "pages": "456-470",
            "doi": "10.1038/s41591-024-00001-1",
        },
        "39095432": {
            "uid": "39095432",
            "pubdate": "2024 Feb",
            "source": "The Lancet Oncology",
            "title": "CAR-T cell therapy for solid tumors",
            "authors": [
                {"name": "Johnson B", "authtype": "Author"},
            ],
            "volume": "25",
            "issue": "2",
            "pages": "123-135",
            "doi": "10.1016/S1470-2045(24)00001-5",
        },
    }
}

SAMPLE_FETCH_XML = """<?xml version="1.0" ?>
<PubmedArticleSet>
    <PubmedArticle>
        <MedlineCitation>
            <PMID>39109882</PMID>
            <Article>
                <ArticleTitle>Immunotherapy advances in breast cancer treatment</ArticleTitle>
                <Abstract>
                    <AbstractText>This review covers recent advances...</AbstractText>
                </Abstract>
            </Article>
        </MedlineCitation>
    </PubmedArticle>
</PubmedArticleSet>"""

SAMPLE_LINK_RESPONSE = {
    "linksets": [
        {
            "dbfrom": "gene",
            "ids": [{"value": "672"}],
            "linksetdbs": [
                {
                    "dbto": "protein",
                    "linkname": "gene_protein",
                    "links": [
                        {"id": "4502"},
                        {"id": "4503"},
                    ],
                },
                {
                    "dbto": "pubmed",
                    "linkname": "gene_pubmed",
                    "links": [
                        {"id": "39109882"},
                    ],
                },
            ],
        }
    ]
}

SAMPLE_INFO_RESPONSE = {
    "einforesult": {
        "dbinfo": [
            {
                "dbname": "pubmed",
                "description": "PubMed bibliographic record",
                "count": "36000000",
                "lastupdate": "2024/03/15",
                "fieldlist": [
                    {
                        "name": "AUTH",
                        "fullname": "Author",
                        "description": "Author name",
                        "termcount": "20000000",
                        "isdate": "N",
                        "isnumerical": "N",
                    },
                    {
                        "name": "TIAB",
                        "fullname": "Title/Abstract",
                        "description": "Title and Abstract words",
                        "termcount": "50000000",
                        "isdate": "N",
                        "isnumerical": "N",
                    },
                ],
                "linklist": [
                    {
                        "name": "pubmed_gene",
                        "menu": "Gene Links",
                        "description": "Link to Gene",
                        "dbto": "gene",
                    },
                ],
            }
        ]
    }
}

SAMPLE_INFO_DBLIST_RESPONSE = {
    "einforesult": {
        "dblist": ["pubmed", "protein", "nucleotide", "gene", "snp", "mesh"],
    }
}

SAMPLE_GLOBAL_QUERY_XML = """<?xml version="1.0" ?>
<Result>
    <Term>BRCA1</Term>
    <eGQueryResult>
        <ResultItem>
            <DbName>pubmed</DbName>
            <MenuName>PubMed</MenuName>
            <Count>15234</Count>
            <Status>Ok</Status>
        </ResultItem>
        <ResultItem>
            <DbName>gene</DbName>
            <MenuName>Gene</MenuName>
            <Count>42</Count>
            <Status>Ok</Status>
        </ResultItem>
        <ResultItem>
            <DbName>protein</DbName>
            <MenuName>Protein</MenuName>
            <Count>1087</Count>
            <Status>Ok</Status>
        </ResultItem>
        <ResultItem>
            <DbName>taxonomy</DbName>
            <MenuName>Taxonomy</MenuName>
            <Count>0</Count>
            <Status>Ok</Status>
        </ResultItem>
    </eGQueryResult>
</Result>"""

SAMPLE_SPELL_XML = """<?xml version="1.0" ?>
<eSpellResult>
    <Query>fibrblast grwth factr</Query>
    <CorrectedQuery>fibroblast growth factor</CorrectedQuery>
</eSpellResult>"""

SAMPLE_CITMATCH_TEXT = "proc natl acad sci u s a|1991|88|3248|paull|ref1|2014248\n"


# ---------------------------------------------------------------------------
# TestNCBIClient
# ---------------------------------------------------------------------------

class TestNCBIClient:
    """Tests for the NCBIClient API wrapper."""

    @pytest.fixture()
    def client(self):
        return NCBIClient()

    @pytest.mark.asyncio
    async def test_search_basic(self, client):
        mock_resp = _mock_response(SAMPLE_SEARCH_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.search(db="pubmed", term="breast cancer immunotherapy")

        assert result["count"] == 1542
        assert len(result["ids"]) == 3
        assert result["ids"][0] == "39109882"
        assert "breast cancer" in result["queryTranslation"]

    @pytest.mark.asyncio
    async def test_search_with_date_filter(self, client):
        mock_resp = _mock_response(SAMPLE_SEARCH_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.search(
                db="pubmed", term="cancer",
                date_type="pdat", min_date="2024/01/01", max_date="2024/12/31",
            )

        call_kwargs = mock_get.call_args
        params = call_kwargs[1]["params"]
        assert params["datetype"] == "pdat"
        assert params["mindate"] == "2024/01/01"
        assert params["maxdate"] == "2024/12/31"

    @pytest.mark.asyncio
    async def test_search_with_sort(self, client):
        mock_resp = _mock_response(SAMPLE_SEARCH_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.search(db="pubmed", term="cancer", sort="pub_date")

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["sort"] == "pub_date"

    @pytest.mark.asyncio
    async def test_search_retmax_clamped(self, client):
        mock_resp = _mock_response(SAMPLE_SEARCH_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.search(db="pubmed", term="cancer", retmax=50000)

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["retmax"] == 10000

    @pytest.mark.asyncio
    async def test_search_error_handling(self, client):
        error_response = {
            "esearchresult": {
                "ERROR": "Invalid database name",
            }
        }
        mock_resp = _mock_response(error_response)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            with pytest.raises(NCBIAPIError, match="Invalid database"):
                await client.search(db="invalid_db", term="test")

    @pytest.mark.asyncio
    async def test_summary_basic(self, client):
        mock_resp = _mock_response(SAMPLE_SUMMARY_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.summary(db="pubmed", ids="39109882,39095432")

        assert len(result["records"]) == 2
        assert result["records"][0]["title"] == "Immunotherapy advances in breast cancer treatment"
        assert result["records"][0]["source"] == "Nature Medicine"

    @pytest.mark.asyncio
    async def test_summary_retmax_clamped(self, client):
        mock_resp = _mock_response(SAMPLE_SUMMARY_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp) as mock_get:
            await client.summary(db="pubmed", ids="1", retmax=1000)

        call_kwargs = mock_get.call_args
        assert call_kwargs[1]["params"]["retmax"] == 500

    @pytest.mark.asyncio
    async def test_fetch_xml(self, client):
        mock_resp = _mock_response(text_data=SAMPLE_FETCH_XML, content_type="text/xml")
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.fetch(db="pubmed", ids="39109882")

        assert "PubmedArticle" in result

    @pytest.mark.asyncio
    async def test_fetch_fasta(self, client):
        fasta_text = ">NM_000546.6 Homo sapiens tumor protein p53\nATGGAGGAGCCGCAGTCAGATCC\n"
        mock_resp = _mock_response(text_data=fasta_text, content_type="text/plain")
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.fetch(db="nucleotide", ids="NM_000546", rettype="fasta")

        assert "text" in result
        assert "NM_000546" in result["text"]

    @pytest.mark.asyncio
    async def test_link_basic(self, client):
        mock_resp = _mock_response(SAMPLE_LINK_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.link(dbfrom="gene", db="protein", ids="672")

        assert len(result["linksets"]) == 2
        assert result["linksets"][0]["dbTo"] == "protein"
        assert result["linksets"][0]["linkName"] == "gene_protein"
        assert len(result["linksets"][0]["ids"]) == 2

    @pytest.mark.asyncio
    async def test_info_dblist(self, client):
        mock_resp = _mock_response(SAMPLE_INFO_DBLIST_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.info()

        assert "pubmed" in result["databases"]
        assert "gene" in result["databases"]

    @pytest.mark.asyncio
    async def test_info_db_details(self, client):
        mock_resp = _mock_response(SAMPLE_INFO_RESPONSE)
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.info(db="pubmed")

        assert result["dbName"] == "pubmed"
        assert result["count"] == "36000000"
        assert len(result["fields"]) == 2
        assert result["fields"][0]["name"] == "AUTH"
        assert len(result["links"]) == 1

    @pytest.mark.asyncio
    async def test_spell(self, client):
        mock_resp = _mock_response(text_data=SAMPLE_SPELL_XML, content_type="text/xml")
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.spell(db="pubmed", term="fibrblast grwth factr")

        assert result["original"] == "fibrblast grwth factr"
        assert result["corrected"] == "fibroblast growth factor"

    @pytest.mark.asyncio
    async def test_global_query(self, client):
        mock_resp = _mock_response(text_data=SAMPLE_GLOBAL_QUERY_XML, content_type="text/xml")
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.global_query(term="BRCA1")

        assert result["term"] == "BRCA1"
        assert len(result["results"]) == 3  # taxonomy filtered out (count=0)
        assert result["results"][0]["dbName"] == "pubmed"  # sorted desc by count
        assert result["results"][0]["count"] == 15234

    @pytest.mark.asyncio
    async def test_citmatch(self, client):
        mock_resp = _mock_response(text_data=SAMPLE_CITMATCH_TEXT, content_type="text/plain")
        with patch.object(client._http, "get", new_callable=AsyncMock, return_value=mock_resp):
            result = await client.citmatch([{
                "journal": "proc natl acad sci u s a",
                "year": "1991",
                "volume": "88",
                "first_page": "3248",
                "author_name": "paull",
                "key": "ref1",
            }])

        assert len(result["matches"]) == 1
        assert result["matches"][0]["pmid"] == "2014248"
        assert result["matches"][0]["key"] == "ref1"

    @pytest.mark.asyncio
    async def test_api_key_in_params(self):
        """Verify API key is included in requests when set."""
        with patch.dict("os.environ", {"NCBI_API_KEY": "test_key_123", "NCBI_EMAIL": "test@example.com"}):
            client = NCBIClient()

        params = client._base_params()
        assert params["api_key"] == "test_key_123"
        assert params["email"] == "test@example.com"


# ---------------------------------------------------------------------------
# TestNCBITools
# ---------------------------------------------------------------------------

class TestNCBITools:
    """Tests for the MCP tool wrapper functions."""

    @pytest.mark.asyncio
    async def test_search_returns_json(self):
        from ncbi_mcp import ncbi_search

        mock_resp = _mock_response(SAMPLE_SEARCH_RESPONSE)
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await ncbi_search(db="pubmed", term="breast cancer")

        parsed = json.loads(result)
        assert "count" in parsed
        assert "ids" in parsed

    @pytest.mark.asyncio
    async def test_summary_returns_json(self):
        from ncbi_mcp import ncbi_summary

        mock_resp = _mock_response(SAMPLE_SUMMARY_RESPONSE)
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await ncbi_summary(db="pubmed", ids="39109882,39095432")

        parsed = json.loads(result)
        assert "records" in parsed
        assert len(parsed["records"]) == 2

    @pytest.mark.asyncio
    async def test_fetch_returns_json(self):
        from ncbi_mcp import ncbi_fetch

        mock_resp = _mock_response(text_data=SAMPLE_FETCH_XML, content_type="text/xml")
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await ncbi_fetch(db="pubmed", ids="39109882")

        parsed = json.loads(result)
        assert "PubmedArticle" in parsed

    @pytest.mark.asyncio
    async def test_link_returns_json(self):
        from ncbi_mcp import ncbi_link

        mock_resp = _mock_response(SAMPLE_LINK_RESPONSE)
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await ncbi_link(dbfrom="gene", db="protein", ids="672")

        parsed = json.loads(result)
        assert "linksets" in parsed

    @pytest.mark.asyncio
    async def test_info_returns_json(self):
        from ncbi_mcp import ncbi_info

        mock_resp = _mock_response(SAMPLE_INFO_DBLIST_RESPONSE)
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await ncbi_info()

        parsed = json.loads(result)
        assert "databases" in parsed

    @pytest.mark.asyncio
    async def test_global_search_returns_json(self):
        from ncbi_mcp import ncbi_global_search

        mock_resp = _mock_response(text_data=SAMPLE_GLOBAL_QUERY_XML, content_type="text/xml")
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await ncbi_global_search(term="BRCA1")

        parsed = json.loads(result)
        assert "results" in parsed
        assert parsed["results"][0]["count"] > 0

    @pytest.mark.asyncio
    async def test_spell_returns_json(self):
        from ncbi_mcp import ncbi_spell

        mock_resp = _mock_response(text_data=SAMPLE_SPELL_XML, content_type="text/xml")
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
        ):
            result = await ncbi_spell(db="pubmed", term="fibrblast")

        parsed = json.loads(result)
        assert "corrected" in parsed

    @pytest.mark.asyncio
    async def test_citmatch_returns_json(self):
        from ncbi_mcp import ncbi_citmatch

        mock_resp = _mock_response(text_data=SAMPLE_CITMATCH_TEXT, content_type="text/plain")
        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock, return_value=mock_resp
        ):
            citations = json.dumps([{
                "journal": "proc natl acad sci u s a",
                "year": "1991",
                "volume": "88",
                "first_page": "3248",
                "author_name": "paull",
                "key": "ref1",
            }])
            result = await ncbi_citmatch(citations_json=citations)

        parsed = json.loads(result)
        assert "matches" in parsed

    @pytest.mark.asyncio
    async def test_citmatch_invalid_json(self):
        from ncbi_mcp import ncbi_citmatch

        result = await ncbi_citmatch(citations_json="not valid json")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "Invalid JSON" in parsed["error"]

    @pytest.mark.asyncio
    async def test_tool_error_wrapping(self):
        from ncbi_mcp import ncbi_search

        with patch.object(
            httpx.AsyncClient, "get", new_callable=AsyncMock,
            side_effect=httpx.TimeoutException("Connection timed out"),
        ):
            result = await ncbi_search(db="pubmed", term="test")

        parsed = json.loads(result)
        assert "error" in parsed
        assert "timed out" in parsed["error"]


# ---------------------------------------------------------------------------
# TestNCBIMcpConfig
# ---------------------------------------------------------------------------

class TestNCBIMcpConfig:
    """Tests for the ncbi entry in extensions_config.json."""

    def test_extensions_config_has_ncbi(self):
        config_path = Path(__file__).resolve().parent.parent.parent / "extensions_config.json"
        with open(config_path) as f:
            config = json.load(f)

        ncbi = config["mcpServers"]["ncbi"]
        assert ncbi["enabled"] is True
        assert ncbi["type"] == "stdio"
        assert ncbi["command"] == "ncbi-mcp"
