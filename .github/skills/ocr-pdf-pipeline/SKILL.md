---
name: ocr-pdf-pipeline
description: "Use when the user wants to convert a PDF to clean Markdown via the local `ocr` CLI (Mistral OCR). Runs the full 3-stage pipeline: (1) OCR the PDF to Markdown + extracted images, (2) replace each extracted image reference with a textual description of the image so the result is consumable as raw text by another LLM, (3) post-process the OCR text to fix typos / OCR misreads while preserving meaning, original language, formatting, line breaks and checkbox/arrow symbols (☐, →). Trigger phrases: 'PDF to markdown', 'OCR pipeline', 'OCR und Bilder beschreiben', 'OCR Fehler beheben', 'PDF aufbereiten', 'PDF für KI lesbar machen'."
---

# OCR PDF Pipeline

Three-stage pipeline that turns a scanned/handwritten PDF into a single LLM-ready Markdown file.

## Conventions

- **Input:** all source PDFs live in `input/` at the repo root. If the user passes a bare filename, resolve it against `input/`.
- **Output:** all generated Markdown + extracted image folders go into `output/` at the repo root. Never write OCR artifacts back into `input/` or next to the source PDF.
- **CLI invocation:** the `ocr` entry point is only available inside the project venv. Always activate it first:
  ```bash
  source .venv/bin/activate
  ```
  If activation fails, fall back to `.venv/bin/ocr` directly. Do **not** call `python -m mistral_ocr.cli` and do **not** reimplement the OCR.

## Inputs

Required:
- `PDF_NAME` — file name (or path) of the source PDF inside `input/`.

Optional:
- `MODEL` — OCR model (default: `mistral-ocr-latest`).
- `NO_IMAGES` — set if image extraction + description should be skipped.

The final Markdown filename is **derived from the OCR'd content** (see Stage 1.b), not from the PDF filename.

## Workflow

### Stage 1.a — OCR (run the CLI)

Run the existing `ocr` command into a temporary slot inside `output/`. **Do not reimplement** the upload/OCR logic.

```bash
source .venv/bin/activate
mkdir -p output
ocr "input/$PDF_NAME" -o "output/$PDF_STEM.md"
# optional: --model "$MODEL"  --no-images
```

`$PDF_STEM` = the source PDF's filename without extension. This produces:
- `output/<PDF_STEM>.md`
- `output/<PDF_STEM>_images/` (if the PDF had images)

Verify after the run:
- The Markdown file exists in `output/`.
- If images were expected, `output/<PDF_STEM>_images/` exists and is non-empty.
- Print a one-line summary (pages, images saved, output path).

If the CLI exits non-zero: surface stderr verbatim and stop. Do not proceed.

### Stage 1.b — Derive content-based filename

Read the produced Markdown and pick a short, descriptive slug **from the content itself** (e.g. first heading, visible date, document type, author/recipient). Then rename the artifacts.

Slug rules:
- Lowercase, ASCII, words separated by `-`.
- Include a date (`YYYY-MM-DD`) if one is clearly visible in the document.
- 3–7 tokens max. No personal data beyond what is already in the filename context (titles, dates, doc type).
- Examples: `2025-06-25-termin-9-dr-krampe`, `arztbrief-kardiologie-2024-11`, `meeting-notes-projekt-x`.

Then rename in place:
```bash
mv "output/$PDF_STEM.md" "output/$SLUG.md"
mv "output/${PDF_STEM}_images" "output/${SLUG}_images"   # if it exists
```

Update every image reference in the Markdown so the path still resolves (`<PDF_STEM>_images/` → `<SLUG>_images/`). After this stage, no filename inside `output/` should still carry the raw PDF stem.

From here on, `OUTPUT_PATH = output/<SLUG>.md`.

### Stage 2 — Describe extracted images

Goal: replace every image reference so the downstream consumer (an LLM reading raw text) does not need to see pixels.

For each Markdown image reference of the form `![<alt>](<images_dir>/<file>)`:

1. View the image file (use the multimodal image-viewing tool).
2. Generate a description in the **same language as the surrounding document text** (auto-detect; for German notes write the description in German).
3. Replace the image tag in-place with a fenced block of the structure below. **Keep the original tag as a comment** so the mapping stays traceable.

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
- Skip silently if `NO_IMAGES` is set or no images were produced.

### Stage 3 — OCR error correction

Operate on the Markdown produced by stages 1 + 2.

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

Apply corrections directly in the Markdown file (in place). Do **not** create a
separate corrections file. Do **not** append a correction table to the document.
After the edit, print a short summary to chat only:
- number of corrections applied,
- count of `[?]` low-confidence markers added,
- list of the few most uncertain fixes the user should sanity-check.

### Stage 4 — Clear `input/`

Only after stages 1–3 finished without errors **and** `output/<SLUG>.md` exists and is non-empty:

```bash
rm -f input/*.pdf
```

Rules:
- Delete only PDF files at the top level of `input/`. Do not touch subdirectories or other file types.
- Skip this stage if any earlier stage failed, was aborted, or produced an empty Markdown file.
- Mention in the chat-side summary which PDFs were removed.

## Output

A single Markdown file at `output/<SLUG>.md` that:
1. Came from the `ocr` CLI (invoked via the project venv),
2. Was renamed using a content-derived slug,
3. Has every image reference replaced by a text description block,
4. Has high-confidence OCR errors corrected in place, with low-confidence guesses marked `[?]`.

Plus a short chat-side summary (counts + most uncertain fixes). No separate files are written.

## Failure modes & recovery

| Symptom | Action |
|---|---|
| `ocr: command not found` | Activate the venv first (`source .venv/bin/activate`) or call `.venv/bin/ocr` directly. Do not fall back to `python -m`. |
| `MISTRAL_API_KEY is not set` | Tell user to set it in `.env`; stop. |
| CLI exits non-zero | Surface stderr; stop. Do not run later stages. |
| PDF not found in `input/` | List `input/` contents, ask the user which file. Do not search elsewhere. |
| Image file unreadable / corrupt | Leave original `![...](...)` tag, add `<!-- image-describe failed: <reason> -->` above it, continue. |
| Whole paragraph unreadable | Keep verbatim, wrap in `<!-- low-confidence OCR -->` … `<!-- /low-confidence -->` markers. |
| Document language unclear | Default to the language of the majority of recognizable tokens. Do not mix languages within a description. |
| No clear slug derivable from content | Fall back to `<YYYY-MM-DD>-<pdf_stem>` using today's date, then continue. |

## Anti-patterns

- ❌ Reimplementing the Mistral OCR call in Python instead of invoking `ocr`.
- ❌ Calling `python -m mistral_ocr.cli` instead of the `ocr` entry point.
- ❌ Writing output next to the source PDF or anywhere outside `output/`.
- ❌ Keeping the raw PDF filename as the final Markdown name.
- ❌ Translating the corrected text into English.
- ❌ Rewriting sentences for style — this stage is OCR repair only.
- ❌ Deleting `![...](...)` lines without leaving a description block.
- ❌ Silently dropping content that was hard to read.
