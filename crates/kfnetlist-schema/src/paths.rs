//! File paths in netlists, the same on every OS (and the same as Python's
//! `kfnetlist.morphnet.netlist.paths`).
//!
//! The stored form is POSIX (`data/w.txt`): `\` and `/` both separate, `.` and `..`
//! resolve lexically (no filesystem, no symlinks), and `/x`, `C:/x`, `C:\x`, `C:x`
//! and `\\server\share` are absolute on every host; `..` never climbs above a
//! root (a drive, a share, `/`). A relative path stays relative
//! unless a `base` is given. Callers make a `std::path::PathBuf` from the result.

/// `(root, rest)`. Every root is absolute: `//server/share/` (UNC: `..` stops at
/// the share), `C:/` (a drive letter is that drive's root, also in `C:rel`), `/`
/// (one, or three or more, slashes); `""` for a relative path.
fn split(text: &str) -> (String, String) {
    let text = text.replace('\\', "/");
    if text.starts_with("//") && !text.starts_with("///") {
        let (server, rest) = text[2..].split_once('/').unwrap_or((&text[2..], ""));
        let (share, rest) = rest.split_once('/').unwrap_or((rest, ""));
        let root = if share.is_empty() {
            format!("//{server}/")
        } else {
            format!("//{server}/{share}/")
        };
        return (root, rest.into());
    }
    let bytes = text.as_bytes();
    if bytes.len() >= 2 && bytes[0].is_ascii_alphabetic() && bytes[1] == b':' {
        return (
            format!("{}/", &text[..2]),
            text[2..].trim_start_matches('/').into(),
        );
    }
    if text.starts_with('/') {
        return ("/".into(), text.trim_start_matches('/').into());
    }
    (String::new(), text)
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

/// `/x`, `//server/share`, `C:/x`, `C:x` (either separator) on every host.
pub fn is_absolute(path: &str) -> bool {
    !split(path).0.is_empty()
}

/// `path` joined to `base` when relative, in the stored form.
pub fn resolve_file(path: &str, base: Option<&str>) -> String {
    match base {
        // an empty base (`Path::new("deck.sp").parent()`) is no base
        Some(base) if !base.is_empty() && !is_absolute(path) => {
            posix_file(&format!("{base}/{path}"))
        }
        _ => posix_file(path),
    }
}
