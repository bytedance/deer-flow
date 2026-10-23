"""Read rows from maintained Jsonify datasets.

Jsonify pipelines run on a schedule, repair themselves when a source changes,
and publish the result as a dataset. Each dataset has a serve URL that returns
its latest rows as JSON with paging, column selection, exact-match filters and
version pinning. The URL is the credential: it is configured by the operator,
never passed by the model, and scrubbed from any error text.

Configure one entry per deployment with a named map of datasets::

    - name: jsonify_dataset_rows
      group: data
      use: deerflow.community.jsonify.tools:dataset_rows_tool
      datasets:
        llm_api_pricing: $JSONIFY_LLM_PRICING_URL
      max_rows: 100
      timeout: 30
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx
from langchain_core.tools import StructuredTool
from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, ValidationError, field_validator

from deerflow.community.provider_credentials import redact_secret, reject_url_userinfo
from deerflow.community.url_safety import validate_public_http_url
from deerflow.config import get_app_config

logger = logging.getLogger(__name__)

_TOOL_NAME = "jsonify_dataset_rows"
_PAGE_SIZE = 1000
_MAX_FILTERS = 10
_SYSTEM_COLUMNS = ("_parent_row_id", "_source_key")


class _JsonifySettings(BaseModel):
    """Validated provider settings stored on the tool entry."""

    model_config = ConfigDict(validate_default=True)

    datasets: dict[str, AnyHttpUrl] = Field(min_length=1, max_length=50)
    max_rows: int = Field(default=100, ge=1, le=10_000)
    timeout: float = Field(default=30, gt=0, le=600)

    @field_validator("datasets")
    @classmethod
    def _check_urls(cls, value: dict[str, AnyHttpUrl]) -> dict[str, AnyHttpUrl]:
        for name, url in value.items():
            if not name.strip():
                raise ValueError("dataset names must not be blank")
            reject_url_userinfo(url)
            if url.scheme != "https":
                raise ValueError(f"dataset '{name}': serve URL must use https")
        return value


class _RowsArgs(BaseModel):
    dataset: str = Field(description="Name of the configured dataset to read.")
    filters: dict[str, str] | None = Field(
        default=None,
        description="Exact, case-sensitive column matches combined with AND, for example {'provider': 'Anthropic'}. Up to 10.",
    )
    columns: list[str] | None = Field(default=None, description="Column names to return. Omit for all columns.")
    limit: int = Field(default=50, ge=1, description="Maximum number of rows to return.")


def _load_settings() -> _JsonifySettings | str:
    config = get_app_config().get_tool_config(_TOOL_NAME)
    extra = dict(config.model_extra or {}) if config is not None else {}
    try:
        return _JsonifySettings(**extra)
    except ValidationError as exc:
        # Log only where and why validation failed; the input values are serve URLs, which are credentials.
        problems = "; ".join(f"{'.'.join(str(part) for part in err['loc']) or '<root>'}: {err['type']}" for err in exc.errors())
        logger.warning("Invalid %s configuration: %s", _TOOL_NAME, problems)
        return f"Error: {_TOOL_NAME} is not configured. Add a 'datasets' map of name to serve URL in config.yaml."


def _build_params(
    *,
    limit: int,
    offset: int,
    columns: list[str] | None,
    filters: dict[str, str] | None,
    version: int | None,
) -> dict[str, Any]:
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if columns:
        params["columns"] = ",".join(c.strip() for c in columns if c.strip())
    if version is not None:
        params["version"] = version
    for column, value in (filters or {}).items():
        params[f"filter[{column}]"] = value
    return params


async def _read_rows(settings: _JsonifySettings, args: _RowsArgs) -> dict[str, Any]:
    serve_url = str(settings.datasets[args.dataset])
    url_error = await asyncio.to_thread(validate_public_http_url, serve_url, action="read")
    if url_error:
        raise ValueError(url_error)

    max_rows = min(args.limit, settings.max_rows)
    rows: list[dict[str, Any]] = []
    meta: dict[str, Any] = {}
    offset = 0
    version: int | None = None
    truncated = False
    async with httpx.AsyncClient(timeout=settings.timeout) as client:
        while True:
            limit = min(_PAGE_SIZE, max_rows - len(rows))
            response = await client.get(
                serve_url,
                params=_build_params(limit=limit, offset=offset, columns=args.columns, filters=args.filters, version=version),
            )
            response.raise_for_status()
            page = _parse_page(response)
            if not meta:
                meta = {
                    "dataset": args.dataset,
                    "dataset_name": page.get("dataset_name"),
                    "table": page.get("table"),
                    "version": page.get("version"),
                    "updated_at": page.get("updated_at"),
                }
            if version is None:
                version = page.get("version")
            page_rows = [{k: v for k, v in row.items() if k not in _SYSTEM_COLUMNS} for row in page["rows"]]
            rows.extend(page_rows)
            has_more = bool(page.get("has_more"))
            next_offset = page.get("next_offset")
            if len(rows) >= max_rows:
                truncated = has_more or len(rows) > max_rows
                break
            # Stop on an empty page or a cursor that does not advance, so a misbehaving endpoint cannot spin the loop.
            if not has_more or not page_rows or not isinstance(next_offset, int) or next_offset <= offset:
                break
            offset = next_offset

    del rows[max_rows:]
    return {**meta, "row_count": len(rows), "truncated": truncated, "rows": rows}


def _parse_page(response: httpx.Response) -> dict[str, Any]:
    """Decode one serve response and check it has the expected shape."""
    try:
        page = response.json()
    except ValueError as exc:
        raise ValueError("Jsonify returned a response that is not JSON") from exc
    rows = page.get("rows") if isinstance(page, dict) else None
    if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
        raise ValueError("Jsonify returned an unexpected response shape")
    return page


async def _dataset_rows(
    dataset: str,
    filters: dict[str, str] | None = None,
    columns: list[str] | None = None,
    limit: int = 50,
) -> str:
    settings = _load_settings()
    if isinstance(settings, str):
        return settings
    if dataset not in settings.datasets:
        available = ", ".join(sorted(settings.datasets))
        return f"Error: Unknown dataset '{dataset}'. Available datasets: {available}"
    if filters and len(filters) > _MAX_FILTERS:
        return f"Error: At most {_MAX_FILTERS} filters are supported"

    serve_url = str(settings.datasets[dataset])
    try:
        args = _RowsArgs(dataset=dataset, filters=filters, columns=columns, limit=limit)
        result = await _read_rows(settings, args)
    except (ValidationError, ValueError, TypeError, AttributeError) as exc:
        return redact_secret(f"Error: {exc}", serve_url)
    except httpx.HTTPStatusError as exc:
        return redact_secret(f"Error: Jsonify returned HTTP {exc.response.status_code}", serve_url)
    except httpx.HTTPError as exc:
        return f"Error: Could not reach Jsonify: {type(exc).__name__}"
    return json.dumps(result, ensure_ascii=False)


dataset_rows_tool = StructuredTool.from_function(
    coroutine=_dataset_rows,
    name=_TOOL_NAME,
    description=(
        "Read rows from a maintained Jsonify dataset. Rows are the latest published output of a scheduled, "
        "self-repairing pipeline, so they are current without scraping. Pass the dataset name, optional exact-match "
        "filters, optional columns and a row limit. Returns JSON with dataset metadata, version, updated_at, rows and a truncated flag that is true when more rows matched than were returned."
    ),
    args_schema=_RowsArgs,
)
