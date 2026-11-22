fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("cargo:rerun-if-changed=proto/circuit.proto");
    println!("cargo:rerun-if-changed=proto/simulation.proto");
    println!("cargo:rerun-if-changed=proto/value.proto");
    prost_build::Config::new()
        .protoc_executable(protoc_bin_vendored::protoc_bin_path()?)
        .btree_map(["."])
        .type_attribute(".", "#[derive(serde::Serialize, serde::Deserialize)]")
        .message_attribute("circuit.ParameterValue", "#[serde(try_from = \"super::ParameterValueWire\", into = \"super::ParameterValueWire\")] ")
        .message_attribute("circuit.Expression", "#[serde(try_from = \"super::ExpressionWire\", into = \"super::ExpressionWire\")] ")
        .message_attribute(".", "#[serde(default, deny_unknown_fields)]")
        .enum_attribute("circuit.ParameterValue.value", "#[serde(rename_all = \"snake_case\")]")
        .field_attribute("circuit.TerminalReference.terminal_name", "#[serde(alias = \"Terminal_name\")]")
        .field_attribute("circuit.Circuit.terminals", "#[serde(alias = \"terminal\")]")
        .field_attribute("circuit.Circuit.macros", "#[serde(skip_serializing_if = \"Vec::is_empty\")]")
        .field_attribute("circuit.Netlist.macros", "#[serde(skip_serializing_if = \"Vec::is_empty\")]")
        .field_attribute("circuit.Simulation.stimuli", "#[serde(skip_serializing_if = \"Vec::is_empty\")]")
        .field_attribute("circuit.Waveform.file", "#[serde(skip_serializing_if = \"String::is_empty\")]")
        .compile_protos(&["proto/circuit.proto", "proto/simulation.proto", "proto/value.proto"], &["proto"])?;
    Ok(())
}
