# Contrat de comptage quota UDP zivpn (Kighmu)

Ce document est le **contrat d'architecture** du comptage de data zivpn.
Toute évolution du binaire ou du panneau (`install2.py`) DOIT le respecter.

## Principes fondateurs

1. **La clé de comptage est le password.** Le protocole zivpn ne transmet
   que le password (header `Zivpnudp-Auth`) : il EST l'identité du compte.
2. **Un password est unique tant qu'il est en vie.** Le registre
   `/etc/zivpn/issued-passwords.txt` (verrou `flock`) enregistre chaque
   password « en cours d'utilisation ». Il est **libéré uniquement après
   purge complète** du compte (state + miroir `.bak` + quarantaine + méta +
   backups nettoyés) : il redevient alors réutilisable, le nouveau compte
   repartant de zéro. Si des résidus subsistent, la réutilisation est
   refusée (code 4) pour empêcher tout héritage de compteur.
3. **Le compteur appartient au compte, pas au credential.** Au changement de
   password, la clé est renommée dans `quota-state.json` : aucune perte.
4. **Séparation enforcement / comptabilité** :
   - Binaire = enforcement temps réel (coupure au dépassement).
   - Panneau = comptabilité lifetime (`used_total_zivpn`), affichage, décisions commerciales.
5. **Le compteur binaire est la vérité terrain.** Le panneau ne fait que
   projeter ; le guard réconcilie de façon strictement unidirectionnelle
   (config régénérée depuis les méta, jamais l'inverse).

## Persistance (binaire v2)

- `quota-state.json` : format **versionné** (`"version": 2`) avec **checksum
  CRC32**. Un state altéré ou partiellement écrit est refusé.
- Écriture **atomique** (tmp + rename) + **miroir `.bak`** : la corruption du
  fichier principal ne remet jamais les compteurs à zéro — le `.bak` est chargé.
- Flush périodique configurable : `quotaFlushInterval` (secondes, défaut
  historique 30 s, le panneau pose 15 s).
- Format legacy (sans version/checksum) accepté en lecture et migré au
  premier flush — aucune perte lors de l'upgrade.

## Redondance panneau

- **Backups horaires** : `/etc/zivpn/backups/quota-state-*.json[.bak]`,
  rétention 7 jours, idempotents (cron `7 * * * * --zivpn-state-backup`).
- **Restauration** : `--zivpn-state-restore` / auto dans le guard si le state
  est corrompu (miroir `.bak` d'abord, puis backup le plus récent).
- **Journal d'événements** : `/var/log/zivpn-quota-events.jsonl`
  (créations, suppressions, changements de password, blocages, déblocages,
  migrations de compteur, dérives config, restaurations, partages détectés).
  Append-only, roté par logrotate, rejouable en cas de litige.

## Observabilité

- `kighmu --zivpn-status [user]` : vue unifiée (compteur brut binaire, cumul
  lifetime panneau, quota, % consommé, état actif/bloqué/quarantaine).
- `kighmu --zivpn-share-detect [minutes]` : passwords utilisés depuis plus de
  4 IPs distinctes (détection de revente/partage) — alerte journalisée.
- Guard (cron */5) : répare config/compteur, journalise toute dérive avec le
  détail (clés manquantes/extra/valeurs divergentes).

## Limites assumées (protocole)

- Deux comptes au **même password** restent indiscernables sur le fil → le
  panneau refuse les doublons (voir principe 1).
- Tolérance d'un datagramme à la coupure de dépassement (≈1,5 Ko) : négligeable.
- Jusqu'à `quotaFlushInterval` secondes de comptage peuvent être perdues en
  cas de kill brutal entre deux flushes.
