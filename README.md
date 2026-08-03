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
- **Banner HTML** (`_banner_html`) : aucun octet ESC — les transports tunnel
  (HTTP Injector, NetMod, VPN Injector) suppriment `\x1b`, donc les codes ANSI
  classiques ne fonctionnent pas sur le chemin pré-auth. Le HTML est livré tel
  quel et rendu en couleur par les apps. Marquage VPS-PRO, dégradé `▬ஜ۩۞`,
  champs colorés (👤 Utilisateur, 📅 Expire, ⏳ Jours restants, 📊 Consommé
  avec `(Max: X Go)`, 🌐 Limite IP si présente), centrage via
  `<p style="text-align:center">`.
- Affichage : `Utilisateur`, `Expiration` (jours restants), `Data`
  (`_fmt_fr` → « 85.2 Mo / 78 Go »), `Limite IP`, verrouillage éventuel.
- Le banner **post-login** (vraie session shell) garde sa version encadrée et
  colorée via `_banner_text(user)`.

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
  `_banner_html()` de `install2.py` (`<font color='#00FFCC'>VPS-PRO</font>`).
- **Couleurs** : variables ANSI 256 en tête de `ssh-banner.sh`
  (`MINT`, `BLUE`, `REDO`, `PINK`, `PURPLE`, `ORANGE`, `WHITE`, `GRAY`, `CYAN`).
  Pour le banner pré-auth (HTML), les couleurs sont les codes hex des balises
  `<font color='#...'>` dans `_banner_html()`.
  Attention : les couleurs ANSI ne s'affichent que sur le chemin post-login
  (vraie session shell). Le banner pré-auth envoyé aux apps tunnel doit rester
  en HTML (le transport supprime les octets ESC).
- **Champs** : ajouter une ligne dans le tableau `rows` — le centrage se
  recalcule automatiquement sur la largeur visible (sans les codes ANSI).

### Rollback

- `/etc/pam.d/sshd` : sauvegarde automatique créée avant modification
  (`/etc/pam.d/sshd.bak-<ts>`). Restaurer puis supprimer la ligne `pam_exec`.
