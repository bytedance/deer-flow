package com.deerflow.mobile.ui

import android.app.Application
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.deerflow.mobile.data.DeerFlowApi
import com.deerflow.mobile.data.RunMode
import com.deerflow.mobile.data.SettingsStore
import com.deerflow.mobile.data.WebViewSessionCookieStore
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Assume.assumeNoException
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class ModelCapabilityInstrumentedTest {
    private val application = ApplicationProvider.getApplicationContext<Application>()
    private val serverUrl = "http://10.0.2.2:2027"

    @Test
    fun mockGatewayModelSelectionClampsModesAndReasoningEffort() = runBlocking {
        try {
            DeerFlowApi(serverUrl, WebViewSessionCookieStore()).currentUser()
        } catch (error: Exception) {
            assumeNoException("Mock Gateway is not running on host port 2027", error)
            return@runBlocking
        }

        val settings = SettingsStore(application)
        val previousServerUrl = settings.read().serverUrl
        val owner = TestViewModelStoreOwner()
        try {
            settings.setServerUrl(serverUrl)
            val viewModel = owner.viewModel(application)
            viewModel.awaitCapabilityLoad()

            assertModelState(
                viewModel = viewModel,
                modelName = "deerflow-fast",
                mode = RunMode.Flash,
                reasoningEffortEnabled = false,
            )

            viewModel.selectModel("deerflow-pro")
            viewModel.awaitModel("deerflow-pro")
            viewModel.selectMode(RunMode.Ultra)
            assertModelState(
                viewModel = viewModel,
                modelName = "deerflow-pro",
                mode = RunMode.Ultra,
                reasoningEffortEnabled = true,
            )

            viewModel.selectModel("deerflow-fast")
            assertModelState(
                viewModel = viewModel,
                modelName = "deerflow-fast",
                mode = RunMode.Flash,
                reasoningEffortEnabled = false,
            )
        } finally {
            owner.viewModelStore.clear()
            settings.setServerUrl(previousServerUrl)
        }
    }

    @Test
    fun mockGatewayPersistsSkillStateAndClearsDisabledRunSelection() = runBlocking {
        val api = DeerFlowApi(serverUrl, WebViewSessionCookieStore())
        try {
            api.currentUser()
        } catch (error: Exception) {
            assumeNoException("Mock Gateway is not running on host port 2027", error)
            return@runBlocking
        }

        val settings = SettingsStore(application)
        val previousServerUrl = settings.read().serverUrl
        val owner = TestViewModelStoreOwner()
        try {
            api.setSkillEnabled("deep-research", true)
            settings.setServerUrl(serverUrl)
            val viewModel = owner.viewModel(application)
            viewModel.awaitCapabilityLoad()
            viewModel.enableSkill("deep-research")
            viewModel.awaitSelectedSkill("deep-research")

            viewModel.setSkillEnabled("deep-research", false)
            viewModel.awaitSkillEnabled("deep-research", enabled = false)

            assertFalse("deep-research" in viewModel.state.value.composer.options.enabledSkills)
            assertFalse(api.loadCapabilities().skills.single { it.name == "deep-research" }.enabled)
        } finally {
            runCatching { api.setSkillEnabled("deep-research", true) }
            owner.viewModelStore.clear()
            settings.setServerUrl(previousServerUrl)
        }
    }

    @Test
    fun mockGatewayPersistsMcpServerEnabledState() = runBlocking {
        val api = DeerFlowApi(serverUrl, WebViewSessionCookieStore())
        try {
            api.currentUser()
        } catch (error: Exception) {
            assumeNoException("Mock Gateway is not running on host port 2027", error)
            return@runBlocking
        }

        val settings = SettingsStore(application)
        val previousServerUrl = settings.read().serverUrl
        val owner = TestViewModelStoreOwner()
        try {
            val existing = api.loadMcpConfig()
            api.setMcpServerEnabled(existing, "research-tools", true)
            settings.setServerUrl(serverUrl)
            val viewModel = owner.viewModel(application)
            viewModel.awaitMcpConfig()

            viewModel.setMcpServerEnabled("research-tools", false)
            viewModel.awaitMcpServerEnabled("research-tools", enabled = false)

            assertFalse(api.loadMcpConfig().servers.single { it.name == "research-tools" }.enabled)
        } finally {
            runCatching { api.setMcpServerEnabled(api.loadMcpConfig(), "research-tools", true) }
            owner.viewModelStore.clear()
            settings.setServerUrl(previousServerUrl)
        }
    }

    @Test
    fun mockGatewayPersistsChannelRuntimeConfigurationBindingAndDisable() = runBlocking {
        val api = DeerFlowApi(serverUrl, WebViewSessionCookieStore())
        try {
            api.currentUser()
        } catch (error: Exception) {
            assumeNoException("Mock Gateway is not running on host port 2027", error)
            return@runBlocking
        }

        val settings = SettingsStore(application)
        val previousServerUrl = settings.read().serverUrl
        val owner = TestViewModelStoreOwner()
        try {
            runCatching { api.disconnectChannelProvider("telegram") }
            settings.setServerUrl(serverUrl)
            val viewModel = owner.viewModel(application)
            viewModel.awaitChannelConfigured("telegram", configured = false)

            viewModel.configureChannelProvider(
                "telegram",
                mapOf("bot_token" to "fixture-token", "bot_username" to "fixture_bot"),
            )
            viewModel.awaitChannelConfigured("telegram", configured = true)
            assertTrue(api.loadChannelProviders().providers.single { it.provider == "telegram" }.connectable)

            viewModel.connectChannelProvider("telegram")
            viewModel.awaitChannelBinding("telegram")
            assertEquals("bind-telegram-fixture", viewModel.state.value.channelConnect?.code)

            viewModel.disconnectChannelProvider("telegram")
            viewModel.awaitChannelConfigured("telegram", configured = false)
            assertFalse(api.loadChannelProviders().providers.single { it.provider == "telegram" }.configured)
        } finally {
            runCatching { api.disconnectChannelProvider("telegram") }
            owner.viewModelStore.clear()
            settings.setServerUrl(previousServerUrl)
        }
    }

    private suspend fun AppViewModel.awaitCapabilityLoad() = withTimeout(15_000) {
        while (state.value.loadingCapabilities || state.value.capabilities.models.size != 2) delay(50)
    }

    private suspend fun AppViewModel.awaitModel(modelName: String) = withTimeout(5_000) {
        while (state.value.composer.options.modelName != modelName) delay(20)
    }

    private suspend fun AppViewModel.awaitSelectedSkill(skillName: String) = withTimeout(5_000) {
        while (skillName !in state.value.composer.options.enabledSkills) delay(20)
    }

    private suspend fun AppViewModel.awaitSkillEnabled(skillName: String, enabled: Boolean) = withTimeout(5_000) {
        while (state.value.workspaceMutationBusy || state.value.capabilities.skills.firstOrNull { it.name == skillName }?.enabled != enabled) delay(20)
    }

    private suspend fun AppViewModel.awaitMcpConfig() = withTimeout(15_000) {
        while (state.value.loadingMcpConfig || state.value.mcpConfig == null) delay(50)
    }

    private suspend fun AppViewModel.awaitMcpServerEnabled(serverName: String, enabled: Boolean) = withTimeout(5_000) {
        while (state.value.workspaceMutationBusy || state.value.mcpConfig?.servers?.firstOrNull { it.name == serverName }?.enabled != enabled) delay(20)
    }

    private suspend fun AppViewModel.awaitChannelConfigured(providerId: String, configured: Boolean) = withTimeout(15_000) {
        while (
            state.value.loadingChannels ||
                state.value.workspaceMutationBusy ||
                state.value.channelProviders?.providers?.firstOrNull { it.provider == providerId }?.configured != configured
        ) delay(20)
    }

    private suspend fun AppViewModel.awaitChannelBinding(providerId: String) = withTimeout(5_000) {
        while (state.value.workspaceMutationBusy || state.value.channelConnect?.provider != providerId) delay(20)
    }

    private fun assertModelState(
        viewModel: AppViewModel,
        modelName: String,
        mode: RunMode,
        reasoningEffortEnabled: Boolean,
    ) {
        val options = viewModel.state.value.composer.options
        assertEquals(modelName, options.modelName)
        assertEquals(mode, options.mode)
        if (reasoningEffortEnabled) {
            assertTrue(options.reasoningEffortEnabled)
        } else {
            assertFalse(options.reasoningEffortEnabled)
        }
    }

    private class TestViewModelStoreOwner : ViewModelStoreOwner {
        override val viewModelStore = ViewModelStore()

        fun viewModel(application: Application): AppViewModel = ViewModelProvider(
            this,
            ViewModelProvider.AndroidViewModelFactory.getInstance(application),
        )[AppViewModel::class.java]
    }
}
