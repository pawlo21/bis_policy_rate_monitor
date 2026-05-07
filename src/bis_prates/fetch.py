"""Download and cache BIS policy-rate bulk data."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen


BULK_DOWNLOAD_URL = "https://data.bis.org/bulkdownload"
DATASET_LABEL = "Central bank policy rates (CSV, flat)"
DEFAULT_CACHE_DIR = Path("data/raw")
MANIFEST_FILENAME = "fetch_manifest.json"
USER_AGENT = "bis-policy-rate-monitor/0.1"


@dataclass(frozen=True)
class DiscoveredDataset:
    label: str
    url: str
    release_date: Optional[str]


@dataclass(frozen=True)
class RemoteMetadata:
    etag: Optional[str]
    last_modified: Optional[str]
    content_length: Optional[int]

    @classmethod
    def from_headers(cls, headers: object) -> "RemoteMetadata":
        content_length = _parse_int(_header_value(headers, "Content-Length"))
        return cls(
            etag=_header_value(headers, "ETag"),
            last_modified=_header_value(headers, "Last-Modified"),
            content_length=content_length,
        )


@dataclass(frozen=True)
class FetchResult:
    downloaded: bool
    archive_path: Path
    manifest_path: Path
    dataset: DiscoveredDataset
    metadata: RemoteMetadata


class BisBulkFetcher:
    """Fetch and cache the BIS central bank policy rates CSV flat ZIP."""

    def __init__(
        self,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        bulk_download_url: str = BULK_DOWNLOAD_URL,
        dataset_label: str = DATASET_LABEL,
        timeout_seconds: int = 30,
    ) -> None:
        self.cache_dir = Path(cache_dir)
        self.bulk_download_url = bulk_download_url
        self.dataset_label = dataset_label
        self.timeout_seconds = timeout_seconds
        self.manifest_path = self.cache_dir / MANIFEST_FILENAME

    def fetch(self) -> FetchResult:
        dataset = self.discover_dataset()
        metadata = self.get_remote_metadata(dataset.url)
        archive_path = self.cache_dir / _filename_from_url(dataset.url)
        manifest = self._load_manifest()

        if self._is_cached_current(archive_path, manifest, dataset, metadata):
            return FetchResult(
                downloaded=False,
                archive_path=archive_path,
                manifest_path=self.manifest_path,
                dataset=dataset,
                metadata=metadata,
            )

        download_metadata, sha256_hash, size_bytes = self._download_archive(
            dataset.url, archive_path
        )
        final_metadata = _prefer_download_metadata(download_metadata, metadata)
        self._write_manifest(
            archive_path=archive_path,
            dataset=dataset,
            metadata=final_metadata,
            sha256_hash=sha256_hash,
            size_bytes=size_bytes,
        )

        return FetchResult(
            downloaded=True,
            archive_path=archive_path,
            manifest_path=self.manifest_path,
            dataset=dataset,
            metadata=final_metadata,
        )

    def discover_dataset(self) -> DiscoveredDataset:
        html = self._http_get_text(self.bulk_download_url)
        parser = _BulkDownloadParser(self.bulk_download_url)
        parser.feed(html)

        for anchor in parser.anchors:
            text = _normalize_space(anchor["text"])
            if text == self.dataset_label or text.startswith(f"{self.dataset_label} "):
                release_date = text.removeprefix(self.dataset_label).strip() or None
                return DiscoveredDataset(
                    label=self.dataset_label,
                    url=anchor["href"],
                    release_date=release_date,
                )

        raise LookupError(
            f"Could not find dataset link on BIS bulk download page: {self.dataset_label}"
        )

    def get_remote_metadata(self, url: str) -> RemoteMetadata:
        request = Request(
            url,
            headers={"User-Agent": USER_AGENT},
            method="HEAD",
        )
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                return RemoteMetadata.from_headers(response.headers)
        except HTTPError as error:
            if error.code not in {403, 405}:
                raise RuntimeError(f"Could not inspect remote ZIP metadata: {url}") from error
        except URLError as error:
            raise RuntimeError(f"Could not inspect remote ZIP metadata: {url}") from error

        return RemoteMetadata(etag=None, last_modified=None, content_length=None)

    def _http_get_text(self, url: str) -> str:
        request = Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                charset = response.headers.get_content_charset() or "utf-8"
                return response.read().decode(charset)
        except URLError as error:
            raise RuntimeError(f"Could not read BIS bulk download page: {url}") from error

    def _download_archive(
        self, url: str, archive_path: Path
    ) -> tuple[RemoteMetadata, str, int]:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        temp_path = archive_path.with_suffix(f"{archive_path.suffix}.tmp")
        sha256 = hashlib.sha256()
        size_bytes = 0

        request = Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urlopen(request, timeout=self.timeout_seconds) as response:
                metadata = RemoteMetadata.from_headers(response.headers)
                with temp_path.open("wb") as output_file:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        output_file.write(chunk)
                        sha256.update(chunk)
                        size_bytes += len(chunk)
        except URLError as error:
            raise RuntimeError(f"Could not download BIS ZIP: {url}") from error

        os.replace(temp_path, archive_path)
        return metadata, sha256.hexdigest(), size_bytes

    def _load_manifest(self) -> Dict[str, object]:
        if not self.manifest_path.exists():
            return {}

        with self.manifest_path.open("r", encoding="utf-8") as manifest_file:
            return json.load(manifest_file)

    def _write_manifest(
        self,
        archive_path: Path,
        dataset: DiscoveredDataset,
        metadata: RemoteMetadata,
        sha256_hash: str,
        size_bytes: int,
    ) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "dataset": dataset.label,
            "source_page": self.bulk_download_url,
            "url": dataset.url,
            "release_date": dataset.release_date,
            "archive_path": str(archive_path),
            "downloaded_at_utc": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "etag": metadata.etag,
            "last_modified": metadata.last_modified,
            "content_length": metadata.content_length,
            "size_bytes": size_bytes,
            "sha256": sha256_hash,
        }

        with self.manifest_path.open("w", encoding="utf-8") as manifest_file:
            json.dump(manifest, manifest_file, indent=2, sort_keys=True)
            manifest_file.write("\n")

    def _is_cached_current(
        self,
        archive_path: Path,
        manifest: Dict[str, object],
        dataset: DiscoveredDataset,
        metadata: RemoteMetadata,
    ) -> bool:
        if not archive_path.exists() or not manifest:
            return False

        if manifest.get("url") != dataset.url:
            return False

        if dataset.release_date and manifest.get("release_date") != dataset.release_date:
            return False

        if metadata.content_length is not None and not _content_length_matches(
            manifest, metadata
        ):
            return False

        if dataset.release_date:
            return True

        if metadata.etag and manifest.get("etag"):
            return manifest.get("etag") == metadata.etag

        if metadata.last_modified and manifest.get("last_modified"):
            if manifest.get("last_modified") != metadata.last_modified:
                return False
            return _content_length_matches(manifest, metadata)

        return False


class _BulkDownloadParser(HTMLParser):
    def __init__(self, base_url: str) -> None:
        super().__init__()
        self.base_url = base_url
        self.anchors: List[Dict[str, str]] = []
        self._current_href: Optional[str] = None
        self._current_text: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        if tag != "a":
            return

        attrs_dict = dict(attrs)
        href = attrs_dict.get("href")
        if not href:
            return

        self._current_href = urljoin(self.base_url, href)
        self._current_text = []

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._current_href is None:
            return

        self.anchors.append(
            {
                "href": self._current_href,
                "text": _normalize_space(" ".join(self._current_text)),
            }
        )
        self._current_href = None
        self._current_text = []


def _filename_from_url(url: str) -> str:
    filename = Path(urlparse(url).path).name
    if not filename:
        raise ValueError(f"Could not derive filename from URL: {url}")
    return filename


def _content_length_matches(
    manifest: Dict[str, object], metadata: RemoteMetadata
) -> bool:
    if metadata.content_length is None:
        return True

    manifest_length = manifest.get("content_length") or manifest.get("size_bytes")
    return manifest_length == metadata.content_length


def _header_value(headers: object, name: str) -> Optional[str]:
    value = headers.get(name)  # type: ignore[attr-defined]
    return str(value) if value else None


def _normalize_space(value: str) -> str:
    return " ".join(value.split())


def _parse_int(value: Optional[str]) -> Optional[int]:
    if value is None:
        return None

    try:
        return int(value)
    except ValueError:
        return None


def _prefer_download_metadata(
    download_metadata: RemoteMetadata, head_metadata: RemoteMetadata
) -> RemoteMetadata:
    return RemoteMetadata(
        etag=download_metadata.etag or head_metadata.etag,
        last_modified=download_metadata.last_modified or head_metadata.last_modified,
        content_length=download_metadata.content_length or head_metadata.content_length,
    )
