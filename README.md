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

`bis-prates transform` uses pandas to read the cached ZIP in chunks and writes a
tidy CSV to `data/processed/policy_rates_tidy.csv`, with run metadata in
`data/processed/transform_manifest.json`. Rows with `obs_value` equal to `""` or
`"NaN"`, or with `obs_status_code` equal to `"M"`, are also written to
`data/processed/missing_observations.csv` for review.
