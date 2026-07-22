package com.deerflow.mobile

import android.content.Context
import android.content.pm.ShortcutInfo
import android.content.pm.ShortcutManager
import android.graphics.drawable.Icon
import com.deerflow.mobile.data.ThreadSummary
import java.security.MessageDigest

internal const val MAX_RECENT_CONVERSATION_SHORTCUTS = 4

internal data class RecentConversationShortcut(
    val id: String,
    val threadId: String,
    val title: String,
)

internal fun recentConversationShortcuts(
    serverUrl: String,
    threads: List<ThreadSummary>,
    maxCount: Int,
): List<RecentConversationShortcut> = threads
    .asSequence()
    .filter { it.id.isNotBlank() }
    .distinctBy { it.id }
    .sortedByDescending { it.updatedAt }
    .take(maxCount.coerceAtLeast(0))
    .map { thread ->
        RecentConversationShortcut(
            id = "conversation-${shortcutDigest(serverUrl, thread.id)}",
            threadId = thread.id,
            title = thread.title.trim().replace(Regex("\\s+"), " ").take(MAX_SHORT_LABEL_LENGTH),
        )
    }
    .toList()

/** Publishes only server-scoped, recently active conversations. New chat is a static shortcut. */
class ConversationShortcuts(context: Context) {
    private val appContext = context.applicationContext
    private val manager = appContext.getSystemService(ShortcutManager::class.java)

    fun publish(serverUrl: String, threads: List<ThreadSummary>) {
        if (serverUrl.isBlank()) {
            clear()
            return
        }
        val maxCount = (manager.maxShortcutCountPerActivity - STATIC_SHORTCUT_COUNT)
            .coerceIn(0, MAX_RECENT_CONVERSATION_SHORTCUTS)
        manager.dynamicShortcuts = recentConversationShortcuts(serverUrl, threads, maxCount).mapIndexed { rank, shortcut ->
            val label = shortcut.title.ifBlank { appContext.getString(R.string.conversation) }
            ShortcutInfo.Builder(appContext, shortcut.id)
                .setShortLabel(label)
                .setLongLabel(appContext.getString(R.string.shortcut_open_conversation, label))
                .setIcon(Icon.createWithResource(appContext, R.mipmap.ic_launcher))
                .setIntent(MainActivity.conversationShortcutIntent(appContext, serverUrl, shortcut.threadId))
                .setRank(rank)
                .build()
        }
    }

    fun clear() {
        manager.removeAllDynamicShortcuts()
    }
}

private fun shortcutDigest(serverUrl: String, threadId: String): String = MessageDigest
    .getInstance("SHA-256")
    .digest("$serverUrl\u0000$threadId".toByteArray())
    .take(SHORTCUT_DIGEST_LENGTH)
    .joinToString(separator = "") { byte -> "%02x".format(byte.toInt() and 0xff) }

private const val STATIC_SHORTCUT_COUNT = 1
private const val MAX_SHORT_LABEL_LENGTH = 25
private const val SHORTCUT_DIGEST_LENGTH = 8
