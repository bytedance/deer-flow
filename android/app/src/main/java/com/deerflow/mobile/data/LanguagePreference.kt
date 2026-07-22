package com.deerflow.mobile.data

enum class LanguagePreference(val languageTag: String) {
    System(""),
    English("en"),
    SimplifiedChinese("zh-CN"),
    ;

    companion object {
        fun fromLanguageTags(languageTags: String): LanguagePreference {
            val tag = languageTags.substringBefore(',').trim().lowercase()
            return when {
                tag.isBlank() -> System
                tag == "en" || tag.startsWith("en-") -> English
                tag == "zh" || tag.startsWith("zh-") -> SimplifiedChinese
                else -> System
            }
        }
    }
}
