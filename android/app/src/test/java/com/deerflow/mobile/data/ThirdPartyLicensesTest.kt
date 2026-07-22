package com.deerflow.mobile.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ThirdPartyLicensesTest {
    @Test
    fun parsesPluginMetadataOffsetsIntoNamedNotices() {
        val notices = parseThirdPartyLicenseNotices(
            metadata = "0:11 Kotlin stdlib\n11:11 OkHttp",
            licenseText = "Kotlin textOkHttp text",
        )

        assertEquals(listOf("Kotlin stdlib", "OkHttp"), notices.map { it.name })
        assertEquals(listOf("Kotlin text", "OkHttp text"), notices.map { it.text })
    }

    @Test
    fun keepsReadableDiagnosticTextWhenDebugMetadataIsNotIndexed() {
        val notices = parseThirdPartyLicenseNotices("invalid metadata", "Debug license notice")

        assertEquals(1, notices.size)
        assertTrue(notices.single().text.contains("Debug license"))
    }
}
