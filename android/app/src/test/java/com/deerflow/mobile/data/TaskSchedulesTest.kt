package com.deerflow.mobile.data

import java.time.LocalDate
import java.time.LocalTime
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test

class TaskSchedulesTest {
    @Test
    fun createsOnceScheduleWithTheDeclaredTimezoneOffset() {
        val schedule = onceScheduleFor(
            date = LocalDate.of(2026, 12, 31),
            time = LocalTime.of(9, 30),
            timezone = "Asia/Shanghai",
        )

        assertEquals(TaskSchedule.Once("2026-12-31T09:30:00+08:00"), schedule)
    }

    @Test
    fun parsesOffsetOnceSchedulesIntoTheDeclaredTimezone() {
        assertEquals(
            "2026-12-31T09:30",
            parseOnceSchedule("2026-12-31T01:30:00Z", "Asia/Shanghai").toString(),
        )
    }

    @Test
    fun rejectsInvalidTimezoneWhenCreatingOrParsingOnceSchedules() {
        assertNull(onceScheduleFor(LocalDate.of(2026, 12, 31), LocalTime.NOON, "Not/AZone"))
        assertNull(parseOnceSchedule("2026-12-31T09:30:00+08:00", "Not/AZone"))
    }
}
