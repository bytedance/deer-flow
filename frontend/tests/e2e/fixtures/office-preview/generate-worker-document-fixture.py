"""Synthetic OOXML relationship fixture; no user data."""
import struct
import zlib
from io import BytesIO
from pathlib import Path

from docx import Document
from docx.shared import Inches


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
png += chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00\x00\xff\x00" * 2)) + chunk(b"IEND", b"")
document = Document()
document.add_heading("Worker resource document", 1)
document.add_paragraph("Body text survives worker parsing.")
document.add_picture(BytesIO(png), width=Inches(0.25))
document.sections[0].header.paragraphs[0].text = "Worker header text"
document.sections[0].footer.paragraphs[0].text = "Worker footer text"
document.save(Path(__file__).with_name("worker-resources.docx"))
