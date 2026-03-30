from deerflow.sandbox.bash_path_validation import extract_absolute_path_candidates


def test_extract_absolute_path_candidates_keeps_unix_paths() -> None:
    assert extract_absolute_path_candidates("cat /etc/passwd >/mnt/user-data/workspace/out.txt") == [
        "/etc/passwd",
        "/mnt/user-data/workspace/out.txt",
    ]


def test_extract_absolute_path_candidates_ignores_https_urls() -> None:
    assert extract_absolute_path_candidates("curl -X POST https://example.com/api/v1/risk/check") == []


# ---------------------------------------------------------------------------
# Additional edge-case coverage
# ---------------------------------------------------------------------------


def test_ignores_http_urls() -> None:
    assert extract_absolute_path_candidates("curl http://internal.service/health") == []


def test_ignores_ftp_urls() -> None:
    assert extract_absolute_path_candidates("wget ftp://files.example.com/pub/data.tar.gz") == []


def test_ignores_port_slash_path() -> None:
    # The /path portion after a port number is preceded by a digit (\w) so it must be excluded.
    assert extract_absolute_path_candidates("curl http://localhost:8080/api/v1/endpoint") == []


def test_empty_command_returns_empty_list() -> None:
    assert extract_absolute_path_candidates("") == []


def test_command_with_no_paths_returns_empty_list() -> None:
    assert extract_absolute_path_candidates("echo hello world") == []


def test_path_after_pipe_operator() -> None:
    result = extract_absolute_path_candidates("cat /etc/hosts | grep localhost")
    assert "/etc/hosts" in result


def test_path_after_semicolon_is_detected() -> None:
    # Semicolons terminate a path token but don't prevent detection of the path that follows.
    result = extract_absolute_path_candidates("echo done; cat /tmp/output.txt")
    assert "/tmp/output.txt" in result


def test_multiple_paths_in_copy_command() -> None:
    result = extract_absolute_path_candidates("cp /src/data/input.csv /dst/results/output.csv")
    assert "/src/data/input.csv" in result
    assert "/dst/results/output.csv" in result


def test_path_as_first_token() -> None:
    result = extract_absolute_path_candidates("/usr/bin/python3 script.py")
    assert "/usr/bin/python3" in result


def test_redirect_target_path_is_extracted() -> None:
    result = extract_absolute_path_candidates("echo hello > /tmp/out.txt")
    assert "/tmp/out.txt" in result


def test_word_char_prefix_excludes_embedded_slash() -> None:
    # "abc/def" — preceded by a word char, so no absolute path detected.
    assert extract_absolute_path_candidates("abc/def/ghi") == []


def test_mixed_url_and_local_path() -> None:
    result = extract_absolute_path_candidates("curl https://example.com/download -o /tmp/file.bin")
    assert result == ["/tmp/file.bin"]


def test_path_with_dots_and_underscores() -> None:
    result = extract_absolute_path_candidates("cat /mnt/user-data/uploads/my_file.md")
    assert "/mnt/user-data/uploads/my_file.md" in result


def test_virtual_upload_path_is_extracted() -> None:
    result = extract_absolute_path_candidates("python /mnt/user-data/workspace/process.py")
    assert "/mnt/user-data/workspace/process.py" in result
