# BIS Policy Rate Monitor

Minimal scaffold for the BIS Policy Rate Monitor interview exercise.

## Environment setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .
```

## CLI

```bash
bis-prates fetch
bis-prates transform
bis-prates report --countries "US,EA,GB,JP,CH" --start "2015-01-01"
```

`bis-prates fetch` stores the raw ZIP in `data/raw/` and records cache metadata
in `data/raw/fetch_manifest.json`.
