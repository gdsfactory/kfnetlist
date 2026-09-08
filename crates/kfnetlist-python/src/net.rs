use pyo3::basic::CompareOp;
use pyo3::exceptions::{PyIndexError, PyTypeError};
use pyo3::prelude::*;
use pyo3::types::{PyList, PyType};
use serde::{Deserialize, Serialize};

use crate::port::{NetlistPort, PortArrayRef, PortArrayRefData, PortArrayRefPython, PortRef};
use crate::{cmp_to_py, from_py_any, hash64, json_parse, json_string, richcmp_result, to_py_dict};

pub(crate) use kfnetlist_core::NetMember;
pub(crate) trait NetMemberPython: Sized {
    fn into_py_obj<'py>(self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>>;
    fn from_py(obj: &Bound<'_, PyAny>) -> PyResult<Self>;
}

impl NetMemberPython for NetMember {
    fn into_py_obj<'py>(self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        Ok(match self {
            NetMember::Port(p) => Py::new(py, NetlistPort(p))?.into_any().into_bound(py),
            NetMember::Ref(r) => Py::new(py, PortRef(r))?.into_any().into_bound(py),
            NetMember::ArrayRef(d) => d.into_py(py)?.into_any().into_bound(py),
        })
    }

    fn from_py(obj: &Bound<'_, PyAny>) -> PyResult<Self> {
        // PortArrayRef must be checked before PortRef because it inherits
        // from it.
        if let Ok(b) = obj.downcast::<PortArrayRef>() {
            Ok(NetMember::ArrayRef(PortArrayRefData::from_py(b)))
        } else if let Ok(b) = obj.downcast::<PortRef>() {
            Ok(NetMember::Ref(b.borrow().0.clone()))
        } else if let Ok(b) = obj.downcast::<NetlistPort>() {
            Ok(NetMember::Port(b.borrow().0.clone()))
        } else {
            Err(PyTypeError::new_err(
                "expected NetlistPort, PortRef, or PortArrayRef",
            ))
        }
    }
}

/// A net: an unordered collection of port members that share electrical
/// connectivity. Internally stored sorted by (kind, fields) for stable
/// equality and hashing.
#[pyclass(module = "kfnetlist._native")]
#[derive(Clone, Debug, Hash, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(transparent)]
pub struct Net(pub kfnetlist_core::Net);
crate::core_wrapper!(Net, kfnetlist_core::Net);

impl Net {
    pub(crate) fn from_members(members: Vec<NetMember>) -> Self {
        Self(kfnetlist_core::Net::from_members(members))
    }

    fn extract_members(obj: Option<&Bound<'_, PyAny>>) -> PyResult<Vec<NetMember>> {
        let Some(obj) = obj else {
            return Ok(Vec::new());
        };
        if obj.is_none() {
            return Ok(Vec::new());
        }
        let mut out = Vec::new();
        let iter = obj.try_iter()?;
        for item in iter {
            let item = item?;
            out.push(NetMember::from_py(&item)?);
        }
        Ok(out)
    }
}

#[pymethods]
impl Net {
    #[new]
    #[pyo3(signature = (members=None))]
    fn new(members: Option<&Bound<'_, PyAny>>) -> PyResult<Self> {
        let members = Self::extract_members(members)?;
        Ok(Net::from_members(members))
    }

    fn __len__(&self) -> usize {
        self.members.len()
    }

    fn __iter__(slf: PyRef<'_, Self>) -> PyResult<Py<NetIter>> {
        let py = slf.py();
        let mut objs: Vec<PyObject> = Vec::with_capacity(slf.members.len());
        for m in &slf.members {
            objs.push(m.clone().into_py_obj(py)?.unbind());
        }
        Py::new(
            py,
            NetIter {
                items: objs.into_iter(),
            },
        )
    }

    fn __getitem__<'py>(&self, py: Python<'py>, idx: isize) -> PyResult<Bound<'py, PyAny>> {
        let n = self.members.len() as isize;
        let i = if idx < 0 { idx + n } else { idx };
        if i < 0 || i >= n {
            return Err(PyIndexError::new_err("net index out of range"));
        }
        self.members[i as usize].clone().into_py_obj(py)
    }

    fn __contains__(&self, item: &Bound<'_, PyAny>) -> PyResult<bool> {
        let needle = NetMember::from_py(item)?;
        Ok(self.members.iter().any(|m| m == &needle))
    }

    fn __hash__(&self) -> u64 {
        hash64(&self.members)
    }

    fn __richcmp__(&self, other: &Bound<'_, PyAny>, op: CompareOp) -> PyResult<PyObject> {
        let py = other.py();
        let Ok(other) = other.downcast::<Net>() else {
            return Ok(py.NotImplemented());
        };
        let other = other.borrow();
        let eq = self == &*other;
        let lt = self < &*other;
        Ok(richcmp_result(py, Some(cmp_to_py(op, lt, eq))))
    }

    fn __repr__<'py>(&self, py: Python<'py>) -> PyResult<String> {
        let mut parts = Vec::with_capacity(self.members.len());
        for m in &self.members {
            let bound = m.clone().into_py_obj(py)?;
            parts.push(bound.repr()?.to_string());
        }
        Ok(format!("Net([{}])", parts.join(", ")))
    }

    fn sort(&mut self) {
        self.sort_in_place();
    }

    fn append(&mut self, item: &Bound<'_, PyAny>) -> PyResult<()> {
        self.members.push(NetMember::from_py(item)?);
        self.sort_in_place();
        Ok(())
    }

    fn extend(&mut self, items: &Bound<'_, PyAny>) -> PyResult<()> {
        let iter = items.try_iter()?;
        for item in iter {
            let item = item?;
            self.members.push(NetMember::from_py(&item)?);
        }
        self.sort_in_place();
        Ok(())
    }

    /// Return a fresh Python list containing the members.
    fn members<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyList>> {
        let list = PyList::empty(py);
        for m in &self.members {
            list.append(m.clone().into_py_obj(py)?)?;
        }
        Ok(list)
    }

    #[classmethod]
    fn __get_pydantic_core_schema__(
        cls: &Bound<'_, PyType>,
        _source_type: &Bound<'_, PyAny>,
        _handler: &Bound<'_, PyAny>,
    ) -> PyResult<PyObject> {
        crate::pydantic_core_schema(cls)
    }

    fn to_json(&self) -> PyResult<String> {
        json_string(self)
    }

    #[classmethod]
    fn from_json(_cls: &Bound<'_, PyType>, data: &str) -> PyResult<Self> {
        let mut net: Net = json_parse(data)?;
        net.sort_in_place();
        Ok(net)
    }

    fn to_dict<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyAny>> {
        to_py_dict(py, self)
    }

    #[classmethod]
    fn from_dict(_cls: &Bound<'_, PyType>, obj: &Bound<'_, PyAny>) -> PyResult<Self> {
        let mut net: Net = from_py_any(obj)?;
        net.sort_in_place();
        Ok(net)
    }
}

#[pyclass(module = "kfnetlist._native")]
pub struct NetIter {
    items: std::vec::IntoIter<PyObject>,
}

#[pymethods]
impl NetIter {
    fn __iter__(slf: PyRef<'_, Self>) -> PyRef<'_, Self> {
        slf
    }

    fn __next__(mut slf: PyRefMut<'_, Self>) -> Option<PyObject> {
        slf.items.next()
    }
}
