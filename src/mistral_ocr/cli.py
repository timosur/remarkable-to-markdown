"""CLI: convert a PDF to Markdown using the Mistral OCR API."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

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


def write_markdown(
    ocr_response,
    output_path: Path,
    images_dir: Path | None,
) -> int:
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
                    # Rewrite ![...](img-x.jpeg) -> ![...](images_dir/img-x.jpeg)
                    md = md.replace(f"]({image.id})", f"]({rel_prefix}{image.id})")
            f.write(md)
            if i != len(ocr_response.pages) - 1:
                f.write("\n\n")
    return image_count


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="ocr",
        description="Convert a PDF to Markdown using the Mistral OCR API.",
    )
    p.add_argument("pdf", type=Path, help="Path to the PDF file.")
    p.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output markdown path (default: <pdf_stem>.md next to the PDF).",
    )
    p.add_argument(
        "--no-images", action="store_true",
        help="Do not extract embedded images.",
    )
    p.add_argument(
        "--model", default="mistral-ocr-latest",
        help="OCR model to use (default: mistral-ocr-latest).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    pdf_path: Path = args.pdf
    if not pdf_path.is_file():
        print(f"error: file not found: {pdf_path}", file=sys.stderr)
        return 2
    if pdf_path.suffix.lower() != ".pdf":
        print(f"error: expected a .pdf file, got: {pdf_path.name}", file=sys.stderr)
        return 2

    load_dotenv()
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        print(
            "error: MISTRAL_API_KEY is not set. Add it to a .env file or export it.",
            file=sys.stderr,
        )
        return 2

    output_path: Path = args.output or pdf_path.with_suffix(".md")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    images_dir: Path | None = None
    if not args.no_images:
        images_dir = output_path.parent / f"{output_path.stem}_images"
        images_dir.mkdir(parents=True, exist_ok=True)

    client = Mistral(api_key=api_key)

    print(f"Uploading {pdf_path} ...", file=sys.stderr)
    signed_url = upload_pdf(client, pdf_path)

    print(f"Running OCR with model {args.model} ...", file=sys.stderr)
    ocr_response = client.ocr.process(
        model=args.model,
        document={"type": "document_url", "document_url": signed_url},
        include_image_base64=not args.no_images,
    )

    image_count = write_markdown(ocr_response, output_path, images_dir)

    # Clean up empty images dir
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


if __name__ == "__main__":
    raise SystemExit(main())
