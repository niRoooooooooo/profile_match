"""Write ONE consolidated, professional DOCX from the rendered report.

Input is the ReportDocument produced by report_renderer.render_report from
the innovator's latest SAVED edited draft (the same data the web report
shows). No AI is used; no facts are added.

Citations such as [3] are internal links to a bookmark on reference [3] in
Section 15, so the document works offline and contains no web addresses.
"""

import io

from docx import Document
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor

from app.services.report_renderer import (
    REPORT_NOTICE,
    ReportBlock,
    ReportDocument,
    ReportItem,
    render_report,
)

INK = RGBColor(0x1E, 0x2A, 0x3E)
MUTED = RGBColor(0x5B, 0x67, 0x7A)
WARN = RGBColor(0x9A, 0x5B, 0x00)
LINK = "1F5FBF"
_WARN_STATUSES = ("unverified", "contradiction", "discrepancy")


def _styles(document):
    normal = document.styles["Normal"]
    normal.font.name = "Calibri"
    normal.font.size = Pt(11)
    normal.font.color.rgb = INK
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.15
    for name, size, before in (("Title", 24, 0), ("Heading 1", 15, 18), ("Heading 2", 12, 10)):
        style = document.styles[name]
        style.font.name = "Calibri"
        style.font.size = Pt(size)
        style.font.color.rgb = INK
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(4)
        style.paragraph_format.keep_with_next = True
    section = document.sections[0]
    for side in ("top_margin", "bottom_margin", "left_margin", "right_margin"):
        setattr(section, side, Pt(64))


def _shade(cell, hex_fill: str):
    properties = cell._tc.get_or_add_tcPr()
    shading = OxmlElement("w:shd")
    shading.set(qn("w:val"), "clear")
    shading.set(qn("w:color"), "auto")
    shading.set(qn("w:fill"), hex_fill)
    properties.append(shading)


def _small(run, color=MUTED, italic=False, size=9):
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.italic = italic
    return run


def _ref_anchor(number: int) -> str:
    return f"ref_{number}"


def _citation_link(paragraph, number: int):
    """[n] as an internal hyperlink to the bookmark of reference n."""
    link = OxmlElement("w:hyperlink")
    link.set(qn("w:anchor"), _ref_anchor(number))
    link.set(qn("w:history"), "1")
    run = OxmlElement("w:r")
    props = OxmlElement("w:rPr")
    for tag, attr, value in (("w:color", "w:val", LINK), ("w:sz", "w:val", "18"),
                             ("w:vertAlign", "w:val", "superscript")):
        element = OxmlElement(tag)
        element.set(qn(attr), value)
        props.append(element)
    run.append(props)
    text = OxmlElement("w:t")
    text.text = f"[{number}]"
    run.append(text)
    link.append(run)
    paragraph._p.append(link)


def _bookmark(paragraph, name: str, bookmark_id: int):
    start = OxmlElement("w:bookmarkStart")
    start.set(qn("w:id"), str(bookmark_id))
    start.set(qn("w:name"), name)
    end = OxmlElement("w:bookmarkEnd")
    end.set(qn("w:id"), str(bookmark_id))
    paragraph._p.insert(0, start)
    paragraph._p.append(end)


def _label(paragraph, label: str | None, status: str | None):
    if label:
        _small(paragraph.add_run(f" ({label})"), WARN if status in _WARN_STATUSES else MUTED,
               italic=True)


def _annotations(paragraph, item: ReportItem):
    """Citations like [1][3] (internal links) and the item's own label, if any."""
    for number in item.citations:
        _citation_link(paragraph, number)
    _label(paragraph, item.label, item.status)


def _item_paragraph(document, item: ReportItem, style=None):
    paragraph = document.add_paragraph(style=style)
    if item.name:
        paragraph.add_run(f"{item.name}: ").bold = True
    paragraph.add_run(item.text)
    _annotations(paragraph, item)
    return paragraph


def _block_heading(document, block: ReportBlock):
    """Heading 2 with the block's shared label, e.g. 'Use cases (AI interpretation)'."""
    heading = document.add_heading(block.heading, level=2)
    if block.label:
        _small(heading.add_run(f"  ({block.label})"), italic=True)
        heading.runs[-1].bold = False


def _caption(document, block: ReportBlock):
    caption = document.add_paragraph()
    caption.paragraph_format.space_after = Pt(2)
    _small(caption.add_run(block.label), italic=True)


def _results_table(document, block: ReportBlock):
    show_status = any(item.label for item in block.items)
    headers = ("Result", "Source", "Status") if show_status else ("Result", "Source")
    table = document.add_table(rows=1, cols=len(headers))
    table.style = "Table Grid"
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    for cell, text in zip(table.rows[0].cells, headers):
        cell.text = text
        cell.paragraphs[0].runs[0].bold = True
        _shade(cell, "EEF3FA")
    for item in block.items:
        row = table.add_row().cells
        row[0].text = item.text
        if item.citations:
            for number in item.citations:
                _citation_link(row[1].paragraphs[0], number)
        else:
            row[1].text = "—"
        if show_status:
            row[2].text = item.label or "Documented"
            if item.status in _WARN_STATUSES:
                row[2].paragraphs[0].runs[0].font.color.rgb = WARN
    document.add_paragraph()


def _key_value_table(document, rows, fill="F4F6F9"):
    table = document.add_table(rows=0, cols=2)
    table.style = "Table Grid"
    for key, value in rows:
        cells = table.add_row().cells
        cells[0].text = str(key)
        cells[0].paragraphs[0].runs[0].bold = True
        _shade(cells[0], fill)
        cells[1].text = str(value)
    return table


def build_report_docx(report: ReportDocument, submission: dict | None = None) -> bytes:
    """Render the report to DOCX bytes.

    `submission` is accepted for compatibility; version and submission
    details already come from the report (render_report draft_meta).
    """
    document = Document()
    _styles(document)

    title = document.add_paragraph(report.title, style="Title")
    title.alignment = WD_ALIGN_PARAGRAPH.LEFT
    subtitle = document.add_paragraph(report.subtitle)
    _small(subtitle.runs[0], size=13)
    banner = document.add_paragraph()
    run = banner.add_run(REPORT_NOTICE)
    run.bold = True
    run.font.color.rgb = WARN

    # Short header: domain, TRL, version, submission and review status.
    rows = [(m.name, m.value) for m in report.metadata if m.name != "Review status"]
    if report.version:
        rows.append(("Version", report.version))
    rows += [(m.name, m.value) for m in report.processing if m.name == "Submission ID"]
    rows += [(m.name, m.value) for m in report.metadata if m.name == "Review status"]
    if rows:
        _key_value_table(document, rows)
    for text in (report.disclaimer, report.legend):
        note = document.add_paragraph()
        _small(note.add_run(text), italic=True)

    bookmark_id = 0
    for section in report.sections:
        document.add_heading(f"{section.number}. {section.title}", level=1)
        for block in section.blocks:
            if block.kind == "note":
                paragraph = document.add_paragraph()
                run = paragraph.add_run(block.text or "")
                run.italic = True
                run.font.color.rgb = MUTED
                continue
            if block.heading and block.kind != "facts":
                _block_heading(document, block)
            elif block.label and block.kind in ("facts", "bullets"):
                _caption(document, block)
            if block.kind == "paragraph":
                for item in block.items:
                    parts = [p for p in item.text.split("\n") if p.strip()] or [item.text]
                    for index, part in enumerate(parts):
                        paragraph = document.add_paragraph(part.strip())
                        if index == len(parts) - 1:
                            _annotations(paragraph, item)
                            if not block.heading:
                                _label(paragraph, block.label, block.status)
            elif block.kind == "facts":
                for item in block.items:
                    _item_paragraph(document, item)
            elif block.kind == "bullets":
                for item in block.items:
                    _item_paragraph(document, item, style="List Bullet")
            elif block.kind == "table":
                _results_table(document, block)
        if section.key == "sources" and report.sources:
            document.add_heading("References", level=2)
            for entry in report.sources:
                where = ", ".join(filter(None, [
                    f"page {entry.page}" if entry.page is not None else None,
                    f"section {entry.section}" if entry.section else None]))
                paragraph = document.add_paragraph()
                paragraph.paragraph_format.space_after = Pt(2)
                paragraph.add_run(f"[{entry.number}] ").bold = True
                paragraph.add_run(entry.source_file + (f" ({where})" if where else ""))
                bookmark_id += 1
                _bookmark(paragraph, _ref_anchor(entry.number), bookmark_id)
                for excerpt in entry.excerpts:          # complete quotations
                    quote = document.add_paragraph()
                    quote.paragraph_format.left_indent = Pt(18)
                    _small(quote.add_run(f"“{excerpt}”"), italic=True)
                if not entry.excerpts and entry.note:
                    quote = document.add_paragraph()
                    quote.paragraph_format.left_indent = Pt(18)
                    _small(quote.add_run(entry.note), italic=True)

    if report.processing or report.diagnostics:
        document.add_heading("Appendix: Processing record and evidence notes", level=1)
        if report.processing:
            _key_value_table(document, [(m.name, m.value) for m in report.processing])
            document.add_paragraph()
        for warning in report.diagnostics:
            paragraph = document.add_paragraph(style="List Bullet")
            _small(paragraph.add_run(warning))

    footer = document.sections[0].footer.paragraphs[0]
    footer.text = "Profile Match · Innovator-submitted · Not institutionally approved"
    footer.alignment = WD_ALIGN_PARAGRAPH.CENTER

    stream = io.BytesIO()
    document.save(stream)
    return stream.getvalue()


def build_submission_docx(manifest: dict) -> bytes:
    """DOCX for a submission manifest (a fixed snapshot of the edited profile)."""
    report = render_report(manifest["profile"], {
        "generation_number": manifest.get("generation_number"),
        "invention_id": manifest.get("invention_id"),
        "submission_id": manifest.get("submission_id"),
        "submitted_at": manifest.get("submitted_at"),
    })
    return build_report_docx(report, manifest)
