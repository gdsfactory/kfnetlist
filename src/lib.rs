use pyo3::basic::CompareOp;
use pyo3::prelude::*;
use pythonize::{depythonize, pythonize};
use serde::{Deserialize, Serialize};
use std::collections::hash_map::DefaultHasher;
use std::hash::{Hash, Hasher};

mod instance;
mod net;
mod netlist;
mod port;

use instance::{NetlistArray, NetlistInstance};
use net::{Net, NetIter};
use netlist::Netlist;
use port::{NetlistPort, PortArrayRef, PortRef};

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<NetlistPort>()?;
    m.add_class::<PortRef>()?;
    m.add_class::<PortArrayRef>()?;
    m.add_class::<NetlistArray>()?;
    m.add_class::<NetlistInstance>()?;
    m.add_class::<Net>()?;
    m.add_class::<NetIter>()?;
    m.add_class::<Netlist>()?;
    Ok(())
}

// Re-export helpers used across modules.
pub(crate) fn hash64<T: Hash>(t: &T) -> u64 {
    let mut s = DefaultHasher::new();
    t.hash(&mut s);
    s.finish()
}

pub(crate) fn cmp_to_py(op: CompareOp, lt: bool, eq: bool) -> bool {
    match op {
        CompareOp::Lt => lt,
        CompareOp::Le => lt || eq,
        CompareOp::Eq => eq,
        CompareOp::Ne => !eq,
        CompareOp::Gt => !lt && !eq,
        CompareOp::Ge => !lt,
    }
}

/// Wrap a comparison result as a Python object, returning `NotImplemented`
/// when the operands are not comparable. CPython will then try the reflected
/// operation, and ultimately fall back to identity-based equality / a
/// `TypeError` on ordering ops.
pub(crate) fn richcmp_result(py: Python<'_>, value: Option<bool>) -> PyObject {
    use pyo3::IntoPyObjectExt;
    match value {
        Some(b) => b.into_py_any(py).expect("bool is always convertible"),
        None => py.NotImplemented(),
    }
}

pub(crate) fn json_string<T: Serialize>(value: &T) -> PyResult<String> {
    serde_json::to_string(value)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("serialize: {e}")))
}

pub(crate) fn json_parse<'de, T: Deserialize<'de>>(s: &'de str) -> PyResult<T> {
    serde_json::from_str(s)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("deserialize: {e}")))
}

pub(crate) fn to_py_dict<'py, T: Serialize>(
    py: Python<'py>,
    value: &T,
) -> PyResult<Bound<'py, PyAny>> {
    pythonize(py, value)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("to_dict: {e}")))
}

pub(crate) fn from_py_any<'py, T: for<'de> Deserialize<'de>>(
    obj: &Bound<'py, PyAny>,
) -> PyResult<T> {
    depythonize(obj)
        .map_err(|e| pyo3::exceptions::PyValueError::new_err(format!("from_dict: {e}")))
}

pub(crate) fn pydantic_core_schema(cls: &Bound<'_, pyo3::types::PyType>) -> PyResult<PyObject> {
    let py = cls.py();
    let locals = pyo3::types::PyDict::new(py);
    locals.set_item("cls", cls)?;
    locals.set_item(
        "cs",
        py.import("pydantic_core")?.getattr("core_schema")?,
    )?;
    py.run(
        c"def _validate(v):
    if isinstance(v, cls):
        return v
    if isinstance(v, dict):
        return cls.from_dict(v)
    raise ValueError(f'Cannot convert {type(v).__name__} to {cls.__name__}')

_schema = cs.no_info_plain_validator_function(
    _validate,
    serialization=cs.plain_serializer_function_ser_schema(
        lambda v: v.to_dict(), info_arg=False,
    ),
)",
        Some(&locals),
        Some(&locals),
    )?;
    Ok(locals.get_item("_schema")?.unwrap().unbind())
}

/// Python-style repr for a string: single-quoted, escapes only the minimum
/// for the values we expect (identifiers / port names). Mirrors the output
/// used by Python's f-string `{!r}` for ASCII strings without single quotes.
pub(crate) fn py_repr(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 2);
    let has_single = s.contains('\'');
    let has_double = s.contains('"');
    let (quote, escape_quote) = if has_single && !has_double {
        ('"', '"')
    } else {
        ('\'', '\'')
    };
    out.push(quote);
    for c in s.chars() {
        match c {
            c if c == escape_quote => {
                out.push('\\');
                out.push(c);
            }
            '\\' => out.push_str("\\\\"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            c if (c as u32) < 0x20 => {
                out.push_str(&format!("\\x{:02x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}
