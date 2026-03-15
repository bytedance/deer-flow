"""Async HTTP client for the NCBI E-utilities API."""

import logging
import os
import sys
import xml.etree.ElementTree as ET
from typing import Any

import httpx
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

# All logging to stderr (stdout reserved for JSON-RPC)
logging.basicConfig(
    stream=sys.stderr,
    level=getattr(logging, os.environ.get("NCBI_MCP_LOG_LEVEL", "WARNING").upper(), logging.WARNING),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("ncbi-mcp")

BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

# Key NCBI databases and their descriptions
DATABASES = {
    "pubmed": "Biomedical literature (MEDLINE, life science journals, online books)",
    "pmc": "Full-text biomedical and life science journal articles",
    "gene": "Gene-centered information (sequences, maps, pathways, phenotypes)",
    "protein": "Protein sequences from GenBank, RefSeq, PDB, SwissProt",
    "nucleotide": "DNA/RNA sequences from GenBank, EMBL, DDBJ",
    "snp": "Single nucleotide polymorphisms and variants",
    "omim": "Online Mendelian Inheritance in Man (genetic disorders)",
    "mesh": "Medical Subject Headings vocabulary",
    "taxonomy": "Organism taxonomy and phylogenetic data",
    "clinvar": "Human genomic variants and clinical significance",
    "biosample": "Biological source materials used in studies",
    "sra": "Sequence Read Archive (next-gen sequencing data)",
    "gds": "Gene Expression Omnibus datasets",
    "structure": "3D macromolecular structures from PDB",
    "books": "NCBI Bookshelf full-text books and documents",
}


class NCBIAPIError(Exception):
    """Raised when the NCBI E-utilities API returns an error."""


def _is_retryable(exc: BaseException) -> bool:
    """Return True for transient failures worth retrying."""
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in (429, 500, 502, 503, 504):
        return True
    return False


def _xml_to_dict(element: ET.Element) -> dict[str, Any] | str:
    """Convert an XML element to a dictionary recursively."""
    result: dict[str, Any] = {}

    if element.attrib:
        result["@attributes"] = dict(element.attrib)

    children = list(element)
    if not children:
        text = (element.text or "").strip()
        if result:
            if text:
                result["#text"] = text
            return result
        return text

    for child in children:
        tag = child.tag
        child_data = _xml_to_dict(child)

        if tag in result:
            if not isinstance(result[tag], list):
                result[tag] = [result[tag]]
            result[tag].append(child_data)
        else:
            result[tag] = child_data

    text = (element.text or "").strip()
    if text:
        result["#text"] = text

    return result


class NCBIClient:
    """Async client for the NCBI E-utilities API.

    Supports optional API key for increased rate limits (10 req/s vs 3 req/s).
    Set NCBI_API_KEY environment variable to use.
    """

    def __init__(self) -> None:
        self._api_key = os.environ.get("NCBI_API_KEY", "")
        self._email = os.environ.get("NCBI_EMAIL", "")
        self._http = httpx.AsyncClient(base_url=BASE_URL, timeout=30.0)

    async def close(self) -> None:
        await self._http.aclose()

    def _base_params(self) -> dict[str, str]:
        """Build common parameters included in every request.

        NCBI best practices: always include tool name, email, and API key
        so NCBI can contact you and grant higher rate limits.
        """
        params: dict[str, str] = {"tool": "thinktank-ncbi-mcp"}
        if self._api_key:
            params["api_key"] = self._api_key
        if self._email:
            params["email"] = self._email
        return params

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> httpx.Response:
        """Make a GET request with retry logic."""
        request_params = {**self._base_params(), **(params or {})}
        logger.debug(f"GET {path} params={request_params}")
        resp = await self._http.get(path, params={k: v for k, v in request_params.items() if v is not None})
        resp.raise_for_status()
        return resp

    async def _get_json(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a GET request and return JSON."""
        resp = await self._get(path, params)
        return resp.json()

    async def _get_xml(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make a GET request and parse XML response to dict."""
        resp = await self._get(path, params)
        text = resp.text
        try:
            root = ET.fromstring(text)
            parsed = _xml_to_dict(root)
            return parsed if isinstance(parsed, dict) else {"result": parsed}
        except ET.ParseError as e:
            raise NCBIAPIError(f"Failed to parse XML response: {e}")

    async def search(
        self,
        db: str,
        term: str,
        retmax: int = 20,
        retstart: int = 0,
        sort: str | None = None,
        date_type: str | None = None,
        min_date: str | None = None,
        max_date: str | None = None,
        use_history: bool = False,
    ) -> dict[str, Any]:
        """Search an NCBI database (ESearch).

        Returns UIDs matching the query along with count and pagination info.
        """
        params: dict[str, Any] = {
            "db": db,
            "term": term,
            "retmax": min(max(0, retmax), 10000),
            "retstart": max(0, retstart),
            "retmode": "json",
        }
        if sort:
            params["sort"] = sort
        if date_type:
            params["datetype"] = date_type
        if min_date:
            params["mindate"] = min_date
        if max_date:
            params["maxdate"] = max_date
        if use_history:
            params["usehistory"] = "y"

        body = await self._get_json("/esearch.fcgi", params)
        result = body.get("esearchresult", {})

        # Check for errors
        error_list = result.get("ERROR", result.get("ErrorList", {}))
        if error_list:
            raise NCBIAPIError(f"Search error: {error_list}")

        return {
            "count": int(result.get("count", 0)),
            "retmax": int(result.get("retmax", 0)),
            "retstart": int(result.get("retstart", 0)),
            "ids": result.get("idlist", []),
            "queryTranslation": result.get("querytranslation", ""),
            "webenv": result.get("webenv", ""),
            "queryKey": result.get("querykey", ""),
        }

    async def summary(
        self,
        db: str,
        ids: str,
        retstart: int = 0,
        retmax: int = 20,
    ) -> dict[str, Any]:
        """Get document summaries for UIDs (ESummary).

        Returns lightweight metadata for each record.
        """
        params: dict[str, Any] = {
            "db": db,
            "id": ids,
            "retmode": "json",
            "version": "2.0",
            "retstart": max(0, retstart),
            "retmax": min(max(1, retmax), 500),
        }

        body = await self._get_json("/esummary.fcgi", params)
        result_container = body.get("result", {})

        # Extract UIDs list and individual records
        uids = result_container.get("uids", [])
        records = []
        for uid in uids:
            record = result_container.get(uid)
            if record:
                records.append(record)

        return {"uids": uids, "records": records}

    async def fetch(
        self,
        db: str,
        ids: str,
        rettype: str | None = None,
        retmode: str | None = None,
        retstart: int = 0,
        retmax: int = 20,
    ) -> dict[str, Any]:
        """Fetch full records by UID (EFetch).

        Returns complete data in the specified format.
        For PubMed: use rettype="abstract" for abstracts, "xml" for full XML.
        For Nucleotide/Protein: use rettype="fasta" for sequences.
        """
        params: dict[str, Any] = {
            "db": db,
            "id": ids,
            "retstart": max(0, retstart),
            "retmax": min(max(1, retmax), 500),
        }
        if rettype:
            params["rettype"] = rettype
        if retmode:
            params["retmode"] = retmode

        # For JSON-capable requests, try JSON first
        if retmode == "json" or (not retmode and not rettype):
            params["retmode"] = "xml"

        resp = await self._get("/efetch.fcgi", params)
        content_type = resp.headers.get("content-type", "")

        if "xml" in content_type or resp.text.strip().startswith("<?xml") or resp.text.strip().startswith("<"):
            try:
                root = ET.fromstring(resp.text)
                parsed = _xml_to_dict(root)
                return parsed if isinstance(parsed, dict) else {"result": parsed}
            except ET.ParseError:
                return {"text": resp.text[:10000]}
        else:
            # Return plain text (e.g., FASTA sequences)
            return {"text": resp.text[:10000]}

    async def link(
        self,
        dbfrom: str,
        db: str,
        ids: str,
        linkname: str | None = None,
        cmd: str = "neighbor",
    ) -> dict[str, Any]:
        """Find related records across databases (ELink).

        Discovers cross-references between NCBI databases.
        """
        params: dict[str, Any] = {
            "dbfrom": dbfrom,
            "db": db,
            "id": ids,
            "cmd": cmd,
            "retmode": "json",
        }
        if linkname:
            params["linkname"] = linkname

        body = await self._get_json("/elink.fcgi", params)
        linksets = body.get("linksets", [])

        results = []
        for linkset in linksets:
            linkset_dbs = linkset.get("linksetdbs", [])
            for lsdb in linkset_dbs:
                results.append({
                    "dbTo": lsdb.get("dbto", ""),
                    "linkName": lsdb.get("linkname", ""),
                    "ids": [link.get("id", "") for link in lsdb.get("links", [])],
                })

        return {"linksets": results}

    async def info(self, db: str | None = None) -> dict[str, Any]:
        """Get database statistics and field information (EInfo).

        Without a db parameter, returns the list of all available databases.
        With a db parameter, returns field descriptions and link information.
        """
        params: dict[str, Any] = {"retmode": "json"}
        if db:
            params["db"] = db

        body = await self._get_json("/einfo.fcgi", params)
        einfo = body.get("einforesult", {})

        if not db:
            return {"databases": einfo.get("dblist", [])}

        db_info = einfo.get("dbinfo", [{}])[0] if isinstance(einfo.get("dbinfo"), list) else einfo.get("dbinfo", {})
        return {
            "dbName": db_info.get("dbname", ""),
            "description": db_info.get("description", ""),
            "count": db_info.get("count", ""),
            "lastUpdate": db_info.get("lastupdate", ""),
            "fields": [
                {
                    "name": f.get("name", ""),
                    "fullName": f.get("fullname", ""),
                    "description": f.get("description", ""),
                    "termCount": f.get("termcount", ""),
                    "isDate": f.get("isdate", ""),
                    "isNumerical": f.get("isnumerical", ""),
                }
                for f in db_info.get("fieldlist", [])
            ],
            "links": [
                {
                    "name": l.get("name", ""),
                    "menu": l.get("menu", ""),
                    "description": l.get("description", ""),
                    "dbTo": l.get("dbto", ""),
                }
                for l in db_info.get("linklist", [])
            ],
        }

    async def spell(self, db: str, term: str) -> dict[str, Any]:
        """Get spelling suggestions for a search term (ESpell).

        Useful for correcting misspellings in biomedical queries.
        """
        params: dict[str, Any] = {
            "db": db,
            "term": term,
        }

        result = await self._get_xml("/espell.fcgi", params)
        return {
            "original": result.get("Query", ""),
            "corrected": result.get("CorrectedQuery", ""),
        }

    async def global_query(self, term: str) -> dict[str, Any]:
        """Search across all NCBI databases simultaneously (EGQuery).

        Returns hit counts per database for a given query term.
        """
        params: dict[str, Any] = {"term": term, "retmode": "xml"}

        result = await self._get_xml("/egquery.fcgi", params)

        counts = []
        result_items = result.get("eGQueryResult", {})
        if isinstance(result_items, dict):
            items = result_items.get("ResultItem", [])
            if not isinstance(items, list):
                items = [items]
            for item in items:
                if isinstance(item, dict):
                    count = item.get("Count", "0")
                    if isinstance(count, dict):
                        count = count.get("#text", "0")
                    db_name = item.get("DbName", "")
                    if isinstance(db_name, dict):
                        db_name = db_name.get("#text", "")
                    menu_name = item.get("MenuName", "")
                    if isinstance(menu_name, dict):
                        menu_name = menu_name.get("#text", "")
                    status = item.get("Status", "")
                    if isinstance(status, dict):
                        status = status.get("#text", "")
                    counts.append({
                        "dbName": db_name,
                        "menuName": menu_name,
                        "count": int(count) if count.isdigit() else 0,
                        "status": status,
                    })

        # Sort by count descending, filter out zero-count databases
        counts = sorted([c for c in counts if c["count"] > 0], key=lambda x: x["count"], reverse=True)
        return {"term": term, "results": counts}

    async def citmatch(self, citations: list[dict[str, str]]) -> dict[str, Any]:
        """Match bibliographic citations to PubMed IDs (ECitMatch).

        Each citation should have keys: journal, year, volume, first_page, author_name, key.
        """
        bdata_parts = []
        for cit in citations:
            parts = [
                cit.get("journal", ""),
                cit.get("year", ""),
                cit.get("volume", ""),
                cit.get("first_page", ""),
                cit.get("author_name", ""),
                cit.get("key", ""),
            ]
            bdata_parts.append("|".join(parts) + "|")

        params: dict[str, Any] = {
            "db": "pubmed",
            "retmode": "xml",
            "bdata": "\r".join(bdata_parts),
        }

        resp = await self._get("/ecitmatch.cgi", params)
        text = resp.text.strip()

        results = []
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            parts = line.split("|")
            result: dict[str, str] = {
                "journal": parts[0] if len(parts) > 0 else "",
                "year": parts[1] if len(parts) > 1 else "",
                "volume": parts[2] if len(parts) > 2 else "",
                "firstPage": parts[3] if len(parts) > 3 else "",
                "authorName": parts[4] if len(parts) > 4 else "",
                "key": parts[5] if len(parts) > 5 else "",
                "pmid": parts[6] if len(parts) > 6 else "",
            }
            results.append(result)

        return {"matches": results}
