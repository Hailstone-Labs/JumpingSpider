from __future__ import annotations

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from unittest.mock import MagicMock

import pytest
import requests

from JumpingSpider.crawler import SpiderCrawler, classify_resource_type
from JumpingSpider.main import build_parser, crawl_site
from JumpingSpider.models import CrawlConfig, CrawlSummary, LinkReference, LinkResult
from JumpingSpider.reporters import export_csv, export_html, export_json, export_markdown, export_report
from JumpingSpider.tui import JumpingSpiderApp


class _TestSiteHandler(BaseHTTPRequestHandler):
    """Local test HTTP server simulating internal pages, broken links, assets, redirects, and HEAD/405."""

    request_counts: dict[tuple[str, str], int] = {}
    lock = threading.Lock()

    def log_message(self, format: str, *args: object) -> None:
        pass  # keep test output clean

    def _record(self, method: str) -> None:
        with self.lock:
            key = (method, self.path)
            self.request_counts[key] = self.request_counts.get(key, 0) + 1

    def do_HEAD(self) -> None:
        self._record("HEAD")
        if self.path == "/tempo/docs/no_head_allowed.pdf":
            self.send_response(405)
            self.end_headers()
            return
        if self.path == "/tempo/media/slide.pptx":
            self.send_response(200)
            self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.presentationml.presentation")
            self.end_headers()
            return
        if self.path == "/tempo/media/missing_video.mp4":
            self.send_response(404)
            self.end_headers()
            return
        if self.path == "/tempo/assets/logo.png":
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.end_headers()
            return
        if self.path == "/tempo/assets/broken.js":
            self.send_response(404)
            self.end_headers()
            return
        if self.path == "/other-dept/info.html":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            return
        self.send_response(200)
        self.end_headers()

    def do_GET(self) -> None:
        self._record("GET")
        if self.path in ("/tempo", "/tempo/"):
            html = """
            <html>
              <head>
                <link rel="stylesheet" href="/tempo/assets/missing.css">
                <script src="/tempo/assets/broken.js"></script>
              </head>
              <body>
                <a href="/tempo/about.html">About Tempo</a>
                <a href="/tempo/broken_page.html">Dead Link on Home</a>
                <a href="/tempo/old_link.html">Old Redirected Link</a>
                <a href="/tempo/media/slide.pptx">Presentation Deck</a>
                <a href="/tempo/docs/no_head_allowed.pdf">Special PDF</a>
                <a href="/other-dept/info.html">Sibling Dept Link</a>
                <img src="/tempo/assets/logo.png" alt="Tempo Logo">
              </body>
            </html>
            """
            self._send_html(200, html)
        elif self.path == "/tempo/about.html":
            html = """
            <html>
              <body>
                <a href="/tempo/broken_page.html">Dead Link on About Too</a>
                <a href="/tempo/media/missing_video.mp4">Missing Workshop Recording</a>
              </body>
            </html>
            """
            self._send_html(200, html)
        elif self.path == "/tempo/old_link.html":
            self.send_response(301)
            self.send_header("Location", "/tempo/about.html")
            self.end_headers()
        elif self.path == "/tempo/docs/no_head_allowed.pdf":
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.end_headers()
            self.wfile.write(b"%PDF-1.4 fake pdf bytes")
        elif self.path == "/other-dept/info.html":
            # Should NOT be parsed when crawling /tempo/
            html = '<html><body><a href="/other-dept/should_never_be_visited.html">Secret</a></body></html>'
            self._send_html(200, html)
        else:
            self.send_response(404)
            self.send_header("Content-Type", "text/html")
            self.end_headers()

    def _send_html(self, status: int, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture()
def test_server() -> str:
    _TestSiteHandler.request_counts.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _TestSiteHandler)
    port = server.server_port
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        server.server_close()


def test_crawler_end_to_end(test_server: str) -> None:
    start_url = f"{test_server}/tempo/"
    config = CrawlConfig(
        start_url=start_url,
        delay=0.0,
        workers=4,
        check_external=True,
        check_assets=True,
    )
    crawler = SpiderCrawler(config)
    summary = crawler.run()

    by_url = {r.link: r for r in summary.results}

    # 1. Start URL and internal about page succeeded
    assert by_url[start_url].success == 1
    assert by_url[f"{test_server}/tempo/about.html"].success == 1

    # 2. Broken page linked from TWO pages has both referrers and both link texts
    broken_page = by_url[f"{test_server}/tempo/broken_page.html"]
    assert broken_page.success == 0
    assert broken_page.status_code == 404
    assert set(broken_page.found_on) == {start_url, f"{test_server}/tempo/about.html"}
    assert set(broken_page.link_texts) == {"Dead Link on Home", "Dead Link on About Too"}

    # 3. Redirect chain captured properly
    redirected = by_url[f"{test_server}/tempo/old_link.html"]
    assert redirected.success == 1
    assert redirected.is_redirect is True
    assert redirected.final_url == f"{test_server}/tempo/about.html"
    assert len(redirected.redirect_chain) == 1

    # 4. Smart HEAD used for .pptx and .mp4 without GET
    slide_res = by_url[f"{test_server}/tempo/media/slide.pptx"]
    assert slide_res.success == 1
    assert slide_res.method_used == "HEAD"
    assert slide_res.resource_type == "document"
    assert _TestSiteHandler.request_counts.get(("GET", "/tempo/media/slide.pptx"), 0) == 0

    # 5. 405 Method Not Allowed on HEAD falls back to streaming GET
    pdf_res = by_url[f"{test_server}/tempo/docs/no_head_allowed.pdf"]
    assert pdf_res.success == 1
    assert pdf_res.method_used == "GET"
    assert _TestSiteHandler.request_counts.get(("HEAD", "/tempo/docs/no_head_allowed.pdf"), 0) == 1
    assert _TestSiteHandler.request_counts.get(("GET", "/tempo/docs/no_head_allowed.pdf"), 0) == 1

    # 6. External / sibling link is validated via HEAD, but NOT crawled for its child links
    sibling_res = by_url[f"{test_server}/other-dept/info.html"]
    assert sibling_res.success == 1
    assert sibling_res.scope == "external"
    assert sibling_res.method_used == "HEAD"
    assert f"{test_server}/other-dept/should_never_be_visited.html" not in by_url

    # 7. Assets (<img>, <script>, <link>) are checked and classified as 'asset'
    logo_res = by_url[f"{test_server}/tempo/assets/logo.png"]
    assert logo_res.success == 1
    assert logo_res.resource_type == "asset"
    assert logo_res.link_texts == ["Tempo Logo"]

    broken_js = by_url[f"{test_server}/tempo/assets/broken.js"]
    assert broken_js.success == 0
    assert broken_js.resource_type == "asset"


def test_network_exception_diagnostics() -> None:
    session = MagicMock(spec=requests.Session)
    session.get.side_effect = requests.exceptions.SSLError("certificate verify failed")

    config = CrawlConfig(start_url="https://expired-cert.test/app/", delay=0.0, workers=1)
    crawler = SpiderCrawler(config, session=session)
    summary = crawler.run()

    assert len(summary.results) == 1
    res = summary.results[0]
    assert res.success == 0
    assert res.status_code == 0
    assert res.error_type == "SSLError"
    assert "certificate verify failed" in (res.error_message or "")


def test_reporters_all_formats(tmp_path: Path) -> None:
    summary = CrawlSummary(
        start_url="https://example.com/tempo/",
        base_prefix="https://example.com/tempo/",
        duration_seconds=1.25,
        results=[
            LinkResult(
                link="https://example.com/tempo/",
                success=1,
                status_code=200,
                scope="internal",
                resource_type="page",
            ),
            LinkResult(
                link="https://example.com/tempo/missing.pdf",
                success=0,
                status_code=404,
                error_type="HTTPError",
                error_message="HTTP 404",
                scope="internal",
                resource_type="document",
                method_used="HEAD",
                references=[
                    LinkReference(
                        source_url="https://example.com/tempo/",
                        tag="a",
                        attribute="href",
                        text="Download Report",
                    )
                ],
            ),
        ],
    )

    json_path = export_report(summary, tmp_path / "out.json")
    csv_path = export_report(summary, tmp_path / "out.csv")
    md_path = export_report(summary, tmp_path / "out.md")
    html_path = export_report(summary, tmp_path / "out.html")

    # Verify JSON backwards compatibility + enriched fields
    json_data = json.loads(json_path.read_text(encoding="utf-8"))
    assert len(json_data) == 2
    assert json_data[1]["link"] == "https://example.com/tempo/missing.pdf"
    assert json_data[1]["success"] == 0
    assert json_data[1]["status_code"] == 404
    assert json_data[1]["found_on"] == ["https://example.com/tempo/"]
    assert json_data[1]["link_texts"] == ["Download Report"]

    # Verify CSV, Markdown, HTML contents
    csv_text = csv_path.read_text(encoding="utf-8")
    assert "Download Report" in csv_text
    assert "https://example.com/tempo/missing.pdf" in csv_text

    md_text = md_path.read_text(encoding="utf-8")
    assert "## Broken Links (1)" in md_text
    assert "Download Report" in md_text

    html_text = html_path.read_text(encoding="utf-8")
    assert "JumpingSpider Crawl Report" in html_text
    assert "Download Report" in html_text


def test_cli_legacy_and_flag_arguments(test_server: str, tmp_path: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(["https://example.com/a/", "legacy.json", "-o", "extra.csv", "--no-assets"])
    assert args.start_url == "https://example.com/a/"
    assert args.legacy_output == "legacy.json"
    assert args.outputs == ["extra.csv"]
    assert args.check_assets is False

    out_json = tmp_path / "cli_out.json"
    summary = crawl_site(f"{test_server}/tempo/", str(out_json), delay=0.0, quiet=True)
    assert out_json.exists()
    assert summary.total_checked >= 5


async def test_tui_app_mount_and_filters() -> None:
    config = CrawlConfig(start_url="https://weather.ndc.nasa.gov/tempo/")
    app = JumpingSpiderApp(initial_config=config)
    async with app.run_test() as pilot:
        # Simulate completed URLs arriving in the TUI
        ok_res = LinkResult(
            link="https://weather.ndc.nasa.gov/tempo/",
            success=1,
            status_code=200,
            scope="internal",
            resource_type="page",
        )
        broken_res = LinkResult(
            link="https://weather.ndc.nasa.gov/tempo/green_paper.html",
            success=0,
            status_code=404,
            error_type="HTTPError",
            error_message="HTTP 404",
            scope="internal",
            resource_type="page",
            references=[
                LinkReference(
                    source_url="https://weather.ndc.nasa.gov/tempo/",
                    tag="a",
                    attribute="href",
                    text="Green Paper",
                )
            ],
        )
        app._on_url_completed_ui(ok_res, 1, 2)
        app._on_url_completed_ui(broken_res, 2, 2)
        await pilot.pause()

        table = app.query_one("#results-table")
        assert table.row_count == 2

        # Filter to Broken only (key "2")
        await pilot.press("2")
        await pilot.pause()
        assert app.active_filter == "broken"
        assert table.row_count == 1

        # Filter back to All (key "1")
        await pilot.press("1")
        await pilot.pause()
        assert app.active_filter == "all"
        assert table.row_count == 2


def test_classify_resource_type() -> None:
    assert classify_resource_type("https://a.com/doc.pdf") == "document"
    assert classify_resource_type("https://a.com/deck.pptx") == "document"
    assert classify_resource_type("https://a.com/video.mp4") == "asset"
    assert classify_resource_type("https://a.com/page.html") == "page"
    assert classify_resource_type("https://a.com/dynamic", tag="img") == "asset"
