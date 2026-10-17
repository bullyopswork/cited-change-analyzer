"""Bounded XML extraction with canonical paragraph text and raw-byte provenance."""

from __future__ import annotations

import hashlib
import re
import unicodedata
import xml.etree.ElementTree as ET
from datetime import date as Date
from urllib.parse import urlsplit

MAX_XML_BYTES = 32 * 1024 * 1024
BLOCKS = {"P", "FP", "HD", "HEAD", "HEADING", "SUBJECT", "SECTNO", "HED",
          "LI", "ROW", "TR", "DIV", "DIV1", "DIV2", "DIV3", "DIV4", "DIV5",
          "DIV6", "DIV7", "DIV8", "DIV9", "TABLE", "AUTH", "SOURCE"}


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].upper()


def normalize(text: str) -> str:
    """NFC and whitespace normalization, preserving blank-line paragraph breaks."""
    text = unicodedata.normalize("NFC", text.replace("\r\n", "\n").replace("\r", "\n"))
    paragraphs = re.split(r"\n[ \t]*\n+", text)
    return "\n\n".join(" ".join(part.split()) for part in paragraphs if part.strip())


def _section_text(element: ET.Element) -> str:
    pieces: list[str] = []

    def visit(node: ET.Element) -> None:
        block = _tag(node) in BLOCKS
        if block:
            pieces.append("\n\n")
        if node.text:
            pieces.append(node.text)
        for child in node:
            visit(child)
            # Child tails belong to the parent and are emitted exactly once.
            if child.tail:
                pieces.append(child.tail)
        if block:
            pieces.append("\n\n")

    visit(element)
    return normalize("".join(pieces))


def check_metadata(metadata: dict) -> None:
    for key in ("date", "url", "snapshot_sha256"):
        if not isinstance(metadata.get(key), str):
            raise ValueError(f"source {key} must be a string")
    parsed_date = Date.fromisoformat(metadata["date"])
    if parsed_date.isoformat() != metadata["date"]:
        raise ValueError("source date must be YYYY-MM-DD")
    source_kind = metadata.get("source_kind")
    if source_kind == "local":
        if metadata["url"] != "":
            raise ValueError("local source url must be empty")
        filename = metadata.get("filename")
        if (not isinstance(filename, str) or not filename.strip() or
                filename in {".", ".."} or re.search(r"[/\\\x00-\x1f\x7f]", filename)):
            raise ValueError("local source filename must be a basename without control characters")
        if metadata.get("format") not in ("text", "pdf"):
            raise ValueError("local source format must be text or pdf")
        warnings = metadata.get("extraction_warnings")
        if not isinstance(warnings, list) or any(not isinstance(w, str) for w in warnings):
            raise ValueError("local extraction_warnings must be a list of strings")
        pages = metadata.get("pages")
        if metadata["format"] == "pdf":
            if not isinstance(pages, list) or not 1 <= len(pages) <= 50:
                raise ValueError("local PDF pages must contain 1 to 50 page ranges")
            previous_end = -2
            for number, page in enumerate(pages, 1):
                if (not isinstance(page, dict) or
                        any(type(page.get(k)) is not int for k in ("number", "start", "end")) or
                        page["number"] != number or page["start"] != previous_end + 2 or
                        not page["start"] <= page["end"] <= 100_000):
                    raise ValueError("local PDF page ranges must be ordered, numbered, bounded offsets")
                previous_end = page["end"]
        elif pages not in (None, []):
            raise ValueError("local text sources must not declare PDF page ranges")
    else:
        if source_kind not in (None, "external"):
            raise ValueError("source_kind must be local or external")
        parsed_url = urlsplit(metadata["url"])
        if parsed_url.scheme not in {"https", "http"} or not parsed_url.hostname:
            raise ValueError("source url must be absolute HTTP(S)")
        if parsed_url.username or parsed_url.password:
            raise ValueError("source url must not include credentials")
    if not re.fullmatch(r"[0-9a-f]{64}", metadata["snapshot_sha256"]):
        raise ValueError("snapshot_sha256 must be a lowercase SHA-256 hex digest")


def extract_snapshot(xml: bytes | str, *, date: str, url: str,
                     max_bytes: int = MAX_XML_BYTES) -> dict:
    """Extract eCFR DIV TYPE=SECTION or SECTION elements from a dated XML body.

    Digest identifies the XML bytes, not a section string. Missing sections may be
    represented only after a complete successful parse containing section records.
    """
    raw = xml.encode("utf-8") if isinstance(xml, str) else xml
    if not isinstance(raw, bytes) or not raw or len(raw) > max_bytes:
        raise ValueError("XML body is empty, invalid, or exceeds the byte limit")
    try:
        decoded = raw.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("snapshot XML must be UTF-8") from error
    # ElementTree expands internal entities. Reject DTDs rather than accepting
    # amplification or external-entity-dependent regulatory documents.
    if re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", decoded, re.IGNORECASE):
        raise ValueError("DTD/entity declarations are not accepted")
    metadata = {"date": date, "url": url,
                "snapshot_sha256": hashlib.sha256(raw).hexdigest()}
    check_metadata(metadata)
    try:
        root = ET.fromstring(decoded)
    except ET.ParseError as error:
        raise ValueError(f"malformed XML: {error}") from error
    stack = [(root, 0)]
    elements = 0
    while stack:
        node, depth = stack.pop()
        elements += 1
        if depth > 128 or elements > 200_000:
            raise ValueError("XML nesting or element limit exceeded")
        stack.extend((child, depth + 1) for child in node)
    sections: dict[str, dict] = {}
    for element in root.iter():
        tag = _tag(element)
        attrs = {key.upper(): value for key, value in element.attrib.items()}
        if tag != "SECTION" and attrs.get("TYPE", "").upper() != "SECTION":
            continue
        identifier = attrs.get("N") or attrs.get("ID") or attrs.get("SECTNO")
        if not identifier:
            number = next((child for child in element if _tag(child) == "SECTNO"), None)
            identifier = "".join(number.itertext()).strip() if number is not None else None
        if not identifier:
            raise ValueError("section without an identifier")
        identifier = re.sub(r"^§\s*", "", identifier).strip()
        if identifier in sections:
            raise ValueError(f"duplicate section identifier: {identifier}")
        heading = next((child for child in element
                        if _tag(child) in {"HEAD", "HD", "HED", "SUBJECT", "HEADING"}), None)
        title = normalize("".join(heading.itertext())) if heading is not None else identifier
        sections[identifier] = {"section": identifier, "title": title,
                                "text": _section_text(element)}
    if not sections:
        raise ValueError("XML contains no identifiable section records; absence cannot be inferred")
    return {**metadata, "sections": sections, "byte_length": len(raw)}


def section_source(snapshot: dict, section: str) -> dict:
    """Return contract source metadata/text, including a proven missing section."""
    check_metadata(snapshot)
    if not isinstance(snapshot.get("sections"), dict) or not snapshot["sections"]:
        raise ValueError("a successfully extracted snapshot with sections is required")
    record = snapshot["sections"].get(section)
    return {key: snapshot[key] for key in ("date", "url", "snapshot_sha256")} | {
        "text": record["text"] if record else ""}
