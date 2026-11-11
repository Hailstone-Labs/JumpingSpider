# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-11-11

### Added
- Concurrent multi-threaded crawler (`SpiderCrawler`) with configurable worker count (`-w/--workers`), request delay (`-d/--delay`), timeout (`--timeout`), and max depth (`--max-depth`).
- Referrer (`found_on`), HTML tag (`<a>`, `<img>`, `<script>`, `<link>`, `<video>`, `<iframe>`), and link/alt text tracking via `LinkReference`.
- External and sibling link validation without crawling outside the starting URL path boundary (`--check-external` / `--no-external`).
- Page asset and binary document validation using `HEAD` requests with automatic streaming `GET` fallback on `405`/`403` (`--check-assets` / `--no-assets`).
- Redirect chain tracking (`301`/`302` -> final URL) and structured error categorization (`Timeout`, `SSLError`, `ConnectionError`, `HTTPError`).
- Multi-format report exporters for `.json`, `.csv`, `.md`, and `.html` (`-o/--output`, `-f/--format`, `--broken-only`).
- Interactive Terminal User Interface (`--tui`) built with `textual` for live crawl monitoring, filtering, referrer inspection, and report exports.
- GitHub Actions workflows for CI (`ci.yml`), automated releases (`release.yml`), and on-demand site audits (`site-audit.yml`), plus Dependabot configuration.

## [0.1.0] - 2026-11-10

### Added
- Initial path-locked recursive web crawler and JSON status exporter.

[0.2.0]: https://github.com/Hailstone-Labs/JumpingSpider/releases/tag/v0.2.0
[0.1.0]: https://github.com/Hailstone-Labs/JumpingSpider/commits/9974e31
