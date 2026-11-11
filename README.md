# JumpingSpider

**JumpingSpider** (`v0.2.0`) is a concurrent web crawler and broken link/asset validator with multi-format reporting (`.json`, `.csv`, `.md`, `.html`) and an interactive Terminal User Interface (TUI).

## Features

- **Strict Path Boundary Crawling**: Recursively crawls HTML pages under the starting URL path while preventing upward or parallel directory escapes.
- **Referrer & Anchor Text Tracking**: Records every source page (`found_on`), HTML tag (`<a>`, `<img>`, `<script>`, `<link>`, `<video>`, `<iframe>`), and link/alt text for every discovered URL so you know exactly which file to update.
- **External & Sibling Link Validation**: Validates links outside the crawl boundary without crawling into external sites.
- **Smart `HEAD` & Streaming Requests**: Uses `HEAD` requests (with automatic streaming `GET` fallback on `405`/`403`) for documents (`.pdf`, `.pptx`, `.xlsx`, `.mp4`, etc.), static assets, and external links to avoid downloading large binary files into memory.
- **Redirect & Error Diagnostics**: Captures full redirect chains (`301`/`302` -> final URL) and categorizes failures (`Timeout`, `SSLError`, `ConnectionError`, `HTTPError`).
- **Multi-Format Reports**: Export results to JSON, CSV, Markdown, or styled HTML.
- **Interactive TUI (`--tui`)**: Built with `textual` for live crawl monitoring, filtering (`All`, `Broken`, `Redirects`, `External`, `Assets/Docs`), referrer inspection, and one-key report exports.

## Installation

Requires Python 3.13+ and [uv](https://docs.astral.sh/uv/):

```bash
uv sync
```

## Usage

### CLI Mode

```bash
# Basic crawl (outputs crawl_results.json and prints a terminal summary scorecard)
uv run JumpingSpider https://weather.ndc.nasa.gov/tempo/

# Export multiple report formats at once
uv run JumpingSpider https://weather.ndc.nasa.gov/tempo/ \
  -o tempo_results.json \
  -o tempo_broken.csv \
  -o tempo_report.md \
  -o tempo_report.html

# Export only broken links to CSV
uv run JumpingSpider https://weather.ndc.nasa.gov/tempo/ -o broken_links.csv --broken-only

# Customize concurrency, rate limit delay, and depth
uv run JumpingSpider https://example.com/docs/ -w 8 -d 0.1 --max-depth 3

# Only check internal links and skip page assets
uv run JumpingSpider https://example.com/docs/ --no-external --no-assets
```

### CLI Options

| Option | Default | Description |
| :--- | :--- | :--- |
| `start_url` | — | Starting URL to crawl (strictly locked to paths under this directory). |
| `-o, --output <path>` | `crawl_results.json` | Output file path (`.json`, `.csv`, `.md`, `.html`). Can be passed multiple times. |
| `-f, --format <fmt>` | Auto from extension | Explicit report format override (`json`, `csv`, `md`, `html`). |
| `--tui` | `False` | Launch the interactive Terminal User Interface (TUI). |
| `--check-external` / `--no-external` | `True` | Validate external and sibling links without crawling them. |
| `--check-assets` / `--no-assets` | `True` | Validate page assets (`<img>`, `<script>`, `<link>`, `<video>`, `<iframe>`). |
| `-w, --workers <int>` | `5` | Number of concurrent worker threads. |
| `-d, --delay <float>` | `0.2` | Delay in seconds between HTTP requests. |
| `--timeout <float>` | `10.0` | HTTP request timeout in seconds. |
| `--max-depth <int>` | Unlimited | Maximum link depth to crawl for internal pages. |
| `--broken-only` | `False` | Only include broken links in exported reports. |
| `-q, --quiet` | `False` | Suppress live console progress and summary tables. |

### Interactive TUI Mode

```bash
uv run JumpingSpider --tui https://weather.ndc.nasa.gov/tempo/
```

**TUI Keyboard Shortcuts:**
- `Ctrl+S`: Start crawl
- `Ctrl+X`: Stop crawl
- `1`–`5`: Filter table (`1` All, `2` Broken, `3` Redirects, `4` External, `5` Assets/Docs)
- `e`: Export all report formats (`crawl_results.{json,csv,md,html}`)
- `q`: Quit

## Development & Tests

```bash
uv run pytest -v
```
