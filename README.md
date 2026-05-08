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
tidy Parquet dataset to `data/processed/policy_rates_tidy.parquet`, with run metadata in
`data/processed/transform_manifest.json`. Rows with `obs_value` equal to `""` or
`"NaN"`, or with `obs_status_code` equal to `"M"`, are also written to
`data/processed/missing_observations.csv` for review.

`bis-prates report` reads `data/processed/policy_rates_tidy.parquet` and writes
the required report outputs to `out/`:

```text
out/summary.csv
out/summary.json
out/policy_rates.png
out/report.html
```

Before generating the report, `bis-prates report` uses `data/raw/fetch_manifest.json`
to locate the downloaded archive, reads `STRUCTURE_ID` from the CSV inside it to
discover the BIS dataflow, queries its SDMX structure with `pysdmx`, then pulls
the declared `REF_AREA` codelist and validates the requested country or area
codes. Invalid codes fail fast with "did you mean" suggestions where a close
match is available. The downloaded SDMX codelist is cached in
`data/raw/sdmx_ref_area_codes.json` and reused if the BIS metadata service is
temporarily unavailable. If the live metadata request fails after retries and no
cache is present, the report still runs and validates requested codes against
the local processed dataset only.
