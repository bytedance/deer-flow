"""NCBI E-utilities MCP Server.

Exposes NCBI Entrez databases (PubMed, Gene, Protein, Nucleotide, SNP, etc.)
via MCP tools. Set NCBI_API_KEY env var for higher rate limits (10 req/s vs 3 req/s).
"""

import json
import sys

from mcp.server.fastmcp import FastMCP

from ncbi_mcp.api_client import DATABASES, NCBIAPIError, NCBIClient

mcp = FastMCP("ncbi")
client = NCBIClient()


@mcp.tool()
async def ncbi_search(
    db: str,
    term: str,
    retmax: int = 20,
    retstart: int = 0,
    sort: str | None = None,
    min_date: str | None = None,
    max_date: str | None = None,
    date_type: str | None = None,
) -> str:
    """Search an NCBI Entrez database for records matching a query.

    Returns matching record IDs (UIDs) with count and pagination.
    Use ncbi_summary or ncbi_fetch to retrieve details for returned IDs.

    Available databases (most commonly used):
        pubmed - Biomedical literature (articles, reviews, clinical trials)
        pmc - Full-text journal articles (PubMed Central)
        gene - Gene records (sequences, maps, pathways, phenotypes)
        protein - Protein sequences (GenBank, RefSeq, PDB, SwissProt)
        nucleotide - DNA/RNA sequences (GenBank, EMBL, DDBJ)
        snp - Single nucleotide polymorphisms and variants
        omim - Genetic disorders (Online Mendelian Inheritance in Man)
        clinvar - Human genomic variants and clinical significance
        taxonomy - Organism taxonomy and phylogenetic data
        mesh - Medical Subject Headings (MeSH vocabulary)
        biosample - Biological source materials used in studies
        structure - 3D macromolecular structures (PDB)

    PubMed search syntax examples:
        "breast cancer" - Simple keyword search
        "breast cancer AND immunotherapy" - Boolean operators
        "Smith J[Author]" - Search by author
        "Nature[Journal]" - Search by journal
        "2023[Date - Publication]" - Search by year
        "review[Publication Type]" - Filter by type
        "breast neoplasms[MeSH Terms]" - MeSH term search

    Args:
        db: Database to search (e.g., "pubmed", "gene", "protein")
        term: Search query using Entrez syntax
        retmax: Maximum number of UIDs to return (max 10000, default 20)
        retstart: Index of first UID to return (for pagination, default 0)
        sort: Sort order. For PubMed: "relevance", "pub_date", "author", "journal".
            For Gene: "relevance", "name", "chromosome"
        min_date: Minimum date filter (YYYY/MM/DD or YYYY/MM or YYYY)
        max_date: Maximum date filter (YYYY/MM/DD or YYYY/MM or YYYY)
        date_type: Date field to filter on. For PubMed: "pdat" (publication),
            "edat" (Entrez), "mdat" (modification)
    """
    try:
        retmax = max(0, min(retmax, 10000))
        result = await client.search(
            db=db, term=term, retmax=retmax, retstart=retstart,
            sort=sort, date_type=date_type, min_date=min_date, max_date=max_date,
        )
        return json.dumps(result, ensure_ascii=False)
    except (NCBIAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def ncbi_summary(
    db: str,
    ids: str,
    retmax: int = 20,
) -> str:
    """Get document summaries for specific NCBI record IDs.

    Returns lightweight metadata (title, authors, dates, etc.) for each record.
    Use this after ncbi_search to get details without fetching full records.

    Response varies by database. Common fields:
        PubMed: title, authors, source (journal), pubdate, volume, issue, pages, doi, pmcid
        Gene: name, description, organism, chromosome, maplocation, summary
        Protein: caption, title, extra (accession), taxid, slen (sequence length)

    Args:
        db: Database name (e.g., "pubmed", "gene", "protein")
        ids: Comma-separated UIDs (e.g., "39109882,39095432" for PubMed,
            "672,675" for Gene). Get these from ncbi_search.
        retmax: Maximum records to return (max 500, default 20)
    """
    try:
        retmax = max(1, min(retmax, 500))
        result = await client.summary(db=db, ids=ids, retmax=retmax)
        return json.dumps(result, ensure_ascii=False)
    except (NCBIAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def ncbi_fetch(
    db: str,
    ids: str,
    rettype: str | None = None,
    retmax: int = 5,
) -> str:
    """Fetch full records from an NCBI database by ID.

    Returns complete data for specified records. Content depends on database and rettype.

    Common rettype values:
        PubMed: "abstract" (text abstracts), "xml" (full MEDLINE XML)
        Nucleotide: "fasta" (FASTA sequence), "gb" (GenBank flat file)
        Protein: "fasta" (FASTA sequence), "gp" (GenPept flat file)
        Gene: "gene_table" (gene table)
        SNP: "xml" (dbSNP XML)

    Args:
        db: Database name (e.g., "pubmed", "gene", "protein", "nucleotide")
        ids: Comma-separated UIDs to fetch (e.g., "39109882" for PubMed,
            "NM_000546" for Nucleotide). Get these from ncbi_search.
        rettype: Return type format. Database-specific (see above).
            Defaults to XML if not specified.
        retmax: Maximum records to fetch (max 500, default 5).
            Keep small for large records like full sequences.
    """
    try:
        retmax = max(1, min(retmax, 500))
        result = await client.fetch(db=db, ids=ids, rettype=rettype, retmax=retmax)
        return json.dumps(result, ensure_ascii=False)
    except (NCBIAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def ncbi_link(
    dbfrom: str,
    db: str,
    ids: str,
    linkname: str | None = None,
) -> str:
    """Find related records across NCBI databases.

    Discovers cross-references between databases (e.g., Gene → Protein,
    PubMed → Gene, Nucleotide → Protein).

    Common cross-database links:
        gene → protein: Gene to protein sequences
        gene → nucleotide: Gene to nucleotide sequences
        gene → pubmed: Gene to related literature
        pubmed → gene: Articles to mentioned genes
        pubmed → pmc: PubMed to full-text articles
        nucleotide → protein: Nucleotide to protein translations
        snp → gene: SNP to associated genes
        clinvar → gene: Clinical variants to genes
        omim → gene: Genetic disorders to genes

    Args:
        dbfrom: Source database (e.g., "gene", "pubmed", "nucleotide")
        db: Target database (e.g., "protein", "pubmed", "gene")
        ids: Comma-separated source UIDs to find links for
        linkname: Specific link type (e.g., "gene_protein", "gene_pubmed_rif").
            If omitted, all available links between the databases are returned.
    """
    try:
        result = await client.link(dbfrom=dbfrom, db=db, ids=ids, linkname=linkname)
        return json.dumps(result, ensure_ascii=False)
    except (NCBIAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def ncbi_info(
    db: str | None = None,
) -> str:
    """Get NCBI database information and searchable fields.

    Without a database name: returns list of all available NCBI databases.
    With a database name: returns searchable fields, link types, record count,
    and last update time.

    Useful for discovering:
    - Which databases are available
    - What search fields a database supports (for building precise queries)
    - What cross-database links exist
    - Database size and freshness

    Args:
        db: Database name (e.g., "pubmed", "gene"). Omit to list all databases.
    """
    try:
        result = await client.info(db=db)
        return json.dumps(result, ensure_ascii=False)
    except (NCBIAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def ncbi_global_search(
    term: str,
) -> str:
    """Search across ALL NCBI databases simultaneously to find where data exists.

    Returns hit counts per database for a given query. Useful as a first step
    to discover which databases contain relevant records before doing
    targeted searches with ncbi_search.

    Example: searching "BRCA1" returns counts for gene, protein, nucleotide,
    pubmed, snp, clinvar, etc. — showing you exactly where to look.

    Args:
        term: Search query (e.g., "BRCA1", "COVID-19", "insulin resistance")
    """
    try:
        result = await client.global_query(term=term)
        return json.dumps(result, ensure_ascii=False)
    except (NCBIAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def ncbi_spell(
    db: str,
    term: str,
) -> str:
    """Get spelling suggestions for a biomedical search term.

    Useful for correcting misspellings in biomedical queries before searching.

    Args:
        db: Database context for spelling check (e.g., "pubmed")
        term: Query with potential misspellings (e.g., "fibrblast grwth factr")
    """
    try:
        result = await client.spell(db=db, term=term)
        return json.dumps(result, ensure_ascii=False)
    except (NCBIAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def ncbi_citmatch(
    citations_json: str,
) -> str:
    """Match bibliographic citations to PubMed IDs.

    Given citation details (journal, year, volume, page, author), finds
    the corresponding PubMed ID (PMID). Useful for resolving references.

    Args:
        citations_json: JSON array of citation objects. Each must have:
            journal (str): Journal title (e.g., "proc natl acad sci u s a")
            year (str): Publication year (e.g., "1991")
            volume (str): Volume number (e.g., "88")
            first_page (str): First page number (e.g., "3248")
            author_name (str): First author last name (e.g., "paull")
            key (str): Your reference key for matching (e.g., "ref1")
    """
    try:
        citations = json.loads(citations_json)
        if not isinstance(citations, list):
            return json.dumps({"error": "citations_json must be a JSON array of citation objects"})
        result = await client.citmatch(citations)
        return json.dumps(result, ensure_ascii=False)
    except json.JSONDecodeError as e:
        return json.dumps({"error": f"Invalid JSON: {e}"})
    except (NCBIAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


def main():
    """Entry point for the ncbi-mcp CLI."""
    print("NCBI E-utilities MCP server starting...", file=sys.stderr)
    mcp.run(transport="stdio")
