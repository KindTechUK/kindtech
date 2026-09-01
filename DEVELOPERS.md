# Developer Guide

This guide provides instructions for developers working on the KindTech project.

## Setup

KindTech uses `uv` for dependency management instead of traditional pip. Make sure you have `uv` installed before proceeding and that you become familiar
with `uv`'s syntax.

### Initial Setup

Instead of the traditional `pip install -e .`, use:

```bash
# Clone the repository
git clone https://github.com/KindTechUK/kindtech
cd kindtech

# Install the package in development mode with all dev dependencies
uv sync --group dev
```

## Code Quality Tools

### Ruff

We use Ruff for linting and formatting. Run:

```bash
# Lint the code
uv run --group dev ruff check .

# Format the code
uv run --group dev ruff format .
```

### Pre-commit

We use prek to ensure code quality before committing:

```bash
# Install pre-commit hooks
uv run --group dev prek install

# Run pre-commit on all files
uv run --group dev prek run --all-files
```

## Documentation

Documentation is built using MkDocs:

```bash
# Serve documentation locally
uv run --group dev mkdocs serve

# Build documentation
uv run --group dev mkdocs build --strict
```

## Releases

PyPI releases are published by `.github/workflows/release.yml` when a version tag
such as `v0.1.0` is pushed. Before tagging, update `[project].version`, merge the
change to `main`, and confirm CI passes. The workflow verifies that the tag matches
the package version, builds and smoke-tests both distributions, generates
attestations, and publishes through the `pypi` environment using Trusted
Publishing. Do not upload distributions manually.
