# BIS Policy Rate Monitor

Minimal scaffold for the BIS Policy Rate Monitor interview exercise.

## Environment setup

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

## CLI

```bash
bis-prates fetch
bis-prates transform
bis-prates report --countries "US,EA,GB,JP,CH" --start "2015-01-01"
```
