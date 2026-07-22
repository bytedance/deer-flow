@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.deerflow.mobile.ui

import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Add
import androidx.compose.material.icons.outlined.ArrowBack
import androidx.compose.material.icons.outlined.DeleteOutline
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Menu
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.Psychology
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.LoadingIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.deerflow.mobile.R
import com.deerflow.mobile.data.MemoryFact
import com.deerflow.mobile.data.MemorySection
import java.text.NumberFormat

@Composable
fun MemoryScreen(
    state: AppUiState,
    onBack: () -> Unit,
    contentPadding: PaddingValues,
    onRefresh: () -> Unit,
    onSaveFact: (MemoryFact?, String, String, Double, () -> Unit) -> Unit,
    onDeleteFact: (MemoryFact) -> Unit,
    onClearMemory: () -> Unit,
) {
    var query by rememberSaveable { mutableStateOf("") }
    var filterName by rememberSaveable { mutableStateOf(MemoryFilter.All.name) }
    var selectedFact by remember { mutableStateOf<MemoryFact?>(null) }
    var editingFact by remember { mutableStateOf<MemoryFact?>(null) }
    var showEditor by remember { mutableStateOf(false) }
    var deleteTarget by remember { mutableStateOf<MemoryFact?>(null) }
    var showClearConfirmation by remember { mutableStateOf(false) }
    var menuExpanded by remember { mutableStateOf(false) }
    val filter = MemoryFilter.valueOf(filterName)

    Column(Modifier.fillMaxSize().padding(contentPadding).testTag(UiTags.MemoryScreen)) {
        TopAppBar(
            navigationIcon = {
                IconButton(onClick = onBack, modifier = Modifier.size(48.dp)) {
                    Icon(Icons.Outlined.ArrowBack, contentDescription = stringResource(R.string.back))
                }
            },
            title = { Text(stringResource(R.string.memory_title)) },
            actions = {
                IconButton(
                    onClick = { editingFact = null; showEditor = true },
                    enabled = !state.memoryMutationBusy,
                    modifier = Modifier.size(48.dp).testTag(UiTags.MemoryAddFact),
                ) {
                    Icon(Icons.Filled.Add, contentDescription = stringResource(R.string.memory_add_fact))
                }
                IconButton(onClick = onRefresh, enabled = !state.loadingMemory, modifier = Modifier.size(48.dp)) {
                    Icon(Icons.Outlined.Refresh, contentDescription = stringResource(R.string.refresh))
                }
                Box {
                    IconButton(
                        onClick = { menuExpanded = true },
                        modifier = Modifier.size(48.dp).testTag(UiTags.MemoryMoreActions),
                    ) {
                        Icon(Icons.Outlined.MoreVert, contentDescription = stringResource(R.string.more_actions))
                    }
                    DropdownMenu(expanded = menuExpanded, onDismissRequest = { menuExpanded = false }) {
                        DropdownMenuItem(
                            text = { Text(stringResource(R.string.memory_clear_all), color = MaterialTheme.colorScheme.error) },
                            leadingIcon = { Icon(Icons.Outlined.DeleteOutline, contentDescription = null, tint = MaterialTheme.colorScheme.error) },
                            enabled = state.memory?.isEmpty == false && !state.memoryMutationBusy,
                            onClick = {
                                menuExpanded = false
                                showClearConfirmation = true
                            },
                            modifier = Modifier.testTag(UiTags.MemoryClearAction),
                        )
                    }
                }
            },
            colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
        )

        if (state.offline && state.memory != null) {
            Surface(color = MaterialTheme.colorScheme.secondaryContainer) {
                Box(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp)) { OfflineBanner() }
            }
        }

        val memory = state.memory
        when {
            state.loadingMemory && memory == null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                LoadingIndicator(Modifier.size(32.dp))
            }
            memory == null -> Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                EmptyState(
                    icon = { Icon(Icons.Outlined.Psychology, contentDescription = null, modifier = Modifier.size(48.dp), tint = MaterialTheme.colorScheme.primary) },
                    title = stringResource(R.string.memory_unavailable),
                    body = stringResource(R.string.memory_unavailable_body),
                )
            }
            else -> MemoryContent(
                memory = memory,
                query = query,
                onQueryChange = { query = it },
                filter = filter,
                onFilterChange = { filterName = it.name },
                onSelectFact = { selectedFact = it },
            )
        }
    }

    selectedFact?.let { fact ->
        MemoryFactDetailSheet(
            fact = fact,
            onDismiss = { selectedFact = null },
            onEdit = {
                editingFact = fact
                selectedFact = null
                showEditor = true
            },
            onDelete = {
                deleteTarget = fact
                selectedFact = null
            },
        )
    }

    if (showEditor) {
        MemoryFactEditorSheet(
            state = state,
            fact = editingFact,
            onDismiss = { showEditor = false; editingFact = null },
            onSave = { content, category, confidence ->
                onSaveFact(editingFact, content, category, confidence) {
                    showEditor = false
                    editingFact = null
                }
            },
        )
    }

    deleteTarget?.let { fact ->
        AlertDialog(
            onDismissRequest = { deleteTarget = null },
            title = { Text(stringResource(R.string.memory_delete_fact_title)) },
            text = { Text(fact.content, maxLines = 5, overflow = TextOverflow.Ellipsis) },
            confirmButton = {
                TextButton(
                    onClick = { deleteTarget = null; onDeleteFact(fact) },
                    enabled = !state.memoryMutationBusy,
                    modifier = Modifier.testTag(UiTags.MemoryFactDeleteConfirm),
                ) { Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { deleteTarget = null }) { Text(stringResource(R.string.cancel)) } },
        )
    }

    if (showClearConfirmation) {
        AlertDialog(
            onDismissRequest = { showClearConfirmation = false },
            title = { Text(stringResource(R.string.memory_clear_title)) },
            text = { Text(stringResource(R.string.memory_clear_body)) },
            confirmButton = {
                TextButton(
                    onClick = { showClearConfirmation = false; onClearMemory() },
                    enabled = !state.memoryMutationBusy,
                    modifier = Modifier.testTag(UiTags.MemoryClearConfirm),
                ) { Text(stringResource(R.string.memory_clear_all), color = MaterialTheme.colorScheme.error) }
            },
            dismissButton = { TextButton(onClick = { showClearConfirmation = false }) { Text(stringResource(R.string.cancel)) } },
        )
    }
}

@Composable
private fun MemoryContent(
    memory: com.deerflow.mobile.data.MemoryData,
    query: String,
    onQueryChange: (String) -> Unit,
    filter: MemoryFilter,
    onFilterChange: (MemoryFilter) -> Unit,
    onSelectFact: (MemoryFact) -> Unit,
) {
    val normalizedQuery = query.trim().lowercase()
    val userSummaries = listOf(
        MemorySummaryItem(stringResource(R.string.memory_work_context), memory.user.workContext),
        MemorySummaryItem(stringResource(R.string.memory_personal_context), memory.user.personalContext),
        MemorySummaryItem(stringResource(R.string.memory_top_of_mind), memory.user.topOfMind),
    ).filter { it.matches(normalizedQuery) }
    val historySummaries = listOf(
        MemorySummaryItem(stringResource(R.string.memory_recent_months), memory.history.recentMonths),
        MemorySummaryItem(stringResource(R.string.memory_earlier_context), memory.history.earlierContext),
        MemorySummaryItem(stringResource(R.string.memory_long_term_background), memory.history.longTermBackground),
    ).filter { it.matches(normalizedQuery) }
    val facts = memory.facts.filter { fact ->
        normalizedQuery.isBlank() || listOf(fact.content, fact.category, fact.source)
            .any { it.contains(normalizedQuery, ignoreCase = true) }
    }
    val showSummaries = filter != MemoryFilter.Facts
    val showFacts = filter != MemoryFilter.Summaries
    val hasResults = (showSummaries && (userSummaries.isNotEmpty() || historySummaries.isNotEmpty())) ||
        (showFacts && facts.isNotEmpty())

    Column(Modifier.fillMaxSize()) {
        OutlinedTextField(
            value = query,
            onValueChange = onQueryChange,
            leadingIcon = { Icon(Icons.Outlined.Search, contentDescription = null) },
            placeholder = { Text(stringResource(R.string.memory_search)) },
            singleLine = true,
            modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 8.dp).testTag(UiTags.MemorySearch),
        )
        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp)) {
            MemoryFilter.entries.forEachIndexed { index, item ->
                SegmentedButton(
                    selected = item == filter,
                    onClick = { onFilterChange(item) },
                    shape = SegmentedButtonDefaults.itemShape(index, MemoryFilter.entries.size),
                    label = { Text(item.label()) },
                    modifier = Modifier.testTag("${UiTags.MemoryFilterPrefix}${item.name.lowercase()}"),
                )
            }
        }

        if (!hasResults) {
            Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
                EmptyState(
                    icon = { Icon(Icons.Outlined.Search, contentDescription = null, modifier = Modifier.size(44.dp), tint = MaterialTheme.colorScheme.primary) },
                    title = stringResource(if (normalizedQuery.isBlank()) R.string.memory_empty else R.string.memory_no_matches),
                    body = if (normalizedQuery.isBlank()) stringResource(R.string.memory_empty_body) else null,
                )
            }
            return@Column
        }

        LazyColumn(
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(vertical = 12.dp),
        ) {
            item {
                Row(
                    Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp),
                    horizontalArrangement = Arrangement.SpaceBetween,
                ) {
                    Text(stringResource(R.string.memory_version, memory.version), style = MaterialTheme.typography.labelLarge)
                    memory.lastUpdated.takeIf { it.isNotBlank() }?.let {
                        Text(it.toDisplayTime(), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                    }
                }
            }
            if (showSummaries && userSummaries.isNotEmpty()) {
                item { MemorySectionHeader(stringResource(R.string.memory_user_context)) }
                items(userSummaries, key = { "user-${it.title}" }) { MemorySummaryRow(it) }
            }
            if (showSummaries && historySummaries.isNotEmpty()) {
                item { MemorySectionHeader(stringResource(R.string.memory_history)) }
                items(historySummaries, key = { "history-${it.title}" }) { MemorySummaryRow(it) }
            }
            if (showFacts && facts.isNotEmpty()) {
                item { MemorySectionHeader(stringResource(R.string.memory_facts_count, facts.size)) }
                items(facts, key = { it.id }) { fact ->
                    MemoryFactRow(fact, onClick = { onSelectFact(fact) })
                }
            }
        }
    }
}

@Composable
private fun MemorySectionHeader(title: String) {
    Text(
        text = title,
        style = MaterialTheme.typography.titleMedium,
        fontWeight = FontWeight.SemiBold,
        modifier = Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 12.dp),
    )
}

@Composable
private fun MemorySummaryRow(item: MemorySummaryItem) {
    ListItem(
        headlineContent = { Text(item.title) },
        supportingContent = {
            Column {
                Text(
                    item.section.summary.ifBlank { stringResource(R.string.memory_summary_empty) },
                    color = if (item.section.summary.isBlank()) MaterialTheme.colorScheme.onSurfaceVariant else MaterialTheme.colorScheme.onSurface,
                )
                item.section.updatedAt.takeIf { it.isNotBlank() }?.let {
                    Spacer(Modifier.height(4.dp))
                    Text(it.toDisplayTime(), style = MaterialTheme.typography.labelMedium, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        },
        modifier = Modifier.fillMaxWidth(),
    )
    HorizontalDivider(Modifier.padding(horizontal = 20.dp))
}

@Composable
private fun MemoryFactRow(fact: MemoryFact, onClick: () -> Unit) {
    ListItem(
        headlineContent = { Text(fact.content, maxLines = 3, overflow = TextOverflow.Ellipsis) },
        supportingContent = {
            Text(
                "${fact.category.ifBlank { "context" }} · ${confidenceText(fact.confidence)}",
                color = MaterialTheme.colorScheme.onSurfaceVariant,
            )
        },
        trailingContent = { Icon(Icons.Outlined.MoreVert, contentDescription = stringResource(R.string.memory_open_fact)) },
        modifier = Modifier
            .fillMaxWidth()
            .testTag("${UiTags.MemoryFactPrefix}${fact.id}")
            .clickable(onClick = onClick),
    )
    HorizontalDivider(Modifier.padding(horizontal = 20.dp))
}

@Composable
private fun MemoryFactDetailSheet(
    fact: MemoryFact,
    onDismiss: () -> Unit,
    onEdit: () -> Unit,
    onDelete: () -> Unit,
) {
    ModalBottomSheet(onDismissRequest = onDismiss) {
        LazyColumn(
            modifier = Modifier.fillMaxWidth(),
            contentPadding = PaddingValues(horizontal = 20.dp, vertical = 8.dp),
        ) {
            item {
                Text(stringResource(R.string.memory_fact_detail), style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.height(16.dp))
                Text(fact.content, style = MaterialTheme.typography.bodyLarge)
                Spacer(Modifier.height(20.dp))
                MemoryMetadataRow(stringResource(R.string.memory_category), fact.category.ifBlank { "context" })
                MemoryMetadataRow(stringResource(R.string.memory_confidence), confidenceText(fact.confidence))
                MemoryMetadataRow(stringResource(R.string.memory_created), fact.createdAt.toDisplayTime().ifBlank { stringResource(R.string.memory_unknown) })
                MemoryMetadataRow(stringResource(R.string.memory_source), fact.source.ifBlank { stringResource(R.string.memory_unknown) })
                fact.sourceError?.takeIf { it.isNotBlank() }?.let {
                    MemoryMetadataRow(stringResource(R.string.memory_source_error), it, error = true)
                }
                Spacer(Modifier.height(20.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    OutlinedButton(onClick = onEdit, modifier = Modifier.weight(1f).testTag(UiTags.MemoryFactDetailEdit)) {
                        Icon(Icons.Outlined.Edit, contentDescription = null)
                        Spacer(Modifier.width(8.dp))
                        Text(stringResource(R.string.edit))
                    }
                    TextButton(onClick = onDelete, modifier = Modifier.weight(1f).testTag(UiTags.MemoryFactDetailDelete)) {
                        Icon(Icons.Outlined.DeleteOutline, contentDescription = null, tint = MaterialTheme.colorScheme.error)
                        Spacer(Modifier.width(8.dp))
                        Text(stringResource(R.string.delete), color = MaterialTheme.colorScheme.error)
                    }
                }
                Spacer(Modifier.height(28.dp))
            }
        }
    }
}

@Composable
private fun MemoryMetadataRow(label: String, value: String, error: Boolean = false) {
    Row(Modifier.fillMaxWidth().padding(vertical = 5.dp)) {
        Text(label, modifier = Modifier.width(112.dp), style = MaterialTheme.typography.labelLarge, color = MaterialTheme.colorScheme.onSurfaceVariant)
        Text(value, modifier = Modifier.weight(1f), color = if (error) MaterialTheme.colorScheme.error else MaterialTheme.colorScheme.onSurface)
    }
}

@Composable
private fun MemoryFactEditorSheet(
    state: AppUiState,
    fact: MemoryFact?,
    onDismiss: () -> Unit,
    onSave: (String, String, Double) -> Unit,
) {
    var content by remember(fact?.id) { mutableStateOf(fact?.content.orEmpty()) }
    var category by remember(fact?.id) { mutableStateOf(fact?.category ?: "context") }
    var confidence by remember(fact?.id) { mutableStateOf((fact?.confidence ?: 0.8).toFloat()) }
    ModalBottomSheet(onDismissRequest = onDismiss) {
        LazyColumn(
            modifier = Modifier.fillMaxWidth(),
            contentPadding = PaddingValues(horizontal = 20.dp, vertical = 8.dp),
        ) {
            item {
                Text(stringResource(if (fact == null) R.string.memory_add_fact else R.string.memory_edit_fact), style = MaterialTheme.typography.titleLarge)
                Spacer(Modifier.height(16.dp))
                OutlinedTextField(
                    value = content,
                    onValueChange = { content = it },
                    label = { Text(stringResource(R.string.memory_fact_content)) },
                    minLines = 3,
                    maxLines = 7,
                    modifier = Modifier.fillMaxWidth().testTag(UiTags.MemoryFactContent),
                )
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = category,
                    onValueChange = { category = it },
                    label = { Text(stringResource(R.string.memory_category)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(16.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text(stringResource(R.string.memory_confidence), style = MaterialTheme.typography.titleSmall)
                    Text(confidenceText(confidence.toDouble()), style = MaterialTheme.typography.labelLarge)
                }
                Slider(
                    value = confidence,
                    onValueChange = { confidence = it },
                    valueRange = 0f..1f,
                    steps = 19,
                    modifier = Modifier.fillMaxWidth(),
                )
                Spacer(Modifier.height(18.dp))
                Button(
                    onClick = { onSave(content, category, confidence.toDouble()) },
                    enabled = content.isNotBlank() && !state.memoryMutationBusy,
                    modifier = Modifier.fillMaxWidth().testTag(UiTags.MemoryFactSave),
                ) { Text(stringResource(R.string.save)) }
                Spacer(Modifier.height(28.dp))
            }
        }
    }
}

private data class MemorySummaryItem(
    val title: String,
    val section: MemorySection,
) {
    fun matches(query: String): Boolean = query.isBlank() ||
        title.contains(query, ignoreCase = true) ||
        section.summary.contains(query, ignoreCase = true)
}

private enum class MemoryFilter { All, Facts, Summaries }

@Composable
private fun MemoryFilter.label(): String = stringResource(
    when (this) {
        MemoryFilter.All -> R.string.memory_filter_all
        MemoryFilter.Facts -> R.string.memory_filter_facts
        MemoryFilter.Summaries -> R.string.memory_filter_summaries
    },
)

private fun confidenceText(value: Double): String = NumberFormat.getPercentInstance().apply {
    maximumFractionDigits = 0
}.format(value.coerceIn(0.0, 1.0))
