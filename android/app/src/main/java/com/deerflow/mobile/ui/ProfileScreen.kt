@file:OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)

package com.deerflow.mobile.ui

import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import android.text.format.Formatter
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.selection.selectable
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.ArrowBack
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material.icons.outlined.CleaningServices
import androidx.compose.material.icons.outlined.DarkMode
import androidx.compose.material.icons.outlined.Info
import androidx.compose.material.icons.outlined.Language
import androidx.compose.material.icons.outlined.Link
import androidx.compose.material.icons.outlined.Menu
import androidx.compose.material.icons.outlined.Notifications
import androidx.compose.material.icons.outlined.Palette
import androidx.compose.material.icons.outlined.PersonOutline
import androidx.compose.material.icons.outlined.Policy
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Button
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.ListItem
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.RadioButton
import androidx.compose.material3.SegmentedButton
import androidx.compose.material3.SegmentedButtonDefaults
import androidx.compose.material3.SingleChoiceSegmentedButtonRow
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.deerflow.mobile.BuildConfig
import com.deerflow.mobile.R
import com.deerflow.mobile.data.CacheRetentionPolicy
import com.deerflow.mobile.data.LanguagePreference
import com.deerflow.mobile.data.ThemePreference
import com.deerflow.mobile.data.parseThirdPartyLicenseNotices

@Composable
fun ProfileScreen(
    state: AppUiState,
    viewModel: AppViewModel,
    onBack: () -> Unit,
    contentPadding: PaddingValues,
) {
    val context = LocalContext.current
    var showChannels by remember { mutableStateOf(false) }
    LaunchedEffect(Unit) { viewModel.refreshCacheStats() }
    ProfileContent(
        state = state,
        onBack = onBack,
        onSaveServerUrl = viewModel::saveServerUrl,
        onThemeSelected = viewModel::setTheme,
        onDynamicColorChanged = viewModel::setDynamicColor,
        onLanguageSelected = viewModel::setLanguage,
        onNotifyOnRunCompletionChanged = viewModel::setNotifyOnRunCompletion,
        onCacheRetentionPolicySelected = viewModel::setCacheRetentionPolicy,
        onRefreshCacheStats = viewModel::refreshCacheStats,
        onClearCache = viewModel::clearCache,
        onSignOut = viewModel::logout,
        onOpenChannels = {
            viewModel.refreshChannels()
            showChannels = true
        },
        onOpenSourceLicenses = {},
        onOpenSourceCode = {
            context.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(SOURCE_CODE_URL)))
        },
        contentPadding = contentPadding,
    )
    if (showChannels) {
        ChannelsSheet(state, viewModel, onDismiss = { showChannels = false })
    }
}

@Composable
internal fun ProfileContent(
    state: AppUiState,
    onBack: () -> Unit,
    onSaveServerUrl: (String) -> Unit,
    onThemeSelected: (ThemePreference) -> Unit,
    onDynamicColorChanged: (Boolean) -> Unit,
    onLanguageSelected: (LanguagePreference) -> Unit,
    onNotifyOnRunCompletionChanged: (Boolean) -> Unit,
    onCacheRetentionPolicySelected: (CacheRetentionPolicy) -> Unit,
    onRefreshCacheStats: () -> Unit,
    onClearCache: () -> Unit,
    onSignOut: () -> Unit,
    onOpenChannels: () -> Unit = {},
    onOpenSourceLicenses: () -> Unit,
    onOpenSourceCode: () -> Unit,
    contentPadding: PaddingValues = PaddingValues(),
) {
    var serverUrl by rememberSaveable(state.serverUrl) { mutableStateOf(state.serverUrl) }
    var showLanguageDialog by rememberSaveable { mutableStateOf(false) }
    var showCachePolicyDialog by rememberSaveable { mutableStateOf(false) }
    var showClearCacheDialog by rememberSaveable { mutableStateOf(false) }
    var showAbout by rememberSaveable { mutableStateOf(false) }
    var showDeerFlowLicense by rememberSaveable { mutableStateOf(false) }
    var showThirdPartyLicenses by rememberSaveable { mutableStateOf(false) }
    var showServerDialog by rememberSaveable { mutableStateOf(false) }

    BackHandler(enabled = showAbout || showThirdPartyLicenses) {
        if (showThirdPartyLicenses) showThirdPartyLicenses = false else showAbout = false
    }
    if (showThirdPartyLicenses) {
        ThirdPartyLicensesScreen(onBack = { showThirdPartyLicenses = false }, contentPadding = contentPadding)
    } else if (showAbout) {
        AboutScreen(
            onBack = { showAbout = false },
            onOpenDeerFlowLicense = { showDeerFlowLicense = true },
            onOpenSourceLicenses = {
                showThirdPartyLicenses = true
                onOpenSourceLicenses()
            },
            onOpenSourceCode = onOpenSourceCode,
            contentPadding = contentPadding,
        )
    } else {
        Column(Modifier.fillMaxSize().padding(contentPadding).testTag(UiTags.ProfileScreen)) {
            TopAppBar(
                navigationIcon = {
                    IconButton(onClick = onBack, modifier = Modifier.size(48.dp)) {
                        Icon(Icons.Outlined.ArrowBack, contentDescription = stringResource(R.string.back))
                    }
                },
                title = { Text(stringResource(R.string.profile_title)) },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
            )
            LazyColumn(
                modifier = Modifier.fillMaxSize().navigationBarsPadding().testTag(UiTags.ProfileList),
                contentPadding = PaddingValues(horizontal = 20.dp, vertical = 16.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                item {
                    ProfileSection {
                        SettingsSectionTitle(R.string.account)
                        ListItem(
                            headlineContent = { Text(state.user?.email.orEmpty()) },
                            supportingContent = { Text(state.user?.role.orEmpty()) },
                            leadingContent = { Icon(Icons.Outlined.PersonOutline, contentDescription = null) },
                        )
                    }
                }
                item {
                    ProfileSection {
                        SettingsDivider()
                        SettingsSectionTitle(R.string.connection)
                        ListItem(
                            headlineContent = { Text(stringResource(R.string.server_address)) },
                            supportingContent = { Text(serverUrl) },
                            leadingContent = { Icon(Icons.Outlined.Link, contentDescription = null) },
                            trailingContent = { Icon(Icons.Outlined.ChevronRight, contentDescription = null) },
                            modifier = Modifier.fillMaxWidth().clickable { showServerDialog = true }.testTag(UiTags.ProfileServer),
                        )
                        ListItem(
                            headlineContent = { Text(stringResource(R.string.channels)) },
                            leadingContent = { Icon(Icons.Outlined.Link, contentDescription = null) },
                            trailingContent = { Icon(Icons.Outlined.ChevronRight, contentDescription = null) },
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable(onClick = onOpenChannels)
                                .testTag(UiTags.ProfileChannels),
                        )
                    }
                }
                item {
                    ProfileSection {
                        SettingsDivider()
                        SettingsSectionTitle(R.string.preferences)
                        SingleChoiceSegmentedButtonRow(Modifier.fillMaxWidth().padding(vertical = 8.dp)) {
                            ThemePreference.entries.forEachIndexed { index, preference ->
                                SegmentedButton(
                                    selected = state.theme == preference,
                                    onClick = { onThemeSelected(preference) },
                                    shape = SegmentedButtonDefaults.itemShape(index, ThemePreference.entries.size),
                                    label = { Text(preference.label()) },
                                    modifier = Modifier.testTag(UiTags.ProfileThemePrefix + preference.name),
                                )
                            }
                        }
                        ListItem(
                            headlineContent = { Text(stringResource(R.string.dynamic_color)) },
                            supportingContent = { Text(stringResource(R.string.dynamic_color_subtitle)) },
                            leadingContent = { Icon(Icons.Outlined.Palette, contentDescription = null) },
                            trailingContent = {
                                Switch(
                                    checked = state.useDynamicColor,
                                    onCheckedChange = onDynamicColorChanged,
                                )
                            },
                        )
                        ListItem(
                            headlineContent = { Text(stringResource(R.string.language)) },
                            supportingContent = { Text(state.language.label()) },
                            leadingContent = { Icon(Icons.Outlined.Language, contentDescription = null) },
                            trailingContent = { Icon(Icons.Outlined.ChevronRight, contentDescription = null) },
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { showLanguageDialog = true }
                                .testTag(UiTags.ProfileLanguage),
                        )
                    }
                }
                item {
                    ProfileSection {
                        SettingsDivider()
                        SettingsSectionTitle(R.string.notifications)
                        ListItem(
                            headlineContent = { Text(stringResource(R.string.run_completion_notifications)) },
                            supportingContent = { Text(stringResource(R.string.run_completion_notifications_subtitle)) },
                            leadingContent = { Icon(Icons.Outlined.Notifications, contentDescription = null) },
                            trailingContent = {
                                Switch(
                                    checked = state.notifyOnRunCompletion,
                                    onCheckedChange = onNotifyOnRunCompletionChanged,
                                    modifier = Modifier.testTag(UiTags.ProfileNotifications),
                                )
                            },
                        )
                        LiveUpdateSettingsItem()
                    }
                }
                item {
                    ProfileSection {
                        SettingsDivider()
                        SettingsSectionTitle(R.string.storage)
                        ListItem(
                            headlineContent = { Text(stringResource(R.string.cached_data)) },
                            supportingContent = {
                                val size = Formatter.formatShortFileSize(LocalContext.current, state.cacheStats.bytesOnDisk)
                                Text(
                                    if (state.loadingCacheStats) {
                                        stringResource(R.string.loading)
                                    } else {
                                        stringResource(R.string.cache_summary, state.cacheStats.itemCount, size)
                                    },
                                )
                            },
                            leadingContent = { Icon(Icons.Outlined.Storage, contentDescription = null) },
                            trailingContent = {
                                IconButton(
                                    onClick = onRefreshCacheStats,
                                    enabled = !state.loadingCacheStats && !state.clearingCache,
                                    modifier = Modifier.size(48.dp).testTag(UiTags.ProfileCacheRefresh),
                                ) {
                                    if (state.loadingCacheStats) {
                                        CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp)
                                    } else {
                                        Icon(Icons.Outlined.Refresh, contentDescription = stringResource(R.string.refresh))
                                    }
                                }
                            },
                        )
                        ListItem(
                            headlineContent = { Text(stringResource(R.string.cache_retention)) },
                            supportingContent = { Text(state.cacheRetentionPolicy.label()) },
                            leadingContent = { Icon(Icons.Outlined.Policy, contentDescription = null) },
                            trailingContent = { Icon(Icons.Outlined.ChevronRight, contentDescription = null) },
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { showCachePolicyDialog = true }
                                .testTag(UiTags.ProfileCachePolicy),
                        )
                        ListItem(
                            headlineContent = { Text(stringResource(R.string.clear_cached_data)) },
                            supportingContent = {
                                if (state.run.active) Text(stringResource(R.string.clear_cache_run_active))
                            },
                            leadingContent = { Icon(Icons.Outlined.CleaningServices, contentDescription = null) },
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable(enabled = !state.run.active && !state.clearingCache) {
                                    showClearCacheDialog = true
                                }
                                .testTag(UiTags.ProfileCacheClear),
                        )
                    }
                }
                item {
                    ProfileSection {
                        SettingsDivider()
                        SettingsSectionTitle(R.string.about_title)
                        ListItem(
                            headlineContent = { Text(stringResource(R.string.about_deerflow)) },
                            supportingContent = { Text(stringResource(R.string.version, BuildConfig.VERSION_NAME)) },
                            leadingContent = { Icon(Icons.Outlined.Info, contentDescription = null) },
                            trailingContent = { Icon(Icons.Outlined.ChevronRight, contentDescription = null) },
                            modifier = Modifier
                                .fillMaxWidth()
                                .clickable { showAbout = true }
                                .testTag(UiTags.ProfileAbout),
                        )
                        SettingsDivider()
                        OutlinedButton(onClick = onSignOut, modifier = Modifier.fillMaxWidth()) {
                            Text(stringResource(R.string.sign_out))
                        }
                    }
                }
            }
        }
    }

    if (showLanguageDialog) {
        SingleChoiceDialog(
            title = stringResource(R.string.language),
            values = LanguagePreference.entries,
            selected = state.language,
            label = { it.label() },
            tag = { UiTags.ProfileLanguageOptionPrefix + it.name },
            onSelect = {
                showLanguageDialog = false
                onLanguageSelected(it)
            },
            onDismiss = { showLanguageDialog = false },
        )
    }
    if (showServerDialog) {
        AlertDialog(
            onDismissRequest = { showServerDialog = false },
            title = { Text(stringResource(R.string.server_address)) },
            text = {
                OutlinedTextField(
                    value = serverUrl,
                    onValueChange = { serverUrl = it },
                    label = { Text(stringResource(R.string.server_address)) },
                    singleLine = true,
                    modifier = Modifier.fillMaxWidth(),
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    showServerDialog = false
                    onSaveServerUrl(serverUrl)
                }) { Text(stringResource(R.string.save_reconnect)) }
            },
            dismissButton = { TextButton(onClick = { showServerDialog = false }) { Text(stringResource(R.string.cancel)) } },
        )
    }
    if (showCachePolicyDialog) {
        SingleChoiceDialog(
            title = stringResource(R.string.cache_retention),
            values = CacheRetentionPolicy.entries,
            selected = state.cacheRetentionPolicy,
            label = { it.label() },
            tag = { UiTags.ProfileCachePolicyOptionPrefix + it.name },
            onSelect = {
                showCachePolicyDialog = false
                onCacheRetentionPolicySelected(it)
            },
            onDismiss = { showCachePolicyDialog = false },
        )
    }
    if (showClearCacheDialog) {
        AlertDialog(
            onDismissRequest = { showClearCacheDialog = false },
            title = { Text(stringResource(R.string.clear_cache_title)) },
            text = { Text(stringResource(R.string.clear_cache_body)) },
            confirmButton = {
                TextButton(
                    onClick = {
                        showClearCacheDialog = false
                        onClearCache()
                    },
                    modifier = Modifier.testTag(UiTags.ProfileCacheClearConfirm),
                ) { Text(stringResource(R.string.clear_cached_data)) }
            },
            dismissButton = {
                TextButton(onClick = { showClearCacheDialog = false }) {
                    Text(stringResource(R.string.cancel))
                }
            },
        )
    }
    if (showDeerFlowLicense) {
        DeerFlowLicenseDialog(onDismiss = { showDeerFlowLicense = false })
    }
}

@Composable
private fun AboutScreen(
    onBack: () -> Unit,
    onOpenDeerFlowLicense: () -> Unit,
    onOpenSourceLicenses: () -> Unit,
    onOpenSourceCode: () -> Unit,
    contentPadding: PaddingValues,
) {
    Column(Modifier.fillMaxSize().padding(contentPadding).testTag(UiTags.AboutScreen)) {
        TopAppBar(
            navigationIcon = {
                IconButton(onClick = onBack, modifier = Modifier.size(48.dp).testTag(UiTags.AboutBack)) {
                    Icon(Icons.Outlined.ArrowBack, contentDescription = stringResource(R.string.back))
                }
            },
            title = { Text(stringResource(R.string.about_title)) },
            colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
        )
        LazyColumn(
            modifier = Modifier.fillMaxSize().navigationBarsPadding(),
            contentPadding = PaddingValues(horizontal = 20.dp, vertical = 20.dp),
            horizontalAlignment = Alignment.CenterHorizontally,
        ) {
            item {
                Column(Modifier.widthIn(max = 680.dp).fillMaxWidth()) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        BrandMark()
                        Spacer(Modifier.weight(1f))
                    }
                    Spacer(Modifier.height(24.dp))
                    Text(stringResource(R.string.version, BuildConfig.VERSION_NAME), style = MaterialTheme.typography.titleMedium)
                    Text(
                        stringResource(R.string.build_number, BuildConfig.VERSION_CODE),
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    Text(
                        BuildConfig.APPLICATION_ID,
                        style = MaterialTheme.typography.bodyMedium,
                        color = MaterialTheme.colorScheme.onSurfaceVariant,
                    )
                    SettingsDivider()
                    ListItem(
                        headlineContent = { Text(stringResource(R.string.deerflow_license)) },
                        supportingContent = { Text(stringResource(R.string.mit_license)) },
                        leadingContent = { Icon(Icons.Outlined.Policy, contentDescription = null) },
                        trailingContent = { Icon(Icons.Outlined.ChevronRight, contentDescription = null) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable(onClick = onOpenDeerFlowLicense)
                            .testTag(UiTags.AboutDeerFlowLicense),
                    )
                    ListItem(
                        headlineContent = { Text(stringResource(R.string.open_source_licenses)) },
                        supportingContent = { Text(stringResource(R.string.open_source_licenses_subtitle)) },
                        leadingContent = { Icon(Icons.Outlined.Info, contentDescription = null) },
                        trailingContent = { Icon(Icons.Outlined.ChevronRight, contentDescription = null) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable(onClick = onOpenSourceLicenses)
                            .testTag(UiTags.AboutOpenSourceLicenses),
                    )
                    ListItem(
                        headlineContent = { Text(stringResource(R.string.source_code)) },
                        supportingContent = { Text(SOURCE_CODE_URL) },
                        leadingContent = { Icon(Icons.Outlined.Info, contentDescription = null) },
                        trailingContent = { Icon(Icons.Outlined.ChevronRight, contentDescription = null) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .clickable(onClick = onOpenSourceCode)
                            .testTag(UiTags.AboutSourceCode),
                    )
                }
            }
        }
    }
}

@Composable
private fun DeerFlowLicenseDialog(onDismiss: () -> Unit) {
    val context = LocalContext.current
    val license = remember {
        context.resources.openRawResource(R.raw.deerflow_license).bufferedReader().use { it.readText() }
    }
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(stringResource(R.string.deerflow_license)) },
        text = {
            Text(
                license,
                modifier = Modifier.heightIn(max = 460.dp).verticalScroll(rememberScrollState()),
                style = MaterialTheme.typography.bodySmall,
            )
        },
        confirmButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.close)) } },
        modifier = Modifier.testTag(UiTags.AboutLicenseDialog),
    )
}

@Composable
private fun ThirdPartyLicensesScreen(onBack: () -> Unit, contentPadding: PaddingValues) {
    val context = LocalContext.current
    val notices = remember {
        runCatching {
            val metadata = context.resources.openRawResource(R.raw.third_party_license_metadata)
                .bufferedReader().use { it.readText() }
            val text = context.resources.openRawResource(R.raw.third_party_licenses)
                .bufferedReader().use { it.readText() }
            parseThirdPartyLicenseNotices(metadata, text)
        }.getOrDefault(emptyList())
    }
    Column(Modifier.fillMaxSize().padding(contentPadding).testTag(UiTags.ThirdPartyLicensesScreen)) {
        TopAppBar(
            navigationIcon = {
                IconButton(onClick = onBack, modifier = Modifier.size(48.dp)) {
                    Icon(Icons.Outlined.ArrowBack, contentDescription = stringResource(R.string.back))
                }
            },
            title = { Text(stringResource(R.string.open_source_licenses)) },
            colors = TopAppBarDefaults.topAppBarColors(containerColor = MaterialTheme.colorScheme.background),
        )
        LazyColumn(
            modifier = Modifier.fillMaxSize().navigationBarsPadding(),
            contentPadding = PaddingValues(horizontal = 20.dp, vertical = 12.dp),
        ) {
            notices.forEach { notice ->
                item(key = notice.name) {
                    Text(notice.name, style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(top = 12.dp))
                    Text(notice.text, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(top = 4.dp))
                    HorizontalDivider(Modifier.padding(top = 12.dp))
                }
            }
            if (notices.isEmpty()) {
                item { Text(stringResource(R.string.licenses_unavailable)) }
            }
        }
    }
}

@Composable
private fun LiveUpdateSettingsItem() {
    val context = LocalContext.current
    val notifications = context.getSystemService(android.app.NotificationManager::class.java)
    val promotedAvailable = Build.VERSION.SDK_INT >= 36 && notifications.canPostPromotedNotifications()
    val status = if (promotedAvailable) {
        stringResource(R.string.live_updates_available)
    } else {
        stringResource(R.string.live_updates_unavailable)
    }
    ListItem(
        headlineContent = { Text(stringResource(R.string.live_updates)) },
        supportingContent = { Text(status) },
        leadingContent = { Icon(Icons.Outlined.Notifications, contentDescription = null) },
        trailingContent = { Icon(Icons.Outlined.ChevronRight, contentDescription = null) },
        modifier = Modifier.fillMaxWidth().clickable {
            context.startActivity(
                Intent(Settings.ACTION_APP_NOTIFICATION_SETTINGS)
                    .putExtra(Settings.EXTRA_APP_PACKAGE, context.packageName),
            )
        },
    )
}

@Composable
private fun <T> SingleChoiceDialog(
    title: String,
    values: List<T>,
    selected: T,
    label: @Composable (T) -> String,
    tag: (T) -> String,
    onSelect: (T) -> Unit,
    onDismiss: () -> Unit,
) {
    AlertDialog(
        onDismissRequest = onDismiss,
        title = { Text(title) },
        text = {
            Column {
                values.forEach { value ->
                    ListItem(
                        headlineContent = { Text(label(value)) },
                        leadingContent = { RadioButton(selected = selected == value, onClick = null) },
                        modifier = Modifier
                            .fillMaxWidth()
                            .selectable(selected = selected == value, onClick = { onSelect(value) })
                            .testTag(tag(value)),
                    )
                }
            }
        },
        confirmButton = {},
        dismissButton = { TextButton(onClick = onDismiss) { Text(stringResource(R.string.cancel)) } },
    )
}

@Composable
private fun ProfileSection(content: @Composable () -> Unit) {
    Column(Modifier.widthIn(max = 680.dp).fillMaxWidth()) {
        content()
    }
}

@Composable
private fun SettingsSectionTitle(resourceId: Int) {
    Text(stringResource(resourceId), style = MaterialTheme.typography.titleMedium)
}

@Composable
private fun SettingsDivider() {
    HorizontalDivider(Modifier.padding(vertical = 8.dp))
}

@Composable
private fun ThemePreference.label(): String = when (this) {
    ThemePreference.System -> stringResource(R.string.theme_system)
    ThemePreference.Light -> stringResource(R.string.theme_light)
    ThemePreference.Dark -> stringResource(R.string.theme_dark)
}

@Composable
private fun LanguagePreference.label(): String = when (this) {
    LanguagePreference.System -> stringResource(R.string.language_system)
    LanguagePreference.English -> stringResource(R.string.language_english)
    LanguagePreference.SimplifiedChinese -> stringResource(R.string.language_simplified_chinese)
}

@Composable
private fun CacheRetentionPolicy.label(): String = when (this) {
    CacheRetentionPolicy.KeepUntilCleared -> stringResource(R.string.cache_keep_until_cleared)
    CacheRetentionPolicy.ClearOnSignOut -> stringResource(R.string.cache_clear_on_sign_out)
}

private const val SOURCE_CODE_URL = "https://github.com/bytedance/deer-flow"
