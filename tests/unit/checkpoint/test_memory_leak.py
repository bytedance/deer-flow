
from unittest.mock import patch
import mongomock
import src.graph.checkpoint as checkpoint

MONGO_URL = "mongodb://admin:admin@localhost:27017/checkpointing_db?authSource=admin"

def test_memory_leak_check_memory_cleared_after_persistence(monkeypatch):
    """
    Test that InMemoryStore is cleared for a thread after successful persistence.
    This prevents memory leaks for long-running processes.
    """
    with patch("src.graph.checkpoint.MongoClient") as mock_mongo_client:
        # Setup mongomock
        mock_client = mongomock.MongoClient()
        mock_mongo_client.return_value = mock_client
        
        manager = checkpoint.ChatStreamManager(
            checkpoint_saver=True,
            db_uri=MONGO_URL,
        )
        
        thread_id = "leak_test_thread"
        namespace = ("messages", thread_id)
        
        # 1. Simulate streaming messages
        manager.process_stream_message(thread_id, "Hello", "partial")
        manager.process_stream_message(thread_id, " World", "partial")
        
        # Verify items are in store during streaming
        items = manager.store.search(namespace)
        assert len(items) > 0, "Store should contain items during streaming"
        
        # 2. Simulate end of conversation (trigger persistence)
        # 'stop' should trigger _persist_complete_conversation which now includes cleanup
        manager.process_stream_message(thread_id, "!", "stop")
        
        # 3. Verify store is empty for this thread
        items_after = manager.store.search(namespace)
        assert len(items_after) == 0, "Memory should be cleared after successful persistence"
        
        # Verify persistence actually happened
        collection = manager.mongo_db.chat_streams
        doc = collection.find_one({"thread_id": thread_id})
        assert doc is not None
        assert doc["messages"] == ["Hello", " World", "!"]
