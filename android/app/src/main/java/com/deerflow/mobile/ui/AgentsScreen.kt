@file:OptIn(
    androidx.compose.material3.ExperimentalMaterial3Api::class,
    androidx.compose.material3.ExperimentalMaterial3ExpressiveApi::class,
)

package com.deerflow.mobile.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.OpenInNew
import androidx.compose.material.icons.outlined.ChatBubbleOutline
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.History
import androidx.compose.material.icons.outlined.Menu
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Schedule
import androidx.compose.material.icons.outlined.SmartToy
import androidx.compose.material.icons.outlined.StarOutline
import androidx.compose.material3.Button
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.LoadingIndicator
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.deerflow.mobile.R
import com.deerflow.mobile.data.AgentInfo
import com.deerflow.mobile.data.AgentRunInfo

@Composable
fun AgentsScreen(state: AppUiState, viewModel: AppViewModel, onBack: () -> Unit, contentPadding: PaddingValues) {
    var detailName by rememberSaveable { mutableStateOf<String?>(null) }
    var editing by remember { mutableStateOf<AgentInfo?>(null) }
    var creating by remember { mutableStateOf(false) }
    var historyAgent by remember { mutableStateOf<AgentInfo?>(null) }
    val leadAgent = AgentInfo(
        "lead_agent",
        stringResource(R.string.lead_agent_description),
        state.composer.options.modelName,
        emptyList(),
    )
    val detailAgent = when (detailName) {
        "lead_agent" -> leadAgent
        null -> null
        else -> state.capabilities.agents.firstOrNull { it.name == detailName }
    }

    if (detailAgent == null) {
        AgentListScreen(
            state = state,
            leadAgent = leadAgent,
            onBack = onBack,
            onCreate = { creating = true },
            onRefresh = viewModel::refreshCapabilities,
            onOpen = { detailName = it.name },
            onSetDefault = viewModel::setDefaultAgent,
            onChat = viewModel::startChatWithAgent,
            onEdit = { editing = it },
            contentPadding = contentPadding,
        )
    } else {
        AgentDetailScreen(
            agent = detailAgent,
            isDefault = state.defaultAgentId == detailAgent.name,
            mutationBusy = state.workspaceMutationBusy,
            onBack = { detailName = null },
            onSetDefault = { viewModel.setDefaultAgent(detailAgent.name) },
            onChat = { viewModel.startChatWithAgent(detailAgent.name) },
            onHistory = {
                historyAgent = detailAgent
                viewModel.loadAgentRuns(detailAgent)
            },
            onEdit = detailAgent.takeUnless { it.name == "lead_agent" }?.let { agent ->
                { editing = agent }
            },
            contentPadding = contentPadding,
        )
    }
    if (creating || editing != null) {
        AgentEditorSheet(
            state = state,
            agent = editing,
            onDismiss = { creating = false; editing = null },
            onSave = { name, description, model ->
                viewModel.saveAgent(editing, name, description, model) {
                    creating = false
                    editing = null
                }
            },
            onDelete = editing?.let { agent ->
                {
                    viewModel.deleteAgent(agent)
                    if (detailName == agent.name) detailName = null
                    editing = null
                }
            },
        )
    }
    historyAgent?.let { agent ->
        AgentRunHistorySheet(
            agent = agent,
            runs = if (state.agentRunsAgentId == agent.name) state.agentRuns else emptyList(),
            loading = state.loadingAgentRuns && state.agentRunsAgentId == agent.name,
            error = state.agentRunsError.takeIf { state.agentRunsAgentId == agent.name },
            onDismiss = { historyAgent = null },
            onRefresh = { viewModel.loadAgentRuns(agent) },
            onOpenConversation = { run ->
                historyAgent = null
                viewModel.openAgentRunConversation(agent, run)
            },
        )
    }
}

@Composable
private fun AgentListScreen(
    state: AppUiState,
    leadAgent: AgentInfo,
    onBack: () -> Unit,
    onCreate: () -> Unit,
    onRefresh: () -> Unit,
    onOpen: (AgentInfo) -> Unit,
    onSetDefault: (String) -> Unit,
    onChat: (String) -> Unit,
    onEdit: (AgentInfo) -> Unit,
    contentPadding: PaddingValues,
) {
    Column(Modifier.fillMaxSize().padding(contentPadding)) {
        TopAppBar(
            navigationIcon = {
                IconButton(onClick = onBack, modifier = Modifier.size(48.dp)) {
                    Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = stringResource(R.string.back))
                }
            },
            title = { Text(stringResource(R.string.agents_title)) },
            actions = {
                if (state.capabilities.agentsEnabled) {
                    IconButton(onClick = onCreate, enabled = !state.workspaceMutationBusy, modifier = Modifier.size(48.dp)) {
                        Icon(Icons.Filled.Add, contentDescription = stringResource(R.string.create_agent))
                    }
                }
                IconButton(onClick = onRefresh, enabled = !state.loadingCapabilities, modifier = Modifier.size(48.dp)) {
                    Icon(Icons.Outlined.Refresh, contentDescription = stringResource(R.string.refresh))
                }
            },
            colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
        )
        when {
            state.loadingCapabilities && state.capabilities.agents.isEmpty() -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                LoadingIndicator(Modifier.size(32.dp))
            }
            else -> LazyColumn(
                modifier = Modifier.fillMaxSize(),
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 12.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp),
            ) {
                item {
                    AgentRow(
                        leadAgent,
                        isDefault = state.defaultAgentId == "lead_agent",
                        onOpen = { onOpen(leadAgent) },
                        onSetDefault = { onSetDefault("lead_agent") },
                        onChat = { onChat("lead_agent") },
                        onEdit = null,
                    )
                }
                items(state.capabilities.agents.customAgentsOnly(), key = { it.name }) { agent ->
                    AgentRow(
                        agent = agent,
                        isDefault = state.defaultAgentId == agent.name,
                        onOpen = { onOpen(agent) },
                        onSetDefault = { onSetDefault(agent.name) },
                        onChat = { onChat(agent.name) },
                        onEdit = { onEdit(agent) },
                    )
                }
                if (!state.capabilities.agentsEnabled) {
                    item {
                        Text(
                            stringResource(R.string.custom_agents_disabled),
                            style = MaterialTheme.typography.bodyMedium,
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(16.dp),
                        )
                    }
                }
            }
        }
    }
}

internal fun List<AgentInfo>.customAgentsOnly(): List<AgentInfo> =
    filterNot { it.name == "lead_agent" }

@Composable
internal fun AgentRow(
    agent: AgentInfo,
    isDefault: Boolean,
    onOpen: () -> Unit,
    onSetDefault: () -> Unit,
    onChat: () -> Unit,
    onEdit: (() -> Unit)?,
) {
    ListItem(
        headlineContent = { Text(agent.name) },
        supportingContent = {
            Column {
                if (agent.description.isNotBlank()) Text(agent.description, maxLines = 3, overflow = TextOverflow.Ellipsis)
                agent.model?.let { Text(it, color = MaterialTheme.colorScheme.primary) }
            }
        },
        leadingContent = { Icon(Icons.Outlined.SmartToy, contentDescription = null) },
        trailingContent = {
            Row {
                if (isDefault) {
                    Box(
                        modifier = Modifier.size(48.dp).testTag(UiTags.AgentDefaultPrefix + agent.name),
                        contentAlignment = Alignment.Center,
                    ) {
                        Icon(
                            Icons.Filled.Star,
                            contentDescription = stringResource(R.string.default_agent),
                            tint = MaterialTheme.colorScheme.primary,
                        )
                    }
                } else {
                    IconButton(
                        onClick = onSetDefault,
                        modifier = Modifier.size(48.dp).testTag(UiTags.AgentDefaultPrefix + agent.name),
                    ) {
                        Icon(
                            Icons.Outlined.StarOutline,
                            contentDescription = stringResource(R.string.set_default_agent),
                        )
                    }
                }
                IconButton(onClick = onChat, modifier = Modifier.size(48.dp)) {
                    Icon(Icons.Outlined.ChatBubbleOutline, contentDescription = stringResource(R.string.chat))
                }
                if (onEdit != null) {
                    IconButton(onClick = onEdit, modifier = Modifier.size(48.dp)) {
                        Icon(Icons.Outlined.Edit, contentDescription = stringResource(R.string.edit))
                    }
                }
            }
        },
        modifier = Modifier
            .fillMaxWidth()
            .clickable(onClick = onOpen)
            .testTag(UiTags.AgentRowPrefix + agent.name),
    )
}

@Composable
internal fun AgentDetailScreen(
    agent: AgentInfo,
    isDefault: Boolean,
    mutationBusy: Boolean,
    onBack: () -> Unit,
    onSetDefault: () -> Unit,
    onChat: () -> Unit,
    onHistory: () -> Unit = {},
    onEdit: (() -> Unit)?,
    contentPadding: PaddingValues = PaddingValues(),
) {
    Column(
        Modifier
            .fillMaxSize()
            .padding(contentPadding)
            .testTag(UiTags.AgentDetailScreen),
    ) {
        TopAppBar(
            navigationIcon = {
                IconButton(onClick = onBack, modifier = Modifier.size(48.dp)) {
                    Icon(
                        Icons.AutoMirrored.Outlined.ArrowBack,
                        contentDescription = stringResource(R.string.back),
                    )
                }
            },
            title = { Text(agent.name, maxLines = 1, overflow = TextOverflow.Ellipsis) },
            actions = {
                if (onEdit != null) {
                    IconButton(
                        onClick = onEdit,
                        enabled = !mutationBusy,
                        modifier = Modifier.size(48.dp).testTag(UiTags.AgentDetailEdit),
                    ) {
                        Icon(Icons.Outlined.Edit, contentDescription = stringResource(R.string.edit))
                    }
                }
            },
            colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
        )
        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(horizontal = 24.dp, vertical = 20.dp),
            verticalArrangement = Arrangement.spacedBy(24.dp),
        ) {
            item {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Icon(
                        Icons.Outlined.SmartToy,
                        contentDescription = null,
                        tint = MaterialTheme.colorScheme.primary,
                        modifier = Modifier.size(56.dp),
                    )
                    Column(Modifier.padding(start = 18.dp)) {
                        Text(agent.name, style = MaterialTheme.typography.headlineSmall)
                        if (isDefault) {
                            Row(
                                modifier = Modifier.padding(top = 6.dp).testTag(UiTags.AgentDetailDefault),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Icon(
                                    Icons.Filled.Star,
                                    contentDescription = null,
                                    tint = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.size(18.dp),
                                )
                                Text(
                                    stringResource(R.string.default_agent),
                                    style = MaterialTheme.typography.labelLarge,
                                    color = MaterialTheme.colorScheme.primary,
                                    modifier = Modifier.padding(start = 6.dp),
                                )
                            }
                        }
                    }
                }
            }
            item { HorizontalDivider() }
            item {
                AgentDetailSection(
                    stringResource(R.string.description),
                    agent.description.ifBlank { stringResource(R.string.no_agent_description) },
                )
            }
            item {
                AgentDetailSection(
                    stringResource(R.string.model),
                    agent.model ?: stringResource(R.string.server_default),
                )
            }
            if (agent.skills.isNotEmpty()) {
                item {
                    Text(stringResource(R.string.skills), style = MaterialTheme.typography.titleMedium)
                    LazyRow(
                        modifier = Modifier.fillMaxWidth().padding(top = 8.dp),
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        items(agent.skills, key = { it }) { skill ->
                            Surface(
                                color = MaterialTheme.colorScheme.secondaryContainer,
                                contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
                                shape = MaterialTheme.shapes.small,
                            ) {
                                Text(
                                    skill,
                                    style = MaterialTheme.typography.labelLarge,
                                    modifier = Modifier.padding(horizontal = 14.dp, vertical = 10.dp),
                                )
                            }
                        }
                    }
                }
            }
            if (agent.soul.isNotBlank()) {
                item {
                    AgentDetailSection(stringResource(R.string.agent_instructions), agent.soul)
                }
            }
            item {
                Button(
                    onClick = onChat,
                    enabled = !mutationBusy,
                    modifier = Modifier.fillMaxWidth().height(48.dp).testTag(UiTags.AgentDetailChat),
                ) {
                    Icon(Icons.Outlined.ChatBubbleOutline, contentDescription = null)
                    Text(stringResource(R.string.chat), modifier = Modifier.padding(start = 8.dp))
                }
                Spacer(Modifier.height(10.dp))
                OutlinedButton(
                    onClick = onHistory,
                    enabled = !mutationBusy,
                    modifier = Modifier.fillMaxWidth().height(48.dp).testTag(UiTags.AgentDetailHistory),
                ) {
                    Icon(Icons.Outlined.History, contentDescription = null)
                    Text(stringResource(R.string.execution_history), modifier = Modifier.padding(start = 8.dp))
                }
                if (!isDefault) {
                    Spacer(Modifier.height(10.dp))
                    FilledTonalButton(
                        onClick = onSetDefault,
                        enabled = !mutationBusy,
                        modifier = Modifier.fillMaxWidth().height(48.dp).testTag(UiTags.AgentDetailSetDefault),
                    ) {
                        Icon(Icons.Outlined.StarOutline, contentDescription = null)
                        Text(stringResource(R.string.set_default_agent), modifier = Modifier.padding(start = 8.dp))
                    }
                }
                Spacer(Modifier.height(24.dp))
            }
        }
    }
}

@Composable
internal fun AgentRunHistorySheet(
    agent: AgentInfo,
    runs: List<AgentRunInfo>,
    loading: Boolean,
    error: String?,
    onDismiss: () -> Unit,
    onRefresh: () -> Unit,
    onOpenConversation: (AgentRunInfo) -> Unit,
) {
    var selectedRun by remember(agent.name) { mutableStateOf<AgentRunInfo?>(null) }
    ModalBottomSheet(
        onDismissRequest = onDismiss,
        modifier = Modifier.testTag(UiTags.AgentRunHistorySheet),
    ) {
        when (val detail = selectedRun) {
            null -> AgentRunList(
                agent = agent,
                runs = runs,
                loading = loading,
                error = error,
                onRefresh = onRefresh,
                onSelect = { selectedRun = it },
            )
            else -> AgentRunDetail(
                run = detail,
                onBack = { selectedRun = null },
                onOpenConversation = { onOpenConversation(detail) },
            )
        }
    }
}

@Composable
private fun AgentRunList(
    agent: AgentInfo,
    runs: List<AgentRunInfo>,
    loading: Boolean,
    error: String?,
    onRefresh: () -> Unit,
    onSelect: (AgentRunInfo) -> Unit,
) {
    Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp)) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(stringResource(R.string.execution_history), style = MaterialTheme.typography.titleLarge)
                Text(agent.name, style = MaterialTheme.typography.bodyMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            IconButton(onClick = onRefresh, enabled = !loading, modifier = Modifier.size(48.dp)) {
                Icon(Icons.Outlined.Refresh, contentDescription = stringResource(R.string.refresh))
            }
        }
        when {
            loading -> Box(Modifier.fillMaxWidth().height(180.dp), contentAlignment = Alignment.Center) {
                LoadingIndicator(Modifier.size(32.dp))
            }
            error != null -> Column(
                modifier = Modifier.fillMaxWidth().heightIn(min = 180.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
                verticalArrangement = Arrangement.Center,
            ) {
                Text(
                    error,
                    color = MaterialTheme.colorScheme.error,
                    style = MaterialTheme.typography.bodyMedium,
                )
                Spacer(Modifier.height(12.dp))
                OutlinedButton(onClick = onRefresh) {
                    Icon(Icons.Outlined.Refresh, contentDescription = null)
                    Spacer(Modifier.width(8.dp))
                    Text(stringResource(R.string.retry))
                }
            }
            runs.isEmpty() -> Box(Modifier.fillMaxWidth().height(180.dp), contentAlignment = Alignment.Center) {
                Text(stringResource(R.string.no_agent_runs), color = MaterialTheme.colorScheme.onSurfaceVariant)
            }
            else -> LazyColumn(
                modifier = Modifier.fillMaxWidth().heightIn(max = 520.dp),
                contentPadding = PaddingValues(vertical = 8.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp),
            ) {
                items(runs, key = { it.runId }) { run ->
                    ListItem(
                        headlineContent = {
                            Text(
                                run.threadTitle?.takeIf(String::isNotBlank) ?: stringResource(R.string.untitled_conversation),
                                maxLines = 1,
                                overflow = TextOverflow.Ellipsis,
                            )
                        },
                        supportingContent = {
                            Column {
                                Text(agentRunStatusLabel(run.status))
                                run.createdAt?.let { Text(agentRunTimestamp(it), maxLines = 1) }
                            }
                        },
                        leadingContent = { AgentRunStatusIcon(run.status) },
                        trailingContent = run.modelName?.takeIf(String::isNotBlank)?.let { model ->
                            { Text(model, style = MaterialTheme.typography.labelMedium, maxLines = 1) }
                        },
                        modifier = Modifier.fillMaxWidth()
                            .clickable { onSelect(run) }
                            .testTag(UiTags.AgentRunPrefix + run.runId),
                    )
                }
            }
        }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun AgentRunDetail(
    run: AgentRunInfo,
    onBack: () -> Unit,
    onOpenConversation: () -> Unit,
) {
    LazyColumn(
        modifier = Modifier.fillMaxWidth().testTag(UiTags.AgentRunDetail),
        contentPadding = PaddingValues(horizontal = 20.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        item {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                IconButton(onClick = onBack, modifier = Modifier.size(48.dp)) {
                    Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = stringResource(R.string.back))
                }
                Text(stringResource(R.string.execution_detail), style = MaterialTheme.typography.titleLarge)
            }
        }
        run.threadTitle?.takeIf(String::isNotBlank)?.let { title ->
            item { AgentRunDetailRow(stringResource(R.string.conversation), title) }
        }
        item { AgentRunDetailRow(stringResource(R.string.task_run_status_label), agentRunStatusLabel(run.status)) }
        run.modelName?.takeIf(String::isNotBlank)?.let { model ->
            item { AgentRunDetailRow(stringResource(R.string.model), model) }
        }
        run.createdAt?.let { created ->
            item { AgentRunDetailRow(stringResource(R.string.agent_run_created), agentRunTimestamp(created)) }
        }
        run.updatedAt?.let { updated ->
            item { AgentRunDetailRow(stringResource(R.string.agent_run_updated), agentRunTimestamp(updated)) }
        }
        run.durationSeconds?.let { duration ->
            item { AgentRunDetailRow(stringResource(R.string.agent_run_duration), stringResource(R.string.agent_run_duration_value, duration)) }
        }
        item { AgentRunDetailRow(stringResource(R.string.agent_run_messages), run.messageCount.toString()) }
        item { AgentRunDetailRow(stringResource(R.string.agent_run_tokens), run.totalTokens.toString()) }
        run.cost?.let { cost ->
            item { AgentRunDetailRow(stringResource(R.string.agent_run_cost), stringResource(R.string.agent_run_cost_value, cost)) }
        }
        item { AgentRunDetailRow(stringResource(R.string.task_run_id), run.runId) }
        run.error?.takeIf(String::isNotBlank)?.let { message ->
            item {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    Text(stringResource(R.string.task_run_error_label), style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.error)
                    Text(message, color = MaterialTheme.colorScheme.error)
                }
            }
        }
        item {
            Button(
                onClick = onOpenConversation,
                enabled = run.threadId.isNotBlank(),
                modifier = Modifier.fillMaxWidth().testTag(UiTags.AgentRunOpenConversation),
            ) {
                Icon(Icons.AutoMirrored.Outlined.OpenInNew, contentDescription = null)
                Spacer(Modifier.width(8.dp))
                Text(stringResource(R.string.open_agent_run_conversation))
            }
        }
        item { Spacer(Modifier.height(24.dp)) }
    }
}

@Composable
private fun AgentRunDetailRow(label: String, value: String) {
    Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
        Text(label, style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, style = MaterialTheme.typography.bodyLarge)
    }
}

@Composable
private fun AgentRunStatusIcon(status: String) {
    val (icon, tint) = when (status.lowercase()) {
        "pending", "queued", "running" -> Icons.Outlined.Schedule to MaterialTheme.colorScheme.primary
        "success", "completed" -> Icons.Outlined.CheckCircle to MaterialTheme.colorScheme.tertiary
        "error", "failed", "timeout", "interrupted", "cancelled", "canceled" ->
            Icons.Outlined.ErrorOutline to MaterialTheme.colorScheme.error
        else -> Icons.Outlined.History to MaterialTheme.colorScheme.onSurfaceVariant
    }
    Icon(icon, contentDescription = stringResource(R.string.status_description, agentRunStatusLabel(status)), tint = tint)
}

@Composable
private fun agentRunStatusLabel(status: String): String = when (status.lowercase()) {
    "pending", "queued" -> stringResource(R.string.task_run_status_queued)
    "running" -> stringResource(R.string.task_run_status_running)
    "success", "completed" -> stringResource(R.string.task_run_status_success)
    "error", "failed", "timeout" -> stringResource(R.string.task_run_status_failed)
    "interrupted", "cancelled", "canceled" -> stringResource(R.string.task_run_status_interrupted)
    else -> stringResource(R.string.task_run_status_unknown, status)
}

private fun agentRunTimestamp(value: String): String = value.toDisplayTime()

@Composable
private fun AgentDetailSection(label: String, value: String) {
    Column {
        Text(label, style = MaterialTheme.typography.titleMedium)
        Text(
            value,
            style = MaterialTheme.typography.bodyLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(top = 8.dp),
        )
    }
}

@Composable
internal fun AgentEditorSheet(
    state: AppUiState,
    agent: AgentInfo?,
    onDismiss: () -> Unit,
    onSave: (String, String, String?) -> Unit,
    onDelete: (() -> Unit)?,
) {
    var name by remember(agent?.name) { mutableStateOf(agent?.name.orEmpty()) }
    var description by remember(agent?.name) { mutableStateOf(agent?.description.orEmpty()) }
    var model by remember(agent?.name) { mutableStateOf(agent?.model) }
    ModalBottomSheet(onDismissRequest = onDismiss) {
        LazyColumn(
            modifier = Modifier.fillMaxWidth(),
            contentPadding = PaddingValues(horizontal = 20.dp, vertical = 8.dp),
        ) {
            item { Text(stringResource(if (agent == null) R.string.create_agent else R.string.edit_agent), style = MaterialTheme.typography.titleLarge) }
            item {
                Spacer(Modifier.height(16.dp))
                OutlinedTextField(
                    value = name,
                    onValueChange = { name = it },
                    label = { Text(stringResource(R.string.agent_name)) },
                    enabled = agent == null,
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth().testTag(UiTags.AgentEditorName),
                )
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = description,
                    onValueChange = { description = it },
                    label = { Text(stringResource(R.string.description)) },
                    minLines = 2,
                    maxLines = 5,
                    modifier = Modifier.fillMaxWidth().testTag(UiTags.AgentEditorDescription),
                )
                Spacer(Modifier.height(16.dp))
                Text(stringResource(R.string.model), style = MaterialTheme.typography.titleMedium)
                LazyColumn(Modifier.fillMaxWidth().height(160.dp)) {
                    item {
                        FilterChip(
                            selected = model == null,
                            onClick = { model = null },
                            label = { Text(stringResource(R.string.server_default)) },
                            modifier = Modifier.testTag(UiTags.AgentEditorModelPrefix + "server-default"),
                        )
                    }
                    items(state.capabilities.models, key = { it.name }) { item ->
                        FilterChip(
                            selected = model == item.name,
                            onClick = { model = item.name },
                            label = { Text(item.displayName) },
                            modifier = Modifier.testTag(UiTags.AgentEditorModelPrefix + item.name),
                        )
                    }
                }
                Spacer(Modifier.height(16.dp))
                Button(
                    onClick = { onSave(name, description, model) },
                    enabled = !state.workspaceMutationBusy && name.isNotBlank(),
                    modifier = Modifier.fillMaxWidth().testTag(UiTags.AgentEditorSave),
                ) { Text(stringResource(R.string.save)) }
                if (onDelete != null) {
                    Spacer(Modifier.height(8.dp))
                    OutlinedButton(
                        onClick = onDelete,
                        enabled = !state.workspaceMutationBusy,
                        modifier = Modifier.fillMaxWidth().testTag(UiTags.AgentEditorDelete),
                    ) {
                        Icon(Icons.Outlined.DeleteOutline, contentDescription = null)
                        Text(stringResource(R.string.delete), modifier = Modifier.padding(start = 8.dp), color = MaterialTheme.colorScheme.error)
                    }
                }
                Spacer(Modifier.height(28.dp))
            }
        }
    }
}
