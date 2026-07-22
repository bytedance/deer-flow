package com.deerflow.mobile.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.test.core.app.ApplicationProvider
import com.deerflow.mobile.R
import com.deerflow.mobile.data.ScheduledTaskInfo
import com.deerflow.mobile.data.ScheduledTaskRunInfo
import com.deerflow.mobile.data.TaskSchedule
import com.deerflow.mobile.data.isFutureOnceSchedule
import java.util.concurrent.atomic.AtomicReference
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class TasksScreenTest {
    @get:Rule val compose = createComposeRule()

    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()

    @Test
    fun cronTaskRowDispatchesRunHistoryPauseEditAndDelete() {
        val actions = mutableListOf<String>()
        setTaskRow(
            task = task(),
            onPause = { actions += "pause" },
            onTrigger = { actions += "run" },
            onEdit = { actions += "edit" },
            onDelete = { actions += "delete" },
            onHistory = { actions += "history" },
        )

        compose.onNodeWithTag(UiTags.TaskRunNow).performClick()
        compose.onNodeWithTag(UiTags.TaskHistoryPrefix + "task-1").performClick()
        openTaskMenu()
        compose.onNodeWithTag(UiTags.TaskPauseResume).performClick()
        openTaskMenu()
        compose.onNodeWithTag(UiTags.TaskEdit).performClick()
        openTaskMenu()
        compose.onNodeWithTag(UiTags.TaskDelete).performClick()

        compose.runOnIdle { assertEquals(listOf("run", "history", "pause", "edit", "delete"), actions) }
    }

    @Test
    fun executionHistoryOpensDetailAndDispatchesConversationNavigation() {
        val run = taskRun(status = "failed", error = "The configured model was unavailable.")
        var openedRun: ScheduledTaskRunInfo? = null
        compose.setContent {
            MaterialTheme {
                TaskRunHistorySheet(
                    task = task(),
                    runs = listOf(run),
                    loading = false,
                    onDismiss = {},
                    onRefresh = {},
                    onOpenConversation = { openedRun = it },
                )
            }
        }

        compose.onNodeWithTag(UiTags.TaskRunPrefix + run.id).performClick()
        compose.onNodeWithText(context.getString(R.string.execution_detail)).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.task_run_status_failed)).assertIsDisplayed()
        compose.onNodeWithText(run.error!!).assertIsDisplayed()
        compose.onNodeWithTag(UiTags.TaskRunOpenConversation).performScrollTo().performClick()

        compose.runOnIdle { assertEquals(run, openedRun) }
    }

    @Test
    fun pausedNonCronTaskResumesWithoutEditAction() {
        var resumes = 0
        setTaskRow(task = task(scheduleType = "interval", status = "paused"), onPause = { resumes += 1 })

        openTaskMenu()
        compose.onNodeWithText(context.getString(R.string.resume)).assertIsDisplayed()
        compose.onNodeWithTag(UiTags.TaskEdit).assertDoesNotExist()
        compose.onNodeWithTag(UiTags.TaskPauseResume).performClick()

        compose.runOnIdle { assertEquals(1, resumes) }
    }

    @Test
    fun createTaskEditorCollectsRequiredScheduleFields() {
        val saved = AtomicReference<SavedTask?>(null)
        setTaskEditor { title, prompt, schedule, timezone -> saved.set(SavedTask(title, prompt, schedule, timezone)) }

        compose.onNodeWithTag(UiTags.TaskEditorTitle).performTextReplacement("Daily brief")
        compose.onNodeWithTag(UiTags.TaskEditorPrompt).performTextReplacement("Summarize overnight changes")
        compose.onNodeWithTag(UiTags.TaskEditorCron).performTextReplacement("0 8 * * *")
        compose.onNodeWithTag(UiTags.TaskEditorTimezone).performTextReplacement("Asia/Shanghai")
        compose.waitForIdle()
        compose.onNodeWithTag(UiTags.TaskEditorSave).performScrollTo()
        compose.waitForIdle()
        compose.onNodeWithTag(UiTags.TaskEditorSave).assertIsEnabled().performClick()
        compose.waitUntil(timeoutMillis = 15_000) { saved.get() != null }

        compose.runOnIdle {
            assertEquals(
                SavedTask(
                    "Daily brief",
                    "Summarize overnight changes",
                    TaskSchedule.Cron("0 8 * * *"),
                    "Asia/Shanghai",
                ),
                saved.get(),
            )
        }
    }

    @Test
    fun editTaskEditorUpdatesExistingSchedule() {
        val saved = AtomicReference<SavedTask?>(null)
        setTaskEditor(task()) { title, prompt, schedule, timezone -> saved.set(SavedTask(title, prompt, schedule, timezone)) }

        compose.onNodeWithTag(UiTags.TaskEditorTitle).performTextReplacement("Updated brief")
        compose.waitForIdle()
        compose.onNodeWithTag(UiTags.TaskEditorSave).performScrollTo()
        compose.waitForIdle()
        compose.onNodeWithTag(UiTags.TaskEditorSave).assertIsEnabled().performClick()
        compose.waitUntil(timeoutMillis = 10_000) { saved.get() != null }

        compose.runOnIdle {
            assertEquals(SavedTask("Updated brief", "Review changes", TaskSchedule.Cron("0 9 * * *"), "UTC"), saved.get())
        }
    }

    @Test
    fun createTaskEditorSupportsOneTimeSchedules() {
        val saved = AtomicReference<SavedTask?>(null)
        setTaskEditor { title, prompt, schedule, timezone -> saved.set(SavedTask(title, prompt, schedule, timezone)) }

        compose.onNodeWithTag(UiTags.TaskEditorTitle).performTextReplacement("Release review")
        compose.onNodeWithTag(UiTags.TaskEditorPrompt).performTextReplacement("Review the final release")
        compose.onNodeWithTag(UiTags.TaskEditorScheduleOnce).performClick()
        compose.onNodeWithTag(UiTags.TaskEditorOnceDate).performScrollTo()
        compose.onNodeWithTag(UiTags.TaskEditorOnceTime).performScrollTo()
        compose.onNodeWithTag(UiTags.TaskEditorSave).performScrollTo().assertIsEnabled().performClick()
        compose.waitUntil(timeoutMillis = 10_000) { saved.get() != null }

        compose.runOnIdle {
            assertEquals("Release review", saved.get()?.title)
            assertEquals("Review the final release", saved.get()?.prompt)
            assertEquals(true, (saved.get()?.schedule as? TaskSchedule.Once)?.let(::isFutureOnceSchedule))
        }
    }

    private fun setTaskRow(
        task: ScheduledTaskInfo,
        onPause: () -> Unit = {},
        onTrigger: () -> Unit = {},
        onEdit: (() -> Unit)? = null,
        onDelete: () -> Unit = {},
        onHistory: () -> Unit = {},
    ) {
        compose.setContent {
            MaterialTheme {
                TaskRow(task, onPause, onTrigger, onEdit, onDelete, onHistory)
            }
        }
    }

    private fun setTaskEditor(
        task: ScheduledTaskInfo? = null,
        onSave: (String, String, TaskSchedule, String) -> Unit,
    ) {
        compose.setContent {
            MaterialTheme {
                TaskEditorSheet(
                    state = AppUiState(serverUrl = "http://10.0.2.2:2027"),
                    task = task,
                    onDismiss = {},
                    onSave = onSave,
                )
            }
        }
    }

    private fun openTaskMenu() {
        compose.onNodeWithTag(UiTags.TaskMoreActions).performClick()
    }

    private fun task(
        scheduleType: String = "cron",
        status: String = "active",
        scheduleLabel: String = "0 9 * * *",
    ) = ScheduledTaskInfo(
        id = "task-1",
        title = "Daily review",
        prompt = "Review changes",
        scheduleType = scheduleType,
        scheduleLabel = scheduleLabel,
        timezone = "UTC",
        status = status,
        nextRunAt = null,
        lastError = null,
        runCount = 3,
    )

    private fun taskRun(
        status: String = "success",
        error: String? = null,
    ) = ScheduledTaskRunInfo(
        id = "task-run-1",
        taskId = "task-1",
        threadId = "thread-1",
        runId = "gateway-run-1",
        scheduledFor = "2026-07-20T09:00:00+08:00",
        trigger = "scheduled",
        status = status,
        error = error,
        startedAt = "2026-07-20T09:00:02+08:00",
        finishedAt = "2026-07-20T09:00:10+08:00",
        createdAt = "2026-07-20T09:00:00+08:00",
    )

    private data class SavedTask(
        val title: String,
        val prompt: String,
        val schedule: TaskSchedule,
        val timezone: String,
    )
}
