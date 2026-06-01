use serde::Serialize;
use std::fmt::Write;

#[derive(Debug, Clone, Default, Serialize)]
pub struct ReportDatabase {
    pub description: String,
    pub original_file: String,
    pub generator: String,
    pub top_cell: String,
    pub tags: Vec<Tag>,
    pub categories: Vec<Category>,
    pub cells: Vec<Cell>,
    pub items: Vec<Item>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Tag {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Category {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub description: Option<String>,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub categories: Vec<Category>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Cell {
    pub name: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub variant: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub struct Item {
    pub category: String,
    pub cell: String,
    pub values: Vec<Value>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tags: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub multiplicity: Option<u32>,
    #[serde(skip_serializing_if = "std::ops::Not::not")]
    pub visited: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub comment: Option<String>,
}

#[derive(Debug, Clone, Serialize)]
pub enum Value {
    Text(String),
    Box {
        x1: f64,
        y1: f64,
        x2: f64,
        y2: f64,
    },
    Polygon(Vec<(f64, f64)>),
    Edge {
        x1: f64,
        y1: f64,
        x2: f64,
        y2: f64,
    },
    Point {
        x: f64,
        y: f64,
    },
}

impl Value {
    fn to_rdb_string(&self) -> String {
        match self {
            Value::Text(s) => {
                if s.contains(' ') {
                    let escaped = s.replace('\'', "\\'");
                    format!("text: '{escaped}'")
                } else {
                    format!("text: {s}")
                }
            }
            Value::Box { x1, y1, x2, y2 } => format!("box: ({x1},{y1};{x2},{y2})"),
            Value::Polygon(pts) => {
                let pts_str: Vec<String> = pts.iter().map(|(x, y)| format!("{x},{y}")).collect();
                format!("polygon: ({})", pts_str.join(";"))
            }
            Value::Edge { x1, y1, x2, y2 } => format!("edge: ({x1},{y1};{x2},{y2})"),
            Value::Point { x, y } => format!(
                "polygon: ({},{};{},{};{},{};{},{})",
                x - 0.001,
                y - 0.001,
                x - 0.001,
                y + 0.001,
                x + 0.001,
                y + 0.001,
                x + 0.001,
                y - 0.001,
            ),
        }
    }
}

impl ReportDatabase {
    pub fn new(description: impl Into<String>) -> Self {
        Self {
            description: description.into(),
            generator: "kfnetlist".to_string(),
            ..Default::default()
        }
    }

    #[must_use]
    pub fn with_top_cell(mut self, top_cell: impl Into<String>) -> Self {
        self.top_cell = top_cell.into();
        self
    }

    pub fn add_category(&mut self, category: Category) {
        self.categories.push(category);
    }

    pub fn add_cell(&mut self, name: impl Into<String>) {
        self.cells.push(Cell {
            name: name.into(),
            variant: None,
        });
    }

    pub fn add_item(&mut self, item: Item) {
        self.items.push(item);
    }

    #[must_use]
    pub fn to_lyrdb(&self) -> String {
        let mut xml = String::new();
        writeln!(xml, r#"<?xml version="1.0" encoding="utf-8"?>"#).unwrap();
        writeln!(xml, "<report-database>").unwrap();

        writeln!(
            xml,
            " <description>{}</description>",
            escape_xml(&self.description)
        )
        .unwrap();
        writeln!(
            xml,
            " <original-file>{}</original-file>",
            escape_xml(&self.original_file)
        )
        .unwrap();
        writeln!(
            xml,
            " <generator>{}</generator>",
            escape_xml(&self.generator)
        )
        .unwrap();
        writeln!(xml, " <top-cell>{}</top-cell>", escape_xml(&self.top_cell)).unwrap();

        writeln!(xml, " <tags>").unwrap();
        for tag in &self.tags {
            write!(xml, "  <tag>").unwrap();
            write!(xml, "<name>{}</name>", escape_xml(&tag.name)).unwrap();
            if let Some(desc) = &tag.description {
                write!(xml, "<description>{}</description>", escape_xml(desc)).unwrap();
            }
            writeln!(xml, "</tag>").unwrap();
        }
        writeln!(xml, " </tags>").unwrap();

        writeln!(xml, " <categories>").unwrap();
        for cat in &self.categories {
            write_category(&mut xml, cat, 2);
        }
        writeln!(xml, " </categories>").unwrap();

        writeln!(xml, " <cells>").unwrap();
        for cell in &self.cells {
            write!(xml, "  <cell>").unwrap();
            write!(xml, "<name>{}</name>", escape_xml(&cell.name)).unwrap();
            if let Some(variant) = &cell.variant {
                write!(xml, "<variant>{}</variant>", escape_xml(variant)).unwrap();
            }
            writeln!(xml, "</cell>").unwrap();
        }
        writeln!(xml, " </cells>").unwrap();

        writeln!(xml, " <items>").unwrap();
        for item in &self.items {
            writeln!(xml, "  <item>").unwrap();
            if let Some(tags) = &item.tags {
                writeln!(xml, "   <tags>{}</tags>", escape_xml(tags)).unwrap();
            }
            writeln!(
                xml,
                "   <category>{}</category>",
                escape_xml(&item.category)
            )
            .unwrap();
            writeln!(xml, "   <cell>{}</cell>", escape_xml(&item.cell)).unwrap();
            if item.visited {
                writeln!(xml, "   <visited>true</visited>").unwrap();
            }
            if let Some(mult) = item.multiplicity {
                writeln!(xml, "   <multiplicity>{mult}</multiplicity>").unwrap();
            }
            if let Some(comment) = &item.comment {
                writeln!(xml, "   <comment>{}</comment>", escape_xml(comment)).unwrap();
            }
            writeln!(xml, "   <values>").unwrap();
            for value in &item.values {
                writeln!(
                    xml,
                    "    <value>{}</value>",
                    escape_xml(&value.to_rdb_string())
                )
                .unwrap();
            }
            writeln!(xml, "   </values>").unwrap();
            writeln!(xml, "  </item>").unwrap();
        }
        writeln!(xml, " </items>").unwrap();

        writeln!(xml, "</report-database>").unwrap();
        xml
    }
}

#[must_use]
pub fn include_from_rdb(xml: &str, paths: &[String]) -> String {
    filter_rdb(xml, |path| paths.iter().any(|q| matches_path(path, q)))
}

#[must_use]
pub fn exclude_from_rdb(xml: &str, paths: &[String]) -> String {
    filter_rdb(xml, |path| !paths.iter().any(|q| matches_path(path, q)))
}

pub fn filter_rdb(xml: &str, mut keep: impl FnMut(&str) -> bool) -> String {
    let Some(items_open_idx) = xml.find("<items>") else {
        return xml.to_string();
    };
    let inner_start = items_open_idx + "<items>".len();
    let Some(items_close_rel) = xml[inner_start..].find("</items>") else {
        return xml.to_string();
    };
    let inner_end = inner_start + items_close_rel;

    let mut out = String::with_capacity(xml.len());
    out.push_str(&xml[..inner_start]);

    let inner = &xml[inner_start..inner_end];
    let mut cursor = 0;
    while cursor < inner.len() {
        let Some(open_rel) = inner[cursor..].find("<item>") else {
            out.push_str(&inner[cursor..]);
            break;
        };
        let item_start = cursor + open_rel;
        let Some(close_rel) = inner[item_start..].find("</item>") else {
            out.push_str(&inner[cursor..]);
            break;
        };
        let item_end = item_start + close_rel + "</item>".len();

        let path = extract_inner_text(&inner[item_start..item_end], "category").unwrap_or("");

        if keep(path) {
            out.push_str(&inner[cursor..item_end]);
        }
        cursor = item_end;
    }
    out.push_str(&xml[inner_end..]);
    out
}

fn matches_path(path: &str, query: &str) -> bool {
    if path == query {
        return true;
    }
    path.len() > query.len() && path.as_bytes()[query.len()] == b'.' && path.starts_with(query)
}

fn extract_inner_text<'a>(xml: &'a str, tag: &str) -> Option<&'a str> {
    let open = format!("<{tag}>");
    let close = format!("</{tag}>");
    let start = xml.find(&open)? + open.len();
    let end_rel = xml[start..].find(&close)?;
    Some(&xml[start..start + end_rel])
}

fn write_category(xml: &mut String, cat: &Category, indent: usize) {
    let pad = " ".repeat(indent);
    writeln!(xml, "{pad}<category>").unwrap();
    writeln!(xml, "{} <name>{}</name>", pad, escape_xml(&cat.name)).unwrap();
    if let Some(desc) = &cat.description {
        writeln!(
            xml,
            "{} <description>{}</description>",
            pad,
            escape_xml(desc)
        )
        .unwrap();
    }
    if !cat.categories.is_empty() {
        writeln!(xml, "{pad} <categories>").unwrap();
        for sub in &cat.categories {
            write_category(xml, sub, indent + 2);
        }
        writeln!(xml, "{pad} </categories>").unwrap();
    }
    writeln!(xml, "{pad}</category>").unwrap();
}

fn escape_xml(s: &str) -> String {
    s.replace('&', "&amp;")
        .replace('<', "&lt;")
        .replace('>', "&gt;")
        .replace('"', "&quot;")
        .replace('\'', "&apos;")
}

impl Item {
    pub fn new(category: impl Into<String>, cell: impl Into<String>) -> Self {
        Self {
            category: category.into(),
            cell: cell.into(),
            values: Vec::new(),
            tags: None,
            multiplicity: None,
            visited: false,
            comment: None,
        }
    }

    #[must_use]
    pub fn with_comment(mut self, comment: impl Into<String>) -> Self {
        self.comment = Some(comment.into());
        self
    }

    #[must_use]
    pub fn with_text(mut self, text: impl Into<String>) -> Self {
        self.values.push(Value::Text(text.into()));
        self
    }

    #[must_use]
    pub fn with_tag(mut self, tag: impl Into<String>) -> Self {
        self.tags = Some(tag.into());
        self
    }

    #[must_use]
    pub fn with_edge(mut self, x1: f64, y1: f64, x2: f64, y2: f64) -> Self {
        self.values.push(Value::Edge { x1, y1, x2, y2 });
        self
    }

    #[must_use]
    pub fn with_point(mut self, x: f64, y: f64) -> Self {
        self.values.push(Value::Point { x, y });
        self
    }

    #[must_use]
    pub fn with_box(mut self, x1: f64, y1: f64, x2: f64, y2: f64) -> Self {
        self.values.push(Value::Box { x1, y1, x2, y2 });
        self
    }

    #[must_use]
    pub fn with_polygon(mut self, points: Vec<(f64, f64)>) -> Self {
        self.values.push(Value::Polygon(points));
        self
    }
}

impl Category {
    pub fn new(name: impl Into<String>) -> Self {
        Self {
            name: name.into(),
            description: None,
            categories: Vec::new(),
        }
    }

    #[must_use]
    pub fn with_description(mut self, desc: impl Into<String>) -> Self {
        self.description = Some(desc.into());
        self
    }

    #[must_use]
    pub fn with_subcategory(mut self, sub: Category) -> Self {
        self.categories.push(sub);
        self
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_simple_report() {
        let mut rdb = ReportDatabase::new("LVS Results").with_top_cell("top");

        rdb.add_category(
            Category::new("LVS")
                .with_description("LVS Errors")
                .with_subcategory(Category::new("instance").with_description("Instance mismatches"))
                .with_subcategory(Category::new("net").with_description("Net mismatches"))
                .with_subcategory(Category::new("port").with_description("Port mismatches")),
        );

        rdb.add_cell("top");

        rdb.add_item(Item::new("LVS.instance", "top").with_text("Missing instance: mmi1 (mmi1x2)"));

        let xml = rdb.to_lyrdb();
        assert!(xml.contains("<report-database>"));
        assert!(xml.contains("LVS Results"));
        assert!(xml.contains("Missing instance: mmi1"));
    }

    #[test]
    fn test_value_formats() {
        let item = Item::new("LVS.open", "top")
            .with_text("Open port")
            .with_point(25.5, 0.625);
        assert_eq!(item.values[0].to_rdb_string(), "text: 'Open port'");
        assert_eq!(
            item.values[1].to_rdb_string(),
            "polygon: (25.499,0.624;25.499,0.626;25.501,0.626;25.501,0.624)"
        );
    }

    fn build_two_item_db() -> ReportDatabase {
        let mut db = ReportDatabase::new("LVS").with_top_cell("top");
        db.add_category(
            Category::new("LVS")
                .with_subcategory(Category::new("short"))
                .with_subcategory(
                    Category::new("net").with_subcategory(Category::new("missing_in_schematic")),
                ),
        );
        db.add_cell("top");
        db.add_item(Item::new("LVS.short", "top").with_text("Short"));
        db.add_item(Item::new("LVS.net.missing_in_schematic", "top").with_text("Net mismatch"));
        db
    }

    fn count_items_with_category(xml: &str, path: &str) -> usize {
        let target = format!("<category>{path}</category>");
        let Some(items_start) = xml.find("<items>") else {
            return 0;
        };
        let Some(items_end) = xml.find("</items>") else {
            return 0;
        };
        let items = &xml[items_start..items_end];
        items.matches(&target).count()
    }

    #[test]
    fn test_include_from_rdb_exact() {
        let xml = build_two_item_db().to_lyrdb();
        let kept = include_from_rdb(&xml, &["LVS.short".into()]);
        assert_eq!(count_items_with_category(&kept, "LVS.short"), 1);
        assert_eq!(
            count_items_with_category(&kept, "LVS.net.missing_in_schematic"),
            0
        );
    }

    #[test]
    fn test_include_from_rdb_prefix() {
        let xml = build_two_item_db().to_lyrdb();
        let kept = include_from_rdb(&xml, &["LVS.net".into()]);
        assert_eq!(count_items_with_category(&kept, "LVS.short"), 0);
        assert_eq!(
            count_items_with_category(&kept, "LVS.net.missing_in_schematic"),
            1
        );
    }

    #[test]
    fn test_exclude_from_rdb() {
        let xml = build_two_item_db().to_lyrdb();
        let kept = exclude_from_rdb(&xml, &["LVS.short".into()]);
        assert_eq!(count_items_with_category(&kept, "LVS.short"), 0);
        assert_eq!(
            count_items_with_category(&kept, "LVS.net.missing_in_schematic"),
            1
        );
    }

    #[test]
    fn test_dot_boundary_no_false_match() {
        let mut db = ReportDatabase::new("LVS").with_top_cell("top");
        db.add_category(Category::new("LVS").with_subcategory(Category::new("network")));
        db.add_cell("top");
        db.add_item(Item::new("LVS.network", "top").with_text("nw"));
        let xml = db.to_lyrdb();
        let kept = include_from_rdb(&xml, &["LVS.net".into()]);
        assert_eq!(count_items_with_category(&kept, "LVS.network"), 0);
    }

    #[test]
    fn test_filter_preserves_non_item_content() {
        let xml = build_two_item_db().to_lyrdb();
        let kept = include_from_rdb(&xml, &["LVS.short".into()]);
        assert!(kept.contains("<top-cell>top</top-cell>"));
        assert!(kept.contains("<categories>"));
        assert!(kept.contains("<cells>"));
    }

    #[test]
    fn test_include_empty_drops_all() {
        let xml = build_two_item_db().to_lyrdb();
        let kept = include_from_rdb(&xml, &[]);
        assert_eq!(count_items_with_category(&kept, "LVS.short"), 0);
        assert_eq!(
            count_items_with_category(&kept, "LVS.net.missing_in_schematic"),
            0
        );
    }

    #[test]
    fn test_exclude_empty_keeps_all() {
        let xml = build_two_item_db().to_lyrdb();
        let kept = exclude_from_rdb(&xml, &[]);
        assert_eq!(count_items_with_category(&kept, "LVS.short"), 1);
        assert_eq!(
            count_items_with_category(&kept, "LVS.net.missing_in_schematic"),
            1
        );
    }

    #[test]
    fn test_text_quoting() {
        assert_eq!(Value::Text("Word".into()).to_rdb_string(), "text: Word");
        assert_eq!(
            Value::Text("Multi word string".into()).to_rdb_string(),
            "text: 'Multi word string'"
        );
        assert_eq!(
            Value::Text("Has 'quotes' inside".into()).to_rdb_string(),
            "text: 'Has \\'quotes\\' inside'"
        );
    }
}
