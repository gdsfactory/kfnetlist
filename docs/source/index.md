# kfnetlist

**kfnetlist** is a standalone, Rust-backed netlist schema for [kfactory](https://github.com/gdsfactory/kfactory) and netlist tooling.

It provides a fast, type-safe data model for circuit connectivity — instances, nets, ports, and arrays — with full JSON/dict serialization and Pydantic v2 integration. The core is implemented in Rust via PyO3 and has zero runtime Python dependencies.

---

<div class="grid cards" markdown>

-   :material-rocket-launch:{ .lg .middle } **Getting Started**

    ---

    Install kfnetlist and build your first netlist in under 5 minutes.

    [:octicons-arrow-right-24: Installation](getting_started/installation.md)
    &nbsp;·&nbsp;
    [:octicons-arrow-right-24: Quickstart](getting_started/quickstart.py)

-   :material-book-open-variant:{ .lg .middle } **Core Concepts**

    ---

    Understand the Netlist data model, port types, and serialization.

    [:octicons-arrow-right-24: Netlist Model](concepts/netlist_model.py)
    &nbsp;·&nbsp;
    [:octicons-arrow-right-24: Ports & Refs](concepts/ports_and_refs.py)
    &nbsp;·&nbsp;
    [:octicons-arrow-right-24: Serialization](concepts/serialization.py)

-   :material-magnify-scan:{ .lg .middle } **Extraction**

    ---

    Extract hierarchical netlists, detect shorts and opens, parse L2N results.

    [:octicons-arrow-right-24: Overview](extraction/overview.md)
    &nbsp;·&nbsp;
    [:octicons-arrow-right-24: Short Detection](extraction/short_detection.py)
    &nbsp;·&nbsp;
    [:octicons-arrow-right-24: L2N Parsing](extraction/l2n_parsing.py)

-   :material-lightbulb-on:{ .lg .middle } **Guides**

    ---

    Equivalent ports, open detection, RDB filtering, and common patterns.

    [:octicons-arrow-right-24: Equivalent Ports](guides/equivalent_ports.py)
    &nbsp;·&nbsp;
    [:octicons-arrow-right-24: Open Detection](guides/open_detection.py)
    &nbsp;·&nbsp;
    [:octicons-arrow-right-24: RDB Filtering](guides/rdb_filtering.py)
    &nbsp;·&nbsp;
    [:octicons-arrow-right-24: FAQ](guides/faq.md)

</div>

---

## Key Features

- **Rust core** — `Netlist`, `Net`, and port types implemented in Rust for speed and memory safety
- **Zero runtime dependencies** — the base package has no Python dependencies
- **Full serialization** — `to_json()` / `from_json()` and `to_dict()` / `from_dict()` on every type
- **Pydantic v2 support** — all types implement `__get_pydantic_core_schema__`
- **Equivalent ports** — fold electrically-equivalent ports into canonical names for netlist comparison
- **Instance flattening** — merge sub-cell instances into the parent, reconnecting touching nets
- **Port checking** — `PortCheck` bitmask and `check_connection()` for geometric port-pair comparison
- **Netlist extraction** — extract hierarchical netlists from kfactory/klayout cells
- **L2N parsing** — convert klayout `LayoutToNetlist` results to JSON-serializable dicts
- **Short detection** — find geometric polygon overlaps between distinct nets
- **Open detection** — find unconnected ports, singleton nets, and missing nets vs. a reference
- **RDB filtering** — filter KLayout Report Databases by error category with typed `LvsError` constants
- **Error summary** — generate Markdown tables from verification results

## Relationship to kfactory

kfnetlist is the netlist data model that [kfactory](https://github.com/gdsfactory/kfactory)
uses internally. It is published as a separate package so that:

- Tools that only need netlist manipulation do not have to depend on kfactory or klayout
- The netlist schema can evolve on its own release cadence
- Downstream projects can consume netlists without pulling in a full layout framework

For end-to-end examples of netlist extraction using kfactory, see the
[kfactory schematics documentation](https://gdsfactory.github.io/kfactory/dev/schematics/overview/).
