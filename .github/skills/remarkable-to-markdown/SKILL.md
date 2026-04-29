---
name: remarkable-to-markdown
description: "Use when the user wants to pull a note or PDF from a reMarkable tablet and turn it into clean LLM-ready Markdown via the local `rm2md` CLI (rmapi + rmc + Mistral OCR). Runs the full 4-stage pipeline: (0) browse the reMarkable cloud and pick the right document, (1) `rm2md pull` to download + render + OCR, (2) describe each extracted image so the result is consumable as raw text, (3) post-process the OCR text to fix typos / OCR misreads while preserving meaning, original language, formatting, line breaks and checkbox/arrow symbols (☐, →). Trigger phrases: 'pull from remarkable', 'remarkable to markdown', 'rm2md', 'note vom reMarkable holen', 'reMarkable Notiz aufbereiten', 'handschriftliche Notiz in Markdown'."
---

# reMarkable → Markdown Pipeline

Four-stage pipeline that pulls a document straight from the reMarkable cloud and turns it into a single LLM-ready Markdown file.

This is the **cloud counterpart** to the `ocr-pdf-pipeline` skill. Use this one when the source lives on the reMarkable tablet; use `ocr-pdf-pipeline` when the source is a PDF in `input/`.

## Conventions

- **Source:** lives on the reMarkable cloud, accessed via the bundled `rmapi` binary. Never ask the user to manually download anything.
- **Output:** all generated Markdown + extracted image folders go into `output/` at the repo root. The CLI writes there by default — do not override `-o`.
- **Naming:** `rm2md` auto-creates `output/<YYYY-MM-DD>-<slug>.md` where the slug is derived from the remote document name. Only rename in stage 1.b if the auto-slug is generic (e.g. `notebook`, `untitled`, `quick-sheets`).
- **CLI invocation:** the `rm2md` entry point is only available inside the project venv. Always activate it first:
  ```bash
  source .venv/bin/activate
  ```
  If activation fails, fall back to `.venv/bin/rm2md` directly. Do **not** call `python -m rm2md.cli` and do **not** reimplement the download/conversion/OCR.
- **Never run `rm2md wizard`** — it is interactive (questionary prompts) and will hang the agent. Use `rm2md ls` + `rm2md pull` instead.
- **Auth:** assumed to already be set up at `~/.config/rmapi/`. If `rmapi` errors with an auth message, surface it and stop — do not try to re-pair the device.

## Inputs

Required (one of):
- `REMOTE_PATH` — full reMarkable cloud path the user already named (e.g. `/Psychotherapie/Urlaubssituation Ostsee`), **or**
- A description of what they want; in that case start at stage 0 and browse to find it.

Optional:
- `PAGES` — 1-indexed selection like `"1,3,5-7"`. Use this whenever the user only cares about a subset; it directly cuts OCR cost.
- `MODEL` — OCR model (default: `mistral-ocr-latest`).
- `KEEP_PDF` — also copy the intermediate PDF into `output/`.
- `NO_IMAGES` — skip image extraction + descriptions.

## Workflow

### Stage 0 — Locate the document on the cloud (only if needed)

Skip this stage if the user already gave a full `REMOTE_PATH`.

Browse top-down with `rm2md ls`. Folders are marked `[d]`, files `[f]`.

```bash
source .venv/bin/activate
rm2md ls /
rm2md ls "/Psychotherapie"
```

Rules:
- Run **one** `ls` per directory level — do not recursively crawl the whole cloud.
- Quote paths with spaces or umlauts.
- If the user's intent matches multiple files, list the candidates back and ask which one. Do **not** guess.
- If `rmapi` fails (auth, network), surface stderr verbatim and stop.

When the right `[f]` entry is found, the full path is `<parent>/<entry name>` — use that as `REMOTE_PATH`.

### Stage 1.a — Pull + convert + OCR

Run `rm2md pull` to do everything in one shot: download the archive via rmapi, render any handwritten `.rm` v6 pages with `rmc` + `cairosvg`, fall through to embedded PDF if the doc is just an uploaded PDF, then OCR with Mistral.

```bash
source .venv/bin/activate
mkdir -p output
rm2md pull "$REMOTE_PATH"
# optional flags:
#   --pages "1,3,5-7"          only OCR these pages (saves credits)
#   --keep-pdf                 also drop the intermediate PDF in output/
#   --no-images                skip image extraction
#   --model mistral-ocr-latest override OCR model
#   --clean-work               delete input/.rm2md-work/<run>/ after success
```

This produces:
- `output/<YYYY-MM-DD>-<slug>.md`
- `output/<YYYY-MM-DD>-<slug>_images/` (if the PDF had images and `--no-images` was not set)
- `output/<YYYY-MM-DD>-<slug>.pdf` (only if `--keep-pdf`)
- `input/.rm2md-work/<YYYY-MM-DD>-<slug>/` — intermediate files (downloaded `.zip`, extracted folder, per-page SVG/PDFs, merged PDF). Kept by default for inspection; pass `--clean-work` to remove on success.

Verify after the run:
- The Markdown file exists in `output/` and is non-empty.
- If images were expected, the `_images/` folder exists and is non-empty.
- Print a one-line summary (slug, pages OCR'd, images saved, output path).

If the CLI exits non-zero: surface stderr verbatim and stop. Do not proceed.

Common `pull`-time warnings that are **not** failures:
- `Some data has not been read. The data may have been written using a newer format than this reader supports.` — printed by `rmscene` for unknown stroke block types. Harmless; pages still render.
- `warn: failed to render page N (...)` — that single page is skipped; the rest still merge. Mention it in the chat summary.
- `Failed to generate annotations ...` from `rmapi` — a server-side annotation flatten attempt failed, but the raw archive was still downloaded. Pipeline continues normally.

### Stage 1.b — Optional content-based rename

`rm2md` already names the file from the remote document title, so 95 % of the time you can skip this stage.

Rename **only** if the auto-slug is clearly unhelpful — e.g. `notebook`, `untitled`, `quick-sheets`, or a generic date-only name. In that case, derive a better slug from the Markdown content (first heading, visible date, document type) and rename in place:

```bash
mv "output/$OLD.md"        "output/$NEW.md"
mv "output/${OLD}_images"  "output/${NEW}_images"   # if it exists
```

Slug rules (same as `ocr-pdf-pipeline`):
- Lowercase, ASCII, words separated by `-`.
- Include a date (`YYYY-MM-DD`) if one is clearly visible in the document.
- 3–7 tokens max.

After renaming, update every image reference in the Markdown so the path still resolves (`<OLD>_images/` → `<NEW>_images/`).

From here on, `OUTPUT_PATH = output/<final-slug>.md`.

### Stage 2 — Describe extracted images

Identical to `ocr-pdf-pipeline` stage 2.

For each Markdown image reference of the form `![<alt>](<images_dir>/<file>)`:

1. View the image file (use the multimodal image-viewing tool).
2. Generate a description in the **same language as the surrounding document text** (auto-detect; for German notes write the description in German).
3. Replace the image tag in-place with a fenced block. **Keep the original tag as a comment** so the mapping stays traceable.

Replacement template:

```markdown
<!-- image: <images_dir>/<file> -->
**Bild / Image: <file>**

<concise but complete textual description: type of figure, axes, labels,
arrows, colors, callouts, numbered zones, key takeaway. 1 short paragraph
+ a bullet list of labeled elements when the image is a diagram/chart.>
```

Rules:
- Describe **what is on the image**, not what it might mean clinically/legally.
- For diagrams/charts: list axes, units, ranges, every label, every arrow/annotation, color coding.
- For photos: subject, setting, salient objects, readable text.
- Preserve the position of the original `![...](...)` line — replace, don't move.
- Do **not** delete the image file from disk.
- Skip silently if `NO_IMAGES` was set or no images were produced.

### Stage 3 — OCR error correction

Identical to `ocr-pdf-pipeline` stage 3.

Hard rules (do not violate):
- **Preserve the original language.** Do not translate.
- **Preserve structure exactly:** headings, blank lines, bullet markers, numbering, indentation, line breaks within a paragraph, and special characters used as bullets (`☐`, `→`, `•`, `–`).
- **Do not remove content.** Only fix what is clearly an OCR misread.
- **Do not touch the image-description blocks** added in stage 2.
- **Do not invent facts**, names, dates or numbers. If a token is unreadable and you cannot infer it with high confidence from immediate context, leave it as-is and mark it with a trailing `[?]`.

What to fix:
- Obvious character confusions (`rn`↔`m`, `cl`↔`d`, `0`↔`O`, `1`↔`l`/`I`).
- Wrongly split or merged words (`zurück gekehrt` → `zurückgekehrt`, `reinzelaufen` → `reingelaufen`).
- Capitalization of nouns in German.
- Phonetic OCR garble that has an obvious correct reading from context
  (e.g. `Genommenheit` → `Benommenheit`, `Herzkopfen` → `Herzklopfen`).
- Punctuation only when clearly missing/duplicated.

Handwriting-specific OCR quirks worth scanning for (more common than in scanned PDFs):
- Mid-word case flips (`derPatient` → `der Patient`).
- Crossed-out words read as garbage tokens — wrap in `<!-- low-confidence OCR -->` markers if you cannot infer them.
- Checkbox/arrow glyphs swapped with random letters (`D` for `☐`, `>` for `→`) — restore the symbol.

Apply corrections directly in the Markdown file (in place). Do **not** create a separate corrections file. Do **not** append a correction table to the document.

After the edit, print a short summary to chat only:
- number of corrections applied,
- count of `[?]` low-confidence markers added,
- list of the few most uncertain fixes the user should sanity-check.

## Output

A single Markdown file at `output/<final-slug>.md` that:
1. Came from `rm2md pull` (invoked via the project venv),
2. Has every image reference replaced by a text description block,
3. Has high-confidence OCR errors corrected in place, with low-confidence guesses marked `[?]`.

Plus a short chat-side summary (counts + most uncertain fixes + any pages that failed to render). No separate files are written. Nothing is deleted from the reMarkable cloud.

## Failure modes & recovery

| Symptom | Action |
|---|---|
| `rm2md: command not found` | Activate the venv first (`source .venv/bin/activate`) or call `.venv/bin/rm2md` directly. Do not fall back to `python -m`. |
| `MISTRAL_API_KEY is not set` | Tell user to set it in `.env`; stop. |
| `rmapi` auth/login error | Surface stderr; tell user to run `rmapi` once manually to re-pair. Do not try to authenticate from the agent. |
| Network / cloud timeout from `rmapi` | Surface stderr; suggest retry. Do not loop. |
| `ConvertError: No pages could be rendered` | The notebook's `.rm` files all failed to parse. Inspect `input/.rm2md-work/<run>/` (kept by default) to see what was downloaded and which per-page PDFs are missing. If cairo/inkscape errors appear, ensure `brew install cairo` was done. |
| Some pages skipped with `warn: failed to render page N` | Continue. Mention the missing page numbers in the final summary. |
| User asked for a specific subset | Always pass `--pages "..."` rather than OCR'ing the whole doc and trimming after. |
| Document not found (`rmapi: ... no such file`) | Re-run `rm2md ls` on the parent folder and ask the user which entry they meant. Do not retry blindly. |
| `cairosvg` ImportError about `cairo` | Tell user to `brew install cairo` (macOS) / `apt install libcairo2` (Linux); stop. |
| Image file unreadable / corrupt | Leave original `![...](...)` tag, add `<!-- image-describe failed: <reason> -->` above it, continue. |
| Whole paragraph unreadable | Keep verbatim, wrap in `<!-- low-confidence OCR -->` … `<!-- /low-confidence -->` markers. |

## Anti-patterns

- ❌ Running `rm2md wizard` from the agent — it is interactive and will hang.
- ❌ Reimplementing the rmapi/rmc/Mistral calls in Python instead of invoking `rm2md`.
- ❌ Calling `python -m rm2md.cli` instead of the `rm2md` entry point.
- ❌ Recursively `ls`-ing the whole reMarkable cloud "to find it" — ask the user instead.
- ❌ Writing output anywhere other than `./output/`.
- ❌ Renaming the output file when the auto-slug was already meaningful.
- ❌ OCR'ing the whole document when the user asked for specific pages — always use `--pages`.
- ❌ Translating the corrected text into English.
- ❌ Rewriting sentences for style — stage 3 is OCR repair only.
- ❌ Deleting `![...](...)` lines without leaving a description block.
- ❌ Trying to re-pair / re-authenticate `rmapi` from inside the agent.
