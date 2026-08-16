# Hysteria 2 (zivpn) — Analyse des captures réseau + Authentification

Sources : `/root/tuo/hysteria-src/`, captures dans `/root/zivpn-analysis/`, configs bench `/root/kighmu-work/20260813/bench/`

---

## A. Le binaire est un Hysteria 2 REBRANDÉ et MODIFIÉ

Ce n'est PAS un Hysteria 2 vanilla. Le binaire `/usr/local/bin/zivpn` a été fork/rebrandé (binaire appelé `udp-zivpn`) :

### En-têtes de protocole renommés (au lieu de `Hysteria-*`) — confirmés dans le .rodata
| Upstream Hysteria | Binaire zivpn |
|---|---|
| `Hysteria-Auth` | `Zivpnudp-Auth` (refs @ `0x8b4cda`, `0x8b4d5b`) |
| `Hysteria-Padding` | `Zivpnudp-Padding` (refs @ `0x8b4ef5`, `0x8b53f0`) |
| `Hysteria-CC-RX` | `Zivpnudp-CC-RX` (refs @ `0x8b4cb3`, `0x8b4e26`, `0x8b50c3`, `0x8b525d`, `0x8b5316`) |
| `Hysteria-UDP` | `Zivpnudp-UDP` (refs @ `0x8b4ff7`, `0x8b5195` ; confirmé, sert aussi de message d'erreur `dial error: Zivpnudp-UDP`/`empty packet`) |

Chaque ref pointe une instruction `lea rbx/rax,[rip+str]` dans les fonctions `protocol.AuthRequestFromHeader/ToHeader` et `AuthResponseFromHeader/ToHeader` (détaillé dans `APPROFONDISSEMENTS.md` §10).

Autres chaînes custom observées dans le binaire :
- `ZIVPN_UDP_BRUTAL_DEBUG` (au lieu de `HYSTERIA_BRUTAL_DEBUG`)
- `ZIVPN UDP running`, `UDP tunneling from ZIVPN`
- `zivpn_udp`, `udp-zivpn`, config `/etc/udp-zivpn/client.json`, `$HOME/.zivpn`
- `ZIVPN_LOG_LEVEL`, `ZIVPN_LOG_FORMAT`
- `signature ping mode`, `Ping mode`

### Fonctionnalités custom (absentes d'upstream 405572d)
D'après les configs et les chaînes du binaire :
- **`exclude_port`** (liste de ports exclus) : présent dans les configs serveur (`[53, 5300, 4466, 36712, 20000]`)
- **`obfs: "zivpn"`** — un type d'obfuscation custom en plus de `salamander`/`plain`
- **`auth.mode: "passwords"`** avec `config` (liste de mots de passe)
- Champs client custom : `TCPRelays`, `TCPRelay`, `UDPRelays`, `UDPRelay`, `TUN`, `ACL`, `MMDB`, `Protocol`, `HopInterval`, `TCPUDP TProxy/Redirect` (vus dans les logs de config)
- `*adaptiveConnFactory` : classe custom qui combine la factory UDP + obfs

### Version réelle
- Log : `version:app/v2.12.1` (Hysteria récent, fork), mais buildinfo GoReSym indiquait `go1.21.4` + commit upstream `405572d` (2023). Le binaire est donc un **fork à base de Hysteria 2 récent** avec modifications locales.
- C'est un client **et** serveur en un seul binaire (`hysteria client|server` équivalent).

---

## B. Authentification détaillée

### ⚠️ Le fork a un schéma de config d'auth COMPLÈTEMENT DIFFÉRENT d'upstream

**Vérifié par test fonctionnel direct** (configs serveur réelles exécutées avec le binaire) :

- **Upstream Hysteria** : `"auth": "mon-secret"` (string simple) ou `"auth": "user:pass"`.
- **Fork zivpn** : `"auth"` doit être un **objet** (`cmd.serverConfigAuth`), sinon :
  ```
  Failed to parse server configuration {"error": "json: cannot unmarshal string into Go value of type cmd.serverConfigAuth"}
  ```
  (le client zivpn échoue avec `FATAL wtf!!!No Idea` — voir D.4)

**Modes d'auth supportés par le fork** (testés un par un) :

| mode | résultat | erreur si champs manquants |
|---|---|---|
| `passwords` | ✅ **accepté** | liste de mots de passe dans `auth.config` |
| `userpass` | ⚠️ reconnu | `auth.userpass: empty auth userpass` |
| `command` | ⚠️ reconnu | `auth.command: empty auth command` |
| `http` | ⚠️ reconnu | `auth.http.url: empty auth http url` |
| `password` | ❌ refusé | `auth.type: unsupported auth type` |
| `users` | ❌ refusé | `auth.type: unsupported auth type` |

Donc : `auth.mode: "passwords"` + `auth.config: ["pw1", "pw2", ...]` = la manière native du fork de gérer plusieurs mots de passe. Le mot de passe upstream `password` n'existe plus (remplacé par `passwords`).

**Config serveur de production réelle** (`/etc/zivpn/config.json`) :
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
  "auth": { "mode": "passwords", "config": ["George34", "https://t.me/lkgcddtoogv", "ip9090"] }
}
```
⚠️ Contient des secrets réels — ne pas diffuser. Le serveur tourne depuis le 11 août (process `zivpn server -c /etc/zivpn/config.json`, port 5667).

### L'implémentation d'auth côté `extras/auth` (upstream conservé)

L'upstream propose 4 authentificateurs, toujours présents dans le binaire (symboles `*auth.PasswordAuthenticator`, `*auth.UserPassAuthenticator`, `*auth.CommandAuthenticator`, `*auth.HTTPAuthenticator` et leurs `.Authenticate`).

### 1. `PasswordAuthenticator` (password.go)
- Vérifie `auth == Password` (chaîne unique).
- Succès → `id = "user"`.

### 2. `UserPassAuthenticator` (userpass.go)
- Format : `auth = "username:password"` (séparateur `:`).
- Cherche dans `Users map[string]string` ; succès → `id = username`.

### 3. `CommandAuthenticator` (command.go)
- Exécute `Cmd <addr> <auth> <tx>` via `exec.Command`.
- Sortie stdout (trimée) = `id` si exit code 0 ; sinon refus.

### 4. `HTTPAuthenticator` (http.go)
- POST JSON vers l'URL configurée : `{"addr","auth","tx"}`.
- Réponse attendue : `{"ok","id"}` ; timeout 10 s ; TLS `InsecureSkipVerify` optionnel.

### Le protocole d'auth sur le fil (côté serveur)
Dans `h3sHandler.ServeHTTP` (server.go) :
- Le client envoie `POST hysteria/auth` (ici renommé `Zivpnudp-Auth`).
- En-têtes : `Hysteria-Auth` (token) + `Hysteria-CC-RX` (débit montant demandé) + padding aléatoire.
- Le serveur vérifie via `config.Authenticator.Authenticate(remoteAddr, auth, rx)`.
- Succès → réponse HTTP statut `233` (`StatusAuthOK`) + en-tête `Hysteria-UDP` (booléen) + `Hysteria-CC-RX` (débit alloué, ou `auto`).
- Échec → le serveur fait **masquage** : répond comme un site web normal (404 ou masq handler) pour tromper les scanners.

### Padding anti-analyse
- Auth request/response : 256–2048 octets aléatoires (`authRequestPadding`/`authResponsePadding`).
- TCP request : 64–512 ; TCP response : 128–1024.
- Le but : uniformiser les tailles de paquets pour brouiller la reconnaissance par longueur.

---

## C. Corrélation avec vos captures réseau

Configurations utilisées (bench) :
- Serveur : `zivpn-loopback.json` → `listen 127.0.0.1:28444`, `obfs "zivpn"`, `auth.mode "passwords"`, `exclude_port [53,5300,4466,36712,20000]`.
- Client : `zivpn-client.json` → `server 127.0.0.1:28444`, SOCKS5 `127.0.0.1:21081`, up/down 1000 Mbps, fast_open, insecure.

### Topologie réseau (serveur = 204.152.219.23, clients = 165.210.39.184/251)

**Capture `all_udp_sample.txt`** (20 lignes, 06:53:44) :
- Session UDP stable : client `165.210.39.184.58478` → serveur `204.152.219.23.9103` (petit paquet 45 B), puis le serveur renvoie des **datagrammes QUIC pleins de 1447 B** vers ce client. → Session UDP QUIC du tunnel en place.
- Trafic externe : serveur `:16556` ↔ `31.13.71.48:3478` (STUN), serveur `:61656` ↔ `148.153.113.225:10014`, `:15878`↔`165.210.39.251:50058`, etc.

**Capture `zivpn_porthop_30s.txt`** (7803 lignes, 06:54:28–58) — démonstration du PORT HOPPING :
- Le client `165.210.39.251` change de **port source ET port destination à chaque envoi** :
  ```
  19781 → 16827
  22170 → 16828
  22171 → 16829
  63257 → 16830
  63258 → 16831
  32347 → 16832
  ...
  ```
  813 ports destination distincts en 30 s, 226 ports source distincts (client184) en 20 s.
- Le serveur répond depuis le même port destination reçu (16827, 16828, ...) avec des datagrammes de **1447 B** (taille max QUIC).
- Le client envoie de petits paquets (33–75 B, typique QUIC Initial/ACK).
- Trafic externe en parallèle (vraies destinations tunnelées) :
  - `31.13.71.48:3478` (STUN) → 2370 paquets entrants, tailles 20–1046 B
  - `148.153.113.225:10014` → 600 paquets
  - `57.145.2.141:443` → QUIC

**Capture `zivpn_client184_20s.txt` / `client184_download_30s.txt`** (download benchmark) :
- Client 184 ouvre des centaines de **sockets source différentes** (226 en 20 s) et saute entre des ports serveur consécutifs.
- Chaque paire source→dest = une nouvelle "session" ; le serveur répond par rafales de 1447 B (download).
- Tailles dominantes : 1447 B (datagrammes QUIC max) + 1208 B (paquets QUIC Initial) + petits ACK.

### Interprétation du port hopping (corrélation avec le code)

Comportement observé = `extras/transport/udphop` :
- `NewUDPHopPacketConn(addr, hopInterval)` : ouvre une socket UDP, tire un `addrIndex` aléatoire, puis toutes les `HopInterval` :
  1. `hop()` : ferme l'ancienne socket, en crée une nouvelle (`net.ListenUDP` éphémère) → **nouveau port source** ;
  2. garde l'ancienne (`prevConn`) le temps du basculement pour ne pas perdre de paquets ;
  3. `addrIndex = rand.Intn(len(Addrs))` → **nouveau port destination** (choisi dans la liste/plage configurée).
- Sur le réseau : on voit bien chaque paire `(port_source, port_dest)` nouvelle, avec des ports destination consécutifs car la config utilise une plage (ex. les 813 ports).
- Le client enveloppe cette `udpHopPacketConn` dans `adaptiveConnFactory` (obfs optionnelle) puis la donne à quic-go → le QUIC est émis depuis un port qui change en continu.

**Ce que cela implique pour un observateur :** le flux n'a pas de 5-tuple stable : l'IP source/dest et le port source changent en permanence, rendant le blocage par IP+port inefficace. Le port 36712 (dans `exclude_port`) est vraisemblablement le port de service principal à ne pas sauter (ou celui de l'API/statut).

### Le port hopping est côté SERVEUR aussi (découvert par désassemblage)

Symboles du fork dans `app/cmd` (adresses réelles = GoReSym − 0x72d3e0) :
- `parseServerAddrString` @ `0x903240` : parse une adresse serveur avec support des crochets `[` (IPv6) et split sur `:`.
- `isPortHoppingPort` @ `0x903360` : vérifie si un port contient `-` ou `,` (plage `16827-16851` ou liste).
- `(*serverConfig).fillConn` @ `0x905d80` : construit la factory UDP serveur (buffers 2048, obfs).
- `(*clientConfig).fillConnFactory` @ `0x901aa0` : parse le type de transport — reconnaît `"udp"` (cmp `0x6475`=«ud» + `0x70`=«p») et `"udphop"` (`0x68706475`=«udph» + `0x706f`=«op») puis branche vers l'obfs.
- `(*adaptiveConnFactory).New` @ `0x9033e0` : combine la socket brute + obfs optionnelle en factory pour quic-go.

Le port hopping réel : côté serveur prod, c'est un **DNAT nftables** (UDP 6000–19999 → :5667) ; le binaire ignore `exclude_port` (voir D.2). Le serveur répond depuis le port reçu (observé dans les captures : 813 ports dest, réponses depuis le même port).

### Synthèse des tailles de paquets QUIC
| Taille | Rôle probable |
|---|---|
| 1447 B | Datagramme QUIC max (UDP data plein) |
| 1208 B | Paquet QUIC Initial (handshake) |
| 1435 B | Datagramme QUIC légèrement réduit |
| 33–75 B | ACK / ping / contrôle QUIC |

---

## D. Éléments confirmés par le désassemblage du binaire (adresses réelles = GoReSym − 0x72d3e0)

### 1. `obfs: "zivpn"` = Salamander standard + PSK fixe embarquée (résolu)
- `NewSalamanderObfuscator` @ réel `0x8e65e0` : c'est **exactement** l'algorithme Salamander d'upstream (`extras/obfs/salamander.go` : `smPSKMinLen=4`, salt 8 octets, `blake2b.Sum256(PSK||salt)`, seed `rand.NewSource(time.Now().UnixNano())`).
- La PSK est **fixe et embarquée** dans le binaire : ``hu``hqb`c`` (9 octets), en .rodata à `0xa3026f` ; globals .data `[0xebbb20]`=ptr→PSK, `[0xebbb28]`=9.
- Seulement 2 xrefs vers `NewSalamanderObfuscator` : client `fillConnFactory` @ `0x901ba9` et serveur `init.3` @ `0x905e49`. **Le serveur et le client utilisent TOUJOURS cette même PSK** — pas de branchement runtime sur une autre valeur.
- Autres adresses : Obfuscate `0x8e67e0`, Deobfuscate `0x8e6a80`, init `0x8e6c20`.
- Conséquence furtivité : l'obfs est partagée publiquement dans le binaire client distribué ; elle protège contre la détection par signature mais pas contre un adversaire ayant le binaire.

### 2. `exclude_port` = champ JSON ignoré par le binaire officiel (résolu)
- La chaîne `exclude_port` est **absente** du binaire (strings, izz, GoReSym). 
- Le JSON est parsé **non strictement** (pas de `DisallowUnknownFields`) : test expérimental avec champ inconnu `unknown_field_xyz` + `exclude_port` → le serveur démarre sans erreur.
- → `exclude_port` est **ignoré** par le binaire officiel. Le vrai « port hopping » observé en capture vient d'upstream `udphop` + DNAT nftables en prod (6000–19999 → :5667). La config prod `exclude_port` n'a donc **aucun effet**.

### 3. Parsing `auth.mode` serveur (résolu, `fillAuthenticator` @ `0x906a60`)
Valeurs numériques internes comparées par le switch du parseur :
| mode | valeur | note |
|---|---|---|
| `cmd` | 3 | |
| `http` | 4 | |
| `https` | 5 | |
| `command` | 7 | |
| `userpass` | 8 | |
| `passwords` | 9 | le mode natif multi-mots-de-passe du fork |
| `password` | — | ❌ `auth.type: unsupported auth type` (n'existe pas) |

### 4. Bug client : kill-switch `signature` → `wtf!!!No Idea` (résolu)
- `runClient` @ `0x9020c0`–`0x9026e0`. Au tout début (`0x9020f3`–`0x902105`) :
  1. `lea rbx,[0xa30281]` = clé `"signature"` (9 chars), `ecx=9` ;
  2. `call viper.GetString` (`0x7de8c0`) ;
  3. `cmp [0xebbb28](=9), rbx` : compare la longueur de la valeur lue avec **9** ;
  4. si ≠ 9 → `zap.Logger.Fatal` (`0x801aa0`) avec la chaîne `wtf!!!No Idea` (`0xa31fa1`, 13 chars).
- Le check est un **kill-switch** : la valeur de `signature` doit faire **exactement 9 caractères ET être égale à ``hu``hqb`c``** (à `0x90210e`–`0x902120`, comparaison via `0x406ba0`).
- Ensuite (`0x902160`→`0x902191`) : `viper.GetString("config")` retourne le contenu brut du fichier, parsé par `json5.Unmarshal` (`0x8e94a0`, lib `yosuke-furukawa/json5` v0.1.1).
- `initFlags` @ `0x905400` : flags `config file`, `log level`, `log format`, `signature` (le flag `signature` est bindé à viper).

**Résultat des tests fonctionnels — le client officiel zivpn 1.5.0 est inutilisable :**
1. Signature dans le fichier config (même la vraie ``hu``hqb`c``) → viper ne lit pas la clé depuis le fichier au moment du check → `wtf!!!No Idea`.
2. Signature via le flag `--signature 'hu``hqb`c'` → le check **passe**, mais le re-parsing json5 du fichier échoue ensuite : `Failed to parse client configuration {"error": "invalid character 't' in comment"}` (interaction viper flag + backticks de la valeur).
3. Signature via flag sans fichier config → `unexpected end of JSON input`.
4. Signature autre (ex. `abcdefghi`, 9 chars) → `wtf!!!No Idea` (contenu ≠ PSK).

→ Aucun scénario testé ne permet au client zivpn officiel de fonctionner. C'est un bug de conception du fork (la signature censée être un mécanisme anti-piratage casse le client lui-même).

## E. Méthodologie des tests fonctionnels (reproductible)
Pour vérifier le comportement réel du binaire sans le casser :
```bash
# 1. Générer une config serveur de test (auth passwords)
/usr/local/bin/zivpn server -c srv.json   # observe le log "server up and running" ou l'erreur de config
# 2. Pour tester les modes d'auth : modifier auth.mode et relancer, lire "invalid config: auth.type: ..."
# 3. Client test : "wtf!!!No Idea" = kill-switch signature (voir D.4) ; l'obfs "zivpn" est Salamander standard + PSK fixe (voir D.1)
```
Nota : lancer en arrière-plan via un script (`setsid`/`nohup` dans le shell persistent) sinon le shell se bloque sur le `wait`.