# sshws v2

TCP RAW Injector + WebSocket → SSH (durci, stdlib uniquement).

## Architecture

```
WS  80  : clients ──clair──> sshws:80 ──> 127.0.0.1:1092 (SSH)
WSS 443 : clients ──TLS──> HAProxy:443 (déchiffre) ──clair──> backend ssh-wss ──> sshws:127.0.0.1:80
```

Le binaire reste en clair par défaut ; `-tls-cert`/`-tls-key` pour WSS direct
(déconseillé, préférer HAProxy).

## Flags

Compat v1 : `-listen -target-host -target-port`.

```
-mode auto          raw|ws|auto (auto = vrai WS si frame masquée, sinon RAW legacy)
-paths /ssh-wss,/ssh-ws,/ws   (404 si Upgrade mais path inconnu)
-allow-raw=true     injecteur TCP sans Upgrade (compat v1, 200 OK)
-allow-proxy=true   parse PROXY v1 HAProxy auto (vraie IP en logs)
-max-conns 2048 -handshake-timeout 5s -idle-timeout 5m -dial-timeout 5s
-tls-cert/-tls-key  WSS autonome (vide = clair derrière HAProxy)
-metrics-listen 127.0.0.1:14080 (/metrics, /healthz)
-log-file "" (stderr/journal), -log-level info|quiet|debug
```

## Build

```bash
GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o sshws .
GOOS=linux GOARCH=arm64 go build -trimpath -ldflags="-s -w" -o sshws-arm64 .
```

## Déploiement

`install2.py: install_sshws()` télécharge l'asset `sshws` de la release
`v1.0.0-zivpn`, réécrit l'unité systemd v2 (`-mode auto -paths ...`,
`RestartSec=2`), garantit `backend ssh-wss -> 127.0.0.1:80` dans HAProxy,
puis `kighmu --sshws-upgrade` pour migrer un VPS existant.
