#!/usr/bin/env bash
# ==============================================================================
#  VENTES v2.0 — Gestionnaire de Licences · édition simple
#  Un seul écran · deux questions · clé générée · jamais d'UUID à taper
#  Compatible Ubuntu 22.04/24.04+ · Base identique à la v1.x (migration nulle)
# ==============================================================================
set -Eeuo pipefail
IFS=$' \t\n'

# ── Auto-install ──────────────────────────────────────────────────────────────
if [[ "$(readlink -f "$0")" != "/usr/local/bin/ventes" ]]; then
    cp "$0" /usr/local/bin/ventes
    chmod 700 /usr/local/bin/ventes
    exec /usr/local/bin/ventes "$@"
fi

[[ $EUID -eq 0 ]] || { echo "ERREUR : à exécuter en root." >&2; exit 1; }
umask 077

readonly VERSION="2.0"
readonly DB_DIR="/etc/ventes"
readonly DB="${DB_DIR}/ventes.db"
readonly CONFIG="${DB_DIR}/config.json"
readonly CHKSUM_FILE="${DB_DIR}/.checksum"
readonly BACKUP_DIR="${DB_DIR}/backups"
readonly DAILY_KEEP=7

readonly RST='\033[0m' BLD='\033[1m' DIM='\033[2m'
readonly RED='\033[0;31m' GREEN='\033[0;32m' YELLOW='\033[0;33m'
readonly BLUE='\033[0;34m' CYAN='\033[0;36m' WHITE='\033[0;97m' GRAY='\033[0;90m'

trap 'echo' EXIT
trap 'echo; exit 130' INT

# ==============================================================================
#  UTILITAIRES
# ==============================================================================
_sql()       { sqlite3 "$DB" "$@"; }
_esc()       { local s="$1"; s="${s//\'/\'\'}"; printf '%s' "$s"; }
_now()       { date '+%Y-%m-%d %H:%M:%S'; }
_today()     { date '+%Y-%m-%d'; }
_expire_at() { [[ "$1" == "0" ]] && { echo "9999-12-31"; return; }; date -d "+$1 days" '+%Y-%m-%d'; }
_days_until(){ [[ "$1" == "9999-12-31" ]] && { echo 99999; return; }; echo $(( ($(date -d "$1" +%s) - $(date -d "$(_today)" +%s)) / 86400 )); }

_ok()   { printf '  \033[0;32m✓\033[0m  %b\n' "$*"; }
_err()  { printf '  \033[0;31m✗\033[0m  %b\n' "$*" >&2; }
_info() { printf '  \033[0;34mℹ\033[0m  %b\n' "$*"; }
_warn() { printf '  \033[0;33m⚠\033[0m  %b\n' "$*"; }
_pause(){ printf '  \033[0;90mEntrée pour continuer...\033[0m' >&2; read -r; printf '\n' >&2; }

ASK() {
    local q="$1" def="${2:-}"
    printf '  \033[0;33m►\033[0m \033[0;97m%s\033[0m' "$q" >&2
    if [[ -n "$def" ]]; then printf ' \033[0;90m[%s]\033[0m' "$def" >&2; fi
    printf ' : ' >&2
    REPLY_VAL=""
    read -r REPLY_VAL || true
    if [[ -z "$REPLY_VAL" && -n "$def" ]]; then REPLY_VAL="$def"; fi
    return 0
}

CONFIRM() {
    printf '  \033[0;33m?\033[0m \033[0;97m%s\033[0m \033[0;90m(o/N)\033[0m : ' "$1" >&2
    local r=""; read -r r
    [[ "$r" =~ ^[oOyY]$ ]]
}

_gen_uuid() {
    local h; h=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
    printf '%s-%s-4%s-%s%s-%s' "${h:0:8}" "${h:8:4}" "${h:13:3}" \
        "$(printf '%x' $(( 0x${h:16:2} & 0x3f | 0x80 )))" "${h:18:2}" "${h:20:12}"
}
_gen_key() {
    local len=$(( 32 + (RANDOM % 17) ))
    dd if=/dev/urandom bs=64 count=1 2>/dev/null | md5sum | cut -d' ' -f1 | head -c "$len"
}

LICENSE_SECRET="$(printf '%s' 'KighmuPanel2026!@#LicenseBombSecureKey_X7k9m2' | sha256sum | cut -d' ' -f1)"
_pack_token() {
    local msg="$1|$2" sig
    sig=$(printf '%s' "$msg" | openssl dgst -sha256 -hmac "$LICENSE_SECRET" 2>/dev/null | cut -d' ' -f2)
    printf '%s|%s' "$msg" "$sig"
}

# ==============================================================================
#  INIT — auto-réparation base corrompue (jamais de blocage silencieux)
# ==============================================================================
_check_deps() {
    command -v sqlite3 &>/dev/null && return 0
    apt-get update -qq 2>/dev/null || true
    apt-get install -y -qq sqlite3 2>/dev/null || true
    command -v sqlite3 &>/dev/null || { _err "sqlite3 requis."; exit 1; }
}

_apply_schema() {
    _sql "
        CREATE TABLE IF NOT EXISTS licenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid TEXT UNIQUE NOT NULL,
            license_key TEXT UNIQUE NOT NULL,
            client_name TEXT NOT NULL,
            client_phone TEXT DEFAULT '',
            client_email TEXT DEFAULT '',
            notes TEXT DEFAULT '',
            status TEXT NOT NULL DEFAULT 'ACTIVE',
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL,
            activated_at TEXT DEFAULT NULL,
            last_checkin TEXT DEFAULT NULL,
            hw_binding TEXT DEFAULT NULL
        );
        CREATE TABLE IF NOT EXISTS audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL, action TEXT NOT NULL,
            license_uuid TEXT DEFAULT NULL, details TEXT DEFAULT '',
            user TEXT DEFAULT 'admin'
        );
        PRAGMA user_version = 2;
    " && return 0
    return 1
}

_init_db() {
    _check_deps
    mkdir -p "$DB_DIR" "$BACKUP_DIR"

    if [[ -f "$DB" ]] && ! _sql "PRAGMA integrity_check;" >/dev/null 2>&1; then
        chattr -i "$DB" 2>/dev/null || true
        local stamp="${DB}.corrupted.$(date '+%Y%m%d-%H%M%S')"
        cp "$DB" "$stamp" 2>/dev/null || true
        rm -f "$DB" 2>/dev/null || true
        _warn "Base corrompue archivée → $(basename "$stamp")"
    fi

    if ! _apply_schema; then
        chattr -i "$DB" 2>/dev/null || true
        cp "$DB" "${DB}.unreadable.$$" 2>/dev/null || true
        rm -f "$DB" 2>/dev/null || true
        _apply_schema || { _err "Impossible d'initialiser la base."; exit 1; }
        _warn "Base reconstruite à neuf."
    fi

    [[ -f "$CONFIG" ]] || printf '{"version":"%s","created_at":"%s"}\n' "$VERSION" "$(_now)" > "$CONFIG"
    sha256sum "$0" > "$CHKSUM_FILE" 2>/dev/null || true
}

_silent_backup() {
    [[ -f "$DB" ]] || exit 0
    local f="${BACKUP_DIR}/ventes-$(_today).db.gz"
    sqlite3 "$DB" ".backup '${BACKUP_DIR}/tmp.db'" 2>/dev/null || cp "$DB" "${BACKUP_DIR}/tmp.db"
    gzip -cf "${BACKUP_DIR}/tmp.db" > "$f" 2>/dev/null || true
    rm -f "${BACKUP_DIR}/tmp.db"
    ls -1t "${BACKUP_DIR}"/ventes-*.db.gz 2>/dev/null | tail -n +$((DAILY_KEEP+1)) | xargs -r rm -f 2>/dev/null || true
}

_ensure_cron() {
    crontab -l 2>/dev/null | grep -q '/usr/local/bin/ventes' && return 0
    (crontab -l 2>/dev/null; echo '0 4 * * * /usr/local/bin/ventes >/dev/null 2>&1') | crontab - 2>/dev/null || true
}

# ==============================================================================
#  TABLEAU — navigation par N° de ligne (zéro UUID)
# ==============================================================================
declare -a ROW_UUID=()

_show_table() {
    ROW_UUID=()
    local filter="${1:-}" where="" row n name exp status days dot
    [[ -n "$filter" ]] && where="WHERE $filter"

    printf '  %-4s %-22s %-12s %s\n' "$(printf '%b' "${GRAY}N°${RST}")" \
        "$(printf '%b' "${GRAY}CLIENT${RST}")" "$(printf '%b' "${GRAY}EXPIRE${RST}")" \
        "$(printf '%b' "${GRAY}STATUT${RST}")"
    printf '  \033[0;90m──────────────────────────────────────────────\033[0m\n'

    while IFS='|' read -r uuid name exp status; do
        [[ -z "$uuid" ]] && continue
        ROW_UUID+=("$uuid")
        n=${#ROW_UUID[@]}
        case "$status" in
            SUSPENDED) dot="${YELLOW}⏸ suspendue${RST}" ;;
            DELETED)   dot="${GRAY}○ supprimée${RST}" ;;
            BANNED)    dot="${RED}● bannie${RST}" ;;
            *)
                if [[ "$exp" == "9999-12-31" ]]; then dot="${GREEN}● illimitée${RST}"
                else
                    days=$(_days_until "$exp")
                    if   (( days < 0 )); then dot="${RED}● expirée${RST}"
                    elif (( days <= 3 )); then dot="${RED}● ${days}j${RST}"
                    elif (( days <= 7 )); then dot="${YELLOW}● ${days}j${RST}"
                    else dot="${GREEN}● ${days}j${RST}"; fi
                fi ;;
        esac
        printf '  \033[0;36m%-4s\033[0m \033[0;97m%-22s\033[0m \033[0;90m%-12s\033[0m %b\n' \
            "$n" "${name:0:22}" "$exp" "$dot"
    done < <(_sql "SELECT uuid, client_name, expires_at, status FROM licenses ${where} ORDER BY CASE status WHEN 'ACTIVE' THEN 0 WHEN 'SUSPENDED' THEN 1 ELSE 2 END, expires_at ASC;")
}

PICKED_UUID=""
_pick() {
    PICKED_UUID=""
    printf '\n' >&2
    _show_table "status != 'DELETED'"
    if (( ${#ROW_UUID[@]} == 0 )); then _info "Aucune licence enregistrée."; printf '\n' >&2; return; fi
    ASK "$1 (0 = annuler)"
    local i="$REPLY_VAL"
    [[ -z "$i" || "$i" == "0" ]] && { printf '\n' >&2; return; }
    if [[ "$i" =~ ^[0-9]+$ ]] && (( i >= 1 && i <= ${#ROW_UUID[@]} )); then
        PICKED_UUID="${ROW_UUID[$((i-1))]}"
    else
        _err "Numéro invalide."
    fi
    printf '\n' >&2
}

_card() {
    local uuid="$1" row name key exp status created reste
    row=$(_sql "SELECT client_name, license_key, expires_at, status, created_at FROM licenses WHERE uuid='$uuid';")
    IFS='|' read -r name key exp status created <<< "$row"
    if [[ "$exp" == "9999-12-31" ]]; then reste="illimité"; else reste="$((_days_until "$exp")) jours restants"; fi

    printf '\n'
    printf '  \033[0;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n'
    printf '  \033[0;97m\033[1m🔑 %s\033[0m  \033[0;90m· %s\033[0m\n' "$name" "$status"
    printf '  \033[0;34m━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n'
    printf '  \033[0;97mClé      :\033[0m \033[0;32m%s\033[0m\n' "$key"
    printf '  \033[0;97mExpire   :\033[0m \033[0;36m%s\033[0m \033[0;90m(%s)\033[0m\n' "$exp" "$reste"
    printf '  \033[0;97mCréée le :\033[0m \033[0;90m%s\033[0m\n' "$created"
    printf '  \033[0;97mToken    :\033[0m \033[0;2m%s\033[0m\n' "$(_pack_token "$key" "$exp")"
    printf '\n'
}

# ==============================================================================
#  ACTIONS
# ==============================================================================
act_create() {
    printf '\n  \033[0;97m\033[1m➕ NOUVELLE LICENCE\033[0m\n\n' >&2
    ASK "Nom du client"; local name="$REPLY_VAL"
    [[ -z "$name" ]] && { _info "Annulé."; return; }
    ASK "Durée en jours (0 = illimité)" "30"; local days="$REPLY_VAL"
    [[ "$days" =~ ^[0-9]+$ ]] || days=30

    local uuid key exp
    uuid=$(_gen_uuid); key=$(_gen_key); exp=$(_expire_at "$days")

    _sql "INSERT INTO licenses (uuid, license_key, client_name, status, created_at, expires_at)
          VALUES ('$uuid', '$key', '$(_esc "$name")', 'ACTIVE', '$(_now)', '$exp');" \
        && _sql "INSERT INTO audit (timestamp, action, license_uuid, details) VALUES ('$(_now)','CREATE','$uuid','$(_esc "$name")');"

    printf '\n'
    _ok "Licence créée pour $(printf '%b' "${WHITE}${name}${RST}")"
    printf '\n'
    printf '  ┌─────────────────────────────────────────┐\n'
    printf '  │ Clé : \033[0;32m\033[1m%-29s\033[0m │\n' "$key"
    printf '  └─────────────────────────────────────────┘\n'
    [[ "$days" != "0" ]] && printf '  Expire le \033[0;36m%s\033[0m \033[0;90m(+%sj)\033[0m\n' "$exp" "$days"
    printf '\n  \033[0;90m── À envoyer au client ───────────────────────\033[0m\n'
    printf '  bash <(curl -sL https://github.com/kinf744/fasto/raw/main/install.sh)\n'
    printf '  Clé : \033[0;32m%s\033[0m\n' "$key"
    printf '  \033[0;90m──────────────────────────────────────────────\033[0m\n\n'
}

act_list() {
    printf '\n  \033[0;97m\033[1m📋 LICENCES\033[0m\n'
    _show_table "status != 'DELETED'"
    if (( ${#ROW_UUID[@]} > 0 )); then
        ASK "N° pour voir la fiche (Entrée = retour)"
        local i="$REPLY_VAL"
        if [[ "$i" =~ ^[0-9]+$ ]] && (( i >= 1 && i <= ${#ROW_UUID[@]} )); then
            _card "${ROW_UUID[$((i-1))]}"
        fi
    fi
    printf '\n'
}

act_search() {
    printf '\n  \033[0;97m\033[1m🔍 RECHERCHER\033[0m\n\n' >&2
    ASK "Nom (ou partie)"; local term="$REPLY_VAL"
    [[ -z "$term" ]] && return
    local esc; esc=$(_esc "$term")
    local count
    count=$(_sql "SELECT COUNT(*) FROM licenses WHERE client_name LIKE '%${esc}%';")
    if (( count == 0 )); then _info "Aucun résultat pour « $term »."; printf '\n' >&2; return; fi
    printf '\n'
    ROW_UUID=()
    _show_table "client_name LIKE '%${esc}%'"
    if (( count == 1 )); then
        _card "${ROW_UUID[0]}"
    else
        ASK "N° pour voir la fiche (Entrée = retour)"
        local i="$REPLY_VAL"
        [[ "$i" =~ ^[0-9]+$ ]] && (( i >= 1 && i <= ${#ROW_UUID[@]} )) && _card "${ROW_UUID[$((i-1))]}"
    fi
    printf '\n' >&2
}

act_renew() {
    printf '\n  \033[0;97m\033[1m🔄 RENOUVELER / PROLONGER\033[0m\n' >&2
    _pick "N° de la licence"
    [[ -z "$PICKED_UUID" ]] && return
    local name exp
    IFS='|' read -r name exp <<< "$(_sql "SELECT client_name, expires_at FROM licenses WHERE uuid='$PICKED_UUID';")"
    _info "$name expire le $exp"
    ASK "Ajouter combien de jours ?" "30"; local days="$REPLY_VAL"
    [[ "$days" =~ ^[0-9]+$ ]] || days=30
    local new_exp
    if [[ "$days" == "0" ]]; then new_exp="9999-12-31"; else new_exp=$(date -d "+${days} days" '+%Y-%m-%d'); fi
    _sql "UPDATE licenses SET expires_at='$new_exp', status='ACTIVE' WHERE uuid='$PICKED_UUID';"
    _sql "INSERT INTO audit (timestamp, action, license_uuid, details) VALUES ('$(_now)','RENEW','$PICKED_UUID','+$days j → $new_exp');"
    _ok "$name → nouvelle expiration : $(printf '%b' "${CYAN}${new_exp}${RST}")"
    printf '\n'
}

act_toggle() {
    printf '\n  \033[0;97m\033[1m⏸ SUSPENDRE / REACTIVER\033[0m\n' >&2
    _pick "N° de la licence"
    [[ -z "$PICKED_UUID" ]] && return
    local name status
    IFS='|' read -r name status <<< "$(_sql "SELECT client_name, status FROM licenses WHERE uuid='$PICKED_UUID';")"
    if [[ "$status" == "ACTIVE" ]]; then
        _sql "UPDATE licenses SET status='SUSPENDED' WHERE uuid='$PICKED_UUID';"
        _sql "INSERT INTO audit (timestamp, action, license_uuid, details) VALUES ('$(_now)','SUSPEND','$PICKED_UUID','$name');"
        _warn "« $name » est maintenant suspendue."
    else
        _sql "UPDATE licenses SET status='ACTIVE' WHERE uuid='$PICKED_UUID';"
        _sql "INSERT INTO audit (timestamp, action, license_uuid, details) VALUES ('$(_now)','REACTIVATE','$PICKED_UUID','$name');"
        _ok "« $name » est réactivée."
    fi
    printf '\n'
}

act_delete() {
    printf '\n  \033[0;97m\033[1m🗑 SUPPRIMER\033[0m\n' >&2
    _pick "N° de la licence"
    [[ -z "$PICKED_UUID" ]] && return
    local name; name=$(_sql "SELECT client_name FROM licenses WHERE uuid='$PICKED_UUID';")
    if CONFIRM "Supprimer « $name » ?"; then
        _sql "UPDATE licenses SET status='DELETED' WHERE uuid='$PICKED_UUID';"
        _sql "INSERT INTO audit (timestamp, action, license_uuid, details) VALUES ('$(_now)','DELETE','$PICKED_UUID','$name');"
        _ok "« $name » supprimée (archivée en base)."
    else
        _info "Annulé."
    fi
    printf '\n'
}

act_backup() {
    printf '\n  \033[0;97m\033[1m💾 SAUVEGARDE\033[0m\n\n'
    _init_db_backup_once
    ls -1t "${BACKUP_DIR}"/ventes-*.db.gz 2>/dev/null | head -5 | while read -r f; do
        printf '  \033[0;90m· %s  (%s)\033[0m\n' "$(basename "$f")" "$(du -h "$f" | cut -f1)"
    done
    printf '\n'
}

_init_db_backup_once() {
    local f="${BACKUP_DIR}/ventes-$(_today)-$(date '+%H%M%S').db.gz"
    sqlite3 "$DB" ".backup '${BACKUP_DIR}/tmp.db'" 2>/dev/null || cp "$DB" "${BACKUP_DIR}/tmp.db"
    gzip -cf "${BACKUP_DIR}/tmp.db" > "$f" 2>/dev/null || true
    rm -f "${BACKUP_DIR}/tmp.db"
    _ok "Sauvegarde créée : $(basename "$f")"
    ls -1t "${BACKUP_DIR}"/ventes-*.db.gz 2>/dev/null | tail -n +$((DAILY_KEEP+1)) | xargs -r rm -f 2>/dev/null || true
}

act_stats() {
    printf '\n  \033[0;97m\033[1m📊 STATISTIQUES\033[0m\n\n'
    local total active susp expired soon
    total=$(_sql "SELECT COUNT(*) FROM licenses WHERE status!='DELETED';")
    active=$(_sql "SELECT COUNT(*) FROM licenses WHERE status='ACTIVE';")
    susp=$(_sql "SELECT COUNT(*) FROM licenses WHERE status='SUSPENDED';")
    expired=$(_sql "SELECT COUNT(*) FROM licenses WHERE status!='DELETED' AND expires_at!='9999-12-31' AND expires_at<'$(_today)' AND status='ACTIVE';")
    soon=$(_sql "SELECT COUNT(*) FROM licenses WHERE status='ACTIVE' AND expires_at!='9999-12-31' AND expires_at>='$(_today)' AND expires_at<=date('now','+7 days');")

    printf '  Total : \033[0;97m\033[1m%s\033[0m   Active : \033[0;32m%s\033[0m   Suspendue : \033[0;33m%s\033[0m   Expirée : \033[0;31m%s\033[0m\n' "$total" "$active" "$susp" "$expired"
    if (( soon > 0 )); then _warn "$soon licence(s) expirent dans les 7 prochains jours"; fi
    printf '\n  \033[0;90mDernières créations :\033[0m\n'
    _sql "SELECT client_name, created_at FROM licenses ORDER BY id DESC LIMIT 5;" 2>/dev/null | while IFS='|' read -r n c; do
        printf '  \033[0;90m· %s — %s\033[0m\n' "$n" "$c"
    done
    printf '\n'
}

# ==============================================================================
#  MENU PRINCIPAL
# ==============================================================================
_count() { _sql "$1" 2>/dev/null || echo 0; }

_header() {
    clear
    local total active warn_line=""
    total=$(_count "SELECT COUNT(*) FROM licenses WHERE status!='DELETED';")
    active=$(_count "SELECT COUNT(*) FROM licenses WHERE status='ACTIVE';")
    local soon
    soon=$(_count "SELECT COUNT(*) FROM licenses WHERE status='ACTIVE' AND expires_at!='9999-12-31' AND expires_at>='$(_today)' AND expires_at<=date('now','+7 days');")
    (( soon > 0 )) && warn_line=$(printf '   \033[0;33m⚠ %s expirent sous 7 jours\033[0m' "$soon")

    printf '\n'
    printf '  \033[0;34m╔══════════════════════════════════════════╗\033[0m\n'
    printf '  \033[0;34m║\033[0m  \033[0;97m\033[1mVENTES\033[0m \033[0;90m· Licences · v%s\033[0m\033[0;34m               ║\033[0m\n' "$VERSION"
    printf '  \033[0;34m╚══════════════════════════════════════════╝\033[0m\n'
    printf '  \033[0;90mActives \033[0;32m%s\033[0m\033[0;90m / %s%s\033[0m\n' "$active" "$total" "$warn_line"
    printf '\n'
    printf '   \033[0;36m1\033[0m)  ➕  Nouvelle licence\n'
    printf '   \033[0;36m2\033[0m)  📋  Liste des licences\n'
    printf '   \033[0;36m3\033[0m)  🔍  Rechercher\n'
    printf '   \033[0;36m4\033[0m)  🔄  Renouveler / Prolonger\n'
    printf '   \033[0;36m5\033[0m)  ⏸  Suspendre / Réactiver\n'
    printf '   \033[0;36m6\033[0m)  🗑  Supprimer\n'
    printf '   \033[0;36m7\033[0m)  💾  Sauvegarde\n'
    printf '   \033[0;36m8\033[0m)  📊  Statistiques\n'
    printf '\n'
    printf '   \033[0;31m0\033[0m)  Quitter\n\n'
}

_main_menu() {
    local c
    while true; do
        _header
        printf '  \033[0;33m►\033[0m \033[0;97mChoix\033[0m : '
        c=""
        read -r c || exit 0
        case "$c" in
            1) act_create ;;
            2) act_list ;;
            3) act_search ;;
            4) act_renew ;;
            5) act_toggle ;;
            6) act_delete ;;
            7) act_backup ;;
            8) act_stats ;;
            0|q|Q) clear; exit 0 ;;
            *) ;;
        esac
    done
}

# ==============================================================================
#  POINT D'ENTRÉE
# ==============================================================================

# Mode automatique (cron) : pas de TTY → sauvegarde silencieuse et sortie.
if [[ ! -t 0 && "${VENTES_UI:-}" != "1" ]]; then
    _init_db
    _silent_backup
    exit 0
fi

_init_db
_ensure_cron
_main_menu
