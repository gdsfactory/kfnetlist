"""Tests for the RDB (Report Database) module — lyrdb XML filtering via Rust."""

import pytest

from kfnetlist import LvsError, exclude_from_rdb_xml, filter_rdb_xml, include_from_rdb_xml

SAMPLE_XML = """\
<?xml version="1.0" encoding="utf-8"?>
<report-database>
 <description>LVS</description>
 <original-file></original-file>
 <generator>kfnetlist</generator>
 <top-cell>top</top-cell>
 <tags>
 </tags>
 <categories>
  <category>
   <name>LVS</name>
   <categories>
    <category>
     <name>short</name>
    </category>
    <category>
     <name>net</name>
     <categories>
      <category>
       <name>missing_in_schematic</name>
      </category>
     </categories>
    </category>
    <category>
     <name>open</name>
    </category>
   </categories>
  </category>
 </categories>
 <cells>
  <cell><name>top</name></cell>
 </cells>
 <items>
  <item>
   <category>LVS.short</category>
   <cell>top</cell>
   <values>
    <value>text: &apos;VDD shorted to VSS&apos;</value>
   </values>
  </item>
  <item>
   <category>LVS.net.missing_in_schematic</category>
   <cell>top</cell>
   <values>
    <value>text: &apos;splitter_1,o2 &lt;-&gt; combiner_1,o1&apos;</value>
   </values>
  </item>
  <item>
   <category>LVS.open</category>
   <cell>top</cell>
   <values>
    <value>text: &apos;Dangling port: clk&apos;</value>
   </values>
  </item>
 </items>
</report-database>
"""


def _count_items(xml: str, category: str) -> int:
    target = f"<category>{category}</category>"
    items_start = xml.find("<items>")
    items_end = xml.find("</items>")
    return xml[items_start:items_end].count(target)


class TestIncludeFromRdb:
    def test_exact_match(self):
        result = include_from_rdb_xml(SAMPLE_XML, ["LVS.short"])
        assert _count_items(result, "LVS.short") == 1
        assert _count_items(result, "LVS.net.missing_in_schematic") == 0
        assert _count_items(result, "LVS.open") == 0

    def test_prefix_match(self):
        result = include_from_rdb_xml(SAMPLE_XML, ["LVS.net"])
        assert _count_items(result, "LVS.short") == 0
        assert _count_items(result, "LVS.net.missing_in_schematic") == 1
        assert _count_items(result, "LVS.open") == 0

    def test_multiple_paths(self):
        result = include_from_rdb_xml(SAMPLE_XML, ["LVS.short", "LVS.open"])
        assert _count_items(result, "LVS.short") == 1
        assert _count_items(result, "LVS.net.missing_in_schematic") == 0
        assert _count_items(result, "LVS.open") == 1

    def test_empty_paths_drops_all(self):
        result = include_from_rdb_xml(SAMPLE_XML, [])
        assert _count_items(result, "LVS.short") == 0
        assert _count_items(result, "LVS.net.missing_in_schematic") == 0
        assert _count_items(result, "LVS.open") == 0

    def test_preserves_non_item_content(self):
        result = include_from_rdb_xml(SAMPLE_XML, ["LVS.short"])
        assert "<top-cell>top</top-cell>" in result
        assert "<categories>" in result
        assert "<cells>" in result


class TestExcludeFromRdb:
    def test_exact_match(self):
        result = exclude_from_rdb_xml(SAMPLE_XML, ["LVS.short"])
        assert _count_items(result, "LVS.short") == 0
        assert _count_items(result, "LVS.net.missing_in_schematic") == 1
        assert _count_items(result, "LVS.open") == 1

    def test_prefix_match(self):
        result = exclude_from_rdb_xml(SAMPLE_XML, ["LVS.net"])
        assert _count_items(result, "LVS.short") == 1
        assert _count_items(result, "LVS.net.missing_in_schematic") == 0
        assert _count_items(result, "LVS.open") == 1

    def test_empty_paths_keeps_all(self):
        result = exclude_from_rdb_xml(SAMPLE_XML, [])
        assert _count_items(result, "LVS.short") == 1
        assert _count_items(result, "LVS.net.missing_in_schematic") == 1
        assert _count_items(result, "LVS.open") == 1


class TestFilterRdb:
    def test_predicate(self):
        result = filter_rdb_xml(SAMPLE_XML, lambda p: p == "LVS.open")
        assert _count_items(result, "LVS.short") == 0
        assert _count_items(result, "LVS.net.missing_in_schematic") == 0
        assert _count_items(result, "LVS.open") == 1

    def test_predicate_error_propagates(self):
        def bad_predicate(path: str) -> bool:
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            filter_rdb_xml(SAMPLE_XML, bad_predicate)


class TestDotBoundarySemantics:
    def test_no_false_prefix_match(self):
        xml = SAMPLE_XML.replace("LVS.net.missing_in_schematic", "LVS.network")
        result = include_from_rdb_xml(xml, ["LVS.net"])
        assert _count_items(result, "LVS.network") == 0


class TestLvsErrorEnum:
    def test_values(self):
        assert LvsError.SHORT == "LVS.short"
        assert LvsError.OPEN == "LVS.open"
        assert LvsError.NET_MISSING_IN_LAYOUT == "LVS.net.missing_in_layout"
        assert LvsError.INSTANCE_COMPONENT_MISMATCH == "LVS.instance.component_mismatch"

    def test_usable_with_include(self):
        result = include_from_rdb_xml(SAMPLE_XML, [LvsError.SHORT])
        assert _count_items(result, "LVS.short") == 1
        assert _count_items(result, "LVS.open") == 0

    def test_usable_with_exclude(self):
        result = exclude_from_rdb_xml(SAMPLE_XML, [LvsError.SHORT, LvsError.OPEN])
        assert _count_items(result, "LVS.short") == 0
        assert _count_items(result, "LVS.open") == 0
        assert _count_items(result, "LVS.net.missing_in_schematic") == 1
