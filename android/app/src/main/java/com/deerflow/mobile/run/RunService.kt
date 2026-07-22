package com.deerflow.mobile.run

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Notification
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.graphics.drawable.Icon
import android.os.Build
import android.os.Bundle
import android.os.IBinder
import android.os.SystemClock
import androidx.annotation.RequiresApi
import androidx.core.app.NotificationCompat
import androidx.core.app.ServiceCompat
import androidx.core.content.ContextCompat
import com.deerflow.mobile.MainActivity
import com.deerflow.mobile.R
import com.deerflow.mobile.data.SettingsStore
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

class RunService : Service() {
    private var title: String = ""
    private var progress = RunProgressUpdate(RunProgress.Preparing)
    private var serverUrl: String? = null
    private var threadId: String? = null
    private var notificationSurfaceColor: Int = 0xFFDCE8D8.toInt()
    private var notificationAccentColor: Int = 0xFF234D37.toInt()
    private var terminalSmallIconRes: Int = android.R.drawable.stat_sys_upload_done
    private var liveUpdateDismissed = false
    private var lastPublishedSignature: String? = null
    private var lastNotificationProjection: RunNotificationProjection? = null
    private var lastPublishedAtMs: Long = 0
    private var pendingPublish: Job? = null
    private val serviceScope = CoroutineScope(SupervisorJob() + Dispatchers.Main.immediate)

    override fun onCreate() {
        super.onCreate()
        getSystemService(NotificationManager::class.java).createNotificationChannel(
            NotificationChannel(CHANNEL_ID, getString(R.string.run_channel), NotificationManager.IMPORTANCE_LOW),
        )
        // Keep the notification palette in lockstep with the adaptive launcher icon.
        notificationSurfaceColor = getColor(R.color.ic_launcher_background)
        notificationAccentColor = getColor(R.color.ic_launcher_foreground)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            ACTION_STOP -> {
                serviceScope.launch {
                    RunCoordinator.get(applicationContext).cancelActive()
                    removeNotification()
                    stopSelf(startId)
                }
                return START_NOT_STICKY
            }
            ACTION_UPDATE -> {
                title = intent.getStringExtra(EXTRA_TITLE).orEmpty().ifBlank { title }.ifBlank { getString(R.string.run_in_progress) }
                val phase = intent.getStringExtra(EXTRA_PHASE)?.let { value ->
                    runCatching { RunProgress.valueOf(value) }.getOrNull()
                } ?: progress.phase
                progress = RunProgressUpdate(
                    phase = phase,
                    completedTodos = intent.getIntExtra(EXTRA_COMPLETED_TODOS, 0),
                    totalTodos = intent.getIntExtra(EXTRA_TOTAL_TODOS, 0),
                    currentTodo = intent.getStringExtra(EXTRA_CURRENT_TODO),
                )
                publish(ongoing = true)
            }
            ACTION_COMPLETE -> {
                title = intent.getStringExtra(EXTRA_TITLE).orEmpty().ifBlank { title }
                progress = progress.copy(phase = RunProgress.Completed, currentTodo = null)
                terminalSmallIconRes = android.R.drawable.stat_sys_upload_done
                finish(getString(R.string.run_completed))
                return START_NOT_STICKY
            }
            ACTION_FAILED -> {
                title = intent.getStringExtra(EXTRA_TITLE).orEmpty().ifBlank { title }
                terminalSmallIconRes = android.R.drawable.ic_dialog_alert
                finish(intent.getStringExtra(EXTRA_DETAIL).orEmpty().ifBlank { getString(R.string.run_failed) })
                return START_NOT_STICKY
            }
            ACTION_DISMISSED -> {
                // The foreground service still needs a notification, but no longer requests Live Update promotion.
                liveUpdateDismissed = true
                publish(ongoing = true, force = true)
                return START_STICKY
            }
            else -> {
                if (intent == null) {
                    serviceScope.launch {
                        val recovered = runCatching { recover(applicationContext) }.getOrDefault(false)
                        if (!recovered) {
                            removeNotification()
                            stopSelf(startId)
                        }
                    }
                    return START_NOT_STICKY
                }
                title = intent.getStringExtra(EXTRA_TITLE).orEmpty().ifBlank { getString(R.string.run_in_progress) }
                serverUrl = intent.getStringExtra(EXTRA_SERVER_URL).orEmpty().ifBlank { serverUrl }
                threadId = intent.getStringExtra(EXTRA_THREAD_ID).orEmpty().ifBlank { threadId }
                progress = RunProgressUpdate(RunProgress.Preparing)
                liveUpdateDismissed = false
                publish(ongoing = true)
            }
        }
        return START_STICKY
    }

    private fun publish(ongoing: Boolean, detail: String? = null, force: Boolean = false) {
        val now = SystemClock.elapsedRealtime()
        val projection = progress.notificationProjection()
        val signature = listOf(ongoing, detail.orEmpty(), projection, liveUpdateDismissed).joinToString("|")
        val remainingInterval = NOTIFICATION_UPDATE_INTERVAL_MS - (now - lastPublishedAtMs)
        if (
            ongoing &&
            !force &&
            lastNotificationProjection != null &&
            lastNotificationProjection != projection &&
            remainingInterval > 0
        ) {
            pendingPublish?.cancel()
            pendingPublish = serviceScope.launch {
                delay(remainingInterval)
                pendingPublish = null
                publish(ongoing = true)
            }
            return
        }
        if (ongoing && !shouldPublishOngoingNotification(lastNotificationProjection, projection, lastPublishedAtMs, now, force)) return
        val openIntent = PendingIntent.getActivity(
            this,
            threadId?.hashCode() ?: 0,
            MainActivity.runDestinationIntent(this, serverUrl, threadId),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val stopIntent = PendingIntent.getService(
            this,
            1,
            Intent(this, RunService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val dismissIntent = PendingIntent.getService(
            this,
            2,
            Intent(this, RunService::class.java).setAction(ACTION_DISMISSED),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
        )
        val notification = if (ongoing && Build.VERSION.SDK_INT >= 36 && shouldUseLiveUpdate()) {
            buildLiveUpdate(openIntent, stopIntent, dismissIntent, ongoing, detail)
        } else if (ongoing) {
            buildCompatNotification(openIntent, stopIntent, ongoing, detail)
        } else {
            buildTerminalNotification(openIntent, detail)
        }
        if (ongoing) {
            ServiceCompat.startForeground(
                this,
                NOTIFICATION_ID,
                notification,
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC else 0,
            )
        } else {
            getSystemService(NotificationManager::class.java).notify(NOTIFICATION_ID, notification)
        }
        lastPublishedSignature = signature
        lastNotificationProjection = projection
        lastPublishedAtMs = now
        pendingPublish?.cancel()
        pendingPublish = null
    }

    private fun shouldUseLiveUpdate(): Boolean {
        if (Build.VERSION.SDK_INT < 36 || liveUpdateDismissed) return false
        return getSystemService(NotificationManager::class.java).canPostPromotedNotifications()
    }

    @RequiresApi(36)
    private fun buildLiveUpdate(
        openIntent: PendingIntent,
        stopIntent: PendingIntent,
        dismissIntent: PendingIntent,
        ongoing: Boolean,
        detail: String?,
    ): Notification {
        val style = Notification.ProgressStyle()
            .setProgress(progress.percent)
            .setProgressIndeterminate(progress.indeterminate)
            .setStyledByProgress(true)
            .setProgressTrackerIcon(progressTrackerIcon())
            .addProgressSegment(Notification.ProgressStyle.Segment(100).setColor(notificationAccentColor))
        return Notification.Builder(this, CHANNEL_ID)
            // The small icon is what Android renders at the left of a Live Update status chip.
            .setSmallIcon(statusChipSmallIconRes())
            .setContentTitle(title.ifBlank { getString(R.string.run_in_progress) })
            .setContentText(detail ?: progressLabel())
            .setContentIntent(openIntent)
            .setOngoing(ongoing)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .apply {
                // System UI derives the app-title contrast from this surface color.
                setColor(notificationSurfaceColor)
            }
            .setShortCriticalText(statusChip())
            .setStyle(style)
            .addExtras(Bundle().apply { putBoolean(EXTRA_REQUEST_PROMOTED_ONGOING, ongoing) })
            .setDeleteIntent(dismissIntent)
            .apply {
                if (ongoing) {
                    addAction(
                        Notification.Action.Builder(
                            Icon.createWithResource(this@RunService, android.R.drawable.ic_media_pause),
                            getString(R.string.stop_run),
                            stopIntent,
                        ).build(),
                    )
                }
            }
            .build()
    }

    private fun buildCompatNotification(
        openIntent: PendingIntent,
        stopIntent: PendingIntent,
        ongoing: Boolean,
        detail: String?,
    ): Notification = NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(statusChipSmallIconRes())
            .setContentTitle(title.ifBlank { getString(R.string.run_in_progress) })
            .setContentText(detail ?: progressLabel())
            .setContentIntent(openIntent)
            .setOngoing(ongoing)
            .setOnlyAlertOnce(true)
            .setColor(notificationSurfaceColor)
            .setProgress(if (progress.indeterminate) 0 else 100, progress.percent, progress.indeterminate)
            .apply { if (ongoing) addAction(0, getString(R.string.stop_run), stopIntent) }
            .build()

    private fun buildTerminalNotification(openIntent: PendingIntent, detail: String?): Notification {
        val terminalTitle = title.ifBlank { getString(R.string.run_in_progress) }
        val terminalDetail = detail ?: progressLabel()
        return NotificationCompat.Builder(this, CHANNEL_ID)
            .setSmallIcon(terminalSmallIconRes)
            .setContentTitle(terminalTitle)
            .setContentText(terminalDetail)
            .setContentIntent(openIntent)
            .setAutoCancel(true)
            .setOnlyAlertOnce(true)
            .setColor(notificationSurfaceColor)
            .setStyle(NotificationCompat.BigTextStyle().bigText(terminalDetail))
            .build()
    }

    private fun phaseLabel(progress: RunProgress): Int = when (progress) {
        RunProgress.Preparing -> R.string.run_preparing
        RunProgress.Uploading -> R.string.run_uploading
        RunProgress.Connecting -> R.string.run_connecting
        RunProgress.Working, RunProgress.Responding -> R.string.run_running
        RunProgress.Reconnecting -> R.string.run_reconnecting
        RunProgress.Finalizing -> R.string.run_finalizing
        RunProgress.Completed -> R.string.run_completed
    }

    private fun progressLabel(): String = if (progress.indeterminate) {
        progress.currentTodo?.let { getString(R.string.run_current_step, it) }
            ?: getString(phaseLabel(progress.phase))
    } else {
        progress.currentTodo?.let { getString(R.string.run_current_step, it) }
            ?: getString(R.string.run_plan_progress, progress.completedTodos, progress.totalTodos)
    }

    private fun statusChip(): String = progress.todoChip ?: getString(
        when (progress.phase) {
            RunProgress.Preparing -> R.string.run_chip_preparing
            RunProgress.Uploading -> R.string.run_chip_uploading
            RunProgress.Connecting -> R.string.run_chip_connecting
            RunProgress.Working -> R.string.run_chip_working
            RunProgress.Responding -> R.string.run_chip_responding
            RunProgress.Reconnecting -> R.string.run_chip_reconnecting
            RunProgress.Finalizing -> R.string.run_chip_finalizing
            RunProgress.Completed -> R.string.run_chip_completed
        },
    )

    @RequiresApi(36)
    private fun progressTrackerIcon(): Icon = Icon.createWithResource(
        this,
        when (progress.phase) {
            RunProgress.Uploading -> android.R.drawable.stat_sys_upload
            RunProgress.Reconnecting -> android.R.drawable.stat_notify_sync
            RunProgress.Working, RunProgress.Responding -> android.R.drawable.stat_notify_sync_noanim
            RunProgress.Finalizing, RunProgress.Completed -> android.R.drawable.stat_sys_upload_done
            RunProgress.Preparing, RunProgress.Connecting -> android.R.drawable.stat_notify_sync
        },
    )

    private fun statusChipSmallIconRes(): Int = when (progress.phase) {
        RunProgress.Uploading -> android.R.drawable.stat_sys_upload
        RunProgress.Completed -> android.R.drawable.stat_sys_upload_done
        else -> android.R.drawable.stat_notify_sync
    }

    private fun finish(detail: String) {
        serviceScope.launch {
            pendingPublish?.cancel()
            pendingPublish = null
            if (SettingsStore(this@RunService).read().notifyOnRunCompletion) {
                // Stop the foreground notification first. Some OEMs remove a terminal result
                // published before the foreground-service teardown completes.
                stopForeground(STOP_FOREGROUND_REMOVE)
                getSystemService(NotificationManager::class.java).notify(
                    NOTIFICATION_ID,
                    buildTerminalNotification(
                        PendingIntent.getActivity(
                            this@RunService,
                            threadId?.hashCode() ?: 0,
                            MainActivity.runDestinationIntent(this@RunService, serverUrl, threadId),
                            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE,
                        ),
                        detail,
                    ),
                )
            } else {
                removeNotification()
            }
            lastPublishedSignature = null
            lastNotificationProjection = null
            lastPublishedAtMs = 0
            stopSelf()
        }
    }

    private fun removeNotification() {
        pendingPublish?.cancel()
        pendingPublish = null
        getSystemService(NotificationManager::class.java).cancel(NOTIFICATION_ID)
        stopForeground(STOP_FOREGROUND_REMOVE)
        lastPublishedSignature = null
        lastNotificationProjection = null
        lastPublishedAtMs = 0
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onDestroy() {
        serviceScope.cancel()
        super.onDestroy()
    }

    companion object {
        private const val CHANNEL_ID = "deerflow-runs"
        private const val NOTIFICATION_ID = 2026
        private const val ACTION_STOP = "com.deerflow.mobile.action.STOP_RUN"
        private const val ACTION_UPDATE = "com.deerflow.mobile.action.UPDATE_RUN"
        private const val ACTION_COMPLETE = "com.deerflow.mobile.action.COMPLETE_RUN"
        private const val ACTION_FAILED = "com.deerflow.mobile.action.FAILED_RUN"
        internal const val ACTION_DISMISSED = "com.deerflow.mobile.action.DISMISS_RUN_LIVE_UPDATE"
        private const val EXTRA_TITLE = "title"
        private const val EXTRA_PHASE = "phase"
        private const val EXTRA_DETAIL = "detail"
        private const val EXTRA_SERVER_URL = "server_url"
        private const val EXTRA_THREAD_ID = "thread_id"
        private const val EXTRA_COMPLETED_TODOS = "completed_todos"
        private const val EXTRA_TOTAL_TODOS = "total_todos"
        private const val EXTRA_CURRENT_TODO = "current_todo"
        internal const val EXTRA_REQUEST_PROMOTED_ONGOING = "android.requestPromotedOngoing"

        fun start(context: Context, title: String, serverUrl: String? = null, threadId: String? = null) {
            ContextCompat.startForegroundService(
                context,
                Intent(context, RunService::class.java)
                    .putExtra(EXTRA_TITLE, title)
                    .putExtra(EXTRA_SERVER_URL, serverUrl)
                    .putExtra(EXTRA_THREAD_ID, threadId),
            )
        }

        fun update(context: Context, update: RunProgressUpdate, title: String? = null) {
            context.startService(
                Intent(context, RunService::class.java)
                    .setAction(ACTION_UPDATE)
                    .putExtra(EXTRA_PHASE, update.phase.name)
                    .putExtra(EXTRA_COMPLETED_TODOS, update.completedTodos)
                    .putExtra(EXTRA_TOTAL_TODOS, update.totalTodos)
                    .putExtra(EXTRA_CURRENT_TODO, update.currentTodo)
                    .putExtra(EXTRA_TITLE, title),
            )
        }

        fun update(context: Context, phase: RunProgress, title: String? = null) =
            update(context, RunProgressUpdate(phase), title)

        fun complete(context: Context, title: String? = null) {
            context.startService(
                Intent(context, RunService::class.java)
                    .setAction(ACTION_COMPLETE)
                    .putExtra(EXTRA_TITLE, title),
            )
        }

        fun fail(context: Context, detail: String, title: String? = null) {
            context.startService(
                Intent(context, RunService::class.java)
                    .setAction(ACTION_FAILED)
                    .putExtra(EXTRA_TITLE, title)
                    .putExtra(EXTRA_DETAIL, detail),
            )
        }

        fun stop(context: Context) {
            context.stopService(Intent(context, RunService::class.java))
            context.getSystemService(NotificationManager::class.java).cancel(NOTIFICATION_ID)
        }

        suspend fun recover(context: Context, serverUrl: String? = null): Boolean =
            RunCoordinator.get(context).recoverLatest(serverUrl)
    }
}
