package com.deerflow.mobile.run

import android.Manifest
import android.app.Notification
import android.app.NotificationManager
import android.content.Intent
import android.content.pm.PackageManager
import android.os.SystemClock
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.filters.SdkSuppress
import androidx.test.platform.app.InstrumentationRegistry
import com.deerflow.mobile.data.SettingsStore
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Test
import org.junit.Assume.assumeTrue
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
@SdkSuppress(minSdkVersion = 36)
class RunServiceLiveUpdateTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val context = instrumentation.targetContext
    private val notifications = context.getSystemService(NotificationManager::class.java)

    @Before
    fun grantNotificationPermission() {
        RunService.stop(context)
        notifications.cancel(2026)
        SystemClock.sleep(200)
        if (context.checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
            instrumentation.uiAutomation.grantRuntimePermission(context.packageName, Manifest.permission.POST_NOTIFICATIONS)
        }
        runBlocking { SettingsStore(context).setNotifyOnRunCompletion(true) }
    }

    @After
    fun cleanUp() {
        RunService.stop(context)
        runBlocking { SettingsStore(context).setNotifyOnRunCompletion(true) }
    }

    @Test
    fun ongoingRunRequestsPromotedProgressNotification() {
        assumeTrue(notifications.canPostPromotedNotifications())
        RunService.start(context, "Research workspace")
        val preparing = awaitRunNotification()

        assertTrue(preparing.flags and Notification.FLAG_ONGOING_EVENT != 0)
        assertTrue(preparing.extras.getBoolean(RunService.EXTRA_REQUEST_PROMOTED_ONGOING))
        assertTrue(preparing.flags and Notification.FLAG_PROMOTED_ONGOING != 0)
        assertEquals(RunProgress.Preparing.percent, preparing.extras.getInt(Notification.EXTRA_PROGRESS))
        assertEquals(Notification.ProgressStyle::class.java.name, preparing.extras.getString(Notification.EXTRA_TEMPLATE))
        assertTrue(preparing.hasPromotableCharacteristics())
        assertEquals("Prep", preparing.shortCriticalText)
        assertEquals(expectedLiveUpdateColor(), preparing.color)
        assertNotNull(preparing.smallIcon)
        assertNotNull(preparing.actions.single().icon)

        RunService.update(
            context,
            RunProgressUpdate(
                phase = RunProgress.Working,
                completedTodos = 1,
                totalTodos = 3,
                currentTodo = "Write report",
            ),
            "Research workspace",
        )
        val working = awaitRunNotification(expectedProgress = 33)
        assertEquals("1/3", working.shortCriticalText)
        assertEquals("Working: Write report", working.extras.getCharSequence(Notification.EXTRA_TEXT).toString())
        assertNotNull(working.smallIcon)
    }

    @Test
    fun enabledPreferenceKeepsTerminalNotification() {
        RunService.start(context, "Research workspace")
        val ongoing = awaitRunNotification(isOngoing = true)
        assertEquals(context.getColor(com.deerflow.mobile.R.color.ic_launcher_background), ongoing.color)
        assertEquals("Research workspace", ongoing.extras.getCharSequence(Notification.EXTRA_TITLE).toString())

        RunService.complete(context, "Research workspace")

        val completed = awaitRunNotification(isOngoing = false)
        assertTrue(completed.flags and Notification.FLAG_ONGOING_EVENT == 0)
        assertEquals(context.getColor(com.deerflow.mobile.R.color.ic_launcher_background), completed.color)
        assertEquals("Research workspace", completed.extras.getCharSequence(Notification.EXTRA_TITLE).toString())
        assertNotNull(completed.smallIcon)
    }

    @Test
    fun disabledPreferenceRemovesNotificationAfterTheServiceStops() {
        runBlocking { SettingsStore(context).setNotifyOnRunCompletion(false) }
        RunService.start(context, "Research workspace")
        awaitRunNotification(isOngoing = true)

        RunService.complete(context, "Research workspace")
        awaitRunNotificationRemoved()
    }

    @Test
    fun dismissedLiveUpdateFallsBackToAStandardForegroundNotification() {
        assumeTrue(notifications.canPostPromotedNotifications())
        RunService.start(context, "Research workspace")
        awaitRunNotification(isOngoing = true, expectedPromoted = true)

        context.startService(
            Intent(context, RunService::class.java).setAction(RunService.ACTION_DISMISSED),
        )

        val fallback = awaitRunNotification(isOngoing = true, expectedPromoted = false)
        assertEquals("Research workspace", fallback.extras.getString(Notification.EXTRA_TITLE))
        assertFalse(fallback.extras.getBoolean(RunService.EXTRA_REQUEST_PROMOTED_ONGOING))
    }

    private fun awaitRunNotification(
        expectedProgress: Int? = null,
        isOngoing: Boolean? = null,
        expectedPromoted: Boolean? = null,
    ): Notification {
        repeat(40) {
            val notification = notifications.activeNotifications
                .firstOrNull { it.id == 2026 }
                ?.notification
            val ongoing = notification?.flags?.and(Notification.FLAG_ONGOING_EVENT) != 0
            if (
                notification != null &&
                (expectedProgress == null || notification.extras.getInt(Notification.EXTRA_PROGRESS) == expectedProgress) &&
                (isOngoing == null || ongoing == isOngoing) &&
                (expectedPromoted == null || notification.extras.getBoolean(RunService.EXTRA_REQUEST_PROMOTED_ONGOING) == expectedPromoted)
            ) {
                return notification
            }
            SystemClock.sleep(100)
        }
        assertNotNull("Run notification was not posted", null)
        error("Run notification was not posted")
    }

    private fun awaitRunNotificationRemoved() {
        repeat(40) {
            if (notifications.activeNotifications.none { it.id == 2026 }) return
            SystemClock.sleep(100)
        }
        assertTrue("Run notification should have been removed", notifications.activeNotifications.none { it.id == 2026 })
    }

    private fun expectedLiveUpdateColor(): Int =
        context.getColor(com.deerflow.mobile.R.color.ic_launcher_background)

}
