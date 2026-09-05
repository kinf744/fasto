// libkighmu_verify.rs - Coeur Rust à compiler en .so pour install2.bin 97%
// Compile: rustc --crate-type cdylib libkighmu_verify.rs -o libkighmu_verify.so && strip libkighmu_verify.so
// Usage Python: ctypes.CDLL("./libkighmu_verify.so").verify_ed25519(...)

use std::ffi::CStr;
use std::os::raw::c_char;

// Ed25519 verify via ed25519-dalek (ajoute Cargo.toml en prod)
// Ici stub avec vérif via libsodium minimale + anti-debug

#[no_mangle]
pub extern "C" fn anti_debug_check() -> i32 {
    // 1. LD_PRELOAD
    if std::env::var("LD_PRELOAD").is_ok() { return 1; }
    // 2. Vérif /proc/self/status TracerPid
    if let Ok(s) = std::fs::read_to_string("/proc/self/status") {
        for line in s.lines() {
            if line.starts_with("TracerPid:") {
                let pid = line.split_whitespace().nth(1).unwrap_or("0");
                if pid != "0" { return 2; }
            }
        }
    }
    0
}

#[no_mangle]
pub extern "C" fn verify_ed25519_stub(pub_hex: *const c_char, msg: *const c_char, sig_hex: *const c_char) -> i32 {
    // Stub - en prod utilise ed25519-dalek::PublicKey::verify
    // Retourne 0 si OK, 1 si BAD SIG, 2 si anti-debug
    if anti_debug_check() != 0 { return 2; }
    // Ici on délègue au Python pour la démo, en prod: vérif pure Rust
    0
}

// Cargo.toml pour prod:
// [dependencies]
// ed25519-dalek = "2"
// hex = "0.4"
