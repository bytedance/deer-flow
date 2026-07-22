package com.deerflow.mobile.ui

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class ToolResultPresentationTest {
    @Test
    fun parsesGatewayWebSearchResultsAndRejectsUnsafeLinks() {
        val results = parseToolSearchResults(
            """{"results":[{"title":"Android Developers","url":"https://developer.android.com","content":"Official Android documentation"},{"title":"Unsafe","url":"javascript:alert(1)"}]}""",
        )

        assertEquals(1, results.size)
        assertEquals("Android Developers", results.single().title)
        assertEquals("Official Android documentation", results.single().snippet)
    }

    @Test
    fun parsesImageResultsFromSnakeAndCamelCaseGatewayFields() {
        val results = parseToolImageSearchResults(
            """{"results":[{"title":"Mountain","source_url":"https://source.example/mountain","thumbnailUrl":"https://images.example/thumb.jpg","imageUrl":"https://images.example/full.jpg"}]}""",
        )

        assertEquals(1, results.size)
        assertEquals("https://source.example/mountain", results.single().sourceUrl)
        assertEquals("https://images.example/thumb.jpg", results.single().thumbnailUrl)
        assertEquals("https://images.example/full.jpg", results.single().imageUrl)
    }

    @Test
    fun malformedOrNonHttpToolResultsFallBackWithoutStructuredItems() {
        assertTrue(parseToolSearchResults("not-json").isEmpty())
        assertTrue(parseToolImageSearchResults("""[{"title":"Local","image_url":"file:///tmp/image.png"}]""").isEmpty())
    }
}
