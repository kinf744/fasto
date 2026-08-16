# Analyse du binaire `zivpn` — Tunnel UDP

## Identité du binaire

- **Fichier** : `/usr/local/bin/zivpn` (ELF64 x86-64, statique, stripped, 11.3 Mo)
- **Langage/outillage** : Go `go1.21.4` (buildid `1No4RJuLvCbrAjAOW7dN/...`)
- **Logiciel réel** : **Hysteria 2** (`github.com/apernet/hysteria/app`)
  - Commit source : `405572dc6e335c29ab28011bcfa9e0db2c45a4b4` (2023-12-08), build local modifié (`vcs.modified=true`)
  - Les sources exactes ont été récupérées à ce commit dans `/tmp/opencode/hysteria-src/`
- **Rôles** : client et serveur de tunnel (hysteria2) en un seul binaire, CLI type Cobra (`hysteria client|server|...`)

## Archétypes et dépendances clés

- `github.com/apernet/hysteria/core` : cœur du tunnel (client, server, protocol, congestion)
- `github.com/apernet/quic-go` v0.40.1 : transport QUIC (datagrams pour l'UDP)
- `github.com/apernet/hysteria/extras` : obfs (Salamander), udphop, auth
- `github.com/txthinking/socks5` : support client SOCKS5
- Algorithme de congestion **Brutal** (package `core/internal/congestion/brutal` + `bbr`) : contrôle de débit agressif basé sur un RTT/bandwidth cible

## Fonctionnement du tunnel UDP

### Vue d'ensemble

Le tunnel UDP fonctionne par **multiplexage de sessions UDP sur un seul QUIC datagram channel** :

1. Le client Hysteria ouvre une connexion **QUIC** (avec TLS + auth) vers le serveur.
2. Sur cette connexion, les paquets UDP des clients locaux sont encapsulés dans des **messages de protocole** (payload des datagrams QUIC).
3. Le serveur démultiplexe par `SessionID`, maintient une **table NAT-like de sessions UDP**, et forward chaque message vers la destination réelle via une socket UDP.
4. Les réponses de la destination sont re-encapsulées et renvoyées au client par le même canal QUIC.

### Format du message UDP (`core/internal/protocol/proxy.go`)

```
UDP message wire format:
  Session ID     uint32   big-endian        (4 octets)
  Packet ID      uint16   big-endian        (2 octets)
  Fragment ID    uint8                      (1 octet)
  Fragment count uint8                      (1 octet)
  Address length QUIC varint (1/2/4/8 o.)   ← longueur de l'adresse cible
  Address        bytes                      ← "IP:port" ou "hostname:port" cible
  Data           bytes                      ← payload UDP
```

- `HeaderSize() = 8 + len(varint(lAddr)) + lAddr` (cf. désassemblage `(*UDPMessage).HeaderSize` @ `0x8b6340`)
- `MaxUDPSize = 4096`, `MaxAddressLength = 2048`, `MaxPaddingLength = 4096`
- La taille de l'adresse est bornée à 2048 pour prévenir les attaques DoS ("invalid address length")

### Fragmentation (`core/internal/frag/frag.go`)

- Si un datagram dépasse la taille max QUIC (`quic.ErrMessageTooLarge`), le message est **fragmenté** : même `SessionID`, `PacketID` non nul aléatoire (1..0xFFFF), `FragID`/`FragCount` renseignés.
- Chaque fragment est sérialisé avec le même header (adresse répétée dans chaque fragment).
- Le récepteur utilise un `Defragger` qui ne gère qu'un seul `PacketID` à la fois (état écrasé si un nouveau paquet arrive avant complétion).

### Côté client (`core/client/udp.go`)

- `udpSessionManager` alloue un **`SessionID` croissant** (à partir de 1) par connexion UDP locale (typiquement une session SOCKS5 UDP).
- `(*udpConn).Send()` : essaye sans fragmentation, puis fragmente si nécessaire.
- `(*udpConn).Receive()` : reçoit les messages, les défragmente, retourne `(data, addr)`.
- `udpIOImpl.SendMessage/ReceiveMessage` : wrapper sur `quic.Connection.SendDatagram()/ReceiveDatagram()`.
- Buffer d'envoi : `make([]byte, protocol.MaxUDPSize)`.

### Côté serveur (`core/server/udp.go`)

- `udpSessionManager` : table `map[uint32]*udpSessionEntry` **identique à un NAT**.
  - Une nouvelle `SessionID` reçue ⇒ création d'une socket UDP locale vers la destination (`io.UDP(msg.Addr)`).
  - `ReceiveLoop` : lit les paquets UDP entrants, les encapsule (`SessionID` fixé, `PacketID=0`, `FragCount=1`) et les renvoie au client, avec fragmentation auto si nécessaire.
  - `idleCleanupLoop` (toutes les 1 s) : ferme les sessions dont `Last` (dernier échange) dépasse `idleTimeout` configurable.
- `eventLogger` : log des ouvertures/fermetures de sessions UDP.

## Obfuscation Salamander (`extras/obfs`)

But : rendre le trafic QUIC **indiscernable d'UDP aléatoire** pour les systèmes de détection (DPI), puisque QUIC standard a des en-têtes identifiables.

### Principe — XOR avec clé dérivée par paquet

Format d'un paquet obfusqué : `[8 octets de sel aléatoire][payload XOR-clé]`

- **Émission** (`Obfuscate`, désassemblé @ `0x8E6A80`) :
  1. génère 8 octets de sel aléatoire (`rand.Rand`, seed `time.Now().UnixNano()`) en tête de paquet ;
  2. calcule `key = BLAKE2b-256(PSK || sel)` ;
  3. `out[i+8] = payload[i] XOR key[i % 32]`.
- **Réception** (`Deobfuscate` @ `0x8E6C20`) :
  1. lit les 8 premiers octets (le sel) ;
  2. recalcule la même clé (`BLAKE2b.Sum256`, désassemblé @ `0x8E00C0`) ;
  3. XOR inverse pour retrouver le payload.
- La clé **change à chaque paquet** (sel aléatoire) ⇒ pas de keystream rejouable, coût CPU d'un hash BLAKE2b-256 par paquet.

### Transparence vis-à-vis de quic-go

- `obfsPacketConn`/`obfsPacketConnUDP` implémentent `net.PacketConn` et enveloppent la vraie socket UDP.
- `ReadFrom`/`WriteTo` **déobfusquent/obfusquent** avant de rendre les données à quic-go : quic-go croit parler UDP normal.
- Quand le sous-jacent est un `*net.UDPConn`, on utilise `obfsPacketConnUDP` pour conserver les optimisations (`SetReadBuffer`, `SetWriteBuffer`, `SyscallConn`).
- Les paquets invalides (`Deobfuscate` retourne 0) sont **silencieusement ignorés** et on relit (boucle dans `ReadFrom`).

### Branchement dans le binaire

- Serveur (`app/cmd/server.go` ~l.227) et client (`app/cmd/client.go` ~l.193) : selon `obfs.type` :
  - `""` ou `"plain"` → socket nue ;
  - `"salamander"` → `obfs.NewSalamanderObfuscator([]byte(password))` + `obfs.WrapPacketConn(conn, ob)`.
- Le `Conn` ainsi enveloppé devient la `net.PacketConn` passée à quic-go.
- Il existe aussi `fillConn` (client) qui applique l'obfs **avant** quic-go (`Obfuscator` optionnel).

### Notes de sécurité

- Ce n'est **pas du chiffrement** : le sel est en clair et seule la clé XOR est dérivée du PSK. La confidentialité vient du TLS/QUIC par-dessus. Salamander ne sert qu'à **brouiller les signatures** de paquets.
- PSK minimum 4 octets (sinon `ErrPSKTooShort`) ; une clé faible est brute-forcable (BLAKE2b est rapide).

## Où sont les réponses à vos captures

Vos captures (`zivpn_porthop_30s.txt`, `zivpn_client184_20s.txt`, etc.) devraient montrer :
- Du trafic **QUIC UDP 443** (chiffré) entre client et serveur — c'est le canal du tunnel.
- Du trafic **UDP sortant** du serveur vers les destinations cibles (le "tunnel").

## Outils installés pour l'analyse

| Outil | Rôle | Emplacement |
|---|---|---|
| GoReSym | Extraction des symboles/métadonnées Go depuis le pclntab | `~/go/bin/GoReSym` |
| redress | Reconstruction symboles + projection source | `~/go/bin/redress` |
| radare2 | Désassemblage interactif | `/usr/bin/r2` |
| go 1.22 | Divers (buildid, `go tool objdump`) | `/usr/bin/go` |

Sources du commit exact : `/tmp/opencode/hysteria-src/`
