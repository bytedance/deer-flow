"""Single owner of the rule deciding which workspace bytes count as text.

Two independent readers turn the same workspace files into text for a human or a
model to look at: ``LocalSandbox.read_file`` (what the ``read_file`` tool shows
the agent) and ``workspace_changes.scanner`` (what the change panel diffs). When
they disagree, a file the panel renders fine is reported to the agent as binary —
the exact drift #3966 fixed on the scanner side alone, leaving the tool behind.
Keeping the rule here means a third reader cannot quietly invent a fourth answer.

The rule is deliberately narrow:

- UTF-8, with or without a BOM. ``utf-8-sig`` is the default codec rather than a
  special case because it decodes plain UTF-8 unchanged and strips a BOM when one
  is present, so a Windows-authored file no longer arrives with a stray ``\\ufeff``
  at offset 0 — invisible in the model's context, but enough to break a leading
  ``str_replace`` match or a YAML/JSON parse.
- UTF-16, only when the file declares its byte order with a BOM. Without one there
  is nothing to separate UTF-16 from bytes that merely resemble it, and ASCII-range
  UTF-16-LE is itself valid UTF-8 (the NUL padding decodes to U+0000), so such a
  file comes back NUL-riddled rather than raising. Callers that must reject it can
  screen for embedded NULs the way ``workspace_changes.scanner`` already does.

Legacy encodings (CP949, Shift-JIS, GBK, latin-1, ...) are **not** guessed. A
wrong guess decodes without raising and yields silently corrupted text, which is
strictly worse for a caller that cannot see the original bytes than an explicit
failure it can report and route around.
"""

from __future__ import annotations

from codecs import BOM_UTF16_BE, BOM_UTF16_LE

#: Byte-order marks that select the UTF-16 codec. Public so readers that sniff a
#: file themselves classify the same prefixes this module does.
UTF16_BOMS = (BOM_UTF16_LE, BOM_UTF16_BE)

#: Codec to continue an existing file with, per byte-order mark. These are the
#: BOM-less UTF-16 variants on purpose: the ``utf-16`` codec emits a fresh BOM on
#: its first write, which mid-file is data, not a mark.
_APPEND_ENCODING_BY_BOM = ((BOM_UTF16_LE, "utf-16-le"), (BOM_UTF16_BE, "utf-16-be"))

#: Bytes a caller must supply to :func:`detect_text_encoding`. Streaming readers
#: need only this many; the UTF-8 BOM needs no sniffing because ``utf-8-sig``
#: handles its presence and absence alike.
BOM_PREFIX_SIZE = max(len(bom) for bom in UTF16_BOMS)

UTF8_ENCODING = "utf-8-sig"
UTF16_ENCODING = "utf-16"


def detect_text_encoding(prefix: bytes) -> str:
    """Return the codec to decode a file whose leading bytes are ``prefix``.

    ``prefix`` need only hold :data:`BOM_PREFIX_SIZE` bytes; passing the whole
    file is allowed but never necessary, which is what lets a streaming reader
    pick a codec without buffering the content.

    The returned codec may still fail on the full content — that failure is how
    non-text bytes are rejected — so callers must handle ``UnicodeDecodeError``.
    """
    return UTF16_ENCODING if prefix.startswith(UTF16_BOMS) else UTF8_ENCODING


def detect_append_encoding(prefix: bytes) -> str:
    """Return the codec that continues a file whose leading bytes are ``prefix``.

    This is not :func:`detect_text_encoding`: appending must match the existing
    bytes without re-emitting a byte-order mark, so a UTF-16 file continues in its
    BOM-less variant. Writing UTF-8 onto UTF-16 (or a second BOM into the middle)
    leaves a file that no decoder can read back — including the one that was
    reading it a moment earlier.

    A UTF-8 BOM needs no special case: appending UTF-8 after it stays valid.
    """
    for bom, encoding in _APPEND_ENCODING_BY_BOM:
        if prefix.startswith(bom):
            return encoding
    return "utf-8"


def decode_text_bytes(data: bytes) -> str | None:
    """Decode ``data`` as text, or return ``None`` when it is not text.

    ``None`` covers both genuinely binary content and text in an encoding this
    rule declines to guess; callers that need to tell those apart must do so from
    the content itself.
    """
    try:
        return data.decode(detect_text_encoding(data))
    except UnicodeDecodeError:
        return None
