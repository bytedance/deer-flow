package com.deerflow.mobile.data

import java.net.URI

fun normalizeServerUrl(input: String): String {
    val trimmed = input.trim().trimEnd('/')
    require(trimmed.isNotEmpty()) { "Enter a DeerFlow server address." }

    val withScheme = if (trimmed.contains("://")) {
        trimmed
    } else {
        val local = trimmed.startsWith("localhost") ||
            trimmed.startsWith("127.") ||
            trimmed.startsWith("10.") ||
            trimmed.startsWith("192.168.") ||
            trimmed.matches(Regex("172\\.(1[6-9]|2\\d|3[01])\\..*"))
        "${if (local || trimmed.isIpv4Address()) "http" else "https"}://$trimmed"
    }

    val uri = runCatching { URI(withScheme) }
        .getOrElse { throw IllegalArgumentException("Enter a valid HTTP or HTTPS address.") }
    require(uri.scheme == "http" || uri.scheme == "https") { "Only HTTP and HTTPS addresses are supported." }
    require(!uri.host.isNullOrBlank()) { "The server address needs a host name." }
    require(uri.rawQuery == null && uri.rawFragment == null && (uri.path.isNullOrBlank() || uri.path == "/")) {
        "Use the server origin without an /api path."
    }
    return URI(uri.scheme, uri.userInfo, uri.host, uri.port, null, null, null).toString().trimEnd('/')
}

private fun String.isIpv4Address(): Boolean {
    val host = substringBefore('/').substringBefore(':')
    val octets = host.split('.')
    return octets.size == 4 && octets.all { octet -> octet.toIntOrNull()?.let { it in 0..255 } == true }
}
