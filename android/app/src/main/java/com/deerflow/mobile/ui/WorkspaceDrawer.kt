@file:OptIn(androidx.compose.foundation.ExperimentalFoundationApi::class, androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.deerflow.mobile.ui

import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.focusable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.staggeredgrid.LazyVerticalStaggeredGrid
import androidx.compose.foundation.lazy.staggeredgrid.StaggeredGridCells
import androidx.compose.foundation.lazy.staggeredgrid.items as staggeredItems
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Psychology
import androidx.compose.material.icons.outlined.PersonOutline
import androidx.compose.material.icons.outlined.PushPin
import androidx.compose.material.icons.outlined.Schedule
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.SmartToy
import androidx.compose.material.icons.outlined.Tune
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Checkbox
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.ListItemDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.TabRow
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.platform.testTag
import com.deerflow.mobile.R
import com.deerflow.mobile.data.ChannelConnectResult
import com.deerflow.mobile.data.ChannelProviderInfo
import com.deerflow.mobile.data.ChannelProviders
import com.deerflow.mobile.data.McpConfig
import com.deerflow.mobile.data.SkillInfo
import com.deerflow.mobile.data.ThreadSummary
import org.json.JSONObject
import kotlinx.coroutines.delay

private enum class SkillCatalogTab(val labelRes: Int) {
    Public(R.string.public_skills),
    Custom(R.string.custom_skills),
    Tools(R.string.tools),
}

private val SkillInfo.isCustom: Boolean
    get() = category.contains("custom", ignoreCase = true) || category.contains("user", ignoreCase = true)

@Composable
fun WorkspaceDrawer(
    state: AppUiState,
    onNewChat: () -> Unit,
    onOpenThread: (ThreadSummary) -> Unit,
    onRenameThread: (ThreadSummary, String) -> Unit,
    onDeleteThread: (ThreadSummary) -> Unit,
    onPinThread: (ThreadSummary) -> Unit,
    onDestination: (DrawerDestination) -> Unit,
    onOpenProfile: () -> Unit = {},
    drawerOpen: Boolean = false,
) {
    var query by remember { mutableStateOf("") }
    var renameTarget by remember { mutableStateOf<ThreadSummary?>(null) }
    var deleteTarget by remember { mutableStateOf<ThreadSummary?>(null) }
    val headerFocus = remember { FocusRequester() }
    val focusManager = LocalFocusManager.current
    val filtered = state.threads.filter { query.isBlank() || it.title.contains(query, ignoreCase = true) }

    LaunchedEffect(drawerOpen) {
        if (drawerOpen) {
            focusManager.clearFocus(force = true)
            // Move focus away from a previously focused composer before the drawer is shown.
            delay(80)
            headerFocus.requestFocus()
        }
    }

    Box(Modifier.fillMaxHeight().fillMaxWidth().testTag(UiTags.WorkspaceDrawer)) {
        Column(Modifier.fillMaxHeight().fillMaxWidth()) {
            Row(
                modifier = Modifier
                    .fillMaxWidth()
                    .padding(start = 16.dp, end = 16.dp, top = 18.dp, bottom = 14.dp)
                    .focusRequester(headerFocus)
                    .focusable(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Surface(
                    onClick = onOpenProfile,
                    modifier = Modifier.size(36.dp),
                    shape = CircleShape,
                    color = MaterialTheme.colorScheme.secondaryContainer,
                    contentColor = MaterialTheme.colorScheme.onSecondaryContainer,
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Icon(Icons.Outlined.PersonOutline, contentDescription = stringResource(R.string.tab_profile))
                    }
                }
                Column(Modifier.weight(1f).padding(horizontal = 10.dp)) {
                    Text("DeerFlow", style = MaterialTheme.typography.titleMedium)
                    Text(
                        state.user?.email.orEmpty(),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
            DrawerDestinationRow(Icons.Outlined.SmartToy, stringResource(R.string.tab_agents)) { onDestination(DrawerDestination.Agents) }
            DrawerDestinationRow(Icons.Outlined.Schedule, stringResource(R.string.tab_tasks)) { onDestination(DrawerDestination.Tasks) }
            if (state.capabilities.skills.isNotEmpty()) {
                DrawerDestinationRow(Icons.Outlined.Tune, stringResource(R.string.skills)) { onDestination(DrawerDestination.Skills) }
            }
            DrawerDestinationRow(Icons.Outlined.Psychology, stringResource(R.string.tab_memory)) { onDestination(DrawerDestination.Memory) }
            HorizontalDivider(Modifier.padding(vertical = 10.dp))
            LazyColumn(
                modifier = Modifier.weight(1f),
                contentPadding = PaddingValues(bottom = 88.dp),
            ) {
                item {
                    Text(
                        stringResource(R.string.recent_conversations),
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 4.dp),
                    )
                    OutlinedTextField(
                        value = query,
                        onValueChange = { query = it },
                        leadingIcon = { Icon(Icons.Outlined.Search, contentDescription = null) },
                        placeholder = { Text(stringResource(R.string.search_conversations)) },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp).testTag(UiTags.ConversationSearch),
                    )
                    if (state.offline) {
                        Box(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) { OfflineBanner() }
                    }
                }
                items(filtered, key = { it.id }) { thread ->
                    ThreadDrawerRow(
                        thread = thread,
                        selected = state.selectedThread?.id == thread.id,
                        onClick = { onOpenThread(thread) },
                        onRename = { renameTarget = thread },
                        onDelete = { deleteTarget = thread },
                        onPin = { onPinThread(thread) },
                    )
                }
                if (filtered.isEmpty()) {
                    item {
                        Text(
                            stringResource(if (query.isBlank()) R.string.no_conversations else R.string.no_search_results),
                            color = MaterialTheme.colorScheme.onSurfaceVariant,
                            modifier = Modifier.padding(16.dp),
                        )
                    }
                }
            }
        }
        FloatingActionButton(
            onClick = onNewChat,
            containerColor = MaterialTheme.colorScheme.primaryContainer,
            modifier = Modifier.align(Alignment.BottomEnd).padding(16.dp).testTag(UiTags.NewChatButton),
        ) {
            Icon(Icons.Filled.Add, contentDescription = stringResource(R.string.new_chat))
        }
    }

    renameTarget?.let { target ->
        RenameThreadDialog(
            thread = target,
            onDismiss = { renameTarget = null },
            onConfirm = {
                onRenameThread(target, it)
                renameTarget = null
            },
        )
    }
    deleteTarget?.let { target ->
        AlertDialog(
            onDismissRequest = { deleteTarget = null },
            title = { Text(stringResource(R.string.delete_conversation_title)) },
            text = { Text(stringResource(R.string.delete_conversation_body)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        onDeleteThread(target)
                        deleteTarget = null
                    },
                    modifier = Modifier.testTag(UiTags.ThreadDeleteConfirm),
                ) { Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { deleteTarget = null }) { Text(stringResource(R.string.cancel)) } },
        )
    }
}

@Composable
private fun DrawerDestinationRow(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, onClick: () -> Unit) {
    ListItem(
        headlineContent = { Text(label) },
        leadingContent = { Icon(icon, contentDescription = null) },
        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
        modifier = Modifier.fillMaxWidth().combinedClickable(onClick = onClick, onLongClick = {}),
    )
}

@Composable
private fun ThreadDrawerRow(
    thread: ThreadSummary,
    selected: Boolean,
    onClick: () -> Unit,
    onRename: () -> Unit,
    onDelete: () -> Unit,
    onPin: () -> Unit,
) {
    var menu by remember { mutableStateOf(false) }
    Box {
        ListItem(
            headlineContent = {
                Text(thread.title, maxLines = 2, overflow = TextOverflow.Ellipsis, fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal)
            },
            supportingContent = {
                Text(thread.updatedAt.toDisplayTime(), maxLines = 1, overflow = TextOverflow.Ellipsis)
            },
            leadingContent = {
                StatusDot(
                    status = thread.status,
                    description = stringResource(R.string.status_description, thread.status),
                )
            },
            trailingContent = {
                if (thread.isPinned) Icon(Icons.Outlined.PushPin, contentDescription = stringResource(R.string.pinned), modifier = Modifier.size(18.dp))
            },
            colors = ListItemDefaults.colors(containerColor = if (selected) MaterialTheme.colorScheme.secondaryContainer else Color.Transparent),
            modifier = Modifier
                .fillMaxWidth()
                .testTag(UiTags.ThreadRowPrefix + thread.id)
                .combinedClickable(onClick = onClick, onLongClick = { menu = true }),
        )
        DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
            DropdownMenuItem(
                text = { Text(stringResource(if (thread.isPinned) R.string.unpin else R.string.pin)) },
                leadingIcon = { Icon(Icons.Outlined.PushPin, contentDescription = null) },
                onClick = { menu = false; onPin() },
                modifier = Modifier.testTag(UiTags.ThreadPinAction),
            )
            DropdownMenuItem(
                text = { Text(stringResource(R.string.rename)) },
                leadingIcon = { Icon(Icons.Outlined.Edit, contentDescription = null) },
                onClick = { menu = false; onRename() },
                modifier = Modifier.testTag(UiTags.ThreadRenameAction),
            )
            DropdownMenuItem(
                text = { Text(stringResource(R.string.delete)) },
                leadingIcon = { Icon(Icons.Outlined.DeleteOutline, contentDescription = null) },
                onClick = { menu = false; onDelete() },
                modifier = Modifier.testTag(UiTags.ThreadDeleteAction),
            )
        }
    }
}

@Composable
private fun RenameThreadDialog(thread: ThreadSummary, onDismiss: () -> Unit, onConfirm: (String) -> Unit) {
    var value by remember(thread.id) { mutableStateOf(thread.title) }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.rename_conversation)) },
        text = {
            OutlinedTextField(
                value = value,
                onValueChange = { value = it },
                singleLine = true,
                label = { Text(stringResource(R.string.title)) },
                modifier = Modifier.testTag(UiTags.ThreadRenameTitle),
            )
        },
        confirmButton = {
            TextButton(
                onClick = { onConfirm(value) },
                enabled = value.isNotBlank(),
                modifier = Modifier.testTag(UiTags.ThreadRenameSave),
            ) { Text(stringResource(R.string.save)) }
        },
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

@Composable
fun SkillsSheet(
    state: AppUiState,
    viewModel: AppViewModel,
    onDismiss: () -> Unit,
    onSkillSelected: ((String) -> Unit)? = null,
) {
    var detail by remember { mutableStateOf<SkillInfo?>(null) }
    var tab by remember { mutableStateOf(SkillCatalogTab.Public) }
    var editingConfiguration by remember { mutableStateOf(false) }
    ModalBottomSheet(onDismissRequest = onDismiss, modifier = Modifier.testTag(UiTags.SkillsSheet)) {
        val selectSkill: (String) -> Unit = { skillName ->
            if (onSkillSelected != null) onSkillSelected(skillName)
            else viewModel.toggleSkill(skillName)
        }
        val selectedSkills = state.composer.options.enabledSkills
        val selectedDetail = detail?.let { detailSkill ->
            state.capabilities.skills.firstOrNull { it.name == detailSkill.name } ?: detailSkill
        }
        val canManageSkillStates = state.user?.role == "admin"
        if (editingConfiguration) {
            McpConfigEditorContent(
                config = state.mcpConfig,
                mutationBusy = state.workspaceMutationBusy,
                onBack = { editingConfiguration = false },
                onSave = { rawJson -> viewModel.updateMcpConfiguration(rawJson) { editingConfiguration = false } },
            )
        } else if (selectedDetail == null) {
            Text(
                stringResource(R.string.skills),
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp),
            )
            TabRow(
                selectedTabIndex = tab.ordinal,
                containerColor = Color.Transparent,
                contentColor = MaterialTheme.colorScheme.onSurface,
            ) {
                SkillCatalogTab.entries.forEach { item ->
                    androidx.compose.material3.Tab(
                        selected = tab == item,
                        onClick = { tab = item },
                        text = { Text(stringResource(item.labelRes)) },
                    )
                }
            }
            when (tab) {
                SkillCatalogTab.Public, SkillCatalogTab.Custom -> {
                    val custom = tab == SkillCatalogTab.Custom
                    SkillsSheetContent(
                        skills = state.capabilities.skills.filter { skill -> skill.isCustom == custom },
                        selectedSkills = selectedSkills,
                        onSkillSelected = selectSkill,
                        onSkillDetail = { detail = it },
                        showDisabledSkills = canManageSkillStates,
                        canManageSkillStates = canManageSkillStates,
                        mutationBusy = state.workspaceMutationBusy,
                        onSkillEnabledChanged = viewModel::setSkillEnabled,
                        titleRes = tab.labelRes,
                    )
                }
                SkillCatalogTab.Tools -> McpSheetContent(
                    config = state.mcpConfig,
                    loading = state.loadingMcpConfig,
                    mutationBusy = state.workspaceMutationBusy,
                    canManageServers = canManageSkillStates,
                    onServerEnabledChanged = viewModel::setMcpServerEnabled,
                    onEditConfiguration = { editingConfiguration = true },
                )
            }
        } else {
            SkillDetailContent(
                skill = selectedDetail,
                selected = selectedDetail.name in selectedSkills,
                onBack = { detail = null },
                onSkillSelected = selectSkill,
                canManageSkillStates = canManageSkillStates,
                mutationBusy = state.workspaceMutationBusy,
                onSkillEnabledChanged = viewModel::setSkillEnabled,
            )
        }
    }
}

@Composable
fun McpSheet(
    state: AppUiState,
    viewModel: AppViewModel,
    onDismiss: () -> Unit,
) {
    var editingConfiguration by remember { mutableStateOf(false) }
    ModalBottomSheet(onDismissRequest = onDismiss, modifier = Modifier.testTag(UiTags.McpSheet)) {
        if (editingConfiguration) {
            McpConfigEditorContent(
                config = state.mcpConfig,
                mutationBusy = state.workspaceMutationBusy,
                onBack = { editingConfiguration = false },
                onSave = { rawJson ->
                    viewModel.updateMcpConfiguration(rawJson) { editingConfiguration = false }
                },
            )
        } else {
            McpSheetContent(
                config = state.mcpConfig,
                loading = state.loadingMcpConfig,
                mutationBusy = state.workspaceMutationBusy,
                onServerEnabledChanged = viewModel::setMcpServerEnabled,
                onEditConfiguration = { editingConfiguration = true },
            )
        }
    }
}

@Composable
internal fun McpSheetContent(
    config: McpConfig?,
    loading: Boolean,
    mutationBusy: Boolean,
    canManageServers: Boolean = true,
    onServerEnabledChanged: (String, Boolean) -> Unit,
    onEditConfiguration: () -> Unit = {},
) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(start = 24.dp, end = 12.dp, top = 8.dp, bottom = 4.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Text(
            stringResource(R.string.mcp_servers),
            style = MaterialTheme.typography.titleLarge,
            modifier = Modifier.weight(1f),
        )
        if (config != null && canManageServers) {
            IconButton(
                onClick = onEditConfiguration,
                enabled = !mutationBusy,
                modifier = Modifier.testTag(UiTags.McpConfigEdit),
            ) {
                Icon(Icons.Outlined.Edit, contentDescription = stringResource(R.string.mcp_edit_configuration))
            }
        }
    }
    when {
        loading -> Text(
            stringResource(R.string.loading),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 24.dp, vertical = 32.dp),
        )

        config == null || config.servers.isEmpty() -> Text(
            stringResource(R.string.no_mcp_servers),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 24.dp, vertical = 32.dp),
        )

        else -> LazyColumn(
            modifier = Modifier.fillMaxWidth().height(440.dp),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            items(config.servers, key = { it.name }) { server ->
                ListItem(
                    headlineContent = { Text(server.name) },
                    supportingContent = {
                        Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                            Text(server.transport, style = MaterialTheme.typography.labelMedium)
                            if (server.description.isNotBlank()) {
                                Text(server.description, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            }
                            if (server.toolOverrides.isNotEmpty()) {
                                Text(
                                    stringResource(R.string.mcp_tool_overrides, server.toolOverrides.joinToString()),
                                    style = MaterialTheme.typography.labelMedium,
                                )
                            }
                        }
                    },
                    trailingContent = {
                        Switch(
                            checked = server.enabled,
                            onCheckedChange = { onServerEnabledChanged(server.name, it) },
                            enabled = canManageServers && !mutationBusy,
                            modifier = Modifier.testTag(UiTags.McpServerEnablePrefix + server.name),
                        )
                    },
                    colors = ListItemDefaults.colors(containerColor = Color.Transparent),
                    modifier = Modifier.testTag(UiTags.McpServerPrefix + server.name),
                )
            }
        }
    }
    Spacer(Modifier.navigationBarsPadding().height(20.dp))
}

@Composable
fun ChannelsSheet(
    state: AppUiState,
    viewModel: AppViewModel,
    onDismiss: () -> Unit,
) {
    val uriHandler = LocalUriHandler.current
    ModalBottomSheet(
        onDismissRequest = {
            viewModel.clearChannelConnect()
            onDismiss()
        },
        modifier = Modifier.testTag(UiTags.ChannelsSheet),
    ) {
        ChannelsSheetContent(
            providers = state.channelProviders,
            loading = state.loadingChannels,
            mutationBusy = state.workspaceMutationBusy,
            isAdmin = state.user?.role == "admin",
            connection = state.channelConnect,
            onConfigure = viewModel::configureChannelProvider,
            onDisable = viewModel::disconnectChannelProvider,
            onConnect = viewModel::connectChannelProvider,
            onOpenUrl = uriHandler::openUri,
        )
    }
}

@Composable
internal fun McpConfigEditorContent(
    config: McpConfig?,
    mutationBusy: Boolean,
    onBack: () -> Unit,
    onSave: (String) -> Unit,
) {
    if (config == null) {
        Text(
            stringResource(R.string.no_mcp_servers),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 24.dp, vertical = 32.dp),
        )
        return
    }

    var rawConfiguration by remember(config.rawJson) { mutableStateOf(config.rawJson) }
    var validationError by remember(config.rawJson) { mutableStateOf(false) }
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .heightIn(max = 600.dp)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 24.dp, vertical = 8.dp)
            .testTag(UiTags.McpConfigEditor),
        verticalArrangement = Arrangement.spacedBy(12.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack, enabled = !mutationBusy) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = stringResource(R.string.back))
            }
            Text(
                stringResource(R.string.mcp_config_editor_title),
                style = MaterialTheme.typography.titleLarge,
                modifier = Modifier.padding(start = 4.dp),
            )
        }
        Text(
            stringResource(R.string.mcp_config_editor_description),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        OutlinedTextField(
            value = rawConfiguration,
            onValueChange = {
                rawConfiguration = it
                validationError = false
            },
            minLines = 10,
            maxLines = 20,
            modifier = Modifier.fillMaxWidth().testTag(UiTags.McpConfigRawJson),
            isError = validationError,
        )
        if (validationError) {
            Text(
                stringResource(R.string.mcp_config_invalid),
                color = MaterialTheme.colorScheme.error,
                style = MaterialTheme.typography.bodySmall,
            )
        }
        TextButton(
            onClick = {
                val valid = runCatching {
                    JSONObject(rawConfiguration).optJSONObject("mcp_servers") != null
                }.getOrDefault(false)
                if (valid) onSave(rawConfiguration) else validationError = true
            },
            enabled = !mutationBusy,
            modifier = Modifier.align(Alignment.End).testTag(UiTags.McpConfigSave),
        ) { Text(stringResource(R.string.save)) }
    }
}

@Composable
internal fun ChannelsSheetContent(
    providers: ChannelProviders?,
    loading: Boolean,
    mutationBusy: Boolean,
    isAdmin: Boolean,
    connection: ChannelConnectResult?,
    onConfigure: (String, Map<String, String>) -> Unit,
    onDisable: (String) -> Unit,
    onConnect: (String) -> Unit,
    onOpenUrl: (String) -> Unit = {},
) {
    var configurationTarget by remember { mutableStateOf<ChannelProviderInfo?>(null) }
    Text(
        stringResource(R.string.channels),
        style = MaterialTheme.typography.titleLarge,
        modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp),
    )
    when {
        loading -> Text(
            stringResource(R.string.loading),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 24.dp, vertical = 32.dp),
        )

        providers == null || !providers.enabled -> Text(
            stringResource(R.string.channels_disabled),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 24.dp, vertical = 32.dp),
        )

        providers.providers.isEmpty() -> Text(
            stringResource(R.string.no_channel_providers),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 24.dp, vertical = 32.dp),
        )

        else -> LazyColumn(
            modifier = Modifier.fillMaxWidth().height(440.dp),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
            verticalArrangement = Arrangement.spacedBy(4.dp),
        ) {
            items(providers.providers, key = { it.provider }) { provider ->
                ChannelProviderRow(
                    provider = provider,
                    isAdmin = isAdmin,
                    mutationBusy = mutationBusy,
                    onConfigure = { configurationTarget = provider },
                    onDisable = { onDisable(provider.provider) },
                    onConnect = { onConnect(provider.provider) },
                )
            }
            connection?.let { result ->
                item(key = "channel-binding-${result.provider}") {
                    ChannelBindingResult(result, onOpenUrl)
                }
            }
        }
    }
    configurationTarget?.let { provider ->
        ChannelRuntimeConfigDialog(
            provider = provider,
            mutationBusy = mutationBusy,
            onDismiss = { configurationTarget = null },
            onSave = { values ->
                configurationTarget = null
                onConfigure(provider.provider, values)
            },
        )
    }
    Spacer(Modifier.navigationBarsPadding().height(20.dp))
}

@Composable
private fun ChannelProviderRow(
    provider: ChannelProviderInfo,
    isAdmin: Boolean,
    mutationBusy: Boolean,
    onConfigure: () -> Unit,
    onDisable: () -> Unit,
    onConnect: () -> Unit,
) {
    val status = when {
        !provider.enabled -> stringResource(R.string.channel_provider_disabled)
        !provider.configured -> stringResource(R.string.channel_not_configured)
        provider.connectionStatus == "connected" -> stringResource(R.string.channel_connected)
        else -> stringResource(R.string.channel_not_connected)
    }
    ListItem(
        headlineContent = { Text(provider.displayName) },
        supportingContent = {
            Column(verticalArrangement = Arrangement.spacedBy(2.dp)) {
                Text(status, style = MaterialTheme.typography.labelMedium)
                provider.unavailableReason?.let { reason ->
                    Text(reason, maxLines = 2, overflow = TextOverflow.Ellipsis)
                }
            }
        },
        trailingContent = {
            Column(horizontalAlignment = Alignment.End) {
                if (isAdmin && provider.enabled && provider.credentialFields.isNotEmpty()) {
                    TextButton(
                        onClick = onConfigure,
                        enabled = !mutationBusy,
                        modifier = Modifier.testTag(UiTags.ChannelConfigurePrefix + provider.provider),
                    ) {
                        Text(stringResource(if (provider.configured) R.string.channel_edit_configuration_action else R.string.channel_configure_action))
                    }
                }
                if (isAdmin && provider.configured) {
                    TextButton(
                        onClick = onDisable,
                        enabled = !mutationBusy,
                        modifier = Modifier.testTag(UiTags.ChannelDisablePrefix + provider.provider),
                    ) {
                        Text(stringResource(R.string.channel_disable))
                    }
                }
                if (provider.connectable && provider.connectionStatus != "connected") {
                    FilledTonalButton(
                        onClick = onConnect,
                        enabled = !mutationBusy,
                        modifier = Modifier.testTag(UiTags.ChannelConnectPrefix + provider.provider),
                    ) {
                        Text(stringResource(R.string.channel_connect))
                    }
                }
            }
        },
        colors = ListItemDefaults.colors(containerColor = Color.Transparent),
        modifier = Modifier.testTag(UiTags.ChannelProviderPrefix + provider.provider),
    )
}

@Composable
private fun ChannelBindingResult(result: ChannelConnectResult, onOpenUrl: (String) -> Unit) {
    Column(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 12.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(stringResource(R.string.channel_binding_code), style = MaterialTheme.typography.titleSmall)
        Text(result.code, modifier = Modifier.testTag(UiTags.ChannelBindingCode), style = MaterialTheme.typography.headlineSmall)
        if (result.instruction.isNotBlank()) Text(result.instruction)
        result.url?.let { url ->
            TextButton(onClick = { onOpenUrl(url) }) { Text(stringResource(R.string.channel_open_link)) }
        }
    }
}

@Composable
private fun ChannelRuntimeConfigDialog(
    provider: ChannelProviderInfo,
    mutationBusy: Boolean,
    onDismiss: () -> Unit,
    onSave: (Map<String, String>) -> Unit,
) {
    var values by remember(provider.provider) { mutableStateOf(provider.credentialValues) }
    val valid = provider.credentialFields.all { field -> !field.required || !values[field.name].isNullOrBlank() }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = {
            Text(
                stringResource(
                    if (provider.configured) R.string.channel_edit_configuration else R.string.channel_configure,
                    provider.displayName,
                ),
            )
        },
        text = {
            Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Text(stringResource(R.string.channel_configuration_description))
                provider.credentialFields.forEach { field ->
                    OutlinedTextField(
                        value = values[field.name].orEmpty(),
                        onValueChange = { value -> values = values + (field.name to value) },
                        label = { Text(field.label) },
                        singleLine = true,
                        visualTransformation = if (field.type == "password") PasswordVisualTransformation() else VisualTransformation.None,
                        modifier = Modifier.fillMaxWidth().testTag(UiTags.ChannelCredentialPrefix + field.name),
                    )
                }
            }
        },
        confirmButton = {
            TextButton(
                onClick = { onSave(values) },
                enabled = valid && !mutationBusy,
                modifier = Modifier.testTag(UiTags.ChannelConfigSave),
            ) { Text(stringResource(R.string.channel_save_configuration)) }
        },
        dismissButton = {
            TextButton(onClick = onDismiss, enabled = !mutationBusy) { Text(stringResource(R.string.cancel)) }
        },
    )
}

@Composable
internal fun SkillsSheetContent(
    skills: List<SkillInfo>,
    selectedSkills: Set<String>,
    onSkillSelected: (String) -> Unit,
    onSkillDetail: (SkillInfo) -> Unit = { onSkillSelected(it.name) },
    showDisabledSkills: Boolean = false,
    canManageSkillStates: Boolean = false,
    mutationBusy: Boolean = false,
    onSkillEnabledChanged: (String, Boolean) -> Unit = { _, _ -> },
    titleRes: Int = R.string.skills,
) {
    var query by remember { mutableStateOf("") }
    val visibleSkills = skills.filter { skill ->
        (showDisabledSkills || skill.enabled) && (
            query.isBlank() || listOf(skill.name, skill.description, skill.category)
                .any { value -> value.contains(query, ignoreCase = true) }
        )
    }
    Text(
        stringResource(titleRes),
        style = MaterialTheme.typography.titleLarge,
        modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp),
    )
    OutlinedTextField(
        value = query,
        onValueChange = { query = it },
        leadingIcon = { Icon(Icons.Outlined.Search, contentDescription = null) },
        placeholder = { Text(stringResource(R.string.search_skills)) },
        singleLine = true,
        modifier = Modifier
            .fillMaxWidth()
            .padding(horizontal = 16.dp, vertical = 8.dp)
            .testTag(UiTags.SkillsSearch),
    )
    if (visibleSkills.isEmpty()) {
        Text(
            stringResource(if (skills.any { it.enabled }) R.string.no_matching_skills else R.string.no_skills_available),
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            modifier = Modifier.padding(horizontal = 24.dp, vertical = 32.dp),
        )
    } else {
        LazyVerticalStaggeredGrid(
            columns = StaggeredGridCells.Adaptive(168.dp),
            modifier = Modifier.fillMaxWidth().height(440.dp).testTag(UiTags.SkillsGrid),
            contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp),
            horizontalArrangement = Arrangement.spacedBy(10.dp),
            verticalItemSpacing = 10.dp,
        ) {
            staggeredItems(visibleSkills, key = { it.name }) { skill ->
                val selected = skill.name in selectedSkills
                Surface(
                    onClick = { onSkillDetail(skill) },
                    shape = MaterialTheme.shapes.large,
                    color = if (selected) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.surfaceVariant,
                    modifier = Modifier.fillMaxWidth().testTag(UiTags.SkillCardPrefix + skill.name),
                ) {
                    Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Text(skill.name, style = MaterialTheme.typography.titleMedium)
                        Text(
                            skill.description.ifBlank { stringResource(R.string.skill_no_description) },
                            style = MaterialTheme.typography.bodyMedium,
                            color = if (selected) MaterialTheme.colorScheme.onPrimaryContainer else MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        if (canManageSkillStates) {
                            Row(
                                modifier = Modifier.fillMaxWidth(),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                Text(
                                    stringResource(R.string.enable_skill_for_workspace),
                                    style = MaterialTheme.typography.labelLarge,
                                    modifier = Modifier.weight(1f),
                                )
                                Switch(
                                    checked = skill.enabled,
                                    onCheckedChange = { onSkillEnabledChanged(skill.name, it) },
                                    enabled = !mutationBusy,
                                    modifier = Modifier.testTag(UiTags.SkillGlobalEnablePrefix + skill.name),
                                )
                            }
                        }
                    }
                }
            }
        }
    }
    Spacer(Modifier.navigationBarsPadding().height(20.dp))
}

@Composable
internal fun SkillDetailContent(
    skill: SkillInfo,
    selected: Boolean,
    onBack: () -> Unit,
    onSkillSelected: (String) -> Unit,
    canManageSkillStates: Boolean = false,
    mutationBusy: Boolean = false,
    onSkillEnabledChanged: (String, Boolean) -> Unit = { _, _ -> },
) {
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .testTag(UiTags.SkillDetailScreen)
            .padding(horizontal = 24.dp, vertical = 8.dp),
        verticalArrangement = Arrangement.spacedBy(16.dp),
    ) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = onBack, modifier = Modifier.testTag(UiTags.SkillDetailBack)) {
                Icon(Icons.AutoMirrored.Outlined.ArrowBack, contentDescription = stringResource(R.string.back))
            }
            Text(skill.name, style = MaterialTheme.typography.titleLarge, modifier = Modifier.weight(1f))
        }
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(stringResource(R.string.skill_category), style = MaterialTheme.typography.labelLarge)
            Text(
                skill.category.ifBlank { stringResource(R.string.skill_uncategorized) },
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Text(stringResource(R.string.description), style = MaterialTheme.typography.labelLarge)
            Text(
                skill.description.ifBlank { stringResource(R.string.skill_no_description) },
                style = MaterialTheme.typography.bodyLarge,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        }
        HorizontalDivider()
        if (canManageSkillStates) {
            Row(
                modifier = Modifier.fillMaxWidth(),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(
                    stringResource(R.string.enable_skill_for_workspace),
                    modifier = Modifier.weight(1f),
                )
                Switch(
                    checked = skill.enabled,
                    onCheckedChange = { onSkillEnabledChanged(skill.name, it) },
                    enabled = !mutationBusy,
                    modifier = Modifier.testTag(UiTags.SkillDetailGlobalEnable),
                )
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth(),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Checkbox(
                checked = selected,
                onCheckedChange = { onSkillSelected(skill.name) },
                enabled = skill.enabled,
                modifier = Modifier.testTag(UiTags.SkillDetailSelect),
            )
            Text(stringResource(R.string.enable_skill_for_next_run))
        }
        Spacer(Modifier.navigationBarsPadding().height(20.dp))
    }
}
