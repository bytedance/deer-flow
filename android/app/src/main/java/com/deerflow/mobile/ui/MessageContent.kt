@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.deerflow.mobile.ui

import androidx.compose.animation.animateContentSize
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.ime
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.relocation.BringIntoViewRequester
import androidx.compose.foundation.relocation.bringIntoViewRequester
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.filled.Send
import androidx.compose.material.icons.automirrored.outlined.HelpOutline
import androidx.compose.material.icons.automirrored.outlined.CallSplit
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.CheckBoxOutlineBlank
import androidx.compose.material.icons.outlined.ContentCopy
import androidx.compose.material.icons.outlined.Code
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.Psychology
import androidx.compose.material.icons.outlined.IndeterminateCheckBox
import androidx.compose.material3.AssistChip
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.LoadingIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.IconButton
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.PlainTooltip
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TooltipBox
import androidx.compose.material3.TooltipAnchorPosition
import androidx.compose.material3.TooltipDefaults
import androidx.compose.material3.rememberTooltipState
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
import androidx.compose.ui.focus.onFocusChanged
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.deerflow.mobile.R
import com.deerflow.mobile.data.ChatMessage
import com.deerflow.mobile.data.ChatMessageGroup
import com.deerflow.mobile.data.HumanInputRequest
import com.deerflow.mobile.data.MessageBlock
import com.deerflow.mobile.data.MessageRole
import com.deerflow.mobile.data.TokenUsage
import com.deerflow.mobile.ui.theme.ExpressiveMotion
import org.json.JSONObject

@Composable
fun ChatMessageGroupItem(
    group: ChatMessageGroup,
    runActive: Boolean,
    actionBusy: Boolean = false,
    onHumanInput: (HumanInputRequest, String, String?) -> Unit,
    onCopy: (String) -> Unit = {},
    onBranch: (String) -> Unit = {},
    onArtifact: (String) -> Unit = {},
) {
    when (group) {
        is ChatMessageGroup.Message -> MessageItem(
            message = group.message,
            showReasoning = group.showReasoning,
            trailingArtifacts = group.trailingArtifacts,
            actionsEnabled = !runActive && !actionBusy,
            onCopy = onCopy,
            onBranch = onBranch,
            onArtifact = onArtifact,
        )
        is ChatMessageGroup.Processing -> ProcessingMessageGroup(group, runActive, onArtifact)
        is ChatMessageGroup.HumanInput -> HumanInputCard(
            request = group.request,
            response = group.response,
            isLatestOpen = group.isLatestOpen,
            runActive = runActive,
            onSubmit = onHumanInput,
        )
        is ChatMessageGroup.Approval -> HumanInputCard(
            request = group.request,
            response = group.response,
            isLatestOpen = group.isLatestOpen,
            runActive = runActive,
            onSubmit = onHumanInput,
            approval = true,
        )
    }
}

@Composable
private fun MessageItem(
    message: ChatMessage,
    showReasoning: Boolean,
    trailingArtifacts: List<MessageBlock.Artifact>,
    actionsEnabled: Boolean,
    onCopy: (String) -> Unit,
    onBranch: (String) -> Unit,
    onArtifact: (String) -> Unit,
) {
    val user = message.role == MessageRole.User
    val clipboard = LocalClipboardManager.current
    val reasoning = message.blocks.filterIsInstance<MessageBlock.Reasoning>().lastOrNull()?.takeIf { showReasoning }
    Row(Modifier.fillMaxWidth(), horizontalArrangement = if (user) Arrangement.End else Arrangement.Start) {
        Surface(
            color = when (message.role) {
                MessageRole.User -> MaterialTheme.colorScheme.primaryContainer
                MessageRole.Assistant -> Color.Transparent
                MessageRole.Tool, MessageRole.System -> MaterialTheme.colorScheme.surfaceVariant
            },
            shape = MaterialTheme.shapes.medium,
            modifier = Modifier.widthIn(max = 720.dp).animateContentSize(ExpressiveMotion.spatial()),
        ) {
            Column(Modifier.padding(if (user) 14.dp else 8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                if (!user) {
                    Text(
                        if (message.role == MessageRole.Assistant) "DeerFlow" else stringResource(R.string.system),
                        style = MaterialTheme.typography.labelLarge,
                        color = MaterialTheme.colorScheme.secondary,
                    )
                }
                if (user) {
                    SelectionContainer {
                        Text(message.text, style = MaterialTheme.typography.bodyLarge)
                    }
                } else {
                    SelectionContainer {
                        Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            if (message.role == MessageRole.Assistant) {
                                reasoning?.let { FinalReasoningDisclosure(it.text) }
                            }
                            message.blocks
                                .filterNot {
                                    it is MessageBlock.Reasoning ||
                                        it is MessageBlock.ToolCall ||
                                        it is MessageBlock.ToolResult
                                }
                                .forEach { MessageBlockView(it, onArtifact) }
                            trailingArtifacts.forEach { MessageBlockView(it, onArtifact) }
                        }
                    }
                }
                MessageAttachments(message)
                if (message.role == MessageRole.Assistant) {
                    message.tokenUsage?.let { usage -> TokenUsageLabel(usage) }
                }
                if (message.isStreaming) {
                    Box(Modifier.size(7.dp).clip(CircleShape).background(MaterialTheme.colorScheme.primary))
                }
                if (message.id.isNotBlank() && message.role == MessageRole.Assistant) {
                    Row(
                        modifier = Modifier.align(Alignment.Start),
                        horizontalArrangement = Arrangement.spacedBy(2.dp),
                    ) {
                        MessageActionButton(
                            icon = Icons.Outlined.ContentCopy,
                            label = stringResource(R.string.copy),
                            enabled = message.text.isNotBlank(),
                            onClick = {
                                clipboard.setText(AnnotatedString(message.text))
                                onCopy(message.id)
                            },
                        )
                        MessageActionButton(
                            icon = Icons.AutoMirrored.Outlined.CallSplit,
                            label = stringResource(R.string.branch_conversation),
                            enabled = actionsEnabled,
                            onClick = { onBranch(message.id) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun TokenUsageLabel(usage: TokenUsage) {
    Text(
        stringResource(
            R.string.token_usage,
            formatTokenCount(usage.inputTokens),
            formatTokenCount(usage.outputTokens),
            formatTokenCount(usage.totalTokens),
        ),
        style = MaterialTheme.typography.labelSmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant,
    )
}

internal fun formatTokenCount(value: Long): String = when {
    value >= 1_000_000 -> compactTokenCount(value, 1_000_000, "m")
    value >= 1_000 -> compactTokenCount(value, 1_000, "k")
    else -> value.toString()
}

private fun compactTokenCount(value: Long, divisor: Long, suffix: String): String {
    val scaled = value.toDouble() / divisor
    val rounded = (scaled * 10).toInt() / 10.0
    val text = if (rounded % 1.0 == 0.0) rounded.toInt().toString() else rounded.toString()
    return text + suffix
}

@Composable
private fun MessageActionButton(
    icon: ImageVector,
    label: String,
    enabled: Boolean,
    onClick: () -> Unit,
) {
    TooltipBox(
        positionProvider = TooltipDefaults.rememberTooltipPositionProvider(TooltipAnchorPosition.Above),
        tooltip = { PlainTooltip { Text(label) } },
        state = rememberTooltipState(),
    ) {
        IconButton(onClick = onClick, enabled = enabled, modifier = Modifier.size(48.dp)) {
            Icon(icon, contentDescription = label, modifier = Modifier.size(20.dp))
        }
    }
}

@Composable
private fun ProcessingMessageGroup(group: ChatMessageGroup.Processing, runActive: Boolean, onArtifact: (String) -> Unit) {
    val steps = remember(group.messages) { processingSteps(group.messages) }
    val lastToolIndex = steps.indexOfLast { it is ProcessingStep.Tool }
    val aboveLastTool = steps.take(lastToolIndex.coerceAtLeast(0))
    val collapsibleAboveLastTool = aboveLastTool.filterNot { it is ProcessingStep.AssistantText }
    val lastTool = steps.getOrNull(lastToolIndex) as? ProcessingStep.Tool
    val stepReasoning = if (lastToolIndex >= 0) {
        steps.drop(lastToolIndex + 1).filterIsInstance<ProcessingStep.Reasoning>().lastOrNull()
    } else {
        steps.filterIsInstance<ProcessingStep.Reasoning>().lastOrNull()
    }
    val finalReasoning = group.trailingReasoning?.text ?: stepReasoning?.text
    var showPreviousSteps by rememberSaveable(group.key) { mutableStateOf(false) }

    Surface(
        color = MaterialTheme.colorScheme.surfaceContainerLow,
        shape = RoundedCornerShape(8.dp),
        modifier = Modifier
            .fillMaxWidth()
            .widthIn(max = 760.dp)
            .testTag(UiTags.ProcessingCard)
            .animateContentSize(ExpressiveMotion.spatial()),
    ) {
        Column(Modifier.padding(horizontal = 12.dp, vertical = 10.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            if (collapsibleAboveLastTool.isNotEmpty()) {
                ProcessingStepsToggle(
                    count = collapsibleAboveLastTool.size,
                    expanded = showPreviousSteps,
                    onClick = { showPreviousSteps = !showPreviousSteps },
                )
            }
            val visibleAboveLastTool = if (showPreviousSteps) {
                aboveLastTool
            } else {
                aboveLastTool.filterIsInstance<ProcessingStep.AssistantText>()
            }
            visibleAboveLastTool.forEach { ProcessingStepView(it, runActive = false, onArtifact) }
            lastTool?.let { ProcessingStepView(it, runActive = runActive, onArtifact) }
            steps.drop(lastToolIndex + 1)
                .filterNot { it == stepReasoning }
                .forEach { ProcessingStepView(it, runActive = false, onArtifact) }
            finalReasoning?.let { FinalReasoningDisclosure(it) }
            if (runActive && (steps.isEmpty() || lastTool?.result != null)) {
                ThinkingIndicator()
            }
        }
    }
}

@Composable
private fun ProcessingStepsToggle(count: Int, expanded: Boolean, onClick: () -> Unit) {
    TextButton(onClick = onClick, modifier = Modifier.fillMaxWidth()) {
        Icon(
            Icons.Outlined.ExpandMore,
            contentDescription = null,
            modifier = Modifier.rotate(if (expanded) 180f else 0f),
        )
        Text(
            stringResource(if (expanded) R.string.fewer_tool_steps else R.string.more_tool_steps, count),
            modifier = Modifier.padding(start = 6.dp),
        )
    }
}

private sealed interface ProcessingStep {
    val key: String

    data class AssistantText(val block: MessageBlock, override val key: String) : ProcessingStep
    data class Reasoning(val text: String, override val key: String) : ProcessingStep
    data class Tool(
        val call: MessageBlock.ToolCall,
        val result: MessageBlock.ToolResult?,
        override val key: String,
    ) : ProcessingStep

    data class Subtask(val value: MessageBlock.Subtask, override val key: String) : ProcessingStep
}

private fun processingSteps(messages: List<ChatMessage>): List<ProcessingStep> {
    val results = messages
        .flatMap { it.blocks }
        .filterIsInstance<MessageBlock.ToolResult>()
        .associateBy { it.callId }

    return buildList {
        messages.forEachIndexed { messageIndex, message ->
            if (message.role != MessageRole.Assistant) return@forEachIndexed
            val containsToolCall = message.blocks.any { it is MessageBlock.ToolCall }
            message.blocks.forEachIndexed { blockIndex, block ->
                val key = "${message.id.ifBlank { messageIndex.toString() }}:$blockIndex"
                when (block) {
                    is MessageBlock.Markdown, is MessageBlock.Code, is MessageBlock.Quote -> {
                        if (containsToolCall) add(ProcessingStep.AssistantText(block, key))
                    }
                    is MessageBlock.Reasoning -> add(ProcessingStep.Reasoning(block.text, key))
                    is MessageBlock.ToolCall -> {
                        if (block.name !in setOf("task", "present_files")) {
                            add(ProcessingStep.Tool(block, results[block.id], key))
                        }
                    }
                    is MessageBlock.Subtask -> add(ProcessingStep.Subtask(block, key))
                    else -> Unit
                }
            }
        }
    }
}

@Composable
private fun ProcessingStepView(step: ProcessingStep, runActive: Boolean, onArtifact: (String) -> Unit) {
    when (step) {
        is ProcessingStep.AssistantText -> MessageBlockView(step.block, onArtifact)
        is ProcessingStep.Reasoning -> MarkdownContent(
            step.text,
            Modifier.padding(start = 28.dp),
            onArtifact,
        )
        is ProcessingStep.Tool -> ToolCallSummary(step.call, step.result, active = runActive)
        is ProcessingStep.Subtask -> SubtaskStep(step.value)
    }
}

@Composable
private fun SubtaskStep(subtask: MessageBlock.Subtask) {
    var expanded by rememberSaveable(subtask.callId) { mutableStateOf(false) }
    val statusText = stringResource(
        when (subtask.status) {
            MessageBlock.SubtaskStatus.InProgress -> R.string.subtask_running
            MessageBlock.SubtaskStatus.Completed -> R.string.subtask_completed
            MessageBlock.SubtaskStatus.Failed -> R.string.subtask_failed
        },
    )
    Surface(
        onClick = { expanded = !expanded },
        color = MaterialTheme.colorScheme.secondaryContainer,
        shape = RoundedCornerShape(8.dp),
        modifier = Modifier.fillMaxWidth(),
    ) {
        Column(Modifier.padding(horizontal = 10.dp, vertical = 8.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                Icon(Icons.Outlined.Psychology, contentDescription = null, modifier = Modifier.size(20.dp), tint = MaterialTheme.colorScheme.primary)
                Column(Modifier.weight(1f)) {
                    Text(subtask.description, style = MaterialTheme.typography.bodyMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    Text(statusText, style = MaterialTheme.typography.labelSmall, color = if (subtask.status == MessageBlock.SubtaskStatus.Failed) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurfaceVariant)
                }
                when (subtask.status) {
                    MessageBlock.SubtaskStatus.InProgress -> LoadingIndicator(Modifier.size(20.dp))
                    MessageBlock.SubtaskStatus.Completed -> Icon(Icons.Outlined.CheckCircle, contentDescription = null, tint = MaterialTheme.colorScheme.primary)
                    MessageBlock.SubtaskStatus.Failed -> Icon(Icons.Outlined.ErrorOutline, contentDescription = null, tint = MaterialTheme.colorScheme.error)
                }
                Icon(Icons.Outlined.ExpandMore, contentDescription = null, modifier = Modifier.rotate(if (expanded) 180f else 0f))
            }
            if (expanded) {
                subtask.subagentType.takeIf { it.isNotBlank() }?.let { Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.primary) }
                subtask.prompt.takeIf { it.isNotBlank() }?.let { MarkdownContent(it) }
                subtask.result?.takeIf { it.isNotBlank() }?.let { MarkdownContent(it) }
                subtask.error?.takeIf { it.isNotBlank() }?.let { Text(it, color = MaterialTheme.colorScheme.error) }
            }
        }
    }
}

@Composable
private fun ToolCallSummary(call: MessageBlock.ToolCall, result: MessageBlock.ToolResult?, active: Boolean) {
    val failed = result?.failed == true
    val label = remember(call.name, call.detail) { toolLabel(call) }

    Row(
        modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp, vertical = 6.dp),
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(10.dp),
    ) {
        Icon(Icons.Outlined.Code, contentDescription = null, modifier = Modifier.size(20.dp), tint = MaterialTheme.colorScheme.primary)
        Text(label, modifier = Modifier.weight(1f), style = MaterialTheme.typography.bodyMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
        when {
            failed -> Icon(Icons.Outlined.ErrorOutline, contentDescription = null, tint = MaterialTheme.colorScheme.error)
            active -> LoadingIndicator(Modifier.size(20.dp))
            else -> Unit
        }
    }
}

@Composable
private fun FinalReasoningDisclosure(text: String) {
    var expanded by rememberSaveable(text.hashCode()) { mutableStateOf(false) }
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        TextButton(onClick = { expanded = !expanded }, modifier = Modifier.fillMaxWidth()) {
            Icon(Icons.Outlined.Psychology, contentDescription = null, modifier = Modifier.size(20.dp), tint = MaterialTheme.colorScheme.primary)
            Text(stringResource(R.string.reasoning), modifier = Modifier.padding(start = 8.dp, end = 8.dp))
            Box(Modifier.weight(1f))
            Icon(
                Icons.Outlined.ExpandMore,
                contentDescription = null,
                modifier = Modifier.rotate(if (expanded) 180f else 0f),
            )
        }
        if (expanded) MarkdownContent(text, Modifier.padding(horizontal = 8.dp, vertical = 4.dp))
    }
}

@Composable
private fun ThinkingIndicator() {
    Row(
        modifier = Modifier.padding(horizontal = 4.dp, vertical = 2.dp),
        horizontalArrangement = Arrangement.spacedBy(10.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        LoadingIndicator(Modifier.size(22.dp))
        Text(
            stringResource(R.string.thinking),
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
    }
}

@Composable
private fun HumanInputCard(
    request: HumanInputRequest,
    response: com.deerflow.mobile.data.HumanInputResponse?,
    isLatestOpen: Boolean,
    runActive: Boolean,
    onSubmit: (HumanInputRequest, String, String?) -> Unit,
    approval: Boolean = false,
) {
    var answer by rememberSaveable(request.requestId) { mutableStateOf("") }
    var textInputFocused by remember { mutableStateOf(false) }
    val submitRequester = remember { BringIntoViewRequester() }
    val imeBottom = WindowInsets.ime.getBottom(LocalDensity.current)
    val pending = runActive && isLatestOpen && response == null
    val enabled = isLatestOpen && response == null && !runActive

    LaunchedEffect(textInputFocused, imeBottom) {
        if (textInputFocused && imeBottom > 0) submitRequester.bringIntoView()
    }

    Surface(
        color = MaterialTheme.colorScheme.surfaceContainer,
        shape = RoundedCornerShape(8.dp),
        modifier = Modifier.fillMaxWidth().widthIn(max = 760.dp)
            .border(1.dp, MaterialTheme.colorScheme.outlineVariant, RoundedCornerShape(8.dp)),
    ) {
        Row(Modifier.padding(16.dp), horizontalArrangement = Arrangement.spacedBy(12.dp), verticalAlignment = Alignment.Top) {
            Icon(
                if (approval) Icons.Outlined.ErrorOutline else Icons.AutoMirrored.Outlined.HelpOutline,
                contentDescription = null,
                tint = if (approval) MaterialTheme.colorScheme.tertiary else MaterialTheme.colorScheme.primary,
            )
            Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                    Text(
                        request.title ?: stringResource(if (approval) R.string.approval_required else R.string.need_your_help),
                        style = MaterialTheme.typography.titleSmall,
                    )
                    when {
                        response != null -> Text(stringResource(R.string.answered), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.primary)
                        pending -> LoadingIndicator(Modifier.size(20.dp))
                    }
                }
                request.context?.takeIf { it.isNotBlank() }?.let { MarkdownContent(it) }
                MarkdownContent(request.question)
                request.options.forEach { option ->
                    OutlinedButton(
                        onClick = { onSubmit(request, option.value, option.id) },
                        enabled = enabled,
                        shape = RoundedCornerShape(6.dp),
                        modifier = Modifier.fillMaxWidth().heightIn(min = 48.dp),
                    ) {
                        Text(option.label, modifier = Modifier.fillMaxWidth())
                    }
                }
                if (request.inputMode == "free_text" || request.inputMode == "choice_with_other") {
                    OutlinedTextField(
                        value = answer,
                        onValueChange = { answer = it },
                        enabled = enabled,
                        placeholder = { Text(stringResource(R.string.human_input_placeholder)) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .heightIn(min = 96.dp)
                            .onFocusChanged { textInputFocused = it.isFocused }
                            .testTag(UiTags.HumanInputText),
                    )
                    FilledTonalButton(
                        onClick = { onSubmit(request, answer, null) },
                        enabled = enabled && answer.isNotBlank(),
                        modifier = Modifier
                            .align(Alignment.End)
                            .bringIntoViewRequester(submitRequester)
                            .testTag(UiTags.HumanInputSubmit),
                    ) {
                        Icon(Icons.AutoMirrored.Filled.Send, contentDescription = null, modifier = Modifier.size(18.dp))
                        Text(stringResource(R.string.submit_answer), modifier = Modifier.padding(start = 8.dp))
                    }
                }
                response?.let {
                    Text(stringResource(R.string.answered_value, it.value), color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
    }
}

@Composable
private fun MessageBlockView(block: MessageBlock, onArtifact: (String) -> Unit = {}) {
    when (block) {
        is MessageBlock.Markdown -> MarkdownContent(block.text, onArtifact = onArtifact)
        is MessageBlock.Code -> CodeDetail(block.code, block.language)
        is MessageBlock.Quote -> Row {
            Box(Modifier.width(3.dp).height(48.dp).background(MaterialTheme.colorScheme.primary))
            MarkdownContent(block.text, Modifier.padding(start = 12.dp), onArtifact)
        }
        is MessageBlock.Reasoning -> FinalReasoningDisclosure(block.text)
        is MessageBlock.ToolCall -> Unit
        is MessageBlock.ToolResult -> Unit
        is MessageBlock.Subtask -> SubtaskStep(block)
        is MessageBlock.HumanInput -> Unit
        is MessageBlock.Approval -> Unit
        is MessageBlock.HumanInputResponseBlock -> Unit
        is MessageBlock.Todo -> Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(
                imageVector = when (block.status) {
                    "completed" -> Icons.Outlined.CheckCircle
                    "in_progress" -> Icons.Outlined.IndeterminateCheckBox
                    else -> Icons.Outlined.CheckBoxOutlineBlank
                },
                contentDescription = null,
                tint = when (block.status) {
                    "completed" -> MaterialTheme.colorScheme.primary
                    "in_progress" -> MaterialTheme.colorScheme.secondary
                    else -> MaterialTheme.colorScheme.onSurfaceVariant
                },
                modifier = Modifier.size(18.dp),
            )
            Text(block.title, modifier = Modifier.padding(start = 8.dp))
        }
        is MessageBlock.Artifact -> AssistChip(
            onClick = { onArtifact(block.path) },
            label = { Text(block.title) },
            leadingIcon = { Icon(Icons.Outlined.FolderOpen, contentDescription = null) },
            modifier = Modifier.padding(horizontal = 4.dp, vertical = 4.dp),
        )
        is MessageBlock.Error -> Text(block.message, color = MaterialTheme.colorScheme.error)
    }
}

@Composable
internal fun CodeDetail(code: String, language: String? = null) {
    Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = RoundedCornerShape(6.dp)) {
        Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            language?.takeIf { it.isNotBlank() }?.let { Text(it, style = MaterialTheme.typography.labelMedium) }
            Text(code, style = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace))
        }
    }
}

@Composable
private fun MessageAttachments(message: ChatMessage) {
    if (message.attachments.isEmpty()) return
    LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
        items(message.attachments, key = { it.path ?: it.filename }) { file ->
            AssistChip(
                onClick = {},
                label = { Text(file.filename, maxLines = 1, overflow = TextOverflow.Ellipsis) },
                leadingIcon = { Icon(Icons.Outlined.Description, contentDescription = null, modifier = Modifier.size(18.dp)) },
            )
        }
    }
}

private fun toolLabel(call: MessageBlock.ToolCall): String {
    val args = runCatching { JSONObject(call.detail) }.getOrNull()
    val description = args?.optString("description").orEmpty()
    if (description.isNotBlank()) return description
    val subject = when (call.name) {
        "web_search", "image_search" -> args?.optString("query")
        "web_fetch" -> args?.optString("url")
        "ls", "read_file", "write_file", "str_replace" -> args?.optString("path")
        "bash" -> args?.optString("command")
        else -> null
    }
    return subject?.takeIf { it.isNotBlank() }?.let { "${call.name}: $it" } ?: call.name
}
