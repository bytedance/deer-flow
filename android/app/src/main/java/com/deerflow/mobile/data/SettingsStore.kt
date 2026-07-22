package com.deerflow.mobile.data

import android.content.Context
import androidx.datastore.core.DataStore
import androidx.datastore.preferences.SharedPreferencesMigration
import androidx.datastore.preferences.core.Preferences
import androidx.datastore.preferences.core.booleanPreferencesKey
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.emptyPreferences
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.core.stringSetPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import java.io.IOException
import kotlinx.coroutines.flow.catch
import kotlinx.coroutines.flow.first

private const val SETTINGS_NAME = "deerflow_settings"

private val Context.settingsDataStore: DataStore<Preferences> by preferencesDataStore(
    name = SETTINGS_NAME,
    produceMigrations = { context ->
        listOf(SharedPreferencesMigration(context, SETTINGS_NAME))
    },
)

data class SettingsSnapshot(
    val serverUrl: String = SettingsStore.DEFAULT_SERVER_URL,
    val theme: ThemePreference = ThemePreference.System,
    val useDynamicColor: Boolean = true,
    val notifyOnRunCompletion: Boolean = true,
    val cacheRetentionPolicy: CacheRetentionPolicy = CacheRetentionPolicy.KeepUntilCleared,
)

data class SavedRunOptions(
    val modelName: String? = null,
    val mode: RunMode = RunMode.Thinking,
)

class SettingsStore internal constructor(
    private val dataStore: DataStore<Preferences>,
) {
    constructor(context: Context) : this(context.applicationContext.settingsDataStore)

    suspend fun read(): SettingsSnapshot = preferences().toSnapshot()

    suspend fun setServerUrl(value: String) {
        dataStore.edit { it[SERVER_URL] = value }
    }

    suspend fun setTheme(value: ThemePreference) {
        dataStore.edit { it[THEME] = value.name }
    }

    suspend fun setDynamicColor(enabled: Boolean) {
        dataStore.edit { it[DYNAMIC_COLOR] = enabled }
    }

    suspend fun setNotifyOnRunCompletion(enabled: Boolean) {
        dataStore.edit { it[NOTIFY_ON_RUN_COMPLETION] = enabled }
    }

    suspend fun setCacheRetentionPolicy(value: CacheRetentionPolicy) {
        dataStore.edit { it[CACHE_RETENTION_POLICY] = value.name }
    }

    suspend fun pinnedThreads(serverUrl: String): Set<String> =
        preferences()[pinnedThreadsKey(serverUrl)]?.toSet().orEmpty()

    suspend fun setThreadPinned(serverUrl: String, threadId: String, pinned: Boolean) {
        dataStore.edit { preferences ->
            val key = pinnedThreadsKey(serverUrl)
            val values = preferences[key]?.toMutableSet() ?: mutableSetOf()
            if (pinned) values += threadId else values -= threadId
            preferences[key] = values
        }
    }

    suspend fun defaultAgent(serverUrl: String): String =
        preferences()[defaultAgentKey(serverUrl)]?.takeIf { it.isNotBlank() } ?: LEAD_AGENT_ID

    suspend fun setDefaultAgent(serverUrl: String, agentId: String) {
        dataStore.edit { preferences ->
            val key = defaultAgentKey(serverUrl)
            val normalized = agentId.trim()
            if (normalized.isBlank() || normalized == LEAD_AGENT_ID) preferences.remove(key)
            else preferences[key] = normalized
        }
    }

    suspend fun savedRunOptions(serverUrl: String): SavedRunOptions {
        val preferences = preferences()
        return SavedRunOptions(
            modelName = preferences[selectedModelKey(serverUrl)]?.takeIf { it.isNotBlank() },
            mode = runCatching {
                RunMode.valueOf(preferences[selectedModeKey(serverUrl)].orEmpty())
            }.getOrDefault(RunMode.Thinking),
        )
    }

    suspend fun setSavedRunOptions(serverUrl: String, modelName: String?, mode: RunMode) {
        dataStore.edit { preferences ->
            val key = selectedModelKey(serverUrl)
            val normalizedModelName = modelName?.trim().orEmpty()
            if (normalizedModelName.isBlank()) preferences.remove(key) else preferences[key] = normalizedModelName
            preferences[selectedModeKey(serverUrl)] = mode.name
        }
    }

    private suspend fun preferences(): Preferences = dataStore.data
        .catch { error ->
            if (error is IOException) emit(emptyPreferences()) else throw error
        }
        .first()

    private fun Preferences.toSnapshot(): SettingsSnapshot = SettingsSnapshot(
        serverUrl = this[SERVER_URL]
            ?.takeUnless { it == LEGACY_EMULATOR_SERVER_URL }
            .orEmpty(),
        theme = runCatching { ThemePreference.valueOf(this[THEME].orEmpty()) }
            .getOrDefault(ThemePreference.System),
        useDynamicColor = this[DYNAMIC_COLOR] ?: true,
        notifyOnRunCompletion = this[NOTIFY_ON_RUN_COMPLETION] ?: true,
        cacheRetentionPolicy = runCatching {
            CacheRetentionPolicy.valueOf(this[CACHE_RETENTION_POLICY].orEmpty())
        }.getOrDefault(CacheRetentionPolicy.KeepUntilCleared),
    )

    private fun pinnedThreadsKey(serverUrl: String) = stringSetPreferencesKey("$KEY_PINNED_PREFIX$serverUrl")

    private fun defaultAgentKey(serverUrl: String) = stringPreferencesKey("$KEY_DEFAULT_AGENT_PREFIX$serverUrl")

    private fun selectedModelKey(serverUrl: String) = stringPreferencesKey("$KEY_SELECTED_MODEL_PREFIX$serverUrl")

    private fun selectedModeKey(serverUrl: String) = stringPreferencesKey("$KEY_SELECTED_MODE_PREFIX$serverUrl")

    companion object {
        const val DEFAULT_SERVER_URL = ""
        private const val LEGACY_EMULATOR_SERVER_URL = "http://10.0.2.2:2026"

        private val SERVER_URL = stringPreferencesKey("server_url")
        private val THEME = stringPreferencesKey("theme")
        private val DYNAMIC_COLOR = booleanPreferencesKey("dynamic_color")
        private val NOTIFY_ON_RUN_COMPLETION = booleanPreferencesKey("notify_on_run_completion")
        private val CACHE_RETENTION_POLICY = stringPreferencesKey("cache_retention_policy")
        private const val KEY_PINNED_PREFIX = "pinned_threads_"
        private const val KEY_DEFAULT_AGENT_PREFIX = "default_agent_"
        private const val KEY_SELECTED_MODEL_PREFIX = "selected_model_"
        private const val KEY_SELECTED_MODE_PREFIX = "selected_mode_"
    }
}

enum class ThemePreference { System, Light, Dark }

enum class CacheRetentionPolicy { KeepUntilCleared, ClearOnSignOut }
