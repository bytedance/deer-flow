from deerflow.sandbox.bash_path_validation import extract_absolute_path_candidates


def test_extract_absolute_path_candidates_keeps_unix_paths() -> None:
    assert extract_absolute_path_candidates("cat /etc/passwd >/mnt/user-data/workspace/out.txt") == [
        "/etc/passwd",
        "/mnt/user-data/workspace/out.txt",
    ]


def test_extract_absolute_path_candidates_ignores_https_urls() -> None:
    assert extract_absolute_path_candidates("curl -X POST https://example.com/api/v1/risk/check") == []
