# rm2md

Pull notebooks and PDFs from your [reMarkable](https://remarkable.com/) tablet
and turn them into clean Markdown using the
[Mistral OCR API](https://docs.mistral.ai/api/#tag/ocr).

The pipeline is:

1. **Download** the document from the reMarkable cloud via
   [`rmapi`](https://github.com/ddvk/rmapi) (bundled binary in `bin/`).
2. **Render** the `.rm` strokes / `.rmdoc` archive to a PDF via
   [`rmc`](https://github.com/ricklupton/rmc) + `cairosvg`.
3. **OCR** the PDF to Markdown via Mistral OCR, optionally extracting
   embedded images alongside the `.md` file.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# Mistral API key (https://console.mistral.ai/api-keys)
export MISTRAL_API_KEY=...        # or put it in a .env file

# One-time reMarkable cloud auth (opens a device-code prompt)
./bin/rmapi-darwin-arm64          # or bin/rmapi-linux-arm64 on Linux
```

The bundled `rmapi` binary is picked up automatically; nothing else to
configure.

## Usage

The CLI entry point is `rm2md` with four subcommands.

### `rm2md wizard`

Interactive flow: browse the reMarkable cloud, pick a document, choose
options (page range, keep PDF, etc.), and run the full pipeline. Recommended
for day-to-day use.

```bash
rm2md wizard
```

### `rm2md ls [PATH]`

List a folder on the reMarkable cloud (default: `/`).

```bash
rm2md ls
rm2md ls /Notes
```

### `rm2md pull REMOTE_PATH`

Download → convert → OCR in one shot. Output goes to `./output/` as
`YYYY-MM-DD-<slug>.md` (plus an images folder if the document contains
images).

```bash
rm2md pull "/Notes/Meeting 2026-04-29"
```

Options:

- `-o, --output DIR` — output directory (default: `./output`)
- `--keep-pdf` — also copy the intermediate PDF into the output directory
- `--clean-work` — delete intermediate files in `input/.rm2md-work/` after a
  successful run (default: keep them for inspection)
- `--no-images` — skip extracting embedded images
- `--model MODEL` — OCR model (default: `mistral-ocr-latest`)
- `--pages SPEC` — only OCR the given 1-indexed pages, e.g. `1,3,5-7`

### `rm2md ocr PDF`

Run only the OCR step on a local PDF (no reMarkable involved).

```bash
rm2md ocr scan.pdf -o scan.md
```

Supports the same `--no-images`, `--model`, and `--pages` options as `pull`.

## Output layout

```
output/
  2026-04-29-meeting.md
  2026-04-29-meeting_images/      # only if the document contains images
input/
  .rm2md-work/
    2026-04-29-meeting/           # downloaded archive + rendered PDF
```
