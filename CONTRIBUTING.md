# Contributing to JumpingSpider

First off, thank you for considering contributing to **JumpingSpider**! Contributions, bug reports, and feature requests are welcome.

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md).

## Development Setup

JumpingSpider uses **Python 3.13+** and [**uv**](https://docs.astral.sh/uv/) for dependency management and packaging.

1. **Fork and clone the repository:**

   ```bash
   git clone https://github.com/Hailstone-Labs/JumpingSpider.git
   cd JumpingSpider
   ```

2. **Install dependencies (including development dependencies):**

   ```bash
   uv sync --all-groups
   ```

## Running Tests & Linting

Before submitting a Pull Request, please ensure all tests pass and the linter reports no issues:

```bash
# Run the test suite
uv run pytest -v

# Run Ruff linter
uv run ruff check .

# Check formatting with Ruff
uv run ruff format --check .

# Verify package build
uv build
```

## Submitting Changes

1. Create a descriptive branch from `main` (e.g., `feat/custom-headers` or `fix/redirect-handling`).
2. Add or update unit tests in `tests/` to cover your changes.
3. Update documentation in `README.md` or `CHANGELOG.md` if applicable.
4. Open a Pull Request against the `main` branch and fill out the pull request template.

## License

By contributing to JumpingSpider, you agree that your contributions will be licensed under its [MIT License](LICENSE).
