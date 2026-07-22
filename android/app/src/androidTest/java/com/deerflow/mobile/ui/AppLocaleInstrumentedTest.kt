package com.deerflow.mobile.ui

import androidx.appcompat.app.AppCompatDelegate
import androidx.core.os.LocaleListCompat
import androidx.test.core.app.ActivityScenario
import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.deerflow.mobile.MainActivity
import com.deerflow.mobile.R
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

@RunWith(AndroidJUnit4::class)
class AppLocaleInstrumentedTest {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()

    @After
    fun restoreSystemLocale() {
        setApplicationLocales("")
    }

    @Test
    fun selectedLocaleUpdatesResourcesAndSurvivesActivityRecreation() {
        ActivityScenario.launch(MainActivity::class.java).use { scenario ->
            setApplicationLocales("zh-CN")
            scenario.onActivity { activity ->
                assertEquals("我的", activity.getString(R.string.profile_title))
            }

            scenario.recreate()
            scenario.onActivity { activity ->
                assertEquals("我的", activity.getString(R.string.profile_title))
                assertTrue(AppCompatDelegate.getApplicationLocales().toLanguageTags().startsWith("zh"))
            }

            setApplicationLocales("en")
            scenario.onActivity { activity ->
                assertEquals("Me", activity.getString(R.string.profile_title))
            }
            setApplicationLocales("")
        }
    }

    private fun setApplicationLocales(languageTags: String) {
        instrumentation.runOnMainSync {
            AppCompatDelegate.setApplicationLocales(LocaleListCompat.forLanguageTags(languageTags))
        }
        instrumentation.waitForIdleSync()
    }
}
