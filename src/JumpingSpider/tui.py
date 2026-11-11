from __future__ import annotations

import threading
from typing import ClassVar

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Button, Checkbox, DataTable, Footer, Header, Input, Static

from JumpingSpider.crawler import SpiderCrawler
from JumpingSpider.models import CrawlConfig, CrawlSummary, LinkResult
from JumpingSpider.reporters import export_csv, export_html, export_json, export_markdown


class JumpingSpiderApp(App[None]):
    """Interactive Terminal User Interface for JumpingSpider."""

    TITLE = "JumpingSpider — Web Crawler & Link Validator"
    CSS = """
    Screen {
        layout: vertical;
    }
    #controls-row {
        height: auto;
        padding: 1 1 0 1;
        align: left middle;
    }
    #url-input {
        width: 1fr;
        margin-right: 1;
    }
    #workers-input {
        width: 10;
        margin-right: 1;
    }
    .ctrl-chk {
        margin-right: 1;
    }
    .ctrl-btn {
        margin-right: 1;
        min-width: 12;
    }
    #scorecard {
        height: 3;
        margin: 1 1 0 1;
        padding: 0 2;
        background: $surface;
        border: tall $primary;
        content-align: left middle;
    }
    #filter-row {
        height: auto;
        padding: 0 1;
        margin-top: 1;
        align: left middle;
    }
    .filter-btn {
        margin-right: 1;
        min-width: 12;
    }
    #results-table {
        height: 1fr;
        margin: 1 1 0 1;
        border: tall $panel;
    }
    #inspector-box {
        height: 11;
        margin: 1;
        padding: 1 2;
        background: $surface;
        border: tall $secondary;
    }
    """

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("ctrl+s", "start_crawl", "Start Crawl"),
        Binding("ctrl+x", "stop_crawl", "Stop"),
        Binding("1", "filter_mode('all')", "All"),
        Binding("2", "filter_mode('broken')", "Broken"),
        Binding("3", "filter_mode('redirects')", "Redirects"),
        Binding("4", "filter_mode('external')", "External"),
        Binding("5", "filter_mode('assets')", "Assets/Docs"),
        Binding("e", "export_all", "Export Reports"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, initial_config: CrawlConfig | None = None) -> None:
        super().__init__()
        self.config = initial_config or CrawlConfig(start_url="https://weather.ndc.nasa.gov/tempo/")
        self.crawler: SpiderCrawler | None = None
        self.summary: CrawlSummary | None = None
        self.results_by_url: dict[str, LinkResult] = {}
        self.ordered_urls: list[str] = []
        self.active_filter: str = "all"
        self.completed_count: int = 0
        self.total_queued: int = 0
        self.status_message: str = "Ready. Enter a URL and press Start."

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="controls-row"):
            yield Input(
                value=self.config.start_url,
                placeholder="https://example.com/path/",
                id="url-input",
            )
            yield Checkbox("External", value=self.config.check_external, id="chk-external", classes="ctrl-chk")
            yield Checkbox("Assets", value=self.config.check_assets, id="chk-assets", classes="ctrl-chk")
            yield Input(value=str(self.config.workers), placeholder="Workers", id="workers-input")
            yield Button("Start", id="btn-start", variant="success", classes="ctrl-btn")
            yield Button("Stop", id="btn-stop", variant="error", disabled=True, classes="ctrl-btn")

        yield Static("", id="scorecard")

        with Horizontal(id="filter-row"):
            yield Button("All (1)", id="filter-all", variant="primary", classes="filter-btn")
            yield Button("Broken (2)", id="filter-broken", variant="default", classes="filter-btn")
            yield Button("Redirects (3)", id="filter-redirects", variant="default", classes="filter-btn")
            yield Button("External (4)", id="filter-external", variant="default", classes="filter-btn")
            yield Button("Assets/Docs (5)", id="filter-assets", variant="default", classes="filter-btn")
            yield Button("Export All (e)", id="btn-export", variant="warning", classes="filter-btn")

        yield DataTable(id="results-table", cursor_type="row", zebra_stripes=True)

        with VerticalScroll(id="inspector-box"):
            yield Static(
                "Select a row in the table above to inspect its HTTP details, redirect chain, and source pages (referrers).",
                id="inspector-content",
            )
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.add_columns("Status", "URL", "Scope", "Type", "Method", "Time (ms)", "Referrers")
        self._refresh_scorecard()

    def _matches_filter(self, result: LinkResult) -> bool:
        if self.active_filter == "broken":
            return result.success == 0
        if self.active_filter == "redirects":
            return result.is_redirect
        if self.active_filter == "external":
            return result.scope == "external"
        if self.active_filter == "assets":
            return result.resource_type in ("asset", "document")
        return True

    def _format_status_cell(self, result: LinkResult) -> Text:
        label = str(result.status_code) if result.status_code else (result.error_type or "ERR")
        if result.success == 0:
            return Text(f"✗ {label}", style="bold red")
        if result.is_redirect:
            return Text(f"↪ {label}", style="bold yellow")
        return Text(f"✓ {label}", style="bold green")

    def _refresh_scorecard(self) -> None:
        results = [self.results_by_url[u] for u in self.ordered_urls]
        valid = sum(1 for r in results if r.success == 1)
        broken = sum(1 for r in results if r.success == 0)
        redirects = sum(1 for r in results if r.is_redirect)
        external = sum(1 for r in results if r.scope == "external")
        assets = sum(1 for r in results if r.resource_type in ("asset", "document"))

        score_text = (
            f"[bold]Checked:[/bold] {self.completed_count}/{self.total_queued}   "
            f"[bold green]Valid:[/bold green] {valid}   "
            f"[bold red]Broken:[/bold red] {broken}   "
            f"[bold yellow]Redirects:[/bold yellow] {redirects}   "
            f"[bold cyan]External:[/bold cyan] {external}   "
            f"[bold magenta]Assets/Docs:[/bold magenta] {assets}   "
            f"|  {self.status_message}"
        )
        self.query_one("#scorecard", Static).update(score_text)

    def _rebuild_table(self) -> None:
        table = self.query_one("#results-table", DataTable)
        table.clear()
        for url in self.ordered_urls:
            res = self.results_by_url[url]
            if self._matches_filter(res):
                table.add_row(
                    self._format_status_cell(res),
                    res.link,
                    res.scope,
                    res.resource_type,
                    res.method_used,
                    f"{res.response_time_ms:.1f}",
                    str(len(res.references)),
                    key=res.link,
                )

    def _on_url_completed_ui(self, result: LinkResult, completed: int, total: int) -> None:
        is_new = result.link not in self.results_by_url
        self.results_by_url[result.link] = result
        if is_new:
            self.ordered_urls.append(result.link)
        self.completed_count = completed
        self.total_queued = total
        self.status_message = f"Checked {result.link}"
        self._refresh_scorecard()

        table = self.query_one("#results-table", DataTable)
        if self._matches_filter(result) and is_new:
            table.add_row(
                self._format_status_cell(result),
                result.link,
                result.scope,
                result.resource_type,
                result.method_used,
                f"{result.response_time_ms:.1f}",
                str(len(result.references)),
                key=result.link,
            )

    def _on_crawl_finished_ui(self, summary: CrawlSummary) -> None:
        self.summary = summary
        self.results_by_url = {r.link: r for r in summary.results}
        self.ordered_urls = [r.link for r in summary.results]
        self.completed_count = summary.total_checked
        self.total_queued = summary.total_checked
        self.status_message = f"Done in {summary.duration_seconds:.2f}s"
        self.query_one("#btn-start", Button).disabled = False
        self.query_one("#btn-stop", Button).disabled = True
        self._refresh_scorecard()
        self._rebuild_table()

    def action_start_crawl(self) -> None:
        if self.crawler is not None and not self.query_one("#btn-start", Button).disabled:
            pass
        url_val = self.query_one("#url-input", Input).value.strip()
        if not url_val:
            self.status_message = "Please enter a valid start URL."
            self._refresh_scorecard()
            return

        workers_str = self.query_one("#workers-input", Input).value.strip()
        try:
            workers = max(1, int(workers_str))
        except ValueError:
            workers = 5

        self.config.start_url = url_val
        self.config.check_external = self.query_one("#chk-external", Checkbox).value
        self.config.check_assets = self.query_one("#chk-assets", Checkbox).value
        self.config.workers = workers

        self.results_by_url.clear()
        self.ordered_urls.clear()
        self.completed_count = 0
        self.total_queued = 1
        self.status_message = f"Crawling under {self.config.base_prefix} ..."
        self.query_one("#results-table", DataTable).clear()
        self.query_one("#btn-start", Button).disabled = True
        self.query_one("#btn-stop", Button).disabled = False
        self._refresh_scorecard()

        def handle_completed(res: LinkResult, comp: int, tot: int) -> None:
            self.call_from_thread(self._on_url_completed_ui, res, comp, tot)

        self.crawler = SpiderCrawler(self.config, on_url_completed=handle_completed)

        def worker_fn() -> None:
            assert self.crawler is not None
            summary = self.crawler.run()
            self.call_from_thread(self._on_crawl_finished_ui, summary)

        thread = threading.Thread(target=worker_fn, daemon=True)
        thread.start()

    def action_stop_crawl(self) -> None:
        if self.crawler is not None:
            self.crawler.stop()
            self.status_message = "Stopping crawl..."
            self._refresh_scorecard()

    def action_filter_mode(self, mode: str) -> None:
        self.active_filter = mode
        filter_ids = {
            "all": "#filter-all",
            "broken": "#filter-broken",
            "redirects": "#filter-redirects",
            "external": "#filter-external",
            "assets": "#filter-assets",
        }
        for key, btn_id in filter_ids.items():
            btn = self.query_one(btn_id, Button)
            btn.variant = "primary" if key == mode else "default"
        self._rebuild_table()

    def action_export_all(self) -> None:
        results = [self.results_by_url[u] for u in self.ordered_urls]
        if not results:
            self.status_message = "Nothing to export yet."
            self._refresh_scorecard()
            return
        summary = self.summary or CrawlSummary(
            start_url=self.config.start_url,
            base_prefix=self.config.base_prefix,
            results=results,
        )
        export_json(summary, "crawl_results.json")
        export_csv(summary, "crawl_results.csv")
        export_markdown(summary, "crawl_results.md")
        export_html(summary, "crawl_results.html")
        self.status_message = "Exported crawl_results.{json,csv,md,html}"
        self._refresh_scorecard()

    @on(Button.Pressed, "#btn-start")
    def on_start_pressed(self) -> None:
        self.action_start_crawl()

    @on(Button.Pressed, "#btn-stop")
    def on_stop_pressed(self) -> None:
        self.action_stop_crawl()

    @on(Button.Pressed, "#filter-all")
    def on_filter_all(self) -> None:
        self.action_filter_mode("all")

    @on(Button.Pressed, "#filter-broken")
    def on_filter_broken(self) -> None:
        self.action_filter_mode("broken")

    @on(Button.Pressed, "#filter-redirects")
    def on_filter_redirects(self) -> None:
        self.action_filter_mode("redirects")

    @on(Button.Pressed, "#filter-external")
    def on_filter_external(self) -> None:
        self.action_filter_mode("external")

    @on(Button.Pressed, "#filter-assets")
    def on_filter_assets(self) -> None:
        self.action_filter_mode("assets")

    @on(Button.Pressed, "#btn-export")
    def on_export_pressed(self) -> None:
        self.action_export_all()

    @on(DataTable.RowHighlighted, "#results-table")
    @on(DataTable.RowSelected, "#results-table")
    def on_row_selected(self, event: DataTable.RowHighlighted | DataTable.RowSelected) -> None:
        if event.row_key is None or event.row_key.value is None:
            return
        url_key = str(event.row_key.value)
        res = self.results_by_url.get(url_key)
        if res is None:
            return

        lines = [
            f"[bold]URL:[/bold] {res.link}",
            (
                f"[bold]Status:[/bold] {res.status_code} ({'OK' if res.success else (res.error_type or 'Broken')})   "
                f"[bold]Scope:[/bold] {res.scope}   [bold]Type:[/bold] {res.resource_type}   "
                f"[bold]Method:[/bold] {res.method_used}   [bold]Content-Type:[/bold] {res.content_type or 'N/A'}"
            ),
        ]
        if res.is_redirect:
            chain_str = " -> ".join([*res.redirect_chain, res.final_url])
            lines.append(f"[bold yellow]Redirect Chain:[/bold yellow] {chain_str}")
        if res.error_message:
            lines.append(f"[bold red]Error Detail:[/bold red] {res.error_message}")

        if not res.references:
            lines.append("[bold]Referrers:[/bold] _(Start URL — root of crawl)_")
        else:
            lines.append(f"[bold]Found On ({len(res.references)} reference(s)):[/bold]")
            for ref in res.references[:15]:
                label_part = f' — "{ref.text}"' if ref.text else ""
                lines.append(f"  • {ref.source_url}  [dim](<{ref.tag} {ref.attribute}>)[/dim]{label_part}")
            if len(res.references) > 15:
                lines.append(f"  • ... and {len(res.references) - 15} more reference(s)")

        self.query_one("#inspector-content", Static).update("\n".join(lines))
