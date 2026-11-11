"""Deep Document Parsing and Layout-Aware Analysis Subsystem for BEL (Stage 8).

Extracts structured sections, tables, headers, metadata, and code blocks
from PDF, Markdown, LaTeX, and technical text documents.
"""
from __future__ import annotations

import io
from pathlib import Path
import re
from typing import Any, Sequence

from pydantic import BaseModel, ConfigDict, Field

try:
    import pypdf
    HAS_PYPDF = True
except ImportError:
    HAS_PYPDF = False


class DocumentSection(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = ""
    level: int = 1
    content: str
    section_type: str = "paragraph"  # header, paragraph, table, code, list
    page_number: int = 1


class StructuredTable(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = "Table"
    headers: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)
    raw_markdown: str = ""


class StructuredDocument(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str
    author: str = ""
    total_pages: int = 1
    file_type: str  # pdf, markdown, latex, text
    sections: list[DocumentSection] = Field(default_factory=list)
    tables: list[StructuredTable] = Field(default_factory=list)
    full_text: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentParser:
    """Parses PDF, Markdown, LaTeX, and technical text files into structured schemas."""

    def parse_file(self, file_path: Path | str) -> StructuredDocument:
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"Document file not found: '{file_path}'")

        ext = p.suffix.lower()
        if ext == ".pdf":
            return self.parse_pdf_bytes(p.read_bytes(), filename=p.name)
        elif ext in (".md", ".markdown"):
            return self.parse_markdown(p.read_text(encoding="utf-8", errors="replace"), filename=p.name)
        elif ext in (".tex", ".latex"):
            return self.parse_latex(p.read_text(encoding="utf-8", errors="replace"), filename=p.name)
        else:
            return self._parse_generic_text(p.read_text(encoding="utf-8", errors="replace"), filename=p.name)

    def parse_pdf_bytes(self, pdf_bytes: bytes, filename: str = "document.pdf") -> StructuredDocument:
        sections: list[DocumentSection] = []
        tables: list[StructuredTable] = []
        all_text_parts: list[str] = []
        metadata: dict[str, Any] = {}
        total_pages = 1
        title = Path(filename).stem

        if HAS_PYPDF:
            try:
                reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
                total_pages = len(reader.pages)
                if reader.metadata:
                    meta = reader.metadata
                    metadata["author"] = meta.author or ""
                    metadata["creator"] = meta.creator or ""
                    metadata["producer"] = meta.producer or ""
                    if meta.title:
                        title = meta.title

                for idx, page in enumerate(reader.pages, start=1):
                    page_text = page.extract_text() or ""
                    all_text_parts.append(page_text)

                    # Break page text into paragraphs and detect potential tables
                    paragraphs = page_text.split("\n\n")
                    for para in paragraphs:
                        clean_para = para.strip()
                        if not clean_para:
                            continue

                        # Simple table heuristic: lines with multiple tabs or consistent delimiters
                        lines = clean_para.splitlines()
                        if len(lines) >= 2 and all("\t" in l or "  " in l for l in lines):
                            # Candidate table
                            parsed_table = self._extract_table_from_text(lines)
                            if parsed_table:
                                tables.append(parsed_table)
                                sections.append(
                                    DocumentSection(
                                        title=parsed_table.title,
                                        content=parsed_table.raw_markdown,
                                        section_type="table",
                                        page_number=idx,
                                    )
                                )
                                continue

                        # Header detection heuristic: short line in all caps or title case
                        if len(clean_para) < 80 and ("\n" not in clean_para):
                            sections.append(
                                DocumentSection(
                                    title=clean_para,
                                    content=clean_para,
                                    section_type="header",
                                    level=2,
                                    page_number=idx,
                                )
                            )
                        else:
                            sections.append(
                                DocumentSection(
                                    content=clean_para,
                                    section_type="paragraph",
                                    page_number=idx,
                                )
                            )

            except Exception as exc:
                metadata["error"] = f"pypdf extraction warning: {exc}"
                all_text_parts.append("[PDF Content Unreadable]")

        full_text = "\n\n".join(all_text_parts)
        return StructuredDocument(
            title=title,
            author=metadata.get("author", ""),
            total_pages=total_pages,
            file_type="pdf",
            sections=sections,
            tables=tables,
            full_text=full_text,
            metadata=metadata,
        )

    def parse_markdown(self, content: str, filename: str = "document.md") -> StructuredDocument:
        sections: list[DocumentSection] = []
        tables: list[StructuredTable] = []
        lines = content.splitlines()

        current_header = Path(filename).stem
        current_level = 1
        current_block: list[str] = []
        in_code_block = False
        code_block_lines: list[str] = []

        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.strip()

            # Code blocks
            if stripped.startswith("```"):
                if in_code_block:
                    in_code_block = False
                    code_text = "\n".join(code_block_lines)
                    sections.append(
                        DocumentSection(
                            title=current_header,
                            level=current_level,
                            content=code_text,
                            section_type="code",
                        )
                    )
                    code_block_lines = []
                else:
                    in_code_block = True
                    code_block_lines = []
                i += 1
                continue

            if in_code_block:
                code_block_lines.append(line)
                i += 1
                continue

            # Markdown Tables (e.g. | col1 | col2 |)
            if stripped.startswith("|") and stripped.endswith("|"):
                table_lines = [stripped]
                j = i + 1
                while j < len(lines) and lines[j].strip().startswith("|") and lines[j].strip().endswith("|"):
                    table_lines.append(lines[j].strip())
                    j += 1
                if len(table_lines) >= 2:
                    table = self._parse_markdown_table(table_lines)
                    if table:
                        tables.append(table)
                        sections.append(
                            DocumentSection(
                                title=table.title,
                                level=current_level,
                                content=table.raw_markdown,
                                section_type="table",
                            )
                        )
                    i = j
                    continue

            # Markdown Headers (# Header)
            header_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
            if header_match:
                if current_block:
                    sections.append(
                        DocumentSection(
                            title=current_header,
                            level=current_level,
                            content="\n".join(current_block).strip(),
                            section_type="paragraph",
                        )
                    )
                    current_block = []

                current_level = len(header_match.group(1))
                current_header = header_match.group(2).strip()
                sections.append(
                    DocumentSection(
                        title=current_header,
                        level=current_level,
                        content=current_header,
                        section_type="header",
                    )
                )
                i += 1
                continue

            if stripped:
                current_block.append(line)
            elif current_block:
                sections.append(
                    DocumentSection(
                        title=current_header,
                        level=current_level,
                        content="\n".join(current_block).strip(),
                        section_type="paragraph",
                    )
                )
                current_block = []

            i += 1

        if current_block:
            sections.append(
                DocumentSection(
                    title=current_header,
                    level=current_level,
                    content="\n".join(current_block).strip(),
                    section_type="paragraph",
                )
            )

        return StructuredDocument(
            title=Path(filename).stem,
            total_pages=1,
            file_type="markdown",
            sections=sections,
            tables=tables,
            full_text=content,
        )

    def parse_latex(self, content: str, filename: str = "document.tex") -> StructuredDocument:
        sections: list[DocumentSection] = []
        title_match = re.search(r"\\title\{([^}]+)\}", content)
        doc_title = title_match.group(1) if title_match else Path(filename).stem

        # Extract sections using regex
        sec_pattern = re.compile(r"\\(section|subsection|subsubsection)\{([^}]+)\}")
        splits = sec_pattern.split(content)

        if len(splits) > 1:
            # Preamble
            if splits[0].strip():
                sections.append(
                    DocumentSection(
                        title="Preamble",
                        level=1,
                        content=splits[0].strip()[:1000],
                        section_type="paragraph",
                    )
                )
            # Groups: (level_name, title, content)
            for k in range(1, len(splits), 3):
                if k + 2 < len(splits):
                    lvl_name = splits[k]
                    s_title = splits[k + 1]
                    s_content = splits[k + 2].strip()
                    lvl = 1 if lvl_name == "section" else (2 if lvl_name == "subsection" else 3)
                    sections.append(
                        DocumentSection(
                            title=s_title,
                            level=lvl,
                            content=s_title,
                            section_type="header",
                        )
                    )
                    sections.append(
                        DocumentSection(
                            title=s_title,
                            level=lvl,
                            content=s_content,
                            section_type="paragraph",
                        )
                    )
        else:
            sections.append(
                DocumentSection(title=doc_title, level=1, content=content, section_type="paragraph")
            )

        return StructuredDocument(
            title=doc_title,
            total_pages=1,
            file_type="latex",
            sections=sections,
            tables=[],
            full_text=content,
        )

    def _parse_generic_text(self, content: str, filename: str) -> StructuredDocument:
        paras = [p.strip() for p in content.split("\n\n") if p.strip()]
        sections = [
            DocumentSection(content=p, section_type="paragraph", page_number=1) for p in paras
        ]
        return StructuredDocument(
            title=Path(filename).stem,
            total_pages=1,
            file_type="text",
            sections=sections,
            tables=[],
            full_text=content,
        )

    def _parse_markdown_table(self, lines: list[str]) -> StructuredTable | None:
        if len(lines) < 2:
            return None
        # Extract headers
        raw_headers = [c.strip() for c in lines[0].split("|") if c.strip()]
        # Skip separator line (|---|---|)
        data_rows: list[list[str]] = []
        start_row = 2 if len(lines) > 1 and "---" in lines[1] else 1

        for r_line in lines[start_row:]:
            cols = [c.strip() for c in r_line.split("|") if c.strip()]
            if cols:
                data_rows.append(cols)

        return StructuredTable(
            title="Markdown Table",
            headers=raw_headers,
            rows=data_rows,
            raw_markdown="\n".join(lines),
        )

    def _extract_table_from_text(self, lines: list[str]) -> StructuredTable | None:
        rows: list[list[str]] = []
        for line in lines:
            parts = [p.strip() for p in re.split(r"\t+|\s{2,}", line) if p.strip()]
            if parts:
                rows.append(parts)
        if len(rows) < 2:
            return None

        headers = rows[0]
        data_rows = rows[1:]
        md_lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
        for dr in data_rows:
            # Pad row to match header length
            padded = dr + [""] * max(0, len(headers) - len(dr))
            md_lines.append("| " + " | ".join(padded[: len(headers)]) + " |")

        return StructuredTable(
            title="Extracted Table",
            headers=headers,
            rows=data_rows,
            raw_markdown="\n".join(md_lines),
        )
