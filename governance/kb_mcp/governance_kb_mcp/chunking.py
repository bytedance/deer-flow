from dataclasses import dataclass


@dataclass
class DocumentChunk:
    content: str
    source_file: str
    line_range: str
    char_offset: int


def chunk_document(
    content: str,
    source_file: str,
    max_chunk_size: int = 1000,
) -> list[DocumentChunk]:
    if not content.strip():
        return []

    chunks: list[DocumentChunk] = []
    paragraphs = content.split("\n\n")
    current_line = 1
    char_offset = 0

    for para in paragraphs:
        para_lines = para.split("\n")
        para_line_count = len(para_lines)
        para_text = para.strip()

        if not para_text:
            current_line += para_line_count + 1
            char_offset += len(para) + 2
            continue

        start_line = current_line
        end_line = current_line + para_line_count - 1

        if len(para_text) <= max_chunk_size:
            chunks.append(
                DocumentChunk(
                    content=para_text,
                    source_file=source_file,
                    line_range=f"{start_line}-{end_line}",
                    char_offset=char_offset,
                )
            )
        else:
            offset_in_para = 0
            while offset_in_para < len(para_text):
                sub = para_text[offset_in_para : offset_in_para + max_chunk_size]
                chunks.append(
                    DocumentChunk(
                        content=sub,
                        source_file=source_file,
                        line_range=f"{start_line}-{end_line}",
                        char_offset=char_offset + offset_in_para,
                    )
                )
                offset_in_para += max_chunk_size

        current_line += para_line_count + 1
        char_offset += len(para) + 2

    return chunks
