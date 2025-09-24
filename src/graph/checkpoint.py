# Copyright (c) 2025 Bytedance Ltd. and/or its affiliates
# SPDX-License-Identifier: MIT

import json
import logging
import uuid
from datetime import datetime

from typing import List, Optional, Tuple, cast

import psycopg
from langgraph.store.memory import InMemoryStore
from psycopg.rows import dict_row
from pymongo import MongoClient

from src.config.loader import get_bool_env, get_str_env


class ChatStreamManager:
    """
    Manages chat stream messages with persistent storage and in-memory caching.

    This class handles the storage and retrieval of chat messages using both
    an in-memory store for temporary data and MongoDB or PostgreSQL for persistent storage.
    It tracks message chunks and consolidates them when a conversation finishes.

    Attributes:
        store (InMemoryStore): In-memory storage for temporary message chunks
        mongo_client (MongoClient): MongoDB client connection
        mongo_db (Database): MongoDB database instance
        postgres_conn (psycopg.Connection): PostgreSQL connection
        logger (logging.Logger): Logger instance for this class
    """

    def __init__(
        self, checkpoint_saver: bool = False, db_uri: Optional[str] = None
    ) -> None:
        """
        Initialize the ChatStreamManager with database connections.

        Args:
            db_uri: Database connection URI. Supports MongoDB (mongodb://) and PostgreSQL (postgresql://)
                   If None, uses LANGGRAPH_CHECKPOINT_DB_URL env var or defaults to localhost
        """
        self.logger = logging.getLogger(__name__)
        self.store = InMemoryStore()
        self.checkpoint_saver = checkpoint_saver
        # Use provided URI or fall back to environment variable or default
        self.db_uri = db_uri

        # Initialize database connections
        self.mongo_client = None
        self.mongo_db = None
        self.postgres_conn = None

        if self.checkpoint_saver:
            if self.db_uri.startswith("mongodb://"):
                self._init_mongodb()
            elif self.db_uri.startswith("postgresql://") or self.db_uri.startswith(
                "postgres://"
            ):
                self._init_postgresql()
            else:
                self.logger.warning(
                    f"Unsupported database URI scheme: {self.db_uri}. "
                    "Supported schemes: mongodb://, postgresql://, postgres://"
                )
        else:
            self.logger.warning("Checkpoint saver is disabled")

    def _init_mongodb(self) -> None:
        """Initialize MongoDB connection."""

        try:
            self.mongo_client = MongoClient(self.db_uri)
            self.mongo_db = self.mongo_client.checkpointing_db
            # Test connection
            self.mongo_client.admin.command("ping")
            self.logger.info("Successfully connected to MongoDB")
        except Exception as e:
            self.logger.error(f"Failed to connect to MongoDB: {e}")

    def _init_postgresql(self) -> None:
        """Initialize PostgreSQL connection and create table if needed."""

        try:
            self.postgres_conn = psycopg.connect(self.db_uri, row_factory=dict_row)
            self.logger.info("Successfully connected to PostgreSQL")
            self._create_chat_streams_table()
            self._create_langgraph_events_table()
            self._create_research_replays_table()
        except Exception as e:
            self.logger.error(f"Failed to connect to PostgreSQL: {e}")

    def _create_chat_streams_table(self) -> None:
        """Create the chat_streams table if it doesn't exist."""
        try:
            with self.postgres_conn.cursor() as cursor:
                create_table_sql = """
                CREATE TABLE IF NOT EXISTS chat_streams (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    thread_id VARCHAR(255) NOT NULL UNIQUE,
                    messages JSONB NOT NULL,
                    ts TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                );
                
                CREATE INDEX IF NOT EXISTS idx_chat_streams_thread_id ON chat_streams(thread_id);
                CREATE INDEX IF NOT EXISTS idx_chat_streams_ts ON chat_streams(ts);
                """
                cursor.execute(create_table_sql)
                self.postgres_conn.commit()
                self.logger.info("Chat streams table created/verified successfully")
        except Exception as e:
            self.logger.error(f"Failed to create chat_streams table: {e}")
            if self.postgres_conn:
                self.postgres_conn.rollback()

    def _create_langgraph_events_table(self) -> None:
        """Create the langgraph_events table if it doesn't exist."""
        try:
            with self.postgres_conn.cursor() as cursor:
                create_table_sql = """
                CREATE TABLE IF NOT EXISTS langgraph_events (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    thread_id VARCHAR(255) NOT NULL,
                    event VARCHAR(255) NOT NULL,
                    level VARCHAR(50) NOT NULL,
                    message JSONB NOT NULL,
                    ts TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_langgraph_events_thread_id ON langgraph_events(thread_id);
                CREATE INDEX IF NOT EXISTS idx_langgraph_events_ts ON langgraph_events(ts);
                """
                cursor.execute(create_table_sql)
                self.postgres_conn.commit()
                self.logger.info("Langgraph events table created/verified successfully")
        except Exception as e:
            self.logger.error(f"Failed to create langgraph_events table: {e}")
            if self.postgres_conn:
                self.postgres_conn.rollback()

    def _create_research_replays_table(self) -> None:
        """Create the research_replays table if it doesn't exist."""
        try:
            with self.postgres_conn.cursor() as cursor:
                create_table_sql = """
                CREATE TABLE IF NOT EXISTS research_replays (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    thread_id VARCHAR(255) NOT NULL,
                    research_topic VARCHAR(255) NOT NULL,
                    report_style VARCHAR(50) NOT NULL,
                    messages INTEGER NOT NULL,
                    ts TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW()
                );
                CREATE INDEX IF NOT EXISTS idx_research_replays_thread_id ON research_replays(thread_id);
                CREATE INDEX IF NOT EXISTS idx_research_replays_ts ON research_replays(ts);
                """
                cursor.execute(create_table_sql)
                self.postgres_conn.commit()
                self.logger.info("Research replays table created/verified successfully")
        except Exception as e:
            self.logger.error(f"Failed to create research_replays table: {e}")
            if self.postgres_conn:
                self.postgres_conn.rollback()

    def _process_stream_messages(self, stream_message: dict | str | None) -> str:
        if stream_message is None:
            return ""
        if isinstance(stream_message, str):
            # If stream_message is a string, return it directly
            return stream_message
        if not isinstance(stream_message, dict):
            # If stream_message is not a dict, return an empty string
            return ""
        messages = cast(list, stream_message.get("messages", []))
        # remove the first message which is usually the system prompt
        if messages and isinstance(messages, list) and len(messages) > 0:
            # Decode byte messages back to strings
            decoded_messages = []
            for message in messages:
                if isinstance(message, bytes):
                    decoded_messages.append(message.decode("utf-8"))
                else:
                    decoded_messages.append(str(message))
            # Return all messages except the first one
            valid_messages = []
            for message in decoded_messages:
                if (
                    str(message).find("event:") == -1
                    and str(message).find("data:") == -1
                ):
                    continue
                if str(message).find("message_chunk") > -1:
                    if (
                        str(message).find("content") > -1
                        or str(message).find("reasoning_content") > -1
                        or str(message).find("finish_reason") > -1
                    ):
                        valid_messages.append(message)

                else:
                    valid_messages.append(message)
            return "".join(valid_messages) if valid_messages else ""
        elif messages and isinstance(messages, str):
            # If messages is a single string, return it directly
            return messages
        else:
            # If no messages found, return an empty string
            return ""

    def log_research_replays(
        self, thread_id: str, research_topic: str, report_style: str, messages: int
    ) -> None:
        if not self.checkpoint_saver:
            logging.warning(
                "Checkpoint saver is disabled, cannot retrieve conversation"
            )
            return None
        if self.mongo_db is None and self.postgres_conn is None:
            logging.warning("No DB connection available")
            return None
        if self.mongo_db is not None:
            try:
                collection = self.mongo_db.research_replays
                # Update existing conversation with new messages count
                if messages > 0:
                    existing_document = collection.find_one({"thread_id": thread_id})
                    if existing_document:
                        update_result = collection.update_one(
                            {"thread_id": thread_id},
                            {
                                "$set": {
                                    "messages": messages,
                                }
                            },
                        )
                        self.logger.info(
                            f"Updated research replay for thread {thread_id}: "
                            f"{update_result.modified_count} documents modified"
                        )
                else:
                    result = collection.insert_one(
                        {
                            "thread_id": thread_id,
                            "research_topic": research_topic,
                            "report_style": report_style,
                            "messages": messages,
                            "ts": datetime.now(),
                            "id": uuid.uuid4().hex,
                        }
                    )
                    self.logger.info(f"Event logged: {result.inserted_id}")
            except Exception as e:
                self.logger.error(f"Error logging event: {e}")
        elif self.postgres_conn is not None:
            try:
                # Update existing conversation with new messages count
                if messages > 0:
                    with self.postgres_conn.cursor() as cursor:
                        cursor.execute(
                            "SELECT id FROM research_replays WHERE thread_id = %s",
                            (thread_id,),
                        )
                        existing_record = cursor.fetchone()
                    if existing_record:
                        with self.postgres_conn.cursor() as cursor:
                            cursor.execute(
                                """
                                UPDATE research_replays
                                SET messages = %s
                                WHERE thread_id = %s
                                """,
                                (messages, thread_id),
                            )
                        self.postgres_conn.commit()
                        self.logger.info(
                            f"Updated research replay for thread {thread_id}: "
                            f"{cursor.rowcount} rows modified"
                        )
                else:
                    with self.postgres_conn.cursor() as cursor:
                        cursor.execute(
                            """
                        INSERT INTO research_replays (thread_id, research_topic, report_style, messages, ts)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                            (
                                thread_id,
                                research_topic,
                                report_style,
                                messages,
                                datetime.now(),
                            ),
                        )
                    self.postgres_conn.commit()
                    self.logger.info("Research replay logged successfully")
            except Exception as e:
                self.logger.error(f"Error logging research replay: {e}")

    def log_graph_event(
        self, thread_id: str, event: str, level: str, message: dict
    ) -> None:
        """
        Log an event related to a conversation thread.
        Args:
            thread_id (str): Unique identifier for the conversation thread
            event (str): Event type or name
            level (str): Log level (e.g., "info", "warning", "error")
            message (dict): Additional message data to log
        """
        if not self.checkpoint_saver:
            logging.warning(
                "Checkpoint saver is disabled, cannot retrieve conversation"
            )
            return None
        if self.mongo_db is None and self.postgres_conn is None:
            logging.warning("No mongodb connection available")
            return None
        if self.mongo_db is not None:
            try:
                collection = self.mongo_db.langgraph_events
                result = collection.insert_one(
                    {
                        "thread_id": thread_id,
                        "event": event,
                        "level": level,
                        "message": message,
                        "ts": datetime.now(),
                        "id": uuid.uuid4().hex,
                    }
                )
                self.logger.info(f"Event logged: {result.inserted_id}")
            except Exception as e:
                self.logger.error(f"Error logging event: {e}")
        elif self.postgres_conn is not None:
            try:
                with self.postgres_conn.cursor() as cursor:
                    cursor.execute(
                        """
                        INSERT INTO langgraph_events (thread_id, event, level, message, ts)
                        VALUES (%s, %s, %s, %s, %s)
                        """,
                        (
                            thread_id,
                            event,
                            level,
                            json.dumps(message),
                            datetime.now(),
                        ),
                    )
                    self.postgres_conn.commit()
                    self.logger.info("Event logged successfully")
            except Exception as e:
                self.logger.error(f"Error logging event: {e}")

    def get_messages_by_id(self, thread_id: str) -> Optional[str]:
        """Retrieve a conversation by thread_id."""
        if not self.checkpoint_saver:
            logging.warning(
                "Checkpoint saver is disabled, cannot retrieve conversation"
            )
            return None
        if self.mongo_db is None and self.postgres_conn is None:
            logging.warning("No database connection available")
            return None
        if self.mongo_db is not None:
            # MongoDB retrieval
            collection = self.mongo_db.chat_streams
            conversation = collection.find_one({"thread_id": thread_id})
            if conversation is None:
                logging.warning(f"No conversation found for thread_id: {thread_id}")
                return None
            messages = self._process_stream_messages(conversation)
            return messages
        elif self.postgres_conn:
            # PostgreSQL retrieval
            with self.postgres_conn.cursor() as cursor:
                cursor.execute(
                    "SELECT * FROM chat_streams WHERE thread_id = %s", (thread_id,)
                )
                conversation = cursor.fetchone()
                if conversation is None:
                    logging.warning(f"No conversation found for thread_id: {thread_id}")
                    return None
                messages = self._process_stream_messages(conversation)
                return messages
        else:
            logging.warning("No database connection available")
            return None

    def get_stream_messages(self, limit: int = 10, sort: str = "ts") -> List[dict]:
        """
        Retrieve chat stream messages from the database.
        Args:
            limit (int): Maximum number of messages to retrieve
            sort (str): Field to sort by, default is 'ts' (timestamp)
        Returns:
            List[dict]: List of chat stream messages, sorted by the specified field
        """
        if not self.checkpoint_saver:
            self.logger.warning(
                "Checkpoint saver is disabled, cannot retrieve messages"
            )
            return []
        if self.mongo_db is None and self.postgres_conn is None:
            self.logger.warning("No database connection available")
            return []
        try:
            if self.mongo_db is not None:
                # MongoDB retrieval
                collection = self.mongo_db.research_replays
                cursor = collection.find().sort(sort, -1).limit(limit)
                messages = list(cursor) if cursor is not None else []
                return messages
            elif self.postgres_conn:
                # PostgreSQL retrieval
                with self.postgres_conn.cursor() as cursor:
                    query = (
                        f"SELECT * FROM research_replays ORDER BY {sort} DESC LIMIT %s"
                    )
                    cursor.execute(query, (limit,))
                    messages = cursor.fetchall()
                    return messages
            else:
                self.logger.warning("No database connection available")
                return []
        except Exception as e:
            self.logger.error(f"Error retrieving chat stream messages: {e}")
            return []

    def process_stream_message(
        self, thread_id: str, message: str, finish_reason: str
    ) -> bool:
        """
        Process and store a chat stream message chunk.

        This method handles individual message chunks during streaming and consolidates
        them into a complete message when the stream finishes. Messages are stored
        temporarily in memory and permanently in MongoDB when complete.

        Args:
            thread_id: Unique identifier for the conversation thread
            message: The message content or chunk to store
            finish_reason: Reason for message completion ("stop", "interrupt", or partial)

        Returns:
            bool: True if message was processed successfully, False otherwise
        """
        if not thread_id or not isinstance(thread_id, str):
            self.logger.warning("Invalid thread_id provided")
            return False

        if not message:
            self.logger.warning("Empty message provided")
            return False

        try:
            # Create namespace for this thread's messages
            store_namespace: Tuple[str, str] = ("messages", thread_id)

            # Get or initialize message cursor for tracking chunks
            cursor = self.store.get(store_namespace, "cursor")
            current_index = 0

            if cursor is None:
                # Initialize cursor for new conversation
                self.store.put(store_namespace, "cursor", {"index": 0})
            else:
                # Increment index for next chunk
                current_index = int(cursor.value.get("index", 0)) + 1
                self.store.put(store_namespace, "cursor", {"index": current_index})

            # Store the current message chunk
            self.store.put(store_namespace, f"chunk_{current_index}", message)

            # Check if conversation is complete and should be persisted
            if finish_reason in ("stop", "interrupt"):
                return self._persist_complete_conversation(
                    thread_id, store_namespace, current_index
                )

            return True

        except Exception as e:
            self.logger.error(
                f"Error processing stream message for thread {thread_id}: {e}"
            )
            return False

    def _persist_complete_conversation(
        self, thread_id: str, store_namespace: Tuple[str, str], final_index: int
    ) -> bool:
        """
        Persist completed conversation to database (MongoDB or PostgreSQL).

        Retrieves all message chunks from memory store and saves the complete
        conversation to the configured database for permanent storage.

        Args:
            thread_id: Unique identifier for the conversation thread
            store_namespace: Namespace tuple for accessing stored messages
            final_index: The final chunk index for this conversation

        Returns:
            bool: True if persistence was successful, False otherwise
        """
        try:
            # Retrieve all message chunks from memory store
            # Get all messages up to the final index including cursor metadata
            memories = self.store.search(store_namespace, limit=final_index + 2)

            # Extract message content, filtering out cursor metadata
            messages: List[str] = []
            for item in memories:
                value = item.dict().get("value", "")
                # Skip cursor metadata, only include actual message chunks
                if value and not isinstance(value, dict):
                    messages.append(str(value))

            if not messages:
                self.logger.warning(f"No messages found for thread {thread_id}")
                return False

            if not self.checkpoint_saver:
                self.logger.warning("Checkpoint saver is disabled")
                return False
            # Log the event of persisting conversation
            self.log_research_replays(thread_id, "", "", len(messages))
            # Choose persistence method based on available connection
            if self.mongo_db is not None:
                return self._persist_to_mongodb(thread_id, messages)
            elif self.postgres_conn is not None:
                return self._persist_to_postgresql(thread_id, messages)
            else:
                self.logger.warning("No database connection available")
                return False

        except Exception as e:
            self.logger.error(
                f"Error persisting conversation for thread {thread_id}: {e}"
            )
            return False

    def _persist_to_mongodb(self, thread_id: str, messages: List[str]) -> bool:
        """Persist conversation to MongoDB."""
        try:
            # Get MongoDB collection for chat streams
            collection = self.mongo_db.chat_streams

            # Check if conversation already exists in database
            existing_document = collection.find_one({"thread_id": thread_id})

            current_timestamp = datetime.now()

            if existing_document:
                # Update existing conversation with new messages
                update_result = collection.update_one(
                    {"thread_id": thread_id},
                    {"$set": {"messages": messages, "ts": current_timestamp}},
                )
                self.logger.info(
                    f"Updated conversation for thread {thread_id}: "
                    f"{update_result.modified_count} documents modified"
                )
                return update_result.modified_count > 0
            else:
                # Create new conversation document
                new_document = {
                    "thread_id": thread_id,
                    "messages": messages,
                    "ts": current_timestamp,
                    "id": uuid.uuid4().hex,
                }
                insert_result = collection.insert_one(new_document)
                self.logger.info(
                    f"Created new conversation: {insert_result.inserted_id}"
                )
                return insert_result.inserted_id is not None

        except Exception as e:
            self.logger.error(f"Error persisting to MongoDB: {e}")
            return False

    def _persist_to_postgresql(self, thread_id: str, messages: List[str]) -> bool:
        """Persist conversation to PostgreSQL."""
        try:
            with self.postgres_conn.cursor() as cursor:
                # Check if conversation already exists
                cursor.execute(
                    "SELECT id FROM chat_streams WHERE thread_id = %s", (thread_id,)
                )
                existing_record = cursor.fetchone()

                current_timestamp = datetime.now()
                messages_json = json.dumps(messages)

                if existing_record:
                    # Update existing conversation with new messages
                    cursor.execute(
                        """
                        UPDATE chat_streams 
                        SET messages = %s, ts = %s 
                        WHERE thread_id = %s
                        """,
                        (messages_json, current_timestamp, thread_id),
                    )
                    affected_rows = cursor.rowcount
                    self.postgres_conn.commit()

                    self.logger.info(
                        f"Updated conversation for thread {thread_id}: "
                        f"{affected_rows} rows modified"
                    )
                    return affected_rows > 0
                else:
                    # Create new conversation record
                    conversation_id = uuid.uuid4()
                    cursor.execute(
                        """
                        INSERT INTO chat_streams (id, thread_id, messages, ts) 
                        VALUES (%s, %s, %s, %s)
                        """,
                        (conversation_id, thread_id, messages_json, current_timestamp),
                    )
                    affected_rows = cursor.rowcount
                    self.postgres_conn.commit()

                    self.logger.info(
                        f"Created new conversation with ID: {conversation_id}"
                    )
                    return affected_rows > 0

        except Exception as e:
            self.logger.error(f"Error persisting to PostgreSQL: {e}")
            if self.postgres_conn:
                self.postgres_conn.rollback()
            return False

    def close(self) -> None:
        """Close database connections."""
        try:
            if self.mongo_client is not None:
                self.mongo_client.close()
                self.logger.info("MongoDB connection closed")
        except Exception as e:
            self.logger.error(f"Error closing MongoDB connection: {e}")

        try:
            if self.postgres_conn is not None:
                self.postgres_conn.close()
                self.logger.info("PostgreSQL connection closed")
        except Exception as e:
            self.logger.error(f"Error closing PostgreSQL connection: {e}")

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close connections."""
        self.close()


# Global instance for backward compatibility
# TODO: Consider using dependency injection instead of global instance
_default_manager = ChatStreamManager(
    checkpoint_saver=get_bool_env("LANGGRAPH_CHECKPOINT_SAVER", False),
    db_uri=get_str_env("LANGGRAPH_CHECKPOINT_DB_URL", "mongodb://localhost:27017"),
)


def chat_stream_message(thread_id: str, message: str, finish_reason: str) -> bool:
    """
    Legacy function wrapper for backward compatibility.

    Args:
        thread_id: Unique identifier for the conversation thread
        message: The message content to store
        finish_reason: Reason for message completion

    Returns:
        bool: True if message was processed successfully
    """
    checkpoint_saver = get_bool_env("LANGGRAPH_CHECKPOINT_SAVER", False)
    if checkpoint_saver:
        return _default_manager.process_stream_message(
            thread_id, message, finish_reason
        )
    else:
        return False


def list_conversations(limit: int, sort: str = "ts"):
    checkpoint_saver = get_bool_env("LANGGRAPH_CHECKPOINT_SAVER", False)
    if checkpoint_saver:
        return _default_manager.get_stream_messages(limit, sort)
    else:
        logging.warning("Checkpoint saver is disabled, message not processed")
        return []


def get_conversation(thread_id: str):
    """Retrieve a conversation by thread_id."""
    checkpoint_saver = get_bool_env("LANGGRAPH_CHECKPOINT_SAVER", False)
    if checkpoint_saver:
        return _default_manager.get_messages_by_id(thread_id)
    else:
        logging.warning("Checkpoint saver is disabled, message not processed")
        return ""


def log_graph_event(thread_id: str, event: str, level: str, message: dict):
    checkpoint_saver = get_bool_env("LANGGRAPH_CHECKPOINT_SAVER", False)
    if checkpoint_saver:
        return _default_manager.log_graph_event(thread_id, event, level, message)
    else:
        logging.warning("Checkpoint saver is disabled, message not processed")
        return ""


def log_research_replays(
    thread_id: str, research_topic: str, report_style: str, messages: int
):
    checkpoint_saver = get_bool_env("LANGGRAPH_CHECKPOINT_SAVER", False)
    if checkpoint_saver:
        return _default_manager.log_research_replays(
            thread_id, research_topic, report_style, messages
        )
    else:
        logging.warning("Checkpoint saver is disabled, message not processed")
        return ""
