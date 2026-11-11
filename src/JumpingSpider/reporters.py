from __future__ import annotations

import csv
import html
import json
import os
from pathlib import Path

from JumpingSpider.models import CrawlSummary, LinkResult


def _filter_results(summary: CrawlSummary, broken_only: bool = False) -> list[LinkResult]:
    if broken_only:
        return [r for r in summary.results if r.success == 0]
    return list(summary.results)


def export_json(summary: CrawlSummary, output_path: str | Path, broken_only: bool = False) -> Path:
    """
    Exports crawl results to JSON.
    Preserves top-level array structure where each item contains "link", "success", and "status_code"
    for backwards compatibility, enriched with referrer and diagnostic fields.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    items = [r.to_dict() for r in _filter_results(summary, broken_only=broken_only)]
    with path.open("w", encoding="utf-8") as f:
        json.dump(items, f, indent=4)
    return path


def export_csv(summary: CrawlSummary, output_path: str | Path, broken_only: bool = False) -> Path:
    """Exports crawl results to a flat CSV file suitable for Excel or Google Sheets."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    results = _filter_results(summary, broken_only=broken_only)

    fieldnames = [
        "link",
        "status_code",
        "success",
        "scope",
        "resource_type",
        "method_used",
        "is_redirect",
        "final_url",
        "redirect_chain",
        "error_type",
        "error_message",
        "response_time_ms",
        "reference_count",
        "found_on_pages",
        "link_texts",
    ]

    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(
                {
                    "link": r.link,
                    "status_code": r.status_code,
                    "success": r.success,
                    "scope": r.scope,
                    "resource_type": r.resource_type,
                    "method_used": r.method_used,
                    "is_redirect": r.is_redirect,
                    "final_url": r.final_url or r.link,
                    "redirect_chain": " -> ".join(r.redirect_chain),
                    "error_type": r.error_type or "",
                    "error_message": r.error_message or "",
                    "response_time_ms": round(r.response_time_ms, 2),
                    "reference_count": len(r.references),
                    "found_on_pages": " | ".join(r.found_on),
                    "link_texts": " | ".join(r.link_texts),
                }
            )
    return path


def export_markdown(summary: CrawlSummary, output_path: str | Path, broken_only: bool = False) -> Path:
    """Exports a human-readable Markdown report with summary scorecard, broken links, and redirects."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = [
        "# JumpingSpider Crawl Report",
        "",
        f"- **Start URL**: `{summary.start_url}`",
        f"- **Path Boundary**: `{summary.base_prefix}`",
        f"- **Duration**: `{summary.duration_seconds:.2f}s`",
        "",
        "## Summary Scorecard",
        "",
        "| Metric | Count |",
        "| :--- | ---: |",
        f"| Total Checked | {summary.total_checked} |",
        f"| Valid (2xx/3xx) | {summary.valid_count} |",
        f"| Broken (4xx/5xx/Err) | {summary.broken_count} |",
        f"| Redirected | {summary.redirect_count} |",
        f"| External Links | {summary.external_count} |",
        f"| Documents & Assets | {summary.document_count + summary.asset_count} |",
        "",
    ]

    broken = summary.broken_results
    lines.append(f"## Broken Links ({len(broken)})")
    lines.append("")
    if not broken:
        lines.append("_No broken links detected._")
        lines.append("")
    else:
        lines.append("| Status | Broken URL | Type | Scope | Found On (Referrer Pages) | Link Text / Alt |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")
        for r in broken:
            status_label = str(r.status_code) if r.status_code else (r.error_type or "ERR")
            referrers = "<br>".join(f"`{p}`" for p in r.found_on) if r.found_on else "_(Start URL)_"
            texts = ", ".join(r.link_texts) if r.link_texts else "—"
            lines.append(
                f"| **{status_label}** | `{r.link}` | {r.resource_type} | {r.scope} | {referrers} | {texts} |"
            )
        lines.append("")

    if not broken_only:
        redirects = summary.redirect_results
        lines.append(f"## Redirected Links ({len(redirects)})")
        lines.append("")
        if not redirects:
            lines.append("_No redirects detected._")
            lines.append("")
        else:
            lines.append("| Original URL | Final URL | Hops | Found On |")
            lines.append("| :--- | :--- | ---: | :--- |")
            for r in redirects:
                referrers = "<br>".join(f"`{p}`" for p in r.found_on) if r.found_on else "_(Start URL)_"
                lines.append(
                    f"| `{r.link}` | `{r.final_url}` | {len(r.redirect_chain)} | {referrers} |"
                )
            lines.append("")

        lines.append(f"## All Checked URLs ({summary.total_checked})")
        lines.append("")
        lines.append("| Status | URL | Scope | Type | Method | Time (ms) | Referrers |")
        lines.append("| :--- | :--- | :--- | :--- | :--- | ---: | ---: |")
        for r in summary.results:
            status_label = str(r.status_code) if r.status_code else (r.error_type or "ERR")
            lines.append(
                f"| {status_label} | `{r.link}` | {r.scope} | {r.resource_type} | {r.method_used} | {r.response_time_ms:.1f} | {len(r.references)} |"
            )
        lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")
    return path


def export_html(summary: CrawlSummary, output_path: str | Path, broken_only: bool = False) -> Path:
    """Exports a self-contained HTML report with summary cards and tables."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    results = _filter_results(summary, broken_only=broken_only)

    broken_rows: list[str] = []
    for r in summary.broken_results:
        status_label = str(r.status_code) if r.status_code else html.escape(r.error_type or "ERROR")
        refs_html = "<br>".join(
            f'<a href="{html.escape(p)}">{html.escape(p)}</a>' for p in r.found_on
        ) or "<em>Start URL</em>"
        texts_html = html.escape(", ".join(r.link_texts)) or "—"
        err_detail = html.escape(r.error_message or "")
        broken_rows.append(
            f"<tr>"
            f'<td><span class="badge badge-err">{status_label}</span></td>'
            f'<td><a href="{html.escape(r.link)}">{html.escape(r.link)}</a>'
            f'{f"<div class=err-msg>{err_detail}</div>" if err_detail else ""}</td>'
            f"<td>{html.escape(r.resource_type)}</td>"
            f"<td>{html.escape(r.scope)}</td>"
            f"<td>{refs_html}</td>"
            f"<td>{texts_html}</td>"
            f"</tr>"
        )

    all_rows: list[str] = []
    for r in results:
        badge_cls = "badge-ok" if r.success == 1 else "badge-err"
        if r.is_redirect and r.success == 1:
            badge_cls = "badge-warn"
        status_label = str(r.status_code) if r.status_code else html.escape(r.error_type or "ERROR")
        refs_html = "<br>".join(html.escape(p) for p in r.found_on) or "<em>Start URL</em>"
        all_rows.append(
            f"<tr>"
            f'<td><span class="badge {badge_cls}">{status_label}</span></td>'
            f'<td><a href="{html.escape(r.link)}">{html.escape(r.link)}</a></td>'
            f"<td>{html.escape(r.scope)}</td>"
            f"<td>{html.escape(r.resource_type)}</td>"
            f"<td>{html.escape(r.method_used)}</td>"
            f"<td>{r.response_time_ms:.1f} ms</td>"
            f"<td>{refs_html}</td>"
            f"</tr>"
        )

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>JumpingSpider Crawl Report</title>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; margin: 2rem; color: #1f2937; background: #f9fafb; }}
  h1, h2 {{ color: #111827; }}
  .meta {{ background: #fff; padding: 1rem 1.25rem; border-radius: 8px; border: 1px solid #e5e7eb; margin-bottom: 1.5rem; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 1rem; margin-bottom: 2rem; }}
  .card {{ background: #fff; padding: 1rem; border-radius: 8px; border: 1px solid #e5e7eb; }}
  .card .label {{ font-size: 0.85rem; color: #6b7280; }}
  .card .value {{ font-size: 1.6rem; font-weight: 700; margin-top: 0.25rem; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; border: 1px solid #e5e7eb; margin-bottom: 2rem; }}
  th, td {{ text-align: left; padding: 0.65rem 0.85rem; border-bottom: 1px solid #e5e7eb; font-size: 0.9rem; vertical-align: top; word-break: break-all; }}
  th {{ background: #f3f4f6; font-weight: 600; }}
  .badge {{ display: inline-block; padding: 0.15rem 0.5rem; border-radius: 4px; font-weight: 600; font-size: 0.8rem; }}
  .badge-ok {{ background: #d1fae5; color: #065f46; }}
  .badge-warn {{ background: #fef3c7; color: #92400e; }}
  .badge-err {{ background: #fee2e2; color: #991b1b; }}
  .err-msg {{ color: #991b1b; font-size: 0.8rem; margin-top: 0.25rem; }}
</style>
</head>
<body>
  <h1>JumpingSpider Crawl Report</h1>
  <div class="meta">
    <div><strong>Start URL:</strong> <code>{html.escape(summary.start_url)}</code></div>
    <div><strong>Path Boundary:</strong> <code>{html.escape(summary.base_prefix)}</code></div>
    <div><strong>Duration:</strong> {summary.duration_seconds:.2f}s</div>
  </div>
  <div class="cards">
    <div class="card"><div class="label">Total Checked</div><div class="value">{summary.total_checked}</div></div>
    <div class="card"><div class="label">Valid</div><div class="value" style="color:#065f46">{summary.valid_count}</div></div>
    <div class="card"><div class="label">Broken</div><div class="value" style="color:#991b1b">{summary.broken_count}</div></div>
    <div class="card"><div class="label">Redirects</div><div class="value" style="color:#92400e">{summary.redirect_count}</div></div>
    <div class="card"><div class="label">External</div><div class="value">{summary.external_count}</div></div>
    <div class="card"><div class="label">Docs &amp; Assets</div><div class="value">{summary.document_count + summary.asset_count}</div></div>
  </div>

  <h2>Broken Links ({summary.broken_count})</h2>
  <table>
    <thead>
      <tr><th>Status</th><th>Broken URL</th><th>Type</th><th>Scope</th><th>Found On (Referrers)</th><th>Link Text / Alt</th></tr>
    </thead>
    <tbody>
      {"".join(broken_rows) if broken_rows else '<tr><td colspan="6">No broken links detected.</td></tr>'}
    </tbody>
  </table>

  <h2>Checked URLs ({len(results)})</h2>
  <table>
    <thead>
      <tr><th>Status</th><th>URL</th><th>Scope</th><th>Type</th><th>Method</th><th>Time</th><th>Found On</th></tr>
    </thead>
    <tbody>
      {"".join(all_rows)}
    </tbody>
  </table>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")
    return path


def export_report(
    summary: CrawlSummary,
    output_path: str | Path,
    fmt: str | None = None,
    broken_only: bool = False,
) -> Path:
    """Dispatches export based on explicit format or file extension (.json, .csv, .md, .html)."""
    ext = (fmt or os.path.splitext(str(output_path))[1].lstrip(".")).lower()
    if ext == "csv":
        return export_csv(summary, output_path, broken_only=broken_only)
    if ext in ("md", "markdown"):
        return export_markdown(summary, output_path, broken_only=broken_only)
    if ext in ("html", "htm"):
        return export_html(summary, output_path, broken_only=broken_only)
    return export_json(summary, output_path, broken_only=broken_only)
