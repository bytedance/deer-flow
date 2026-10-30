# Image Search

DDG, Brave, and Serper `image_search` screen returned image, thumbnail and
source page URLs with `community.url_safety.safe_public_result_url`. This pure
string check does not resolve hostnames; any later downloader must enforce its
own connection-time address policy. The screen reuses `is_blocked_address` for
literal and embedded IPv4 addresses, including multicast/reserved forms. Shared
regression coverage is in `tests/test_image_result_url_safety.py`; DDG tool
coverage is in `tests/test_ddg_image_search_urls.py`.

Normalize IDNA's Unicode dot separators before checking blocked hostnames or IP
literals; preserve the original URL for allowed results. Client-normalization
regressions are in `tests/test_image_result_idna_hosts.py`.
