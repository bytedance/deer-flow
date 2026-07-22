package com.deerflow.mobile.data

data class ThirdPartyLicenseNotice(
    val name: String,
    val text: String,
)

/**
 * The OSS Licenses Gradle plugin packages a line-oriented index where each line
 * is `offset:length library name` and the companion resource holds the text.
 */
internal fun parseThirdPartyLicenseNotices(metadata: String, licenseText: String): List<ThirdPartyLicenseNotice> {
    val indexedNotices = metadata.lineSequence().mapNotNull { line ->
        val match = METADATA_LINE.matchEntire(line.trim()) ?: return@mapNotNull null
        val offset = match.groupValues[1].toIntOrNull() ?: return@mapNotNull null
        val length = match.groupValues[2].toIntOrNull() ?: return@mapNotNull null
        val name = match.groupValues[3].trim()
        val end = offset.toLong() + length.toLong()
        if (offset < 0 || length <= 0 || end > licenseText.length || name.isBlank()) return@mapNotNull null
        ThirdPartyLicenseNotice(name, licenseText.substring(offset, end.toInt()).trim())
    }.filter { it.text.isNotBlank() }.toList()

    if (indexedNotices.isNotEmpty()) return indexedNotices
    return licenseText.trim().takeIf { it.isNotBlank() }?.let {
        listOf(ThirdPartyLicenseNotice("Third-party notices", it))
    }.orEmpty()
}

private val METADATA_LINE = Regex("^(\\d+):(\\d+)\\s+(.+)$")
