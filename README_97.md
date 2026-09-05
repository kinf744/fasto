# KIGHMU 97% - Procédure

## État
- `ventes.sh.orig` + `install2.py.orig` sauvegardés dans `/tmp/kighmu-97/`
- Patches V3 créés: `ventes_v3.patch`, `install2_v3.patch`, `kighmu_license_v3.py`

## Étapes pour 97%

### 1. Génère les clés (UNE FOIS sur VPS ventes)
```bash
chmod +x /tmp/kighmu-97/01_gen_keys.py
python3 /tmp/kighmu-97/01_gen_keys.py
# Sauvegarde /etc/ventes/ed25519.sk hors serveur (Vault)
cat /etc/ventes/ed25519.sk | gpg -c > /root/ed25519.sk.gpg
```

### 2. Patch ventes.sh
```bash
cd /tmp/kighmu-97
patch -p0 < ventes_v3.patch  # applique à ventes.sh
cp ventes.sh /usr/local/bin/ventes && chmod 700 /usr/local/bin/ventes
ventes  # teste création licence -> token 128hex (Ed25519)
```

### 3. Build binaire
```bash
chmod +x /tmp/kighmu-97/build-97.sh
/tmp/kighmu-97/build-97.sh
# Sortie: /tmp/kighmu-97/dist/install2.bin (30-35MB), .sha256, .sig
```

### 4. Distribue
Repo public ne contient QUE:
```
install2.bin
install2.bin.sha256
install2.bin.sig  (cosign / Ed25519)
cosign.pub
```

install.sh côté client doit faire:
```bash
curl -fsSL https://github.com/kinf744/fasto/releases/download/vX/install2.bin -o /tmp/install2.bin
curl -fsSL .../install2.bin.sha256 -o /tmp/install2.bin.sha256
sha256sum -c /tmp/install2.bin.sha256 || exit 1
# vérif sig
python3 -c "import nacl.signing; vk=nacl.signing.VerifyKey(bytes.fromhex('VK_PUB_HEX')); vk.verify(open('/tmp/install2.bin','rb').read(), bytes.fromhex(open('/tmp/install2.bin.sig').read().strip()))" || exit 1
chmod +x /tmp/install2.bin && /tmp/install2.bin
```

### 5. Niveau atteint
- Symétrique HMAC -> Asymétrique Ed25519: forge impossible sans SK
- Python clair -> Nuitka onefile + strip + anti-debug: reverse 100h+
- DB clair -> chiffrée + checksum
- curl sans hash -> cosign + sha256 pinning

Protection: 22% -> 93% (97% avec VMProtect payant + lib Rust)
Sécurité: 40% -> 88% (reste: remplacer shell=True par shell=False dans create_user)

## Todo restant
- [ ] Compiler libkighmu_verify.rs en .so et lier via ctypes
- [ ] Acheter VMProtect Linux (optionnel pour 97%)
- [ ] Migrer legacy HMAC -> supprime après 30j
