"""U.S. Treasury Fiscal Data MCP Server.

Exposes Treasury fiscal datasets (national debt, interest rates, exchange rates, etc.) via MCP tools.
"""

import json
import sys

from mcp.server.fastmcp import FastMCP

from api_client import FiscalDataAPIError, FiscalDataClient

mcp = FastMCP("fiscaldata")
client = FiscalDataClient()


@mcp.tool()
async def fiscaldata_get_national_debt(
    start_date: str | None = None,
    end_date: str | None = None,
    fields: str | None = None,
    sort: str = "-record_date",
    page_size: int = 100,
    page: int = 1,
) -> str:
    """Query the U.S. national debt from the "Debt to the Penny" dataset (daily data).

    Key fields: record_date, tot_pub_debt_out_amt (total public debt outstanding),
    debt_held_public_amt (debt held by the public), intragov_hold_amt (intragovernmental holdings).

    Args:
        start_date: Start date filter (YYYY-MM-DD)
        end_date: End date filter (YYYY-MM-DD)
        fields: Comma-separated field names to return (e.g., "record_date,tot_pub_debt_out_amt")
        sort: Sort order, prefix with - for descending (default: "-record_date")
        page_size: Results per page, max 10000 (default: 100)
        page: Page number (default: 1)
    """
    try:
        page_size = max(1, min(page_size, 10000))
        result = await client.get_debt_to_penny(
            start_date=start_date, end_date=end_date, fields=fields, sort=sort, page_size=page_size, page=page
        )
        return json.dumps(result, ensure_ascii=False)
    except (FiscalDataAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def fiscaldata_get_interest_rates(
    start_date: str | None = None,
    end_date: str | None = None,
    security_type: str | None = None,
    fields: str | None = None,
    sort: str = "-record_date",
    page_size: int = 100,
    page: int = 1,
) -> str:
    """Query average interest rates on U.S. Treasury securities (monthly data).

    Key fields: record_date, security_desc, avg_interest_rate_amt.
    Security types include: Treasury Bonds, Treasury Notes, Treasury Bills,
    Treasury Inflation-Protected Securities (TIPS), Treasury Floating Rate Notes (FRN).

    Args:
        start_date: Start date filter (YYYY-MM-DD)
        end_date: End date filter (YYYY-MM-DD)
        security_type: Filter by security description (e.g., "Treasury Bonds")
        fields: Comma-separated field names to return
        sort: Sort order (default: "-record_date")
        page_size: Results per page, max 10000 (default: 100)
        page: Page number (default: 1)
    """
    try:
        page_size = max(1, min(page_size, 10000))
        result = await client.get_interest_rates(
            start_date=start_date, end_date=end_date, security_type=security_type,
            fields=fields, sort=sort, page_size=page_size, page=page,
        )
        return json.dumps(result, ensure_ascii=False)
    except (FiscalDataAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def fiscaldata_get_exchange_rates(
    start_date: str | None = None,
    end_date: str | None = None,
    country: str | None = None,
    currency: str | None = None,
    fields: str | None = None,
    sort: str = "-record_date",
    page_size: int = 100,
    page: int = 1,
) -> str:
    """Query Treasury reporting rates of exchange for ~170 currencies (quarterly data).

    Key fields: record_date, country, currency, exchange_rate, effective_date.

    Args:
        start_date: Start date filter (YYYY-MM-DD)
        end_date: End date filter (YYYY-MM-DD)
        country: Filter by country name (e.g., "Japan")
        currency: Filter by currency name (e.g., "Yen")
        fields: Comma-separated field names to return
        sort: Sort order (default: "-record_date")
        page_size: Results per page, max 10000 (default: 100)
        page: Page number (default: 1)
    """
    try:
        page_size = max(1, min(page_size, 10000))
        result = await client.get_exchange_rates(
            start_date=start_date, end_date=end_date, country=country, currency=currency,
            fields=fields, sort=sort, page_size=page_size, page=page,
        )
        return json.dumps(result, ensure_ascii=False)
    except (FiscalDataAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def fiscaldata_get_interest_expense(
    start_date: str | None = None,
    end_date: str | None = None,
    fields: str | None = None,
    sort: str = "-record_date",
    page_size: int = 100,
    page: int = 1,
) -> str:
    """Query interest expense on the U.S. public debt outstanding.

    Key fields: record_date, expense_catg_desc, month_expense_amt, fytd_expense_amt.

    Args:
        start_date: Start date filter (YYYY-MM-DD)
        end_date: End date filter (YYYY-MM-DD)
        fields: Comma-separated field names to return
        sort: Sort order (default: "-record_date")
        page_size: Results per page, max 10000 (default: 100)
        page: Page number (default: 1)
    """
    try:
        page_size = max(1, min(page_size, 10000))
        result = await client.get_interest_expense(
            start_date=start_date, end_date=end_date, fields=fields, sort=sort, page_size=page_size, page=page
        )
        return json.dumps(result, ensure_ascii=False)
    except (FiscalDataAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def fiscaldata_get_treasury_statement(
    table: str = "operating_cash_balance",
    start_date: str | None = None,
    end_date: str | None = None,
    fields: str | None = None,
    sort: str = "-record_date",
    page_size: int = 100,
    page: int = 1,
) -> str:
    """Query the Daily Treasury Statement (DTS) — operating cash, deposits/withdrawals, debt transactions.

    Valid table names:
        operating_cash_balance, deposits_withdrawals_operating_cash,
        public_debt_transactions, adjustment_public_debt_transactions_cash_basis,
        inter_agency_tax_transfers, income_tax_refunds_issued,
        federal_tax_deposits, short_term_cash_investments,
        gulf_coast_restoration_trust_fund

    Args:
        table: DTS table name (default: "operating_cash_balance")
        start_date: Start date filter (YYYY-MM-DD)
        end_date: End date filter (YYYY-MM-DD)
        fields: Comma-separated field names to return
        sort: Sort order (default: "-record_date")
        page_size: Results per page, max 10000 (default: 100)
        page: Page number (default: 1)
    """
    try:
        page_size = max(1, min(page_size, 10000))
        result = await client.get_treasury_statement(
            table=table, start_date=start_date, end_date=end_date,
            fields=fields, sort=sort, page_size=page_size, page=page,
        )
        return json.dumps(result, ensure_ascii=False)
    except (FiscalDataAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def fiscaldata_query_dataset(
    endpoint: str,
    filter: str | None = None,
    fields: str | None = None,
    sort: str | None = None,
    page_size: int = 100,
    page: int = 1,
) -> str:
    """Generic query for any of the 90+ Fiscal Data API endpoints.

    Popular endpoints:
        v2/accounting/od/debt_to_penny - National debt
        v2/accounting/od/avg_interest_rates - Average interest rates
        v1/accounting/od/rates_of_exchange - Exchange rates
        v2/accounting/od/interest_expense - Interest expense
        v2/accounting/od/gold_reserve - Gold reserve
        v2/accounting/od/utf_qtr_balances - Unemployment trust fund
        v1/accounting/dts/operating_cash_balance - Daily Treasury Statement
        v2/accounting/od/statement_net_cost - Statement of net cost
        v2/revenue/rcm - Revenue collections management

    Filter syntax: "field:operator:value" — operators: eq, lt, lte, gt, gte.
    Multiple filters: "field1:eq:val1,field2:gte:val2"
    Example: "record_date:gte:2024-01-01,record_date:lte:2024-12-31"

    Args:
        endpoint: API endpoint path (e.g., "v2/accounting/od/gold_reserve")
        filter: Filter expression (e.g., "record_date:gte:2024-01-01")
        fields: Comma-separated field names to return
        sort: Sort expression (prefix with - for descending)
        page_size: Results per page, max 10000 (default: 100)
        page: Page number (default: 1)
    """
    try:
        page_size = max(1, min(page_size, 10000))
        result = await client.query_dataset(
            endpoint=endpoint, filter_expr=filter, fields=fields, sort=sort, page_size=page_size, page=page
        )
        return json.dumps(result, ensure_ascii=False)
    except (FiscalDataAPIError, Exception) as e:
        return json.dumps({"error": str(e)})


if __name__ == "__main__":
    print("Fiscal Data MCP server starting...", file=sys.stderr)
    mcp.run(transport="stdio")
