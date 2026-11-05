fn main() -> Result<(), Box<dyn std::error::Error>> {
    println!("cargo:rerun-if-changed=proto/circuit.proto");
    println!("cargo:rerun-if-changed=proto/simulation.proto");
    prost_build::Config::new()
        .protoc_executable(protoc_bin_vendored::protoc_bin_path()?)
        .btree_map(["."])
        .type_attribute(".", "#[derive(serde::Serialize, serde::Deserialize)]")
        .message_attribute("circuit.ParameterValue", "#[serde(try_from = \"super::ParameterValueWire\", into = \"super::ParameterValueWire\")] ")
        .message_attribute(".", "#[serde(default, deny_unknown_fields)]")
        .enum_attribute("circuit.ParameterValue.value", "#[serde(rename_all = \"snake_case\")]")
        .field_attribute("circuit.TerminalReference.terminal_name", "#[serde(alias = \"Terminal_name\")]")
        .field_attribute("circuit.Module.terminals", "#[serde(alias = \"terminal\")]")
        .compile_protos(&["proto/circuit.proto", "proto/simulation.proto"], &["proto"])?;
    Ok(())
}
