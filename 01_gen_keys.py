#!/usr/bin/env python3
"""Génère paire Ed25519 pour VENTES v3 -> install2.bin v3
Usage: python3 01_gen_keys.py
Sortie: /etc/ventes/ed25519.sk (600) et ed25519.vk + VK_PUB_HEX à coller dans install2.py
"""
import os, pathlib
from nacl.signing import SigningKey

DB_DIR = pathlib.Path("/etc/ventes")
SK_PATH = DB_DIR / "ed25519.sk"
VK_PATH = DB_DIR / "ed25519.vk"

DB_DIR.mkdir(parents=True, exist_ok=True)
if SK_PATH.exists():
    print(f"[!] {SK_PATH} existe déjà - ne jamais régénérer (toutes les licences invalides)")
    sk = SigningKey(open(SK_PATH, "rb").read())
    vk = sk.verify_key
else:
    sk = SigningKey.generate()
    vk = sk.verify_key
    SK_PATH.write_bytes(sk.encode())
    VK_PATH.write_bytes(vk.encode())
    os.chmod(SK_PATH, 0o600)
    os.chmod(VK_PATH, 0o644)
    print(f"[+] Clé privée générée: {SK_PATH} (600) - SAUVEGARDE IMMÉDIATE")
    print(f"[+] Clé publique: {VK_PATH}")

vk_hex = vk.encode().hex()
print(f"\nVK_PUB_HEX = \"{vk_hex}\"")
print(f"\nÀ coller dans install2.py:3425:")
print(f'VK_PUB_HEX = "{vk_hex}"  # 32 bytes Ed25519 verify key')
print(f"\nTest sign/verify:")
msg = b"test-key|2027-01-01"
sig = sk.sign(msg).signature
assert vk.verify(msg, sig) == msg
print("  OK - sign/verify fonctionne")
print(f"\nCommande ventes.sh pour signer:")
print(f'  echo -n "$key|$expiry" | python3 -c "import nacl.signing; sk=nacl.signing.SigningKey(open(\"/etc/ventes/ed25519.sk\",\"rb\").read()); import sys; print(sk.sign(sys.stdin.buffer.read()).signature.hex())"')
