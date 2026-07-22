package com.deerflow.mobile.data

import java.time.Instant
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

sealed interface TaskSchedule {
    data class Cron(val expression: String) : TaskSchedule
    data class Once(val runAt: String) : TaskSchedule
}

fun onceScheduleFor(date: LocalDate, time: LocalTime, timezone: String): TaskSchedule.Once? = runCatching {
    val runAt = LocalDateTime.of(date, time)
        .atZone(ZoneId.of(timezone.trim()))
        .toOffsetDateTime()
        .format(DateTimeFormatter.ISO_OFFSET_DATE_TIME)
    TaskSchedule.Once(runAt)
}.getOrNull()

fun parseOnceSchedule(runAt: String, timezone: String): LocalDateTime? = runCatching {
    val zone = ZoneId.of(timezone.trim())
    runCatching { OffsetDateTime.parse(runAt).atZoneSameInstant(zone).toLocalDateTime() }
        .recoverCatching { Instant.parse(runAt).atZone(zone).toLocalDateTime() }
        .recoverCatching { LocalDateTime.parse(runAt) }
        .getOrThrow()
}.getOrNull()

fun isFutureOnceSchedule(schedule: TaskSchedule.Once): Boolean = runCatching {
    OffsetDateTime.parse(schedule.runAt).toInstant().isAfter(Instant.now())
}.getOrDefault(false)
