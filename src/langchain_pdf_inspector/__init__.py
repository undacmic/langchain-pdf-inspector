"""`langchain-pdf-inspector` integration package.

Exposes `PdfInspectorLoader` and `PdfInspectorParser` for loading and parsing
PDF files into LangChain documents via the `pdf-inspector` library.
"""

from .pdf_inspector_loader import PdfInspectorLoader
from .pdf_inspector_parser import PdfInspectorParser

__all__ = [
    "PdfInspectorLoader",
    "PdfInspectorParser",
]

__version__ = "0.1.1"
