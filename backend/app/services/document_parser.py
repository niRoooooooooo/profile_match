
import re
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, BadZipFile
import pymupdf

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph


MAX_FILE_SIZE = 20 * 1024 * 1024
MAX_PAGES = 200
MAX_CHARACTERS = 120000
MAX_UNCOMPRESSED_SIZE = 80 * 1024 * 1024


@dataclass
class DocumentChunk:
    source_file: str
    text: str
    page: int | None = None
    section: str | None = None


@dataclass
class ParsedDocument:
    filename: str
    file_type: str
    chunks: list[DocumentChunk] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    total_pages: int | None = None
    truncated: bool = False

    @property
    def text(self) -> str:
        """Return extracted text with source references."""

        parts = []

        for chunk in self.chunks:
            location = chunk.source_file

            if chunk.page is not None:
                location += f", page {chunk.page}"

            if chunk.section:
                location += f", section: {chunk.section}"

            parts.append(
                f"[Source: {location}]\n{chunk.text}"
            )

        return "\n\n".join(parts)

    @property
    def character_count(self) -> int:
        return sum(len(chunk.text) for chunk in self.chunks)


def parse_document(
    file_bytes: bytes,
    filename: str
) -> ParsedDocument:
    """
    Parse a PDF or DOCX document from memory.

    Does not save files to the local disk.
    Returns extracted text and source metadata.
    """

    if not file_bytes:
        raise ValueError("Document is empty.")

    if len(file_bytes) > MAX_FILE_SIZE:
        raise ValueError("Document exceeds the 20 MB limit.")

    safe_filename = Path(
        filename.replace("\\", "/")
    ).name

    extension = Path(safe_filename).suffix.lower()

    if extension == ".doc":
        raise ValueError(
            "Legacy .doc documents require conversion "
            "to DOCX before text extraction."
        )

    if extension == ".pdf":
        return parse_pdf(file_bytes, safe_filename)

    if extension == ".docx":
        return parse_docx(file_bytes, safe_filename)

    raise ValueError(
        "Unsupported format. Use PDF or DOCX."
    )


TABLE_ROWS_HEADING = (
    "[Table rows from this page, with wrapped cells joined]"
)

# Layout thresholds in PDF points.
_COLUMN_GAP = 9.0           # gap between words that separates two table cells
_LINE_TOLERANCE = 3.0       # words on the same visual line
_CONTINUATION_INDENT = 18.0 # right of a table's first column = a wrapped line


def reconstruct_table_rows(page) -> list[str]:
    """Rebuild table rows whose cells wrap across lines ("a | b | c").

    Uses word positions only (no table-detection engine). Returns [] when
    the page has no wrapped table cells, so ordinary pages are unchanged,
    and on any unexpected layout problem (extraction must never fail here).
    """
    try:
        words = page.get_text("words", sort=True)
        lines = []
        for word in sorted(words, key=lambda w: (round(w[1] / _LINE_TOLERANCE), w[0])):
            if lines and abs(lines[-1]["y"] - word[1]) <= _LINE_TOLERANCE:
                lines[-1]["words"].append(word)
            else:
                lines.append({"y": word[1], "h": word[3] - word[1], "words": [word]})
        for line in lines:
            line["words"].sort(key=lambda w: w[0])
            cells = []
            for word in line["words"]:
                if cells and word[0] - cells[-1]["x1"] <= _COLUMN_GAP:
                    cells[-1]["text"] += " " + word[4]
                    cells[-1]["x1"] = word[2]
                else:
                    cells.append({"x0": word[0], "x1": word[2], "text": word[4]})
            line["cells"] = cells

        rows, current, left, merged = [], None, None, False
        for line in lines:
            cells = line["cells"]
            # A bullet glyph is not a table column: bullet lists are not tables.
            bullet = len(cells[0]["text"]) <= 2 and not any(ch.isalnum() for ch in cells[0]["text"])
            page_furniture = re.search(r"\bpage\s+\d+\b",
                                       " ".join(c["text"] for c in cells), re.IGNORECASE)
            continuation = (
                current is not None and left is not None and not bullet and not page_furniture
                and cells[0]["x0"] > left + _CONTINUATION_INDENT
                and line["y"] - current["y"] <= current["h"] * 2.6
                # same type size: page headers/footers are not wrapped cells
                and abs(line["h"] - current["h"]) <= current["h"] * 0.2
            )
            if continuation:
                for cell in cells:
                    target = max(
                        (c for c in current["cells"] if c["x0"] <= cell["x0"] + 12),
                        key=lambda c: c["x0"], default=None,
                    )
                    if target is None:
                        continue
                    joiner = (
                        "" if target["text"].endswith("-") and cell["text"][:1].islower()
                        else " "
                    )
                    target["text"] += joiner + cell["text"]
                    merged = True
                current["y"] = line["y"]
                continue
            if current is not None:
                rows.append(current)
            if len(cells) >= 2 and not bullet:
                current = {"y": line["y"], "h": line["h"], "cells": [dict(c) for c in cells]}
                if left is None or cells[0]["x0"] < left + _CONTINUATION_INDENT:
                    left = cells[0]["x0"]
            else:
                current, left = None, None
        if current is not None:
            rows.append(current)
        if not merged:
            return []
        return [
            " | ".join(c["text"] for c in row["cells"])
            for row in rows if len(row["cells"]) >= 2
        ]
    except Exception:  # noqa: BLE001 - extraction must never fail here
        return []


def parse_pdf(
    file_bytes: bytes,
    filename: str
) -> ParsedDocument:
    """Extract text from PDF pages."""

    result = ParsedDocument(
        filename=filename,
        file_type="pdf"
    )

    try:
        with pymupdf.open(
            stream=file_bytes,
            filetype="pdf"
        ) as document:

            if document.needs_pass:
                raise ValueError(
                    "Password-protected PDF cannot be parsed."
                )

            result.total_pages = len(document)

            pages_to_read = min(
                len(document),
                MAX_PAGES
            )

            if len(document) > MAX_PAGES:
                result.truncated = True
                result.warnings.append(
                    "PDF page limit reached."
                )

            empty_pages = []

            for page_index in range(pages_to_read):

                page = document[page_index]

                text = page.get_text(
                    "text",
                    sort=True
                ).strip()

                if not text:
                    empty_pages.append(page_index + 1)
                    continue

                # Tables whose cells wrap onto several lines are read line
                # by line above, which interleaves neighbouring columns.
                # Add the rows once more with each cell joined, so the AI
                # and the citation check see every cell as one passage.
                table_rows = reconstruct_table_rows(page)
                if table_rows:
                    text += (
                        "\n\n" + TABLE_ROWS_HEADING + "\n"
                        + "\n".join(table_rows)
                    )

                remaining = (
                    MAX_CHARACTERS
                    - result.character_count
                )

                if remaining <= 0:
                    result.truncated = True
                    break

                if len(text) > remaining:
                    text = text[:remaining]
                    result.truncated = True

                result.chunks.append(
                    DocumentChunk(
                        source_file=filename,
                        page=page_index + 1,
                        text=text
                    )
                )

                if result.truncated:
                    break

            if empty_pages:
                result.warnings.append(
                    f"{len(empty_pages)} PDF page(s) "
                    "contained no extractable text. "
                    "OCR may be required."
                )

    except ValueError:
        raise
    except Exception as error:
        raise ValueError(
            "Unable to parse PDF document."
        ) from error

    if result.truncated:
        result.warnings.append(
            "Extraction was truncated. "
            "The document was not fully processed."
        )

    if not result.chunks:
        result.warnings.append(
            "No readable text found in this PDF."
        )

    return result


def parse_docx(
    file_bytes: bytes,
    filename: str
) -> ParsedDocument:
    """Extract Word paragraphs and tables."""

    result = ParsedDocument(
        filename=filename,
        file_type="docx"
    )

    try:
        # Check the compressed Word package first.
        with ZipFile(BytesIO(file_bytes)) as archive:

            if "word/document.xml" not in archive.namelist():
                raise ValueError(
                    "Not a valid DOCX document."
                )

            expanded_size = sum(
                item.file_size
                for item in archive.infolist()
            )

            if expanded_size > MAX_UNCOMPRESSED_SIZE:
                raise ValueError(
                    "DOCX uncompressed size exceeds limit."
                )

        document = Document(BytesIO(file_bytes))

        current_section = None

        for block in document.iter_inner_content():

            if isinstance(block, Paragraph):

                text = block.text.strip()

                if not text:
                    continue

                style_name = (
                    block.style.name
                    if block.style
                    else ""
                )

                if (
                    style_name.startswith("Heading")
                    or style_name == "Title"
                ):
                    current_section = text

            elif isinstance(block, Table):

                rows = []

                for row in block.rows:

                    cells = [
                        cell.text.strip()
                        for cell in row.cells
                    ]

                    rows.append(" | ".join(cells))

                text = "\n".join(rows).strip()

                if not text:
                    continue

            else:
                continue

            remaining = (
                MAX_CHARACTERS
                - result.character_count
            )

            if remaining <= 0:
                result.truncated = True
                break

            if len(text) > remaining:
                text = text[:remaining]
                result.truncated = True

            result.chunks.append(
                DocumentChunk(
                    source_file=filename,
                    section=current_section,
                    text=text
                )
            )

            if result.truncated:
                break

    except ValueError:
        raise
    except (BadZipFile, Exception) as error:
        raise ValueError(
            "Unable to parse DOCX document."
        ) from error

    result.warnings.append(
        "DOCX does not provide reliable page numbers. "
        "Section headings are used where available. "
        "Images, headers, footers, and embedded objects "
        "have not been analyzed."
    )

    if result.truncated:
        result.warnings.append(
            "Extraction was truncated."
        )

    if not result.chunks:
        result.warnings.append(
            "No readable text found in this DOCX."
        )

    return result
