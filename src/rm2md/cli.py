"""rm2md CLI: ls / pull / ocr."""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from datetime import date, datetime
from pathlib import Path

from . import convert, ocr, rmapi, wizard

# Intermediate downloads (zip archives) and rendered per-page PDFs go here so
# the user can inspect them. One subdirectory per `pull` invocation.
_WORK_ROOT = Path("input") / ".rm2md-work"


def _slugify(name: str) -> str:
    """Filesystem-safe lowercase slug derived from a remote basename."""
    s = name.lower().strip()
    # Drop file extensions that may slip through (rare).
    s = re.sub(r"\.(zip|rmdoc|pdf)$", "", s)
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "document"


# ---------- subcommand: login ----------

def cmd_login(_args: argparse.Namespace) -> int:
    """Pair this machine with the reMarkable cloud via rmapi's interactive flow."""
    try:
        return rmapi.login()
    except rmapi.RmapiError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


# ---------- subcommand: ls ----------

def cmd_ls(args: argparse.Namespace) -> int:
    try:
        entries = rmapi.ls(args.path)
    except rmapi.RmapiError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    for entry in entries:
        marker = "d" if entry.is_dir else "f"
        print(f"[{marker}]\t{entry.name}")
    return 0


def _find_existing_archive(work_dir: Path) -> Path | None:
    """Return a previously downloaded reMarkable archive in ``work_dir``, if any."""
    if not work_dir.is_dir():
        return None
    for pattern in ("*.zip", "*.rmdoc"):
        for candidate in sorted(work_dir.glob(pattern)):
            if candidate.is_file() and candidate.stat().st_size > 0:
                return candidate
    return None


def _find_existing_pdf(work_dir: Path) -> Path | None:
    """Return a previously produced PDF in ``work_dir``, if any.

    Looks for an embedded passthrough PDF in ``extracted/`` and for merged
    notebook PDFs in ``pdf/``. Picks the largest hit so a fully merged file
    wins over per-page intermediates.
    """
    if not work_dir.is_dir():
        return None
    candidates: list[Path] = []
    extracted = work_dir / "extracted"
    if extracted.is_dir():
        candidates.extend(p for p in extracted.rglob("*.pdf") if p.is_file())
    pdf_dir = work_dir / "pdf"
    if pdf_dir.is_dir():
        # Skip per-page intermediates (pages-*/0001.pdf etc.); keep merged ones.
        for p in pdf_dir.glob("*.pdf"):
            if p.is_file() and p.stat().st_size > 0:
                candidates.append(p)
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_size)


# ---------- subcommand: pull ----------

def cmd_pull(args: argparse.Namespace) -> int:
    out_dir: Path = args.output
    out_dir.mkdir(parents=True, exist_ok=True)

    basename = Path(args.remote_path).name or "document"
    slug = _slugify(basename)
    now = datetime.now()
    md_name = f"{now.strftime('%Y-%m-%d-%H%M')}-{slug}.md"
    md_path = out_dir / md_name

    work_dir = _WORK_ROOT / f"{date.today().isoformat()}-{slug}"
    work_dir.mkdir(parents=True, exist_ok=True)
    print(f"Work dir: {work_dir}", file=sys.stderr)
    try:
        archive = _find_existing_archive(work_dir)
        if archive is not None:
            print(f"Reusing downloaded archive: {archive.name}", file=sys.stderr)
        else:
            print(f"Downloading {args.remote_path!r} ...", file=sys.stderr)
            try:
                archive = rmapi.geta(args.remote_path, work_dir)
            except rmapi.RmapiError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1

        pdf = _find_existing_pdf(work_dir)
        if pdf is not None:
            print(f"Reusing converted PDF: {pdf.relative_to(work_dir)}", file=sys.stderr)
        else:
            print(f"Converting {archive.name} -> PDF ...", file=sys.stderr)
            try:
                pdf = convert.to_pdf(archive, work_dir)
            except convert.ConvertError as e:
                print(f"error: {e}", file=sys.stderr)
                return 1

        if args.keep_pdf:
            kept = out_dir / f"{now.strftime('%Y-%m-%d-%H%M')}-{slug}.pdf"
            shutil.copy2(pdf, kept)
            print(f"Kept PDF: {kept}", file=sys.stderr)

        try:
            pages = ocr.parse_pages(args.pages) if args.pages else None
        except ValueError as e:
            print(f"error: --pages: {e}", file=sys.stderr)
            return 2

        rc = ocr.run_ocr(
            pdf,
            md_path,
            include_images=not args.no_images,
            model=args.model,
            pages=pages,
        )
    finally:
        if args.clean_work:
            shutil.rmtree(work_dir, ignore_errors=True)
        else:
            print(
                f"Intermediate files kept in {work_dir} (use --clean-work to remove).",
                file=sys.stderr,
            )

    return rc


# ---------- subcommand: ocr ----------

def cmd_ocr(args: argparse.Namespace) -> int:
    pdf_path: Path = args.pdf
    output_path: Path = args.output or pdf_path.with_suffix(".md")
    try:
        pages = ocr.parse_pages(args.pages) if args.pages else None
    except ValueError as e:
        print(f"error: --pages: {e}", file=sys.stderr)
        return 2
    return ocr.run_ocr(
        pdf_path,
        output_path,
        include_images=not args.no_images,
        model=args.model,
        pages=pages,
    )


# ---------- parser ----------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rm2md",
        description="reMarkable -> Markdown via Mistral OCR.",
    )
    sub = p.add_subparsers(dest="command", required=True)

    # login
    p_login = sub.add_parser(
        "login",
        help="Pair this machine with the reMarkable cloud (interactive one-time code).",
    )
    p_login.set_defaults(func=cmd_login)

    # ls
    p_ls = sub.add_parser("ls", help="List a folder on the reMarkable cloud.")
    p_ls.add_argument("path", nargs="?", default="/", help="Remote path (default: /).")
    p_ls.set_defaults(func=cmd_ls)

    # pull
    p_pull = sub.add_parser(
        "pull",
        help="Download a file from reMarkable, convert to PDF, OCR to Markdown.",
    )
    p_pull.add_argument("remote_path", help="Remote path on the reMarkable cloud.")
    p_pull.add_argument(
        "-o", "--output", type=Path, default=Path("output"),
        help="Output directory (default: ./output).",
    )
    p_pull.add_argument(
        "--keep-pdf", action="store_true",
        help="Also copy the intermediate PDF into the output directory.",
    )
    p_pull.add_argument(
        "--clean-work", action="store_true",
        help=(
            "Delete the per-run intermediate files in input/.rm2md-work/ "
            "after a successful run (default: keep them for inspection)."
        ),
    )
    p_pull.add_argument("--no-images", action="store_true",
                        help="Do not extract embedded images.")
    p_pull.add_argument("--model", default="mistral-ocr-latest",
                        help="OCR model (default: mistral-ocr-latest).")
    p_pull.add_argument(
        "--pages", default=None,
        help="Only OCR the given 1-indexed pages, e.g. '1,3,5-7'.",
    )
    p_pull.set_defaults(func=cmd_pull)

    # ocr (local PDF)
    p_ocr = sub.add_parser("ocr", help="Convert a local PDF to Markdown.")
    p_ocr.add_argument("pdf", type=Path, help="Path to the PDF file.")
    p_ocr.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output markdown path (default: <pdf_stem>.md next to the PDF).",
    )
    p_ocr.add_argument("--no-images", action="store_true",
                       help="Do not extract embedded images.")
    p_ocr.add_argument("--model", default="mistral-ocr-latest",
                       help="OCR model (default: mistral-ocr-latest).")
    p_ocr.add_argument(
        "--pages", default=None,
        help="Only OCR the given 1-indexed pages, e.g. '1,3,5-7'.",
    )
    p_ocr.set_defaults(func=cmd_ocr)

    # wizard
    p_wiz = sub.add_parser(
        "wizard",
        help="Interactive: browse reMarkable, pick a file, choose options, run.",
    )
    p_wiz.set_defaults(func=lambda _args: wizard.run())

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
