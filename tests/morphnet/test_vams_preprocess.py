import pytest

from kfnetlist.morphnet.netlist.vams.preprocess import preprocess_vams


class TestCommentStripping:
    def test_block_comment(self) -> None:
        text = "/* comment */\nmodule test (a); endmodule\n"
        result = preprocess_vams(text)
        assert "comment" not in result.text
        assert "module test" in result.text

    def test_line_comment(self) -> None:
        text = "module test (a); // inline\nendmodule\n"
        result = preprocess_vams(text)
        assert "inline" not in result.text
        assert "module test" in result.text

    def test_multiline_block_comment(self) -> None:
        text = "module test (a);\n/* multi\nline\ncomment */\nendmodule\n"
        result = preprocess_vams(text)
        assert "multi" not in result.text


class TestDirectiveExtraction:
    def test_include(self) -> None:
        text = '`include "models.vams"\nmodule test (a); endmodule\n'
        result = preprocess_vams(text)
        assert ("include", '"models.vams"') in result.directives
        assert "`include" not in result.text

    def test_define(self) -> None:
        text = "`define PI 3.14159\nmodule test (a); endmodule\n"
        result = preprocess_vams(text)
        assert ("define", "PI 3.14159") in result.directives

    def test_timescale(self) -> None:
        text = "`timescale 1ns/1ps\nmodule test (a); endmodule\n"
        result = preprocess_vams(text)
        assert ("timescale", "1ns/1ps") in result.directives


class TestAnalogBlockReplacement:
    def test_analog_begin_end(self) -> None:
        text = "module test (a);\nanalog begin\n  V(a) <+ 1.0;\nend\nendmodule\n"
        result = preprocess_vams(text)
        assert "__analog_placeholder__" in result.text
        assert len(result.analog_blocks) == 1
        assert "V(a)" in result.analog_blocks[0]

    def test_analog_single_statement(self) -> None:
        text = "module test (a);\nanalog V(a) <+ 1.0;\nendmodule\n"
        result = preprocess_vams(text)
        assert "__analog_placeholder__" in result.text
        assert len(result.analog_blocks) == 1

    def test_nested_begin_end(self) -> None:
        text = "module test (a);\nanalog begin\n  begin\n    V(a) <+ 1.0;\n  end\nend\nendmodule\n"
        result = preprocess_vams(text)
        assert len(result.analog_blocks) == 1
        assert "begin" in result.analog_blocks[0]


class TestConditionals:
    TEXT = """\
`ifdef SIM
module sim (a); endmodule
`elsif FAST
module fast (a); endmodule
`else
module plain (a); endmodule
`endif
`ifndef SIM
`define W 3
`endif
module m (a); input [`W:0] a; endmodule
"""

    def test_else_branch_without_defines(self) -> None:
        text = preprocess_vams(self.TEXT).text
        assert "module plain" in text
        assert "module sim" not in text and "module fast" not in text
        assert "input [3:0] a;" in text

    def test_defines_select_branches(self) -> None:
        assert "module sim" in preprocess_vams(self.TEXT, {"SIM": "1"}).text
        fast = preprocess_vams(self.TEXT, {"FAST": ""}).text
        assert "module fast" in fast and "module plain" not in fast

    def test_nested_inactive_branch_stays_inactive(self) -> None:
        text = "`ifdef A\n`ifdef B\nx;\n`else\ny;\n`endif\n`endif\nz;\n"
        assert preprocess_vams(text).text == "z;\n"

    def test_unbalanced_raises(self) -> None:
        with pytest.raises(ValueError, match="without `endif"):
            preprocess_vams("`ifdef A\nmodule m (a); endmodule\n")
        with pytest.raises(ValueError, match="`else without"):
            preprocess_vams("`else\n")
