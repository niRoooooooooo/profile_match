"""Generate the FICTIONAL upload files for the live Supabase end-to-end test.

Run (offline, no network):
    cd backend
    .venv/Scripts/python.exe ../tests/e2e_live/make_documents.py

Creates tests/e2e_live/upload_files/:
  glowfern_technical_report.pdf  (3 pages, real PDF -> exercises PDF parsing)
  glowfern_ip_disclosure.docx    (2 headed sections)
  bakery_notes.docx              (unrelated document; must be excluded)

The text is the fictional Glowfern comparison set from tests/_fixtures.py,
so live results can be scored against the same ground truth. Every file
starts with a FICTIONAL TEST DOCUMENT banner. After writing, each file is
parsed back with the app's own parser to prove it will be readable.
"""

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent), str(HERE.parents[1] / "backend")]

import _fixtures as fx  # noqa: E402
import pymupdf  # noqa: E402
from docx import Document  # noqa: E402

from app.services.document_parser import parse_document  # noqa: E402

OUT = HERE / "upload_files"
BANNER = "FICTIONAL TEST DOCUMENT - Profile Match end-to-end test. Not a real invention."


def write_pdf(path: Path, pages: list[str]):
    document = pymupdf.open()
    for text in pages:
        page = document.new_page()
        rect = pymupdf.Rect(56, 56, page.rect.width - 56, page.rect.height - 56)
        overflow = page.insert_textbox(rect, f"{BANNER}\n\n{text}", fontsize=11)
        if overflow < 0:
            raise RuntimeError(f"text did not fit on a page of {path.name}")
    document.save(path)
    document.close()


def write_docx(path: Path, sections: list[tuple[str | None, str]]):
    document = Document()
    document.add_paragraph(BANNER)
    for heading, text in sections:
        if heading:
            document.add_heading(heading, level=1)
        document.add_paragraph(text)
    document.save(path)


def main():
    OUT.mkdir(exist_ok=True)
    docs = fx.COMPARISON_DOCS
    write_pdf(OUT / "glowfern_technical_report.pdf",
              [text for _, _, text in docs["glowfern_technical_report.pdf"]])
    write_docx(OUT / "glowfern_ip_disclosure.docx",
               [(section, text) for _, section, text in docs["glowfern_ip_disclosure.docx"]])
    write_docx(OUT / "bakery_notes.docx",
               [(section, text) for _, section, text in docs["bakery_notes.docx"]])

    # Prove the app's own parser can read every file and finds key facts.
    expected = {
        "glowfern_technical_report.pdf": ["ESP32-C3", "41 consecutive nights", "below 10 degrees"],
        "glowfern_ip_disclosure.docx": ["provisional patent application", "USD 14"],
        "bakery_notes.docx": ["Sourdough"],
    }
    for name, needles in expected.items():
        path = OUT / name
        parsed = parse_document(path.read_bytes(), name)
        text = " ".join(chunk.text for chunk in parsed.chunks)
        missing = [n for n in needles if n not in " ".join(text.split())]
        status = "OK" if not missing else f"MISSING {missing}"
        pages = f"{parsed.total_pages} pages" if parsed.total_pages else f"{len(parsed.chunks)} chunks"
        print(f"{name:34s} {path.stat().st_size:>7,} bytes  {pages:10s} parse check: {status}")
        if missing:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
