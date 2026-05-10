"""Unit tests for `BisBulkFetcher` discovery and caching behaviour."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bis_prates.fetch import BisBulkFetcher, DiscoveredDataset, RemoteMetadata, _FetchCache

DATASET = DiscoveredDataset(
    label="Central bank policy rates (CSV, flat)",
    url="https://data.bis.org/static/bulk/WS_CBPOL_csv_flat.zip",
    release_date="7 May 2026",
)


class FetchDiscoveryTest(unittest.TestCase):
    """Discovery of the policy-rates link on the bulk-downloads page."""

    def test_discovers_policy_rates_csv_flat_link(self) -> None:
        """Anchor with matching label is parsed into a `DiscoveredDataset`."""

        class FakeFetcher(BisBulkFetcher):
            def _http_get_text(self, url: str) -> str:
                return """
                <html>
                  <body>
                    <a href="/static/bulk/OTHER.zip">Other data (CSV, flat) 1 May 2026</a>
                    <a href="/static/bulk/WS_CBPOL_csv_flat.zip">
                      <article>
                        <header>
                          <h4>Central bank policy rates (CSV, flat)</h4>
                        </header>
                        <div><span><time>7 May 2026</time></span></div>
                      </article>
                    </a>
                  </body>
                </html>
                """

        dataset = FakeFetcher().discover_dataset()

        self.assertEqual(dataset.label, DATASET.label)
        self.assertEqual(dataset.url, DATASET.url)
        self.assertEqual(dataset.release_date, DATASET.release_date)


class FetchCacheTest(unittest.TestCase):
    """Conditional re-download logic driven by ETag/Last-Modified/Content-Length."""

    def test_uses_cache_when_remote_metadata_is_unchanged(self) -> None:
        """No download happens when remote validators match the manifest."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            archive_path = cache_dir / "WS_CBPOL_csv_flat.zip"
            archive_path.write_bytes(b"cached")
            (cache_dir / "fetch_manifest.json").write_text(
                json.dumps(
                    {
                        "url": DATASET.url,
                        "release_date": DATASET.release_date,
                        "etag": '"unchanged"',
                        "content_length": 6,
                    }
                ),
                encoding="utf-8",
            )

            class FakeFetcher(BisBulkFetcher):
                download_called = False

                def discover_dataset(self) -> DiscoveredDataset:
                    return DATASET

                def get_remote_metadata(self, url: str) -> RemoteMetadata:
                    return RemoteMetadata(etag='"unchanged"', last_modified=None, content_length=6)

                def _download_archive(
                    self, url: str, archive_path: Path
                ) -> tuple[RemoteMetadata, str, int]:
                    self.download_called = True
                    raise AssertionError("cache hit should not download")

            fetcher = FakeFetcher(cache_dir=cache_dir)
            result = fetcher.fetch()

            self.assertFalse(result.downloaded)
            self.assertFalse(fetcher.download_called)
            self.assertEqual(result.archive_path, archive_path)

    def test_uses_cache_when_validator_changes_but_release_and_size_match(self) -> None:
        """A new ETag alone is not enough to trigger re-download if size and release-date agree."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            archive_path = cache_dir / "WS_CBPOL_csv_flat.zip"
            archive_path.write_bytes(b"old")
            (cache_dir / "fetch_manifest.json").write_text(
                json.dumps(
                    {
                        "url": DATASET.url,
                        "release_date": DATASET.release_date,
                        "etag": '"old"',
                        "content_length": 3,
                    }
                ),
                encoding="utf-8",
            )

            class FakeFetcher(BisBulkFetcher):
                download_called = False

                def discover_dataset(self) -> DiscoveredDataset:
                    return DATASET

                def get_remote_metadata(self, url: str) -> RemoteMetadata:
                    return RemoteMetadata(etag='"new"', last_modified=None, content_length=3)

                def _download_archive(
                    self, url: str, archive_path: Path
                ) -> tuple[RemoteMetadata, str, int]:
                    self.download_called = True
                    archive_path.write_bytes(b"new")
                    return (
                        RemoteMetadata(etag='"new"', last_modified=None, content_length=3),
                        "11507a0e2f5e69d5c840b1bc4d5fc4c4",
                        3,
                    )

            fetcher = FakeFetcher(cache_dir=cache_dir)
            result = fetcher.fetch()

            self.assertFalse(result.downloaded)
            self.assertFalse(fetcher.download_called)
            self.assertEqual(archive_path.read_bytes(), b"old")

    def test_downloads_when_remote_size_changes(self) -> None:
        """A different `Content-Length` invalidates the cache and triggers a fresh download."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            archive_path = cache_dir / "WS_CBPOL_csv_flat.zip"
            archive_path.write_bytes(b"old")
            (cache_dir / "fetch_manifest.json").write_text(
                json.dumps(
                    {
                        "url": DATASET.url,
                        "release_date": DATASET.release_date,
                        "etag": '"old"',
                        "content_length": 3,
                    }
                ),
                encoding="utf-8",
            )

            class FakeFetcher(BisBulkFetcher):
                download_called = False

                def discover_dataset(self) -> DiscoveredDataset:
                    return DATASET

                def get_remote_metadata(self, url: str) -> RemoteMetadata:
                    return RemoteMetadata(etag='"new"', last_modified=None, content_length=4)

                def _download_archive(
                    self, url: str, archive_path: Path
                ) -> tuple[RemoteMetadata, str, int]:
                    self.download_called = True
                    archive_path.write_bytes(b"new!")
                    return (
                        RemoteMetadata(etag='"new"', last_modified=None, content_length=4),
                        "3910cfcd488d171590c90b71e486d224",
                        4,
                    )

            fetcher = FakeFetcher(cache_dir=cache_dir)
            result = fetcher.fetch()
            manifest = json.loads((cache_dir / "fetch_manifest.json").read_text())

            self.assertTrue(result.downloaded)
            self.assertTrue(fetcher.download_called)
            self.assertEqual(archive_path.read_bytes(), b"new!")
            self.assertEqual(manifest["content_length"], 4)


class FetchCacheUnitTest(unittest.TestCase):
    """Direct unit tests for the `_FetchCache` cache-management class."""

    def test_archive_path_for_derives_from_dataset_url(self) -> None:
        """`archive_path_for` joins the cache dir with the filename in the URL."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache = _FetchCache(Path(tmp_dir))

            self.assertEqual(
                cache.archive_path_for(DATASET),
                Path(tmp_dir) / "WS_CBPOL_csv_flat.zip",
            )

    def test_load_manifest_returns_empty_dict_when_missing(self) -> None:
        """A missing manifest file yields `{}` rather than raising."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache = _FetchCache(Path(tmp_dir))

            self.assertEqual(cache.load_manifest(), {})

    def test_is_current_returns_false_without_archive_on_disk(self) -> None:
        """No archive on disk → cache cannot be reused."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache = _FetchCache(Path(tmp_dir))
            metadata = RemoteMetadata(etag='"x"', last_modified=None, content_length=6)

            self.assertFalse(cache.is_current(cache.archive_path_for(DATASET), DATASET, metadata))

    def test_is_current_true_when_release_date_matches(self) -> None:
        """A matching `release_date` is itself sufficient signal for cache reuse."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            archive_path = cache_dir / "WS_CBPOL_csv_flat.zip"
            archive_path.write_bytes(b"cached")
            (cache_dir / "fetch_manifest.json").write_text(
                json.dumps(
                    {
                        "url": DATASET.url,
                        "release_date": DATASET.release_date,
                        "etag": '"old"',
                        "content_length": 6,
                    }
                ),
                encoding="utf-8",
            )
            cache = _FetchCache(cache_dir)
            metadata = RemoteMetadata(etag='"new"', last_modified=None, content_length=6)

            self.assertTrue(cache.is_current(archive_path, DATASET, metadata))

    def test_is_current_false_when_url_changes(self) -> None:
        """A different URL invalidates the cache regardless of validators."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            archive_path = cache_dir / "WS_CBPOL_csv_flat.zip"
            archive_path.write_bytes(b"cached")
            (cache_dir / "fetch_manifest.json").write_text(
                json.dumps(
                    {
                        "url": "https://data.bis.org/static/bulk/OLD.zip",
                        "release_date": DATASET.release_date,
                        "etag": '"matching"',
                        "content_length": 6,
                    }
                ),
                encoding="utf-8",
            )
            cache = _FetchCache(cache_dir)
            metadata = RemoteMetadata(etag='"matching"', last_modified=None, content_length=6)

            self.assertFalse(cache.is_current(archive_path, DATASET, metadata))

    def test_write_manifest_contains_required_provenance_fields(self) -> None:
        """The written manifest carries dataset, validators, and integrity hash."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            cache_dir = Path(tmp_dir)
            archive_path = cache_dir / "WS_CBPOL_csv_flat.zip"
            cache = _FetchCache(cache_dir)
            metadata = RemoteMetadata(
                etag='"abc"',
                last_modified="Wed, 07 May 2026 12:00:00 GMT",
                content_length=42,
            )

            cache.write_manifest(
                archive_path=archive_path,
                dataset=DATASET,
                metadata=metadata,
                sha256_hash="deadbeef",
                size_bytes=42,
                source_page="https://data.bis.org/bulkdownload",
            )
            manifest = json.loads((cache_dir / "fetch_manifest.json").read_text("utf-8"))

            self.assertEqual(manifest["url"], DATASET.url)
            self.assertEqual(manifest["release_date"], DATASET.release_date)
            self.assertEqual(manifest["etag"], '"abc"')
            self.assertEqual(manifest["sha256"], "deadbeef")
            self.assertEqual(manifest["size_bytes"], 42)
            self.assertEqual(manifest["source_page"], "https://data.bis.org/bulkdownload")


if __name__ == "__main__":
    unittest.main()
