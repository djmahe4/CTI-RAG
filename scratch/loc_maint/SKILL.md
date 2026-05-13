---
name: cti-rag-localization-maint
description: Maintain English localization for CTI-RAG. Scan for Chinese regressions, translate new files, and lint for non-ASCII characters.
---

# CTI-RAG Localization Maintenance Skill

Use this skill to ensure the CTI-RAG repository remains English-first during future development, patches, or when new files are added.

## Core Capabilities

1.  **Scanning**: Find any Chinese characters in the codebase.
2.  **Translation**: Translate Python comments, strings, and Markdown prose from Chinese to English.
3.  **Linting**: Verify that a specific file or the whole repository follows the localization standard.

## Tools in `scratch/loc_maint/`

### 0. Engine Setup (`init_engine.py`)
Initializes the offline translation model (ZH -> EN).
```bash
python scratch/loc_maint/init_engine.py
```

### 1. Scanner (`scan.py`)
Scans the repository (excluding `stopwords.py`, `.venv`, etc.) for any Chinese characters.
```bash
python scratch/loc_maint/scan.py
```

### 2. Translation Engine (`translate.py`)
Translates a file using the `argostranslate` engine.
- **Dry Run**: `python scratch/loc_maint/translate.py path/to/file.py`
- **Apply**: `python scratch/loc_maint/translate.py path/to/file.py --apply`
- **Lint Single File**: `python scratch/loc_maint/translate.py path/to/file.py --lint`

## Maintenance Workflow

### When a new patch adds Chinese comments:
1. Run `python scratch/loc_maint/scan.py` to identify the files.
2. For each file, run `python scratch/loc_maint/translate.py <file> --apply`.
3. Verify with `scan.py` again.

### Pre-commit Check:
Run the scanner to ensure no Chinese characters are staged (excluding ignored data files).

## Exclusions
- `packages/utils/stopwords.py`: Contains necessary Chinese stop words.
- `benchmark/dataset.xlsx`: Evaluation data.
- `.venv/`, `node_modules/`, `.git/`: Infrastructure directories.
