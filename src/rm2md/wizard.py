"""Interactive wizard: browse reMarkable -> pick file -> options -> run.

Uses `questionary` for arrow-key navigation, icons, and inline validation.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

import questionary
from questionary import Choice

from . import ocr, rmapi


PARENT_SENTINEL = object()
CANCEL_SENTINEL = object()


def _join(parent: str, name: str) -> str:
    if parent in ("", "/"):
        return f"/{name}"
    return f"{parent.rstrip('/')}/{name}"


def _parent(path: str) -> str:
    if path in ("", "/"):
        return "/"
    p = path.rstrip("/").rsplit("/", 1)[0]
    return p or "/"


def _build_choices(entries: List[rmapi.RemoteEntry], at_root: bool) -> list:
    """Build a Choice list with folders first, then files, plus nav entries."""
    folders = [e for e in entries if e.is_dir]
    files = [e for e in entries if not e.is_dir]

    choices: list = []
    if not at_root:
        choices.append(Choice(title="📁 ..  (parent folder)", value=PARENT_SENTINEL))

    for e in folders:
        choices.append(Choice(title=f"📁 {e.name}/", value=("dir", e.name)))
    for e in files:
        choices.append(Choice(title=f"📄 {e.name}", value=("file", e.name)))

    choices.append(questionary.Separator())
    choices.append(Choice(title="✖  cancel", value=CANCEL_SENTINEL))
    return choices


def browse_and_pick() -> Optional[str]:
    """Interactive folder browser. Returns the chosen remote file path, or None."""
    current = "/"
    while True:
        try:
            entries = rmapi.ls(current)
        except rmapi.RmapiError as e:
            print(f"error: {e}", file=sys.stderr)
            return None

        choice = questionary.select(
            f"📂  {current}",
            choices=_build_choices(entries, at_root=(current == "/")),
            qmark="",
            instruction="(↑/↓ to move, Enter to select)",
        ).ask()

        if choice is None or choice is CANCEL_SENTINEL:
            return None
        if choice is PARENT_SENTINEL:
            current = _parent(current)
            continue

        kind, name = choice  # type: ignore[misc]
        if kind == "dir":
            current = _join(current, name)
            continue
        return _join(current, name)


def _validate_pages(text: str) -> bool | str:
    text = text.strip()
    if not text:
        return True
    try:
        ocr.parse_pages(text)
        return True
    except ValueError as e:
        return f"invalid: {e}"


def run() -> int:
    questionary.print(
        "rm2md wizard — browse your reMarkable and convert a note to Markdown.",
        style="bold",
    )

    try:
        remote = browse_and_pick()
    except KeyboardInterrupt:
        print("\nAborted.")
        return 130

    if remote is None:
        print("No file selected.")
        return 1

    questionary.print(f"\nSelected: {remote}\n", style="fg:#00aa88 bold")

    try:
        answers = questionary.form(
            output=questionary.text(
                "Output directory:",
                default="output",
            ),
            pages=questionary.text(
                "Pages to OCR (e.g. '1,3,5-7'; empty = all):",
                default="",
                validate=_validate_pages,
            ),
            include_images=questionary.confirm(
                "Extract embedded images?",
                default=True,
            ),
            keep_pdf=questionary.confirm(
                "Keep intermediate PDF in output dir?",
                default=False,
            ),
            model=questionary.text(
                "OCR model:",
                default="mistral-ocr-latest",
            ),
        ).ask()
    except KeyboardInterrupt:
        print("\nAborted.")
        return 130

    if not answers:
        print("Aborted.")
        return 1

    pages_spec = answers["pages"].strip() or None
    output_dir = Path(answers["output"].strip() or "output")

    questionary.print("\nPlan:", style="bold")
    print(f"  remote      : {remote}")
    print(f"  output dir  : {output_dir}")
    print(f"  pages       : {pages_spec or 'all'}")
    print(f"  images      : {'yes' if answers['include_images'] else 'no'}")
    print(f"  keep pdf    : {'yes' if answers['keep_pdf'] else 'no'}")
    print(f"  model       : {answers['model']}\n")

    proceed = questionary.confirm("Proceed?", default=True).ask()
    if not proceed:
        print("Aborted.")
        return 1

    from . import cli as _cli  # local import avoids circular import

    args = argparse.Namespace(
        remote_path=remote,
        output=output_dir,
        keep_pdf=answers["keep_pdf"],
        no_images=not answers["include_images"],
        model=answers["model"],
        pages=pages_spec,
        clean_work=False,
    )
    return _cli.cmd_pull(args)
