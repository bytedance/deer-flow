# InfoQuest result safety

Result URLs in `organic[].url`, `top_stories.items[].url`, and
`images_results[].original` use
`community.url_safety.safe_public_result_url` (imported as `_safe_public_url`);
do not add a provider-local copy. Return the screened value and deduplicate
on that value. Drop rejected rows while retaining valid rows in order.

Web and image searches require a `search_result` envelope. Unknown response
shapes return the provider's format error; never return the raw payload as a
fallback, because that bypasses result-URL screening. Missing, null, or empty
result containers within a valid envelope retain their empty-result behavior.
Log missing envelope names without queries, credentials, or payload values.

Screening is string-only and performs no DNS lookup. Downloaders must still
validate resolved addresses at connection time through the shared fetch policy.
Keep fetch behavior and HTTP timeout handling unchanged.

Tests: `backend/tests/test_infoquest_result_url_safety.py`,
`backend/tests/test_image_result_url_safety.py`, and
`backend/tests/test_infoquest_client.py` (all offline).
