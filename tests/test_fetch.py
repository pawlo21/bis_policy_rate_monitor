from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from bis_prates.fetch import BisBulkFetcher, DiscoveredDataset, RemoteMetadata


DATASET = DiscoveredDataset(
    label="Central bank policy rates (CSV, flat)",
    url="https://data.bis.org/static/bulk/WS_CBPOL_csv_flat.zip",
    release_date="7 May 2026",
)


class FetchDiscoveryTest(unittest.TestCase):
    def test_discovers_policy_rates_csv_flat_link(self) -> None:
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
    def test_uses_cache_when_remote_metadata_is_unchanged(self) -> None:
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
                    return RemoteMetadata(
                        etag='"unchanged"', last_modified=None, content_length=6
                    )

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
                        RemoteMetadata(
                            etag='"new"', last_modified=None, content_length=3
                        ),
                        "11507a0e2f5e69d5c840b1bc4d5fc4c4",
                        3,
                    )

            fetcher = FakeFetcher(cache_dir=cache_dir)
            result = fetcher.fetch()

            self.assertFalse(result.downloaded)
            self.assertFalse(fetcher.download_called)
            self.assertEqual(archive_path.read_bytes(), b"old")

    def test_downloads_when_remote_size_changes(self) -> None:
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
                        RemoteMetadata(
                            etag='"new"', last_modified=None, content_length=4
                        ),
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


if __name__ == "__main__":
    unittest.main()
