package com.deerflow.mobile.ui

import android.graphics.BitmapFactory
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyRow
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.OpenInNew
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import com.deerflow.mobile.R
import com.deerflow.mobile.data.MessageBlock
import java.io.ByteArrayOutputStream
import java.net.URI
import java.net.URL
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import org.json.JSONArray
import org.json.JSONObject

internal data class ToolSearchResult(
    val title: String,
    val url: String,
    val snippet: String,
)

internal data class ToolImageSearchResult(
    val title: String,
    val sourceUrl: String,
    val thumbnailUrl: String,
    val imageUrl: String,
)

@Composable
internal fun ToolResultPresentation(call: MessageBlock.ToolCall, result: MessageBlock.ToolResult) {
    when (call.name) {
        "web_search" -> WebSearchResults(parseToolSearchResults(result.detail), result.detail)
        "image_search" -> ImageSearchResults(parseToolImageSearchResults(result.detail), result.detail)
        "ls", "read_file", "write_file", "str_replace" -> FileToolResult(call, result)
        "bash" -> ShellToolResult(call, result)
        else -> MarkdownContent(result.detail)
    }
}

@Composable
private fun WebSearchResults(results: List<ToolSearchResult>, fallback: String) {
    if (results.isEmpty()) {
        MarkdownContent(fallback)
        return
    }
    val uriHandler = LocalUriHandler.current
    Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
        Text(stringResource(R.string.tool_sources), style = MaterialTheme.typography.labelMedium)
        results.forEach { item ->
            Column(Modifier.fillMaxWidth().padding(vertical = 4.dp), verticalArrangement = Arrangement.spacedBy(2.dp)) {
                TextButton(
                    onClick = { openExternalUri(uriHandler::openUri, item.url) },
                    enabled = isSafeExternalUrl(item.url),
                    modifier = Modifier.height(48.dp),
                ) {
                    Text(
                        item.title,
                        modifier = Modifier.weight(1f),
                        maxLines = 1,
                        overflow = TextOverflow.Ellipsis,
                    )
                    Icon(Icons.Outlined.OpenInNew, contentDescription = stringResource(R.string.open))
                }
                item.snippet.takeIf { it.isNotBlank() }?.let {
                    Text(it, style = MaterialTheme.typography.bodySmall, maxLines = 3, overflow = TextOverflow.Ellipsis)
                }
                Text(item.url, style = MaterialTheme.typography.labelSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

@Composable
private fun ImageSearchResults(results: List<ToolImageSearchResult>, fallback: String) {
    if (results.isEmpty()) {
        MarkdownContent(fallback)
        return
    }
    val uriHandler = LocalUriHandler.current
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        Text(stringResource(R.string.tool_images), style = MaterialTheme.typography.labelMedium)
        LazyRow(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
            items(results, key = { it.imageUrl.ifBlank { it.sourceUrl.ifBlank { it.title } } }) { item ->
                val target = item.sourceUrl.takeIf(::isSafeExternalUrl) ?: item.imageUrl
                Surface(
                    onClick = { openExternalUri(uriHandler::openUri, target) },
                    enabled = isSafeExternalUrl(target),
                    shape = RoundedCornerShape(6.dp),
                    color = MaterialTheme.colorScheme.surfaceVariant,
                    modifier = Modifier.size(width = 132.dp, height = 156.dp),
                ) {
                    Column(Modifier.padding(6.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                        ToolImageThumbnail(item.thumbnailUrl, item.title)
                        Text(item.title, style = MaterialTheme.typography.labelSmall, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
        }
    }
}

@Composable
private fun ToolImageThumbnail(url: String, title: String) {
    var image by remember(url) { mutableStateOf<ImageBitmap?>(null) }
    LaunchedEffect(url) { image = decodeThumbnail(url) }
    Box(
        modifier = Modifier.fillMaxWidth().height(96.dp).background(MaterialTheme.colorScheme.surfaceContainerHighest),
        contentAlignment = Alignment.Center,
    ) {
        image?.let {
            Image(
                bitmap = it,
                contentDescription = title,
                modifier = Modifier.fillMaxWidth().height(96.dp),
                contentScale = ContentScale.Crop,
            )
        } ?: Icon(Icons.Outlined.Image, contentDescription = null, tint = MaterialTheme.colorScheme.onSurfaceVariant)
    }
}

@Composable
private fun FileToolResult(call: MessageBlock.ToolCall, result: MessageBlock.ToolResult) {
    val path = toolArgument(call, "path")
    when (call.name) {
        "ls" -> {
            val entries = result.detail.lineSequence().map(String::trim).filter(String::isNotBlank).take(12).toList()
            if (entries.isEmpty()) {
                MarkdownContent(result.detail)
            } else {
                Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    path?.let { Text(it, style = MaterialTheme.typography.labelMedium) }
                    entries.forEach { entry ->
                        Row(verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Icon(
                                if (entry.endsWith('/')) Icons.Outlined.FolderOpen else Icons.Outlined.Description,
                                contentDescription = null,
                                modifier = Modifier.size(18.dp),
                            )
                            Text(entry, style = MaterialTheme.typography.bodySmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                    }
                }
            }
        }
        "read_file" -> CodeDetail(result.detail, path?.substringAfterLast('.')?.takeIf { it.isNotBlank() })
        else -> {
            Column(verticalArrangement = Arrangement.spacedBy(4.dp)) {
                path?.let { Text(it, style = MaterialTheme.typography.labelMedium) }
                MarkdownContent(result.detail)
            }
        }
    }
}

@Composable
private fun ShellToolResult(call: MessageBlock.ToolCall, result: MessageBlock.ToolResult) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        toolArgument(call, "command")?.let { CodeDetail(it, "bash") }
        Text(stringResource(R.string.tool_output), style = MaterialTheme.typography.labelMedium)
        CodeDetail(result.detail)
    }
}

internal fun parseToolSearchResults(payload: String): List<ToolSearchResult> = toolResultItems(payload).mapNotNull { item ->
    val url = item.optString("url")
    if (!isSafeExternalUrl(url)) return@mapNotNull null
    ToolSearchResult(
        title = item.optString("title").ifBlank { url },
        url = url,
        snippet = item.optString("content").ifBlank { item.optString("snippet") },
    )
}

internal fun parseToolImageSearchResults(payload: String): List<ToolImageSearchResult> = toolResultItems(payload).mapNotNull { item ->
    val sourceUrl = item.firstString("source_url", "sourceUrl", "url")
    val imageUrl = item.firstString("image_url", "imageUrl", "url")
    if (!isSafeExternalUrl(sourceUrl) && !isSafeExternalUrl(imageUrl)) return@mapNotNull null
    ToolImageSearchResult(
        title = item.optString("title").ifBlank { "Image" },
        sourceUrl = sourceUrl,
        thumbnailUrl = item.firstString("thumbnail_url", "thumbnailUrl", "image_url", "imageUrl"),
        imageUrl = imageUrl,
    )
}

private fun toolResultItems(payload: String): List<JSONObject> = runCatching {
    val root = org.json.JSONTokener(payload).nextValue()
    when (root) {
        is JSONObject -> root.optJSONArray("results").toObjectList()
        is JSONArray -> root.toObjectList()
        else -> emptyList()
    }
}.getOrDefault(emptyList())

private fun JSONArray?.toObjectList(): List<JSONObject> = buildList {
    val array = this@toObjectList ?: return@buildList
    for (index in 0 until array.length()) array.optJSONObject(index)?.let(::add)
}

private fun JSONObject.firstString(vararg names: String): String = names
    .asSequence()
    .map { optString(it) }
    .firstOrNull(String::isNotBlank)
    .orEmpty()

private fun toolArgument(call: MessageBlock.ToolCall, name: String): String? = runCatching {
    JSONObject(call.detail).optString(name).takeIf(String::isNotBlank)
}.getOrNull()

private fun isSafeExternalUrl(value: String): Boolean = runCatching {
    URI(value).let { it.scheme?.lowercase() in setOf("http", "https") && !it.host.isNullOrBlank() }
}.getOrDefault(false)

private fun openExternalUri(openUri: (String) -> Unit, value: String) {
    if (isSafeExternalUrl(value)) runCatching { openUri(value) }
}

private suspend fun decodeThumbnail(url: String): ImageBitmap? = withContext(Dispatchers.IO) {
    if (!isSafeExternalUrl(url)) return@withContext null
    runCatching {
        val bytes = URL(url).openConnection().apply {
            connectTimeout = 5_000
            readTimeout = 5_000
        }.getInputStream().use(::readThumbnailBytes)
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
        val options = BitmapFactory.Options().apply {
            inSampleSize = thumbnailSampleSize(bounds.outWidth, bounds.outHeight)
        }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)?.asImageBitmap()
    }.getOrNull()
}

private fun readThumbnailBytes(input: java.io.InputStream): ByteArray {
    val output = ByteArrayOutputStream()
    val buffer = ByteArray(8_192)
    var remaining = MAX_THUMBNAIL_BYTES
    while (remaining > 0) {
        val read = input.read(buffer, 0, minOf(buffer.size, remaining))
        if (read < 0) break
        output.write(buffer, 0, read)
        remaining -= read
    }
    return output.toByteArray()
}

private fun thumbnailSampleSize(width: Int, height: Int): Int {
    var sample = 1
    while (width / sample > 256 || height / sample > 256) sample *= 2
    return sample
}

private const val MAX_THUMBNAIL_BYTES = 1_500_000
