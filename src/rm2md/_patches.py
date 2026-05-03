"""Runtime patches applied to third-party rendering libraries.

These exist to fix bugs / omissions in the upstream packages (`rmc`,
`rmscene`) that cause whole pages to fail to render. Importing this module
applies the patches as a side effect — it is imported once at the top of
:mod:`rm2md.convert`.
"""
from __future__ import annotations


def _patch_rmc_highlight_palette() -> None:
    """Add the missing ``PenColor.HIGHLIGHT`` entry to ``rmc``'s palette.

    ``rmc`` 0.3.0 deliberately leaves ``PenColor.HIGHLIGHT`` (id 9) out of
    ``RM_PALETTE`` (see the ``#! Skipped`` comment in ``writing_tools.py``).
    The result is that as soon as a notebook page contains any highlighter
    stroke, ``Highlighter.__init__`` raises ``KeyError: 9`` and the entire
    page fails to render. This is very common: a single yellow highlight in
    a header is enough to lose the whole page.

    We restore the entry with reMarkable's standard yellow highlight color.
    Idempotent — safe to call multiple times.
    """
    try:
        from rmc.exporters import writing_tools as _wt  # type: ignore[import-not-found]
        from rmscene.scene_items import PenColor  # type: ignore[import-not-found]
    except Exception:  # pragma: no cover - upstream package missing/renamed
        return

    palette = getattr(_wt, "RM_PALETTE", None)
    if palette is None:
        return
    if PenColor.HIGHLIGHT not in palette:
        palette[PenColor.HIGHLIGHT] = (251, 247, 25)


def apply_all() -> None:
    """Apply every runtime patch. Idempotent."""
    _patch_rmc_highlight_palette()


apply_all()
