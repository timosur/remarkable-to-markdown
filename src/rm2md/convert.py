"""Convert reMarkable archives (.zip/.rmdoc) to PDF.

Two paths:
- Fast path: archive contains a PDF (uploaded PDF on the device) -> use that.
- Notebook path: render each ``.rm`` page with `rmc` (supports v6 / software
  >= 3.0) and concatenate the per-page PDFs with `pypdf`.
"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path
from typing import List, Optional

import rmc
import cairosvg
from pypdf import PdfReader, PdfWriter


class ConvertError(RuntimeError):
    """Raised when archive extraction or PDF conversion fails."""


def extract_archive(archive_path: Path, work_dir: Path) -> Path:
    """Unzip archive into ``work_dir/extracted``. Returns the extracted directory."""
    if not archive_path.exists():
        raise ConvertError(f"Archive not found: {archive_path}")

    out_dir = work_dir / "extracted"
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        with zipfile.ZipFile(archive_path) as zf:
            zf.extractall(out_dir)
    except zipfile.BadZipFile as e:
        raise ConvertError(f"Not a valid zip archive: {archive_path}: {e}") from e

    return out_dir


def find_embedded_pdf(extracted_dir: Path) -> Optional[Path]:
    """Return the largest PDF inside the extracted archive, if any.

    reMarkable stores uploaded PDFs as ``<uuid>.pdf`` alongside ``<uuid>.content``.
    """
    pdfs = sorted(extracted_dir.rglob("*.pdf"), key=lambda p: p.stat().st_size, reverse=True)
    return pdfs[0] if pdfs else None


def _page_ids_from_content(content_path: Path) -> List[str]:
    """Parse a ``<uuid>.content`` JSON and return page IDs in display order.

    Handles both the newer ``cPages.pages`` schema (software >= 3.x) and the
    older flat ``pages`` schema. Pages marked as deleted are skipped.
    """
    try:
        data = json.loads(content_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ConvertError(f"Cannot read {content_path}: {e}") from e

    cpages = data.get("cPages")
    if isinstance(cpages, dict) and isinstance(cpages.get("pages"), list):
        ids: List[str] = []
        for entry in cpages["pages"]:
            if not isinstance(entry, dict):
                continue
            if entry.get("deleted"):
                continue
            pid = entry.get("id")
            if isinstance(pid, str):
                ids.append(pid)
        return ids

    pages = data.get("pages")
    if isinstance(pages, list):
        return [p for p in pages if isinstance(p, str)]

    return []


def _render_notebook(content_path: Path, work_dir: Path) -> Optional[Path]:
    """Render a single notebook (one ``.content`` file) to a merged PDF.

    Returns the output PDF path, or ``None`` if the notebook had no usable pages.
    """
    notebook_dir = content_path.with_suffix("")  # strip .content
    if not notebook_dir.is_dir():
        # Some uploads only have a content file with no per-page strokes.
        return None

    page_ids = _page_ids_from_content(content_path)
    if not page_ids:
        # Fall back to whatever .rm files we can find.
        rm_files = sorted(notebook_dir.glob("*.rm"))
    else:
        rm_files = []
        for pid in page_ids:
            candidate = notebook_dir / f"{pid}.rm"
            if candidate.exists():
                rm_files.append(candidate)

    if not rm_files:
        return None

    pages_dir = work_dir / f"pages-{content_path.stem}"
    pages_dir.mkdir(parents=True, exist_ok=True)

    page_pdfs: List[Path] = []
    for i, rm_file in enumerate(rm_files):
        out_svg = pages_dir / f"{i:04d}.svg"
        out_pdf = pages_dir / f"{i:04d}.pdf"
        try:
            rmc.rm_to_svg(str(rm_file), str(out_svg))
            cairosvg.svg2pdf(url=str(out_svg), write_to=str(out_pdf))
        except Exception as e:  # rmc/cairosvg raise a variety of errors per page
            print(
                f"warn: failed to render page {i + 1} ({rm_file.name}): {e}",
                file=sys.stderr,
            )
            continue
        if out_pdf.exists() and out_pdf.stat().st_size > 0:
            page_pdfs.append(out_pdf)

    if not page_pdfs:
        return None

    merged = work_dir / f"{content_path.stem}.pdf"
    writer = PdfWriter()
    for p in page_pdfs:
        try:
            reader = PdfReader(str(p))
            for page in reader.pages:
                writer.add_page(page)
        except Exception as e:
            print(f"warn: skipping bad page PDF {p.name}: {e}", file=sys.stderr)
            continue

    if len(writer.pages) == 0:
        return None

    with merged.open("wb") as fh:
        writer.write(fh)
    return merged


def convert_notebook_to_pdf(extracted_dir: Path, out_dir: Path) -> Path:
    """Render every notebook in the extracted archive to a single merged PDF."""
    out_dir.mkdir(parents=True, exist_ok=True)

    content_files = sorted(extracted_dir.rglob("*.content"))
    if not content_files:
        raise ConvertError(f"No .content files found in {extracted_dir}")

    rendered: List[Path] = []
    for cf in content_files:
        pdf = _render_notebook(cf, out_dir)
        if pdf is not None:
            rendered.append(pdf)

    if not rendered:
        raise ConvertError(
            "No pages could be rendered (all .rm files failed or notebook is empty)."
        )

    if len(rendered) == 1:
        return rendered[0]

    merged = out_dir / "notebook.pdf"
    writer = PdfWriter()
    for p in rendered:
        reader = PdfReader(str(p))
        for page in reader.pages:
            writer.add_page(page)
    with merged.open("wb") as fh:
        writer.write(fh)
    return merged


def to_pdf(archive_path: Path, work_dir: Path) -> Path:
    """Extract the archive and produce a PDF. Uses passthrough when possible."""
    extracted = extract_archive(archive_path, work_dir)

    embedded = find_embedded_pdf(extracted)
    if embedded is not None:
        return embedded

    return convert_notebook_to_pdf(extracted, work_dir / "pdf")
