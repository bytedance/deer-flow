package com.deerflow.mobile.data

import androidx.room.testing.MigrationTestHelper
import androidx.sqlite.db.SupportSQLiteDatabase
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import java.util.UUID
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class WorkspaceDatabaseMigrationInstrumentedTest {
    @get:Rule
    val helper = MigrationTestHelper(
        InstrumentationRegistry.getInstrumentation(),
        WorkspaceDatabase::class.java,
        emptyList(),
    )

    @Test
    fun migrationFrom1To2PreservesWorkspaceDataAndAddsAttachments() {
        val databaseName = "workspace-migration-${UUID.randomUUID()}.db"
        val serverUrl = "https://migration.example.test"
        val threadId = "thread-v1"
        val context = InstrumentationRegistry.getInstrumentation().targetContext

        try {
            helper.createDatabase(databaseName, 1).apply {
                execSQL(
                    "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?)",
                    arrayOf(serverUrl, threadId, "Legacy thread", "busy", "2026-07-20T00:00:00Z", 1),
                )
                execSQL(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
                    arrayOf(serverUrl, threadId, "message-v1", 0, MessageRole.User.name, "Legacy message"),
                )
                execSQL(
                    "INSERT INTO drafts VALUES (?, ?, ?, ?)",
                    arrayOf(serverUrl, threadId, "Legacy draft", 1_753_000_000_000L),
                )
                execSQL(
                    "INSERT INTO runs VALUES (?, ?, ?, ?, ?, ?)",
                    arrayOf(serverUrl, threadId, "run-v1", "event-v1", RunStatus.Reconnecting.name, 1_753_000_000_001L),
                )
                close()
            }

            val migrated = helper.runMigrationsAndValidate(
                databaseName,
                2,
                true,
                WorkspaceDatabase.MIGRATION_1_2,
            )
            try {
                assertEquals("Legacy thread", migrated.singleString("SELECT title FROM threads"))
                assertEquals("Legacy message", migrated.singleString("SELECT text FROM messages"))
                assertEquals("Legacy draft", migrated.singleString("SELECT text FROM drafts"))
                assertEquals("event-v1", migrated.singleString("SELECT lastEventId FROM runs"))

                migrated.execSQL(
                    "INSERT INTO attachments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    arrayOf(
                        serverUrl,
                        threadId,
                        "content://migration/attachment",
                        "legacy.txt",
                        "text/plain",
                        42L,
                        AttachmentStatus.Pending.name,
                        null,
                        1_753_000_000_002L,
                    ),
                )
                assertEquals("legacy.txt", migrated.singleString("SELECT filename FROM attachments"))
                assertTrue(migrated.hasColumns("attachments", ATTACHMENT_COLUMNS))
            } finally {
                migrated.close()
            }
        } finally {
            context.deleteDatabase(databaseName)
        }
    }

    @Test
    fun migrationFrom2To3PreservesAttachmentsAndAddsWorkspaceMetadata() {
        val databaseName = "workspace-migration-${UUID.randomUUID()}.db"
        val serverUrl = "https://migration.example.test"
        val threadId = "thread-v2"
        val context = InstrumentationRegistry.getInstrumentation().targetContext

        try {
            helper.createDatabase(databaseName, 2).apply {
                execSQL(
                    "INSERT INTO attachments VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    arrayOf(
                        serverUrl,
                        threadId,
                        "content://migration/attachment-v2",
                        "version-two.txt",
                        "text/plain",
                        84L,
                        AttachmentStatus.Failed.name,
                        "Interrupted",
                        1_753_000_000_003L,
                    ),
                )
                close()
            }

            val migrated = helper.runMigrationsAndValidate(
                databaseName,
                3,
                true,
                WorkspaceDatabase.MIGRATION_2_3,
            )
            try {
                assertEquals("version-two.txt", migrated.singleString("SELECT filename FROM attachments"))
                migrated.execSQL(
                    "INSERT INTO workspace_metadata VALUES (?, ?, ?, ?)",
                    arrayOf(serverUrl, "capabilities", "{\"version\":1}", 1_753_000_000_004L),
                )
                assertEquals("capabilities", migrated.singleString("SELECT kind FROM workspace_metadata"))
                assertTrue(migrated.hasColumns("workspace_metadata", METADATA_COLUMNS))
            } finally {
                migrated.close()
            }
        } finally {
            context.deleteDatabase(databaseName)
        }
    }

    @Test
    fun migrationFrom3To4PreservesLegacyMessagesAndAddsStructuredPayload() {
        val databaseName = "workspace-migration-${UUID.randomUUID()}.db"
        val serverUrl = "https://migration.example.test"
        val threadId = "thread-v3"
        val context = InstrumentationRegistry.getInstrumentation().targetContext

        try {
            helper.createDatabase(databaseName, 3).apply {
                execSQL(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
                    arrayOf(serverUrl, threadId, "message-v3", 0, MessageRole.Assistant.name, "Legacy structured text"),
                )
                close()
            }

            val migrated = helper.runMigrationsAndValidate(
                databaseName,
                4,
                true,
                WorkspaceDatabase.MIGRATION_3_4,
            )
            try {
                assertEquals("Legacy structured text", migrated.singleString("SELECT text FROM messages"))
                assertEquals(null, migrated.singleNullableString("SELECT payloadJson FROM messages"))
                assertTrue(migrated.hasColumns("messages", MESSAGE_COLUMNS))
            } finally {
                migrated.close()
            }
        } finally {
            context.deleteDatabase(databaseName)
        }
    }

    @Test
    fun migrationFrom1To4RunsTheCompleteProductionChain() {
        val databaseName = "workspace-migration-${UUID.randomUUID()}.db"
        val context = InstrumentationRegistry.getInstrumentation().targetContext

        try {
            helper.createDatabase(databaseName, 1).apply {
                execSQL(
                    "INSERT INTO threads VALUES (?, ?, ?, ?, ?, ?)",
                    arrayOf(
                        "https://chain.example.test",
                        "thread-v1-chain",
                        "Chain migration",
                        "idle",
                        "2026-07-20T00:00:00Z",
                        0,
                    ),
                )
                execSQL(
                    "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?)",
                    arrayOf(
                        "https://chain.example.test",
                        "thread-v1-chain",
                        "message-v1-chain",
                        0,
                        MessageRole.User.name,
                        "Chain message",
                    ),
                )
                close()
            }

            val migrated = helper.runMigrationsAndValidate(
                databaseName,
                4,
                true,
                WorkspaceDatabase.MIGRATION_1_2,
                WorkspaceDatabase.MIGRATION_2_3,
                WorkspaceDatabase.MIGRATION_3_4,
            )
            try {
                assertEquals("Chain migration", migrated.singleString("SELECT title FROM threads"))
                assertEquals("Chain message", migrated.singleString("SELECT text FROM messages"))
                assertEquals(null, migrated.singleNullableString("SELECT payloadJson FROM messages"))
                assertTrue(migrated.hasColumns("attachments", ATTACHMENT_COLUMNS))
                assertTrue(migrated.hasColumns("workspace_metadata", METADATA_COLUMNS))
                assertTrue(migrated.hasColumns("messages", MESSAGE_COLUMNS))
            } finally {
                migrated.close()
            }
        } finally {
            context.deleteDatabase(databaseName)
        }
    }

    private fun SupportSQLiteDatabase.singleString(query: String): String =
        query(query).use { cursor ->
            assertTrue("Expected one row for: $query", cursor.moveToFirst())
            cursor.getString(0)
        }

    private fun SupportSQLiteDatabase.singleNullableString(query: String): String? =
        query(query).use { cursor ->
            assertTrue("Expected one row for: $query", cursor.moveToFirst())
            if (cursor.isNull(0)) null else cursor.getString(0)
        }

    private fun SupportSQLiteDatabase.hasColumns(table: String, expected: Set<String>): Boolean {
        val actual = query("PRAGMA table_info(`$table`)").use { cursor ->
            val nameIndex = cursor.getColumnIndexOrThrow("name")
            buildSet {
                while (cursor.moveToNext()) add(cursor.getString(nameIndex))
            }
        }
        return actual == expected
    }

    private companion object {
        val ATTACHMENT_COLUMNS = setOf(
            "serverUrl",
            "threadId",
            "uri",
            "filename",
            "mimeType",
            "size",
            "status",
            "error",
            "updatedAt",
        )
        val METADATA_COLUMNS = setOf("serverUrl", "kind", "payload", "updatedAt")
        val MESSAGE_COLUMNS = setOf(
            "serverUrl",
            "threadId",
            "messageId",
            "sortIndex",
            "role",
            "text",
            "payloadJson",
        )
    }
}
