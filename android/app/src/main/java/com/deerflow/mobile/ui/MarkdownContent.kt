package com.deerflow.mobile.ui

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.ClickableText
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalUriHandler
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import com.deerflow.mobile.R
import java.net.URI
import org.commonmark.ext.gfm.strikethrough.Strikethrough
import org.commonmark.ext.gfm.strikethrough.StrikethroughExtension
import org.commonmark.ext.gfm.tables.TableBlock
import org.commonmark.ext.gfm.tables.TableCell
import org.commonmark.ext.gfm.tables.TableRow
import org.commonmark.ext.gfm.tables.TablesExtension
import org.commonmark.node.BlockQuote
import org.commonmark.node.BulletList
import org.commonmark.node.Code
import org.commonmark.node.Emphasis
import org.commonmark.node.FencedCodeBlock
import org.commonmark.node.HardLineBreak
import org.commonmark.node.Heading
import org.commonmark.node.HtmlInline
import org.commonmark.node.Image
import org.commonmark.node.IndentedCodeBlock
import org.commonmark.node.Link
import org.commonmark.node.ListItem
import org.commonmark.node.Node
import org.commonmark.node.OrderedList
import org.commonmark.node.Paragraph
import org.commonmark.node.SoftLineBreak
import org.commonmark.node.StrongEmphasis
import org.commonmark.node.Text as MarkdownTextNode
import org.commonmark.node.ThematicBreak
import org.commonmark.parser.Parser

private val markdownParser = Parser.builder()
    .extensions(listOf(StrikethroughExtension.create(), TablesExtension.create()))
    .build()

@Composable
fun MarkdownContent(markdown: String, modifier: Modifier = Modifier, onArtifact: (String) -> Unit = {}) {
    val document = remember(markdown) { markdownParser.parse(markdown) }
    val citations = remember(markdown) { document.citationSources() }
    Column(modifier, verticalArrangement = Arrangement.spacedBy(8.dp)) {
        document.children().forEach { MarkdownBlock(it, onArtifact) }
        CitationSources(citations)
    }
}

@Composable
private fun MarkdownBlock(node: Node, onArtifact: (String) -> Unit) {
    when (node) {
        is Heading -> MarkdownInline(
            node,
            style = when (node.level) {
                1 -> MaterialTheme.typography.headlineSmall
                2 -> MaterialTheme.typography.titleLarge
                3 -> MaterialTheme.typography.titleMedium
                else -> MaterialTheme.typography.titleSmall
            }.copy(fontWeight = FontWeight.SemiBold),
        )
        is Paragraph -> MarkdownInline(node, MaterialTheme.typography.bodyLarge, onArtifact)
        is FencedCodeBlock -> MarkdownCode(node.literal, node.info.takeIf { it.isNotBlank() })
        is IndentedCodeBlock -> MarkdownCode(node.literal, null)
        is BlockQuote -> Row(Modifier.fillMaxWidth()) {
            Box(Modifier.width(3.dp).height(48.dp).background(MaterialTheme.colorScheme.primary))
            Column(Modifier.padding(start = 12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                node.children().forEach { MarkdownBlock(it, onArtifact) }
            }
        }
        is BulletList -> MarkdownList(node, ordered = false, onArtifact = onArtifact)
        is OrderedList -> MarkdownList(node, ordered = true, start = node.markerStartNumber, onArtifact = onArtifact)
        is TableBlock -> MarkdownTable(node, onArtifact)
        is ThematicBreak -> HorizontalDivider()
        else -> node.children().forEach { MarkdownBlock(it, onArtifact) }
    }
}

@Composable
private fun MarkdownList(node: Node, ordered: Boolean, start: Int = 1, onArtifact: (String) -> Unit) {
    Column(verticalArrangement = Arrangement.spacedBy(6.dp)) {
        node.children().filterIsInstance<ListItem>().forEachIndexed { index, item ->
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.Top) {
                Text(
                    if (ordered) "${start + index}." else "\u2022",
                    style = MaterialTheme.typography.bodyLarge,
                    modifier = Modifier.width(28.dp),
                )
                Column(Modifier.weight(1f), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                    item.children().forEach { MarkdownBlock(it, onArtifact) }
                }
            }
        }
    }
}

@Composable
private fun MarkdownTable(table: TableBlock, onArtifact: (String) -> Unit) {
    val scroll = rememberScrollState()
    Surface(
        shape = MaterialTheme.shapes.small,
        modifier = Modifier.fillMaxWidth().border(1.dp, MaterialTheme.colorScheme.outlineVariant, MaterialTheme.shapes.small),
    ) {
        Column(Modifier.horizontalScroll(scroll)) {
            table.children()
                .flatMap { section -> section.children() }
                .filterIsInstance<TableRow>()
                .forEach { row ->
                    val header = row.children().filterIsInstance<TableCell>().firstOrNull()?.isHeader == true
                    Row(Modifier.fillMaxWidth()) {
                        row.children().filterIsInstance<TableCell>().forEach { cell ->
                            Column(
                                modifier = Modifier
                                    .width(160.dp)
                                    .border(0.5.dp, MaterialTheme.colorScheme.outlineVariant)
                                    .padding(8.dp),
                            ) {
                                MarkdownInline(
                                    cell,
                                    (if (header) MaterialTheme.typography.labelLarge else MaterialTheme.typography.bodyMedium),
                                    onArtifact,
                                )
                            }
                        }
                    }
                }
        }
    }
}

@Composable
private fun MarkdownCode(code: String, language: String?) {
    Surface(color = MaterialTheme.colorScheme.surfaceVariant, shape = MaterialTheme.shapes.small) {
        Column(Modifier.fillMaxWidth().padding(12.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            language?.let { Text(it, style = MaterialTheme.typography.labelMedium) }
            Text(code.trimEnd(), style = MaterialTheme.typography.bodyMedium.copy(fontFamily = FontFamily.Monospace))
        }
    }
}

@Suppress("DEPRECATION")
@Composable
private fun MarkdownInline(node: Node, style: TextStyle, onArtifact: (String) -> Unit = {}) {
    val primary = MaterialTheme.colorScheme.primary
    val codeBackground = MaterialTheme.colorScheme.surfaceVariant
    val value = remember(node, primary, codeBackground) {
        buildAnnotatedString { appendInlineChildren(node, primary, codeBackground) }
    }
    val uriHandler = LocalUriHandler.current
    ClickableText(
        text = value,
        style = style.copy(color = MaterialTheme.colorScheme.onSurface),
        onClick = { offset ->
            value.getStringAnnotations("URL", offset, offset).firstOrNull()?.let { link ->
                if (link.item.isArtifactPath()) onArtifact(link.item)
                else runCatching { uriHandler.openUri(link.item) }
            }
        },
    )
}

private fun String.isArtifactPath(): Boolean = startsWith("/mnt/") || startsWith("mnt/") || startsWith("sandbox:/mnt/")

private fun AnnotatedString.Builder.appendInlineChildren(node: Node, primary: Color, codeBackground: Color) {
    node.children().forEach { child ->
        when (child) {
            is MarkdownTextNode -> append(child.literal)
            is Code -> withStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = codeBackground)) { append(child.literal) }
            is Emphasis -> withStyle(SpanStyle(fontStyle = FontStyle.Italic)) { appendInlineChildren(child, primary, codeBackground) }
            is StrongEmphasis -> withStyle(SpanStyle(fontWeight = FontWeight.Bold)) { appendInlineChildren(child, primary, codeBackground) }
            is Strikethrough -> withStyle(SpanStyle(textDecoration = TextDecoration.LineThrough)) { appendInlineChildren(child, primary, codeBackground) }
            is Link -> {
                val citation = child.citationSource()
                if (citation != null) {
                    withStyle(
                        SpanStyle(
                            color = primary,
                            background = primary.copy(alpha = 0.14f),
                            fontWeight = FontWeight.Medium,
                        ),
                    ) {
                        append(" ${citation.title} ")
                    }
                } else {
                    pushStringAnnotation("URL", child.destination)
                    withStyle(SpanStyle(color = primary, textDecoration = TextDecoration.Underline)) {
                        appendInlineChildren(child, primary, codeBackground)
                    }
                    pop()
                }
            }
            is Image -> append(child.title.ifBlank { child.destination })
            is SoftLineBreak -> append(' ')
            is HardLineBreak -> append('\n')
            is HtmlInline -> append(child.literal)
            else -> appendInlineChildren(child, primary, codeBackground)
        }
    }
}

internal data class CitationSource(val title: String, val url: String, val domain: String, val count: Int)

@Composable
private fun CitationSources(sources: List<CitationSource>) {
    if (sources.isEmpty()) return
    val uriHandler = LocalUriHandler.current
    val primary = MaterialTheme.colorScheme.primary
    Column(
        modifier = Modifier
            .fillMaxWidth()
            .background(MaterialTheme.colorScheme.surfaceVariant, MaterialTheme.shapes.small)
            .padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(6.dp),
    ) {
        Text(
            stringResource(R.string.citation_sources, sources.size),
            style = MaterialTheme.typography.labelLarge,
            color = MaterialTheme.colorScheme.onSurfaceVariant,
        )
        sources.forEach { source ->
            val link = remember(source, primary) {
                buildAnnotatedString {
                    pushStringAnnotation("URL", source.url)
                    withStyle(SpanStyle(color = primary, textDecoration = TextDecoration.Underline)) {
                        append(source.title)
                    }
                    pop()
                    append(" · ${source.domain}")
                    if (source.count > 1) append(" ×${source.count}")
                }
            }
            ClickableText(
                text = link,
                style = MaterialTheme.typography.bodyMedium.copy(color = MaterialTheme.colorScheme.onSurface),
                onClick = { offset ->
                    link.getStringAnnotations("URL", offset, offset).firstOrNull()?.let { reference ->
                        runCatching { uriHandler.openUri(reference.item) }
                    }
                },
            )
        }
    }
}

internal fun citationSources(markdown: String): List<CitationSource> {
    val sources = linkedNodes(markdownParser.parse(markdown))
        .mapNotNull(Link::citationSource)
        .groupBy { it.url }
    return sources.values.map { matches ->
        val source = matches.first()
        source.copy(count = matches.size)
    }
}

private fun Node.citationSources(): List<CitationSource> = linkedNodes(this)
    .mapNotNull(Link::citationSource)
    .groupBy { it.url }
    .values
    .map { matches -> matches.first().copy(count = matches.size) }

private fun linkedNodes(node: Node): Sequence<Link> = sequence {
    if (node is Link) yield(node)
    node.children().forEach { child -> yieldAll(linkedNodes(child)) }
}

private fun Link.citationSource(): CitationSource? {
    val url = destination.takeIf { it.startsWith("http://") || it.startsWith("https://") } ?: return null
    val rawTitle = inlineText(this).trim()
    if (!rawTitle.startsWith("citation:", ignoreCase = true)) return null
    val domain = runCatching { URI(url).host.removePrefix("www.") }.getOrNull().orEmpty().ifBlank { url }
    val title = rawTitle.substringAfter(':').trim()
        .takeUnless { it.equals("source", ignoreCase = true) || it == "来源" }
        .orEmpty()
        .ifBlank { domain }
    return CitationSource(title = title, url = url, domain = domain, count = 1)
}

private fun inlineText(node: Node): String = buildString {
    node.children().forEach { child ->
        when (child) {
            is MarkdownTextNode -> append(child.literal)
            is Code -> append(child.literal)
            is SoftLineBreak, is HardLineBreak -> append(' ')
            else -> append(inlineText(child))
        }
    }
}

private inline fun AnnotatedString.Builder.withStyle(style: SpanStyle, block: AnnotatedString.Builder.() -> Unit) {
    pushStyle(style)
    try {
        block()
    } finally {
        pop()
    }
}

private fun Node.children(): Sequence<Node> = sequence {
    var child = firstChild
    while (child != null) {
        yield(child)
        child = child.next
    }
}
