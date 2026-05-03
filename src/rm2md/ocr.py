"""Mistral OCR pipeline: PDF -> Markdown (+ extracted images)."""
from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Iterable, List, Optional

import datauri
from dotenv import load_dotenv
from mistralai.client import Mistral


def upload_pdf(client: Mistral, pdf_path: Path) -> str:
    """Upload a local PDF and return a signed URL usable by the OCR endpoint."""
    with pdf_path.open("rb") as fh:
        uploaded = client.files.upload(
            file={"file_name": pdf_path.name, "content": fh},
            purpose="ocr",
        )
    signed = client.files.get_signed_url(file_id=uploaded.id)
    return signed.url


def save_image(image, images_dir: Path) -> None:
    """Decode a base64 data-URI image and write it to images_dir/<id>."""
    if not image.image_base64:
        return
    parsed = datauri.parse(image.image_base64)
    out_path = images_dir / image.id
    out_path.write_bytes(parsed.data)


def write_markdown(ocr_response, output_path: Path, images_dir: Path | None) -> int:
    """Write OCR pages to a markdown file. Returns number of images saved."""
    image_count = 0
    with output_path.open("w", encoding="utf-8") as f:
        for i, page in enumerate(ocr_response.pages):
            md = page.markdown
            if images_dir is not None and page.images:
                rel_prefix = f"{images_dir.name}/"
                for image in page.images:
                    save_image(image, images_dir)
                    image_count += 1
                    md = md.replace(f"]({image.id})", f"]({rel_prefix}{image.id})")
            f.write(md)
            if i != len(ocr_response.pages) - 1:
                f.write("\n\n")
    return image_count


def get_api_key() -> str | None:
    """Return ``MISTRAL_API_KEY``, loading ``.env`` and the central config.

    Lookup order (first hit wins):

    1. Existing process environment.
    2. ``./.env`` in the current working directory (developer flow).
    3. ``$XDG_CONFIG_HOME/rm2md/config`` (default: ``~/.config/rm2md/config``)
       — used by central installs done via ``install.sh``.
    """
    load_dotenv()  # local .env (no-op if missing); does not override env vars
    if not os.environ.get("MISTRAL_API_KEY"):
        xdg = os.environ.get("XDG_CONFIG_HOME")
        config_home = Path(xdg) if xdg else Path.home() / ".config"
        central = config_home / "rm2md" / "config"
        if central.is_file():
            load_dotenv(central, override=False)
    return os.environ.get("MISTRAL_API_KEY")


def parse_pages(spec: str) -> List[int]:
    """Parse a 1-indexed page spec like '1,3,5-7' into a sorted unique list of
    0-indexed page numbers (the format Mistral OCR expects).

    Raises ValueError on malformed input or non-positive page numbers.
    """
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo_s, hi_s = part.split("-", 1)
            lo, hi = int(lo_s), int(hi_s)
            if lo < 1 or hi < 1 or hi < lo:
                raise ValueError(f"invalid page range: {part!r}")
            pages.update(range(lo, hi + 1))
        else:
            n = int(part)
            if n < 1:
                raise ValueError(f"page numbers must be >= 1: {part!r}")
            pages.add(n)
    if not pages:
        raise ValueError("no pages specified")
    # Mistral OCR uses 0-indexed page numbers.
    return sorted(p - 1 for p in pages)


def run_ocr(
    pdf_path: Path,
    output_path: Path,
    *,
    include_images: bool = True,
    model: str = "mistral-ocr-latest",
    pages: Optional[Iterable[int]] = None,
) -> int:
    """End-to-end: upload PDF, OCR it, write markdown + images.

    ``pages`` is an optional iterable of 0-indexed page numbers. When provided,
    only those pages are OCR'd.

    Returns 0 on success, non-zero on failure (matches CLI exit codes).
    Prints progress to stderr.
    """
    if not pdf_path.is_file():
        print(f"error: file not found: {pdf_path}", file=sys.stderr)
        return 2
    if pdf_path.suffix.lower() != ".pdf":
        print(f"error: expected a .pdf file, got: {pdf_path.name}", file=sys.stderr)
        return 2

    api_key = get_api_key()
    if not api_key:
        print(
            "error: MISTRAL_API_KEY is not set. Add it to a .env file or export it.",
            file=sys.stderr,
        )
        return 2

    output_path.parent.mkdir(parents=True, exist_ok=True)

    images_dir: Path | None = None
    if include_images:
        images_dir = output_path.parent / f"{output_path.stem}_images"
        images_dir.mkdir(parents=True, exist_ok=True)

    client = Mistral(api_key=api_key)

    print(f"Uploading {pdf_path} ...", file=sys.stderr)
    signed_url = upload_pdf(client, pdf_path)

    pages_list = sorted(set(pages)) if pages is not None else None
    if pages_list is not None:
        human = ", ".join(str(p + 1) for p in pages_list)
        print(
            f"Running OCR with model {model} on pages {human} ...",
            file=sys.stderr,
        )
    else:
        print(f"Running OCR with model {model} ...", file=sys.stderr)

    ocr_kwargs = {
        "model": model,
        "document": {"type": "document_url", "document_url": signed_url},
        "include_image_base64": include_images,
    }
    if pages_list is not None:
        ocr_kwargs["pages"] = pages_list
    ocr_response = client.ocr.process(**ocr_kwargs)

    image_count = write_markdown(ocr_response, output_path, images_dir)

    if images_dir is not None and image_count == 0:
        try:
            images_dir.rmdir()
        except OSError:
            pass

    print(
        f"Done. Pages: {len(ocr_response.pages)}, images: {image_count}. "
        f"Wrote: {output_path}",
        file=sys.stderr,
    )
    return 0
