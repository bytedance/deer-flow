package com.deerflow.mobile.run

import com.deerflow.mobile.data.TodoItem
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class RunProgressTest {
    @Test
    fun normalRunMilestonesAdvanceTowardCompletion() {
        val milestones = listOf(
            RunProgress.Preparing,
            RunProgress.Uploading,
            RunProgress.Connecting,
            RunProgress.Working,
            RunProgress.Responding,
            RunProgress.Finalizing,
            RunProgress.Completed,
        )

        assertEquals(100, RunProgress.Completed.percent)
        assertTrue(milestones.zipWithNext().all { (first, second) -> first.percent < second.percent })
    }

    @Test
    fun reconnectShowsEarlierRecoveryProgress() {
        assertTrue(RunProgress.Reconnecting.percent < RunProgress.Working.percent)
        assertTrue(RunProgress.Reconnecting.percent > RunProgress.Connecting.percent)
    }

    @Test
    fun noPlanUsesAnIndeterminateProgressIndicator() {
        val update = runProgressUpdate(RunProgress.Responding, emptyList())

        assertTrue(update.indeterminate)
        assertEquals(RunProgress.Responding.percent, update.percent)
    }

    @Test
    fun planUsesCompletedTodoRatioForProgress() {
        val update = runProgressUpdate(
            RunProgress.Working,
            listOf(
                TodoItem("Collect evidence", "completed"),
                TodoItem("Write report", "in_progress"),
                TodoItem("Review", "pending"),
            ),
        )

        assertFalse(update.indeterminate)
        assertEquals(1, update.completedTodos)
        assertEquals(3, update.totalTodos)
        assertEquals(33, update.percent)
        assertEquals("Write report", update.currentTodo)
        assertEquals("1/3", update.todoChip)
    }

    @Test
    fun currentTodoIsNormalizedAndBoundedForTheNotification() {
        val update = runProgressUpdate(
            RunProgress.Working,
            listOf(TodoItem("  Draft\n  the   final report ", "running")),
        )

        assertEquals("Draft the final report", update.currentTodo)
    }

    @Test
    fun completedTodosDoNotMarkAnActiveRunAsComplete() {
        val active = runProgressUpdate(RunProgress.Working, listOf(TodoItem("Publish", "completed")))
        val terminal = active.copy(phase = RunProgress.Completed)

        assertEquals(99, active.percent)
        assertEquals(100, terminal.percent)
    }

    @Test
    fun notificationProjectionOnlyPublishesMeaningfulChangesAtMostOncePerSecond() {
        val initial = RunProgressUpdate(RunProgress.Working).notificationProjection()
        val same = RunProgressUpdate(RunProgress.Working).notificationProjection()
        val changed = RunProgressUpdate(RunProgress.Responding).notificationProjection()

        assertFalse(shouldPublishOngoingNotification(initial, same, 1_000, 2_100, force = false))
        assertFalse(shouldPublishOngoingNotification(initial, changed, 1_000, 1_500, force = false))
        assertTrue(shouldPublishOngoingNotification(initial, changed, 1_000, 2_000, force = false))
        assertTrue(shouldPublishOngoingNotification(initial, same, 1_000, 1_001, force = true))
    }
}
