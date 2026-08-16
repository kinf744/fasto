# zivpn-clone

Clone fonctionnel du tunnel UDP **zivpn**, reconstruit par reverse-engineering
du binaire officiel puis recompilé depuis un fork de [Hysteria](https://github.com/apernet/hysteria).
Interopérable avec le protocole zivpn (handshake, obfs Salamander à PSK fixe,
mode `auth.passwords`) et étendu avec la gestion de **quota de données par
utilisateur** (`quotaStateFile` + `statsAPI`).

## Contenu

| Chemin | Description |
|---|---|
| `zivpn` | Binaire clone (Linux x86_64). Checksum dans `zivpn.md5`. |
| `source/` | Code source Go du clone (fork Hysteria + modifications zivpn). |
| `docs/` | Méthodologie complète du clonage et de l'analyse. |

## Documentation

- `docs/CLONE_ZIVPN_TECHNIQUE.md` — méthodologie de clonage, étape par étape.
- `docs/FONCTIONNEMENT.md` — fonctionnement général du tunnel.
- `docs/APPROFONDISSEMENTS.md` — analyse approfondie (protocole, auth, obfs, quota).
- `docs/CAPTURES_ET_AUTH.md` — captures réseau et mécanisme d'authentification.

## Build

Le binaire est produit depuis `source/` (chaîne de build Hysteria, `hyperbole.py`).

## Licence

Basé sur Hysteria — voir `source/LICENSE.md` (Apache-2.0). Les modifications
zivpn héritent de cette licence.
