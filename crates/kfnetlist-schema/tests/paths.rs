//! One OS-agnostic path resolver, the same answers as Python's (shared case table).

use kfnetlist_schema::paths::{is_absolute, posix_file, resolve_file};
use serde_json::Value;

const CASES: &str = include_str!("../../../tests/data/path_cases.json");

#[test]
fn the_shared_path_cases() {
    let cases: Vec<Value> = serde_json::from_str(CASES).unwrap();
    assert!(!cases.is_empty());
    for case in cases {
        let file = case["file"].as_str().unwrap();
        let base = case["base"].as_str();
        assert_eq!(posix_file(file), case["posix"].as_str().unwrap(), "{file}");
        assert_eq!(
            is_absolute(file),
            case["absolute"].as_bool().unwrap(),
            "{file}"
        );
        assert_eq!(
            resolve_file(file, base),
            case["resolved"].as_str().unwrap(),
            "{file} from {base:?}"
        );
    }
}
