from __future__ import annotations

import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter

from JumpingSpider.models import CrawlConfig, CrawlSummary, LinkReference, LinkResult

DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".pptx",
    ".ppt",
    ".xlsx",
    ".xls",
    ".docx",
    ".doc",
    ".csv",
    ".txt",
    ".rtf",
    ".zip",
    ".tar",
    ".gz",
    ".tgz",
    ".rar",
    ".7z",
}

ASSET_EXTENSIONS = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".svg",
    ".webp",
    ".ico",
    ".bmp",
    ".avif",
    ".mp4",
    ".mov",
    ".avi",
    ".webm",
    ".mkv",
    ".mp3",
    ".wav",
    ".ogg",
    ".m4a",
    ".css",
    ".js",
    ".mjs",
    ".map",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".otf",
    ".json",
    ".xml",
}

ASSET_TAGS: tuple[tuple[str, str], ...] = (
    ("img", "src"),
    ("script", "src"),
    ("link", "href"),
    ("video", "src"),
    ("audio", "src"),
    ("source", "src"),
    ("iframe", "src"),
    ("embed", "src"),
)


def classify_resource_type(url: str, tag: str = "a") -> str:
    """Classify a URL into 'page', 'document', or 'asset' based on extension and HTML tag."""
    parsed = urlparse(url)
    _, ext = os.path.splitext(parsed.path.lower())
    if ext in DOCUMENT_EXTENSIONS:
        return "document"
    if ext in ASSET_EXTENSIONS:
        return "asset"
    if tag in {"img", "script", "link", "video", "audio", "source", "embed"}:
        return "asset"
    return "page"


def refine_resource_type_from_content_type(current_type: str, content_type: str) -> str:
    """Refine resource classification once HTTP Content-Type header is known."""
    ct = content_type.lower()
    if not ct:
        return current_type
    if "text/html" in ct or "application/xhtml+xml" in ct:
        return "page" if current_type == "page" else current_type
    if any(doc_ct in ct for doc_ct in ("application/pdf", "msword", "officedocument", "powerpoint", "excel", "zip")):
        return "document"
    if any(asset_ct in ct for asset_ct in ("image/", "video/", "audio/", "text/css", "javascript", "font/")):
        return "asset"
    return current_type


class SpiderCrawler:
    """Concurrent web crawler and link/asset validator."""

    def __init__(
        self,
        config: CrawlConfig,
        on_url_started: Callable[[str, int, int], None] | None = None,
        on_url_completed: Callable[[LinkResult, int, int], None] | None = None,
        on_log: Callable[[str], None] | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.config = config
        self.on_url_started = on_url_started
        self.on_url_completed = on_url_completed
        self.on_log = on_log
        self.stop_event = threading.Event()

        self._lock = threading.RLock()
        self._rate_lock = threading.Lock()
        self._next_allowed_time = 0.0

        self._registry: dict[str, LinkResult] = {}
        self._discovered_order: list[str] = []
        self._completed_count = 0

        if session is not None:
            self.session = session
            self._owns_session = False
        else:
            self.session = requests.Session()
            pool_size = max(10, config.workers * 2)
            adapter = HTTPAdapter(pool_connections=pool_size, pool_maxsize=pool_size)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)
            self.session.headers.update({"User-Agent": config.user_agent})
            self._owns_session = True

    def stop(self) -> None:
        """Signal the crawler to stop queuing and processing remaining URLs."""
        self.stop_event.set()

    def _log(self, message: str) -> None:
        if self.on_log is not None:
            self.on_log(message)

    def _wait_for_rate_limit(self) -> None:
        delay = self.config.delay
        if delay <= 0:
            return
        with self._rate_lock:
            now = time.monotonic()
            if now < self._next_allowed_time:
                sleep_duration = self._next_allowed_time - now
                self._next_allowed_time += delay
            else:
                sleep_duration = delay
                self._next_allowed_time = now + delay
        if sleep_duration > 0 and not self.stop_event.is_set():
            time.sleep(sleep_duration)

    def _is_internal(self, url: str) -> bool:
        return url == self.config.start_url or url.startswith(self.config.base_prefix)

    def _should_parse_html(self, result: LinkResult) -> bool:
        if result.scope != "internal":
            return False
        if result.resource_type != "page":
            return False
        return not (self.config.max_depth is not None and result.depth > self.config.max_depth)

    def _register_url(
        self,
        url: str,
        depth: int,
        reference: LinkReference | None = None,
        tag: str = "a",
    ) -> bool:
        """
        Registers a URL in the thread-safe registry.
        Returns True if the URL is newly discovered and should be fetched, False if already seen.
        """
        scope = "internal" if self._is_internal(url) else "external"
        resource_type = classify_resource_type(url, tag=tag)

        with self._lock:
            existing = self._registry.get(url)
            if existing is not None:
                if reference is not None:
                    existing.add_reference(reference)
                return False

            result = LinkResult(
                link=url,
                success=0,
                status_code=0,
                scope=scope,
                resource_type=resource_type,
                depth=depth,
                references=[reference] if reference is not None else [],
            )
            self._registry[url] = result
            self._discovered_order.append(url)
            return True

    def _extract_references_from_html(self, source_url: str, html_text: str) -> list[tuple[str, LinkReference]]:
        """Extracts candidate (normalized_url, LinkReference) pairs from an HTML document."""
        soup = BeautifulSoup(html_text, "html.parser")
        discovered: list[tuple[str, LinkReference]] = []

        # 1. Extract <a href="..."> links
        for a_tag in soup.find_all("a", href=True):
            raw_href = str(a_tag["href"]).strip()
            if not raw_href or raw_href.startswith(("javascript:", "mailto:", "tel:", "#")):
                continue
            full_url = urljoin(source_url, raw_href).split("#")[0]
            if urlparse(full_url).scheme not in ("http", "https"):
                continue
            text = (
                a_tag.get_text(" ", strip=True)
                or str(a_tag.get("title", "")).strip()
                or str(a_tag.get("aria-label", "")).strip()
            )
            discovered.append(
                (
                    full_url,
                    LinkReference(
                        source_url=source_url,
                        tag="a",
                        attribute="href",
                        text=text[:200],
                    ),
                )
            )

        # 2. Extract asset tags if enabled
        if self.config.check_assets:
            for tag_name, attr_name in ASSET_TAGS:
                for tag_el in soup.find_all(tag_name):
                    raw_val = tag_el.get(attr_name)
                    if not raw_val:
                        continue
                    raw_val_str = str(raw_val).strip()
                    if not raw_val_str or raw_val_str.startswith(("data:", "javascript:", "blob:", "#")):
                        continue

                    # Skip <link> tags that are purely DNS prefetch / preconnect hints without real assets
                    if tag_name == "link":
                        rel_val = tag_el.get("rel")
                        rels = [r.lower() for r in rel_val] if isinstance(rel_val, list) else [str(rel_val or "").lower()]
                        if any(r in {"dns-prefetch", "preconnect"} for r in rels):
                            continue

                    full_url = urljoin(source_url, raw_val_str).split("#")[0]
                    if urlparse(full_url).scheme not in ("http", "https"):
                        continue

                    label = (
                        str(tag_el.get("alt", "")).strip()
                        or str(tag_el.get("title", "")).strip()
                        or (
                            " ".join(tag_el.get("rel", []))
                            if isinstance(tag_el.get("rel"), list)
                            else str(tag_el.get("rel", "")).strip()
                        )
                    )
                    discovered.append(
                        (
                            full_url,
                            LinkReference(
                                source_url=source_url,
                                tag=tag_name,
                                attribute=attr_name,
                                text=label[:200],
                            ),
                        )
                    )

        return discovered

    def _fetch_and_process(self, url: str) -> list[str]:
        """Fetches a single URL, updates its LinkResult, and returns newly queued URLs."""
        if self.stop_event.is_set():
            return []

        with self._lock:
            result = self._registry[url]
            total_queued = len(self._discovered_order)
            completed_so_far = self._completed_count

        if self.on_url_started is not None:
            self.on_url_started(url, completed_so_far, total_queued)
        self._log(f"Checking: {url}")

        self._wait_for_rate_limit()
        if self.stop_event.is_set():
            return []

        need_html = self._should_parse_html(result)
        start_time = time.perf_counter()
        new_urls_to_crawl: list[str] = []

        try:
            response: requests.Response
            if need_html:
                result.method_used = "GET"
                response = self.session.get(url, timeout=self.config.timeout, stream=True)
            else:
                result.method_used = "HEAD"
                response = self.session.head(url, timeout=self.config.timeout, allow_redirects=True)
                if response.status_code in (403, 405, 501):
                    response.close()
                    result.method_used = "GET"
                    response = self.session.get(url, timeout=self.config.timeout, stream=True, allow_redirects=True)

            try:
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                status_code = response.status_code
                is_success = 1 if 200 <= status_code < 400 else 0
                content_type = response.headers.get("Content-Type", "")

                redirect_chain = [resp.url for resp in response.history]
                final_url = response.url or url
                is_redirect = len(redirect_chain) > 0

                with self._lock:
                    result.status_code = status_code
                    result.success = is_success
                    result.final_url = final_url
                    result.is_redirect = is_redirect
                    result.redirect_chain = redirect_chain
                    result.content_type = content_type
                    result.response_time_ms = elapsed_ms
                    result.resource_type = refine_resource_type_from_content_type(
                        result.resource_type, content_type
                    )
                    if not is_success:
                        result.error_type = "HTTPError"
                        result.error_message = f"HTTP {status_code}"

                # If redirected to a different internal URL, queue the final URL rather than
                # attributing the destination page's links to the redirecting URL.
                if is_redirect and final_url != url:
                    if self._is_internal(final_url) or self.config.check_external:
                        ref = LinkReference(
                            source_url=url,
                            tag="redirect",
                            attribute="Location",
                            text=f"Redirect from {url}",
                        )
                        if self._register_url(final_url, depth=result.depth, reference=ref, tag="a"):
                            new_urls_to_crawl.append(final_url)
                elif (
                    need_html
                    and is_success == 1
                    and "text/html" in content_type.lower()
                    and not self.stop_event.is_set()
                ):
                    html_text = response.text
                    extracted = self._extract_references_from_html(final_url, html_text)
                    next_depth = result.depth + 1
                    for target_url, ref in extracted:
                        is_internal = self._is_internal(target_url)
                        if not is_internal and not self.config.check_external:
                            continue
                        if self._register_url(target_url, depth=next_depth, reference=ref, tag=ref.tag):
                            new_urls_to_crawl.append(target_url)
            finally:
                response.close()

        except requests.exceptions.Timeout as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            with self._lock:
                result.success = 0
                result.status_code = 0
                result.response_time_ms = elapsed_ms
                result.error_type = "Timeout"
                result.error_message = str(exc)
            self._log(f"Timeout connecting to {url}: {exc}")

        except requests.exceptions.SSLError as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            with self._lock:
                result.success = 0
                result.status_code = 0
                result.response_time_ms = elapsed_ms
                result.error_type = "SSLError"
                result.error_message = str(exc)
            self._log(f"SSL error on {url}: {exc}")

        except requests.exceptions.ConnectionError as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            with self._lock:
                result.success = 0
                result.status_code = 0
                result.response_time_ms = elapsed_ms
                result.error_type = "ConnectionError"
                result.error_message = str(exc)
            self._log(f"Failed to connect to {url}: {exc}")

        except requests.exceptions.RequestException as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            with self._lock:
                result.success = 0
                result.status_code = 0
                result.response_time_ms = elapsed_ms
                result.error_type = "RequestException"
                result.error_message = str(exc)
            self._log(f"Request failed for {url}: {exc}")

        with self._lock:
            self._completed_count += 1
            completed_now = self._completed_count
            total_now = len(self._discovered_order)

        if self.on_url_completed is not None:
            self.on_url_completed(result, completed_now, total_now)

        return new_urls_to_crawl

    def run(self) -> CrawlSummary:
        """Executes the crawl until all discovered URLs are checked or stop() is called."""
        self.stop_event.clear()
        started_at = time.perf_counter()

        self._register_url(self.config.start_url, depth=0, reference=None, tag="a")

        workers = max(1, self.config.workers)
        try:
            with ThreadPoolExecutor(max_workers=workers) as executor:
                pending: set[Future[list[str]]] = {
                    executor.submit(self._fetch_and_process, self.config.start_url)
                }

                while pending and not self.stop_event.is_set():
                    done, pending = wait(pending, timeout=0.1, return_when=FIRST_COMPLETED)
                    for fut in done:
                        new_urls = fut.result()
                        if self.stop_event.is_set():
                            break
                        for next_url in new_urls:
                            pending.add(executor.submit(self._fetch_and_process, next_url))
        finally:
            if self._owns_session:
                self.session.close()

        duration = time.perf_counter() - started_at
        with self._lock:
            ordered_results = [self._registry[u] for u in self._discovered_order]

        return CrawlSummary(
            start_url=self.config.start_url,
            base_prefix=self.config.base_prefix,
            results=ordered_results,
            duration_seconds=duration,
        )
