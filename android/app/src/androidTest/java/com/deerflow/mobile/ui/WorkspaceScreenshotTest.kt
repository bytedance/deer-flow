package com.deerflow.mobile.ui

import android.content.Context
import android.content.res.Configuration
import android.graphics.Bitmap
import android.util.Log
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.requiredSize
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.text.input.TextFieldValue
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import com.deerflow.mobile.data.ChatMessage
import com.deerflow.mobile.data.ChatMessageGroup
import com.deerflow.mobile.data.ComposerState
import com.deerflow.mobile.data.DeerFlowUser
import com.deerflow.mobile.data.MessageRole
import com.deerflow.mobile.data.ModelInfo
import com.deerflow.mobile.data.RunMode
import com.deerflow.mobile.data.RunOptions
import com.deerflow.mobile.data.SkillInfo
import com.deerflow.mobile.data.ThemePreference
import com.deerflow.mobile.data.ThreadSummary
import com.deerflow.mobile.data.TodoItem
import com.deerflow.mobile.data.WorkspaceCapabilities
import com.deerflow.mobile.ui.theme.DeerFlowTheme
import java.io.File
import java.io.FileOutputStream
import java.util.Locale
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class WorkspaceScreenshotTest {
    @get:Rule val compose = createComposeRule()

    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val targetContext = instrumentation.targetContext

    @Test
    fun phone360LightEnglishMatchesBaseline() = captureScenario(Scenario.Phone360LightEnglish)

    @Test
    fun phone412DarkEnglishMatchesBaseline() = captureScenario(Scenario.Phone412DarkEnglish)

    @Test
    fun foldableLightEnglishMatchesBaseline() = captureScenario(Scenario.FoldableLightEnglish)

    @Test
    fun tabletLightEnglishMatchesBaseline() = captureScenario(Scenario.TabletLightEnglish)

    @Test
    fun phone412DynamicEnglishMatchesBaseline() = captureScenario(Scenario.Phone412DynamicEnglish)

    @Test
    fun phone360LightChineseMatchesBaseline() = captureScenario(Scenario.Phone360LightChinese)

    @Test
    fun phone360LightLargeTextMatchesBaseline() = captureScenario(Scenario.Phone360LightLargeText)

    private fun captureScenario(scenario: Scenario) {
        val localizedContext = localizedContext(scenario.locale, scenario.widthDp, scenario.heightDp, scenario.fontScale)
        val configuration = localizedContext.resources.configuration
        compose.setContent {
            CompositionLocalProvider(
                LocalContext provides localizedContext,
                LocalConfiguration provides configuration,
                LocalDensity provides Density(density = 1f, fontScale = scenario.fontScale),
                androidx.compose.ui.platform.LocalLayoutDirection provides LayoutDirection.Ltr,
            ) {
                DeerFlowTheme(
                    preference = scenario.theme,
                    useDynamicColor = scenario.dynamicColor,
                ) {
                    Box(
                        modifier = Modifier
                            .requiredSize(scenario.widthDp.dp, scenario.heightDp.dp)
                            .testTag(SCREENSHOT_ROOT_TAG),
                    ) {
                        WorkspaceScreenshotScene(
                            state = screenshotState(),
                            expanded = scenario.widthDp >= TABLET_BREAKPOINT_DP,
                        )
                    }
                }
            }
        }

        compose.waitForIdle()
        compose.onNodeWithTag(UiTags.ComposerInput).assertExists()

        val image = compose.onNodeWithTag(SCREENSHOT_ROOT_TAG).captureToImage()
        assertEquals(scenario.widthDp, image.width)
        assertEquals(scenario.heightDp, image.height)

        val signature = image.visualSignature()
        writePng(scenario, image)
        if (recordingBaselines) {
            Log.i(BASELINE_LOG_TAG, "${scenario.id}=$signature")
            return
        }

        val expected = BASELINES[scenario.id]
            ?: error("Missing visual baseline for ${scenario.id}. Run with -e $RECORD_ARG true")
        val difference = expected.zip(signature).count { (expectedDigit, actualDigit) -> expectedDigit != actualDigit }
        assertTrue(
            "${scenario.id} visual signature differs by $difference digits (allowed $MAX_SIGNATURE_DIFFERENCE). " +
                "expected=$expected actual=$signature",
            difference <= MAX_SIGNATURE_DIFFERENCE,
        )
    }

    private val recordingBaselines: Boolean
        get() = InstrumentationRegistry.getArguments().getString(RECORD_ARG).equals("true", ignoreCase = true)

    private fun localizedContext(locale: Locale, widthDp: Int, heightDp: Int, fontScale: Float): Context {
        val configuration = Configuration(targetContext.resources.configuration).apply {
            setLocale(locale)
            screenWidthDp = widthDp
            screenHeightDp = heightDp
            this.fontScale = fontScale
        }
        return targetContext.createConfigurationContext(configuration)
    }

    private fun writePng(scenario: Scenario, image: ImageBitmap) {
        val outputDirectory = File(targetContext.getExternalFilesDir(null), OUTPUT_DIRECTORY).apply { mkdirs() }
        FileOutputStream(File(outputDirectory, "${scenario.id}.png")).use { stream ->
            check(image.asAndroidBitmap().compress(Bitmap.CompressFormat.PNG, 100, stream))
        }
    }

    private fun ImageBitmap.visualSignature(): String = buildString {
        val bitmap = asAndroidBitmap()
        repeat(SIGNATURE_GRID_SIZE) { row ->
            repeat(SIGNATURE_GRID_SIZE) { column ->
                val pixel = bitmap.getPixel(
                    ((column + 0.5f) * bitmap.width / SIGNATURE_GRID_SIZE).toInt().coerceIn(0, bitmap.width - 1),
                    ((row + 0.5f) * bitmap.height / SIGNATURE_GRID_SIZE).toInt().coerceIn(0, bitmap.height - 1),
                )
                append(COLOR_DIGITS[android.graphics.Color.red(pixel) / COLOR_BUCKET_SIZE])
                append(COLOR_DIGITS[android.graphics.Color.green(pixel) / COLOR_BUCKET_SIZE])
                append(COLOR_DIGITS[android.graphics.Color.blue(pixel) / COLOR_BUCKET_SIZE])
            }
        }
    }

    @Composable
    private fun WorkspaceScreenshotScene(state: AppUiState, expanded: Boolean) {
        if (expanded) {
            Row(Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)) {
                Box(Modifier.width(320.dp).fillMaxHeight()) {
                    WorkspaceDrawer(
                        state = state,
                        onNewChat = {},
                        onOpenThread = {},
                        onRenameThread = { _, _ -> },
                        onDeleteThread = {},
                        onPinThread = {},
                        onDestination = {},
                    )
                }
                ConversationSnapshot(
                    state = state,
                    modifier = Modifier.weight(1f).fillMaxHeight(),
                )
            }
        } else {
            ConversationSnapshot(state = state, modifier = Modifier.fillMaxSize())
        }
    }

    @Composable
    private fun ConversationSnapshot(state: AppUiState, modifier: Modifier) {
        var expandedSelector by remember { mutableStateOf<TopSelectorKind?>(null) }
        Column(modifier.background(MaterialTheme.colorScheme.background)) {
            ChatTopBar(
                state = state,
                onOpenDrawer = {},
                onBack = {},
                onModelSelected = {},
                onModeSelected = {},
                onExport = {},
                expandedSelector = expandedSelector,
                onExpandedSelectorChange = { expandedSelector = it },
            )
            HorizontalDivider()
            LazyColumn(
                modifier = Modifier.weight(1f),
                contentPadding = PaddingValues(horizontal = 16.dp, vertical = 18.dp),
                verticalArrangement = androidx.compose.foundation.layout.Arrangement.spacedBy(14.dp),
            ) {
                items(snapshotGroups(), key = { it.key }) { group ->
                    ChatMessageGroupItem(
                        group = group,
                        runActive = false,
                        onHumanInput = { _, _, _ -> },
                    )
                }
                item { TodoSummary(state.todos) }
                item { Spacer(Modifier.height(20.dp)) }
            }
            MessageComposer(
                state = state,
                editorValue = TextFieldValue(state.composer.text),
                onDraftChange = {},
                onAttachment = {},
                onAgent = {},
                onQuickAction = { _, _ -> },
                onRemoveAttachment = {},
                onRetryAttachment = {},
                onSend = {},
                onStop = {},
            )
        }
    }

    private fun screenshotState() = AppUiState(
        serverUrl = "http://10.0.2.2:2027",
        user = DeerFlowUser("user-1", "alex@example.com", "user", needsSetup = false),
        route = AppRoute.Conversation,
        checkingSession = false,
        threads = listOf(
            ThreadSummary("thread-1", "Launch planning", "idle", "2026-07-20T10:00:00Z", isPinned = true),
            ThreadSummary("thread-2", "Research notes", "running", "2026-07-20T09:45:00Z"),
        ),
        selectedThread = ThreadSummary("thread-1", "Launch planning", "idle", "2026-07-20T10:00:00Z", isPinned = true),
        messages = snapshotGroups().mapNotNull { (it as? ChatMessageGroup.Message)?.message },
        todos = listOf(
            TodoItem("Review product requirements", "completed"),
            TodoItem("Draft implementation plan", "in_progress"),
        ),
        artifacts = listOf("mnt/user-data/outputs/launch-plan.md"),
        composer = ComposerState(
            text = "Summarize the open decisions for the launch plan.",
            options = RunOptions(assistantId = "researcher", modelName = "research", mode = RunMode.Thinking),
        ),
        capabilities = WorkspaceCapabilities(
            models = listOf(
                ModelInfo("research", "DeerFlow Research", "Research and synthesis", true, true),
                ModelInfo("fast", "DeerFlow Fast", "Fast answers", false, false),
            ),
            skills = listOf(
                SkillInfo("deep-research", "Investigate sources", "research", enabled = true),
            ),
        ),
    )

    private fun snapshotGroups() = listOf(
        ChatMessageGroup.Message(
            ChatMessage(
                id = "user-1",
                role = MessageRole.User,
                text = "Create a concise launch plan for the workspace update.",
            ),
        ),
        ChatMessageGroup.Message(
            ChatMessage(
                id = "assistant-1",
                role = MessageRole.Assistant,
                text = "## Launch plan\n\n1. Confirm the release scope.\n2. Validate the workspace on phone and tablet.\n3. Publish the signed build.",
            ),
        ),
    )

    private enum class Scenario(
        val widthDp: Int,
        val heightDp: Int,
        val theme: ThemePreference,
        val dynamicColor: Boolean,
        val locale: Locale,
        val fontScale: Float = 1f,
    ) {
        Phone360LightEnglish(360, 800, ThemePreference.Light, false, Locale.US),
        Phone412DarkEnglish(412, 915, ThemePreference.Dark, false, Locale.US),
        FoldableLightEnglish(673, 841, ThemePreference.Light, false, Locale.US),
        TabletLightEnglish(840, 800, ThemePreference.Light, false, Locale.US),
        Phone412DynamicEnglish(412, 915, ThemePreference.Light, true, Locale.US),
        Phone360LightChinese(360, 800, ThemePreference.Light, false, Locale.SIMPLIFIED_CHINESE),
        Phone360LightLargeText(360, 800, ThemePreference.Light, false, Locale.US, fontScale = 1.3f),
        ;

        val id: String get() = name.replace(Regex("([a-z])([A-Z])"), "$1_$2").lowercase()
    }

    private companion object {
        const val SCREENSHOT_ROOT_TAG = "workspace-screenshot-root"
        const val TABLET_BREAKPOINT_DP = 840
        const val OUTPUT_DIRECTORY = "visual-baselines"
        const val BASELINE_LOG_TAG = "DeerFlowVisualBaseline"
        const val RECORD_ARG = "deerflow.record_screenshots"
        const val SIGNATURE_GRID_SIZE = 12
        const val COLOR_BUCKET_SIZE = 16
        const val COLOR_DIGITS = "0123456789abcdef"
        const val MAX_SIGNATURE_DIFFERENCE = 12

        // Filled from the API 36 recording pass. A 12x12 RGB perceptual signature is
        // compact enough for source control while still detecting layout or palette drift.
        val BASELINES = mapOf(
            "phone412dark_english" to "1111111111111111111111111111111111111111112462462462462462462461111111111539ba1531531531531531531531531531531111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111111121121121121121121121121121121111111111111111111111111111111111111111211211211212221211211211211211211211211219a9121121121666666566121121121121121121121121121121121121121121121121121121121121121121121121121121121",
            "phone360light_large_text" to "ffffffffffffffffffffffffffffffffffffffffff789def123123defdef123cddfffffffffded464deddeddeddeddeddeddeddedffffffffffffffffffffffffffffffffffffffffff121eeeffffffffffffffffffffffffffffffffffff121121ffffff333121121ffffffffffffffffffffffffffffffffffffffffffeeeeee121122121eeeeee121222222eeeeeeeeeeeeeeeeee788555bcc787eeeeeeeeeeeeeeeeee555222333eeeeeeeeeeeeeee264264eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            "phone360light_english" to "ffffffffffffffffffffffffffffffffffffffffffdefdefdefdeedefdefdefdeffffffffffcddded8a99babcbbcb9a9abadeddedfffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffef697fef264375cccfffffffffeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeaaaccceee444343444eeeeee264264eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            "tablet_light_english" to "578fffffffffffffffffffffffffffffffff444ffffffffffffdefdefdefdeffffffffffffffffffffffffffff8989baacbdeddeddedfffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff666ffffffaaafffffffffffffffffffffffffffffffffdefceedefdefdefffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffeeeeeeeeeeeeeeeeeeeeefffffffffffffffbbbeeeeeeeee343677dedfffffffffffffffeeeeeeeeeeeeeeeeeeeeefffffffffeeefffeeeeeeeeeeeeeeeeeeeee",
            "foldable_light_english" to "fffffffffffffffffffffffffffffffffffffffdefdefdefdeffffffffffffffffffffffffffffffffffdeddeddeddeddeddeddeddedccc444ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff798fffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee264eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            "phone360light_chinese" to "ffffffffffffffffffffffffffffffffffffffffffdefdefdefdeedefdefdefffffffffffffcddded8a99babcbbcb9a9abadeddedfffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffcdcbccffffffffffffffffffeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeaaaccceee444343444eeeeee264264eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee",
            "phone412dynamic_english" to "ffffffffffffffffffffffffffffffffffffffffffdefdefdefdefdefdefdeffffffffffdef89bdefdefdefdefdefdefdefdefdefdefffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffeefeefeefeefeeeeefeefeefeefeefeefeefeefeef999eefeefeefccdcccccdeefeefeefeefeefeefeefeefeefeefeefeefeefeefeefeefeefeefeefeefeefeefeefeefeefeefeefeef",
        )
    }
}
