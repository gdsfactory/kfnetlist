# Development setup
dev:
    uv sync --all-extras
    maturin develop --release
    uv run pre-commit install

# Run tests
test python_version="3.14":
    uv run -p {{python_version}} --with . --extra dev --isolated pytest -s

# Run linting
lint:
    uv run ruff check .

# Run formatting
format:
    uv run ruff format .

# Clean documentation build
docs-clean:
    rm -rf docs/site

# Pre-build docs source: convert jupytext .py to .md+.ipynb (with download
# button), generate mkdocstrings API reference stubs into docs/source-built/.
# Cached: re-runs only re-execute notebooks whose source hash changed.
docs-build-source python_version="3.14":
    uv run -p {{python_version}} --extra docs --with . python docs/scripts/build_docs_source.py

# Build documentation (zensical) from the pre-built source
docs python_version="3.14": docs-build-source
    uv run -p {{python_version}} --with . --extra docs --isolated zensical build -f docs/zensical-built.yml

# Serve documentation locally (zensical) from the pre-built source
docs-serve python_version="3.14": docs-build-source
    uv run -p {{python_version}} --with . --extra docs --isolated zensical serve -f docs/zensical-built.yml --watch src/kfnetlist
