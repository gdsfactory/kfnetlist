# Schema source directory
SCHEMA_DIR := "kfnetlist-schema"

# Output directory for generated Python protobuf code
PROTO_OUT := "src/kfnetlist/kfnetlist_schema"
PROTO_OUT_RS := "src/kfnetlist_schema"

# Compile .proto files to Python (protoc)
compile-schema-py:
    mkdir -p {{PROTO_OUT}}
    protoc \
        --proto_path={{SCHEMA_DIR}} \
        --python_out={{PROTO_OUT}} \
        --pyi_out={{PROTO_OUT}} \
        {{SCHEMA_DIR}}/*.proto
    touch {{PROTO_OUT}}/__init__.py

# Compile .proto files to Rust via prost-build (invoked through maturin's build.rs)
#compile-schema-rs:
#    mkdir -p {{PROTO_OUT_RS}}
#    maturin build

# Compile .proto files to both Python and Rust
compile-schema: compile-schema-py

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
