"""World Bank Open Data MCP Server.

Exposes World Bank API data (countries, indicators, economic data) via MCP tools.
"""

import json
import sys

from mcp.server.fastmcp import FastMCP

from worldbank_mcp.api_client import WorldBankClient, WorldBankAPIError

mcp = FastMCP("worldbank")
client = WorldBankClient()


@mcp.tool()
async def worldbank_list_countries(
    region: str | None = None,
    income_level: str | None = None,
    per_page: int = 50,
    page: int = 1,
) -> str:
    """List countries from the World Bank database with optional filters.

    Args:
        region: Filter by region code. Common codes:
            EAS (East Asia & Pacific), ECS (Europe & Central Asia),
            LCN (Latin America & Caribbean), MEA (Middle East & North Africa),
            NAC (North America), SAS (South Asia), SSF (Sub-Saharan Africa)
        income_level: Filter by income level code:
            HIC (High income), UMC (Upper middle income),
            LMC (Lower middle income), LIC (Low income)
        per_page: Results per page (max 300)
        page: Page number
    """
    try:
        per_page = max(1, min(per_page, 300))
        result = await client.list_countries(region=region, income_level=income_level, per_page=per_page, page=page)
        return json.dumps(result, ensure_ascii=False)
    except (WorldBankAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def worldbank_search_indicators(
    query: str,
    topic: int | None = None,
    per_page: int = 20,
    page: int = 1,
) -> str:
    """Search World Bank development indicators by keyword.

    Common indicator codes for reference:
        SP.POP.TOTL - Population, total
        NY.GDP.MKTP.CD - GDP (current US$)
        NY.GDP.PCAP.CD - GDP per capita (current US$)
        NY.GDP.MKTP.KD.ZG - GDP growth (annual %)
        SI.POV.DDAY - Poverty headcount ratio at $2.15/day
        SE.ADT.LITR.ZS - Literacy rate, adult total
        SL.UEM.TOTL.ZS - Unemployment, total
        SP.DYN.LE00.IN - Life expectancy at birth
        EN.ATM.CO2E.PC - CO2 emissions (metric tons per capita)
        FP.CPI.TOTL.ZG - Inflation, consumer prices (annual %)

    Args:
        query: Search keyword (e.g., "GDP", "poverty", "education")
        topic: Optional topic ID filter (1-21). Topics include:
            1=Agriculture, 2=Aid, 3=Economy, 4=Education, 5=Energy,
            6=Environment, 7=Financial, 8=Health, 9=Infrastructure,
            10=Social Protection, 11=Poverty, 13=Public Sector,
            14=Science & Tech, 15=Social Development, 16=Urban,
            17=Gender, 18=Millenium Goals, 19=Climate Change, 20=External Debt, 21=Trade
        per_page: Results per page
        page: Page number
    """
    try:
        per_page = max(1, min(per_page, 300))
        result = await client.search_indicators(query=query, topic=topic, per_page=per_page, page=page)
        return json.dumps(result, ensure_ascii=False)
    except (WorldBankAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def worldbank_get_indicator_data(
    country_codes: str,
    indicator_code: str,
    start_year: int | None = None,
    end_year: int | None = None,
    per_page: int = 100,
    page: int = 1,
) -> str:
    """Fetch indicator time-series data for one or more countries.

    Args:
        country_codes: Semicolon-separated ISO country codes (e.g., "USA;CHN;DEU")
            Use "all" for all countries.
        indicator_code: World Bank indicator code (e.g., "NY.GDP.PCAP.CD").
            Use worldbank_search_indicators to find codes.
        start_year: Start of date range (e.g., 2000)
        end_year: End of date range (e.g., 2023)
        per_page: Results per page (max 1000)
        page: Page number
    """
    try:
        per_page = max(1, min(per_page, 1000))
        result = await client.get_indicator_data(
            country_codes=country_codes,
            indicator_code=indicator_code,
            start_year=start_year,
            end_year=end_year,
            per_page=per_page,
            page=page,
        )
        return json.dumps(result, ensure_ascii=False)
    except (WorldBankAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


def main():
    """Entry point for the worldbank-mcp CLI."""
    print("World Bank MCP server starting...", file=sys.stderr)
    mcp.run(transport="stdio")
