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

    Extract hierarchical netlists from kfactory/klayout layout cells.

    [:octicons-arrow-right-24: Overview](extraction/overview.md)
    &nbsp;·&nbsp;
    [:octicons-arrow-right-24: Port Checking](extraction/port_checking.py)

-   :material-lightbulb-on:{ .lg .middle } **Guides**

    ---

    Equivalent ports, instance flattening, and common patterns.

    [:octicons-arrow-right-24: Equivalent Ports](guides/equivalent_ports.py)
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

## Relationship to kfactory

kfnetlist is the netlist data model that [kfactory](https://github.com/gdsfactory/kfactory)
uses internally. It is published as a separate package so that:

- Tools that only need netlist manipulation do not have to depend on kfactory or klayout
- The netlist schema can evolve on its own release cadence
- Downstream projects can consume netlists without pulling in a full layout framework

For end-to-end examples of netlist extraction using kfactory, see the
[kfactory schematics documentation](https://gdsfactory.github.io/kfactory/dev/schematics/overview/).
