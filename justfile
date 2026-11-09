# Development setup
dev:
    uv sync --all-extras
    maturin develop --release
    uv run pre-commit install

# Run tests
test python_version="3.14":
    uv run -p {{python_version}} --with . --with pydantic --extra dev --isolated pytest -s

# Test the standalone Rust core (no Python installation required)
test-rust:
    cargo test --workspace

# Run linting
lint:
    uv run ruff check .

pre-commit:
    uv run pre-commit run --all-files

# Run formatting
format:
    uv run ruff format .

# Zensical's tailored fork of mike for versioned docs deployment
MIKE := "mike @ git+https://github.com/squidfunk/mike.git"

# Clean documentation build
docs-clean:
    rm -rf docs/site

# Pre-build docs source: convert jupytext .py to .md+.ipynb (with download
# button), generate mkdocstrings API reference stubs into docs/source-built/.
# Cached: re-runs only re-execute notebooks whose source hash changed.
docs-build-source python_version="3.14":
    uv run -p {{python_version}} --extra docs --with "{{MIKE}}" --with . python docs/scripts/build_docs_source.py

# Build documentation (zensical) from the pre-built source
docs python_version="3.14": docs-build-source
    uv run -p {{python_version}} --with . --extra docs --with "{{MIKE}}" --isolated zensical build -f docs/zensical-built.yml

# Serve documentation locally (zensical) from the pre-built source
docs-serve python_version="3.14": docs-build-source
    uv run -p {{python_version}} --with . --extra docs --with "{{MIKE}}" --isolated zensical serve -f docs/zensical-built.yml --watch src/kfnetlist

# Deploy docs to gh-pages as the "dev" version (tracks main)
docs-deploy-dev python_version="3.14": docs-build-source
    uv run -p {{python_version}} --with . --extra docs --with "{{MIKE}}" --isolated mike deploy \
        --config-file docs/zensical-built.yml \
        --alias-type=redirect \
        --push \
        --update-aliases \
        dev

# Deploy docs to gh-pages as a tagged release version + set "latest" as default
docs-deploy-release version python_version="3.14": docs-build-source
    uv run -p {{python_version}} --with . --extra docs --with "{{MIKE}}" --isolated mike deploy \
        --config-file docs/zensical-built.yml \
        --alias-type=redirect \
        --push \
        --update-aliases \
        {{version}} latest
    uv run -p {{python_version}} --with . --extra docs --with "{{MIKE}}" --isolated mike set-default \
        --config-file docs/zensical-built.yml \
        --push \
        latest

# Regenerate kfnetlist.morphnet protobuf stubs from the single proto source
compile-schema-py:
    protoc --proto_path=crates/kfnetlist-schema/proto --python_out=src/kfnetlist/morphnet/morphnet_schema --pyi_out=src/kfnetlist/morphnet/morphnet_schema crates/kfnetlist-schema/proto/*.proto
    perl -pi -e 's/^import (\w+_pb2)/import kfnetlist.morphnet.morphnet_schema.$1/' src/kfnetlist/morphnet/morphnet_schema/*_pb2.py src/kfnetlist/morphnet/morphnet_schema/*_pb2.pyi
