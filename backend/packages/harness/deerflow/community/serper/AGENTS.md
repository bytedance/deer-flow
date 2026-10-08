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

Resolve endpoints once in `_serper_post`, before transport setup: a usable
per-tool `base_url` takes precedence over `SERPER_BASE_URL`, then the existing
Serper endpoint. Strip surrounding whitespace and trailing slashes. Require an
absolute HTTP(S) URL with a host and valid port; reject query/fragment markers,
including empty ones, before HTTP without echoing configured values.
Read each tool's config once and pass captured extras to key resolution,
including an empty mapping when config is absent, to keep endpoint/key paired
through hot reload. Settings stay operator-only. Send keys
only via `X-API-KEY`, and preserve result URL validation and model arguments.
Future retries must reuse the resolved endpoint across attempts. Debug endpoint
diagnostics omit URL credentials, query and fragment; result-URL guards do not
restrict the operator's API host.

Tests: `backend/tests/test_serper_domain_filters.py`, `test_serper_tools.py` and
`test_serper_endpoints.py`.
Mock HTTP; live Serper semantics remain unverified. See
`backend/docs/CONFIGURATION.md#serper-source-filters` for the operator contract.
