package com.deerflow.mobile.data

import android.annotation.SuppressLint
import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.SharedPreferencesMigration
import androidx.datastore.preferences.core.PreferenceDataStoreFactory
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.preferencesDataStoreFile
import androidx.test.core.app.ApplicationProvider
import androidx.test.ext.junit.runners.AndroidJUnit4
import java.util.UUID
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.cancel
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.runBlocking
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class SettingsStoreInstrumentedTest {
    private val context: Context = ApplicationProvider.getApplicationContext()

    @Test
    @SuppressLint("ApplySharedPref")
    fun sharedPreferencesValuesMigrateBeforeFirstDataStoreRead() = runBlocking {
        val legacyName = "legacy-settings-${UUID.randomUUID()}"
        val dataStoreName = "migrated-settings-${UUID.randomUUID()}"
        val serverUrl = "https://deerflow.example.test"
        val legacy = context.getSharedPreferences(legacyName, Context.MODE_PRIVATE)
        assertTrue(
            legacy.edit()
                .putString("server_url", serverUrl)
                .putString("theme", ThemePreference.Dark.name)
                .putBoolean("dynamic_color", false)
                .putStringSet("pinned_threads_$serverUrl", setOf("thread-1", "thread-2"))
                .commit(),
        )

        withTestStore(dataStoreName, legacyName) { (store, _) ->
            assertEquals(
                SettingsSnapshot(serverUrl, ThemePreference.Dark, useDynamicColor = false),
                store.read(),
            )
            assertEquals(setOf("thread-1", "thread-2"), store.pinnedThreads(serverUrl))
        }

        assertFalse(legacy.contains("server_url"))
        assertFalse(legacy.contains("theme"))
        assertFalse(legacy.contains("dynamic_color"))
        assertFalse(legacy.contains("pinned_threads_$serverUrl"))
        assertTrue(legacy.edit().clear().commit())
    }

    @Test
    fun defaultAgentPreferenceIsPersistentAndServerScoped() = runBlocking {
        val dataStoreName = "agent-settings-${UUID.randomUUID()}"
        val firstServer = "https://first-agent.example.test"
        val secondServer = "https://second-agent.example.test"

        withTestStore(dataStoreName) { (store, dataStore) ->
            assertEquals(LEAD_AGENT_ID, store.defaultAgent(firstServer))
            assertEquals(LEAD_AGENT_ID, store.defaultAgent(secondServer))

            store.setDefaultAgent(firstServer, "researcher")
            store.setDefaultAgent(secondServer, "writer")

            assertEquals("researcher", SettingsStore(dataStore).defaultAgent(firstServer))
            assertEquals("writer", SettingsStore(dataStore).defaultAgent(secondServer))

            store.setDefaultAgent(firstServer, LEAD_AGENT_ID)
            assertEquals(LEAD_AGENT_ID, store.defaultAgent(firstServer))
            assertEquals("writer", store.defaultAgent(secondServer))
        }
    }

    @Test
    fun selectedRunOptionsArePersistentAndServerScoped() = runBlocking {
        val dataStoreName = "run-options-${UUID.randomUUID()}"
        val firstServer = "https://first-options.example.test"
        val secondServer = "https://second-options.example.test"

        withTestStore(dataStoreName) { (store, dataStore) ->
            assertEquals(SavedRunOptions(), store.savedRunOptions(firstServer))
            assertEquals(SavedRunOptions(), store.savedRunOptions(secondServer))

            store.setSavedRunOptions(firstServer, "research", RunMode.Ultra)
            store.setSavedRunOptions(secondServer, "fast", RunMode.Flash)

            assertEquals(
                SavedRunOptions(modelName = "research", mode = RunMode.Ultra),
                SettingsStore(dataStore).savedRunOptions(firstServer),
            )
            assertEquals(
                SavedRunOptions(modelName = "fast", mode = RunMode.Flash),
                store.savedRunOptions(secondServer),
            )
        }
    }

    @Test
    fun readsWritesAndPinnedThreadTransactionsStayConsistent() = runBlocking {
        val dataStoreName = "settings-${UUID.randomUUID()}"
        val firstServer = "https://first.example.test"
        val secondServer = "https://second.example.test"

        withTestStore(dataStoreName) { (store, dataStore) ->
            assertEquals(SettingsSnapshot(), store.read())
            assertTrue(store.pinnedThreads(firstServer).isEmpty())

            store.setServerUrl(firstServer)
            store.setTheme(ThemePreference.Light)
            store.setDynamicColor(false)
            store.setNotifyOnRunCompletion(false)
            store.setCacheRetentionPolicy(CacheRetentionPolicy.ClearOnSignOut)

            assertEquals(
                SettingsSnapshot(
                    serverUrl = firstServer,
                    theme = ThemePreference.Light,
                    useDynamicColor = false,
                    notifyOnRunCompletion = false,
                    cacheRetentionPolicy = CacheRetentionPolicy.ClearOnSignOut,
                ),
                store.read(),
            )

            val firstServerThreads = (1..20).map { "thread-$it" }
            coroutineScope {
                firstServerThreads.map { threadId ->
                    async { store.setThreadPinned(firstServer, threadId, pinned = true) }
                }.awaitAll()
            }
            store.setThreadPinned(secondServer, "thread-1", pinned = true)
            store.setThreadPinned(firstServer, "thread-1", pinned = false)

            assertEquals(firstServerThreads.drop(1).toSet(), store.pinnedThreads(firstServer))
            assertEquals(setOf("thread-1"), store.pinnedThreads(secondServer))
            assertEquals(
                SettingsSnapshot(
                    serverUrl = firstServer,
                    theme = ThemePreference.Light,
                    useDynamicColor = false,
                    notifyOnRunCompletion = false,
                    cacheRetentionPolicy = CacheRetentionPolicy.ClearOnSignOut,
                ),
                SettingsStore(dataStore).read(),
            )
        }
    }

    private suspend fun withTestStore(
        dataStoreName: String,
        legacyName: String? = null,
        block: suspend (TestStore) -> Unit,
    ) {
        val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
        val file = context.preferencesDataStoreFile(dataStoreName)
        val migrations = legacyName?.let { listOf(SharedPreferencesMigration(context, it)) }.orEmpty()
        val dataStore = PreferenceDataStoreFactory.create(
            migrations = migrations,
            scope = scope,
            produceFile = { file },
        )
        try {
            block(TestStore(SettingsStore(dataStore), dataStore))
        } finally {
            scope.cancel()
            file.delete()
        }
    }

    private data class TestStore(
        val settings: SettingsStore,
        val dataStore: DataStore<Preferences>,
    )
}
