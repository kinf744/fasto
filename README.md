# fasto

Panel Kighmu — gestion d'utilisateurs SSH/V2Ray/DNS avec quotas.

## SSH banners

Deux niveaux de banner coexistent pour les tunnels SSH :

### 1. Banner pré-auth par utilisateur (apps tunnel)

Les apps (HTTP Injector, NetMod, VPN Injector) ouvrent des sessions SSH **sans
shell** : aucun banner post-login ne peut s'afficher. C'est pourquoi un banner
**pré-auth** est généré par utilisateur via `sshd Match User` + `Banner`.

- Généré par `_gen_user_banners()` → `/etc/kighmu/banners/<user>`
- Relié au cron `--ssh-quota-sync` (toutes les 5 min)
- Config sshd : `/etc/ssh/sshd_config.d/99-kighmu-banners.conf`
- **Sans cadre ni codes ANSI** : les transports tunnel (HTTP Injector, NetMod,
  VPN Injector) suppriment l'octet ESC (`\x1b`) et dégradent les bordures
  (`┃`→`|`, emoji perdus) — les couleurs ne peuvent donc pas fonctionner sur le
  chemin pré-auth. Le fichier banner est donc en texte brut, titre centré,
  lignes alignées, aucun caractère de contrôle.
- Affichage : `Utilisateur`, `Expiration` (jours restants colorés), `Data`
  (`fmt_bytes` → « 36.4 MB / 78.0 GB »), verrouillage éventuel.
- Le banner **post-login** (vraie session shell) garde sa version encadrée et
  colorée via `_banner_text(user, plain=False)`.

### 2. Banner post-login dynamique (`/usr/local/bin/ssh-banner.sh`)

Affiché aux sessions **avec shell** via `pam_exec` dans `/etc/pam.d/sshd` :

```
session optional pam_exec.so quiet stdout /usr/local/bin/ssh-banner.sh
```

Style « DARNIX » : centrage dynamique sur la ligne la plus longue, couleurs
ANSI 256 (`\033[38;5;Nm`), titre dégradé, marque « VPS-PRO SSH TUNNEL ».

Lignes affichées (FR) :

- `Utilisateur` : `$PAM_USER`
- `Expire` : `chage -l` (repli sur `exp=` du meta), sinon « ∞ »
- `Jours restants` : vert (>7), orange (≤7), rouge « EXPIRÉ »
- `Consommé` : `used=` (octets, formaté) + `(Max: X GB)` en violet si `quota=` > 0
- `Limite IP` : `limit=` si présent

Sources de données : `/etc/kighmu/users/<user>` (`used=`, `quota=`, `limit=`)
et `chage -l <user>` (expiration). Le script ne plante jamais en cas de champ
absent.

### Personnalisation

- **Marque** : changer `gradient "VPS-PRO SSH TUNNEL"` dans `ssh-banner.sh`
  (dégradé vert→orange). Modifier le titre du banner pré-auth dans
  `_banner_text()` de `install2.py`.
- **Couleurs** : variables ANSI 256 en tête de `ssh-banner.sh`
  (`MINT`, `BLUE`, `REDO`, `PINK`, `PURPLE`, `ORANGE`, `WHITE`, `GRAY`, `CYAN`).
  Attention : les couleurs ne s'affichent que sur le chemin post-login (vraie
  session shell). Le banner pré-auth envoyé aux apps tunnel doit rester sans
  codes ANSI (le transport les supprime).
- **Champs** : ajouter une ligne dans le tableau `rows` — le centrage se
  recalcule automatiquement sur la largeur visible (sans les codes ANSI).

### Rollback

- `/etc/pam.d/sshd` : sauvegarde automatique créée avant modification
  (`/etc/pam.d/sshd.bak-<ts>`). Restaurer puis supprimer la ligne `pam_exec`.
