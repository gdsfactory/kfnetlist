//! Python object conversion only; all schema operations live in kfnetlist-schema.
use crate::{from_py_any, json_parse, json_string, to_py_dict};
use kfnetlist_schema::{self as core, proto};
use prost::Message;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict, PyList, PyTuple, PyType};
use serde::{Deserialize, Serialize};
use serde_json::Value;

fn schema_error(e: impl std::fmt::Display) -> PyErr {
    pyo3::exceptions::PyValueError::new_err(e.to_string())
}

// Accept native schema objects nested in constructor dicts/lists without
// importing Python schema, protobuf, YAML, or pydantic implementations.
fn input_value(obj: &Bound<'_, PyAny>) -> PyResult<Value> {
    if let Ok(d) = obj.downcast::<PyDict>() {
        let mut map = serde_json::Map::new();
        for (k, v) in d {
            map.insert(k.extract()?, input_value(&v)?);
        }
        Ok(Value::Object(map))
    } else if obj.is_instance_of::<PyList>() || obj.is_instance_of::<PyTuple>() {
        Ok(Value::Array(
            obj.try_iter()?
                .map(|v| input_value(&v?))
                .collect::<PyResult<_>>()?,
        ))
    } else if obj.hasattr("to_dict")? {
        from_py_any(&obj.call_method0("to_dict")?)
    } else if obj.hasattr("__int__")?
        && !obj.is_instance_of::<pyo3::types::PyFloat>()
        && !obj.is_instance_of::<pyo3::types::PyBool>()
    {
        from_py_any(&obj.call_method0("__int__")?)
    } else {
        from_py_any(obj)
    }
}
/// Rewrites pre-morphnet schema input; document classes (free-form settings) opt out.
trait Legacy {
    fn upgrade(_py: Python<'_>, _value: &mut Value) -> PyResult<()> {
        Ok(())
    }
}
// Keys removed when the schema adopted morphnet's circuit.proto. None exists in the new
// schema, so a structural rewrite is safe; `properties`/`arguments` hold user keys.
fn upgrade_legacy(value: &mut Value, found: &mut std::collections::BTreeSet<&'static str>) {
    if let Value::Array(items) = value {
        items.iter_mut().for_each(|v| upgrade_legacy(v, found));
        return;
    }
    let Value::Object(obj) = value else { return };
    let mut moved = Vec::new();
    for key in ["uid", "cross_section", "domain"] {
        // `domain` is still an enum on Terminal/Connection/Bus; only the string form is legacy.
        if key == "domain" && !matches!(obj.get(key), Some(Value::String(_))) {
            continue;
        }
        let Some(old) = obj.remove(key) else { continue };
        let text = match old {
            Value::String(s) => s,
            other => other.to_string(),
        };
        if !text.is_empty() && text != "0" {
            found.insert(key);
            moved.push((format!("__{key}__"), Value::String(text)));
        }
    }
    if !moved.is_empty() {
        if let Some(Value::Object(props)) = obj
            .entry("properties")
            .or_insert_with(|| Value::Object(Default::default()))
            .as_object_mut()
            .map(|_| ())
            .and(obj.get_mut("properties"))
        {
            props.extend(moved);
        }
    }
    if let Some(terminals) = obj.remove("terminal") {
        found.insert("terminal");
        obj.entry("terminals").or_insert(terminals);
    }
    let mut parameters = Vec::new();
    if let Some(Value::Array(values)) = obj.remove("parameter_values") {
        parameters.extend(
            values
                .into_iter()
                .map(|v| serde_json::json!({"name": "", "default_value": v})),
        );
    }
    if let Some(Value::Object(overrides)) = obj.remove("parameter_overrides") {
        parameters.extend(
            overrides
                .into_iter()
                .map(|(k, v)| serde_json::json!({"name": k, "default_value": v})),
        );
    }
    if !parameters.is_empty() {
        found.insert("parameter_values/parameter_overrides");
        if let Some(Value::Array(list)) = Some(
            obj.entry("parameters")
                .or_insert_with(|| Value::Array(Vec::new())),
        ) {
            list.extend(parameters);
        }
    }
    for (key, child) in obj.iter_mut() {
        if key != "properties" && key != "arguments" {
            upgrade_legacy(child, found);
        }
    }
}
fn upgrade_with_warning(py: Python<'_>, value: &mut Value) -> PyResult<()> {
    let mut found = std::collections::BTreeSet::new();
    upgrade_legacy(value, &mut found);
    if found.is_empty() {
        return Ok(());
    }
    let keys: Vec<_> = found.into_iter().collect();
    crate::warn_deprecated(
        py,
        &format!(
            "circuit schema fields {} were removed (morphnet schema); \
             values moved to properties[\"__<field>__\"], `terminals` and `parameters`",
            keys.join(", ")
        ),
    )
}
// Deprecated getters read the values `upgrade_legacy` moved into properties.
fn legacy_property(
    py: Python<'_>,
    properties: &std::collections::BTreeMap<String, String>,
    key: &str,
) -> PyResult<String> {
    crate::warn_deprecated(
        py,
        &format!("`{key}` is deprecated; read properties[\"__{key}__\"] instead"),
    )?;
    Ok(properties
        .get(&format!("__{key}__"))
        .cloned()
        .unwrap_or_default())
}
trait Field {
    fn field(&self, py: Python<'_>) -> PyResult<PyObject>;
}
macro_rules! scalar_field {
    ($($t:ty),*) => { $(impl Field for $t {
        fn field(&self, py: Python<'_>) -> PyResult<PyObject> { Ok(to_py_dict(py, self)?.unbind()) }
    })* };
}
scalar_field!(
    String,
    i32,
    i64,
    u32,
    f64,
    Value,
    serde_json::Map<String, Value>,
    proto::Directive,
    proto::Simulation,
    proto::ExternalLibrary
);
impl<T: Field> Field for Option<T> {
    fn field(&self, py: Python<'_>) -> PyResult<PyObject> {
        match self {
            Some(v) => v.field(py),
            None => Ok(py.None()),
        }
    }
}
impl<T: Field> Field for Vec<T> {
    fn field(&self, py: Python<'_>) -> PyResult<PyObject> {
        Ok(PyList::new(
            py,
            self.iter()
                .map(|v| v.field(py))
                .collect::<PyResult<Vec<_>>>()?,
        )?
        .into_any()
        .unbind())
    }
}
macro_rules! map_field {
    ($map:ty) => {
        impl<T: Field> Field for $map {
            fn field(&self, py: Python<'_>) -> PyResult<PyObject> {
                let d = PyDict::new(py);
                for (k, v) in self {
                    d.set_item(k, v.field(py)?)?;
                }
                Ok(d.into_any().unbind())
            }
        }
    };
}
map_field!(indexmap::IndexMap<String, T>);
map_field!(std::collections::BTreeMap<String, T>);

macro_rules! schema_class {
    ($name:ident, $core:ty, [$($field:ident),*], {$($extra:tt)*}) => {
        #[pyclass(module = "kfnetlist._native", frozen)]
        #[derive(Clone, Debug, Serialize, Deserialize)]
        #[serde(transparent)]
        pub struct $name(pub $core);
        impl Field for $core {
            fn field(&self, py: Python<'_>) -> PyResult<PyObject> {
                Ok(Py::new(py, $name(self.clone()))?.into_any())
            }
        }
        #[pymethods]
        impl $name {
            #[new]
            #[pyo3(signature = (**kwargs))]
            fn new(py: Python<'_>, kwargs: Option<&Bound<'_, PyDict>>) -> PyResult<Self> {
                let mut value = kwargs.map(|v| input_value(v.as_any())).transpose()?.unwrap_or_else(|| serde_json::json!({}));
                <Self as Legacy>::upgrade(py, &mut value)?;
                serde_json::from_value(value).map(Self).map_err(schema_error)
            }
            $(#[getter]
            fn $field(&self, py: Python<'_>) -> PyResult<PyObject> { self.0.$field.field(py) })*
            fn to_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> { to_py_dict(py, &self.0) }
            #[pyo3(signature = (*, mode="python"))]
            fn model_dump<'py>(&self, py: Python<'py>, mode: &str) -> PyResult<Bound<'py, PyAny>> {
                let _ = mode;
                self.to_dict(py)
            }
            fn to_json(&self) -> PyResult<String> { json_string(&self.0) }
            fn model_dump_json(&self) -> PyResult<String> { self.to_json() }
            #[classmethod]
            fn from_dict(cls: &Bound<'_, PyType>, obj: &Bound<'_, PyAny>) -> PyResult<Self> {
                let mut value = input_value(obj)?;
                <Self as Legacy>::upgrade(cls.py(), &mut value)?;
                serde_json::from_value(value).map(Self).map_err(schema_error)
            }
            #[classmethod]
            fn model_validate(cls: &Bound<'_, PyType>, obj: &Bound<'_, PyAny>) -> PyResult<Self> { Self::from_dict(cls, obj) }
            #[classmethod]
            fn from_json(cls: &Bound<'_, PyType>, data: &str) -> PyResult<Self> {
                let mut value = json_parse(data)?;
                <Self as Legacy>::upgrade(cls.py(), &mut value)?;
                serde_json::from_value(value).map(Self).map_err(schema_error)
            }
            #[classmethod]
            fn model_validate_json(cls: &Bound<'_, PyType>, data: &str) -> PyResult<Self> { Self::from_json(cls, data) }
            #[classmethod]
            fn __get_pydantic_core_schema__(cls: &Bound<'_, PyType>, _source_type: &Bound<'_, PyAny>, _handler: &Bound<'_, PyAny>) -> PyResult<PyObject> {
                crate::pydantic_core_schema(cls)
            }
            fn __eq__(&self, other: &Self) -> bool { self.0 == other.0 }
            fn __repr__(&self) -> PyResult<String> { Ok(format!("{}({})", stringify!($name), self.to_json()?)) }
            $($extra)*
        }
    };
}
macro_rules! proto_schema_class {
    ($name:ident, $core:ty, [$($field:ident),*], {$($extra:tt)*}) => {
        impl Legacy for $name {
            fn upgrade(py: Python<'_>, value: &mut Value) -> PyResult<()> {
                upgrade_with_warning(py, value)
            }
        }
        schema_class!($name, $core, [$($field),*], {
            fn to_proto<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
                PyBytes::new(py, &self.0.encode_to_vec())
            }
            #[classmethod]
            fn from_proto(_cls: &Bound<'_, PyType>, data: &[u8]) -> PyResult<Self> {
                <$core>::decode(data).map(Self).map_err(schema_error)
            }
            $($extra)*
        });
    };
}
proto_schema_class!(
    PrefixedValue,
    proto::PrefixedValue,
    [double_value, prefix],
    {}
);
proto_schema_class!(ParameterValue, proto::ParameterValue, [], {
    #[getter]
    fn prefixed_value(&self) -> Option<PrefixedValue> {
        match &self.0.value {
            Some(proto::parameter_value::Value::PrefixedValue(v)) => Some(PrefixedValue(*v)),
            _ => None,
        }
    }
    #[getter]
    fn model_ref(&self) -> Option<ModelReference> {
        match &self.0.value {
            Some(proto::parameter_value::Value::ModelRef(v)) => Some(ModelReference(v.clone())),
            _ => None,
        }
    }
});
proto_schema_class!(
    Parameter,
    proto::Parameter,
    [name, default_value, description, properties],
    {
        #[getter]
        fn uid(&self, py: Python<'_>) -> PyResult<u32> {
            Ok(legacy_property(py, &self.0.properties, "uid")?
                .parse()
                .unwrap_or(0))
        }
    }
);
proto_schema_class!(
    ModelInterface,
    proto::ModelInterface,
    [name, function_name, parameters, properties],
    {}
);
proto_schema_class!(
    ModelReference,
    proto::ModelReference,
    [model_interface_name, arguments],
    {}
);
proto_schema_class!(
    Terminal,
    proto::Terminal,
    [name, direction, domain, width, properties, discipline],
    {
        #[getter]
        fn uid(&self, py: Python<'_>) -> PyResult<u32> {
            Ok(legacy_property(py, &self.0.properties, "uid")?
                .parse()
                .unwrap_or(0))
        }
        #[getter]
        fn cross_section(&self, py: Python<'_>) -> PyResult<String> {
            legacy_property(py, &self.0.properties, "cross_section")
        }
    }
);
proto_schema_class!(
    TerminalReference,
    proto::TerminalReference,
    [instance_name, terminal_name],
    {}
);
proto_schema_class!(
    Connection,
    proto::Connection,
    [name, source, target, domain, weight, properties],
    {}
);
proto_schema_class!(
    Bus,
    proto::Bus,
    [name, width, domain, connections, properties],
    {}
);
proto_schema_class!(
    ExternalModule,
    proto::ExternalModule,
    [
        name,
        class_name,
        library_name,
        group_name,
        terminals,
        parameters,
        properties,
        kind
    ],
    {
        #[getter]
        fn domain(&self, py: Python<'_>) -> PyResult<String> {
            legacy_property(py, &self.0.properties, "domain")
        }
    }
);
proto_schema_class!(
    ProtoModuleReference,
    proto::ModuleReference,
    [name, module_name, class_name, parameters, properties],
    {
        #[getter]
        fn parameter_values(&self, py: Python<'_>) -> PyResult<PyObject> {
            crate::warn_deprecated(py, "`parameter_values` is deprecated; use `parameters`")?;
            self.0
                .parameters
                .iter()
                .filter(|p| p.name.is_empty())
                .filter_map(|p| p.default_value.clone())
                .collect::<Vec<_>>()
                .field(py)
        }
        #[getter]
        fn parameter_overrides<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
            crate::warn_deprecated(py, "`parameter_overrides` is deprecated; use `parameters`")?;
            let d = PyDict::new(py);
            for p in self.0.parameters.iter().filter(|p| !p.name.is_empty()) {
                d.set_item(&p.name, p.default_value.field(py)?)?;
            }
            Ok(d)
        }
    }
);
proto_schema_class!(
    ProtoModule,
    proto::Module,
    [
        name,
        class_name,
        terminals,
        parameters,
        model_interfaces,
        module_references,
        connections,
        buses,
        properties,
        directives
    ],
    {
        #[getter]
        fn uid(&self, py: Python<'_>) -> PyResult<u32> {
            Ok(legacy_property(py, &self.0.properties, "uid")?
                .parse()
                .unwrap_or(0))
        }
        #[getter]
        fn terminal(&self, py: Python<'_>) -> PyResult<PyObject> {
            crate::warn_deprecated(py, "`terminal` is deprecated; use `terminals`")?;
            self.0.terminals.field(py)
        }
    }
);
proto_schema_class!(
    ProtoCircuit,
    proto::Circuit,
    [
        name,
        top_module,
        modules,
        ext_modules,
        properties,
        directives,
        simulation,
        libraries
    ],
    {
        #[getter]
        fn domain(&self, py: Python<'_>) -> PyResult<String> {
            legacy_property(py, &self.0.properties, "domain")
        }
    }
);
impl Legacy for ArraySpec {}
impl Legacy for Instance {}
impl Legacy for Module {}
impl Legacy for TopLevelModule {}
schema_class!(ArraySpec, core::ArraySpec, [na, nb], {});
schema_class!(
    Instance,
    core::Instance,
    [component, settings, array, info],
    {}
);
schema_class!(
    Module,
    core::Module,
    [
        name,
        settings,
        info,
        instances,
        placements,
        ports,
        connections,
        nets,
        routes
    ],
    {
        fn to_netlist(&self) -> PyResult<crate::netlist::Netlist> {
            self.0
                .to_netlist()
                .map(crate::netlist::Netlist)
                .map_err(schema_error)
        }
        #[classmethod]
        fn from_netlist(
            _cls: &Bound<'_, PyType>,
            name: String,
            nl: &crate::netlist::Netlist,
        ) -> Self {
            Self(core::Module::from_netlist(name, &nl.0))
        }
    }
);
schema_class!(TopLevelModule, core::TopLevelModule, [modules, toplevel], {
    fn to_proto_circuit(&self) -> PyResult<ProtoCircuit> {
        self.0
            .to_proto_circuit()
            .map(ProtoCircuit)
            .map_err(schema_error)
    }
    #[classmethod]
    fn from_proto_circuit(_cls: &Bound<'_, PyType>, circuit: &ProtoCircuit) -> PyResult<Self> {
        core::TopLevelModule::from_proto_circuit(&circuit.0)
            .map(Self)
            .map_err(schema_error)
    }
    fn to_proto<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyBytes>> {
        Ok(PyBytes::new(py, &self.0.to_proto().map_err(schema_error)?))
    }
    #[classmethod]
    fn from_proto(_cls: &Bound<'_, PyType>, data: &[u8]) -> PyResult<Self> {
        core::TopLevelModule::from_proto(data)
            .map(Self)
            .map_err(schema_error)
    }
    fn to_yaml(&self) -> PyResult<String> {
        self.0.to_yaml().map_err(schema_error)
    }
    #[classmethod]
    fn from_yaml(_cls: &Bound<'_, PyType>, text: &str) -> PyResult<Self> {
        core::TopLevelModule::from_yaml(text)
            .map(Self)
            .map_err(schema_error)
    }
    fn to_netlists<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let result = PyDict::new(py);
        for (k, v) in self.0.to_netlists().map_err(schema_error)? {
            result.set_item(k, crate::netlist::Netlist(v))?;
        }
        Ok(result)
    }
    #[classmethod]
    #[pyo3(signature = (netlists, toplevel=None))]
    fn from_netlists(
        _cls: &Bound<'_, PyType>,
        netlists: &Bound<'_, PyDict>,
        toplevel: Option<String>,
    ) -> PyResult<Self> {
        let netlists = netlists
            .iter()
            .map(|(k, v)| {
                Ok((
                    k.extract()?,
                    v.extract::<PyRef<'_, crate::netlist::Netlist>>()?.0.clone(),
                ))
            })
            .collect::<PyResult<_>>()?;
        Ok(Self(core::TopLevelModule::from_netlists(
            &netlists, toplevel,
        )))
    }
});
#[allow(clippy::upper_case_acronyms)]
#[pyclass(module = "kfnetlist._native", eq, eq_int)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum TerminalDirection {
    INOUT = 0,
    INPUT = 1,
    OUTPUT = 2,
}
#[allow(clippy::upper_case_acronyms)]
#[pyclass(module = "kfnetlist._native", eq, eq_int)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SignalDomain {
    UNSPECIFIED = 0,
    ELECTRICAL = 1,
    WAVEGUIDE = 2,
}
#[allow(clippy::upper_case_acronyms)]
#[pyclass(module = "kfnetlist._native", eq, eq_int)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum SIPrefix {
    UNSPECIFIED = 0,
    QUECTO = 1,
    RONTO = 2,
    YOCTO = 3,
    ZEPTO = 4,
    ATTO = 5,
    FEMTO = 6,
    PICO = 7,
    NANO = 8,
    MICRO = 9,
    MILLI = 10,
    CENTI = 11,
    DECI = 12,
    DECA = 13,
    HECTO = 14,
    KILO = 15,
    MEGA = 16,
    GIGA = 17,
    TERA = 18,
    PETA = 19,
    EXA = 20,
    ZETTA = 21,
    YOTTA = 22,
    RONNA = 23,
    QUETTA = 24,
}
#[pyfunction]
pub fn load_pic_yaml(path: std::path::PathBuf) -> PyResult<TopLevelModule> {
    core::TopLevelModule::load_pic_yaml(path)
        .map(TopLevelModule)
        .map_err(schema_error)
}
pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PrefixedValue>()?;
    m.add_class::<ParameterValue>()?;
    m.add_class::<Parameter>()?;
    m.add_class::<ModelInterface>()?;
    m.add_class::<ModelReference>()?;
    m.add_class::<Terminal>()?;
    m.add_class::<TerminalReference>()?;
    m.add_class::<Connection>()?;
    m.add_class::<Bus>()?;
    m.add_class::<ExternalModule>()?;
    m.add_class::<ProtoModuleReference>()?;
    m.add_class::<ProtoModule>()?;
    m.add_class::<ProtoCircuit>()?;
    m.add_class::<ArraySpec>()?;
    m.add_class::<Instance>()?;
    m.add_class::<Module>()?;
    m.add_class::<TopLevelModule>()?;
    m.add_class::<TerminalDirection>()?;
    m.add_class::<SignalDomain>()?;
    m.add_class::<SIPrefix>()?;
    m.add_function(wrap_pyfunction!(load_pic_yaml, m)?)?;
    Ok(())
}
