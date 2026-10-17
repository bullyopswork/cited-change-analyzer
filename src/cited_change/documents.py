"""Local, bounded UTF-8 TXT and selectable-text PDF extraction; no OCR or I/O."""

from __future__ import annotations

import hashlib
import io
import re
from datetime import datetime, timezone

from .extraction import check_metadata

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 50
MAX_CHARACTERS = 100_000
MAX_PDF_DECODED_BYTES = 2 * 1024 * 1024
MAX_PAGE_CONTENT_STREAMS = 128


def _bounded_pdf_content(page):
    """Check aggregate decoded page content before pypdf concatenates it.

    Count repeated references again: a tiny stream array may otherwise expand
    the same cached bytes thousands of times inside extract_text().
    """
    from pypdf.generic import ArrayObject, IndirectObject, StreamObject
    content = page.get('/Contents')
    if content is None:
        return
    seen = set()
    for _ in range(16):
        if not isinstance(content, IndirectObject):
            break
        identity = (content.idnum, content.generation)
        if identity in seen:
            raise DocumentError("PDF page content contains a reference cycle")
        seen.add(identity)
        content = content.get_object()
    else:
        raise DocumentError("PDF page content nesting exceeds the supported limit")
    streams = content if isinstance(content, ArrayObject) else [content]
    if len(streams) > MAX_PAGE_CONTENT_STREAMS:
        raise DocumentError("PDF page content exceeds the supported stream count")
    decoded = 0
    for stream in streams:
        seen = set()
        for _ in range(16):
            if not isinstance(stream, IndirectObject):
                break
            identity = (stream.idnum, stream.generation)
            if identity in seen:
                raise DocumentError("PDF page content contains a reference cycle")
            seen.add(identity)
            stream = stream.get_object()
        else:
            raise DocumentError("PDF page content nesting exceeds the supported limit")
        if not isinstance(stream, StreamObject):
            raise DocumentError("PDF page content must contain bounded streams")
        decoded += len(stream.get_data())
        if decoded > MAX_PDF_DECODED_BYTES:
            raise DocumentError("PDF page decoded content exceeds the 2 MiB complexity limit")


class DocumentError(ValueError):
    """A local input cannot be completely extracted within the supported bounds."""


def _display_text(text: str) -> str:
    # Preserve all other whitespace and Unicode: offsets refer to this exact
    # inspectable string, not PDF byte offsets or a hidden normalized copy.
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _pdf_text(raw: bytes) -> tuple[str, list[dict], list[str]]:
    try:
        from pypdf import PdfReader, apply_configuration
    except ImportError:
        raise DocumentError("PDF support requires pypdf>=6.21.1,<7") from None
    # Context-local public parser configuration bounds allocation and aggregate
    # repeated-stream work before extract_text, not only its eventual output.
    with apply_configuration(
        maximum_declared_stream_length=MAX_PDF_DECODED_BYTES,
        array_based_stream_maximum_output_length=MAX_PDF_DECODED_BYTES,
        array_maximum_element_count=4096,
        dictionary_maximum_element_count=4096,
        zlib_maximum_output_length=MAX_PDF_DECODED_BYTES,
        lzw_maximum_output_length=MAX_PDF_DECODED_BYTES,
        run_length_maximum_output_length=MAX_PDF_DECODED_BYTES,
        brotli_maximum_output_length=MAX_PDF_DECODED_BYTES,
        stream_decoding_work_maximum_length=8 * 1024 * 1024,
        stream_parsing_work_maximum_count=100_000,
        xform_maximum_invocations_per_extraction=100,
        page_tree_maximum_entries=1000,
    ):
        return _read_pdf(raw, PdfReader)


def _read_pdf(raw, PdfReader):
    warnings = ["PDF text is extracted in reading order reported by the parser; "
                "layout, tables, images and signatures are not compared. No OCR is performed."]
    try:
        if not raw.startswith(b"%PDF-"):
            raise DocumentError("Malformed PDF: missing PDF header")
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted:
            raise DocumentError("Encrypted PDFs are not supported, even with an empty password")
        if not 1 <= len(reader.pages) <= MAX_PDF_PAGES:
            raise DocumentError("PDF must contain 1 to 50 pages")
        pieces, pages, length = [], [], 0
        for number, page in enumerate(reader.pages, 1):
            _bounded_pdf_content(page)
            extracted = _display_text(page.extract_text() or "")
            start = length + (2 if pieces else 0)
            length = start + len(extracted)
            if length > MAX_CHARACTERS:
                raise DocumentError("Extracted document exceeds 100000 code points")
            if not extracted.strip():
                warnings.append(f"Page {number} has no selectable text; any images on it are not analyzed.")
            pieces.append(extracted)
            pages.append({"number": number, "start": start, "end": length})
        text = "\n\n".join(pieces)
        if not text.strip():
            raise DocumentError("PDF contains no selectable text; empty or scanned PDFs require OCR elsewhere")
        return text, pages, warnings
    except DocumentError:
        raise
    except Exception:
        # Parser internals may include attacker-controlled PDF object content.
        raise DocumentError("Malformed or unsupported PDF; selectable text could not be extracted") from None


def extract_document(raw: bytes, filename: str) -> dict:
    """Extract a complete local source, hashing original bytes, never a path.

    The UTC date records import time, not a claimed publication/effective date.
    Parent callers isolate parsing in a memory/time-bounded worker process.
    """
    if not isinstance(raw, bytes) or not raw:
        raise DocumentError("Document must contain nonempty bytes")
    if len(raw) > MAX_FILE_BYTES:
        raise DocumentError("Document exceeds the 10 MiB file limit")
    if not isinstance(filename, str):
        raise DocumentError("Document filename must be a string")
    basename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if (not basename.strip() or basename in {".", ".."} or
            re.search(r"[\x00-\x1f\x7f]", basename)):
        raise DocumentError("Document filename must have a basename without control characters")
    suffix = basename.rsplit(".", 1)[-1].lower() if "." in basename else ""
    if suffix not in {"txt", "pdf"}:
        raise DocumentError("Unsupported document type; choose a UTF-8 .txt or selectable-text .pdf file")
    if suffix == "txt":
        try:
            text = _display_text(raw.decode("utf-8-sig"))
        except UnicodeDecodeError:
            raise DocumentError("TXT documents must be valid UTF-8") from None
        if re.search(r"[\x00-\x08\x0e-\x1f]", text):
            raise DocumentError("TXT document contains binary control characters")
        pages, warnings = None, []
    else:
        text, pages, warnings = _pdf_text(raw)
    if not text.strip():
        raise DocumentError("Document contains no non-whitespace text")
    if len(text) > MAX_CHARACTERS:
        raise DocumentError("Extracted document exceeds 100000 code points")
    snapshot = {"date": datetime.now(timezone.utc).date().isoformat(), "url": "",
                "snapshot_sha256": hashlib.sha256(raw).hexdigest(), "text": text,
                "source_kind": "local", "filename": basename,
                "format": "text" if suffix == "txt" else "pdf",
                "extraction_warnings": warnings}
    if pages is not None:
        snapshot["pages"] = pages
    check_metadata(snapshot)
    return snapshot
