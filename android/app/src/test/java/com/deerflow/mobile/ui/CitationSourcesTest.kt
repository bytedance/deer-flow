package com.deerflow.mobile.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class CitationSourcesTest {
    @Test
    fun extractsAndGroupsCitationLinksWithoutTreatingCodeOrOrdinaryLinksAsCitations() {
        val sources = citationSources(
            """
            Evidence [citation: DeerFlow docs](https://example.com/docs) and
            [citation: Source](https://example.com/docs).

            [ordinary link](https://example.com/ordinary)

            ```text
            [citation: ignored](https://example.com/code)
            ```
            """.trimIndent(),
        )

        assertEquals(1, sources.size)
        assertEquals("DeerFlow docs", sources.single().title)
        assertEquals("example.com", sources.single().domain)
        assertEquals(2, sources.single().count)
        assertTrue(sources.single().url.startsWith("https://example.com/docs"))
    }

    @Test
    fun usesTheDomainForGenericCitationTitles() {
        val source = citationSources("[citation: 来源](https://www.example.com/docs)").single()

        assertEquals("example.com", source.title)
        assertEquals("example.com", source.domain)
    }
}
