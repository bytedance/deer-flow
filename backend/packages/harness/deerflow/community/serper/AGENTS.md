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

Tests: `backend/tests/test_serper_domain_filters.py` and `test_serper_tools.py`.
Mock HTTP; live Serper semantics remain unverified. See
`backend/docs/CONFIGURATION.md#serper-source-filters` for the operator contract.

`_serper_post` owns default-off physical retries (0–3) and one monotonic
scheduling budget (>0–300s), not cancellation of synchronous I/O. Keep config
validation before transport and retry only connect failures, 502/503/504 and
hinted 429. Provider-local hint parsing avoids coupling to Jina. Whole-tool
extension hooks cannot isolate this boundary. Test with real MockTransport
through both tools in `backend/tests/test_serper_retries.py`.
