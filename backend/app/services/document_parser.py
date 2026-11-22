
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
