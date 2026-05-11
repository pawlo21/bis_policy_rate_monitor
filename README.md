# BIS Policy Rate Monitor

Small Python CLI tool for the interview exercise: ingest the latest BIS central
bank policy-rate bulk file, transform it into a tidy analytical dataset, and
generate a country-level HTML report with summary outputs and charts.

The project is structured as a compact analytical data product: staged CLI
workflow, raw/processed data layers, SDMX-aware metadata validation, auditable
data-quality outputs, automated checks, and optional NLP enrichment.

The implementation covers the required task, both optional exercise extensions,
and one additional exploratory enrichment:

- BIS SDMX metadata validation for requested country/area codes.
- BIS central bankers' speeches enrichment with keyword counts.
- Optional Transformer Assessment: a configurable hawkish/dovish stance
  assessment for BIS speeches.

The transformer assessment is exploratory. The required speeches extension counts
transparent keywords such as `inflation`, `rate`, and `tightening`; the
transformer adds a controlled second signal by estimating whether policy language
is hawkish, dovish, or neutral. This separates topic intensity from directional
language while keeping the required workflow simple and reproducible.

## Quick Start

This repository uses `uv` and `uv.lock` for reproducible dependency setup.

Minimal setup for the required exercise:

```bash
uv sync
```

Optional setup for the transformer speech assessment:

```bash
uv sync --extra transformer
```

Then run the pipeline:

```bash
source .venv/bin/activate
bis-prates fetch
bis-prates transform
bis-prates report --countries "US,EA,GB,JP,CH" --start "2015-01-01"
```

To include the speeches extension:

```bash
bis-prates report --countries "US,EA,GB,JP,CH" --start "2015-01-01" --speeches=true
```

To include the optional transformer stance assessment:

```bash
bis-prates report --countries "US,EA,GB,JP,CH" --start "2015-01-01" --speeches=true --assess-sentiment
```

The transformer run is configurable. The default is laptop-friendly: it
classifies up to 12 policy-relevant sentences per speech in batches of 32.

```bash
# More complete but slower: classify all matching policy-relevant sentences
bis-prates report --countries "US,EA,GB,JP,CH" --start "2015-01-01" --speeches=true --assess-sentiment --sentiment-sentences-per-speech 0

# Faster exploratory run
bis-prates report --countries "US,EA,GB,JP,CH" --start "2015-01-01" --speeches=true --assess-sentiment --sentiment-sentences-per-speech 4 --sentiment-batch-size 32
```

If `uv` is not available, the project can also be installed with standard
Python tooling:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e .

# Optional, only needed for the transformer assessment
python -m pip install -e ".[transformer]"
```

## Output Files


Generated required outputs:

```text
out/summary.csv
out/summary.json
out/policy_rates.png
out/report.html
```

Additional output when speeches are enabled:

```text
out/speeches_terms.png
```

Additional output when transformer assessment is enabled:

```text
out/speeches_sentiment.png
```

## Project Layout

```text
src/bis_prates/fetch.py              # BIS bulk-download discovery and caching
src/bis_prates/transform.py          # raw CSV to tidy Parquet transformation
src/bis_prates/metadata.py           # BIS SDMX metadata and REF_AREA validation
src/bis_prates/report/core.py        # report orchestration
src/bis_prates/report/data.py        # country selection and latest snapshot logic
src/bis_prates/report/chart.py       # policy-rate chart rendering
src/bis_prates/report/json_writer.py # summary JSON output
src/bis_prates/report/html_writer.py # self-contained HTML report
src/bis_prates/speeches.py           # BIS speeches keyword extension
src/bis_prates/speech_sentiment.py   # optional transformer speech assessment
tests/unit/                          # deterministic unit tests
```

## What the Tool Does

### Fetch

`bis-prates fetch` discovers the latest BIS "Central bank policy rates (CSV,
flat)" ZIP from the BIS Data Portal bulk downloads page and stores it in
`data/raw/`. It also writes a manifest with the selected dataset, source URL,
archive path, and release metadata.

### Transform

`bis-prates transform` reads the cached archive, parses the flat CSV, normalises
field names, deduplicates observations, converts dates and numeric values, and
writes a tidy Parquet dataset:

```text
data/processed/policy_rates_tidy.parquet
```

Rows with missing or invalid observations are also written separately for review:

```text
data/processed/missing_observations.csv
```

The transform keeps useful time-series attributes such as:

- country/area code and label
- frequency
- series title
- source reference
- compilation note
- unit measure
- unit multiplier
- decimals
- observation status

### Report

`bis-prates report` reads the tidy dataset, validates requested countries, builds
a latest snapshot table, renders the policy-rate chart, and writes a
self-contained HTML report.

The latest snapshot includes the latest valid observation, previous valid
observation, change from previous, metadata attributes, and data recency.

Example:

```bash
bis-prates report --countries "US,EA,GB,JP,CH" --start "2015-01-01"
```

## Optional Extension 1: BIS SDMX Metadata

The report validates requested country and area codes using BIS SDMX metadata.

The implementation reads the `STRUCTURE_ID` from the downloaded flat CSV to
identify the BIS dataflow, queries the SDMX structure metadata with `pysdmx`,
discovers the `REF_AREA` codelist, and fetches the allowed country/area codes.

This allows the CLI to fail fast on invalid input and provide "did you mean"
suggestions. For example, `EA` is handled as a user-friendly alias for the BIS
Euro area code `XM`.

To avoid repeatedly calling the metadata service, the downloaded codelist is
cached in:

```text
data/raw/sdmx_ref_area_codes.json
```

If live metadata is temporarily unavailable, the report falls back to the cache.
If no cache exists, the report still runs and validates requested codes against
the local processed dataset.

## Optional Extension 2: BIS Speeches NLP

When `--speeches=true` is provided, the report loads BIS central bankers'
speeches for the last two years using `gingado` where possible, with a direct BIS
speech ZIP download fallback.

The required mini-NLP section counts transparent keyword families:

- `inflation`
- `rate`
- `tightening`

The report compares monthly term frequencies with signed monthly policy-rate
moves. This is intentionally simple and auditable: it answers "what topics are
being mentioned more often?"

## Optional Transformer Assessment

When `--assess-sentiment` is added, the speeches section also runs an optional
transformer enrichment using:

```text
brjoey/CBSI-CentralBank-BERT
```

This model classifies policy-relevant speech sentences as:

- hawkish
- dovish
- neutral

The code then aggregates sentence labels into a speech-level score:

```text
net_hawkish_score = (hawkish sentences - dovish sentences) / classified sentences
```

Monthly scores are calculated by averaging the speech-level scores, so one long
speech does not dominate a month just because it contains more sentences.

This extension is useful because keyword counts and transformer stance measure
different things:

- keyword counts measure topic intensity
- transformer scores estimate direction of policy language

I treat this transformer output as an exploratory analytical signal rather than
ground truth. I manually compared a small sample of speech classifications with
GPT-based qualitative assessments of the same speeches, and the classifications
were generally directionally aligned.

## Tests, Linting, and Security Checks

The project includes unit tests, local pre-commit hooks, and a GitHub Actions CI
pipeline. The CI runs on Python 3.11 and 3.12 and checks formatting, linting,
security, type hints, licenses, tests with coverage, and SonarQube Cloud
analysis.

Run the full local check suite:

```bash
uv run ruff check
uv run ruff format --check
uv run bandit -r src/ -c pyproject.toml
uv run pip-licenses --fail-on="GPL;AGPL;LGPL" --format=markdown
uv run mypy
uv run pylint src/
uv run pytest
```

Run formatting/linting during development:

```bash
uv run ruff format
uv run ruff check --fix
```

Install and run pre-commit hooks:

```bash
uv run pre-commit install
uv run pre-commit run --all-files
```

The pre-commit configuration checks common repository hygiene issues such as
trailing whitespace, YAML/TOML validity, merge-conflict markers, debug
statements, large added files, line endings, Ruff linting, and Ruff formatting.
Generated report artefacts under `out/` are excluded so hooks do not rewrite
outputs that should be regenerated by the CLI.

The test suite covers fetch discovery and cache behaviour, CLI parsing, raw-data
parsing, country-code validation, latest snapshot calculation, missing-observation
handling, deduplication, report generation, speech term counts, and transformer
scoring with a mocked model pipeline. The transformer tests do not download the
model; they use deterministic fake predictions to keep tests fast and reproducible.

Security and dependency practices:

- Dependabot is configured for Python dependencies and GitHub Actions updates.
- Bandit scans the source tree for common Python security issues.
- `pip-licenses` fails CI on GPL/AGPL/LGPL dependencies.
- SonarQube Cloud runs once per workflow on Python 3.11 to avoid duplicate
  analyses across the matrix.
- Coverage XML is uploaded as a CI artefact for the Python 3.11 run.
- The GitHub repository uses branch protection on `master`: direct commits are
  blocked, changes are developed on feature branches, and updates are merged
  after pull request review.

## Engineering Notes

I kept the pipeline explicit: `fetch` discovers and caches the BIS ZIP,
`transform` converts it to a tidy Parquet dataset, and `report` reads only the
processed data to produce CSV, JSON, PNG, and self-contained HTML outputs.

Key design decisions:

- Parse the BIS bulk-download page to discover the latest policy-rate ZIP instead
  of hardcoding a filename or URL.
- Store the transformed analytical dataset as Parquet to preserve schema and make
  repeated report runs faster than reparsing the raw CSV.
- Write missing or invalid observations to a separate CSV audit file instead of
  silently dropping them.
- Split the original report implementation into focused modules for data
  selection, charting, JSON writing, HTML rendering, and orchestration after the
  report code became too large to review comfortably.

The implementation uses concrete guardrails rather than relying on assumptions:
cache manifests with remote validators, bounded downloads, parsed/normalised
URLs, chunked CSV processing, duplicate fingerprints on
`(freq_code, ref_area_code, time_period)`, a separate missing-observation audit
file, SDMX `REF_AREA` validation with cache fallback, and deterministic test
doubles for external services.

Optional speech and transformer enrichment is isolated behind the report
extension path. If speech download or model inference fails, stale optional
charts are removed and the required policy-rate report still completes.

## AI Usage Note
I used Claude Opus 4.7 through Claude Code and GPT-5.5 through Codex as coding assistants. They generated much of the initial implementation and unit tests, and helped create the initial project structure, suggest refactoring options, and explore ideas for the optional speech and transformer extensions. The CLI workflow, data model, country code validation strategy, report outputs (HTML), and final code review were decided and verified manually.

After reviewing the generated code, I made several design corrections: discovering the BIS ZIP from the bulk-download page instead of hardcoding a URL, storing the tidy dataset as Parquet, keeping missing observations in a separate CSV audit file, showing policy-rate moves by individual country in the NLP chart instead of aggregating all selected countries together, and splitting an oversized report module into focused submodules. Important correction was the SDMX metadata logic: the AI-generated approach did not reliably identify the country/area codelist from the dataflow metadata. I rewrote it to discover the dataflow from the downloaded CSV, inspect the structure metadata, identify `REF_AREA`, and validate countries against the correct codelist. I also directed the production-safety checks and used AI to help design the quality pipeline and fix issues found by linting, formatting, typing, security, and test tools.
