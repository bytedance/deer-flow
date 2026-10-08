# Serper provider

`tools.py` owns web/image search. Keep model-facing arguments unchanged.
Web-only `include_domains`/`exclude_domains` use at most 10 domain-only entries
per list; normalize case, one trailing dot and IDNA, reject invalid configuration
before transport, log validation errors without config/query values, and enforce
exact-host/dot-subdomain matching with deny precedence.
Google `site:` query operators are best-effort; local URL-host filtering is
mandatory even for queries containing operators. Never truncate restrictions,
refill results, or relax scope. The composed query limit is 500 characters;
report the cleaned original query and actual filtered count, including zero.
Image search and unconfigured web behavior retain their existing contracts.
This is source selection, not a fetch policy or factuality check.

`SERPER_BASE_URL` is a shared operator-controlled environment override, outside
model arguments and per-tool config. Trim surrounding whitespace and trailing
slashes; blank values retain the default endpoints. Resolve `/search` or
`/images` once before transport setup so any future retry loop reuses the URL.
Keep the selected tool's API key in `X-API-KEY`, never query parameters. Debug
endpoint diagnostics must omit URL credentials, query, and fragment. Result-URL
guards do not restrict the operator's API host.

Tests: `backend/tests/test_serper_domain_filters.py` and `test_serper_tools.py`.
Mock HTTP; live Serper semantics remain unverified. See
`backend/docs/CONFIGURATION.md#serper-source-filters` for the operator contract.
