package com.deerflow.mobile.data

data class SseEvent(
    val event: String,
    val data: String,
    val id: String?,
)

/** Incremental parser for the LangGraph-compatible SSE framing used by Gateway. */
class SseParser {
    private var eventName = "message"
    private var eventId: String? = null
    private val data = mutableListOf<String>()

    fun accept(line: String): SseEvent? {
        if (line.isEmpty()) return dispatch()
        if (line.startsWith(":")) return null

        val separator = line.indexOf(':')
        val field = if (separator >= 0) line.substring(0, separator) else line
        val rawValue = if (separator >= 0) line.substring(separator + 1) else ""
        val value = rawValue.removePrefix(" ")
        when (field) {
            "event" -> eventName = value
            "data" -> data += value
            "id" -> eventId = value
        }
        return null
    }

    fun finish(): SseEvent? = dispatch()

    private fun dispatch(): SseEvent? {
        if (data.isEmpty()) {
            eventName = "message"
            eventId = null
            return null
        }
        val event = SseEvent(eventName, data.joinToString("\n"), eventId)
        eventName = "message"
        eventId = null
        data.clear()
        return event
    }
}
