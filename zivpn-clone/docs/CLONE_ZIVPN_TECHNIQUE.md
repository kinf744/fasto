# Clonage du binaire zivpn — Méthodologie complète

**Date :** 2026-08-16
**Objectif :** reproduire fonctionnellement le binaire propriétaire `/usr/local/bin/zivpn` (tunnel UDP, v1.5.0) à partir de la source upstream Hysteria 2, sans disposer du code source du fork.
**Résultat :** clone fonctionnel, interopérable, installé en production sur le VPS.

---

## 1. Contexte et contraintes

Le binaire zivpn est un fork fermé (non publié) de **Hysteria 2** (`github.com/apernet/hysteria`). Il n'existe pas de source disponible pour le fork lui-même. La seule référence exploitable est le **binaire compilé**.

Le défi : retrouver, dans le binaire compilé, l'ensemble des modifications apportées par le fork par rapport à l'upstream, puis les rejouer sur une base source connue.

Outillage utilisé :
- **GoReSym** : dump des symboles Go (noms de fonctions, adresses virtuelles de départ).
- **radare2 (r2)** : désassemblage ciblé des fonctions identifiées.
- **Python** (scripts ad hoc) : recherche de chaînes, calculs d'adresses, lecture binaire.
- **Go 1.22** : compilation du clone.

---

## 2. Étape 1 — Analyse statique du binaire

### 2.1 Extraction des symboles

```
GoReSym /usr/local/bin/zivpn > /tmp/opencode/zivpn_full.txt
```

Le dump contient, pour chaque symbole : `Name` (chemin complet du package + fonction), `Start` (adresse virtuelle GoReSym).

### 2.2 Décalage d'adresses GoReSym → adresses réelles

Le binaire est **non-PIE** (adresses virtuelles fixes). Le décalage entre l'adresse GoReSym et l'adresse réelle dans le fichier est :

```
adresse réelle = adresse GoReSym − 0x72d3e0
```

Ce décalage est constant et a été validé sur plusieurs symboles (les adresses réelles pointent bien vers du code cohérent).

### 2.3 Sections ELF

- `.text` : VA `0x401000`, offset fichier `0x1000`
- `.rodata` : VA `0x90b000`, offset fichier `0x50b000`
- VA → offset fichier = VA − `0x400000`

---

## 3. Étape 2 — Identification de la base source exacte

Le point le plus critique : trouver **quel commit upstream** sert de base au fork. Une erreur ici invalide tout.

### 3.1 Méthode : la version de quic-go

La version de `github.com/quic-go/quic-go` est **unique à chaque période** et se retrouve dans le binaire (build info). Le binaire contient :

```
github.com/quic-go/quic-go v0.40.1-0.20231112225043-e7f3af208dee
```

Cette version `v0.40.1-0.20231112225043-...` (pseudo-version de **novembre 2023**) correspond exactement au `go.mod` du commit `405572d` (2023-12-08) d'Hysteria 2.

**Attention** : une piste erronée (string `app/v2.12.1` dans les logs) a d'abord orienté vers la version 2026 ; elle a été invalidée car la string n'existe pas dans le binaire et la version quic-go est incompatible. Le buildinfo (GoVersion `go1.21.4`, Path `github.com/apernet/hysteria/app`, json5 v0.1.1) confirme `405572d`.

### 3.2 Vérifications croisées

- `quic-go v0.40.1-0.2023...` présent dans le binaire **et** dans le `go.mod` de `405572d`. ✅
- `yosuke-furukawa/json5 v0.1.1` présent dans le binaire **et** dans le `go.mod` de `405572d`. ✅
- Pas de string `app/v2.12.1` dans le binaire. ✅

**Conclusion : base = commit `405572d` (2023-12-08).**

---

## 4. Étape 3 — Cartographie du handshake (protocole auth)

### 4.1 Fonctions identifiées (GoReSym → réel)

| Fonction | Adresse réelle | Références internes |
|---|---|---|
| `protocol.AuthRequestFromHeader` | `0x8b4ca0` | `Zivpnudp-Auth` @ `0x8b4cda`, `Zivpnudp-CC-RX` @ `0x8b4cb3` |
| `protocol.AuthRequestToHeader` | `0x8b4d20` | `Zivpnudp-Auth` @ `0x8b4d5b`, `Zivpnudp-CC-RX` @ `0x8b4e26`, `Zivpnudp-Padding` @ `0x8b4ef5` |
| `protocol.AuthResponseFromHeader` | `0x8b4fe0` | `Zivpnudp-UDP` @ `0x8b4ff7`, `Zivpnudp-CC-RX` @ `0x8b50c3` |
| `protocol.AuthResponseToHeader` | `0x8b5140` | `Zivpnudp-UDP` @ `0x8b5195`, `Zivpnudp-CC-RX` @ `0x8b525d`/`0x8b5316`, `Zivpnudp-Padding` @ `0x8b53f0` |
| `protocol.padding.String` | `0x8b54e0` | — |
| `protocol.ReadTCPRequest`/`WriteTCPRequest` | `0x8b55c0`/`0x8b5820` | — |
| `protocol.ReadTCPResponse`/`WriteTCPResponse` | `0x8b5be0`/`0x8b5f20` | — |
| `protocol.(*UDPMessage).Serialize`/`ParseUDPMessage` | `0x8b6500`/`0x8b6800` | — |

### 4.2 Découverte : les 4 headers renommés

Le fork renomme les headers HTTP/3 du handshake :

| Upstream | zivpn |
|---|---|
| `Hysteria-Auth` | `Zivpnudp-Auth` |
| `Hysteria-UDP` | `Zivpnudp-UDP` |
| `Hysteria-CC-RX` | `Zivpnudp-CC-RX` |
| `Hysteria-Padding` | `Zivpnudp-Padding` |

Localisation des chaînes .rodata : `Zivpnudp-UDP` `0xa31da9`, `Zivpnudp-Auth` `0xa324e9`, `Zivpnudp-CC-RX` `0xa32ba2`, `Zivpnudp-Padding` `0xa33aab`.

### 4.3 Découverte : `URLHost = "zivpnudp"`

Au-delà des headers, le **Host** de la requête d'auth est aussi renommé : `hysteria` → `zivpnudp`.

Cette découverte a été **validée empiriquement** : un client utilisant `Host: hysteria` reçoit `HTTP status code: 404` du serveur officiel ; avec `Host: zivpnudp`, l'auth passe.

### 4.4 Structure du handshake (inchangée par rapport à l'upstream)

- URL : `/auth`
- Méthode HTTP/3
- Statut de succès : `233`
- Padding alphanumérique : `256–2048` (auth), `64–512` (TCP request), `128–1024` (TCP response)
- `Zivpnudp-UDP` = `"true"`/`"false"` (`test bl,bl` @ `0x8b516e`, strings `"true"` @ `0xa2ea6c`, `"false"` @ `0xa2ed5c`)
- `Zivpnudp-CC-RX` = débit en bps ou `"auto"` (bandwidth detection)

### 4.5 Motif assembleur d'écriture d'un header

```
lea rax, [string]      ; ex. 0x8b4d5b pour Zivpnudp-Auth
call 0x6ed280          ; construction Go string
lea rax, [0x95ac40]    ; ptr → http.Header
call 0x410580          ; accès map
call 0x46aac0          ; h.Set(key, value)
```

---

## 5. Étape 4 — L'obfs « zivpn » = Salamander + PSK fixe

### 5.1 Découverte de la PSK

Le champ config `obfs: "zivpn"` (ou `obfs: {"type": "zivpn"}`) est en réalité une **obfs Salamander standard** avec une **PSK fixe embarquée** dans le binaire :

```
PSK = hu``hqb`c      (9 octets)
```

Repérée dans le code serveur :
```
movabs rcx, 0x6062716860607568   ; "hu``hqb" (little-endian)
mov    byte [rax+8], 0x63        ; 'c' final
mov    ebx, 9                    ; longueur 9
```
à `0x905e30`, juste avant `call 0x8e65e0` (`NewSalamanderObfuscator` appelé à `0x905e49`).

### 5.2 Le serveur force Salamander

Le type `obfs` de la config n'est **jamais comparé par nom** (la string n'existe pas dans le .rodata du binaire). Le serveur **force toujours** Salamander avec la PSK fixe, quel que soit le champ `obfs` de la config.

### 5.3 Le client accepte la PSK en clair

La PSK `hu``hqb`c` contient des backticks — c'est la cause du bug client (voir §7).

---

## 6. Étape 5 — Configuration serveur

### 6.1 Format de config (Hysteria 1-like)

La config de production réelle (`/etc/zivpn/config.json`) utilise un format proche de Hysteria 1 :

```json
{
  "listen": ":5667",
  "cert": "/etc/zivpn/zivpn.crt",
  "key": "/etc/zivpn/zivpn.key",
  "obfs": "zivpn",
  "recv_window_conn": 15728640,
  "recv_window_client": 67108864,
  "disable_mtu_discovery": false,
  "max_conn_client": 4096,
  "exclude_port": [53, 5300, 4466, 36712, 20000],
  "auth": {
    "mode": "passwords",
    "config": ["George34", "ip9090"]
  }
}
```

Points clés :
- **`cert`/`key` à la racine** (pas sous `tls` comme en Hysteria 2).
- `recv_window_conn`, `exclude_port`, etc. sont **ignorés** par le binaire (absents de ses chaînes) — vestiges d'un format plus ancien.
- Le serveur lit le **contenu** du fichier de config et le parse en **JSON5** (`yosuke-furukawa/json5` v0.1.1).
- `obfs` accepté en **string** (`"zivpn"`) ou **objet** (`{"type": "zivpn"}`).

### 6.2 `auth.mode` étendu

`fillAuthenticator` (@ `0x906a60`) supporte les modes : `password`, `passwords` (liste), `userpass`, `http`, `https`, `command`/`cmd`.

### 6.3 Détails du chargement TLS

Le check `empty cert or key path` (Field `zivpn_udp`) est émis lorsque les chemins cert/key sont absents **ou** lorsque le fichier est illisible/non-PEM (le binaire lit le fichier et vérifie son contenu).

**Artefact viper** : le check dépend du répertoire de travail (`WorkingDirectory=/etc/zivpn` dans l'unit systemd) — les chemins relatifs sont résolus par viper.

---

## 7. Étape 6 — Le bug client : kill-switch `signature`

### 7.1 Le kill-switch

`runClient` (@ `0x904320`) exige :
```go
signature := viper.GetString("signature")
if len(signature) != 9 || signature != "hu``hqb`c" {
    logger.Fatal("wtf!!!No Idea")   // string @ 0xa31fa1
}
```

Le flag `--signature` n'existe **pas** dans le binaire → `viper.GetString("signature")` retourne toujours `""` → **le client officiel ne peut jamais démarrer**.

### 7.2 Le bug de parse json5

Après le kill-switch, le client fait :
```go
configRaw := viper.GetString("config")
json5.Unmarshal([]byte(configRaw), &config)
```

Or `viper.GetString("config")` retourne le **chemin** du fichier (`-c`), **pas son contenu** (le flag `config` est bindé à viper). Conséquences observées, identiques au binaire officiel :
- Sans `-c` : `GetString("config")` = `""` → `unexpected end of JSON input`
- Avec `-c /chemin/vers/config.json` : json5 parse le chemin → `invalid character 't' in comment` (le `/t` de `/tmp`)

**Résultat : le client officiel zivpn est totalement inutilisable — par design.**

---

## 8. Étape 7 — Reconstruction du clone

### 8.1 Création de la base de travail

```
git worktree add /root/tuo/clone-zivpn 405572d
```

### 8.2 Modifications appliquées

**Protocole** (`core/internal/protocol/http.go`) :
- `URLHost = "hysteria"` → `"zivpnudp"`
- `RequestHeaderAuth = "Zivpnudp-Auth"`, `ResponseHeaderUDPEnabled = "Zivpnudp-UDP"`, `CommonHeaderCCRX = "Zivpnudp-CC-RX"`, `CommonHeaderPadding = "Zivpnudp-Padding"`

**Brutal** (`core/internal/congestion/brutal/brutal.go`) :
- `debugEnv = "ZIVPN_UDP_BRUTAL_DEBUG"` (au lieu de `HYSTERIA_BRUTAL_DEBUG`)

**CLI** (`app/cmd/root.go`) :
- `Use: "zivpnudp"` (au lieu de `"hysteria"`)
- Env vars : `ZIVPN_LOG_LEVEL`, `ZIVPN_LOG_FORMAT`, `ZIVPN_ACME_DIR`
- Chemins config : `$HOME/.zivpn`, `/etc/zivpn/`
- Logo `"UDP tunneling from ZIVPN"`, format version 3 champs (`Version:\t%s\nBuildDate:\t%s\nAuthors:\t%s`)
- Flag `--signature` (présent dans le clone pour permettre les tests, absent du binaire)
- Help cobra court-circuité (affiche seulement le Short/Long)

**Suppressions** (`app/cmd/update.go`, `app/cmd/version.go`) :
- Commandes `check-update`, `version`, flag `--disable-update-check` (absents du binaire)

**Client** (`app/cmd/client.go`, `app/cmd/ping.go`) :
- Kill-switch `signature` (len 9, == `hu``hqb`c`, sinon FATAL `wtf!!!No Idea`)
- Config lue via `viper.GetString("config")` + `json5.Unmarshal`
- Message d'erreur `Failed to parse client configuration`

**Serveur** (`app/cmd/server.go`) :
- `fillConn` : force Salamander avec PSK `"hu``hqb`c"` (ignore `c.Obfs.Type`)
- Config lue via `viper.GetString("config")` + `json5.Unmarshal`
- Champs `Cert`/`Key` racine (format Hysteria 1), fallback `tls`
- `auth.mode` : `passwords` supporté via `extras/auth/passwords.go` (nouveau `PasswordsAuthenticator`)
- Type `serverConfigObfs` avec `UnmarshalJSON` acceptant string ou objet
- Field d'erreur `zivpn_udp` (au lieu de `tls`)

**Dépendance** (`app/go.mod`) : + `github.com/yosuke-furukawa/json5 v0.1.1`

### 8.3 Compilation

```bash
cd /root/tuo/clone-zivpn && go build -o /tmp/opencode/zivpn-clone-test ./app
```

> Le binaire officiel est compilé en `go1.21.4`, le clone en `go1.22` → les tailles diffèrent (11.3 Mo vs 22.3 Mo) et certaines optimisations (ex. inline des constantes string en `movabs` vs string .rodata) diffèrent. **C'est un clone fonctionnel, pas un clone byte-identique.**

---

## 9. Étape 8 — Validation

### 9.1 Fidélité des comportements client (identiques mot pour mot)

| Scénario | Binaire officiel | Clone |
|---|---|---|
| `client -c <fichier>` sans signature | `wtf!!!No Idea` | `wtf!!!No Idea` ✅ |
| `client --signature=hu\`\`hqb\`c -c <fichier>` | `Failed to parse client configuration` / `invalid character 't' in comment` | identique ✅ |
| `client --signature=...` sans `-c` | `unexpected end of JSON input` | identique ✅ |

### 9.2 Fidélité des comportements serveur

- `--help` → `UDP tunneling from ZIVPN` + `Version:\t1.5.0\nBuildDate:\t...\nAuthors:\tZI` ✅
- `client --help` → `Run as client mode` ; `server --help` → `Server mode` ✅
- Accepte la config de prod exacte (`cert`/`key` racine, `obfs` string, `auth.mode passwords`) ✅

### 9.3 Interopérabilité (testée contre le serveur réel de production)

Client de test (fork Hysteria avec les modifs zivpn) → serveur :
- Serveur **officiel** prod (`:5667`) : `connected to server`, UDP enabled, auth OK ✅
- Serveur **clone** (`:5668` puis prod) : `connected to server` ✅

L'interop est bidirectionnelle et prouve que le clone parle exactement le protocole zivpn.

### 9.4 Vérification des signatures binaires

Toutes les chaînes clés présentes dans le clone : `Zivpnudp-Auth`, `Zivpnudp-UDP`, `Zivpnudp-CC-RX`, `Zivpnudp-Padding`, `wtf!!!No Idea`, `ping mode`, `ZIVPN_UDP_BRUTAL_DEBUG`, `ZIVPN_LOG_LEVEL`, `zivpnudp`, `UDP tunneling from ZIVPN`, `Version:\t%s\nBuildDate:\t%s\nAuthors:\t%s`.

Seule exception : `hu``hqb`c` — inline par le compilateur go1.22 (présente dans le code, pas comme string .rodata isolée). Sans impact fonctionnel.

---

## 10. Étape 9 — Mise en production

### 10.1 Sauvegarde du binaire officiel

```bash
cp -p /usr/local/bin/zivpn /root/tuo/zivpn.official.bak
md5sum /usr/local/bin/zivpn   # 7c69b556b31b527ae7748c71a95a70d0
```

Double sauvegarde : `/root/tuo/zivpn.official.bak` + `/tmp/opencode/zivpn.official.bak`.

### 10.2 Incident découvert pendant le déploiement

Le premier essai d'installation échoue : le clone ne démarre pas avec la config prod (`empty cert or key path`). Cause : le clone (Hysteria 2) attendait `tls: {cert, key}`, la config prod utilise `cert`/`key` **à la racine**. Corrigé en ajoutant les champs racine + priorité dans `fillTLSConfig` (voir §8.2 serveur).

### 10.3 Remplacement et validation

```bash
systemctl stop zivpn.service
cp /tmp/opencode/zivpn-clone-test /usr/local/bin/zivpn
chmod 755 /usr/local/bin/zivpn
systemctl start zivpn.service
systemctl status zivpn.service   # active (running)
```

État final :
- Service `zivpn.service` actif, écoute sur `:5667`, commande `zivpn server -c /etc/zivpn/config.json`
- Interop vérifiée sur le serveur de prod (client → serveur : `connected to server`)

---

## 11. Bilan des modifications du fork (récapitulatif)

| Domaine | Modification |
|---|---|
| Protocole | 4 headers `Hysteria-*` → `Zivpnudp-*` ; `URLHost` `hysteria` → `zivpnudp` |
| Obfs | Salamander forcée + PSK fixe `hu``hqb`c` |
| Serveur config | `cert`/`key` racine ; json5 ; `auth.mode passwords` ; Field `zivpn_udp` |
| Client | Kill-switch `signature` → client inutilisable par design |
| CLI | `Use: zivpnudp` ; env `ZIVPN_*` ; logo/version 3 champs ; help court-circuité |
| Retraits | `check-update`, `version`, `--disable-update-check` |
| Divers | `ZIVPN_UDP_BRUTAL_DEBUG` ; chemins `$HOME/.zivpn`, `/etc/zivpn/` |

---

## 12. Fichiers et artefacts

- `/root/tuo/clone-zivpn` : worktree Git du clone (base `405572d` + modifs)
- `/root/tuo/fork` : fork principal (port hopping, obfs padding, lossTolerance + modifs zivpn)
- `/root/tuo/hysteria-src` : source upstream @ `405572d`
- `/usr/local/bin/zivpn` : clone installé (production)
- `/root/tuo/zivpn.official.bak` : binaire officiel sauvegardé (md5 `7c69b556...`)
- `/tmp/opencode/zivpn-clone-test` : build de développement du clone
- `/tmp/opencode/zivpn_full.txt` : dump GoReSym
- `/root/tuo/APPROFONDISSEMENTS.md`, `/root/tuo/CAPTURES_ET_AUTH.md` : analyse détaillée (désassemblage, captures)