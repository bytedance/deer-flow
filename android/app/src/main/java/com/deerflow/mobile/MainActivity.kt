package com.deerflow.mobile

import android.content.Context
import android.content.Intent
import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.appcompat.app.AppCompatActivity
import androidx.activity.viewModels
import com.deerflow.mobile.ui.AppViewModel
import com.deerflow.mobile.ui.DeerFlowApp

class MainActivity : AppCompatActivity() {
    private val viewModel: AppViewModel by viewModels()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        setContent {
            DeerFlowApp(viewModel)
        }
        openDestination(intent)
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        openDestination(intent)
    }

    private fun openDestination(intent: Intent?) {
        when (intent?.action) {
            ACTION_NEW_CONVERSATION -> viewModel.openNewConversationShortcut()
            ACTION_OPEN_CONVERSATION -> viewModel.openRunDestination(
                serverUrl = intent.getStringExtra(EXTRA_SHORTCUT_SERVER_URL),
                threadId = intent.getStringExtra(EXTRA_SHORTCUT_THREAD_ID),
            )
            else -> viewModel.openRunDestination(
                serverUrl = intent?.getStringExtra(EXTRA_RUN_SERVER_URL),
                threadId = intent?.getStringExtra(EXTRA_RUN_THREAD_ID),
            )
        }
    }

    companion object {
        const val ACTION_NEW_CONVERSATION = "com.deerflow.mobile.action.NEW_CONVERSATION"
        const val ACTION_OPEN_CONVERSATION = "com.deerflow.mobile.action.OPEN_CONVERSATION"

        private const val EXTRA_RUN_SERVER_URL = "com.deerflow.mobile.run.SERVER_URL"
        private const val EXTRA_RUN_THREAD_ID = "com.deerflow.mobile.run.THREAD_ID"
        private const val EXTRA_SHORTCUT_SERVER_URL = "com.deerflow.mobile.shortcut.SERVER_URL"
        private const val EXTRA_SHORTCUT_THREAD_ID = "com.deerflow.mobile.shortcut.THREAD_ID"

        fun runDestinationIntent(context: Context, serverUrl: String?, threadId: String?): Intent =
            Intent(context, MainActivity::class.java)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
                .putExtra(EXTRA_RUN_SERVER_URL, serverUrl)
                .putExtra(EXTRA_RUN_THREAD_ID, threadId)

        fun conversationShortcutIntent(context: Context, serverUrl: String, threadId: String): Intent =
            Intent(context, MainActivity::class.java)
                .setAction(ACTION_OPEN_CONVERSATION)
                .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
                .putExtra(EXTRA_SHORTCUT_SERVER_URL, serverUrl)
                .putExtra(EXTRA_SHORTCUT_THREAD_ID, threadId)
    }
}
