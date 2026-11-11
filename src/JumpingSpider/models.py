from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class LinkReference:
    """Represents a single occurrence where a URL was referenced on a crawled page."""

    source_url: str
    tag: str = "a"
    attribute: str = "href"
    text: str = ""

    def to_dict(self) -> dict[str, str]:
        return {
            "source_url": self.source_url,
            "tag": self.tag,
            "attribute": self.attribute,
            "text": self.text,
        }


@dataclass
class LinkResult:
    """Stores the validation result and metadata for a single discovered URL."""

    link: str
    success: int
    status_code: int
    final_url: str = ""
    is_redirect: bool = False
    redirect_chain: list[str] = field(default_factory=list)
    error_type: str | None = None
    error_message: str | None = None
    content_type: str = ""
    scope: str = "internal"       # "internal" | "external"
    resource_type: str = "page"   # "page" | "document" | "asset"
    method_used: str = "GET"      # "GET" | "HEAD"
    response_time_ms: float = 0.0
    depth: int = 0
    references: list[LinkReference] = field(default_factory=list)

    @property
    def found_on(self) -> list[str]:
        """Unique ordered list of source URLs where this link was found."""
        seen: set[str] = set()
        pages: list[str] = []
        for ref in self.references:
            if ref.source_url and ref.source_url not in seen:
                seen.add(ref.source_url)
                pages.append(ref.source_url)
        return pages

    @property
    def link_texts(self) -> list[str]:
        """Unique ordered list of non-empty anchor/alt texts associated with this link."""
        seen: set[str] = set()
        texts: list[str] = []
        for ref in self.references:
            cleaned = ref.text.strip()
            if cleaned and cleaned not in seen:
                seen.add(cleaned)
                texts.append(cleaned)
        return texts

    def add_reference(self, ref: LinkReference) -> None:
        """Adds a reference if an identical one is not already recorded."""
        for existing in self.references:
            if (
                existing.source_url == ref.source_url
                and existing.tag == ref.tag
                and existing.attribute == ref.attribute
                and existing.text == ref.text
            ):
                return
        self.references.append(ref)

    def to_dict(self) -> dict[str, Any]:
        return {
            "link": self.link,
            "success": self.success,
            "status_code": self.status_code,
            "final_url": self.final_url or self.link,
            "is_redirect": self.is_redirect,
            "redirect_chain": list(self.redirect_chain),
            "error_type": self.error_type,
            "error_message": self.error_message,
            "content_type": self.content_type,
            "scope": self.scope,
            "resource_type": self.resource_type,
            "method_used": self.method_used,
            "response_time_ms": round(self.response_time_ms, 2),
            "depth": self.depth,
            "found_on": self.found_on,
            "link_texts": self.link_texts,
            "references": [r.to_dict() for r in self.references],
        }


@dataclass
class CrawlConfig:
    """Configuration options for a SpiderCrawler run."""

    start_url: str
    output_files: list[str] = field(default_factory=lambda: ["crawl_results.json"])
    delay: float = 0.2
    workers: int = 5
    timeout: float = 10.0
    max_depth: int | None = None
    check_external: bool = True
    check_assets: bool = True
    broken_only: bool = False
    user_agent: str = "JumpingSpider/0.2.0 (+https://github.com/rogerallen/JumpingSpider)"

    @property
    def base_prefix(self) -> str:
        """Strict directory prefix boundary for crawling internal pages."""
        url = self.start_url
        if url.endswith("/"):
            return url
        # If the last path segment looks like a file (e.g. /tempo/index.html), use its directory
        from urllib.parse import urlparse

        parsed = urlparse(url)
        path = parsed.path
        last_segment = path.rsplit("/", 1)[-1] if "/" in path else path
        if "." in last_segment:
            parent_path = path.rsplit("/", 1)[0] + "/"
            return f"{parsed.scheme}://{parsed.netloc}{parent_path}"
        return url + "/"


@dataclass
class CrawlSummary:
    """Aggregated results and metrics from a crawl session."""

    start_url: str
    base_prefix: str
    results: list[LinkResult] = field(default_factory=list)
    duration_seconds: float = 0.0

    @property
    def total_checked(self) -> int:
        return len(self.results)

    @property
    def valid_count(self) -> int:
        return sum(1 for r in self.results if r.success == 1)

    @property
    def broken_count(self) -> int:
        return sum(1 for r in self.results if r.success == 0)

    @property
    def redirect_count(self) -> int:
        return sum(1 for r in self.results if r.is_redirect)

    @property
    def external_count(self) -> int:
        return sum(1 for r in self.results if r.scope == "external")

    @property
    def asset_count(self) -> int:
        return sum(1 for r in self.results if r.resource_type == "asset")

    @property
    def document_count(self) -> int:
        return sum(1 for r in self.results if r.resource_type == "document")

    @property
    def broken_results(self) -> list[LinkResult]:
        return [r for r in self.results if r.success == 0]

    @property
    def redirect_results(self) -> list[LinkResult]:
        return [r for r in self.results if r.is_redirect]
