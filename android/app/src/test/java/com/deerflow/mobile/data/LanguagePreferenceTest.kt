package com.deerflow.mobile.data

import org.junit.Assert.assertEquals
import org.junit.Test

class LanguagePreferenceTest {
    @Test
    fun applicationLanguageTagsMapToSupportedSelections() {
        assertEquals(LanguagePreference.System, LanguagePreference.fromLanguageTags(""))
        assertEquals(LanguagePreference.English, LanguagePreference.fromLanguageTags("en"))
        assertEquals(LanguagePreference.English, LanguagePreference.fromLanguageTags("en-US"))
        assertEquals(LanguagePreference.SimplifiedChinese, LanguagePreference.fromLanguageTags("zh-CN"))
        assertEquals(LanguagePreference.SimplifiedChinese, LanguagePreference.fromLanguageTags("zh-Hans-CN"))
        assertEquals(LanguagePreference.System, LanguagePreference.fromLanguageTags("fr-FR"))
    }
}
