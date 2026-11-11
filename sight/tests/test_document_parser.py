"""Unit tests for Stage 8 Deep Document Parser."""
from __future__ import annotations

import io
from pathlib import Path
import pytest

from sight_core.document_parser import DocumentParser

try:
    import pypdf
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


def test_markdown_parser_sections_and_tables():
    md_content = """# Executive Briefing
This is the executive summary paragraph.

| Metric | Target | Actual |
| --- | --- | --- |
| Accuracy | 99.0% | 99.4% |
| Latency | < 50ms | 18ms |

## Code Implementation
```python
def execute():
    return True
```
"""
    parser = DocumentParser()
    doc = parser.parse_markdown(md_content, filename="briefing.md")

    assert doc.file_type == "markdown"
    assert len(doc.sections) >= 3
    assert len(doc.tables) == 1
    assert doc.tables[0].headers == ["Metric", "Target", "Actual"]
    assert len(doc.tables[0].rows) == 2

    # Verify code block was extracted
    code_sections = [s for s in doc.sections if s.section_type == "code"]
    assert len(code_sections) == 1
    assert "def execute():" in code_sections[0].content


def test_latex_parser_sections():
    tex_content = r"""\title{BEL Multimodal Paper}
\section{Introduction}
This paper explores multimodal cognitive architecture.
\subsection{Acoustic Engine}
We measure spectral centroids and zero crossing rates.
"""
    parser = DocumentParser()
    doc = parser.parse_latex(tex_content, filename="paper.tex")

    assert doc.file_type == "latex"
    assert doc.title == "BEL Multimodal Paper"
    headers = [s.title for s in doc.sections if s.section_type == "header"]
    assert "Introduction" in headers
    assert "Acoustic Engine" in headers


@pytest.mark.skipif(not HAS_PYPDF, reason="pypdf not installed")
def test_pdf_bytes_parser():
    # Build a minimal valid PDF in memory using pypdf
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buf = io.BytesIO()
    writer.write(buf)
    pdf_bytes = buf.getvalue()

    parser = DocumentParser()
    doc = parser.parse_pdf_bytes(pdf_bytes, filename="test.pdf")

    assert doc.file_type == "pdf"
    assert doc.total_pages == 1
