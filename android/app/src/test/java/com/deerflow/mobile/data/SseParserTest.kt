package com.deerflow.mobile.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class SseParserTest {
    @Test
    fun parsesGatewayFrameAndResetsForNextEvent() {
        val parser = SseParser()

        assertNull(parser.accept("event: metadata"))
        assertNull(parser.accept("data: {\"run_id\":\"run-1\"}"))
        assertNull(parser.accept("id: 10-0"))
        assertEquals(
            SseEvent("metadata", "{\"run_id\":\"run-1\"}", "10-0"),
            parser.accept(""),
        )

        assertNull(parser.accept(": heartbeat"))
        assertNull(parser.accept("event: end"))
        assertNull(parser.accept("data: null"))
        assertEquals(SseEvent("end", "null", null), parser.accept(""))
    }

    @Test
    fun joinsMultilineDataAccordingToSseRules() {
        val parser = SseParser()
        parser.accept("event: values")
        parser.accept("data: {\"messages\":")
        parser.accept("data: []}")

        assertEquals(
            SseEvent("values", "{\"messages\":\n[]}", null),
            parser.finish(),
        )
    }
}
