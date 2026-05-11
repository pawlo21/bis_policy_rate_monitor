# BIS Policy Rate Monitor

Small Python CLI tool for the interview exercise: ingest the latest BIS central
bank policy-rate bulk file, transform it into a tidy analytical dataset, and
generate a country-level HTML report with summary outputs and charts.

The implementation covers the required task, both optional exercise extensions,
and one additional exploratory enrichment:

- BIS SDMX metadata validation for requested country/area codes.
- BIS central bankers' speeches enrichment with keyword counts.
- Optional Transformer Assessment: a configurable hawkish/dovish stance
  assessment for BIS speeches.

The Optional Transformer Assessment was added as an exploratory enrichment. The proposed speeches extension counts
transparent keywords such as `inflation`, `rate`, and `tightening`; the
transformer adds a second view by estimating the direction of policy language as
hawkish, dovish, or neutral. This helps demonstrate how the reporting pipeline
could combine structured policy-rate data with richer unstructured-text
analytics, while still keeping the core required workflow simple and
reproducible.

## Quick Start

This repository is configured for `uv`.

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
uv run bis-prates fetch
uv run bis-prates transform
uv run bis-prates report --countries "US,EA,GB,JP,CH" --start "2015-01-01"
```

To include the speeches extension:

```bash
uv run bis-prates report --countries "US,EA,GB,JP,CH" --start "2015-01-01" --speeches=true
```

To include the optional transformer stance assessment:

```bash
uv run bis-prates report --countries "US,EA,GB,JP,CH" --start "2015-01-01" --speeches=true --assess-sentiment
```

The transformer run is configurable. The default is laptop-friendly: it
classifies up to 12 policy-relevant sentences per speech in batches of 32.

```bash
# More complete but slower: classify all matching policy-relevant sentences
uv run bis-prates report --countries "US,EA,GB,JP,CH" --start "2015-01-01" --speeches=true --assess-sentiment --sentiment-sentences-per-speech 0

# Faster exploratory run
uv run bis-prates report --countries "US,EA,GB,JP,CH" --start "2015-01-01" --speeches=true --assess-sentiment --sentiment-sentences-per-speech 4 --sentiment-batch-size 32
```

If `uv` is not available, the project can also be installed with standard
Python tooling:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip setuptools wheel
python -m pip install -e ".[transformer]"
```

Then replace `uv run bis-prates ...` with `bis-prates ...`.

## CLI Workflow

```bash
# 1. Discover, download, and cache the latest BIS policy-rate flat CSV ZIP
uv run bis-prates fetch

# 2. Parse the raw archive into a tidy local dataset
uv run bis-prates transform

# 3. Generate report outputs for requested country/area codes
uv run bis-prates report --countries "US,EA,GB,JP,CH" --start "2015-01-01"
```

Generated required outputs:

```text
out/summary.csv
out/summary.json
out/policy_rates.png
out/report.html
```

Additional outputs when speeches are enabled:

```text
out/speeches_terms.png
out/speeches_sentiment.png
```

## What The Tool Does

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
uv run bis-prates report --countries "US,EA,GB,JP,CH" --start "2015-01-01"
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

## Tests, Linting, And Security Checks

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

The test suite covers parsing, country-code validation, latest snapshot
calculation, missing-observation handling, deduplication, report generation,
speech term counts, and transformer scoring with a mocked model pipeline. The
transformer tests do not download the model; they use deterministic fake
predictions to keep tests fast and reproducible.

Security and dependency practices:

- Dependabot is configured for Python dependencies and GitHub Actions updates.
- Bandit scans the source tree for common Python security issues.
- `pip-licenses` fails CI on GPL/AGPL/LGPL dependencies.
- SonarQube Cloud runs once per workflow on Python 3.11 to avoid duplicate
  analyses across the matrix.
- Coverage XML is uploaded as a CI artefact for the Python 3.11 run.

## Engineering Notes

I focused on keeping the implementation practical, explicit, and reviewable:

- CLI commands are separated into fetch, transform, and report stages.
- Raw and processed artefacts are cached separately.
- Metadata calls include retry and cache fallback behaviour.
- Country-code validation fails early with suggestions where possible.
- Large raw files are read in a controlled way rather than loaded blindly.
- Optional features are isolated so speech download/model issues do not break
  the required policy-rate report.
- The report is self-contained HTML with embedded charts, making it easy to
  share without a running service.

I also spent time on secure and robust coding practices: bounded downloads,
explicit URL handling, careful exception handling, non-destructive cache usage,
input validation, test injection points, and deterministic unit tests for
external dependencies. At repository level, I added automated safeguards through
GitHub Actions, Dependabot, pre-commit hooks, Ruff, Bandit, license scanning,
mypy, Pylint, pytest coverage, and SonarQube Cloud.

## AI Usage Note

I used AI coding assistance during the project as an implementation accelerator:
for scaffolding modules, generating initial test cases, suggesting refactoring
patterns, and exploring how to structure the optional speech and transformer
extensions. I was responsible for the design decisions, final code structure,
validation approach, and manual review. The most important part was knowing what
the tool needed to do, checking whether generated code actually satisfied that
goal, and improving it when it did not.

Several AI-generated suggestions required correction before they were acceptable.
Examples included overly broad or duplicated exception handling, missing
docstrings, insufficient retry/cache behaviour for HTTP metadata calls, and
initial transformer logic that was too slow or too easy to misinterpret. I
reviewed those areas manually, added tests, improved the CLI controls, and made
the optional NLP outputs explicit about their limitations. AI helped with code
generation, but the engineering judgement, verification, and production-safety
work were done manually.
