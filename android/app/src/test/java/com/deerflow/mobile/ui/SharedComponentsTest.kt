package com.deerflow.mobile.ui

import java.time.ZoneId
import org.junit.Assert.assertEquals
import org.junit.Test

class SharedComponentsTest {
    @Test
    fun displayTimeConvertsUtcTimestampToTheRequestedTimezone() {
        assertEquals(
            "2026-07-22 11:21:23",
            "2026-07-22T03:21:23.835590+00:00".toDisplayTime(ZoneId.of("Asia/Shanghai")),
        )
    }

    @Test
    fun displayTimeLeavesMalformedValuesReadable() {
        assertEquals("not a timestamp", "not a timestamp".toDisplayTime(ZoneId.of("Asia/Shanghai")))
    }
}
