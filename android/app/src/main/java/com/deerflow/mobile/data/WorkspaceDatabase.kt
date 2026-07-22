package com.deerflow.mobile.data

import android.content.Context
import androidx.room.Dao
import androidx.room.Database
import androidx.room.Entity
import androidx.room.Insert
import androidx.room.migration.Migration
import androidx.room.OnConflictStrategy
import androidx.room.Query
import androidx.room.Room
import androidx.room.RoomDatabase
import androidx.room.Transaction
import androidx.sqlite.db.SupportSQLiteDatabase
import java.io.File
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Entity(tableName = "threads", primaryKeys = ["serverUrl", "threadId"])
data class CachedThread(
    val serverUrl: String,
    val threadId: String,
    val title: String,
    val status: String,
    val updatedAt: String,
    val isPinned: Boolean,
)

@Entity(tableName = "messages", primaryKeys = ["serverUrl", "threadId", "messageId"])
data class CachedMessage(
    val serverUrl: String,
    val threadId: String,
    val messageId: String,
    val sortIndex: Int,
    val role: String,
    val text: String,
    val payloadJson: String?,
)

@Entity(tableName = "drafts", primaryKeys = ["serverUrl", "threadId"])
data class CachedDraft(
    val serverUrl: String,
    val threadId: String,
    val text: String,
    val updatedAt: Long,
)

@Entity(tableName = "runs", primaryKeys = ["serverUrl", "threadId"])
data class CachedRun(
    val serverUrl: String,
    val threadId: String,
    val runId: String?,
    val lastEventId: String?,
    val status: String,
    val updatedAt: Long,
)

@Entity(tableName = "attachments", primaryKeys = ["serverUrl", "threadId", "uri"])
data class CachedAttachment(
    val serverUrl: String,
    val threadId: String,
    val uri: String,
    val filename: String,
    val mimeType: String,
    val size: Long,
    val status: String,
    val error: String?,
    val updatedAt: Long,
)

@Entity(tableName = "workspace_metadata", primaryKeys = ["serverUrl", "kind"])
data class CachedWorkspaceMetadata(
    val serverUrl: String,
    val kind: String,
    val payload: String,
    val updatedAt: Long,
)

@Dao
abstract class WorkspaceDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    abstract suspend fun upsertThreads(items: List<CachedThread>)

    @Query("DELETE FROM threads WHERE serverUrl = :serverUrl")
    abstract suspend fun deleteThreads(serverUrl: String)

    @Query("SELECT * FROM threads WHERE serverUrl = :serverUrl ORDER BY isPinned DESC, updatedAt DESC")
    abstract suspend fun loadThreads(serverUrl: String): List<CachedThread>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    abstract suspend fun upsertMessages(items: List<CachedMessage>)

    @Query("DELETE FROM messages WHERE serverUrl = :serverUrl AND threadId = :threadId")
    abstract suspend fun deleteMessages(serverUrl: String, threadId: String)

    @Query("SELECT * FROM messages WHERE serverUrl = :serverUrl AND threadId = :threadId ORDER BY sortIndex")
    abstract suspend fun loadMessages(serverUrl: String, threadId: String): List<CachedMessage>

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    abstract suspend fun saveDraft(value: CachedDraft)

    @Query("SELECT * FROM drafts WHERE serverUrl = :serverUrl AND threadId = :threadId LIMIT 1")
    abstract suspend fun loadDraft(serverUrl: String, threadId: String): CachedDraft?

    @Query("DELETE FROM drafts WHERE serverUrl = :serverUrl AND threadId = :threadId")
    abstract suspend fun deleteDraft(serverUrl: String, threadId: String)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    abstract suspend fun saveRun(value: CachedRun)

    @Query("SELECT * FROM runs WHERE serverUrl = :serverUrl AND threadId = :threadId LIMIT 1")
    abstract suspend fun loadRun(serverUrl: String, threadId: String): CachedRun?

    @Query(
        """
        SELECT * FROM runs
        WHERE serverUrl = :serverUrl
          AND status IN ('Connecting', 'Streaming', 'Reconnecting', 'Stopping')
        ORDER BY updatedAt DESC
        LIMIT 1
        """,
    )
    abstract suspend fun loadLatestActiveRun(serverUrl: String): CachedRun?

    @Query("SELECT * FROM threads WHERE serverUrl = :serverUrl AND threadId = :threadId LIMIT 1")
    abstract suspend fun loadThread(serverUrl: String, threadId: String): CachedThread?

    @Query("DELETE FROM runs WHERE serverUrl = :serverUrl AND threadId = :threadId")
    abstract suspend fun deleteRun(serverUrl: String, threadId: String)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    abstract suspend fun upsertAttachments(items: List<CachedAttachment>)

    @Query("DELETE FROM attachments WHERE serverUrl = :serverUrl AND threadId = :threadId")
    abstract suspend fun deleteAttachments(serverUrl: String, threadId: String)

    @Query("SELECT * FROM attachments WHERE serverUrl = :serverUrl AND threadId = :threadId ORDER BY updatedAt, uri")
    abstract suspend fun loadAttachments(serverUrl: String, threadId: String): List<CachedAttachment>

    @Query("DELETE FROM threads WHERE serverUrl = :serverUrl AND threadId = :threadId")
    abstract suspend fun deleteThread(serverUrl: String, threadId: String)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    abstract suspend fun saveWorkspaceMetadata(value: CachedWorkspaceMetadata)

    @Query("SELECT * FROM workspace_metadata WHERE serverUrl = :serverUrl AND kind = :kind LIMIT 1")
    abstract suspend fun loadWorkspaceMetadata(serverUrl: String, kind: String): CachedWorkspaceMetadata?

    @Query("SELECT COUNT(*) FROM threads")
    abstract suspend fun threadCount(): Int

    @Query("SELECT COUNT(*) FROM messages")
    abstract suspend fun messageCount(): Int

    @Query("SELECT COUNT(*) FROM drafts")
    abstract suspend fun draftCount(): Int

    @Query("SELECT COUNT(*) FROM runs")
    abstract suspend fun runCount(): Int

    @Query("SELECT COUNT(*) FROM attachments")
    abstract suspend fun attachmentCount(): Int

    @Query("SELECT COUNT(*) FROM workspace_metadata")
    abstract suspend fun metadataCount(): Int

    @Transaction
    open suspend fun replaceThreads(serverUrl: String, items: List<CachedThread>) {
        deleteThreads(serverUrl)
        upsertThreads(items)
    }

    @Transaction
    open suspend fun replaceMessages(serverUrl: String, threadId: String, items: List<CachedMessage>) {
        deleteMessages(serverUrl, threadId)
        upsertMessages(items)
    }

    @Transaction
    open suspend fun replaceAttachments(serverUrl: String, threadId: String, items: List<CachedAttachment>) {
        deleteAttachments(serverUrl, threadId)
        upsertAttachments(items)
    }
}

@Database(
    entities = [
        CachedThread::class,
        CachedMessage::class,
        CachedDraft::class,
        CachedRun::class,
        CachedAttachment::class,
        CachedWorkspaceMetadata::class,
    ],
    version = 4,
    exportSchema = true,
)
abstract class WorkspaceDatabase : RoomDatabase() {
    abstract fun workspaceDao(): WorkspaceDao

    companion object {
        @Volatile private var instance: WorkspaceDatabase? = null

        fun get(context: Context): WorkspaceDatabase = instance ?: synchronized(this) {
            instance ?: Room.databaseBuilder(
                context.applicationContext,
                WorkspaceDatabase::class.java,
                "deerflow-workspace.db",
            ).addMigrations(MIGRATION_1_2, MIGRATION_2_3, MIGRATION_3_4).build().also { instance = it }
        }

        internal val MIGRATION_1_2 = object : Migration(1, 2) {
            override fun migrate(database: SupportSQLiteDatabase) {
                database.execSQL(
                    """
                    CREATE TABLE IF NOT EXISTS attachments (
                        serverUrl TEXT NOT NULL,
                        threadId TEXT NOT NULL,
                        uri TEXT NOT NULL,
                        filename TEXT NOT NULL,
                        mimeType TEXT NOT NULL,
                        size INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        error TEXT,
                        updatedAt INTEGER NOT NULL,
                        PRIMARY KEY(serverUrl, threadId, uri)
                    )
                    """.trimIndent(),
                )
            }
        }

        internal val MIGRATION_2_3 = object : Migration(2, 3) {
            override fun migrate(database: SupportSQLiteDatabase) {
                database.execSQL(
                    """
                    CREATE TABLE IF NOT EXISTS workspace_metadata (
                        serverUrl TEXT NOT NULL,
                        kind TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        updatedAt INTEGER NOT NULL,
                        PRIMARY KEY(serverUrl, kind)
                    )
                    """.trimIndent(),
                )
            }
        }

        internal val MIGRATION_3_4 = object : Migration(3, 4) {
            override fun migrate(database: SupportSQLiteDatabase) {
                database.execSQL("ALTER TABLE messages ADD COLUMN payloadJson TEXT")
            }
        }
    }
}

class WorkspaceCache(context: Context) {
    private val appContext = context.applicationContext
    private val database = WorkspaceDatabase.get(appContext)
    private val dao = database.workspaceDao()
    private val artifactsDirectory = File(appContext.cacheDir, ARTIFACTS_DIRECTORY)

    suspend fun stats(): CacheStats = withContext(Dispatchers.IO) {
        CacheStats(
            conversationCount = dao.threadCount(),
            messageCount = dao.messageCount(),
            draftCount = dao.draftCount(),
            runCount = dao.runCount(),
            attachmentCount = dao.attachmentCount(),
            metadataCount = dao.metadataCount(),
            bytesOnDisk = databaseFiles(appContext).sumOf { it.length() } + artifactsDirectory.sizeOnDisk(),
        )
    }

    suspend fun clearAll() = withContext(Dispatchers.IO) {
        database.clearAllTables()
        artifactsDirectory.deleteRecursively()
    }

    suspend fun saveThreads(serverUrl: String, threads: List<ThreadSummary>) {
        dao.replaceThreads(serverUrl, threads.map {
            CachedThread(serverUrl, it.id, it.title, it.status, it.updatedAt, it.isPinned)
        })
    }

    suspend fun loadThreads(serverUrl: String): List<ThreadSummary> = dao.loadThreads(serverUrl).map {
        ThreadSummary(it.threadId, it.title, it.status, it.updatedAt, it.isPinned)
    }

    suspend fun saveMessages(serverUrl: String, threadId: String, messages: List<ChatMessage>) {
        dao.replaceMessages(serverUrl, threadId, messages.mapIndexed { index, message ->
            CachedMessage(
                serverUrl,
                threadId,
                message.id,
                index,
                message.role.name,
                message.text,
                encodeCachedChatMessage(message),
            )
        })
    }

    suspend fun loadMessages(serverUrl: String, threadId: String): List<ChatMessage> =
        dao.loadMessages(serverUrl, threadId).map { cached ->
            val role = MessageRole.valueOf(cached.role)
            cached.payloadJson
                ?.let(::decodeCachedChatMessage)
                ?.takeIf { it.id == cached.messageId && it.role == role }
                ?: ChatMessage(cached.messageId, role, cached.text)
        }

    suspend fun saveDraft(serverUrl: String, threadId: String, text: String) {
        if (text.isBlank()) dao.deleteDraft(serverUrl, threadId)
        else dao.saveDraft(CachedDraft(serverUrl, threadId, text, System.currentTimeMillis()))
    }

    suspend fun loadDraft(serverUrl: String, threadId: String): String =
        dao.loadDraft(serverUrl, threadId)?.text.orEmpty()

    suspend fun saveRun(serverUrl: String, threadId: String, run: RunState) {
        if (run.status == RunStatus.Idle) dao.deleteRun(serverUrl, threadId)
        else dao.saveRun(CachedRun(serverUrl, threadId, run.runId, run.lastEventId, run.status.name, System.currentTimeMillis()))
    }

    suspend fun loadRun(serverUrl: String, threadId: String): RunState? = dao.loadRun(serverUrl, threadId)?.let {
        RunState(RunStatus.valueOf(it.status), it.runId, it.lastEventId)
    }

    suspend fun loadLatestActiveRun(serverUrl: String): RecoverableRun? = dao.loadLatestActiveRun(serverUrl)?.let { cached ->
        val run = runCatching {
            RunState(RunStatus.valueOf(cached.status), cached.runId, cached.lastEventId)
        }.getOrNull() ?: return@let null
        if (!run.active) return@let null
        RecoverableRun(
            threadId = cached.threadId,
            title = dao.loadThread(serverUrl, cached.threadId)?.title ?: "Run in progress",
            run = run,
        )
    }

    suspend fun saveAttachments(serverUrl: String, threadId: String, attachments: List<PendingAttachment>) {
        dao.replaceAttachments(
            serverUrl,
            threadId,
            attachments.map {
                CachedAttachment(
                    serverUrl = serverUrl,
                    threadId = threadId,
                    uri = it.uri,
                    filename = it.filename,
                    mimeType = it.mimeType,
                    size = it.size,
                    status = it.status.name,
                    error = it.error,
                    updatedAt = System.currentTimeMillis(),
                )
            },
        )
    }

    suspend fun loadAttachments(serverUrl: String, threadId: String): List<PendingAttachment> = dao.loadAttachments(serverUrl, threadId).map {
        val persistedStatus = runCatching { AttachmentStatus.valueOf(it.status) }.getOrDefault(AttachmentStatus.Pending)
        val interrupted = persistedStatus == AttachmentStatus.Uploading
        PendingAttachment(
            uri = it.uri,
            filename = it.filename,
            mimeType = it.mimeType,
            size = it.size,
            status = if (interrupted) AttachmentStatus.Pending else persistedStatus,
            error = if (interrupted) "Upload interrupted before completion." else it.error,
        )
    }

    suspend fun saveCapabilities(serverUrl: String, value: WorkspaceCapabilities) {
        saveMetadata(serverUrl, CAPABILITIES_KIND, encodeWorkspaceCapabilities(value))
    }

    suspend fun loadCapabilities(serverUrl: String): WorkspaceCapabilities? =
        loadMetadata(serverUrl, CAPABILITIES_KIND)?.let(::decodeWorkspaceCapabilities)

    suspend fun saveTasks(serverUrl: String, value: List<ScheduledTaskInfo>) {
        saveMetadata(serverUrl, TASKS_KIND, encodeScheduledTasks(value))
    }

    suspend fun loadTasks(serverUrl: String): List<ScheduledTaskInfo>? =
        loadMetadata(serverUrl, TASKS_KIND)?.let(::decodeScheduledTasks)

    suspend fun saveMemory(serverUrl: String, value: MemoryData) {
        saveMetadata(serverUrl, MEMORY_KIND, encodeMemory(value))
    }

    suspend fun loadMemory(serverUrl: String): MemoryData? =
        loadMetadata(serverUrl, MEMORY_KIND)?.let(::decodeMemory)

    suspend fun saveMcpTools(serverUrl: String, value: List<McpToolInfo>) {
        saveMetadata(serverUrl, MCP_TOOLS_KIND, encodeMcpTools(value))
    }

    suspend fun loadMcpTools(serverUrl: String): List<McpToolInfo>? =
        loadMetadata(serverUrl, MCP_TOOLS_KIND)?.let(::decodeMcpTools)

    suspend fun deleteThread(serverUrl: String, threadId: String) {
        dao.deleteThread(serverUrl, threadId)
        dao.deleteMessages(serverUrl, threadId)
        dao.deleteDraft(serverUrl, threadId)
        dao.deleteRun(serverUrl, threadId)
        dao.deleteAttachments(serverUrl, threadId)
    }

    private suspend fun saveMetadata(serverUrl: String, kind: String, payload: String) {
        dao.saveWorkspaceMetadata(
            CachedWorkspaceMetadata(
                serverUrl = serverUrl,
                kind = kind,
                payload = payload,
                updatedAt = System.currentTimeMillis(),
            ),
        )
    }

    private suspend fun loadMetadata(serverUrl: String, kind: String): String? =
        dao.loadWorkspaceMetadata(serverUrl, kind)?.payload

    private companion object {
        const val ARTIFACTS_DIRECTORY = "artifacts"
        const val CAPABILITIES_KIND = "capabilities"
        const val TASKS_KIND = "scheduled_tasks"
        const val MEMORY_KIND = "memory"
        const val MCP_TOOLS_KIND = "mcp_tools"
    }
}

data class CacheStats(
    val conversationCount: Int = 0,
    val messageCount: Int = 0,
    val draftCount: Int = 0,
    val runCount: Int = 0,
    val attachmentCount: Int = 0,
    val metadataCount: Int = 0,
    val bytesOnDisk: Long = 0,
) {
    val itemCount: Int
        get() = conversationCount + messageCount + draftCount + runCount + attachmentCount + metadataCount
}

private fun databaseFiles(context: Context): List<File> {
    val primary = context.getDatabasePath("deerflow-workspace.db")
    return listOf(primary, File("${primary.path}-wal"), File("${primary.path}-shm"))
}

private fun File.sizeOnDisk(): Long = when {
    !exists() -> 0
    isFile -> length()
    else -> listFiles()?.sumOf(File::sizeOnDisk) ?: 0
}

data class RecoverableRun(
    val threadId: String,
    val title: String,
    val run: RunState,
)
