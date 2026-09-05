"""kighmu_license_v3.py - Remplace install2.py:3447 LICENSE_SECRET (symétrique) par Ed25519 asymétrique
À importer dans install2.py v3. Ne contient QUE la clé publique.
"""
import hashlib, hmac, pathlib
from datetime import date

# === COLLE ICI LA SORTIE DE 01_gen_keys.py ===
VK_PUB_HEX = "06d24678802bb97565406d7301db48a5968118bc18c768fcfd447bfca48b430f"  # EXEMPLE - REMPLACE
# Ne JAMAIS coller la clé privée ici

try:
    from nacl.signing import VerifyKey
    from nacl.exceptions import BadSignatureError
    _VK = VerifyKey(bytes.fromhex(VK_PUB_HEX))
    HAS_NACL = True
except Exception:
    HAS_NACL = False
    _VK = None

def _pack_license_token_v3(key: str, expiry: str) -> str:
    """Côté VENTES seulement - signe avec clé privée (ne pas inclure dans binaire)"""
    from nacl.signing import SigningKey
    sk = SigningKey(open("/etc/ventes/ed25519.sk", "rb").read())
    msg = f"{key}|{expiry}".encode()
    sig = sk.sign(msg).signature.hex()
    return f"{key}|{expiry}|{sig}"

def _unpack_license_token_v3(raw: str):
    """Côté CLIENT (install2.bin) - vérifie avec clé publique seule"""
    if not HAS_NACL or _VK is None:
        return None, None
    parts = raw.strip().split("|")
    if len(parts) != 3:
        return None, None
    key, expiry, sig_hex = parts
    msg = f"{key}|{expiry}".encode()
    try:
        sig = bytes.fromhex(sig_hex)
        _VK.verify(msg, sig)
        return key, expiry
    except BadSignatureError:
        return None, None
    except Exception:
        return None, None

def _verify_token_sig_v3(key: str, expiry: str, sig_hex: str) -> bool:
    """Vérif rapide"""
    if not HAS_NACL:
        return False
    try:
        _VK.verify(f"{key}|{expiry}".encode(), bytes.fromhex(sig_hex))
        return True
    except Exception:
        return False

# Compat: garde l'ancien HMAC pour migration douce 30j
_LICENSE_SECRET_OLD = hashlib.sha256(b"KighmuPanel2026!@#LicenseBombSecureKey_X7k9m2").hexdigest()
def _unpack_legacy(raw: str):
    parts = raw.strip().split("|")
    if len(parts) < 3:
        return None, None
    sig = parts[-1]
    msg = "|".join(parts[:-1])
    exp = hmac.new(_LICENSE_SECRET_OLD.encode(), msg.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, exp):
        return None, None
    return parts[0], parts[1]
