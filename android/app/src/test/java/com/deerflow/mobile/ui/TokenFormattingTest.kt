package com.deerflow.mobile.ui

import org.junit.Assert.assertEquals
import org.junit.Test

class TokenFormattingTest {
    @Test
    fun formatsLargeTokenCountsWithCompactUnits() {
        assertEquals("999", formatTokenCount(999))
        assertEquals("1k", formatTokenCount(1_000))
        assertEquals("1.2k", formatTokenCount(1_299))
        assertEquals("12.5k", formatTokenCount(12_599))
        assertEquals("1m", formatTokenCount(1_000_000))
        assertEquals("2.4m", formatTokenCount(2_499_999))
    }
}
