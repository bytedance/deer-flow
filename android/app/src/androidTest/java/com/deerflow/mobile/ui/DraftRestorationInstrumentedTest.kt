package com.deerflow.mobile.ui

import android.app.Application
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.ViewModelStore
import androidx.lifecycle.ViewModelStoreOwner
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import com.deerflow.mobile.data.DeerFlowApi
import com.deerflow.mobile.data.SettingsStore
import com.deerflow.mobile.data.WebViewSessionCookieStore
import com.deerflow.mobile.data.WorkspaceCache
import kotlinx.coroutines.delay
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.Assert.assertEquals
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class DraftRestorationInstrumentedTest {
    private val application = ApplicationProvider.getApplicationContext<Application>()
    private val serverUrl = "http://10.0.2.2:2027"

    @Test
    fun draftsStayWithTheirThreadAcrossSwitchesAndViewModelRecreation() = runBlocking {
        val settings = SettingsStore(application)
        val previousServerUrl = settings.read().serverUrl
        val cache = WorkspaceCache(application)
        val api = DeerFlowApi(serverUrl, WebViewSessionCookieStore())
        val firstThread = api.createThread()
        val secondThread = api.createThread()
        val firstOwner = TestViewModelStoreOwner()
        var secondOwner: TestViewModelStoreOwner? = null

        try {
            settings.setServerUrl(serverUrl)
            cache.saveDraft(serverUrl, firstThread.id, "first draft")
            cache.saveDraft(serverUrl, secondThread.id, "second draft")

            val firstViewModel = firstOwner.viewModel(application)
            firstViewModel.awaitReady()
            firstViewModel.openThread(firstThread)
            firstViewModel.awaitDraft(firstThread.id, "first draft")

            firstViewModel.updateDraft("edited first draft")
            firstViewModel.openThread(secondThread)
            firstViewModel.awaitDraft(secondThread.id, "second draft")
            awaitValue { cache.loadDraft(serverUrl, firstThread.id) == "edited first draft" }
            assertEquals("second draft", cache.loadDraft(serverUrl, secondThread.id))

            firstOwner.viewModelStore.clear()
            secondOwner = TestViewModelStoreOwner()
            val restoredViewModel = secondOwner.viewModel(application)
            restoredViewModel.awaitReady()
            restoredViewModel.openThread(firstThread)
            restoredViewModel.awaitDraft(firstThread.id, "edited first draft")
        } finally {
            firstOwner.viewModelStore.clear()
            secondOwner?.viewModelStore?.clear()
            cache.deleteThread(serverUrl, firstThread.id)
            cache.deleteThread(serverUrl, secondThread.id)
            runCatching { api.deleteThread(firstThread.id) }
            runCatching { api.deleteThread(secondThread.id) }
            settings.setServerUrl(previousServerUrl)
        }
    }

    private suspend fun AppViewModel.awaitReady() = awaitValue {
        state.value.serverUrl == serverUrl && !state.value.checkingSession
    }

    private suspend fun AppViewModel.awaitDraft(threadId: String, text: String) = awaitValue {
        val current = state.value
        current.selectedThread?.id == threadId && !current.loadingChat && current.composer.text == text
    }

    private suspend fun awaitValue(predicate: suspend () -> Boolean) {
        withTimeout(15_000) {
            while (!predicate()) delay(50)
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
