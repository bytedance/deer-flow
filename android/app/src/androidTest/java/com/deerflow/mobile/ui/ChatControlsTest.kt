package com.deerflow.mobile.ui

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertTextContains
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.onAllNodesWithTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.text.input.TextFieldValue
import androidx.test.core.app.ApplicationProvider
import com.deerflow.mobile.R
import com.deerflow.mobile.data.ChannelCredentialField
import com.deerflow.mobile.data.ChannelProviderInfo
import com.deerflow.mobile.data.ChannelProviders
import com.deerflow.mobile.data.ComposerState
import com.deerflow.mobile.data.ModelInfo
import com.deerflow.mobile.data.McpConfig
import com.deerflow.mobile.data.McpServerInfo
import com.deerflow.mobile.data.RunMode
import com.deerflow.mobile.data.RunOptions
import com.deerflow.mobile.data.RunState
import com.deerflow.mobile.data.RunStatus
import com.deerflow.mobile.data.SkillInfo
import com.deerflow.mobile.data.WorkspaceCapabilities
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class ChatControlsTest {
    @get:Rule val compose = createComposeRule()

    private val context = ApplicationProvider.getApplicationContext<android.content.Context>()

    @Test
    fun modelMenuListsModelsAndDispatchesSelection() {
        var selectedModel = ""
        setTopSelectors(
            state = selectorState(modelName = "pro", mode = RunMode.Thinking),
            onModelSelected = { selectedModel = it.orEmpty() },
        )

        compose.onNodeWithTag(UiTags.ModelSelector).performClick()
        compose.onNodeWithText("DeerFlow Fast").performClick()

        compose.runOnIdle { assertEquals("fast", selectedModel) }
    }

    @Test
    fun runModeMenuDispatchesSupportedMode() {
        var selectedMode: RunMode? = null
        setTopSelectors(
            state = selectorState(modelName = "pro", mode = RunMode.Thinking),
            onModeSelected = { selectedMode = it },
        )

        compose.onNodeWithTag(UiTags.ModeSelector).performClick()
        compose.onNodeWithText(context.getString(R.string.mode_ultra)).performClick()

        compose.runOnIdle { assertEquals(RunMode.Ultra, selectedMode) }
    }

    @Test
    fun quickActionsStayInlineAndApplySelection() {
        var selectedPrompt = ""
        val surprise = context.getString(R.string.quick_surprise)
        val writing = context.getString(R.string.quick_writing)
        val writingPrompt = context.getString(R.string.quick_writing_prompt)
        compose.setContent {
            MaterialTheme {
                CapabilityRow(
                    state = AppUiState(serverUrl = "http://10.0.2.2:2027"),
                    onAgent = {},
                    onQuickAction = { prompt, _ -> selectedPrompt = prompt },
                )
            }
        }

        compose.onNodeWithText(surprise).assertExists()
        compose.onNodeWithText(writing).performClick()

        compose.runOnIdle { assertEquals(writingPrompt, selectedPrompt) }
    }

    @Test
    fun nonThinkingModelExposesFlashOnly() {
        val flash = context.getString(R.string.mode_flash)
        setTopSelectors(state = selectorState(modelName = "fast", mode = RunMode.Flash))

        compose.onNodeWithTag(UiTags.ModeSelector).assertTextContains(flash).performClick()

        compose.onNodeWithText(context.getString(R.string.mode_thinking)).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.mode_plan)).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.mode_ultra)).assertDoesNotExist()
    }

    @Test
    fun attachmentSheetDispatchesEveryEntryPoint() {
        val actions = mutableListOf<String>()
        compose.setContent {
            MaterialTheme {
                AttachmentSheet(
                    onDismiss = {},
                    onCamera = { actions += "camera" },
                    onPhotos = { actions += "photos" },
                    onFiles = { actions += "files" },
                    onSkills = { actions += "skills" },
                )
            }
        }

        compose.onNodeWithText(context.getString(R.string.camera)).performClick()
        compose.onNodeWithText(context.getString(R.string.photos)).performClick()
        compose.onNodeWithText(context.getString(R.string.files)).performClick()
        compose.onNodeWithText(context.getString(R.string.skills)).performClick()

        compose.runOnIdle { assertEquals(listOf("camera", "photos", "files", "skills"), actions) }
    }

    @Test
    fun skillsSheetOpensSkillDetailsWithoutASelectionCheckbox() {
        var selected = ""
        compose.setContent {
            MaterialTheme {
                SkillsSheetContent(
                    skills = listOf(
                        SkillInfo("deep-research", "Investigate sources", "research", enabled = true),
                        SkillInfo("writing-studio", "Draft reports", "writing", enabled = true),
                        SkillInfo("disabled-skill", "Unavailable", "other", enabled = false),
                    ),
                    selectedSkills = setOf("deep-research"),
                    onSkillSelected = {},
                    onSkillDetail = { selected = it.name },
                )
            }
        }

        compose.onNodeWithText("disabled-skill").assertDoesNotExist()
        compose.onNodeWithTag(UiTags.SkillCardPrefix + "writing-studio").performClick()

        compose.runOnIdle { assertEquals("writing-studio", selected) }
    }

    @Test
    fun skillsCatalogSearchesDescriptionsAndOpensDetails() {
        var openedSkill = ""
        compose.setContent {
            MaterialTheme {
                SkillsSheetContent(
                    skills = listOf(
                        SkillInfo("deep-research", "Investigate sources", "research", enabled = true),
                        SkillInfo("writing-studio", "Draft reports", "writing", enabled = true),
                    ),
                    selectedSkills = emptySet(),
                    onSkillSelected = {},
                    onSkillDetail = { openedSkill = it.name },
                )
            }
        }

        compose.onNodeWithTag(UiTags.SkillsSearch).performTextInput("reports")
        compose.onNodeWithTag(UiTags.SkillCardPrefix + "deep-research").assertDoesNotExist()
        compose.onNodeWithTag(UiTags.SkillCardPrefix + "writing-studio").performClick()

        compose.runOnIdle { assertEquals("writing-studio", openedSkill) }
    }

    @Test
    fun skillsAdminCatalogShowsDisabledSkillsAndDispatchesPersistentToggle() {
        var changed: Pair<String, Boolean>? = null
        compose.setContent {
            MaterialTheme {
                SkillsSheetContent(
                    skills = listOf(
                        SkillInfo("disabled-skill", "Unavailable", "other", enabled = false),
                    ),
                    selectedSkills = emptySet(),
                    onSkillSelected = {},
                    showDisabledSkills = true,
                    canManageSkillStates = true,
                    onSkillEnabledChanged = { name, enabled -> changed = name to enabled },
                )
            }
        }

        compose.onNodeWithText("disabled-skill").assertIsDisplayed()
        compose.onNodeWithTag(UiTags.SkillGlobalEnablePrefix + "disabled-skill").performClick()

        compose.runOnIdle { assertEquals("disabled-skill" to true, changed) }
    }

    @Test
    fun mcpSheetListsServersAndDispatchesPersistentToggle() {
        var changed: Pair<String, Boolean>? = null
        compose.setContent {
            MaterialTheme {
                McpSheetContent(
                    config = McpConfig(
                        servers = listOf(
                            McpServerInfo("research-tools", "Research sources", "http", enabled = true, toolOverrides = listOf("search")),
                        ),
                        rawJson = "{}",
                    ),
                    loading = false,
                    mutationBusy = false,
                    onServerEnabledChanged = { name, enabled -> changed = name to enabled },
                )
            }
        }

        compose.onNodeWithTag(UiTags.McpServerPrefix + "research-tools").assertIsDisplayed()
        compose.onNodeWithText("http").assertIsDisplayed()
        compose.onNodeWithText("Tool overrides: search").assertIsDisplayed()
        compose.onNodeWithTag(UiTags.McpServerEnablePrefix + "research-tools").performClick()

        compose.runOnIdle { assertEquals("research-tools" to false, changed) }
    }

    @Test
    fun mcpConfigurationEditorValidatesAndSavesTheFullMaskedDocument() {
        var saved = ""
        compose.setContent {
            MaterialTheme {
                McpConfigEditorContent(
                    config = McpConfig(
                        servers = emptyList(),
                        rawJson = """{"mcp_servers":{"research":{"headers":{"Authorization":"***"}}}}""",
                    ),
                    mutationBusy = false,
                    onBack = {},
                    onSave = { saved = it },
                )
            }
        }

        compose.onNodeWithTag(UiTags.McpConfigEditor).assertIsDisplayed()
        compose.onNodeWithTag(UiTags.McpConfigSave).performClick()

        compose.runOnIdle { assertTrue(saved.contains("Authorization")) }
    }

    @Test
    fun channelsSheetConfiguresAdminProviderAndPreservesMaskedCredentialValues() {
        var configured: Pair<String, Map<String, String>>? = null
        val telegram = ChannelProviderInfo(
            provider = "telegram",
            displayName = "Telegram",
            enabled = true,
            configured = false,
            connectable = false,
            unavailableReason = "Runtime credentials are required.",
            authMode = "deep_link",
            connectionStatus = "not_connected",
            credentialFields = listOf(
                ChannelCredentialField("bot_token", "Bot token", "password", required = true),
                ChannelCredentialField("bot_username", "Bot username", "text", required = true),
            ),
            credentialValues = emptyMap(),
        )
        compose.setContent {
            MaterialTheme {
                ChannelsSheetContent(
                    providers = ChannelProviders(enabled = true, providers = listOf(telegram)),
                    loading = false,
                    mutationBusy = false,
                    isAdmin = true,
                    connection = null,
                    onConfigure = { provider, values -> configured = provider to values },
                    onDisable = {},
                    onConnect = {},
                )
            }
        }

        compose.onNodeWithTag(UiTags.ChannelProviderPrefix + "telegram").assertIsDisplayed()
        compose.onNodeWithTag(UiTags.ChannelConfigurePrefix + "telegram").performClick()
        compose.onNodeWithTag(UiTags.ChannelCredentialPrefix + "bot_token").performTextInput("secret")
        compose.onNodeWithTag(UiTags.ChannelCredentialPrefix + "bot_username").performTextInput("fixture_bot")
        compose.onNodeWithTag(UiTags.ChannelConfigSave).performClick()

        compose.runOnIdle {
            assertEquals("telegram", configured?.first)
            assertEquals("secret", configured?.second?.get("bot_token"))
            assertEquals("fixture_bot", configured?.second?.get("bot_username"))
        }
    }

    @Test
    fun channelsSheetDispatchesConnectAndAdminDisableActions() {
        var connected = ""
        var disabled = ""
        val slack = ChannelProviderInfo(
            provider = "slack",
            displayName = "Slack",
            enabled = true,
            configured = true,
            connectable = true,
            unavailableReason = null,
            authMode = "binding_code",
            connectionStatus = "not_connected",
            credentialFields = emptyList(),
            credentialValues = emptyMap(),
        )
        compose.setContent {
            MaterialTheme {
                ChannelsSheetContent(
                    providers = ChannelProviders(enabled = true, providers = listOf(slack)),
                    loading = false,
                    mutationBusy = false,
                    isAdmin = true,
                    connection = null,
                    onConfigure = { _, _ -> },
                    onDisable = { disabled = it },
                    onConnect = { connected = it },
                )
            }
        }

        compose.onNodeWithTag(UiTags.ChannelConnectPrefix + "slack").performClick()
        compose.onNodeWithTag(UiTags.ChannelDisablePrefix + "slack").performClick()

        compose.runOnIdle {
            assertEquals("slack", connected)
            assertEquals("slack", disabled)
        }
    }

    @Test
    fun skillDetailShowsMetadataAndDispatchesSelection() {
        var selected = ""
        compose.setContent {
            MaterialTheme {
                SkillDetailContent(
                    skill = SkillInfo("deep-research", "Investigate sources", "research", enabled = true),
                    selected = false,
                    onBack = {},
                    onSkillSelected = { selected = it },
                )
            }
        }

        compose.onNodeWithTag(UiTags.SkillDetailScreen).assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.skill_category)).assertIsDisplayed()
        compose.onNodeWithText("research").assertIsDisplayed()
        compose.onNodeWithTag(UiTags.SkillDetailSelect).performClick()

        compose.runOnIdle { assertEquals("deep-research", selected) }
    }

    @Test
    fun quickActionRemainsAvailableForNonEmptyComposer() {
        var prompt = ""
        var keywords = emptyList<String>()
        val state = AppUiState(
            serverUrl = "http://10.0.2.2:2027",
            composer = ComposerState(text = "Existing draft"),
            capabilities = WorkspaceCapabilities(
                skills = listOf(SkillInfo("deep-research", "Research reports", "research", enabled = true)),
            ),
        )
        compose.setContent {
            MaterialTheme {
                CapabilityRow(
                    state = state,
                    onAgent = {},
                    onQuickAction = { selectedPrompt, selectedKeywords ->
                        prompt = selectedPrompt
                        keywords = selectedKeywords
                    },
                )
            }
        }

        compose.onNodeWithText(context.getString(R.string.quick_research)).performClick()

        compose.runOnIdle {
            assertEquals(context.getString(R.string.quick_research_prompt), prompt)
            assertTrue("research" in keywords)
        }
    }

    @Test
    fun composerSendsNonEmptyDraftAndDisablesBlankSend() {
        var sends = 0
        var state by mutableStateOf(
            AppUiState(
                serverUrl = "http://10.0.2.2:2027",
                composer = ComposerState(text = "Send this"),
            ),
        )
        compose.setContent {
            MaterialTheme {
                TestComposer(
                    state = state,
                    editorValue = TextFieldValue(state.composer.text),
                    onSend = { sends += 1 },
                )
            }
        }

        compose.onNodeWithTag(UiTags.SendStopButton).assertIsEnabled().performClick()
        compose.runOnIdle {
            assertEquals(1, sends)
            state = AppUiState(serverUrl = "http://10.0.2.2:2027")
        }
        compose.waitForIdle()
        compose.onNodeWithTag(UiTags.SendStopButton).assertIsNotEnabled()
    }

    @Test
    fun composerStopsAnActiveRunEvenWhenDraftIsEmpty() {
        var stops = 0
        setComposer(
            state = AppUiState(
                serverUrl = "http://10.0.2.2:2027",
                run = RunState(RunStatus.Streaming, runId = "run-1"),
            ),
            onStop = { stops += 1 },
        )

        compose.onNodeWithTag(UiTags.SendStopButton).assertIsEnabled().performClick()
        compose.runOnIdle { assertEquals(1, stops) }
    }

    @Test
    fun restoredReconnectStateKeepsStopAvailableWithoutFloatingIndicator() {
        var stops = 0
        setComposer(
            state = AppUiState(
                serverUrl = "http://10.0.2.2:2027",
                run = RunState(
                    status = RunStatus.Reconnecting,
                    runId = "restored-run",
                    lastEventId = "event-7",
                    reconnectAttempt = 2,
                ),
            ),
            onStop = { stops += 1 },
        )

        compose.onNodeWithText(context.getString(R.string.run_reconnecting)).assertDoesNotExist()
        compose.onNodeWithTag(UiTags.SendStopButton).assertIsEnabled().performClick()
        compose.runOnIdle { assertEquals(1, stops) }
    }

    private fun setTopSelectors(
        state: AppUiState,
        onModelSelected: (String?) -> Unit = {},
        onModeSelected: (RunMode) -> Unit = {},
    ) {
        compose.setContent {
            var expanded by remember { mutableStateOf<TopSelectorKind?>(null) }
            MaterialTheme {
                ChatTopSelectors(
                    state = state,
                    expandedSelector = expanded,
                    onExpandedSelectorChange = { expanded = it },
                    onModelSelected = onModelSelected,
                    onModeSelected = onModeSelected,
                )
            }
        }
    }

    private fun setComposer(
        state: AppUiState,
        editorValue: TextFieldValue = TextFieldValue(state.composer.text),
        onSend: () -> Unit = {},
        onStop: () -> Unit = {},
    ) {
        compose.setContent {
            MaterialTheme {
                TestComposer(state, editorValue, onSend, onStop)
            }
        }
    }

    @androidx.compose.runtime.Composable
    private fun TestComposer(
        state: AppUiState,
        editorValue: TextFieldValue,
        onSend: () -> Unit = {},
        onStop: () -> Unit = {},
    ) {
        MessageComposer(
            state = state,
            editorValue = editorValue,
            onDraftChange = {},
            onAttachment = {},
            onAgent = {},
            onQuickAction = { _, _ -> },
            onRemoveAttachment = {},
            onRetryAttachment = {},
            onSend = onSend,
            onStop = onStop,
        )
    }

    private fun selectorState(modelName: String, mode: RunMode): AppUiState = AppUiState(
        serverUrl = "http://10.0.2.2:2027",
        composer = ComposerState(options = RunOptions(modelName = modelName, mode = mode)),
        capabilities = WorkspaceCapabilities(
            models = listOf(
                ModelInfo("fast", "DeerFlow Fast", "Fast", supportsThinking = false, supportsReasoningEffort = false),
                ModelInfo("pro", "DeerFlow Pro", "Pro", supportsThinking = true, supportsReasoningEffort = true),
            ),
        ),
    )
}
