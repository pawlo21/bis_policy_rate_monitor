"""BIS SDMX metadata helpers for country-code validation."""

from __future__ import annotations

import csv
import json
import logging
import re
import time
import zipfile
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from difflib import get_close_matches
from pathlib import Path
from typing import IO

import msgspec
from pysdmx.api.qb import (
    ApiVersion,
    RestService,
    StructureDetail,
    StructureQuery,
    StructureReference,
    StructureType,
)
from pysdmx.io.json.sdmxjson2.messages.code import JsonCodelistMessage

log = logging.getLogger(__name__)

BIS_SDMX_API_ENDPOINT = "https://stats.bis.org/api/v2"
DEFAULT_RAW_DIR = Path("data/raw")
DEFAULT_FETCH_MANIFEST_PATH = DEFAULT_RAW_DIR / "fetch_manifest.json"
DEFAULT_METADATA_CACHE_PATH = Path("data/raw/sdmx_ref_area_codes.json")
DEFAULT_METADATA_ATTEMPTS = 2
DEFAULT_RETRY_DELAY_SECONDS = 1.0
REF_AREA_DIMENSION_ID = "REF_AREA"
COUNTRY_ALIASES = {
    "EA": "XM",
}
SUGGESTION_ALIASES = {
    "EU": ["XM"],
    "UK": ["GB"],
}


@dataclass(frozen=True)
class SdmxDataflowReference:
    """SDMX dataflow identity (`agency:id(version)`)."""

    agency: str
    dataflow_id: str
    version: str


@dataclass(frozen=True)
class SdmxCodelistReference:
    """SDMX codelist identity (`agency:id(version)`)."""

    agency: str
    codelist_id: str
    version: str


@dataclass(frozen=True)
class InvalidCountryCode:
    """A requested country code that did not validate, plus suggested alternatives."""

    code: str
    suggestions: list[str]


class CountryCodeValidationError(ValueError):
    """Raised when one or more requested country codes are not in the BIS codelist."""

    def __init__(self, invalid_codes: list[InvalidCountryCode]) -> None:
        """Build the error from a list of invalid codes with their suggestions."""
        self.invalid_codes = invalid_codes
        super().__init__(format_invalid_country_codes(invalid_codes))


def fetch_reference_area_codes(
    archive_path: Path | None = None,
    timeout: float = 20.0,
    cache_path: Path = DEFAULT_METADATA_CACHE_PATH,
    attempts: int = DEFAULT_METADATA_ATTEMPTS,
    retry_delay_seconds: float = DEFAULT_RETRY_DELAY_SECONDS,
) -> dict[str, str] | None:
    """Discover and pull BIS reference-area codes using the downloaded CSV."""
    max_attempts = max(1, attempts)
    last_error: Exception | None = None

    for attempt in range(1, max_attempts + 1):
        try:
            log.info("BIS SDMX metadata fetch attempt %d/%d", attempt, max_attempts)
            codes = _fetch_reference_area_codes_live(archive_path, timeout, cache_path)
            return codes
        except Exception as error:
            last_error = error
            log.warning(
                "Live BIS SDMX metadata fetch attempt %d/%d failed: %s",
                attempt,
                max_attempts,
                error,
            )
            if attempt < max_attempts:
                delay = retry_delay_seconds * attempt
                log.info("Retrying BIS SDMX metadata fetch in %.1f seconds", delay)
                time.sleep(delay)

    cached_codes = load_cached_reference_area_codes(cache_path)
    if cached_codes:
        log.info(
            "Using cached BIS SDMX reference-area codes from %s (%d codes)",
            cache_path,
            len(cached_codes),
        )
        return cached_codes

    log.warning(
        "Skipping BIS SDMX validation; live metadata failed after %d attempt(s), "
        "no cache exists at %s. Last error: %s",
        max_attempts,
        cache_path,
        last_error,
    )
    return None


def _fetch_reference_area_codes_live(
    archive_path: Path | None,
    timeout: float,
    cache_path: Path,
) -> dict[str, str]:
    resolved_archive_path = resolve_raw_archive_path(archive_path)
    log.info("Discovering BIS SDMX dataflow from %s", resolved_archive_path)
    dataflow = discover_dataflow_reference_from_csv(resolved_archive_path)
    log.info(
        "Discovered SDMX dataflow %s:%s(%s)",
        dataflow.agency,
        dataflow.dataflow_id,
        dataflow.version,
    )
    log.info("Discovering REF_AREA codelist from BIS SDMX structure metadata")
    codelist = discover_ref_area_codelist(dataflow, timeout=timeout)
    log.info(
        "Discovered REF_AREA codelist %s:%s(%s)",
        codelist.agency,
        codelist.codelist_id,
        codelist.version,
    )
    log.info("Fetching BIS SDMX codelist codes")
    codes = fetch_codelist_codes(codelist, timeout=timeout)
    log.info("Fetched %d BIS SDMX reference-area codes", len(codes))
    write_metadata_cache(cache_path, dataflow, codelist, codes)
    return codes


def fetch_codelist_codes(
    codelist: SdmxCodelistReference,
    timeout: float = 60.0,
) -> dict[str, str]:
    """Pull every code from a BIS SDMX codelist, returning `{code: name}`."""
    log.info(
        "SDMX query: %s",
        _structure_query_url("codelist", codelist.agency, codelist.codelist_id, codelist.version),
    )
    query = StructureQuery(
        StructureType.CODELIST,
        codelist.agency,
        codelist.codelist_id,
        codelist.version,
    )
    service = RestService(BIS_SDMX_API_ENDPOINT, ApiVersion.V2_0_0, timeout=timeout)
    response = service.structure(query)
    codelist_model = msgspec.json.Decoder(JsonCodelistMessage).decode(response).to_model()
    return {code.id.upper(): code.name or code.id for code in codelist_model.codes}


def discover_dataflow_reference_from_csv(
    archive_path: Path | None = None,
) -> SdmxDataflowReference:
    """Read STRUCTURE_ID from the downloaded BIS flat CSV."""
    archive_path = resolve_raw_archive_path(archive_path)
    with zipfile.ZipFile(archive_path) as archive:
        csv_name = _largest_csv_name(archive)
        log.info("Reading SDMX STRUCTURE_ID from %s inside %s", csv_name, archive_path)
        with archive.open(csv_name) as raw_file:
            row = _first_csv_row(raw_file)

    if row.get("STRUCTURE") != "dataflow":
        raise ValueError(f"Expected STRUCTURE=dataflow, got {row.get('STRUCTURE')!r}.")

    structure_id = row.get("STRUCTURE_ID", "")
    match = re.match(r"^([^:]+):([^(]+)\(([^)]+)\)", structure_id)
    if not match:
        raise ValueError(f"Cannot parse SDMX STRUCTURE_ID: {structure_id!r}.")

    agency, dataflow_id, version = match.groups()
    return SdmxDataflowReference(agency, dataflow_id, version)


def resolve_raw_archive_path(archive_path: Path | None = None) -> Path:
    """Resolve which raw BIS ZIP to use for SDMX discovery.

    Resolution order: the explicit `archive_path` argument, then the path
    in `data/raw/fetch_manifest.json`, then the single `.zip` in `data/raw/`.

    Raises:
        FileNotFoundError: If no archive can be located.
        FileExistsError: If multiple archives exist and no manifest disambiguates.

    """
    if archive_path is not None:
        return Path(archive_path)

    if DEFAULT_FETCH_MANIFEST_PATH.exists():
        manifest = json.loads(DEFAULT_FETCH_MANIFEST_PATH.read_text(encoding="utf-8"))
        manifest_archive_path = manifest.get("archive_path")
        if manifest_archive_path:
            return Path(str(manifest_archive_path))

    zip_paths = sorted(DEFAULT_RAW_DIR.glob("*.zip"))
    if len(zip_paths) == 1:
        return zip_paths[0]
    if not zip_paths:
        raise FileNotFoundError("No raw BIS archive found. Run `bis-prates fetch` first.")
    raise FileExistsError(
        "Multiple raw ZIP archives found and no fetch manifest identifies which one "
        f"to use: {', '.join(str(path) for path in zip_paths)}"
    )


def discover_ref_area_codelist(
    dataflow: SdmxDataflowReference,
    timeout: float = 60.0,
) -> SdmxCodelistReference:
    """Find the REF_AREA codelist declared by the dataflow structure."""
    log.info(
        "SDMX query: %s?references=children",
        _structure_query_url(
            "dataflow",
            dataflow.agency,
            dataflow.dataflow_id,
            dataflow.version,
        ),
    )
    query = StructureQuery(
        StructureType.DATAFLOW,
        dataflow.agency,
        dataflow.dataflow_id,
        dataflow.version,
        detail=StructureDetail.FULL,
        references=StructureReference.CHILDREN,
    )
    service = RestService(BIS_SDMX_API_ENDPOINT, ApiVersion.V2_0_0, timeout=timeout)
    document = json.loads(service.structure(query))
    dataflow_item = document["data"]["dataflows"][0]
    data_structure_id = _structure_id_from_urn(dataflow_item["structure"])
    data_structure = next(
        item for item in document["data"]["dataStructures"] if item["id"] == data_structure_id
    )
    dimensions = data_structure["dataStructureComponents"]["dimensionList"]["dimensions"]
    ref_area = next(item for item in dimensions if item["id"] == REF_AREA_DIMENSION_ID)
    return _codelist_reference_from_urn(ref_area["localRepresentation"]["enumeration"])


def load_cached_reference_area_codes(cache_path: Path) -> dict[str, str]:
    """Load reference-area codes from disk, returning `{}` if no cache file exists."""
    if not cache_path.exists():
        log.info("No BIS SDMX metadata cache found at %s", cache_path)
        return {}

    payload = json.loads(cache_path.read_text(encoding="utf-8"))
    codes = {str(code).upper(): str(name) for code, name in payload.get("codes", {}).items()}
    log.info("Loaded %d BIS SDMX reference-area codes from %s", len(codes), cache_path)
    return codes


def write_metadata_cache(
    cache_path: Path,
    dataflow: SdmxDataflowReference,
    codelist: SdmxCodelistReference,
    codes: Mapping[str, str],
) -> None:
    """Persist the SDMX metadata cache as deterministic JSON."""
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataflow": asdict(dataflow),
        "codelist": asdict(codelist),
        "codes": dict(sorted(codes.items())),
    }
    cache_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    log.info("Wrote BIS SDMX metadata cache to %s", cache_path)


def validate_country_codes(
    requested_codes: Iterable[str],
    valid_codes: Mapping[str, str],
) -> dict[str, str]:
    """Validate requested country codes and return requested -> BIS code mapping."""
    valid = {code.upper(): name for code, name in valid_codes.items()}
    resolved = {}
    invalid = []

    for raw_code in requested_codes:
        code = str(raw_code).strip().upper()
        if not code:
            continue

        actual_code = COUNTRY_ALIASES.get(code, code)
        if actual_code in valid:
            resolved[code] = actual_code
        else:
            invalid.append(InvalidCountryCode(code, suggest_country_codes(code, valid)))

    if invalid:
        raise CountryCodeValidationError(invalid)

    log.info(
        "Validated country codes against BIS SDMX metadata: %s",
        ", ".join(f"{requested}->{actual}" for requested, actual in resolved.items()),
    )
    return resolved


def suggest_country_codes(
    requested_code: str,
    valid_codes: Mapping[str, str],
    limit: int = 3,
) -> list[str]:
    """Suggest up to `limit` valid codes resembling `requested_code`.

    Combines a curated alias map (e.g. `UK -> GB`) with `difflib` close matches.
    """
    code = requested_code.upper()
    suggestions = list(SUGGESTION_ALIASES.get(code, []))
    suggestions.extend(get_close_matches(code, valid_codes.keys(), n=limit, cutoff=0.55))
    return _dedupe([item for item in suggestions if item in valid_codes])[:limit]


def format_invalid_country_codes(invalid_codes: list[InvalidCountryCode]) -> str:
    """Format an invalid-codes list into a human-readable error string."""
    parts = []
    for invalid in invalid_codes:
        if invalid.suggestions:
            suggestions = ", ".join(invalid.suggestions)
            parts.append(f"{invalid.code} (did you mean {suggestions}?)")
        else:
            parts.append(f"{invalid.code} (no close match found)")
    return "Invalid country code(s): " + "; ".join(parts)


def _largest_csv_name(archive: zipfile.ZipFile) -> str:
    csv_names = [name for name in archive.namelist() if name.lower().endswith(".csv")]
    if not csv_names:
        raise ValueError("No CSV file found in the downloaded BIS archive.")
    return max(csv_names, key=lambda name: archive.getinfo(name).file_size)


def _first_csv_row(raw_file: IO[bytes]) -> dict[str, str]:
    text_file = (line.decode("utf-8-sig") for line in raw_file)
    reader = csv.DictReader(text_file)
    try:
        return next(reader)
    except StopIteration as error:
        raise ValueError("Downloaded BIS CSV is empty.") from error


def _structure_id_from_urn(urn: str) -> str:
    match = re.search(r"DataStructure=[^:]+:([^(]+)\(", urn)
    if not match:
        raise ValueError(f"Cannot parse SDMX data-structure URN: {urn!r}.")
    return match.group(1)


def _codelist_reference_from_urn(urn: str) -> SdmxCodelistReference:
    match = re.search(r"Codelist=([^:]+):([^(]+)\(([^)]+)\)", urn)
    if not match:
        raise ValueError(f"Cannot parse SDMX codelist URN: {urn!r}.")
    agency, codelist_id, version = match.groups()
    return SdmxCodelistReference(agency, codelist_id, version)


def _structure_query_url(
    artefact_type: str,
    agency: str,
    resource_id: str,
    version: str,
) -> str:
    return f"{BIS_SDMX_API_ENDPOINT}/structure/{artefact_type}/{agency}/{resource_id}/{version}"


def _dedupe(items: Iterable[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out
