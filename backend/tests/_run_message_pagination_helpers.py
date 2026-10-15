from fastapi.testclient import TestClient


def assert_run_message_page(
    client: TestClient,
    url: str,
    *,
    expected_seq: list[int],
    has_more: bool = True,
) -> None:
    response = client.get(url)

    assert response.status_code == 200
    body = response.json()
    assert body["has_more"] is has_more
    assert [m["seq"] for m in body["data"]] == expected_seq
