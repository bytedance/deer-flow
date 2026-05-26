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


def test_dify_chat_tool_no_api_key(monkeypatch):
    """Verify DifyAPIError is raised when api_key is not configured."""
    import zens.community.dify.tools as tools_mod

    # Mock get_app_config to return a config with no api_key
    class FakeToolConfig:
        model_extra = {}

    class FakeAppConfig:
        def get_tool_config(self, name):
            return FakeToolConfig()

    monkeypatch.setattr(tools_mod, "_get_dify_client", lambda: (_ for _ in ()).throw(DifyAPIError(0, "no key")))

    from zens.community.dify.tools import dify_chat_tool

    try:
        dify_chat_tool.invoke({"query": "hello"})
        assert False, "should have raised DifyAPIError"
    except DifyAPIError as e:
        assert "no key" in str(e)


def test_conversation_id_caching(monkeypatch):
    """Verify conversation_id is cached per (user, thread) and reused."""
    call_count = [0]

    class FakeDifyResponse:
        def __init__(self, conv_id):
            self.conversation_id = conv_id
            self.answer = f"answer for {conv_id}"
            self.message_id = f"msg-{conv_id}"

    class FakeDifyClient:
        def __init__(self, **kwargs):
            pass

        def chat(self, query, conversation_id, user):
            call_count[0] += 1
            if call_count[0] == 1:
                return FakeDifyResponse("conv-1")
            return FakeDifyResponse(f"conv-reuse-{conversation_id}")

    import zens.community.dify.tools as tools_mod

    # Reset state
    tools_mod._conversation_ids.clear()

    class FakeAppConfig:
        def get_tool_config(self, name):
            class FakeToolConfig:
                model_extra = {}

            return FakeToolConfig()

    monkeypatch.setattr(tools_mod, "_get_dify_client", lambda: FakeDifyClient())

    # Capture original function reference before patching
    _original_get_effective_user_id = tools_mod.get_effective_user_id
    tools_mod.get_effective_user_id = lambda: "default"

    class FakeRunnableConfig(dict):
        def get(self, key, default=None):
            if key == "configurable":
                return {"thread_id": "thread-abc"}
            return super().get(key, default)

    # Patch _get_thread_id to capture what config actually arrives as
    captured_thread_id = [None]
    original_get_thread_id = tools_mod._get_thread_id

    def capture_get_thread_id(config):
        result = original_get_thread_id(config)
        captured_thread_id[0] = result
        return result

    tools_mod._get_thread_id = capture_get_thread_id

    cfg = FakeRunnableConfig(configurable={"thread_id": "thread-abc"})

    result1 = tools_mod.dify_chat_tool.invoke({"query": "hello", "config": cfg})
    assert "answer for conv-1" in result1
    # The actual cache key depends on what user_id and thread_id were used inside invoke
    cache_key = f"default:{captured_thread_id[0]}"
    assert tools_mod._conversation_ids.get(cache_key) == "conv-1", f"Expected cache key 'default:{captured_thread_id[0]}' but got {list(tools_mod._conversation_ids.keys())}"

    result2 = tools_mod.dify_chat_tool.invoke({"query": "follow up", "config": cfg})
    assert "conv-reuse-conv-1" in result2
