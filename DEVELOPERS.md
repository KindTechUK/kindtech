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

### Does KindTech need separate PyPI registration?

No. The configured pending publisher can create the project during the first
trusted publish, so no priming upload is needed. A pending publisher does not
reserve the project name before that first publish.

### Why test installed wheel and source distributions?

A successful build proves only that archives were created. CI installs the wheel
and source distribution in isolation to verify their bundled data, then exercises
the pandas and Polars backends separately.

### What must the first release verify?

Before pushing `v0.1.0`, confirm the tag matches the merged package version and
that CI passes on the exact `main` commit. After the tag triggers the workflow,
verify the published filenames and hashes on PyPI and clean-install the released
artifacts before closing the release issue.
