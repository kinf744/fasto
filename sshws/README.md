# sshws (origine)

TCP RAW Injector + WebSocket → SSH (version d'origine, port 80 direct).

> Note : la v2 durcie (`mode auto`, handshake strict, TLS optionnel, métriques)
> a été évaluée puis **retirée** sur décision d'exploitation : retour au
> binaire d'origine, jugé meilleur en production. Le WSS via HAProxy
> (`backend ssh-wss`, path `/ssh-wss`) est **supprimé et nettoyé**.

## Build

```bash
GOOS=linux GOARCH=amd64 go build -trimpath -ldflags="-s -w" -o sshws .
GOOS=linux GOARCH=arm64 go build -trimpath -ldflags="-s -w" -o sshws-arm64 .
```

## Déploiement

`install2.py: install_sshws()` télécharge l'asset `sshws` de la release
`v1.0.0-zivpn` (binaire d'origine), vérifie le SHA-256 en Python,
écrit l'unité systemd d'origine puis `kighmu --sshws-upgrade`
réinstalle/redémarre sur un VPS existant.
