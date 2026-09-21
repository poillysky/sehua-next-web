"""scrape_worker_proxy unit checks (no network)."""

from __future__ import annotations

import os
import unittest

from app.core import scrape_worker_proxy as swp


class ScrapeWorkerProxyTests(unittest.TestCase):
    def tearDown(self) -> None:
        for key in ("APP_ROLE", "SCRAPE_WORKER_URL"):
            os.environ.pop(key, None)

    def test_local_dev_no_proxy(self) -> None:
        os.environ.pop("APP_ROLE", None)
        os.environ.pop("SCRAPE_WORKER_URL", None)
        self.assertFalse(swp.should_proxy("POST", "/scrap-library/embed/enrich"))

    def test_ui_with_worker_proxies_heavy(self) -> None:
        os.environ["APP_ROLE"] = "ui"
        os.environ["SCRAPE_WORKER_URL"] = "http://scrape-worker:8020"
        self.assertTrue(swp.should_proxy("POST", "/scrap-library/embed/enrich"))
        self.assertTrue(
            swp.should_proxy("GET", "/scrap-library/embed/enrich/status/stream")
        )
        self.assertFalse(swp.should_proxy("GET", "/scrap-library/embed/enrich/strategy"))
        self.assertFalse(swp.should_proxy("PUT", "/scrap-library/embed/enrich/strategy"))

    def test_worker_role_never_proxies(self) -> None:
        os.environ["APP_ROLE"] = "worker"
        os.environ["SCRAPE_WORKER_URL"] = "http://scrape-worker:8020"
        self.assertFalse(swp.should_proxy("POST", "/scrap-library/embed/enrich"))

    def test_url_strip(self) -> None:
        os.environ["SCRAPE_WORKER_URL"] = "http://scrape-worker:8020/"
        self.assertEqual(swp.scrape_worker_url(), "http://scrape-worker:8020")


if __name__ == "__main__":
    unittest.main()
