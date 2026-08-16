# Hysteria 2 (zivpn) — Approfondissements

Suite de l'analyse du binaire `/usr/local/bin/zivpn` (= Hysteria 2, commit `405572d`, Go 1.21.4).
Sources exactes du commit : `/root/tuo/hysteria-src/`

---

## 1. Client SOCKS5 (`app/internal/socks5/server.go`)

Le client Hysteria expose le tunnel localement via un **serveur SOCKS5** utilisant le client Hysteria comme outbound.

### Négociation
- `negotiate()` : lit la requête de négociation, choisit la méthode :
  - `AuthFunc == nil` → `MethodNone (0x00)`
  - sinon → `MethodUsernamePassword (0x02)` et valide `(user, pass)` via `AuthFunc`.
- Méthode non supportée → `MethodUnsupportAll (0xFF)`.

### Dispatch
- `CmdConnect (0x01)` → TCP relay (`handleTCP`).
- `CmdUDP (0x03)` → UDP relay (`handleUDP`), sauf si `DisableUDP` (réponse `RepCommandNotSupported`).

### TCP relay (`handleTCP`)
1. `s.HyClient.TCP(addr)` ouvre un **stream QUIC** vers le serveur Hysteria (le tunnel).
2. Réponse `RepSuccess`, puis `io.Copy` bidirectionnel TCP ↔ stream QUIC.

### UDP relay (`handleUDP`) — le cœur du tunnel UDP local
1. Ouvre une **socket UDP locale** (`net.ListenUDP` sur le même hôte que le listener TCP, port éphémère `0`).
2. Ouvre une **session UDP Hysteria** (`s.HyClient.UDP()` → `HyUDPConn`).
3. Réponse SOCKS5 avec l'adresse de bind UDP (`sendUDPReply`).
4. Boucle `udpServer` (local → remote) :
   - lit un datagramme SOCKS5 (`socks5.NewDatagramFromBytes`) ;
   - **Fragmentation SOCKS5 non supportée** (tout `Frag != 0` est ignoré) ;
   - le **premier émetteur** devient `clientAddr` (c'est à lui qu'on renvoie les réponses) ;
   - `hyUDP.Send(d.Data, d.Address())` envoie le payload à travers le tunnel.
5. Goroutine remote → local :
   - `hyUDP.Receive()` reçoit `(data, from)` depuis le tunnel ;
   - réencapsule en datagramme SOCKS5 (`socks5.NewDatagram`) et l'écrit sur la socket UDP locale vers `clientAddr`.
6. Un `io.Copy(io.Discard, conn)` sur la connexion TCP SOCKS5 **maintient la session en vie** (les clients SOCKS5 gardent la connexion TCP ouverte tant qu'ils utilisent l'UDP).

Note : le binaire embarque `github.com/txthinking/socks5` (`*socks5.Server`, `*socks5Logger`) et `clientSOCKS5` (désassemblé @ `0x903160`).

---

## 2. Congestion Brutal (`core/internal/congestion/brutal/brutal.go`)

Contrôle de congestion **agressif et sans perte-de-queue** : il impose un **débit constant** (bps cible) au lieu d'adapter le débit aux pertes.

### Idée générale
- `BrutalSender` se comporte comme un **contrôleur à fenêtre fixe** : `bps` est la bande passante cible.
- Il **ignore les pertes** (`OnCongestionEvent`/`OnPacketAcked` sont des stubs) et n'utilise **jamais le slow-start** (`InSlowStart`/`InRecovery` = false).
- Seule variable d'ajustement : le **taux d'ACK** (`ackRate`) pour compenser les pertes.

### Fenêtre de congestion
```
GetCongestionWindow() = bps * SmoothedRTT * multiplier(2) / ackRate
```
- Si RTT inconnu → 10240 octets par défaut.
- `CanSend(bytesInFlight)` = `bytesInFlight < GetCongestionWindow()`.
- Plus le RTT est grand, plus la fenêtre est grande (toujours soutenir bps).

### Pacing (token bucket) — `common/pacer.go`
- `Pacer.Budget(now)` = budget restant + `bandwidth * temps_écoulé`, plafonné à `maxBurstSize` (= `max(10 paquets, ~1ms de débit)`).
- `TimeUntilSend()` : si `budget >= maxDatagramSize` → envoi immédiat ; sinon retourne l'instant où le token se remplit.
- `HasPacingBudget()` : `Budget(now) >= maxDatagramSize`.

### Ajustement du taux d'ACK
- `OnCongestionEventEx` échantillonne Ack/Loss par **slot de 1 s** (`pktInfoSlotCount = 5` → 5 s glissantes).
- `updateAckRate` :
  - `ack+loss < 50` → `ackRate = 1` (pas assez de données) ;
  - `rate = ack/(ack+loss)` ; si `< 0.8` → clampé à `minAckRate = 0.8` ;
  - sinon `ackRate = rate`.
- Le débit effectif = `bps / ackRate` : si 20 % des paquets sont perdus, le débit est boosté de 25 % pour viser bps utile.

### Construction
- `NewBrutalSender(bps)` : `debug` piloté par la variable d'env `HYSTERIA_BRUTAL_DEBUG` (dans le binaire zivpn, renommée **`ZIVPN_UDP_BRUTAL_DEBUG`** — différence avec le source upstream), seed du `Pacer` avec `bps/ackRate`.

### Branchement
- `congestion.UseBrutal(conn, tx)` → `conn.SetCongestionControl(brutal.NewBrutalSender(tx))`.
- Côté serveur (dans `ServeHTTP`, après auth) :
  - si `IgnoreClientBandwidth` → `UseBBR` (le serveur décide) ;
  - sinon `actualTx = min(clientRx, serverMaxTx)` ; si `actualTx > 0` → `UseBrutal` sinon `UseBBR`.
- Côté client : si `bandwidth.up` configuré → Brutal avec `MaxTx`, sinon BBR.
- Adresses désassemblées : `NewBrutalSender` @ `0x827BC0`, `blake2b` utilisé par Salamander @ `0x8E00C0`.

---

## 3. Le serveur complet (`core/server/server.go` + `app/cmd/server.go`)

### Transport
- `NewServer` configure TLS (via `http3.ConfigureTLSConfig`) et QUIC (`quic.Listen(config.Conn, ...)`, `EnableDatagrams: true`).
- La `net.PacketConn` d'entrée (`config.Conn`) a déjà été enveloppée par l'obfs Salamander (ou udphop) côté config.

### Serve HTTP/3 comme couche de contrôle
Chaque client QUIC est traité par un `h3sHandler` (`http3.Server` avec `StreamHijacker`) :
- `ServeHTTP` intercepte **uniquement** `POST hysteria/auth` (voir `protocol/http.go`) :
  - en-têtes : `Hysteria-Auth`, `Hysteria-CC-RX` (débit demandé), `Hysteria-Padding`, `Hysteria-UDP` (réponse).
  - si déjà authentifié → re-envoie la réponse OK.
- **Échec d'auth ou toute autre requête → `masqHandler`** : le serveur fait semblant d'être un site web normal (404 ou handler de masquage configuré) — anti-scan.

### Authentification
- `config.Authenticator.Authenticate(remoteAddr, auth, rx)` → `(ok, id)`.
- Auth OK :
  1. décide du congestion control (Brutal ou BBR, cf. §2) ;
  2. répond `StatusAuthOK (233)` avec `UDPEnabled` et `Rx` (ou `RxAuto` → `"auto"`) ;
  3. démarre le `udpSessionManager` (si UDP activé) via une goroutine (`sync.Once`-style).

### Proxying TCP (streams QUIC)
- `ProxyStreamHijacker` intercepte les frames `FrameTypeTCPRequest (0x401)` sur des streams non-HTTP.
- `handleTCPRequest` : lit la requête (`ReadTCPRequest`), dial la cible via `Outbound.TCP`, répond `WriteTCPResponse`, puis relay bidirectionnel (`copyTwoWay` ou `copyTwoWayWithLogger` si `TrafficLogger`).
- Le `TrafficLogger` peut demander la **déconnexion** (`errDisconnect` → `CloseWithError(0x107, "")`, code HTTP3 `ErrCodeExcessiveLoad`).

### Proxy UDP (datagrams QUIC)
- `udpIOImpl.ReceiveMessage/SendMessage` : `ReceiveDatagram`/`SendDatagram` + `ParseUDPMessage`/`Serialize`, avec comptage de trafic (`TrafficLogger.Log(authID, rx, tx)`).
- `udpIOImpl.UDP(reqAddr)` → `Outbound.UDP(reqAddr)` : ouvre la socket UDP locale vers la destination.
- Logs d'événements : `udpEventLoggerImpl` (Connect/Disconnect/TCP/UDP).

### Protocole auth — `core/internal/protocol/http.go`
```
Constantes:
  URLHost = "hysteria", URLPath = "/auth"
  RequestHeaderAuth  = "Hysteria-Auth"
  ResponseHeaderUDP  = "Hysteria-UDP"
  CommonHeaderCCRX   = "Hysteria-CC-RX"
  CommonHeaderPad    = "Hysteria-Padding"
  StatusAuthOK = 233
```
AuthRequest : `{Auth string, Rx uint64}` (Rx=0 → inconnu, détection auto).
AuthResponse : `{UDPEnabled bool, Rx uint64, RxAuto bool}`.

### Padding — `core/internal/protocol/padding.go`
- Padding aléatoire ajouté aux échanges auth/TCP pour masquer les longueurs réelles :
  - auth request/response : 256–2048 octets ;
  - TCP request : 64–512 ; TCP response : 128–1024.
- Caractères alphanumériques, via `math/rand`.

---

## 4. Port hopping UDP (`extras/transport/udphop`)

Le **client** change son port UDP source **périodiquement** (par défaut 30 s) pour échapper aux blocages par IP+port (ex. censeurs qui bloquent un port QUIC spécifique).

### Adresse `UDPHopAddr` (`addr.go`)
- Format : `IP:port` où `port` peut être :
  - une liste : `443,8443` ;
  - une plage : `4000-5000` ;
  - un mélange des deux : `443,5000-6000`.
- `ResolveUDPHopAddr` résout l'IP et génère la liste de ports (`addrs()`).

### `udpHopPacketConn` (`conn.go`) — implémente `net.PacketConn`
- **Écriture** (`WriteTo`) : toujours vers `Addrs[addrIndex]` (un des ports de la liste), **sans vérifier l'adresse fournie** (perf).
- **Lecture** (`ReadFrom`) : reçoit depuis une file `recvQueue` remplie par `recvLoop` ; retourne toujours `u.Addr` comme adresse source.
- **Hop** (`hopLoop` → `hop`, ticker `HopInterval`) :
  1. `net.ListenUDP` sur un **nouveau port éphémère** ;
  2. ferme `prevConn`, promeut `currentConn` → `prevConn`, le nouveau devient `currentConn` ;
  3. démarre `recvLoop` sur le nouveau ;
  4. `addrIndex = rand.Intn(len(Addrs))` → nouveau port de destination.
- **Pourquoi garder `prevConn`** : éviter la perte de paquets pendant la transition (le serveur met un peu de temps à découvrir le nouveau port).
- `HopInterval < 5 s` → erreur ; `recvLoop` ne transmet que les timeouts (pas les fermetures) ; file `recvQueue` de 1024 paquets (drop si pleine) ; buffers 2048 octets.
- Les méthodes UDP (`SetReadBuffer`, `SetWriteBuffer`, `SyscallConn`) sont propagées sur `currentConn` et `prevConn`.

### Où c'est branché
- Côté client (`fillConnFactory`) : si `transport.type == "udphop"` → `newFunc` crée `udphop.NewUDPHopPacketConn(hopAddr, c.Transport.UDP.HopInterval)`.
- Résultat enveloppé par l'obfs puis passé à quic-go comme `net.PacketConn` (via `adaptiveConnFactory` dans le binaire zivpn).

---

## Résumé des adresses (désassemblage, mapping GoReSym→réel = `-0x72d3e0`)

| Symbole | GoReSym VA | Adresse réelle |
|---|---|---|
| `(*UDPMessage).HeaderSize` | 0xfe3720 | 0x8b6340 |
| `(*UDPMessage).Serialize` | 0xfe38e0 | 0x8b6500 |
| `ParseUDPMessage` | 0xfe3be0 | 0x8b6800 |
| `varintPut` | 0xfe3f60 | 0x8b6b80 |
| `NewSalamanderObfuscator` | 0x1013bc0 | 0x8e67e0 |
| `(*SalamanderObfuscator).Obfuscate` | 0x1013e60 | 0x8e6a80 |
| `(*SalamanderObfuscator).Deobfuscate` | 0x1014000 | 0x8e6c20 |
| `blake2b.Sum256` | 0x100d4a0 | 0x8e00c0 |
| `NewBrutalSender` | 0xf54fa0 | 0x827bc0 |
| `clientSOCKS5` | 0x1030540 | 0x903160 |

## 5. L'obfs « zivpn » = Salamander standard + PSK fixe embarquée

Découverte majeure (vérifiée par désassemblage + test) :

- Le mode obfs **`"zivpn"` n'est PAS un algorithme custom** : c'est le **Salamander upstream** (`extras/obfs/salamander.go`) instancié avec une **PSK fixe embarquée dans le binaire** : ``hu``hqb`c`` (9 octets).
- PSK construite à l'exécution dans `app/cmd.init.3` / `(*serverConfig).fillConn` (`0x905d80`) :
  ```
  movabs rcx, 0x6062716860607568   ; "hu``hqb`"
  mov qword [rax], rcx             ; écrit les 8 premiers octets
  mov byte [rax+8], 0x63           ; 'c'  → "hu``hqb`c" (9)
  mov ebx, 9                       ; len = 9
  mov rcx, rbx
  call 0x8e65e0                    ; NewSalamanderObfuscator(PSK, 9)
  ```
  (construction octet par octet = **anti-strings** ; la chaîne apparaît aussi en clair dans le .rodata à `0xa3026f`).
- **Asymétrie serveur/client** : le `movabs 0x6062716860607568` n'existe **qu'une seule fois** dans tout le binaire (offset fichier `0x505e30`). Côté serveur, la PSK est donc **codée en dur dans le code machine** — aucun paramètre de config ne la change. Côté client (`fillConnFactory` @ `0x901ba9`), la PSK est lue de la **config client** (`[rsi+0x10]`/`[rsi+0x18]`, string) : le client doit fournir `hu``hqb`c` lui-même (via `obfs`/`salamander.password`), ce qui fait écho au kill-switch `signature` (§8).
- Xrefs de `0x8e65e0` (NewSalamanderObfuscator) : **2 seuls appels** — `0x901ba9` (client, `fillConnFactory`) et `0x905e49` (serveur, `init.3`). Le serveur ET le client appliquent donc **toujours** ce même obfuscateur Salamander pour le mode « zivpn » ; il n'y a pas de branchement runtime vers un autre algo.
- Conséquence : l'« obfs zivpn » = Salamander standard, clé identique des deux côtés, format on-wire `[salt 8 octets][payload XOR blake2b-256(PSK||salt)]` — **documenté upstream**, pas de secret protoculaire réel au niveau obfs.
- Algorithme Salamander confirmé dans le binaire : `cmp rbx, 4` (PSK ≥ 4 octets, `smPSKMinLen`), seed `math/rand.NewSource(time.Now().UnixNano())` (constante `0x3b9aca00` = 1e9), stockage dans un global construit par `init.3`.

### Pourquoi le serveur zivpn ne répond pas aux clients standards
Ce n'est pas (seulement) l'obfs : un client hysteria standard (obfs salamander avec la PSK de config) ne peut pas se connecter car le **protocole auth/handshake est modifié** (headers `Zivpnudp-Auth/Padding/CC-RX`, `auth.mode` étendu), cf. §6.

---

## 6. Parsing `auth.mode` serveur (`fillAuthenticator` @ `0x906a60`)

Modes acceptés (comparaisons length + motifs à `0x906540+`) :

| Length | Motif (octets) | Mode | Comportement |
|---|---|---|---|
| 3 | `cm` + `d` | `cmd` | — |
| 4 | `http` | `http` | erreur `empty auth http url` si pas d'URL |
| 5 | `http` + `s` | `https` | erreur `empty auth http url` si pas d'URL |
| 7 | `comm` + `an` + `d` | `command` | erreur `empty auth command` si pas de commande |
| 8 | `userpass` | `userpass` | — |
| 9 | `passwords` | `passwords` | multi-mots de passe (config tableau) |

- **`password` (singulier) n'existe PAS** → config `{"mode":"password"}` = `auth.type: unsupported auth type` (cohérent avec les captures).
- Le mode prod `{"mode":"passwords","config":["George34",...]}` est bien supporté.
- Config serveur complète testée avec le binaire réel (cf. `/etc/zivpn/config.json`).

---

## 7. JSON de config non-strict — `exclude_port` IGNORÉ

- La string `exclude_port` n'apparaît **nulle part** dans le binaire (`strings`, `izz`, GoReSym).
- Test expérimental : config avec `"unknown_field_xyz": 12345` ET `"exclude_port": [...]` → serveur démarre **sans erreur** ("server up and running"). Le parsing JSON du serveur n'utilise donc **pas** `DisallowUnknownFields` : les champs inconnus sont ignorés silencieusement.
- **Conclusion** : le `exclude_port` de `/etc/zivpn/config.json` (53, 5300, 4466, 36712, 20000) est **inopérant** côté binaire officiel. Le vrai filtrage/redirection des ports 6000–19999 est assuré par **nftables** (DNAT → 5667), pas par le serveur.
- Le serveur écoute réellement sur le seul port `listen` (5667) ; l'obfs Salamander est appliquée sur cette socket.

---

## 8. Bug client : kill-switch `signature` → `wtf!!!No Idea` (le client officiel ne peut pas fonctionner)

### Localisation (adresses réelles = GoReSym − 0x72d3e0)
- `runClient` @ `0x9020c0`–`0x9026e0`, tout au début (`0x9020f3`–`0x902120`) :
  - `0x9020f3` : `lea rbx,[0xa30281]` = clé viper **`"signature"`** (9 chars), `ecx=9`
  - `0x902100` : `call viper.GetString` (`0x7de8c0`)
  - `0x902105` : `cmp [0xebbb28](=9), rbx` — longueur de la valeur lue doit être **9**
  - si ≠ 9 : `zap.Logger.Fatal` (`0x801aa0`) → chaîne `wtf!!!No Idea` (`0xa31fa1`, 13 chars)
  - `0x90210e`–`0x902120` : charge `[0xebbb20]` (ptr → ``hu``hqb`c`` en .rodata `0xa3026f`) et compare le contenu (`0x406ba0`) ; si ≠ PSK → `wtf!!!No Idea` aussi.
- Ensuite : `0x902160` `GetString("config")` (contenu brut du fichier) → `0x902191` `json5.Unmarshal` (`0x8e94a0`, lib `github.com/yosuke-furukawa/json5` v0.1.1).
- `initFlags` @ `0x905400` : flags `config file`, `log level`, `log format`, **`signature`** (bindé à viper).

### Schéma du check
```
signature = viper.GetString("signature")
if len(signature) != 9  → FATAL wtf!!!No Idea
if signature != "hu``hqb`c" → FATAL wtf!!!No Idea
config_brut = viper.GetString("config")
json5.Unmarshal(config_brut, &clientConfig)   // ici l'erreur si flag signature utilisé
```

### Résultats des tests fonctionnels — aucune voie ne marche
| Scénario | Résultat |
|---|---|
| Signature dans le fichier config (vraie ``hu``hqb`c``, fichier `.json5` ou `.json`) | `wtf!!!No Idea` — viper ne lit pas la clé depuis le fichier au moment du check |
| Signature via `--signature 'hu``hqb`c'` + config | check **passe**, puis `Failed to parse client configuration: invalid character 't' in comment` (interaction flag viper + backticks) |
| `--signature 'hu``hqb`c'` sans fichier config | `unexpected end of JSON input` |
| `--signature 'abcdefghi'` (9 chars, contenu différent) | `wtf!!!No Idea` (comparaison de contenu) |
| Signature avec `/` (ex. `//abcdefg`) | `wtf!!!No Idea` — pas d'erreur json5 → c'est bien le backtick de la PSK qui casse le json5 |

### Interprétation
- La signature est un **kill-switch anti-piratage** : le client ne démarre que si `signature == "hu``hqb`c"` (la PSK de l'obfs, embarquée aussi côté serveur).
- Mais le chemin de lecture est cassé : viper ne voit pas la valeur depuis le fichier JSON5 au moment du check (seul le flag `--signature` la voit), et fournir la vraie valeur (avec backticks) par flag fait échouer le re-parse json5 de la config (`yosuke-furukawa/json5` interprète les backticks comme délimiteurs de commentaire → `stateInlineComment`/`stateSkipComment` dans `scanner.go`, erreur `invalid character ... in comment`).
- **Conclusion** : le client officiel zivpn v1.5.0 est **inutilisable dans tous les scénarios testés**. Le serveur, lui, fonctionne (pas de check signature en `runServer`).
- Implication pour le fork : tout client custom doit fournir `signature` de 9 chars via le flag, mais le bug json5 rend cela impossible → un fork ne peut pas réutiliser le client officiel tel quel (il faut patcher `runClient`).

---

## 9. Mode ping client (`runPing` @ `0x904320`) — un sous-ensemble de `runClient`

- Le binaire expose un 3ᵉ mode au-delà de `client`/`server`, repéré par les strings `ping mode` (`0xa3028a`) et `signature ping mode` (`0xa30298`, les deux juste après ``hu``hqb`c`` dans le .rodata).
- `runPing` @ `0x904320` :
  - exige **exactement 1 argument** d'adresse (`cmp rdx, 1` ; sinon FATAL `must specify one and only one address` à `0x90438f`) ;
  - résout l'adresse (`0x7e0700` ≈ `net.ResolveUDPAddr`) ;
  - parse ensuite la **config client** via `0x901ee0` (le même parseur que `runClient`) — donc `-c fichier` requis ;
  - `0x9047ea` : `call 0x8da1a0` (NewReconnectableClient en mode ping) ;
  - `0x904945`+ : démarre la boucle de ping.
- Il partage donc la config, l'obfs Salamander et le pipeline client — seule la charge utile change (paquets de ping au lieu du tunnel). Le flag/signal `ping mode` branche ce comportement.
- Note : comme `runClient`, il passe par `0x901ee0` qui déclenche le même kill-switch `signature` (§8) — le ping est donc lui aussi inutilisable avec le binaire officiel.

---

## 10. Handshake auth client↔serveur — construction des headers `Zivpnudp-*`

Le handshake de Hysteria 2 (HTTP/3, URL `https://hysteria/auth`) est **inchangé dans sa structure**, seul le nom des headers est renommé `Hysteria-*` → `Zivpnudp-*`. Ceci est **prouvé par adresses réelles** = GoReSym − 0x72d3e0.

### Correspondance fonctions (GoReSym → réel) et refs aux chaînes
| Fonction GoReSym | Adresse réelle | Ref `Zivpnudp-Auth` | Ref `Zivpnudp-UDP` | Ref `Zivpnudp-CC-RX` | Ref `Zivpnudp-Padding` |
|---|---|---|---|---|---|
| `protocol.AuthRequestFromHeader` | `0x8b4ca0` | `0x8b4cda` (lea rbx) | — | `0x8b4cb3` (lea rbx) | — |
| `protocol.AuthRequestToHeader` | `0x8b4d20` | `0x8b4d5b` (lea rax) | — | `0x8b4e26` (lea rax) | `0x8b4ef5` (lea rax) |
| `protocol.AuthResponseFromHeader` | `0x8b4fe0` | — | `0x8b4ff7` (lea rbx) | `0x8b50c3` (lea rbx) | — |
| `protocol.AuthResponseToHeader` | `0x8b5140` | — | `0x8b5195` (lea rax) | `0x8b525d`, `0x8b5316` (lea rax) | `0x8b53f0` (lea rax) |
| `protocol.padding.String` | `0x8b54e0` | — | — | — | — |
| `protocol.ReadTCPRequest` / `WriteTCPRequest` | `0x8b55c0` / `0x8b5820` | — | — | — | — |
| `protocol.ReadTCPResponse` / `WriteTCPResponse` | `0x8b5be0` / `0x8b5f20` | — | — | — | — |
| `protocol.(*UDPMessage).Serialize` / `ParseUDPMessage` | `0x8b6500` / `0x8b6800` | — | — | — | — |

VAs chaînes .rodata : `Zivpnudp-Auth` `0xa324e9`, `Zivpnudp-UDP` `0xa31da9`, `Zivpnudp-CC-RX` `0xa32ba2`, `Zivpnudp-Padding` `0xa33aab`. Toutes les refs sont contenues dans la zone `0x8b4cb3`–`0x8b53f0` (aucune autre occurrence dans le binaire).

### Le rôle de chaque fonction (identique à l'upstream)
- **`AuthRequestToHeader`** (client, émission) : `Zivpnudp-Auth` = auth encodée (base64 dans l'upstream), `Zivpnudp-CC-RX` = débit montant connu (bps, via `strconv.FormatUint`), `Zivpnudp-Padding` = padding.
- **`AuthRequestFromHeader`** (serveur, réception) : lit `Zivpnudp-Auth` et `Zivpnudp-CC-RX` (parse via `strconv.ParseUint`).
- **`AuthResponseToHeader`** (serveur, émission) : `Zivpnudp-UDP` = `"true"`/`"false"` (cf. `0x8b516e` `test bl,bl` → `"true"` @ `0xa2ea6c` / `"false"` @ `0xa2ed5c`), `Zivpnudp-CC-RX` = `"auto"` (demande de bande passante par détection) ou débit en bps, `Zivpnudp-Padding` = padding.
- **`AuthResponseFromHeader`** (client, réception) : `Zivpnudp-UDP` = `strconv.ParseBool`, `Zivpnudp-CC-RX` = `"auto"` → `RxAuto` sinon `ParseUint`.
- **`padding.String`** : comme upstream, génère `Min + rand.Intn(Max-Min)` caractères alphanumériques ; plages : auth request/response `256–2048`, TCP request `64–512`, TCP response `128–1024`.

### Motif assembleur d'écriture d'un header (constante)
```
lea rax, [string]      ; 0x8b4d5b pour Zivpnudp-Auth
call 0x6ed280          ; construction Go string
lea rax, [0x95ac40]    ; ptr → http.Header
call 0x410580          ; accès map
call 0x46aac0          ; h.Set(key, value)
```
Le même motif se répète pour chaque header (Auth `0x8b4d20`, UDP `0x8b5195`, CC-RX `0x8b525d`/`0x8b5316`, Padding `0x8b4ef5`/`0x8b53f0`).

### Trafic réél vs furtivité
- La seule différence de surface protocolaire avec un Hysteria 2 upstream : les **4 noms de headers** au handshake. Le reste (QUIC + obfs Salamander avec PSK ``hu``hqb`c``, statut `233`, URL `/auth`) est identique.
- Implication pour le fork : il suffit de paramétrer ces 4 noms de headers (constantes `RequestHeaderAuth`, `ResponseHeaderUDPEnabled`, `CommonHeaderCCRX`, `CommonHeaderPadding`) pour être interopérable avec zivpn — pas de changement de structure.

## 11. `URLHost = "zivpnudp"` et interopérabilité validée (2026-08-16)

**Découverte** : le host du handshake est `zivpnudp` (pas `hysteria` comme l'upstream). Le serveur officiel rejette en 404 tout client utilisant `Host: hysteria`.

**Validation empirique** (binaire officiel = `/usr/local/bin/zivpn`, service de prod sur `:5667`) :
- Client fork (`URLHost = "zivpnudp"`, headers `Zivpnudp-*`, PSK ``hu``hqb`c``, auth `George34`) → **serveur officiel de prod** : `connected to server` (auth OK, statut 233, UDP enabled). ✅
- Même client → **serveur clone** (`/tmp/opencode/zivpn-clone-test` sur `:5668`) : connecté aussi. ✅
- Avec `URLHost = "hysteria"` → le serveur officiel répond `HTTP status code: 404`. ❌

**Config serveur de prod** (`/etc/zivpn/config.json`, secrets) : `listen :5667`, `obfs "zivpn"` (string — accepté grâce au `UnmarshalJSON` du type obfs, sinon `serverConfigObfs`), `auth {mode: passwords, config: [George34, ip9090]}`, TLS certs `/etc/zivpn/zivpn.crt|key`. Le check TLS du binaire retourne `empty cert or key path` sauf si lancé depuis le WorkingDirectory du service (`/etc/zivpn`) — artefact viper de résolution de chemins.

**Comportements du binaire reproduits par le clone** :
- `--help` → `UDP tunneling from ZIVPN` + `Version:\t1.5.0\nBuildDate:\t...\nAuthors:\tZI` (format 3 champs, pas le 6 champs upstream). Version officielle = 1.5.0, build 2023-12-29.
- `client --help` → `Run as client mode` ; `server --help` → `Server mode` ; `ping --help` → description TCP ping (help cobra court-circuité).
- Client : kill-switch + json5 sur le **chemin** de config → `unexpected end of JSON input` (sans `-c`) / `invalid character 't' in comment` (avec `-c`).
- Serveur : lit le **contenu** du fichier de config + json5, accepte `obfs` string, `auth.mode passwords`.
- Les commandes `check-update`, `version` et le flag `--disable-update-check` sont **absents** du binaire officiel (retirés du fork).

---

## 12. Fonctionnalité ajoutée : quota mensuel par password + API stats gRPC (2026-08-16)

**Besoin** : limiter la consommation de chaque password (usage commercial), avec un quota fixe **par mois** (reset le 1er du mois), déconnexion au dépassement, et une consultation **temps réel** fiable de la conso — sans port HTTP exposé ni logs volumineux. Méthode retenue (sur demande de l'utilisateur) : technique d'API **façon Xray-core/v2ray-core** (gRPC `StatsService` sur localhost).

**Implémentation (clone uniquement, pas dans le binaire officiel)** :
- `app/internal/utils/datasize.go` : `ParseDataSize` (base 1000 SI ; unités `B/KB/MB/GB/TB/PB` + `KiB/MiB/GiB/TiB/PiB`).
- `extras/trafficlogger/quota.go` : `QuotaTrafficLogger` — compteurs par password, quota mensuel, `Log(id, tx, rx) (ok bool)` (false = déconnexion), persistance JSON sur disque (`month`, `quotas`, `used`), reset auto au changement de mois, callback `OnExceed`, méthodes `Usage/Quota/ResetUsage/IDs`.
- `extras/trafficlogger/multi.go` : `MultiTrafficLogger` (combine quota + traffic stats).
- `extras/auth/passwords.go` : l'authenticator retourne **le password comme `id`** (avant : `"user"` fixe) pour compter par password.
- `extras/statsservice/` : proto gRPC `StatsService` (`GetStats`/`QueryStats`/`ResetStats`, champs `Stat{name,value,quota,updated}`), généré avec protoc 3.21 + protoc-gen-go 1.34.1 + protoc-gen-go-grpc 1.4.0 (impose grpc ≥1.64 ; grpc 1.64.0 et protobuf 1.33.0 ajoutés à `extras/go.mod`). Serveur gRPC + helper client `DialStatsService`.
- `app/cmd/server.go` : champs config `quota` (`map[string]string`), `quotaStateFile`, `statsAPI.listen` ; `fillTrafficLogger` installe le `QuotaTrafficLogger` + `runQuotaStateSaver` (ticker 30s) + démarre le serveur gRPC.
- `app/cmd/stats.go` : sous-commande `zivpnudp stats --addr <host:port>` (défaut `127.0.0.1:10088`) qui interroge `QueryStats` et affiche un tableau `PASSWORD / USED / QUOTA / USED%`.

**Config prod** (`/etc/zivpn/config.json`) :
```json
"quota": { "George34": "100GB", "ip9090": "100GB" },
"quotaStateFile": "/etc/zivpn/quota-state.json",
"statsAPI": { "listen": "127.0.0.1:10088" }
```

**Validation empirique** (clone test) :
- Client fork (headers `Zivpnudp-*`, obfs salamander PSK ``hu``hqb`c``) → serveur clone : `connected to server`, `client connected {"id": "George34"}` (l'id = password). ✅
- Trafic TCP via SOCKS5 → `USED` monte en temps réel (API) ; état persisté `{"month":"2026-08","quotas":{...},"used":{"George34":4071}}`. ✅
- Quota `1KB` → WARN `password quota exceeded, disconnecting client {"id": "George34", "used": 3106, "quota": 1000}` + `traffic logger requested disconnect` + `client disconnected`. ✅
- Redémarrage serveur → conso restaurée depuis le fichier d'état. ✅
- En prod : `stats API server up and running {"listen":"127.0.0.1:10088"}`, `zivpn stats` affiche `George34 0 B / 100.00 GB` et `ip9090 0 B / 100.00 GB`. ✅

**Piège de la PSK** : le PSK Salamander forcé par le serveur est ``hu``hqb`c`` (9 caractères, **double** backtick). Une config client avec un seul backtick (`hu`hqb`c`) fait timeout au handshake (le serveur répond mais le client ne décode rien).

---

## Modifications détectées vs source upstream
- Variable d'env debug Brutal renommée : `HYSTERIA_BRUTAL_DEBUG` → **`ZIVPN_UDP_BRUTAL_DEBUG`**.
- Présence d'une classe custom `*adaptiveConnFactory` (`New` avec obfs optionnelle) dans `app/cmd` — absent du commit upstream `405572d` (ajout local pour combiner factory UDP + obfs).
- Protocole auth/handshake modifié : headers `Zivpnudp-Auth`, `Zivpnudp-Padding`, `Zivpnudp-CC-RX`, `Zivpnudp-UDP` (au lieu de `Hysteria-*`), **`URLHost = "zivpnudp"`** (au lieu de `hysteria`), et `auth.mode` étendu (`passwords` supporté côté serveur, `cmd`/`http`/`https`/`command`/`userpass`/`passwords`). Cartographie complète des 4 fonctions auth (`AuthRequestFromHeader/ToHeader`, `AuthResponseFromHeader/ToHeader`) en section 10, validation d'interop en section 11.
- Strings custom présentes : `udp-zivpn`, `./udp-zivpn client --config /etc/udp-zivpn/client.json`, `$HOME/.zivpn`, `Ping mode`, `signature ping mode`, `zivpn_udp`, ``hu``hqb`c``.
- Commandes/flag upstream **retirés** : `check-update`, `version`, `--disable-update-check` (aucune string update-check dans le binaire). Help cobra court-circuité (affiche seulement le Short/Long). Format version réduit à 3 champs (`Version`/`BuildDate`/`Authors`), logo `UDP tunneling from ZIVPN`, Use `zivpnudp`.
- **Client cassé par design** : kill-switch `signature` (9 chars == ``hu``hqb`c``) + config relue via `yosuke-furukawa/json5` (backticks de la PSK → erreur de parse) → le client officiel ne peut pas démarrer (section 8).
- Config serveur lue aussi en JSON5 (`yosuke-furukawa/json5` v0.1.1) — le serveur accepte donc les fichiers `.json5` (clés nues, commentaires, etc.).