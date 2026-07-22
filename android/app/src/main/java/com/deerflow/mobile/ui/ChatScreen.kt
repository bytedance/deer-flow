@file:OptIn(
    androidx.compose.material3.ExperimentalMaterial3Api::class,
    androidx.compose.material3.ExperimentalMaterial3ExpressiveApi::class,
)

package com.deerflow.mobile.ui

import android.content.Context
import android.content.ActivityNotFoundException
import android.content.Intent
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.filled.Stop
import androidx.compose.material.icons.outlined.AttachFile
import androidx.compose.material.icons.outlined.CameraAlt
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.CollectionsBookmark
import androidx.compose.material.icons.outlined.Code
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.EditNote
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.KeyboardArrowDown
import androidx.compose.material.icons.outlined.Language
import androidx.compose.material.icons.outlined.Menu
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.PhotoLibrary
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Check
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.School
import androidx.compose.material.icons.outlined.SmartToy
import androidx.compose.material.icons.outlined.Tune
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material3.AssistChip
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.FloatingToolbarDefaults
import androidx.compose.material3.FilledIconButton
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.HorizontalFloatingToolbar
import androidx.compose.material3.LoadingIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.TextButton
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.rotate
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.isTraversalGroup
import androidx.compose.ui.semantics.semantics
import androidx.compose.ui.semantics.traversalIndex
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.platform.testTag
import androidx.core.content.FileProvider
import com.deerflow.mobile.R
import com.deerflow.mobile.data.AttachmentStatus
import com.deerflow.mobile.data.ChatMessageGroup
import com.deerflow.mobile.data.ConversationExportFormat
import com.deerflow.mobile.data.MessageRole
import com.deerflow.mobile.data.PendingAttachment
import com.deerflow.mobile.data.RunMode
import com.deerflow.mobile.data.RunStatus
import com.deerflow.mobile.data.TodoItem
import com.deerflow.mobile.data.groupChatMessages
import com.deerflow.mobile.data.conversationExportFileName
import com.deerflow.mobile.ui.theme.ExpressiveMotion
import java.io.File
import kotlinx.coroutines.delay

@Composable
fun ChatScreen(
    state: AppUiState,
    viewModel: AppViewModel,
    onOpenDrawer: () -> Unit,
    contentPadding: PaddingValues,
) {
    var showAttachments by remember { mutableStateOf(false) }
    var expandedTopSelector by remember { mutableStateOf<TopSelectorKind?>(null) }
    var showAgentPicker by remember { mutableStateOf(false) }
    var showSkills by remember { mutableStateOf(false) }
    var pendingExportFormat by remember { mutableStateOf<ConversationExportFormat?>(null) }
    var editorValue by rememberSaveable(
        state.draftSessionKey,
        state.composerResetToken,
        stateSaver = TextFieldValue.Saver,
    ) {
        mutableStateOf(
            TextFieldValue(
                text = state.composer.text,
                selection = TextRange(state.composer.text.length),
            ),
        )
    }
    val listState = rememberLazyListState()
    val context = LocalContext.current
    val messageGroups = remember(state.messages) { groupChatMessages(state.messages) }

    LaunchedEffect(state.composer.text) {
        if (editorValue.text != state.composer.text) {
            editorValue = TextFieldValue(
                text = state.composer.text,
                selection = TextRange(state.composer.text.length),
            )
        }
    }

    LaunchedEffect(messageGroups.size, state.messages.lastOrNull()?.text?.length) {
        if (messageGroups.isNotEmpty()) {
            delay(40)
            listState.animateScrollToItem(messageGroups.lastIndex)
        }
    }

    val photoLauncher = rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        uri?.let(viewModel::addAttachment)
    }
    val fileLauncher = rememberLauncherForActivityResult(ActivityResultContracts.OpenMultipleDocuments()) { uris ->
        uris.forEach(viewModel::addAttachment)
    }
    var cameraUri by remember { mutableStateOf<Uri?>(null) }
    val cameraLauncher = rememberLauncherForActivityResult(ActivityResultContracts.TakePicture()) { saved ->
        if (saved) cameraUri?.let(viewModel::addAttachment)
    }
    val exportLauncher = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("text/*")) { uri ->
        val format = pendingExportFormat
        pendingExportFormat = null
        if (uri != null && format != null) viewModel.exportConversation(uri, format)
    }
    val artifactSaveLauncher = rememberLauncherForActivityResult(ActivityResultContracts.CreateDocument("*/*")) { uri ->
        if (uri != null) viewModel.saveArtifact(uri)
    }

    Column(Modifier.fillMaxSize().testTag(UiTags.ChatScreen).padding(contentPadding)) {
        ChatTopBar(
            state = state,
            onOpenDrawer = onOpenDrawer,
            onBack = viewModel::closeConversation,
            onModelSelected = viewModel::selectModel,
            onModeSelected = viewModel::selectMode,
            onExport = { format ->
                pendingExportFormat = format
                val title = state.selectedThread?.title ?: "deerflow-conversation"
                exportLauncher.launch(conversationExportFileName(title, format))
            },
            expandedSelector = expandedTopSelector,
            onExpandedSelectorChange = { expandedTopSelector = it },
        )
        if (state.offline) {
            Surface(color = MaterialTheme.colorScheme.secondaryContainer) {
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) { OfflineBanner() }
            }
        }
        if (state.todos.isNotEmpty()) {
            TodoSummary(state.todos)
        }
        Box(Modifier.weight(1f).fillMaxWidth(), contentAlignment = Alignment.Center) {
            when {
                state.loadingChat -> LoadingIndicator(Modifier.size(32.dp))
                state.messages.isEmpty() -> ChatWelcome(onSuggestion = viewModel::updateDraft)
                else -> LazyColumn(
                    state = listState,
                    modifier = Modifier.fillMaxSize().widthIn(max = 900.dp),
                    contentPadding = PaddingValues(start = 16.dp, top = 20.dp, end = 16.dp, bottom = 72.dp),
                    verticalArrangement = Arrangement.spacedBy(16.dp),
                ) {
                    itemsIndexed(messageGroups, key = { _, group -> group.key }) { _, group ->
                        ChatMessageGroupItem(
                            group = group,
                            runActive = state.run.active,
                            actionBusy = state.messageActionBusy,
                            onHumanInput = viewModel::submitHumanInput,
                            onCopy = { viewModel.showNotice(context.getString(R.string.copied_to_clipboard)) },
                            onBranch = viewModel::branchConversation,
                            onArtifact = viewModel::openArtifact,
                        )
                    }
                }
            }
        }
        MessageComposer(
            state = state,
            editorValue = editorValue,
            onDraftChange = { value ->
                editorValue = value
                viewModel.updateDraft(value.text)
            },
            onAttachment = { showAttachments = true },
            onAgent = { showAgentPicker = true },
            onQuickAction = viewModel::applyQuickAction,
            onRemoveAttachment = viewModel::removeAttachment,
            onRetryAttachment = viewModel::retryAttachment,
            onSend = viewModel::sendMessage,
            onStop = viewModel::stopRun,
        )
    }

    if (showAttachments) {
        AttachmentSheet(
            onDismiss = { showAttachments = false },
            onCamera = {
                val uri = createCameraUri(context)
                cameraUri = uri
                cameraLauncher.launch(uri)
                showAttachments = false
            },
            onPhotos = {
                photoLauncher.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
                showAttachments = false
            },
            onFiles = {
                fileLauncher.launch(arrayOf("*/*"))
                showAttachments = false
            },
            onSkills = {
                showAttachments = false
                showSkills = true
            },
        )
    }
    if (showAgentPicker) {
        AgentPickerSheet(state, viewModel, onDismiss = { showAgentPicker = false })
    }
    if (showSkills) {
        SkillsSheet(
            state = state,
            viewModel = viewModel,
            onDismiss = { showSkills = false },
            onSkillSelected = { skillName ->
                val updated = insertSkillCommand(editorValue, skillName)
                editorValue = updated
                viewModel.enableSkill(skillName)
                viewModel.updateDraft(updated.text)
                showSkills = false
            },
        )
    }
    state.artifactPreview?.let { preview ->
        ArtifactPreviewDialog(
            preview = preview,
            onDismiss = viewModel::dismissArtifactPreview,
            onSave = { artifactSaveLauncher.launch(preview.filename) },
            onOpen = {
                val uri = FileProvider.getUriForFile(context, "${context.packageName}.files", File(preview.localPath))
                val intent = Intent(Intent.ACTION_VIEW)
                    .setDataAndType(uri, preview.mimeType)
                    .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
                try {
                    context.startActivity(intent)
                } catch (_: ActivityNotFoundException) {
                    viewModel.reportArtifactOpenFailure()
                }
            },
        )
    }
}

@Composable
internal fun ChatTopBar(
    state: AppUiState,
    onOpenDrawer: () -> Unit,
    onBack: () -> Unit,
    onModelSelected: (String?) -> Unit,
    onModeSelected: (RunMode) -> Unit,
    onExport: (ConversationExportFormat) -> Unit,
    expandedSelector: TopSelectorKind?,
    onExpandedSelectorChange: (TopSelectorKind?) -> Unit,
) {
    var exportMenuExpanded by remember { mutableStateOf(false) }
    TopAppBar(
        modifier = Modifier
            .testTag(UiTags.ChatTopBar)
            .semantics { isTraversalGroup = true },
        navigationIcon = {
            IconButton(
                onClick = if (state.route == AppRoute.Conversation) onBack else onOpenDrawer,
                modifier = Modifier
                    .size(48.dp)
                    .testTag(UiTags.ChatNavigationButton)
                    .semantics { traversalIndex = 0f },
            ) {
                Icon(
                    if (state.route == AppRoute.Conversation) Icons.AutoMirrored.Outlined.ArrowBack else Icons.Outlined.Menu,
                    contentDescription = stringResource(if (state.route == AppRoute.Conversation) R.string.back else R.string.open_navigation),
                )
            }
        },
        actions = {
            if (state.route == AppRoute.Conversation && state.messages.isNotEmpty()) {
                Box {
                    IconButton(
                        onClick = { exportMenuExpanded = true },
                        enabled = !state.exportBusy,
                        modifier = Modifier
                            .size(48.dp)
                            .testTag(UiTags.ConversationExportButton)
                            .semantics { traversalIndex = 3f },
                    ) {
                        Icon(Icons.Outlined.MoreVert, contentDescription = stringResource(R.string.export_conversation))
                    }
                    DropdownMenu(
                        expanded = exportMenuExpanded,
                        onDismissRequest = { exportMenuExpanded = false },
                    ) {
                        DropdownMenuItem(
                            text = { Text(stringResource(R.string.export_markdown)) },
                            leadingIcon = { Icon(Icons.Outlined.Description, contentDescription = null) },
                            onClick = {
                                exportMenuExpanded = false
                                onExport(ConversationExportFormat.Markdown)
                            },
                            enabled = !state.exportBusy,
                        )
                        DropdownMenuItem(
                            text = { Text(stringResource(R.string.export_plain_text)) },
                            leadingIcon = { Icon(Icons.Outlined.Code, contentDescription = null) },
                            onClick = {
                                exportMenuExpanded = false
                                onExport(ConversationExportFormat.PlainText)
                            },
                            enabled = !state.exportBusy,
                        )
                    }
                }
            }
        },
        title = {
            ChatTopSelectors(
                state = state,
                expandedSelector = expandedSelector,
                onExpandedSelectorChange = onExpandedSelectorChange,
                onModelSelected = onModelSelected,
                onModeSelected = onModeSelected,
            )
        },
        colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
    )
}

@Composable
internal fun ChatTopSelectors(
    state: AppUiState,
    expandedSelector: TopSelectorKind?,
    onExpandedSelectorChange: (TopSelectorKind?) -> Unit,
    onModelSelected: (String?) -> Unit,
    onModeSelected: (RunMode) -> Unit,
) {
    val selectedModel = state.capabilities.selectedModel(state.composer.options.modelName)
    val model = selectedModel?.displayName ?: stringResource(R.string.model)
    val availableModes = state.capabilities.availableRunModes(state.composer.options.modelName)
    Row(
        modifier = Modifier.testTag(UiTags.TopSelectors),
        horizontalArrangement = Arrangement.spacedBy(6.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        TopSelector(
            label = model,
            modifier = Modifier
                .widthIn(max = 152.dp)
                .testTag(UiTags.ModelSelector)
                .semantics { traversalIndex = 1f },
            expanded = expandedSelector == TopSelectorKind.Model,
            onClick = {
                onExpandedSelectorChange(if (expandedSelector == TopSelectorKind.Model) null else TopSelectorKind.Model)
            },
            onDismiss = { onExpandedSelectorChange(null) },
        ) {
            Text(
                stringResource(R.string.model),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
            )
            if (state.capabilities.models.isEmpty()) {
                DropdownMenuItem(
                    text = { Text(stringResource(R.string.no_models_available)) },
                    onClick = { onExpandedSelectorChange(null) },
                    enabled = false,
                )
            } else {
                state.capabilities.models.forEach { option ->
                    DropdownMenuItem(
                        text = {
                            Text(option.displayName, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        },
                        trailingIcon = {
                            if (state.composer.options.modelName == option.name) {
                                Icon(Icons.Outlined.Check, contentDescription = stringResource(R.string.option_selected))
                            }
                        },
                        onClick = {
                            onModelSelected(option.name)
                            onExpandedSelectorChange(null)
                        },
                    )
                }
            }
        }
        TopSelector(
            label = state.composer.options.mode.label(),
            modifier = Modifier
                .widthIn(max = 92.dp)
                .testTag(UiTags.ModeSelector)
                .semantics { traversalIndex = 2f },
            expanded = expandedSelector == TopSelectorKind.Mode,
            onClick = {
                onExpandedSelectorChange(if (expandedSelector == TopSelectorKind.Mode) null else TopSelectorKind.Mode)
            },
            onDismiss = { onExpandedSelectorChange(null) },
        ) {
            Text(
                stringResource(R.string.run_mode),
                style = MaterialTheme.typography.labelMedium,
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                modifier = Modifier.padding(horizontal = 16.dp, vertical = 10.dp),
            )
            availableModes.forEach { option ->
                DropdownMenuItem(
                    text = {
                        Column(
                            modifier = Modifier.padding(vertical = 4.dp),
                            verticalArrangement = Arrangement.spacedBy(2.dp),
                        ) {
                            Text(option.label(), style = MaterialTheme.typography.titleSmall)
                            Text(
                                option.description(),
                                style = MaterialTheme.typography.bodySmall,
                                color = MaterialTheme.colorScheme.onSurfaceVariant,
                            )
                            if (state.capabilities.supportsReasoningEffort(state.composer.options.modelName)) {
                                Text(
                                    "${stringResource(R.string.reasoning_effort)}: ${option.reasoningLabel()} · ${option.reasoningDescription()}",
                                    style = MaterialTheme.typography.labelSmall,
                                    color = MaterialTheme.colorScheme.primary,
                                )
                            }
                        }
                    },
                    trailingIcon = {
                        if (state.composer.options.mode == option) {
                            Icon(Icons.Outlined.Check, contentDescription = stringResource(R.string.option_selected))
                        }
                    },
                    onClick = {
                        onModeSelected(option)
                        onExpandedSelectorChange(null)
                    },
                    contentPadding = PaddingValues(horizontal = 16.dp, vertical = 6.dp),
                )
            }
        }
    }
}

@Composable
private fun TopSelector(
    label: String,
    modifier: Modifier,
    expanded: Boolean,
    onClick: () -> Unit,
    onDismiss: () -> Unit,
    menuContent: @Composable ColumnScope.() -> Unit,
) {
    val selectorShape = RoundedCornerShape(20.dp)
    Box {
        Surface(
            onClick = onClick,
            modifier = modifier.height(48.dp),
            shape = selectorShape,
            color = if (expanded) MaterialTheme.colorScheme.primaryContainer else MaterialTheme.colorScheme.secondaryContainer,
            contentColor = if (expanded) MaterialTheme.colorScheme.onPrimaryContainer else MaterialTheme.colorScheme.onSecondaryContainer,
        ) {
            Row(
                modifier = Modifier.padding(start = 12.dp, end = 8.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Text(label, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.labelLarge)
                Icon(Icons.Outlined.KeyboardArrowDown, contentDescription = null, modifier = Modifier.size(18.dp))
            }
        }
        DropdownMenu(
            expanded = expanded,
            onDismissRequest = onDismiss,
            modifier = Modifier.widthIn(min = 240.dp, max = 340.dp).animateContentSize(ExpressiveMotion.spatial()),
            shape = selectorShape,
            containerColor = MaterialTheme.colorScheme.surfaceContainer,
            tonalElevation = 3.dp,
            shadowElevation = 6.dp,
            content = menuContent,
        )
    }
}

internal enum class TopSelectorKind {
    Model,
    Mode,
}

@Composable
private fun ChatWelcome(onSuggestion: (String) -> Unit) {
    Column(
        modifier = Modifier.fillMaxSize().padding(horizontal = 24.dp, vertical = 12.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center,
    ) {
        Icon(Icons.Outlined.SmartToy, contentDescription = null, modifier = Modifier.size(40.dp), tint = MaterialTheme.colorScheme.primary)
        Spacer(Modifier.height(10.dp))
        Text(stringResource(R.string.chat_welcome), style = MaterialTheme.typography.titleLarge)
        Spacer(Modifier.height(14.dp))
        Column(Modifier.widthIn(max = 560.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            listOf(
                R.string.suggestion_research,
                R.string.suggestion_plan,
                R.string.suggestion_summary,
            ).forEach { textId ->
                val suggestion = stringResource(textId)
                Surface(
                    onClick = { onSuggestion(suggestion) },
                    shape = MaterialTheme.shapes.medium,
                    color = MaterialTheme.colorScheme.surfaceVariant,
                    modifier = Modifier.fillMaxWidth(),
                ) {
                    Text(
                        suggestion,
                        modifier = Modifier.padding(horizontal = 16.dp, vertical = 14.dp),
                        maxLines = 2,
                        overflow = TextOverflow.Ellipsis,
                    )
                }
            }
        }
    }
}

@Composable
internal fun TodoSummary(todos: List<TodoItem>) {
    var expanded by rememberSaveable { mutableStateOf(false) }
    val completed = todos.count { it.status == "completed" }
    Surface(
        color = MaterialTheme.colorScheme.surfaceContainerLow,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp).widthIn(max = 900.dp),
        shape = RoundedCornerShape(8.dp),
    ) {
        Column(Modifier.padding(horizontal = 12.dp, vertical = 6.dp)) {
            TextButton(onClick = { expanded = !expanded }, modifier = Modifier.fillMaxWidth()) {
                Icon(Icons.Outlined.EditNote, contentDescription = null, modifier = Modifier.size(18.dp))
                Text(
                    stringResource(R.string.todo_progress, completed, todos.size),
                    modifier = Modifier.weight(1f).padding(start = 8.dp),
                    textAlign = androidx.compose.ui.text.style.TextAlign.Start,
                )
                Icon(Icons.Outlined.KeyboardArrowDown, contentDescription = null, modifier = Modifier.rotate(if (expanded) 180f else 0f))
            }
            if (expanded) {
                todos.forEach { todo ->
                    Row(
                        Modifier.fillMaxWidth().padding(horizontal = 8.dp, vertical = 4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                        horizontalArrangement = Arrangement.spacedBy(8.dp),
                    ) {
                        Text(
                            when (todo.status) {
                                "completed" -> "[x]"
                                "in_progress" -> "[>]"
                                else -> "[ ]"
                            },
                            color = if (todo.status == "completed") MaterialTheme.colorScheme.primary else MaterialTheme.colorScheme.onSurfaceVariant,
                        )
                        Text(todo.content, modifier = Modifier.weight(1f), maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }
    }
}

@Composable
internal fun ArtifactPreviewDialog(
    preview: ArtifactPreviewState,
    onDismiss: () -> Unit,
    onSave: () -> Unit,
    onOpen: () -> Unit,
) {
    val markdown = preview.filename.endsWith(".md", ignoreCase = true) || preview.filename.endsWith(".markdown", ignoreCase = true)
    val language = artifactLanguage(preview.filename, preview.mimeType)
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(preview.filename, maxLines = 2, overflow = TextOverflow.Ellipsis) },
        text = {
            Surface(
                color = MaterialTheme.colorScheme.surfaceVariant,
                shape = RoundedCornerShape(6.dp),
                modifier = Modifier.fillMaxWidth().heightIn(max = 520.dp).verticalScroll(rememberScrollState()),
            ) {
                SelectionContainer {
                    when {
                        preview.text == null -> Text(preview.mimeType, modifier = Modifier.padding(16.dp))
                        markdown -> MarkdownContent(preview.text, Modifier.padding(16.dp))
                        language != null -> Column(
                            Modifier.padding(16.dp),
                            verticalArrangement = Arrangement.spacedBy(8.dp),
                        ) {
                            Text(language, style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                            Text(
                                preview.text,
                                style = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                            )
                        }
                        else -> Text(
                            preview.text,
                            modifier = Modifier.padding(16.dp),
                            style = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace),
                        )
                    }
                }
            }
        },
        confirmButton = {
            TextButton(onClick = onOpen) { Text(stringResource(R.string.open)) }
        },
        dismissButton = {
            Row {
                TextButton(onClick = onSave) { Text(stringResource(R.string.save_copy)) }
                TextButton(onClick = onDismiss) { Text(stringResource(R.string.close)) }
            }
        },
    )
}

internal fun artifactLanguage(filename: String, mimeType: String): String? {
    val extension = filename.substringAfterLast('.', "").lowercase()
    return when {
        mimeType.contains("kotlin") -> "kotlin"
        mimeType.contains("python") -> "python"
        mimeType == "application/javascript" || mimeType == "text/javascript" -> "javascript"
        mimeType == "application/typescript" -> "typescript"
        mimeType == "application/json" -> "json"
        mimeType == "text/css" -> "css"
        mimeType.contains("xml") -> "xml"
        mimeType == "text/x-shellscript" -> "bash"
        mimeType == "text/x-sql" -> "sql"
        extension in setOf("kt", "kts") -> "kotlin"
        extension == "java" -> "java"
        extension == "py" -> "python"
        extension == "js" -> "javascript"
        extension == "ts" -> "typescript"
        extension == "tsx" -> "typescriptreact"
        extension == "jsx" -> "javascriptreact"
        extension == "json" -> "json"
        extension in setOf("yaml", "yml") -> "yaml"
        extension == "toml" -> "toml"
        extension == "css" -> "css"
        extension == "xml" -> "xml"
        extension == "sh" -> "bash"
        extension == "sql" -> "sql"
        extension == "go" -> "go"
        extension == "rs" -> "rust"
        extension == "rb" -> "ruby"
        extension == "php" -> "php"
        extension in setOf("c", "h") -> "c"
        extension in setOf("cpp", "hpp") -> "cpp"
        else -> null
    }
}

@Composable
internal fun MessageComposer(
    state: AppUiState,
    editorValue: TextFieldValue,
    onDraftChange: (TextFieldValue) -> Unit,
    onAttachment: () -> Unit,
    onAgent: () -> Unit,
    onQuickAction: (String, List<String>) -> Unit,
    onRemoveAttachment: (String) -> Unit,
    onRetryAttachment: (String) -> Unit,
    onSend: () -> Unit,
    onStop: () -> Unit,
) {
    Surface(tonalElevation = 2.dp) {
        Column(
            modifier = Modifier
                .fillMaxWidth()
                .testTag(UiTags.Composer)
                .navigationBarsPadding()
                .imePadding()
                .padding(start = 12.dp, top = 4.dp, end = 12.dp, bottom = 14.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            Column(Modifier.widthIn(max = 820.dp).fillMaxWidth()) {
                CapabilityRow(state, onAgent, onQuickAction)
                if (state.composer.attachments.isNotEmpty()) {
                    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp), contentPadding = PaddingValues(vertical = 6.dp)) {
                        items(state.composer.attachments, key = { it.uri }) { file ->
                            AttachmentChip(
                                file = file,
                                onRemove = { onRemoveAttachment(file.uri) },
                                onRetry = { onRetryAttachment(file.uri) },
                            )
                        }
                    }
                }
                Row(verticalAlignment = Alignment.Bottom) {
                    OutlinedTextField(
                        value = editorValue,
                        onValueChange = onDraftChange,
                        placeholder = { Text(stringResource(R.string.message_deerflow)) },
                        minLines = 1,
                        maxLines = 6,
                        leadingIcon = {
                            IconButton(
                                onClick = onAttachment,
                                enabled = !state.composer.uploading,
                                modifier = Modifier.size(48.dp).testTag(UiTags.ComposerAttachmentButton),
                            ) {
                                Icon(Icons.Filled.Add, contentDescription = stringResource(R.string.add_attachment))
                            }
                        },
                        modifier = Modifier.weight(1f).testTag(UiTags.ComposerInput),
                    )
                    Spacer(Modifier.width(8.dp))
                    FilledIconButton(
                        onClick = if (state.run.active) onStop else onSend,
                        enabled = state.run.active || (!state.composer.uploading && (state.composer.text.isNotBlank() || state.composer.attachments.isNotEmpty())),
                        modifier = Modifier
                            .size(52.dp)
                            .testTag(UiTags.SendStopButton),
                    ) {
                        when {
                            state.composer.uploading -> LoadingIndicator(Modifier.size(24.dp))
                            state.run.active -> Icon(Icons.Filled.Stop, contentDescription = stringResource(R.string.stop_run))
                            else -> Icon(Icons.AutoMirrored.Filled.Send, contentDescription = stringResource(R.string.send_message))
                        }
                    }
                }
            }
        }
    }
}

@Composable
internal fun CapabilityRow(
    state: AppUiState,
    onAgent: () -> Unit,
    onQuickAction: (String, List<String>) -> Unit,
) {
    val actions = listOf(
        QuickActionSpec(
            label = stringResource(R.string.quick_surprise),
            prompt = stringResource(R.string.quick_surprise_prompt),
            keywords = listOf("grill-me", "brainstorm", "惊喜"),
            icon = Icons.Outlined.AutoAwesome,
        ),
        QuickActionSpec(
            label = stringResource(R.string.quick_writing),
            prompt = stringResource(R.string.quick_writing_prompt),
            keywords = listOf("write", "writer", "writing", "写作", "文案"),
            icon = Icons.Outlined.EditNote,
        ),
        QuickActionSpec(
            label = stringResource(R.string.quick_research),
            prompt = stringResource(R.string.quick_research_prompt),
            keywords = listOf("research", "report", "调研", "研究"),
            icon = Icons.Outlined.Search,
        ),
        QuickActionSpec(
            label = stringResource(R.string.quick_collect),
            prompt = stringResource(R.string.quick_collect_prompt),
            keywords = listOf("collect", "extract", "收集", "整理"),
            icon = Icons.Outlined.CollectionsBookmark,
        ),
        QuickActionSpec(
            label = stringResource(R.string.quick_learn),
            prompt = stringResource(R.string.quick_learn_prompt),
            keywords = listOf("learn", "tutor", "学习", "教学"),
            icon = Icons.Outlined.School,
        ),
        QuickActionSpec(
            label = stringResource(R.string.quick_web),
            prompt = stringResource(R.string.quick_web_prompt),
            keywords = listOf("frontend", "web", "网页", "website"),
            icon = Icons.Outlined.Language,
        ),
        QuickActionSpec(
            label = stringResource(R.string.quick_image),
            prompt = stringResource(R.string.quick_image_prompt),
            keywords = listOf("image", "图片", "generation", "视觉"),
            icon = Icons.Outlined.Image,
        ),
    )
    HorizontalFloatingToolbar(
        expanded = true,
        modifier = Modifier.fillMaxWidth().testTag(UiTags.QuickCapabilities),
        colors = FloatingToolbarDefaults.standardFloatingToolbarColors(
            toolbarContainerColor = Color.Transparent,
            toolbarContentColor = MaterialTheme.colorScheme.onSurface,
        ),
        contentPadding = PaddingValues(horizontal = 6.dp, vertical = 0.dp),
        shape = MaterialTheme.shapes.extraLarge,
        expandedShadowElevation = 0.dp,
        collapsedShadowElevation = 0.dp,
    ) {
        Row(
            modifier = Modifier.horizontalScroll(rememberScrollState()),
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            AssistChip(
                onClick = onAgent,
                label = { Text(state.composer.options.agentLabel()) },
                leadingIcon = { Icon(Icons.Outlined.SmartToy, contentDescription = null, modifier = Modifier.size(18.dp)) },
            )
            actions.forEach { action ->
                AssistChip(
                    onClick = { onQuickAction(action.prompt, action.keywords) },
                    label = { Text(action.label) },
                    leadingIcon = { Icon(action.icon, contentDescription = null, modifier = Modifier.size(18.dp)) },
                )
            }
        }
    }
}

private data class QuickActionSpec(
    val label: String,
    val prompt: String,
    val keywords: List<String>,
    val icon: androidx.compose.ui.graphics.vector.ImageVector,
)

@Composable
internal fun AttachmentChip(file: PendingAttachment, onRemove: () -> Unit, onRetry: () -> Unit) {
    AssistChip(
        onClick = {},
        label = { Text(file.filename, maxLines = 1, overflow = TextOverflow.Ellipsis) },
        leadingIcon = {
            when (file.status) {
                AttachmentStatus.Uploading -> LoadingIndicator(Modifier.size(20.dp))
                AttachmentStatus.Failed -> Icon(Icons.Outlined.Close, contentDescription = stringResource(R.string.upload_failed), modifier = Modifier.size(18.dp))
                else -> Icon(Icons.Outlined.AttachFile, contentDescription = null, modifier = Modifier.size(18.dp))
            }
        },
        trailingIcon = {
            if (file.status == AttachmentStatus.Failed) {
                IconButton(onClick = onRetry, modifier = Modifier.size(32.dp)) {
                    Icon(Icons.Outlined.Refresh, contentDescription = stringResource(R.string.retry_upload), modifier = Modifier.size(16.dp))
                }
            } else {
                IconButton(onClick = onRemove, modifier = Modifier.size(32.dp), enabled = file.status != AttachmentStatus.Uploading) {
                    Icon(Icons.Outlined.Close, contentDescription = stringResource(R.string.remove_attachment), modifier = Modifier.size(16.dp))
                }
            }
        },
    )
}

@Composable
internal fun AttachmentSheet(
    onDismiss: () -> Unit,
    onCamera: () -> Unit,
    onPhotos: () -> Unit,
    onFiles: () -> Unit,
    onSkills: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss, modifier = Modifier.testTag(UiTags.AttachmentSheet)) {
        Text(stringResource(R.string.add_to_conversation), style = MaterialTheme.typography.titleLarge, modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp))
        Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            AttachmentAction(Icons.Outlined.CameraAlt, stringResource(R.string.camera), Modifier.weight(1f), onCamera)
            AttachmentAction(Icons.Outlined.PhotoLibrary, stringResource(R.string.photos), Modifier.weight(1f), onPhotos)
            AttachmentAction(Icons.Outlined.FolderOpen, stringResource(R.string.files), Modifier.weight(1f), onFiles)
        }
        HorizontalDivider(Modifier.padding(vertical = 8.dp))
        Surface(
            onClick = onSkills,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp),
            shape = MaterialTheme.shapes.large,
            color = MaterialTheme.colorScheme.secondaryContainer,
        ) {
            Row(
                modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp, vertical = 16.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Outlined.Tune, contentDescription = null)
                Column(Modifier.weight(1f).padding(horizontal = 14.dp)) {
                    Text(stringResource(R.string.skills), style = MaterialTheme.typography.titleMedium)
                    Text(
                        stringResource(R.string.skills_sheet_subtitle),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSecondaryContainer,
                    )
                }
                Icon(Icons.Outlined.KeyboardArrowDown, contentDescription = null)
            }
        }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun AttachmentAction(icon: androidx.compose.ui.graphics.vector.ImageVector, label: String, modifier: Modifier, onClick: () -> Unit) {
    Surface(onClick = onClick, shape = MaterialTheme.shapes.medium, color = MaterialTheme.colorScheme.surfaceVariant, modifier = modifier.height(88.dp)) {
        Column(horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Center) {
            Icon(icon, contentDescription = null)
            Spacer(Modifier.height(8.dp))
            Text(label, style = MaterialTheme.typography.labelLarge)
        }
    }
}

@Composable
private fun AgentPickerSheet(state: AppUiState, viewModel: AppViewModel, onDismiss: () -> Unit) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        Text(
            stringResource(R.string.agent),
            style = MaterialTheme.typography.titleLarge,
            modifier = Modifier.padding(horizontal = 24.dp, vertical = 8.dp),
        )
        LazyColumn(Modifier.fillMaxWidth(), contentPadding = PaddingValues(horizontal = 16.dp, vertical = 8.dp)) {
            item {
                AgentOption("lead_agent", stringResource(R.string.lead_agent_description), state.composer.options.assistantId == "lead_agent") {
                    viewModel.selectAgent("lead_agent")
                    onDismiss()
                }
            }
            items(state.capabilities.agents.customAgentsOnly(), key = { it.name }) { agent ->
                AgentOption(agent.name, agent.description, state.composer.options.assistantId == agent.name) {
                    viewModel.selectAgent(agent.name)
                    onDismiss()
                }
            }
            item { Spacer(Modifier.height(28.dp)) }
        }
    }
}

@Composable
private fun AgentOption(name: String, description: String, selected: Boolean, onClick: () -> Unit) {
    FilterChip(
        selected = selected,
        onClick = onClick,
        label = {
            Column(Modifier.padding(vertical = 8.dp)) {
                Text(name, fontWeight = FontWeight.Medium)
                if (description.isNotBlank()) Text(description, style = MaterialTheme.typography.bodyMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
            }
        },
        modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp),
    )
}

@Composable
private fun RunMode.label(): String = when (this) {
    RunMode.Flash -> stringResource(R.string.mode_flash)
    RunMode.Thinking -> stringResource(R.string.mode_thinking)
    RunMode.Pro -> stringResource(R.string.mode_plan)
    RunMode.Ultra -> stringResource(R.string.mode_ultra)
}

@Composable
private fun RunMode.description(): String = when (this) {
    RunMode.Flash -> stringResource(R.string.mode_flash_description)
    RunMode.Thinking -> stringResource(R.string.mode_thinking_description)
    RunMode.Pro -> stringResource(R.string.mode_plan_description)
    RunMode.Ultra -> stringResource(R.string.mode_ultra_description)
}

@Composable
private fun RunMode.reasoningLabel(): String = when (this) {
    RunMode.Flash -> stringResource(R.string.reasoning_effort_minimal)
    RunMode.Thinking -> stringResource(R.string.reasoning_effort_low)
    RunMode.Pro -> stringResource(R.string.reasoning_effort_medium)
    RunMode.Ultra -> stringResource(R.string.reasoning_effort_high)
}

@Composable
private fun RunMode.reasoningDescription(): String = when (this) {
    RunMode.Flash -> stringResource(R.string.reasoning_effort_minimal_description)
    RunMode.Thinking -> stringResource(R.string.reasoning_effort_low_description)
    RunMode.Pro -> stringResource(R.string.reasoning_effort_medium_description)
    RunMode.Ultra -> stringResource(R.string.reasoning_effort_high_description)
}

internal fun insertSkillCommand(value: TextFieldValue, skillName: String): TextFieldValue {
    val normalizedName = skillName.trim().removePrefix("/")
    if (normalizedName.isBlank()) return value

    val selectionStart = minOf(value.selection.start, value.selection.end)
    val selectionEnd = maxOf(value.selection.start, value.selection.end)
    val command = "/$normalizedName "
    val updatedText = value.text.replaceRange(selectionStart, selectionEnd, command)
    return TextFieldValue(
        text = updatedText,
        selection = TextRange(selectionStart + command.length),
    )
}

private fun com.deerflow.mobile.data.RunOptions.agentLabel(): String =
    if (assistantId == "lead_agent") "DeerFlow" else assistantId

private fun createCameraUri(context: Context): Uri {
    val file = File.createTempFile("deerflow-camera-", ".jpg", context.cacheDir)
    return FileProvider.getUriForFile(context, "${context.packageName}.files", file)
}
