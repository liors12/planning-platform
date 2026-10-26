fn main() {
    // tauri-build reads STATIC_VCRUNTIME but does not ask Cargo to rerun when
    // it changes, so a cached build script would keep linking the VC++ runtime
    // dynamically after the flag was set (v0.2.4).
    println!("cargo:rerun-if-env-changed=STATIC_VCRUNTIME");
    tauri_build::build()
}
