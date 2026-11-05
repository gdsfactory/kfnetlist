from kfnetlist.morphnet.morphnet_schema import AnalysisKind, OutputRequestKind
from kfnetlist.morphnet.netlist.xyce.parser import parse_xyce


class TestXyceSimulationParsing:
    def test_print_tran(self) -> None:
        text = """\
.print TRAN V(out)
.end
"""
        netlist = parse_xyce(text)
        assert netlist.simulation is not None
        req = netlist.simulation.output_requests[0]
        assert req.kind == OutputRequestKind.PRINT
        assert req.analysis_type == "TRAN"
        assert req.variables == ["V(out)"]

    def test_tran_analysis(self) -> None:
        text = """\
.tran 0 10u
.end
"""
        netlist = parse_xyce(text)
        assert netlist.simulation is not None
        a = netlist.simulation.analyses[0]
        assert a.kind == AnalysisKind.TRAN

    def test_xyce_with_brace_expr(self) -> None:
        text = """\
.tran 0 {tstop}
.end
"""
        netlist = parse_xyce(text)
        assert netlist.simulation is not None
        a = netlist.simulation.analyses[0]
        assert a.kind == AnalysisKind.TRAN
        assert "{tstop}" in a.arguments

    def test_dc_analysis(self) -> None:
        text = """\
.dc VDD 0 1.8 0.01
.end
"""
        netlist = parse_xyce(text)
        assert netlist.simulation is not None
        a = netlist.simulation.analyses[0]
        assert a.kind == AnalysisKind.DC

    def test_ic_statement(self) -> None:
        text = """\
.ic V(out)=0
.end
"""
        netlist = parse_xyce(text)
        assert netlist.simulation is not None
        ic = netlist.simulation.initial_conditions
        assert ic is not None
        assert ic.conditions["V(out)"] == "0"

    def test_full_xyce_netlist(self) -> None:
        text = """\
.subckt res a b PARAMS: r=1k
R1 a b {r}
.ends res
X1 in out res r=10k
.dc X1:r 1k 100k 1k
.print DC V(out)
.end
"""
        netlist = parse_xyce(text)
        assert netlist.simulation is not None
        assert len(netlist.simulation.analyses) == 1
        assert len(netlist.simulation.output_requests) == 1
