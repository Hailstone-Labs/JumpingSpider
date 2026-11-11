from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from rich.console import Console
from rich.table import Table

from JumpingSpider.crawler import SpiderCrawler
from JumpingSpider.models import CrawlConfig, CrawlSummary, LinkResult
from JumpingSpider.reporters import export_report


def crawl_site(
    start_url: str,
    output_filename: str | Sequence[str] = "crawl_results.json",
    delay: float = 0.2,
    workers: int = 5,
    timeout: float = 10.0,
    max_depth: int | None = None,
    check_external: bool = True,
    check_assets: bool = True,
    broken_only: bool = False,
    fmt: str | None = None,
    quiet: bool = False,
) -> CrawlSummary:
    """
    Crawls a website starting at `start_url`, strictly staying within its path boundary
    for recursion while optionally validating external links and page assets.
    """
    if isinstance(output_filename, str):
        output_files = [output_filename] if output_filename else []
    else:
        output_files = list(output_filename)

    config = CrawlConfig(
        start_url=start_url,
        output_files=output_files,
        delay=delay,
        workers=workers,
        timeout=timeout,
        max_depth=max_depth,
        check_external=check_external,
        check_assets=check_assets,
        broken_only=broken_only,
    )

    console = Console()
    if not quiet:
        console.print(
            f"[bold cyan]Starting crawl.[/bold cyan] Strictly locked to paths under: [underline]{config.base_prefix}[/underline]"
        )

    def on_completed(res: LinkResult, completed: int, total: int) -> None:
        if quiet:
            return
        status_str = str(res.status_code) if res.status_code else (res.error_type or "ERR")
        if res.success == 0:
            badge = f"[bold red]✗ {status_str}[/bold red]"
        elif res.is_redirect:
            badge = f"[bold yellow]↪ {status_str}[/bold yellow]"
        else:
            badge = f"[bold green]✓ {status_str}[/bold green]"
        console.print(f"[{completed}/{total}] {badge} {res.link} [dim]({res.scope}, {res.resource_type}, {res.method_used})[/dim]")

    crawler = SpiderCrawler(config=config, on_url_completed=on_completed)
    summary = crawler.run()

    saved_paths: list[Path] = []
    for out_file in output_files:
        saved = export_report(summary, out_file, fmt=fmt, broken_only=broken_only)
        saved_paths.append(saved)

    if not quiet:
        _print_terminal_summary(console, summary, saved_paths)

    return summary


def _print_terminal_summary(console: Console, summary: CrawlSummary, saved_paths: list[Path]) -> None:
    console.print()
    score_table = Table(title="Crawl Summary Scorecard", show_header=True, header_style="bold cyan")
    score_table.add_column("Total Checked", justify="right")
    score_table.add_column("Valid", justify="right", style="green")
    score_table.add_column("Broken", justify="right", style="red")
    score_table.add_column("Redirects", justify="right", style="yellow")
    score_table.add_column("External", justify="right")
    score_table.add_column("Docs & Assets", justify="right")
    score_table.add_column("Duration", justify="right")

    score_table.add_row(
        str(summary.total_checked),
        str(summary.valid_count),
        str(summary.broken_count),
        str(summary.redirect_count),
        str(summary.external_count),
        str(summary.document_count + summary.asset_count),
        f"{summary.duration_seconds:.2f}s",
    )
    console.print(score_table)

    broken = summary.broken_results
    if broken:
        console.print()
        broken_table = Table(
            title=f"Broken Links ({len(broken)})",
            show_header=True,
            header_style="bold red",
            show_lines=True,
        )
        broken_table.add_column("Status", style="bold red", width=10)
        broken_table.add_column("Broken URL", overflow="fold")
        broken_table.add_column("Type", width=10)
        broken_table.add_column("Found On (Referrer Pages)", overflow="fold")
        broken_table.add_column("Link Text / Alt", overflow="fold")

        for r in broken:
            status_label = str(r.status_code) if r.status_code else (r.error_type or "ERR")
            referrers = "\n".join(r.found_on) if r.found_on else "(Start URL)"
            texts = ", ".join(r.link_texts) if r.link_texts else "—"
            broken_table.add_row(status_label, r.link, r.resource_type, referrers, texts)
        console.print(broken_table)

    for path in saved_paths:
        console.print(f"[bold green]Saved report:[/bold green] {path}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="JumpingSpider",
        description="JumpingSpider: Concurrent web crawler, broken link detector, and asset validator.",
    )
    parser.add_argument(
        "start_url",
        nargs="?",
        help="Starting URL to crawl (strictly locked to paths under this directory).",
    )
    parser.add_argument(
        "legacy_output",
        nargs="?",
        help="Optional positional output filename (for backwards compatibility).",
    )
    parser.add_argument(
        "-o",
        "--output",
        action="append",
        dest="outputs",
        help="Output report file path (.json, .csv, .md, .html). Can be specified multiple times.",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["json", "csv", "md", "html"],
        default=None,
        help="Explicit report format override (otherwise inferred from file extension).",
    )
    parser.add_argument(
        "--tui",
        action="store_true",
        help="Launch the interactive Terminal User Interface (TUI).",
    )
    parser.add_argument(
        "--check-external",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Validate external and sibling links without crawling them (default: True).",
    )
    parser.add_argument(
        "--no-external",
        action="store_false",
        dest="check_external",
        help="Disable external and sibling link validation.",
    )
    parser.add_argument(
        "--check-assets",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Validate page assets (<img>, <script>, <link>, <video>, <iframe>) (default: True).",
    )
    parser.add_argument(
        "--no-assets",
        action="store_false",
        dest="check_assets",
        help="Disable page asset validation.",
    )
    parser.add_argument(
        "-w",
        "--workers",
        type=int,
        default=5,
        help="Number of concurrent worker threads (default: 5).",
    )
    parser.add_argument(
        "-d",
        "--delay",
        type=float,
        default=0.2,
        help="Delay in seconds between requests (default: 0.2).",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=10.0,
        help="HTTP request timeout in seconds (default: 10.0).",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=None,
        help="Maximum link depth to crawl for internal pages (default: unlimited).",
    )
    parser.add_argument(
        "--broken-only",
        action="store_true",
        help="Only include broken links in exported reports.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress live console output.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    output_files: list[str] = []
    if args.legacy_output:
        output_files.append(args.legacy_output)
    if args.outputs:
        output_files.extend(args.outputs)
    if not output_files:
        output_files = ["crawl_results.json"]

    if args.tui:
        from JumpingSpider.tui import JumpingSpiderApp

        initial_config = CrawlConfig(
            start_url=args.start_url or "https://weather.ndc.nasa.gov/tempo/",
            output_files=output_files,
            delay=args.delay,
            workers=args.workers,
            timeout=args.timeout,
            max_depth=args.max_depth,
            check_external=args.check_external,
            check_assets=args.check_assets,
            broken_only=args.broken_only,
        )
        app = JumpingSpiderApp(initial_config=initial_config)
        app.run()
        return 0

    if not args.start_url:
        parser.print_help()
        return 1

    crawl_site(
        start_url=args.start_url,
        output_filename=output_files,
        delay=args.delay,
        workers=args.workers,
        timeout=args.timeout,
        max_depth=args.max_depth,
        check_external=args.check_external,
        check_assets=args.check_assets,
        broken_only=args.broken_only,
        fmt=args.format,
        quiet=args.quiet,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
