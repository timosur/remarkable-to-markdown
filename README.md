# mistral-ocr

A small CLI that converts a PDF to Markdown using the [Mistral OCR API](https://docs.mistral.ai/api/#tag/ocr).

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
cp .env.example .env
# edit .env and set MISTRAL_API_KEY
```

Get an API key at https://console.mistral.ai/api-keys.

## Usage

```bash
ocr asdf.pdf
```

Produces `asdf.md` and an `asdf_images/` folder (if the PDF contains images) in the current directory.

### Options

```
ocr PDF [-o OUTPUT] [--no-images] [--model MODEL]
```

- `-o, --output` — output markdown path (default: `<pdf_stem>.md`)
- `--no-images` — skip extracting embedded images
- `--model` — OCR model name (default: `mistral-ocr-latest`)
