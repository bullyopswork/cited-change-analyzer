"""Standard-library cited-change engine. Offsets are Unicode code points."""

from .engine import compare_texts
from .extraction import extract_snapshot, normalize, section_source
from .fetch import FetchError, fetch_bytes, fetch_snapshot
from .reports import export_html, export_json
from .validation import validate

__all__ = ["compare_texts", "extract_snapshot", "normalize", "section_source",
           "FetchError", "fetch_bytes", "fetch_snapshot", "export_html",
           "export_json", "validate"]
