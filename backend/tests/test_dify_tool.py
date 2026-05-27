from zens.community.dify.dify_client import DifyAPIError, DifyClient, DifyResponse


def test_dify_response_model():
    r = DifyResponse(answer="hello", conversation_id="conv123", message_id="msg456")
    assert r.answer == "hello"
    assert r.conversation_id == "conv123"
    assert r.message_id == "msg456"


def test_dify_api_error():
    e = DifyAPIError(401, "invalid api key")
    assert e.status_code == 401
    assert "401" in str(e)
    assert "invalid api key" in str(e)


def test_dify_client_chat_request(monkeypatch):
    client = DifyClient(api_key="test-key", base_url="http://localhost:8000")
    recorded_request = {}

    class FakeResponse:
        status_code = 200
        is_success = True

        def json(self):
            return {"answer": "hi", "conversation_id": "conv-new", "message_id": "msg-new"}

    class FakeHttpx:
        def post(self, url, **kwargs):
            recorded_request["url"] = url
            recorded_request["headers"] = kwargs.get("headers")
            recorded_request["json"] = kwargs.get("json")
            return FakeResponse()

    import zens.community.dify.dify_client as mod

    monkeypatch.setattr(mod, "httpx", FakeHttpx())
    response = client.chat(query="hello", conversation_id="", user="u1")
    assert response.answer == "hi"
    assert recorded_request["json"]["query"] == "hello"
    assert recorded_request["json"]["response_mode"] == "blocking"
