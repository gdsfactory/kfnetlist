// Synthetic 2x2 photonic switch: the bit-level patterns of a real switch
// netlist (simulation-view types, empty #(), instance arrays, concatenations,
// bit-selects of bus ports), with none of its content.
`define SEL_MSB 3
`ifdef IS_SIM
typedef struct { real re; real im; } connection;
typedef logic mzmselect;
`endif

module SWITCH_2X2 #() (
`ifdef IS_SIM
  input connection in [1:0],
  output connection out [1:0],
  input mzmselect sel [`SEL_MSB:0]
`else
  input wire [1:0] in,
  output wire [1:0] out,
  input wire [`SEL_MSB:0] sel
`endif
);
`ifdef IS_SIM
  connection a [3:0];
`else
  wire [3:0] a;
`endif
  MZM_1X2 I_I[1:0] (.in0(in), .out0({a[2], a[0]}), .out1({a[3], a[1]}), .sel(sel[1:0]));
  MZM_2X1 I_O[1:0] (.in0(a[1:0]), .in1(a[3:2]), .out0(out), .sel(sel[3:2]));
endmodule
