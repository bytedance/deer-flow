@file:OptIn(
    androidx.compose.material3.ExperimentalMaterial3Api::class,
    androidx.compose.material3.ExperimentalMaterial3ExpressiveApi::class,
)

package com.deerflow.mobile.ui

import android.app.DatePickerDialog
import android.app.TimePickerDialog
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.PlayArrow
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.outlined.ArrowBack
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.History
import androidx.compose.material.icons.outlined.Menu
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.Pause
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Schedule
import androidx.compose.material.icons.outlined.OpenInNew
import androidx.compose.material3.Icon
import androidx.compose.material3.LoadingIndicator
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Button
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.deerflow.mobile.R
import com.deerflow.mobile.data.ScheduledTaskInfo
import com.deerflow.mobile.data.ScheduledTaskRunInfo
import com.deerflow.mobile.data.TaskSchedule
import com.deerflow.mobile.data.isFutureOnceSchedule
import com.deerflow.mobile.data.onceScheduleFor
import com.deerflow.mobile.data.parseOnceSchedule
import java.time.LocalDateTime
import java.time.format.DateTimeFormatter

@Composable
fun TasksScreen(state: AppUiState, viewModel: AppViewModel, onBack: () -> Unit, contentPadding: PaddingValues) {
    var creating by remember { mutableStateOf(false) }
    var editing by remember { mutableStateOf<ScheduledTaskInfo?>(null) }
    var historyTask by remember { mutableStateOf<ScheduledTaskInfo?>(null) }
    Column(Modifier.fillMaxSize().padding(contentPadding)) {
        TopAppBar(
            navigationIcon = {
                IconButton(onClick = onBack, modifier = Modifier.size(48.dp)) {
                    Icon(Icons.Outlined.ArrowBack, contentDescription = stringResource(R.string.back))
                }
            },
            title = { Text(stringResource(R.string.tasks_title)) },
            actions = {
                IconButton(onClick = { creating = true }, enabled = !state.workspaceMutationBusy, modifier = Modifier.size(48.dp)) {
                    Icon(Icons.Filled.Add, contentDescription = stringResource(R.string.create_task))
                }
                IconButton(onClick = viewModel::refreshTasks, enabled = !state.loadingTasks, modifier = Modifier.size(48.dp)) {
                    Icon(Icons.Outlined.Refresh, contentDescription = stringResource(R.string.refresh))
                }
            },
            colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
        )
        Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            when {
                state.loadingTasks && state.tasks.isEmpty() -> LoadingIndicator(Modifier.size(32.dp))
                state.tasks.isEmpty() -> EmptyState(
                    icon = { Icon(Icons.Outlined.Schedule, contentDescription = null, modifier = Modifier.size(46.dp), tint = MaterialTheme.colorScheme.primary) },
                    title = stringResource(R.string.no_tasks),
                    body = stringResource(R.string.no_tasks_body),
                )
                else -> LazyColumn(
                    modifier = Modifier.fillMaxSize(),
                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 12.dp),
                    verticalArrangement = Arrangement.spacedBy(8.dp),
                ) {
                    items(state.tasks, key = { it.id }) { task ->
                        TaskRow(
                            task = task,
                            onPause = { viewModel.pauseTask(task) },
                            onTrigger = { viewModel.triggerTask(task) },
                            onEdit = if (task.scheduleType in setOf("cron", "once")) ({ editing = task }) else null,
                            onDelete = { viewModel.deleteTask(task) },
                            onHistory = {
                                historyTask = task
                                viewModel.loadTaskRuns(task)
                            },
                        )
                    }
                }
            }
        }
    }
    if (creating || editing != null) {
        TaskEditorSheet(
            state = state,
            task = editing,
            onDismiss = { creating = false; editing = null },
            onSave = { title, prompt, schedule, timezone ->
                viewModel.saveTask(editing, title, prompt, schedule, timezone) {
                    creating = false
                    editing = null
                }
            },
        )
    }
    historyTask?.let { task ->
        TaskRunHistorySheet(
            task = task,
            runs = if (state.taskRunsTaskId == task.id) state.taskRuns else emptyList(),
            loading = state.loadingTaskRuns && state.taskRunsTaskId == task.id,
            onDismiss = { historyTask = null },
            onRefresh = { viewModel.loadTaskRuns(task) },
            onOpenConversation = { run ->
                historyTask = null
                viewModel.openTaskRunConversation(task, run)
            },
        )
    }
}

@Composable
internal fun TaskRow(
    task: ScheduledTaskInfo,
    onPause: () -> Unit,
    onTrigger: () -> Unit,
    onEdit: (() -> Unit)?,
    onDelete: () -> Unit,
    onHistory: () -> Unit = {},
) {
    var menuExpanded by remember { mutableStateOf(false) }
    ListItem(
        headlineContent = { Text(task.title, maxLines = 2, overflow = TextOverflow.Ellipsis) },
        supportingContent = {
            Column {
                Text(task.prompt, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Text(
                    "${task.scheduleLabel} · ${task.timezone}",
                    style = MaterialTheme.typography.bodyMedium,
                    color = MaterialTheme.colorScheme.onSurfaceVariant,
                )
                task.lastError?.let { Text(it, color = MaterialTheme.colorScheme.error, maxLines = 2, overflow = TextOverflow.Ellipsis) }
            }
        },
        leadingContent = {
            StatusDot(
                status = task.status,
                description = stringResource(R.string.status_description, task.status),
            )
        },
        trailingContent = {
            Row {
                IconButton(
                    onClick = onTrigger,
                    enabled = task.status != "running",
                    modifier = Modifier.size(48.dp).testTag(UiTags.TaskRunNow),
                ) {
                    Icon(Icons.Filled.PlayArrow, contentDescription = stringResource(R.string.run_now))
                }
                IconButton(
                    onClick = onHistory,
                    modifier = Modifier.size(48.dp).testTag(UiTags.TaskHistoryPrefix + task.id),
                ) {
                    Icon(Icons.Outlined.History, contentDescription = stringResource(R.string.execution_history))
                }
                Box {
                    IconButton(
                        onClick = { menuExpanded = true },
                        enabled = task.status != "running",
                        modifier = Modifier.size(48.dp).testTag(UiTags.TaskMoreActions),
                    ) {
                        Icon(Icons.Outlined.MoreVert, contentDescription = stringResource(R.string.more_actions))
                    }
                    DropdownMenu(expanded = menuExpanded, onDismissRequest = { menuExpanded = false }) {
                        DropdownMenuItem(
                            text = { Text(stringResource(if (task.status == "paused") R.string.resume else R.string.pause)) },
                            leadingIcon = { Icon(if (task.status == "paused") Icons.Filled.PlayArrow else Icons.Outlined.Pause, contentDescription = null) },
                            onClick = { menuExpanded = false; onPause() },
                            modifier = Modifier.testTag(UiTags.TaskPauseResume),
                        )
                        if (onEdit != null) {
                            DropdownMenuItem(
                                text = { Text(stringResource(R.string.edit)) },
                                leadingIcon = { Icon(Icons.Outlined.Edit, contentDescription = null) },
                                onClick = { menuExpanded = false; onEdit() },
                                modifier = Modifier.testTag(UiTags.TaskEdit),
                            )
                        }
                        DropdownMenuItem(
                            text = { Text(stringResource(R.string.delete)) },
                            leadingIcon = { Icon(Icons.Outlined.DeleteOutline, contentDescription = null) },
                            onClick = { menuExpanded = false; onDelete() },
                            modifier = Modifier.testTag(UiTags.TaskDelete),
                        )
                    }
                }
            }
        },
        modifier = Modifier.fillMaxWidth().testTag(UiTags.TaskRowPrefix + task.id),
    )
}

@Composable
internal fun TaskRunHistorySheet(
    task: ScheduledTaskInfo,
    runs: List<ScheduledTaskRunInfo>,
    loading: Boolean,
    onDismiss: () -> Unit,
    onRefresh: () -> Unit,
    onOpenConversation: (ScheduledTaskRunInfo) -> Unit,
) {
    var selectedRun by remember(task.id) { mutableStateOf<ScheduledTaskRunInfo?>(null) }
    ModalBottomSheet(onDismissRequest = onDismiss, modifier = Modifier.testTag(UiTags.TaskRunHistorySheet)) {
        when (val detail = selectedRun) {
            null -> TaskRunList(
                task = task,
                runs = runs,
                loading = loading,
                onRefresh = onRefresh,
                onSelect = { selectedRun = it },
            )
            else -> TaskRunDetail(
                run = detail,
                onBack = { selectedRun = null },
                onOpenConversation = { onOpenConversation(detail) },
            )
        }
    }
}

@Composable
private fun TaskRunList(
    task: ScheduledTaskInfo,
    runs: List<ScheduledTaskRunInfo>,
    loading: Boolean,
    onRefresh: () -> Unit,
    onSelect: (ScheduledTaskRunInfo) -> Unit,
) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(stringResource(R.string.execution_history), style = MaterialTheme.typography.titleLarge)
                Text(task.title, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            IconButton(onClick = onRefresh, enabled = !loading, modifier = Modifier.size(48.dp)) {
                Icon(Icons.Outlined.Refresh, contentDescription = stringResource(R.string.refresh))
            }
        }
        when {
            loading -> Box(Modifier.fillMaxWidth().height(180.dp), contentAlignment = Alignment.Center) {
                LoadingIndicator(Modifier.size(32.dp))
            }
            runs.isEmpty() -> Box(Modifier.fillMaxWidth().height(180.dp), contentAlignment = Alignment.Center) {
                Text(stringResource(R.string.no_task_runs), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            else -> LazyColumn(
                modifier = Modifier.fillMaxWidth().heightIn(max = 520.dp),
                contentPadding = PaddingValues(vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                items(runs, key = { it.id }) { run ->
                    ListItem(
                        headlineContent = { Text(taskRunSummary(run)) },
                        supportingContent = {
                            Text(
                                stringResource(R.string.task_run_scheduled_for, taskRunTimestamp(run.scheduledFor)),
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        },
                        leadingContent = {
                            StatusDot(
                                status = run.status,
                                description = stringResource(R.string.status_description, taskRunStatusLabel(run.status)),
                            )
                        },
                        modifier = Modifier.fillMaxWidth()
                            .clickable { onSelect(run) }
                            .testTag(UiTags.TaskRunPrefix + run.id),
                    )
                }
            }
        }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun TaskRunDetail(
    run: ScheduledTaskRunInfo,
    onBack: () -> Unit,
    onOpenConversation: () -> Unit,
) {
    LazyColumn(
        modifier = Modifier.fillMaxWidth(),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onBack, modifier = Modifier.size(48.dp)) {
                    Icon(Icons.Outlined.ArrowBack, contentDescription = stringResource(R.string.back))
                }
                Text(stringResource(R.string.execution_detail), style = MaterialTheme.typography.titleLarge)
            }
        }
        item { TaskRunDetailRow(stringResource(R.string.task_run_status_label), taskRunStatusLabel(run.status)) }
        item { TaskRunDetailRow(stringResource(R.string.task_run_trigger), taskRunTriggerLabel(run.trigger)) }
        item { TaskRunDetailRow(stringResource(R.string.task_run_scheduled), taskRunTimestamp(run.scheduledFor)) }
        run.startedAt?.let { startedAt -> item { TaskRunDetailRow(stringResource(R.string.task_run_started), taskRunTimestamp(startedAt)) } }
        run.finishedAt?.let { finishedAt -> item { TaskRunDetailRow(stringResource(R.string.task_run_finished), taskRunTimestamp(finishedAt)) } }
        run.runId?.let { runId -> item { TaskRunDetailRow(stringResource(R.string.task_run_id), runId) } }
        run.error?.let { error ->
            item {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(stringResource(R.string.task_run_error_label), style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.error)
                    Text(error, color = MaterialTheme.colorScheme.error)
                }
            }
        }
        item {
            Button(
                onClick = onOpenConversation,
                enabled = run.threadId.isNotBlank(),
                modifier = Modifier.fillMaxWidth().testTag(UiTags.TaskRunOpenConversation),
            ) {
                Icon(Icons.Outlined.OpenInNew, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text(stringResource(R.string.open_task_run_conversation))
            }
        }
        item { Spacer(Modifier.height(24.dp)) }
    }
}

@Composable
private fun TaskRunDetailRow(label: String, value: String) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(label, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.bodyLarge)
    }
}

@Composable
private fun taskRunSummary(run: ScheduledTaskRunInfo): String =
    "${taskRunTriggerLabel(run.trigger)} · ${taskRunStatusLabel(run.status)}"

@Composable
private fun taskRunStatusLabel(status: String): String = when (status) {
    "queued" -> stringResource(R.string.task_run_status_queued)
    "running" -> stringResource(R.string.task_run_status_running)
    "success" -> stringResource(R.string.task_run_status_success)
    "failed" -> stringResource(R.string.task_run_status_failed)
    "skipped" -> stringResource(R.string.task_run_status_skipped)
    "interrupted" -> stringResource(R.string.task_run_status_interrupted)
    else -> stringResource(R.string.task_run_status_unknown, status)
}

@Composable
private fun taskRunTriggerLabel(trigger: String): String = when (trigger) {
    "scheduled" -> stringResource(R.string.task_run_trigger_scheduled)
    "manual" -> stringResource(R.string.task_run_trigger_manual)
    else -> stringResource(R.string.task_run_trigger_unknown, trigger)
}

private fun taskRunTimestamp(value: String): String = value.toDisplayTime()

private enum class TaskScheduleKind { Cron, Once }

@Composable
internal fun TaskEditorSheet(
    state: AppUiState,
    task: ScheduledTaskInfo?,
    onDismiss: () -> Unit,
    onSave: (String, String, TaskSchedule, String) -> Unit,
) {
    val context = LocalContext.current
    val initialTimezone = task?.timezone?.takeIf { it.isNotBlank() } ?: java.time.ZoneId.systemDefault().id
    val initialOnce = parseOnceSchedule(task?.scheduleLabel.orEmpty(), initialTimezone)
        ?: LocalDateTime.now().plusHours(1).withSecond(0).withNano(0)
    var title by remember(task?.id) { mutableStateOf(task?.title.orEmpty()) }
    var prompt by remember(task?.id) { mutableStateOf(task?.prompt.orEmpty()) }
    var cron by remember(task?.id) { mutableStateOf(task?.scheduleLabel ?: "0 9 * * *") }
    var timezone by remember(task?.id) { mutableStateOf(initialTimezone) }
    var scheduleKind by remember(task?.id) {
        mutableStateOf(if (task?.scheduleType == "once") TaskScheduleKind.Once else TaskScheduleKind.Cron)
    }
    var onceDate by remember(task?.id) { mutableStateOf(initialOnce.toLocalDate()) }
    var onceTime by remember(task?.id) { mutableStateOf(initialOnce.toLocalTime()) }
    var validationError by remember(task?.id) { mutableStateOf<String?>(null) }
    val onceSchedule = onceScheduleFor(onceDate, onceTime, timezone)
    val canSaveSchedule = when (scheduleKind) {
        TaskScheduleKind.Cron -> cron.isNotBlank()
        TaskScheduleKind.Once -> onceSchedule?.let(::isFutureOnceSchedule) == true
    }
    ModalBottomSheet(onDismissRequest = onDismiss) {
        LazyColumn(
            modifier = Modifier.fillMaxWidth(),
            contentPadding = PaddingValues(horizontal = 20.dp, vertical = 8.dp),
        ) {
            item { Text(stringResource(if (task == null) R.string.create_task else R.string.edit_task), style = MaterialTheme.typography.titleLarge) }
            item {
                Spacer(Modifier.height(16.dp))
                OutlinedTextField(
                    value = title,
                    onValueChange = { title = it },
                    label = { Text(stringResource(R.string.title)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().testTag(UiTags.TaskEditorTitle),
                )
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = prompt,
                    onValueChange = { prompt = it },
                    label = { Text(stringResource(R.string.prompt)) },
                    minLines = 3,
                    maxLines = 8,
                    modifier = Modifier.fillMaxWidth().testTag(UiTags.TaskEditorPrompt),
                )
                Spacer(Modifier.height(10.dp))
                if (task == null) {
                    SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth()) {
                        TaskScheduleKind.entries.forEachIndexed { index, kind ->
                            SegmentedButton(
                                selected = kind == scheduleKind,
                                onClick = { scheduleKind = kind; validationError = null },
                                shape = SegmentedButtonDefaults.itemShape(index, TaskScheduleKind.entries.size),
                                label = {
                                    Text(stringResource(if (kind == TaskScheduleKind.Cron) R.string.schedule_repeating else R.string.schedule_once))
                                },
                                modifier = Modifier.testTag(
                                    if (kind == TaskScheduleKind.Cron) UiTags.TaskEditorScheduleCron else UiTags.TaskEditorScheduleOnce,
                                ),
                            )
                        }
                    }
                    Spacer(Modifier.height(10.dp))
                } else {
                    Text(stringResource(R.string.schedule_type), style = MaterialTheme.typography.labelLarge)
                    Text(
                        stringResource(if (scheduleKind == TaskScheduleKind.Cron) R.string.schedule_repeating else R.string.schedule_once),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Spacer(Modifier.height(10.dp))
                }
                when (scheduleKind) {
                    TaskScheduleKind.Cron -> OutlinedTextField(
                        value = cron,
                        onValueChange = { cron = it; validationError = null },
                        label = { Text(stringResource(R.string.cron_expression)) },
                        supportingText = { Text(stringResource(R.string.cron_example)) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth().testTag(UiTags.TaskEditorCron),
                    )
                    TaskScheduleKind.Once -> {
                        Text(stringResource(R.string.run_at), style = MaterialTheme.typography.labelLarge)
                        Spacer(Modifier.height(6.dp))
                        OutlinedButton(
                            onClick = {
                                DatePickerDialog(
                                    context,
                                    { _, year, month, day ->
                                        onceDate = java.time.LocalDate.of(year, month + 1, day)
                                        validationError = null
                                    },
                                    onceDate.year,
                                    onceDate.monthValue - 1,
                                    onceDate.dayOfMonth,
                                ).show()
                            },
                            modifier = Modifier.fillMaxWidth().testTag(UiTags.TaskEditorOnceDate),
                        ) { Text(onceDate.format(DateTimeFormatter.ISO_LOCAL_DATE)) }
                        Spacer(Modifier.height(8.dp))
                        OutlinedButton(
                            onClick = {
                                TimePickerDialog(
                                    context,
                                    { _, hour, minute ->
                                        onceTime = java.time.LocalTime.of(hour, minute)
                                        validationError = null
                                    },
                                    onceTime.hour,
                                    onceTime.minute,
                                    true,
                                ).show()
                            },
                            modifier = Modifier.fillMaxWidth().testTag(UiTags.TaskEditorOnceTime),
                        ) { Text(onceTime.format(DateTimeFormatter.ofPattern("HH:mm"))) }
                    }
                }
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = timezone,
                    onValueChange = { timezone = it; validationError = null },
                    label = { Text(stringResource(R.string.timezone)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().testTag(UiTags.TaskEditorTimezone),
                )
                validationError?.let {
                    Text(it, color = MaterialTheme.colorScheme.error, style = MaterialTheme.typography.bodySmall)
                }
                Spacer(Modifier.height(18.dp))
                Button(
                    onClick = {
                        val schedule = when (scheduleKind) {
                            TaskScheduleKind.Cron -> TaskSchedule.Cron(cron.trim())
                            TaskScheduleKind.Once -> onceSchedule
                        }
                        validationError = when {
                            timezone.isBlank() || (scheduleKind == TaskScheduleKind.Once && onceSchedule == null) ->
                                context.getString(R.string.invalid_timezone)
                            scheduleKind == TaskScheduleKind.Once && schedule is TaskSchedule.Once && !isFutureOnceSchedule(schedule) ->
                                context.getString(R.string.once_must_be_future)
                            else -> null
                        }
                        if (schedule != null && validationError == null) onSave(title, prompt, schedule, timezone)
                    },
                    enabled = !state.workspaceMutationBusy && title.isNotBlank() && prompt.isNotBlank() && timezone.isNotBlank() && canSaveSchedule,
                    modifier = Modifier.fillMaxWidth().testTag(UiTags.TaskEditorSave),
                ) { Text(stringResource(R.string.save)) }
                Spacer(Modifier.height(28.dp))
            }
        }
    }
}
