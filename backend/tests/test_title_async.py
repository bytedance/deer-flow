import time
from types import SimpleNamespace

from src.agents.middlewares.title_middleware import TitleMiddleware
from src.agents.title.updater import TitleGenerationTask, TitleGenerationUpdater
from src.config.title_config import TitleConfig, get_title_config, set_title_config


def _message(msg_type: str, content: str):
    return SimpleNamespace(type=msg_type, content=content)


def test_title_middleware_queues_async_work(monkeypatch):
    queued = []

    class QueueStub:
        def add(self, thread_id, messages):
            queued.append((thread_id, messages))

    monkeypatch.setattr("src.agents.middlewares.title_middleware.get_title_queue", lambda: QueueStub())
    middleware = TitleMiddleware()

    state = {
        "messages": [
            _message("human", "What is memory middleware?"),
            _message("ai", "It stores long-term context."),
        ]
    }
    runtime = SimpleNamespace(context={"thread_id": "thread-1"})

    result = middleware.after_agent(state, runtime)

    assert result is None
    assert len(queued) == 1
    assert queued[0][0] == "thread-1"


def test_updater_falls_back_after_timeout(monkeypatch):
    class SlowModel:
        def invoke(self, prompt):
            time.sleep(0.2)
            return SimpleNamespace(content="ignored")

    original = get_title_config()
    set_title_config(TitleConfig(timeout_seconds=0.01, max_retries=0, max_chars=20))
    monkeypatch.setattr("src.agents.title.updater.create_chat_model", lambda **kwargs: SlowModel())

    updater = TitleGenerationUpdater(client_factory=lambda url: None)
    title = updater.generate_title([_message("human", "A long first message for fallback title")])

    set_title_config(original)
    assert title.startswith("A long first message")


def test_updater_does_not_override_manual_title(monkeypatch):
    updates = []

    class ThreadsStub:
        def get_state(self, thread_id):
            return {"values": {"title": "Manual Name"}, "checkpoint": {"checkpoint_id": "c1"}}

        def update_state(self, thread_id, values, checkpoint=None, as_node=None):
            updates.append((thread_id, values, checkpoint, as_node))

    class ClientStub:
        def __init__(self):
            self.threads = ThreadsStub()

        def close(self):
            return None

    updater = TitleGenerationUpdater(client_factory=lambda url: ClientStub())
    updater.process(TitleGenerationTask(thread_id="thread-2", messages=[_message("human", "x")]))

    assert updates == []


def test_updater_updates_when_title_is_untitled(monkeypatch):
    updates = []

    class FastModel:
        def invoke(self, prompt):
            return SimpleNamespace(content='"Short title"')

    class ThreadsStub:
        def get_state(self, thread_id):
            return {"values": {"title": "Untitled"}, "checkpoint": {"checkpoint_id": "c2"}}

        def update_state(self, thread_id, values, checkpoint=None, as_node=None):
            updates.append((thread_id, values, checkpoint, as_node))

    class ClientStub:
        def __init__(self):
            self.threads = ThreadsStub()

        def close(self):
            return None

    monkeypatch.setattr("src.agents.title.updater.create_chat_model", lambda **kwargs: FastModel())
    updater = TitleGenerationUpdater(client_factory=lambda url: ClientStub())
    updater.process(
        TitleGenerationTask(
            thread_id="thread-3",
            messages=[_message("human", "User ask"), _message("ai", "Assistant answer")],
        )
    )

    assert len(updates) == 1
    assert updates[0][1] == {"title": "Short title"}
    assert updates[0][3] == "title_middleware"
