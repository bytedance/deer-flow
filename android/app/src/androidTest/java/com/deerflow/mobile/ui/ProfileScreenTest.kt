package com.deerflow.mobile.ui

import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.material3.MaterialTheme
import androidx.compose.ui.test.junit4.createComposeRule
import androidx.compose.ui.test.hasTestTag
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import com.deerflow.mobile.BuildConfig
import com.deerflow.mobile.data.CacheRetentionPolicy
import com.deerflow.mobile.data.CacheStats
import com.deerflow.mobile.data.DeerFlowUser
import com.deerflow.mobile.data.LanguagePreference
import com.deerflow.mobile.data.ThemePreference
import java.util.concurrent.atomic.AtomicInteger
import java.util.concurrent.atomic.AtomicReference
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

class ProfileScreenTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun languageNotificationAndCachePolicySelectionsDispatchCallbacks() {
        val language = AtomicReference<LanguagePreference>()
        val notifications = AtomicReference<Boolean>()
        val cachePolicy = AtomicReference<CacheRetentionPolicy>()
        setProfile(
            onLanguageSelected = language::set,
            onNotifyOnRunCompletionChanged = notifications::set,
            onCacheRetentionPolicySelected = cachePolicy::set,
        )

        scrollToProfileItem(UiTags.ProfileLanguage)
        compose.onNodeWithTag(UiTags.ProfileLanguage).performClick()
        compose.onNodeWithTag(UiTags.ProfileLanguageOptionPrefix + LanguagePreference.SimplifiedChinese.name).performClick()
        scrollToProfileItem(UiTags.ProfileNotifications)
        compose.onNodeWithTag(UiTags.ProfileNotifications).performClick()
        scrollToProfileItem(UiTags.ProfileCachePolicy)
        compose.onNodeWithTag(UiTags.ProfileCachePolicy).performClick()
        compose.onNodeWithTag(UiTags.ProfileCachePolicyOptionPrefix + CacheRetentionPolicy.ClearOnSignOut.name).performClick()

        compose.runOnIdle {
            assertEquals(LanguagePreference.SimplifiedChinese, language.get())
            assertEquals(false, notifications.get())
            assertEquals(CacheRetentionPolicy.ClearOnSignOut, cachePolicy.get())
        }
    }

    @Test
    fun themeSegmentedControlDispatchesTheSelectedTheme() {
        val theme = AtomicReference<ThemePreference>()
        setProfile(onThemeSelected = theme::set)

        scrollToProfileItem(UiTags.ProfileThemePrefix + ThemePreference.Dark.name)
        compose.onNodeWithTag(UiTags.ProfileThemePrefix + ThemePreference.Dark.name).performClick()

        compose.runOnIdle { assertEquals(ThemePreference.Dark, theme.get()) }
    }

    @Test
    fun channelsAreOpenedFromTheProfileScreen() {
        val channelOpens = AtomicInteger()
        setProfile(onOpenChannels = { channelOpens.incrementAndGet() })

        scrollToProfileItem(UiTags.ProfileChannels)
        compose.onNodeWithTag(UiTags.ProfileChannels).performClick()

        compose.runOnIdle { assertEquals(1, channelOpens.get()) }
    }

    @Test
    fun cacheClearRequiresConfirmationAndAboutExposesLicenseActions() {
        val clearCalls = AtomicInteger()
        val openSourceCalls = AtomicInteger()
        setProfile(
            onClearCache = { clearCalls.incrementAndGet() },
            onOpenSourceLicenses = { openSourceCalls.incrementAndGet() },
        )

        scrollToProfileItem(UiTags.ProfileCacheClear)
        compose.onNodeWithTag(UiTags.ProfileCacheClear).performClick()
        compose.runOnIdle { assertEquals(0, clearCalls.get()) }
        compose.onNodeWithTag(UiTags.ProfileCacheClearConfirm).performClick()
        compose.runOnIdle { assertEquals(1, clearCalls.get()) }

        scrollToProfileItem(UiTags.ProfileAbout)
        compose.onNodeWithTag(UiTags.ProfileAbout).performClick()
        compose.onNodeWithTag(UiTags.AboutScreen).assertExists()
        compose.onNodeWithText("DeerFlow Android ${BuildConfig.VERSION_NAME}").assertExists()
        compose.onNodeWithTag(UiTags.AboutDeerFlowLicense).performScrollTo().performClick()
        compose.onNodeWithTag(UiTags.AboutLicenseDialog).assertExists()
        compose.onNodeWithText("Permission is hereby granted", substring = true).assertExists()
        compose.onNodeWithText("Close").performClick()
        compose.onNodeWithTag(UiTags.AboutOpenSourceLicenses).performScrollTo().performClick()
        compose.onNodeWithTag(UiTags.ThirdPartyLicensesScreen).assertExists()
        compose.runOnIdle { assertEquals(1, openSourceCalls.get()) }
    }

    private fun setProfile(
        onLanguageSelected: (LanguagePreference) -> Unit = {},
        onThemeSelected: (ThemePreference) -> Unit = {},
        onNotifyOnRunCompletionChanged: (Boolean) -> Unit = {},
        onCacheRetentionPolicySelected: (CacheRetentionPolicy) -> Unit = {},
        onClearCache: () -> Unit = {},
        onOpenChannels: () -> Unit = {},
        onOpenSourceLicenses: () -> Unit = {},
    ) {
        compose.setContent {
            MaterialTheme {
                ProfileContent(
                    state = AppUiState(
                        serverUrl = "http://10.0.2.2:2027",
                        user = DeerFlowUser("user-1", "user@example.test", "user", false),
                        checkingSession = false,
                        theme = ThemePreference.System,
                        useDynamicColor = true,
                        language = LanguagePreference.System,
                        notifyOnRunCompletion = true,
                        cacheRetentionPolicy = CacheRetentionPolicy.KeepUntilCleared,
                        cacheStats = CacheStats(conversationCount = 2, messageCount = 5, bytesOnDisk = 4096),
                    ),
                    onBack = {},
                    onSaveServerUrl = {},
                    onThemeSelected = onThemeSelected,
                    onDynamicColorChanged = {},
                    onLanguageSelected = onLanguageSelected,
                    onNotifyOnRunCompletionChanged = onNotifyOnRunCompletionChanged,
                    onCacheRetentionPolicySelected = onCacheRetentionPolicySelected,
                    onRefreshCacheStats = {},
                    onClearCache = onClearCache,
                    onSignOut = {},
                    onOpenChannels = onOpenChannels,
                    onOpenSourceLicenses = onOpenSourceLicenses,
                    onOpenSourceCode = {},
                    contentPadding = PaddingValues(),
                )
            }
        }
    }

    private fun scrollToProfileItem(tag: String) {
        compose.onNodeWithTag(UiTags.ProfileList).performScrollToNode(hasTestTag(tag))
    }
}
