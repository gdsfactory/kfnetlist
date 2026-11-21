//! File paths in netlists, the same on every OS (and the same as Python's
//! `kfnetlist.morphnet.netlist.paths`).
//!
//! The stored form is POSIX (`data/w.txt`): `\` and `/` both separate, `.` and `..`
//! resolve lexically (no filesystem, no symlinks), and `/x`, `C:/x`, `C:\x` and
//! `\\server\share` are absolute on every host. A relative path stays relative
//! unless a `base` is given. Callers make a `std::path::PathBuf` from the result.

/// `(root, rest)`: `//` (UNC), `C:` / `C:/` (drive), `/` or `""`.
fn split(text: &str) -> (String, String) {
    let text = text.replace('\\', "/");
    if let Some(rest) = text.strip_prefix("//") {
        return ("//".into(), rest.into());
    }
    let bytes = text.as_bytes();
    if bytes.len() >= 2 && bytes[0].is_ascii_alphabetic() && bytes[1] == b':' {
        let (root, rest) = text.split_at(2);
        return match rest.strip_prefix('/') {
            Some(rest) => (format!("{root}/"), rest.into()),
            None => (root.into(), rest.into()),
        };
    }
    match text.strip_prefix('/') {
        Some(rest) => ("/".into(), rest.into()),
        None => (String::new(), text),
    }
}

/// `path` in the stored form: POSIX separators, `.`/`..` resolved.
pub fn posix_file(path: &str) -> String {
    let (root, rest) = split(path);
    let mut parts: Vec<&str> = Vec::new();
    for seg in rest.split('/') {
        match seg {
            "" | "." => {}
            ".." if parts.last().is_some_and(|p| *p != "..") => {
                parts.pop();
            }
            ".." if !root.is_empty() => {} // above a root: dropped
            seg => parts.push(seg),
        }
    }
    let out = root + &parts.join("/");
    if out.is_empty() {
        ".".into()
    } else {
        out
    }
}

/// `/x`, `//server/share`, `C:/x` (either separator) on every host.
pub fn is_absolute(path: &str) -> bool {
    let (root, _) = split(path);
    root == "/" || root == "//" || root.ends_with(":/")
}

/// `path` joined to `base` when relative, in the stored form.
pub fn resolve_file(path: &str, base: Option<&str>) -> String {
    match base {
        Some(base) if !is_absolute(path) => posix_file(&format!("{base}/{path}")),
        _ => posix_file(path),
    }
}
