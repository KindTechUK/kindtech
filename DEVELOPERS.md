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
uv sync --extra dev
```

## Code Quality Tools

### Ruff

We use Ruff for linting and formatting. Run:

```bash
# Lint the code
ruff check .

# Format the code
ruff format .
```

### Pre-commit

We use pre-commit to ensure code quality before committing:

```bash
# Install pre-commit hooks
pre-commit install

# Run pre-commit on all files
pre-commit run --all-files
```

## Documentation

Documentation is built using MkDocs:

```bash
# Serve documentation locally
mkdocs serve

# Build documentation
mkdocs build
```
