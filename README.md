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

## Getting started

1. **Install**:

   ```bash
   curl -fsSL https://raw.githubusercontent.com/timosur/remarkable-to-markdown/main/install.sh | bash
   ```

   Then put your Mistral API key into the central config:

   ```bash
   $EDITOR ~/.config/rm2md/config
   ```

2. **Pair this machine with the reMarkable cloud** (one-time):

   ```bash
   rm2md login
   ```

   `rmapi` prints a URL
   ([my.remarkable.com/device/desktop/connect](https://my.remarkable.com/device/desktop/connect))
   and waits for the 8-character one-time code shown there. Paste it into
   the prompt; the token is stored in `~/.config/rmapi/rmapi.conf` so you
   only need to do this once per machine.

3. **Find the document you want** by browsing your cloud:

   ```bash
   rm2md ls
   rm2md ls /Notes
   ```

4. **Pull it as Markdown**:

   ```bash
   rm2md pull "/Notes/Meeting 2026-04-29"
   ```

   The result lands in `./output/YYYY-MM-DD-HHMM-<slug>.md` (plus an
   `_images/` folder if the document contains images).

Prefer a guided flow? Run `rm2md wizard` to browse, pick a document, and
choose options interactively.

## Agent skill (Claude Code / Copilot)

This repo ships a packaged
[Claude Code skill](https://docs.claude.com/en/docs/claude-code/skills) at
[.github/skills/remarkable-to-markdown/SKILL.md](.github/skills/remarkable-to-markdown/SKILL.md).
It teaches an AI agent the full 4-stage workflow built on top of this CLI:

0. Browse the reMarkable cloud with `rm2md ls` to find the document.
1. Run `rm2md pull` to download → render → OCR.
2. View each extracted image and replace its Markdown reference with a
   text description (so the result is consumable as raw text).
3. Post-process the OCR output to fix typos / OCR misreads while preserving
   the original language, structure, line breaks, and special glyphs
   (`☐`, `→`, …).

### When to use it

Trigger the skill whenever you want a handwritten reMarkable note turned
into clean LLM-ready Markdown — not just the raw OCR. Typical prompts that
activate it:

- "pull `<note name>` from remarkable"
- "remarkable to markdown"
- "rm2md `<path>`"
- German equivalents like "Notiz vom reMarkable holen" or "handschriftliche
  Notiz in Markdown".

Skip the skill (just call `rm2md` directly) when you only need the raw OCR
output and don't want image descriptions or correction passes.

### How to use it

- **Claude Code:** the skill is auto-discovered from `.github/skills/`.
  Just describe what you want in natural language ("pull
  /Psychotherapie/Sitzung 12 from remarkable") and Claude will load the
  skill and run the pipeline.
- **GitHub Copilot / other agents:** point the agent at
  [.github/skills/remarkable-to-markdown/SKILL.md](.github/skills/remarkable-to-markdown/SKILL.md)
  and ask it to follow the workflow there.

Prerequisites the skill assumes are already done by you:

- `rm2md login` has been run once on this machine.
- `MISTRAL_API_KEY` is set (in the environment or a `.env` file).
- The project venv exists at `.venv/` (the skill activates it itself; it
  will **not** call `rm2md wizard`, since the wizard is interactive and
  would hang the agent).

## Commands

The CLI entry point is `rm2md` with the following subcommands.

### `rm2md login`

Pair this machine with the reMarkable cloud via `rmapi`'s interactive
one-time-code flow. Run this once before using `ls`, `pull`, or `wizard`.

```bash
rm2md login
```

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
`YYYY-MM-DD-HHMM-<slug>.md` (plus an images folder if the document contains
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
