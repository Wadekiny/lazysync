fn main() -> Result<(), Box<dyn std::error::Error>> {
    let proto_path = "../proto/lazysync.proto";
    println!("cargo:rerun-if-changed={}", proto_path);
    let protoc = protoc_bin_vendored::protoc_bin_path()
        .map_err(|err| format!("Failed to locate vendored protoc: {}", err))?;
    std::env::set_var("PROTOC", protoc);
    tonic_build::configure()
        .compile(&[proto_path], &["../proto"])?;
    Ok(())
}
