# Serper provider

`tools.py` owns web/image search. Keep model-facing arguments unchanged.
Web-only `include_domains`/`exclude_domains` use at most 10 domain-only entries
per list; normalize case, one trailing dot and IDNA, reject invalid configuration
before transport, and enforce exact-host/dot-subdomain matching with deny precedence.
Google `site:` query operators are best-effort; local URL-host filtering is
mandatory even for queries containing operators. Never truncate restrictions,
refill results, or relax scope. The composed query limit is 500 characters;
report the cleaned original query and actual filtered count, including zero.
Image search and unconfigured web behavior retain their existing contracts.
This is source selection, not a fetch policy or factuality check.

Tests: `backend/tests/test_serper_domain_filters.py` and `test_serper_tools.py`.
Mock HTTP; live Serper semantics remain unverified. See
`backend/docs/CONFIGURATION.md#serper-source-filters` for the operator contract.
