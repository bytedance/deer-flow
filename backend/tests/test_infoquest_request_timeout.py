"""Request-boundary tests for the InfoQuest community client."""

import json
from unittest.mock import MagicMock, patch

from deerflow.community.infoquest.infoquest_client import InfoQuestClient


@patch("deerflow.community.infoquest.infoquest_client.requests.post")
def test_all_infoquest_requests_have_a_bounded_timeout(mock_post: MagicMock) -> None:
    response = MagicMock()
    response.status_code = 200
    response.text = json.dumps({"reader_result": "content"})
    response.json.return_value = {"search_result": {"results": []}}
    mock_post.return_value = response

    client = InfoQuestClient()
    assert client.fetch("https://example.com") == "content"
    client.web_search_raw_results("query", "")
    client.image_search_raw_results("query")

    assert mock_post.call_count == 3
    timeouts = [call.kwargs.get("timeout") for call in mock_post.call_args_list]
    assert all(isinstance(timeout, (int, float)) and timeout > 0 for timeout in timeouts)
    assert len(set(timeouts)) == 1
