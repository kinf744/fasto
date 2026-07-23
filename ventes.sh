#!/usr/bin/env bash
# ==============================================================================
#  VENTES — Licence Manager v1.0.0
#  Administration complète du cycle de vie des licences commerciales.
#  PROPRIÉTAIRE — Distribution non autorisée interdite.
#  Compatible Ubuntu 22.04 / 24.04+
# ==============================================================================
set -Eeuo pipefail
IFS=$' \t\n'
# shellcheck disable=SC2312

# ── Protection anti-copie / anti-débogage ─────────────────────────────────────
_secure_init() {
    if [[ -f /proc/self/status ]]; then
        local tracer
        tracer=$(grep -oP '^TracerPid:\s*\K\d+' /proc/self/status 2>/dev/null || echo 0)
        if [[ "$tracer" != "0" ]]; then echo -e "\033[0;31mERROR: Debugging detected.\033[0m" >&2; exit 1; fi
    fi
    [[ $EUID -eq 0 ]] || { echo -e "\033[0;31mERROR: Root required.\033[0m" >&2; exit 1; }
    umask 077
    [[ -f "$0" ]] && chmod 700 "$0" 2>/dev/null || true
}
_secure_init

# ── Intégrité & permissions ───────────────────────────────────────────────────
_secure_permissions() {
    chmod 700 "$0" 2>/dev/null || true
    chmod 750 "$DB_DIR" 2>/dev/null || true
    chmod 750 "$BACKUP_DIR" 2>/dev/null || true
    chmod 750 "${DB_DIR}/log" 2>/dev/null || true
    [[ -f "$DB" ]] && chmod 600 "$DB" 2>/dev/null || true
    [[ -f "$CONFIG" ]] && chmod 600 "$CONFIG" 2>/dev/null || true
    find "$BACKUP_DIR" -type f -exec chmod 600 {} + 2>/dev/null || true
}
_script_checksum() {
    if command -v sha256sum &>/dev/null; then sha256sum "$0" 2>/dev/null | cut -d' ' -f1
    else shasum -a 256 "$0" 2>/dev/null | cut -d' ' -f1 || echo ""; fi
}
verify_integrity() {
    [[ -f "$CHKSUM_FILE" ]] || { _warn "Aucun checksum de référence. Lancez d'abord 'Enregistrer le checksum'."; return 1; }
    local stored current
    stored=$(cut -d' ' -f1 < "$CHKSUM_FILE" 2>/dev/null || echo "")
    current=$(_script_checksum)
    if [[ -z "$stored" || -z "$current" ]]; then _warn "Impossible de vérifier."; return 1; fi
    if [[ "$stored" != "$current" ]]; then
        _err "ALERTE: Script modifié !"
        _err "  Réf: $stored"
        _err "  Act: $current"
        return 1
    fi
    _ok "Intégrité vérifiée."
    return 0
}

# -------- Constantes ----------------------------------------------------------
readonly VERSION="1.0.0"
readonly NAME="VENTES"
readonly DB_DIR="/etc/ventes"
readonly DB="${DB_DIR}/ventes.db"
readonly CONFIG="${DB_DIR}/config.json"
readonly CHKSUM_FILE="${DB_DIR}/.checksum"
readonly BACKUP_DIR="${DB_DIR}/backups"
readonly LOG_FILE="${DB_DIR}/log/audit.log"
readonly DAILY_KEEP=7
readonly WEEKLY_KEEP=4

# -------- Couleurs & Icônes ---------------------------------------------------
readonly RST='\033[0m'
readonly BLD='\033[1m'
readonly DIM='\033[2m'
readonly RED='\033[0;31m'
readonly GREEN='\033[0;32m'
readonly YELLOW='\033[0;33m'
readonly BLUE='\033[0;34m'
readonly MAGENTA='\033[0;35m'
readonly CYAN='\033[0;36m'
readonly WHITE='\033[0;97m'
readonly GRAY='\033[0;90m'
readonly BGRED='\033[41m'
readonly BGGREEN='\033[42m'
readonly BGYELLOW='\033[43m'
readonly BGBLUE='\033[44m'
readonly BGMAGENTA='\033[45m'

readonly ICON_OK="${GREEN}✓${RST}"
readonly ICON_ERR="${RED}✗${RST}"
readonly ICON_WARN="${YELLOW}⚠${RST}"
readonly ICON_INFO="${BLUE}ℹ${RST}"
readonly ICON_LOCK="${YELLOW}🔒${RST}"
readonly ICON_KEY="${MAGENTA}🔑${RST}"
readonly ICON_USER="${CYAN}👤${RST}"
readonly ICON_CAL="${WHITE}📅${RST}"
readonly ICON_STAT="${BLUE}📊${RST}"
readonly ICON_BACKUP="${YELLOW}💾${RST}"
readonly ICON_EXPORT="${MAGENTA}📤${RST}"
readonly ICON_IMPORT="${GREEN}📥${RST}"
readonly ICON_SEARCH="${CYAN}🔍${RST}"
readonly ICON_DEL="${RED}🗑${RST}"
readonly ICON_SUSPEND="${YELLOW}⏸${RST}"
readonly ICON_ACTIVATE="${GREEN}▶${RST}"
readonly ICON_RENEW="${BLUE}🔄${RST}"
readonly ICON_EXTEND="${MAGENTA}➕${RST}"
readonly ICON_MENU="${WHITE}☰${RST}"
readonly ICON_QUIT="${RED}✕${RST}"
readonly ICON_BULLET="${WHITE}•${RST}"

STATUS_ICONS="([ACTIVE]=${ICON_OK}.${GREEN}ACTIVE${RST} [SUSPENDED]=${ICON_SUSPEND}.${YELLOW}SUSPENDED${RST} [EXPIRED]=${ICON_WARN}.${RED}EXPIRED${RST} [BANNED]=${ICON_DEL}.${RED}BANNED${RST} [DELETED]=${ICON_DEL}.${GRAY}DELETED${RST})"

# -------- Trap -----------------------------------------------------------------
_cleanup() {
    local rc=$?
    [[ -n "${TMPDIR:-}" && -d "$TMPDIR" ]] && rm -rf "$TMPDIR"
    exit "$rc"
}
trap _cleanup EXIT SIGINT SIGTERM

# ==============================================================================
#  FONCTIONS UTILITAIRES
# ==============================================================================

# --- couleurs sous non-TTY ----------------------------------------------------
_has_color() { [[ -t 1 ]] && return 0 || return 1; }
_color() {
    local c="$1"; shift
    _has_color || { echo -e "$*"; return; }
    echo -e "${c}${*}${RST}"
}

_ok()   { echo -e "  ${ICON_OK}   ${*}${RST}"; }
_err()  { echo -e "  ${ICON_ERR}   ${*}${RST}" >&2; }
_warn() { echo -e "  ${ICON_WARN}   ${*}${RST}"; }
_info() { echo -e "  ${ICON_INFO}   ${*}${RST}"; }

# --- barre de progression simple ----------------------------------------------
_progress() {
    local n=$1 total=$2 label="${3:-}"
    local w=40 p
    (( total > 0 )) || total=1
    (( n > total )) && n=$total
    p=$(( n * w / total ))
    printf "\r  ${BLUE}▸${RST} %-20s [%s${GRAY}%s${RST}] %3d%%" \
        "$label" "$(printf "%${p}s" | tr ' ' '█')" "$(printf "%$((w-p))s" | tr ' ' '░')" \
        $(( n * 100 / total ))
    (( n == total )) && echo
}

# --- datetime helpers ---------------------------------------------------------
_now()      { date '+%Y-%m-%d %H:%M:%S'; }
_today()    { date '+%Y-%m-%d'; }
_expire_at() {
    local days=$1
    [[ "$days" == "0" ]] && { echo "9999-12-31"; return; }
    date -d "+${days} days" '+%Y-%m-%d' 2>/dev/null || date -v+"${days}"d '+%Y-%m-%d'
}
_days_until() {
    local e=$1
    [[ "$e" == "9999-12-31" ]] && { echo "∞"; return; }
    local now_s expiry_s
    now_s=$(date -d "$(_today)" +%s 2>/dev/null || date -j -f '%Y-%m-%d' "$(_today)" +%s)
    expiry_s=$(date -d "$e" +%s 2>/dev/null || date -j -f '%Y-%m-%d' "$e" +%s)
    echo "$(( (expiry_s - now_s) / 86400 ))"
}
_is_expired() {
    local e=$1
    [[ "$e" == "9999-12-31" ]] && return 1
    [[ "$e" < "$(_today)" ]] && return 0 || return 1
}

# --- UUID v4 (sans dépendance) ------------------------------------------------
_gen_uuid() {
    local hex
    hex=$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')
    printf '%s-%s-4%s-%s%s-%s' \
        "${hex:0:8}" "${hex:8:4}" "${hex:13:3}" \
        "$(printf '%x' $(( 0x${hex:16:2} & 0x3f | 0x80 )))" \
        "${hex:18:2}" "${hex:20:12}"
}

# --- clé aléatoire 32-64 chars -------------------------------------------------
_gen_key() {
    local len=$(( 32 + (RANDOM % 33) ))
    dd if=/dev/urandom bs=64 count=1 2>/dev/null | md5sum | cut -d' ' -f1 | head -c "$len"
}

# --- validation entrées -------------------------------------------------------
_valid_uuid()   { [[ "$1" =~ ^[0-9a-fA-F-]{36}$ ]]; }
_valid_phone()  { [[ "$1" =~ ^[0-9+][0-9[:space:]()-]{4,20}$ ]] || [[ -z "$1" ]]; }
_valid_email()  { [[ "$1" =~ ^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$ ]] || [[ -z "$1" ]]; }
_valid_status() { [[ "$1" =~ ^(ACTIVE|SUSPENDED|EXPIRED|BANNED|DELETED)$ ]]; }
_valid_days()   { [[ "$1" =~ ^[0-9]+$ ]] && (( $1 > 0 )); }
__prompt_result=
_prompt() {
    local msg="$1" default="${2:-}"
    echo -ne "  ${YELLOW}►${RST} ${WHITE}${msg}${RST}" >&2
    [[ -n "$default" ]] && echo -ne " ${GRAY}[${default}]${RST}" >&2
    echo -ne " : ${RST}" >&2
    IFS= read -r __prompt_result
    [[ -z "$__prompt_result" && -n "$default" ]] && __prompt_result="$default"
    return 0
}
_confirm() {
    local msg="$1"
    echo -ne "  ${YELLOW}?${RST} ${WHITE}${msg}${RST} ${GRAY}[y/N]${RST} : " >&2
    local r; read -r r
    [[ "$r" =~ ^[yYoO]$ ]] && return 0 || return 1
}
_press_enter() {
    echo -ne "  ${GRAY}Appuyez sur Entrée pour continuer...${RST}" >&2
    read -r
}

# -------- SQLite helper --------------------------------------------------------
_sql() {
    sqlite3 "$DB" "$@"
}
_sql_escape() {
    # sqlite3 gère les guillemets simples si doublés
    local s="$1"
    s="${s//\'/\'\'}"
    echo "$s"
}

# ==============================================================================
#  INITIALISATION
# ==============================================================================

_check_deps() {
    local missing=()
    command -v sqlite3 &>/dev/null || missing+=("sqlite3")
    if ((${#missing[@]} > 0)); then
        apt-get update -qq 2>/dev/null && apt-get install -y -qq "${missing[@]}" 2>/dev/null
        command -v sqlite3 &>/dev/null || { _err "sqlite3 requis."; exit 1; }
    fi
}

_init_dirs() {
    mkdir -p "$DB_DIR" "$BACKUP_DIR" "${DB_DIR}/log" 2>/dev/null
}

_schema_version() {
    _sql "PRAGMA user_version;" 2>/dev/null || echo 0
}

_apply_schema() {
    local ver
    ver=$(_schema_version)
    (( ver >= 1 )) && return 0

    _sql "
        CREATE TABLE IF NOT EXISTS licenses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            uuid        TEXT    UNIQUE NOT NULL,
            license_key TEXT    UNIQUE NOT NULL,
            client_name TEXT    NOT NULL,
            client_phone TEXT   DEFAULT '',
            client_email TEXT   DEFAULT '',
            notes       TEXT    DEFAULT '',
            status      TEXT    NOT NULL DEFAULT 'ACTIVE',
            created_at  TEXT    NOT NULL,
            expires_at  TEXT    NOT NULL,
            activated_at TEXT   DEFAULT NULL,
            last_checkin TEXT   DEFAULT NULL,
            metadata    TEXT    DEFAULT '{}'
        );
        CREATE TABLE IF NOT EXISTS audit (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp   TEXT    NOT NULL,
            action      TEXT    NOT NULL,
            license_uuid TEXT   DEFAULT NULL,
            details     TEXT    DEFAULT '',
            user        TEXT    DEFAULT 'admin'
        );
        CREATE INDEX IF NOT EXISTS idx_licenses_status ON licenses(status);
        CREATE INDEX IF NOT EXISTS idx_licenses_uuid  ON licenses(uuid);
        CREATE INDEX IF NOT EXISTS idx_licenses_name  ON licenses(client_name);
        CREATE INDEX IF NOT EXISTS idx_audit_time     ON audit(timestamp);
        PRAGMA user_version = 1;
    "
}

_init_db() {
    _check_deps
    _init_dirs

    if [[ ! -f "$DB" ]]; then
        _sql "VACUUM;" 2>/dev/null || true
        _info "Nouvelle base créée : $DB"
    fi

    _apply_schema

    # config.json par défaut
    if [[ ! -f "$CONFIG" ]]; then
        cat > "$CONFIG" <<-EOF
{
    "version": "$VERSION",
    "created_at": "$(_now)",
    "checksum": "",
    "last_backup": ""
}
EOF
    fi
    _secure_permissions
    _script_checksum > "$CHKSUM_FILE" 2>/dev/null || true
    chmod 600 "$CHKSUM_FILE" 2>/dev/null || true
}

# ==============================================================================
#  AUDIT / LOG
# ==============================================================================

_audit() {
    local action="$1" uuid="${2:-}" details="${3:-}"
    local ts; ts=$(_now)
    _sql "INSERT INTO audit (timestamp, action, license_uuid, details) VALUES ('$ts', '$(_sql_escape "$action")', '$(_sql_escape "$uuid")', '$(_sql_escape "$details")');"
    echo "[$ts] [$action] ${uuid:+- $uuid }$details" >> "$LOG_FILE"
}

_last_audit() {
    local n="${1:-20}"
    _sql "SELECT timestamp, action, COALESCE(license_uuid,'-'), details FROM audit ORDER BY id DESC LIMIT $n;"
}

# ==============================================================================
#  LICENCES — CRUD
# ==============================================================================

# --- Créer --------------------------------------------------------------------
create_license() {
    local name phone email notes days uuid key expires_at
    echo
    echo -e "  ${BLUE}═══${RST} ${WHITE}CRÉER UNE LICENCE${RST} ${BLUE}═══${RST}"
    echo
    _prompt "Client / Slogan" ""; name=$__prompt_result
    [[ -z "$name" ]] && { _err "Nom requis."; return 1; }

    _prompt "Téléphone" ""; phone=$__prompt_result
    _prompt "Email" ""; email=$__prompt_result
    _prompt "Notes" ""; notes=$__prompt_result

    echo -e "  ${YELLOW}►${RST} ${WHITE}Durée :${RST}"
    local durations=("1 jour" "3 jours" "7 jours" "15 jours" "30 jours" "60 jours" "90 jours" "180 jours" "365 jours" "Illimité")
    local dvals=(1 3 7 15 30 60 90 180 365 0)
    local i
    for i in "${!durations[@]}"; do
        printf "    ${CYAN}%2d${RST}) ${WHITE}%s${RST}\n" $((i+1)) "${durations[$i]}"
    done
    local choice
    _prompt "Choix" "5"; choice=$__prompt_result
    [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#dvals[@]} )) || choice=5
    days=${dvals[$((choice-1))]}

    uuid=$(_gen_uuid)
    key=$(_gen_key)
    expires_at=$(_expire_at "$days")

    _sql "
        INSERT INTO licenses (uuid, license_key, client_name, client_phone, client_email, notes, status, created_at, expires_at)
        VALUES (
            '$uuid', '$key',
            '$(_sql_escape "$name")',
            '$(_sql_escape "$phone")',
            '$(_sql_escape "$email")',
            '$(_sql_escape "$notes")',
            'ACTIVE',
            '$(_now)',
            '$expires_at'
        );
    "
    _audit "CREATE" "$uuid" "Licence créée pour $name, expire le $expires_at"

    local now; now=$(_now)
    _license_card "$uuid" "$key" "$name" "$phone" "$email" \
                  "$notes" "ACTIVE" "$now" "$expires_at"
    _press_enter
}

# --- Supprimer (soft delete) --------------------------------------------------
delete_license() {
    local uuid
    _prompt "UUID de la licence à supprimer"; uuid=$__prompt_result
    local exists
    exists=$(_sql "SELECT uuid FROM licenses WHERE uuid='$uuid' AND status != 'DELETED';")
    [[ -z "$exists" ]] && { _err "Licence introuvable ou déjà supprimée."; _press_enter; return 1; }
    local name
    name=$(_sql "SELECT client_name FROM licenses WHERE uuid='$uuid';")
    echo
    _warn "Vous allez supprimer la licence de ${WHITE}${name}${RST} (${uuid})"
    _confirm "Confirmer la suppression ?" || { _info "Annulé."; _press_enter; return; }
    _sql "UPDATE licenses SET status='DELETED' WHERE uuid='$uuid';"
    _audit "DELETE" "$uuid" "Licence marquée DELETED pour $name"
    _ok "Licence supprimée."
    _press_enter
}

# --- Suspendre ----------------------------------------------------------------
suspend_license() {
    local uuid
    _prompt "UUID de la licence à suspendre"; uuid=$__prompt_result
    local name
    name=$(_sql "SELECT client_name FROM licenses WHERE uuid='$uuid' AND status='ACTIVE';")
    [[ -z "$name" ]] && { _err "Licence active introuvable."; _press_enter; return 1; }
    _sql "UPDATE licenses SET status='SUSPENDED' WHERE uuid='$uuid';"
    _audit "SUSPEND" "$uuid" "Licence suspendue pour $name"
    _ok "Licence suspendue."
    _press_enter
}

# --- Réactiver ----------------------------------------------------------------
reactivate_license() {
    local uuid
    _prompt "UUID de la licence à réactiver"; uuid=$__prompt_result
    local name
    name=$(_sql "SELECT client_name FROM licenses WHERE uuid='$uuid' AND status='SUSPENDED';")
    [[ -z "$name" ]] && { _err "Licence suspendue introuvable."; _press_enter; return 1; }

    local expires_at
    expires_at=$(_sql "SELECT expires_at FROM licenses WHERE uuid='$uuid';")
    if [[ "$expires_at" < "$(_today)" && "$expires_at" != "9999-12-31" ]]; then
        _warn "Cette licence est expirée depuis le $expires_at."
        _confirm "Réactiver quand même ?" || { _info "Annulé."; _press_enter; return; }
    fi

    _sql "UPDATE licenses SET status='ACTIVE' WHERE uuid='$uuid';"
    _audit "REACTIVATE" "$uuid" "Licence réactivée pour $name"
    _ok "Licence réactivée."
    _press_enter
}

# --- Renouveler ---------------------------------------------------------------
renew_license() {
    local uuid days
    _prompt "UUID de la licence à renouveler"; uuid=$__prompt_result
    local name expires_at status
    name=$(_sql "SELECT client_name FROM licenses WHERE uuid='$uuid' AND status NOT IN ('DELETED','BANNED');")
    [[ -z "$name" ]] && { _err "Licence introuvable."; _press_enter; return 1; }
    expires_at=$(_sql "SELECT expires_at FROM licenses WHERE uuid='$uuid';")
    status=$(_sql "SELECT status FROM licenses WHERE uuid='$uuid';")

    echo -e "  ${ICON_INFO} Client : ${WHITE}${name}${RST}, expire le ${WHITE}${expires_at}${RST}, statut : ${WHITE}${status}${RST}"
    echo
    local durations=("30 jours" "60 jours" "90 jours" "180 jours" "365 jours" "Illimité")
    local dvals=(30 60 90 180 365 0)
    local i
    for i in "${!durations[@]}"; do
        printf "    ${CYAN}%2d${RST}) ${WHITE}%s${RST}\n" $((i+1)) "${durations[$i]}"
    done
    local choice
    _prompt "Choix" "3"; choice=$__prompt_result
    [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#dvals[@]} )) || choice=3
    days=${dvals[$((choice-1))]}

    local new_expires
    if [[ "$days" == "0" ]]; then
        new_expires="9999-12-31"
    else
        new_expires=$(date -d "$(_today) +${days} days" '+%Y-%m-%d' 2>/dev/null)
    fi

    _sql "UPDATE licenses SET expires_at='$new_expires', status='ACTIVE' WHERE uuid='$uuid';"
    _audit "RENEW" "$uuid" "Renouvelée jusqu'au $new_expires"
    _ok "Licence renouvelée jusqu'au ${WHITE}${new_expires}${RST}."
    _press_enter
}

# --- Prolonger ----------------------------------------------------------------
extend_license() {
    local uuid extra
    _prompt "UUID de la licence à prolonger"; uuid=$__prompt_result
    local name expires_at
    name=$(_sql "SELECT client_name FROM licenses WHERE uuid='$uuid' AND status NOT IN ('DELETED','BANNED');")
    [[ -z "$name" ]] && { _err "Licence introuvable."; _press_enter; return 1; }
    expires_at=$(_sql "SELECT expires_at FROM licenses WHERE uuid='$uuid';")
    echo -e "  ${ICON_INFO} Client : ${WHITE}${name}${RST}, expire actuellement le ${WHITE}${expires_at}${RST}"
    _prompt "Jours supplémentaires" "30"; extra=$__prompt_result
    _valid_days "$extra" || { _err "Nombre de jours invalide."; _press_enter; return 1; }

    local current_expires new_expires
    current_expires=$(_sql "SELECT expires_at FROM licenses WHERE uuid='$uuid';")
    if [[ "$current_expires" == "9999-12-31" ]]; then
        _warn "Licence illimitée — la prolongation n'a pas d'effet."
        _press_enter
        return
    fi
    # Ajoute les jours à la date d'expiration actuelle
    new_expires=$(date -d "$current_expires +${extra} days" '+%Y-%m-%d' 2>/dev/null || echo "$current_expires")
    _sql "UPDATE licenses SET expires_at='$new_expires' WHERE uuid='$uuid';"
    _audit "EXTEND" "$uuid" "Prolongée de ${extra}j, nouvelle expiration $new_expires"
    _ok "Licence prolongée jusqu'au ${WHITE}${new_expires}${RST}."
    _press_enter
}

# ==============================================================================
#  AFFICHAGE
# ==============================================================================

# ── Carte de licence (format type DARNIX) ─────────────────────────────────────
# Génère un bloc stylisé "KEY - CLIENT" avec toutes les infos.
_license_card() {
    local uuid="$1" key="$2" name="$3" phone="$4" email="$5"
    local notes="$6" status="$7" created_at="$8" expires_at="$9"
    shift 9
    local activated_at="${1:-}" last_checkin="${2:-}"

    local remaining sstatus
    if [[ "$expires_at" == "9999-12-31" ]]; then
        remaining="${GREEN}∞ Illimité${RST}"
    elif _is_expired "$expires_at"; then
        remaining="${RED}Expirée le ${expires_at}${RST}"
    else
        remaining="${GREEN}$(_days_until "$expires_at") jours${RST}"
    fi
    case "$status" in
        ACTIVE)    sstatus="${GREEN}● ACTIVE${RST}" ;;
        SUSPENDED) sstatus="${YELLOW}● SUSPENDED${RST}" ;;
        EXPIRED)   sstatus="${RED}● EXPIRED${RST}" ;;
        BANNED)    sstatus="${RED}● BANNED${RST}" ;;
        DELETED)   sstatus="${GRAY}● DELETED${RST}" ;;
    esac

    local hbar
    hbar=$(printf '%*s' 48 | tr ' ' '═')

    echo
    echo -e "  ${YELLOW}💥 ─━─━ ${WHITE}KEY - ${CYAN}${name}${YELLOW} ━─━─ 💥${RST}"
    echo
    echo -e "    ${MAGENTA}🔢${RST} ${WHITE}Nº Key:${RST}       ${MAGENTA}${uuid:0:4}${RST}"
    echo -e "    ${CYAN}👤${RST} ${WHITE}Client/Slogan:${RST} ${CYAN}${name}${RST}"
    echo -e "    ${BLUE}🆔${RST} ${WHITE}UUID:${RST}          ${BLUE}${uuid}${RST}"
    echo
    echo -e "    ${GREEN}🔑${RST} ${WHITE}Key Generada:${RST}"
    echo -e "       ${GREEN}${key}${RST}"
    echo
    echo -e "    ${YELLOW}📅${RST} ${WHITE}Créée le:${RST}     ${YELLOW}${created_at}${RST}"
    echo -e "    ${RED}⏳${RST} ${WHITE}Expire le:${RST}     ${expires_at}"
    echo -e "    ${WHITE}⏱${RST}  ${WHITE}Replique:${RST}     ${remaining}"
    echo -e "    ${WHITE}${sstatus}${RST}"
    [[ -n "$phone" ]]      && echo -e "    ${GRAY}📞 Téléphone:${RST}   ${phone}"
    [[ -n "$email" ]]      && echo -e "    ${GRAY}✉ Email:${RST}      ${email}"
    [[ -n "$notes" ]]      && echo -e "    ${GRAY}📝 Notes:${RST}      ${notes}"
    [[ -n "$activated_at" ]] && echo -e "    ${GRAY}⚡ Activée le:${RST} ${activated_at}"
    [[ -n "$last_checkin" ]] && echo -e "    ${GRAY}🔄 Dernier CHK:${RST} ${last_checkin}"
    echo
    if [[ -z "$activated_at" ]]; then
        echo -e "  ${YELLOW}━━━ MESSAGE À ENVOYER AU CLIENT ━━━${RST}"
        echo
        echo -e "    ${WHITE}🔑 Licence Kighmu Panel${RST}"
        echo -e "    ${GRAY}Client :${RST} ${WHITE}${name}${RST}"
        echo -e "    ${GRAY}Durée  :${RST} ${remaining}"
        echo
        echo -e "    ${CYAN}━━━ Installation unique ━━━${RST}"
        echo
        echo -e "    ${YELLOW}1.${RST} ${WHITE}Connectez-vous en root sur votre VPS${RST}"
        echo
        echo -e "    ${YELLOW}2.${RST} ${WHITE}Exécutez cette commande :${RST}"
        echo -e "       ${GREEN}bash <(curl -sL https://github.com/kinf744/fasto/raw/main/install.sh)${RST}"
        echo
        echo -e "    ${YELLOW}3.${RST} ${WHITE}Quand la clé vous est demandée, saisissez :${RST}"
        echo -e "       ${GREEN}${key}${RST}"
        echo
        echo -e "    ${YELLOW}4.${RST} ${WHITE}Le panneau s'ouvre automatiquement après validation${RST}"
        echo
        echo -e "    ${GRAY}Une fois activée, cette clé ne peut plus être réutilisée.${RST}"
        echo
        echo -e "  ${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
    fi
    echo
}

# ── Affichage détaillé d'une licence (appelle _license_card) ─────────────────
show_license_detail() {
    local uuid="$1"
    local row
    row=$(_sql "SELECT uuid, license_key, client_name, client_phone, client_email, notes, status, created_at, expires_at, activated_at, last_checkin FROM licenses WHERE uuid='$uuid';")
    [[ -z "$row" ]] && { _err "Licence introuvable."; _press_enter; return 1; }

    local IFS='|'
    read -r uuid key name phone email notes status created_at expires_at activated_at last_checkin <<< "$row"

    _license_card "$uuid" "$key" "$name" "$phone" "$email" \
                  "$notes" "$status" "$created_at" "$expires_at" \
                  "$activated_at" "$last_checkin"
    _press_enter
}

# ── Une ligne pour la liste compacte ─────────────────────────────────────────
_license_row() {
    local uuid="$1" name="$2" expires_at="$3" status="$4" key="$5"
    local remaining days_left color
    if [[ "$expires_at" == "9999-12-31" ]]; then
        remaining="${GREEN}∞${RST}"
    elif _is_expired "$expires_at"; then
        remaining="${RED}Exp.${RST}"
    else
        days_left=$(_days_until "$expires_at")
        (( days_left <= 3 )) && color="${RED}" || (( days_left <= 7 )) && color="${YELLOW}" || color="${GREEN}"
        remaining="${color}${days_left}j${RST}"
    fi
    local status_colored
    case "$status" in
        ACTIVE)    status_colored="${GREEN}A${RST}" ;;
        SUSPENDED) status_colored="${YELLOW}S${RST}" ;;
        EXPIRED)   status_colored="${RED}E${RST}" ;;
        BANNED)    status_colored="${RED}B${RST}" ;;
        DELETED)   status_colored="${GRAY}D${RST}" ;;
        *)         status_colored="${WHITE}?${RST}" ;;
    esac
    local key_short="${key:0:16}.."
    echo -e "  ${ICON_BULLET} ${WHITE}${name}${RST}  ${CYAN}${expires_at}${RST}  ${remaining}  ${status_colored}  ${GRAY}${key_short}${RST}"
}

list_licenses() {
    local filter="${1:-}" label="${2:-Toutes les licences}"
    local query="SELECT uuid, client_name, expires_at, status, license_key FROM licenses"
    if [[ -n "$filter" ]]; then
        query+=" WHERE $filter"
    fi
    query+=" ORDER BY
        CASE status WHEN 'ACTIVE' THEN 1 WHEN 'SUSPENDED' THEN 2 WHEN 'EXPIRED' THEN 3 ELSE 4 END,
        expires_at ASC;"

    echo
    echo -e "  ${BLUE}═══${RST} ${WHITE}${label}${RST} ${BLUE}═══${RST}"
    echo

    local count
    count=$(_sql "SELECT COUNT(*) FROM licenses ${filter:+WHERE $filter};")
    if [[ "$count" == "0" ]]; then
        _info "Aucune licence à afficher."
        echo
        _press_enter
        return
    fi

    echo -e "  ${GRAY}Total: ${WHITE}${count}${RST} licence(s)"
    echo
    printf "  ${GRAY}%-18s  %-14s  %-6s %s  CLÉ${RST}\n" "CLIENT" "EXPIRATION" "REPL." "S"
    printf "  ${GRAY}%s${RST}\n" "$(printf '─%.0s' $(seq 1 65))"

    local IFS=$'\n'
    for row in $(_sql "$query;"); do
        local uuid name expires_at status key
        IFS='|' read -r uuid name expires_at status key <<< "$row"
        _license_row "$uuid" "$name" "$expires_at" "$status" "$key"
    done
    echo

    # Option: voir le détail d'une licence depuis la liste
    echo -ne "  ${YELLOW}►${RST} ${WHITE}UUID à détailler${RST} ${GRAY}(Entrée = ignorer)${RST} : " >&2
    local pick; read -r pick
    [[ -n "$pick" ]] && show_license_detail "$pick"
}

# ==============================================================================
#  RECHERCHE
# ==============================================================================

search_licenses() {
    echo
    echo -e "  ${BLUE}═══${RST} ${WHITE}RECHERCHER UNE LICENCE${RST} ${BLUE}═══${RST}"
    echo
    local term
    _prompt "Terme (nom, UUID, email, téléphone)"; term=$__prompt_result
    [[ -z "$term" ]] && { _info "Annulé."; _press_enter; return; }
    local escaped
    escaped=$(_sql_escape "$term")
    local filter="client_name LIKE '%$escaped%' OR client_email LIKE '%$escaped%' OR client_phone LIKE '%$escaped%' OR uuid LIKE '%$escaped%'"

    # Cherche d'abord une correspondance exacte UUID → carte détaillée
    local exact_uuid
    exact_uuid=$(_sql "SELECT uuid FROM licenses WHERE uuid='$term' LIMIT 1;")
    if [[ -n "$exact_uuid" ]]; then
        show_license_detail "$exact_uuid"
        return
    fi

    # Sinon affiche la liste des résultats
    local count
    count=$(_sql "SELECT COUNT(*) FROM licenses WHERE $filter;")
    if [[ "$count" == "1" ]]; then
        # Un seul résultat → carte détaillée directe
        local row
        row=$(_sql "SELECT uuid FROM licenses WHERE $filter LIMIT 1;")
        show_license_detail "$row"
    elif (( count > 1 )); then
        list_licenses "$filter" "Résultats pour : ${WHITE}${term}${RST} (${count})"
    else
        _info "Aucun résultat."
        _press_enter
    fi
}

# ==============================================================================
#  STATISTIQUES
# ==============================================================================

show_stats() {
    echo
    echo -e "  ${BLUE}═══${RST} ${WHITE}STATISTIQUES${RST} ${BLUE}═══${RST}"
    echo

    local total active suspended expired banned deleted
    total=$(_sql "SELECT COUNT(*) FROM licenses;")
    active=$(_sql "SELECT COUNT(*) FROM licenses WHERE status='ACTIVE';")
    suspended=$(_sql "SELECT COUNT(*) FROM licenses WHERE status='SUSPENDED';")
    expired=$(_sql "SELECT COUNT(*) FROM licenses WHERE status='EXPIRED';")
    banned=$(_sql "SELECT COUNT(*) FROM licenses WHERE status='BANNED';")
    deleted=$(_sql "SELECT COUNT(*) FROM licenses WHERE status='DELETED';")

    echo -e "    ${WHITE}Total      :${RST} ${BLD}${total}${RST}"
    echo -e "    ${GREEN}Actives    :${RST} ${active}"
    echo -e "    ${YELLOW}Suspendues :${RST} ${suspended}"
    echo -e "    ${RED}Expirées   :${RST} ${expired}"
    echo -e "    ${RED}Bannies    :${RST} ${banned}"
    echo -e "    ${GRAY}Supprimées :${RST} ${deleted}"
    echo

    # Licences expirant dans 7 jours
    local expiring
    expiring=$(_sql "SELECT COUNT(*) FROM licenses WHERE status='ACTIVE' AND expires_at != '9999-12-31' AND expires_at >= '$(_today)' AND expires_at <= '$(date -d '+7 days' '+%Y-%m-%d')';")
    if (( expiring > 0 )); then
        _warn "${expiring} licence(s) expirent dans les 7 prochains jours."
    fi

    # Top 5 des clients les plus récents
    echo -e "  ${BLUE}⸻${RST} ${WHITE}Dernières licences créées${RST}"
    echo
    local IFS=$'\n'
    for row in $(_sql "SELECT client_name, uuid, created_at FROM licenses ORDER BY id DESC LIMIT 5;"); do
        IFS='|' read -r n u c <<< "$row"
        echo -e "    ${ICON_BULLET} ${WHITE}${n}${RST} ${GRAY}${u}${RST} — ${c}"
    done
    echo
    _press_enter
}

# ==============================================================================
#  EXPORT / IMPORT
# ==============================================================================

export_licenses() {
    echo
    echo -e "  ${BLUE}═══${RST} ${WHITE}EXPORTER LES LICENCES${RST} ${BLUE}═══${RST}"
    echo
    echo -e "    ${CYAN}1${RST}) ${WHITE}JSON${RST}"
    echo -e "    ${CYAN}2${RST}) ${WHITE}CSV${RST}"
    local choice
    _prompt "Format" "1"; choice=$__prompt_result
    local outfile
    _prompt "Fichier de sortie" "/tmp/ventes-export-$(_today).json"; outfile=$__prompt_result

    case "$choice" in
        2)
            outfile="${outfile%.*}.csv"
            _sql -header -csv "SELECT uuid, license_key, client_name, client_phone, client_email, notes, status, created_at, expires_at, activated_at, last_checkin FROM licenses;" > "$outfile"
            ;;
        *)
            outfile="${outfile%.*}.json"
            _sql -json "SELECT uuid, license_key, client_name, client_phone, client_email, notes, status, created_at, expires_at, activated_at, last_checkin FROM licenses;" > "$outfile"
            ;;
    esac
    _ok "Exporté vers ${WHITE}${outfile}${RST} ($(du -h "$outfile" | cut -f1))"
    _audit "EXPORT" "" "Export vers $outfile"
    _press_enter
}

import_licenses() {
    echo
    echo -e "  ${BLUE}═══${RST} ${WHITE}IMPORTER DES LICENCES${RST} ${BLUE}═══${RST}"
    echo
    local infile
    _prompt "Fichier à importer (JSON)"; infile=$__prompt_result
    [[ -f "$infile" ]] || { _err "Fichier introuvable."; _press_enter; return 1; }

    _confirm "Cela va ajouter les licences du fichier. Continuer ?" || { _info "Annulé."; _press_enter; return; }

    local total=0 ok=0 err=0
    total=$(jq -r 'length' "$infile" 2>/dev/null || echo 0)
    [[ "$total" == "0" ]] && { _err "Fichier JSON invalide ou vide."; _press_enter; return; }

    local i=0 name uuid key expires_at phone email notes status
    for row in $(jq -c '.[]' "$infile" 2>/dev/null); do
        i=$((i+1))
        _progress "$i" "$total" "Importation"
        name=$(echo "$row" | jq -r '.client_name // ""')
        uuid=$(echo "$row" | jq -r '.uuid // ""')
        key=$(echo "$row" | jq -r '.license_key // ""')
        expires_at=$(echo "$row" | jq -r '.expires_at // ""')
        phone=$(echo "$row" | jq -r '.client_phone // ""')
        email=$(echo "$row" | jq -r '.client_email // ""')
        notes=$(echo "$row" | jq -r '.notes // ""')
        status=$(echo "$row" | jq -r '.status // "ACTIVE"')

        [[ -z "$uuid" || -z "$key" || -z "$name" ]] && { err=$((err+1)); continue; }
        _valid_uuid "$uuid" || { uuid=$(_gen_uuid); }
        _valid_status "$status" || status="ACTIVE"
        [[ -z "$expires_at" ]] && expires_at=$(_expire_at 30)

        if _sql "SELECT uuid FROM licenses WHERE uuid='$uuid';" | grep -q .; then
            err=$((err+1)); continue
        fi

        _sql "
            INSERT INTO licenses (uuid, license_key, client_name, client_phone, client_email, notes, status, created_at, expires_at)
            VALUES (
                '$uuid', '$key',
                '$(_sql_escape "$name")',
                '$(_sql_escape "$phone")',
                '$(_sql_escape "$email")',
                '$(_sql_escape "$notes")',
                '$status',
                '$(_now)',
                '$expires_at'
            );
        " 2>/dev/null && ok=$((ok+1)) || err=$((err+1))
    done
    echo
    _ok "${ok} licence(s) importée(s)."
    (( err > 0 )) && _warn "${err} échec(s)."
    _audit "IMPORT" "" "Importé: ${ok} OK, ${err} échecs depuis $infile"
    _press_enter
}

# ==============================================================================
#  SAUVEGARDES
# ==============================================================================

backup_db() {
    local label="${1:-manuel}"
    local filename="ventes-${label}-$(_today).db"
    local backup_path="${BACKUP_DIR}/${filename}"
    local meta_path="${backup_path}.json"

    echo
    echo -e "  ${BLUE}═══${RST} ${WHITE}SAUVEGARDER${RST} ${BLUE}═══${RST}"
    echo

    # backup SQLite
    _sql ".backup '$backup_path'" 2>/dev/null || cp "$DB" "$backup_path"

    # metadata
    local size checksum
    size=$(stat -c%s "$backup_path" 2>/dev/null || stat -f%z "$backup_path" 2>/dev/null)
    checksum=$(sha256sum "$backup_path" | cut -d' ' -f1)

    cat > "$meta_path" <<-EOF
{
    "filename": "$filename",
    "size": $size,
    "checksum": "$checksum",
    "backup_date": "$(_now)",
    "label": "$label",
    "version": "$VERSION"
}
EOF

    # compression
    gzip -f "$backup_path" 2>/dev/null || true

    _ok "Sauvegarde créée : ${WHITE}${filename}.gz${RST} ($(numfmt --to=iec $size 2>/dev/null || echo "${size}B"))"
    _audit "BACKUP" "" "Sauvegarde $label: $filename.gz"

    # rotation
    _rotate_backups
    _press_enter
}

_rotate_backups() {
    # quotidiens : garder DAILY_KEEP
    local daily_count weekly_count
    daily_count=$(_sql "SELECT COUNT(*) FROM (SELECT 1 FROM backups WHERE label='quotidien' ORDER BY id DESC LIMIT $DAILY_KEEP);" 2>/dev/null || true)

    # Nettoyage des fichiers vieux de plus de DAILY_KEEP jours pour les quotidiens
    find "$BACKUP_DIR" -name "ventes-quotidien-*.db.gz" -type f -mtime +${DAILY_KEEP} -delete 2>/dev/null || true
    find "$BACKUP_DIR" -name "ventes-quotidien-*.db.gz.json" -type f -mtime +${DAILY_KEEP} -delete 2>/dev/null || true
}

restore_backup() {
    echo
    echo -e "  ${BLUE}═══${RST} ${WHITE}RESTAURER UNE SAUVEGARDE${RST} ${BLUE}═══${RST}"
    echo

    local backups=()
    local i=0
    while IFS= read -r f; do
        local name size date
        name=$(basename "$f" .gz)
        size=$(du -h "$f" 2>/dev/null | cut -f1)
        date=$(stat -c '%y' "$f" 2>/dev/null | cut -d. -f1)
        backups+=("$f")
        printf "  ${CYAN}%2d${RST}) ${WHITE}%s${RST} ${GRAY}(%s, %s)${RST}\n" $((i+1)) "$name" "$date" "$size"
        i=$((i+1))
    done < <(find "$BACKUP_DIR" -name "*.db.gz" -type f | sort -r)

    if (( i == 0 )); then
        _info "Aucune sauvegarde trouvée."
        _press_enter
        return
    fi

    echo
    local choice
    _prompt "Choisissez une sauvegarde" "1"; choice=$__prompt_result
    [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= i )) || { _err "Choix invalide."; _press_enter; return; }
    local chosen="${backups[$((choice-1))]}"

    _warn "Cela va ${RED}ÉCRASER${RST} la base de données actuelle !"
    _confirm "Confirmer la restauration ?" || { _info "Annulé."; _press_enter; return; }

    # backup auto avant restauration
    backup_db "pre-restore"

    # décompresser et restaurer
    local tmp
    tmp=$(mktemp)
    gunzip -c "$chosen" > "$tmp"
    _sql ".restore '$tmp'" 2>/dev/null || sqlite3 "$DB" < "$tmp" 2>/dev/null || cp "$tmp" "$DB"
    rm -f "$tmp"

    _ok "Restauration terminée depuis ${WHITE}$(basename "$chosen")${RST}"
    _audit "RESTORE" "" "Restauration depuis $(basename "$chosen")"
    _press_enter
}

daily_backup() {
    backup_db "quotidien"
}

# ==============================================================================
#  API — FONCTIONS PRÊTES POUR SERVEUR REST
# ==============================================================================

# Les fonctions ci-dessous sont conçues pour être appelées par un futur serveur
# API (Node.js, Python, Go, etc.) via `ventes.sh --api <action> <json_payload>`.
# Elles lisent/écrivent uniquement la base et retournent du JSON sur stdout.

api_validate_license() {
    local uuid="$1" license_key="$2"
    local row
    row=$(_sql -json "SELECT uuid, status, expires_at, activated_at, last_checkin FROM licenses WHERE uuid='$uuid' AND license_key='$license_key';" 2>/dev/null)
    if [[ -z "$row" ]]; then
        echo '{"valid":false,"error":"NOT_FOUND"}'
        return 1
    fi
    local status expires_at
    status=$(echo "$row" | jq -r '.[0].status')
    expires_at=$(echo "$row" | jq -r '.[0].expires_at')

    if [[ "$status" != "ACTIVE" ]]; then
        echo "{\"valid\":false,\"error\":\"STATUS_${status}\"}"
        return 1
    fi

    if [[ "$expires_at" != "9999-12-31" && "$expires_at" < "$(_today)" ]]; then
        _sql "UPDATE licenses SET status='EXPIRED' WHERE uuid='$uuid';"
        echo '{"valid":false,"error":"EXPIRED"}'
        _audit "EXPIRE" "$uuid" "Expirée (vérification API)"
        return 1
    fi

    # Mise à jour last_checkin
    _sql "UPDATE licenses SET last_checkin='$(_now)' WHERE uuid='$uuid';"
    echo "$row" | jq '.[0] + {"valid":true}'
    return 0
}

api_activate() {
    local uuid="$1"
    local exists
    exists=$(_sql "SELECT uuid FROM licenses WHERE uuid='$uuid' AND status='ACTIVE';")
    if [[ -n "$exists" ]]; then
        echo '{"ok":false,"error":"ALREADY_ACTIVE"}'
        return 1
    fi
    exists=$(_sql "SELECT uuid FROM licenses WHERE uuid='$uuid' AND status='SUSPENDED';")
    [[ -z "$exists" ]] && { echo '{"ok":false,"error":"NOT_FOUND"}'; return 1; }

    _sql "UPDATE licenses SET status='ACTIVE', activated_at='$(_now)' WHERE uuid='$uuid';"
    _audit "API_ACTIVATE" "$uuid" "Activée via API"
    echo '{"ok":true,"status":"ACTIVE"}'
}

api_deactivate() {
    local uuid="$1"
    local exists
    exists=$(_sql "SELECT uuid FROM licenses WHERE uuid='$uuid' AND status='ACTIVE';")
    [[ -z "$exists" ]] && { echo '{"ok":false,"error":"NOT_FOUND_OR_NOT_ACTIVE"}'; return 1; }
    _sql "UPDATE licenses SET status='SUSPENDED' WHERE uuid='$uuid';"
    _audit "API_DEACTIVATE" "$uuid" "Désactivée via API"
    echo '{"ok":true,"status":"SUSPENDED"}'
}

api_renew() {
    local uuid="$1" days="$2"
    local exists
    exists=$(_sql "SELECT uuid FROM licenses WHERE uuid='$uuid' AND status NOT IN ('DELETED','BANNED');")
    [[ -z "$exists" ]] && { echo '{"ok":false,"error":"NOT_FOUND"}'; return 1; }
    _valid_days "$days" || { echo '{"ok":false,"error":"INVALID_DAYS"}'; return 1; }

    local current_expires new_expires
    current_expires=$(_sql "SELECT expires_at FROM licenses WHERE uuid='$uuid';")
    if [[ "$current_expires" == "9999-12-31" ]]; then
        new_expires="9999-12-31"
    else
        new_expires=$(date -d "$(_today) +${days} days" '+%Y-%m-%d')
    fi
    _sql "UPDATE licenses SET expires_at='$new_expires', status='ACTIVE' WHERE uuid='$uuid';"
    _audit "API_RENEW" "$uuid" "Renouvelée via API: +${days}j, expire $new_expires"
    echo "{\"ok\":true,\"expires_at\":\"$new_expires\"}"
}

api_checkin() {
    local uuid="$1"
    local exists
    exists=$(_sql "SELECT uuid FROM licenses WHERE uuid='$uuid';")
    [[ -z "$exists" ]] && { echo '{"ok":false,"error":"NOT_FOUND"}'; return 1; }
    _sql "UPDATE licenses SET last_checkin='$(_now)' WHERE uuid='$uuid';"
    echo '{"ok":true}'
}

# ==============================================================================
#  INTÉGRITÉ & SÉCURITÉ
# ==============================================================================

store_checksum() {
    local csum
    csum=$(_script_checksum)
    echo "$csum $0" > "$CHKSUM_FILE"
    chmod 600 "$CHKSUM_FILE"
    _secure_permissions
    _ok "Checksum enregistré : ${csum:0:16}..."
}

verify_integrity() {
    echo
    echo -e "  ${BLUE}═══${RST} ${WHITE}VÉRIFICATION D'INTÉGRITÉ${RST} ${BLUE}═══${RST}"
    echo
    if [[ ! -f "$CHKSUM_FILE" ]]; then
        _warn "Aucun checksum de référence. Enregistrez-le d'abord."
        _confirm "Enregistrer le checksum actuel ?" && store_checksum
        _press_enter
        return
    fi
    local stored current
    stored=$(cut -d' ' -f1 < "$CHKSUM_FILE" 2>/dev/null || echo "")
    current=$(_script_checksum)
    if [[ "$stored" == "$current" ]]; then
        _ok "Intégrité vérifiée — le script n'a pas été modifié."
    else
        _err "ALERTE : Le script a été modifié depuis l'enregistrement du checksum !"
        echo
        echo -e "    ${WHITE}Référence  :${RST} ${GRAY}${stored}${RST}"
        echo -e "    ${WHITE}Actuel     :${RST} ${RED}${current}${RST}"
        echo
        _warn "Si vous avez mis à jour le script, réenregistrez le checksum."
        _confirm "Réenregistrer le checksum ?" && store_checksum
    fi
    _press_enter
}

show_audit_log() {
    echo
    echo -e "  ${BLUE}═══${RST} ${WHITE}JOURNAL D'ACTIVITÉS${RST} ${BLUE}═══${RST}"
    echo
    local n
    _prompt "Nombre de lignes" "30"; n=$__prompt_result
    [[ "$n" =~ ^[0-9]+$ ]] || n=30
    echo
    local IFS=$'\n'
    for row in $(_last_audit "$n"); do
        IFS='|' read -r ts action uuid details <<< "$row"
        local color
        case "$action" in
            CREATE|REACTIVATE|RENEW|RESTORE|IMPORT) color="${GREEN}" ;;
            DELETE|SUSPEND|EXPIRE|BAN)               color="${RED}" ;;
            BACKUP|EXPORT)                           color="${BLUE}" ;;
            *)                                        color="${YELLOW}" ;;
        esac
        echo -e "  ${GRAY}${ts}${RST} ${color}${action}${RST} ${GRAY}${uuid}${RST} ${details}"
    done
    echo
    _press_enter
}

# ==============================================================================
#  VÉRIFICATIONS SYSTÈME
# ==============================================================================

system_check() {
    echo
    echo -e "  ${BLUE}═══${RST} ${WHITE}VÉRIFICATION SYSTÈME${RST} ${BLUE}═══${RST}"
    echo

    local warns=0 total=0

    # root
    total=$((total+1))
    if [[ $EUID -eq 0 ]]; then echo -e "  ${ICON_OK}   ${WHITE}Root${RST}"; else echo -e "  ${ICON_ERR}   ${WHITE}Root${RST} — exécutez en root"; warns=$((warns+1)); fi

    # OS
    total=$((total+1))
    if [[ -f /etc/os-release ]]; then
        local os osver
        os=$(grep -oP '^ID=\K.*' /etc/os-release | tr -d '"')
        osver=$(grep -oP '^VERSION_ID=\K.*' /etc/os-release | tr -d '"')
        if [[ "$os" == "ubuntu" ]]; then
            echo -e "  ${ICON_OK}   ${WHITE}OS${RST} Ubuntu ${osver}"
        else
            echo -e "  ${ICON_WARN}   ${WHITE}OS${RST} ${os} ${osver} (non testé)"; warns=$((warns+1))
        fi
    else
        echo -e "  ${ICON_WARN}   ${WHITE}OS${RST} inconnu"; warns=$((warns+1))
    fi

    # Dépendances
    total=$((total+1))
    if command -v sqlite3 &>/dev/null; then echo -e "  ${ICON_OK}   ${WHITE}sqlite3${RST}"; else echo -e "  ${ICON_ERR}   ${WHITE}sqlite3${RST}"; warns=$((warns+1)); fi
    total=$((total+1))
    if command -v jq &>/dev/null; then echo -e "  ${ICON_OK}   ${WHITE}jq${RST}"; else echo -e "  ${ICON_WARN}   ${WHITE}jq${RST} — recommandé"; warns=$((warns+1)); fi

    # Disque
    total=$((total+1))
    local disk_avail disk_pct
    disk_avail=$(df -BG "$DB_DIR" 2>/dev/null | awk 'NR==2{print $4}' | tr -d 'G')
    disk_pct=$(df -h "$DB_DIR" 2>/dev/null | awk 'NR==2{print $5}')
    echo -e "  ${ICON_OK}   ${WHITE}Disque${RST} ${disk_avail}G libre (${disk_pct} utilisé)"

    # RAM
    total=$((total+1))
    local ram_total ram_free
    ram_total=$(free -m | awk '/^Mem:/{print $2}')
    ram_free=$(free -m | awk '/^Mem:/{print $7}')
    echo -e "  ${ICON_OK}   ${WHITE}RAM${RST} ${ram_free}M libre / ${ram_total}M total"

    # Base
    total=$((total+1))
    if [[ -f "$DB" ]]; then
        local db_size db_count
        db_size=$(du -h "$DB" | cut -f1)
        db_count=$(_sql "SELECT COUNT(*) FROM licenses;" 2>/dev/null || echo "?")
        echo -e "  ${ICON_OK}   ${WHITE}Base${RST} ${db_size} — ${db_count} licence(s)"
    else
        echo -e "  ${ICON_WARN}   ${WHITE}Base${RST} absente (sera créée)"; warns=$((warns+1))
    fi

    # Internet
    total=$((total+1))
    if ping -c1 -W2 8.8.8.8 &>/dev/null || ping -c1 -W2 1.1.1.1 &>/dev/null; then
        echo -e "  ${ICON_OK}   ${WHITE}Connexion Internet${RST}"
    else
        echo -e "  ${ICON_WARN}   ${WHITE}Connexion Internet${RST} non détectée"; warns=$((warns+1))
    fi

    echo
    if (( warns == 0 )); then _ok "Tout est OK (${total}/${total})."; else _warn "${warns} avertissement(s) sur ${total} tests."; fi
    echo
    _has_color && _press_enter
}

# ==============================================================================
#  MENU PRINCIPAL
# ==============================================================================

_hr() {
    echo -e "  ${GRAY}──────────────────────────────────────────────────────${RST}"
}

_header() {
    clear
    echo
    echo -e "  ${BLUE}╔══════════════════════════════════════════════════════╗${RST}"
    echo -e "  ${BLUE}║${RST}         ${WHITE}☰ VENTES — Licence Manager ${GRAY}v${VERSION}${RST}${BLUE}            ║${RST}"
    echo -e "  ${BLUE}║${RST}           ${GRAY}Administration Complète des Licences${RST}${BLUE}         ║${RST}"
    echo -e "  ${BLUE}╚══════════════════════════════════════════════════════╝${RST}"
    echo
}

_main_menu() {
    while true; do
        _header
        echo -e "  ${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
        echo -e "  ${WHITE}  MENU PRINCIPAL${RST}"
        echo -e "  ${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
        echo
        echo -e "  ${CYAN} 1${RST}) ${WHITE}Gestion des Licences${RST}"
        echo -e "  ${CYAN} 2${RST}) ${ICON_SEARCH} ${WHITE}Rechercher une Licence${RST}"
        echo -e "  ${CYAN} 3${RST}) ${ICON_STAT} ${WHITE}Statistiques${RST}"
        echo -e "  ${CYAN} 4${RST}) ${ICON_EXPORT} ${WHITE}Exporter / Importer${RST}"
        echo -e "  ${CYAN} 5${RST}) ${ICON_BACKUP} ${WHITE}Sauvegardes${RST}"
        echo -e "  ${CYAN} 6${RST}) ${ICON_INFO} ${WHITE}Journal d'Activités${RST}"
        echo -e "  ${CYAN} 7${RST}) ${ICON_INFO} ${WHITE}Vérification Système${RST}"
        echo -e "  ${CYAN} 8${RST}) ${ICON_LOCK} ${WHITE}Intégrité & Sécurité${RST}"
        echo
        echo -e "  ${RED} 0${RST}) ${ICON_QUIT} ${WHITE}Quitter${RST}"
        echo
        echo -ne "  ${YELLOW}►${RST} ${WHITE}Choix${RST} : ${RST}" >&2
        local c; read -r c
        case "$c" in
            1) _menu_licenses ;;
            2) search_licenses ;;
            3) show_stats ;;
            4) _menu_export ;;
            5) _menu_backups ;;
            6) show_audit_log ;;
            7) system_check ;;
            8) _menu_security ;;
            0) echo; _ok "Au revoir."; exit 0 ;;
            *) _err "Choix invalide."; _press_enter ;;
        esac
    done
}

_menu_licenses() {
    while true; do
        _header
        echo -e "  ${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
        echo -e "  ${WHITE}  GESTION DES LICENCES${RST}"
        echo -e "  ${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
        echo
        echo -e "  ${CYAN} 1${RST}) ${ICON_KEY}   ${WHITE}Créer une licence${RST}"
        echo -e "  ${CYAN} 2${RST}) ${ICON_DEL}   ${WHITE}Supprimer une licence${RST}"
        echo -e "  ${CYAN} 3${RST}) ${ICON_SUSPEND} ${WHITE}Suspendre une licence${RST}"
        echo -e "  ${CYAN} 4${RST}) ${ICON_ACTIVATE} ${WHITE}Réactiver une licence${RST}"
        echo -e "  ${CYAN} 5${RST}) ${ICON_RENEW} ${WHITE}Renouveler une licence${RST}"
        echo -e "  ${CYAN} 6${RST}) ${ICON_EXTEND} ${WHITE}Prolonger la durée${RST}"
        echo
        echo -e "  ${CYAN} 7${RST}) ${WHITE}Afficher toutes les licences${RST}"
        echo -e "  ${CYAN} 8${RST}) ${WHITE}Afficher les actives${RST}"
        echo -e "  ${CYAN} 9${RST}) ${WHITE}Afficher les expirées${RST}"
        echo -e "  ${CYAN}10${RST}) ${WHITE}Carte détaillée d'une licence${RST}"
        echo
        echo -e "  ${CYAN}99${RST}) ${GRAY}Retour au menu principal${RST}"
        echo
        echo -ne "  ${YELLOW}►${RST} ${WHITE}Choix${RST} : ${RST}" >&2
        local c; read -r c
        case "$c" in
            1) create_license ;;
            2) delete_license ;;
            3) suspend_license ;;
            4) reactivate_license ;;
            5) renew_license ;;
            6) extend_license ;;
            7) list_licenses "" "TOUTES LES LICENCES" ;;
            8) list_licenses "status='ACTIVE'" "LICENCES ACTIVES" ;;
            9) list_licenses "status='EXPIRED' OR (expires_at < '$(_today)' AND expires_at != '9999-12-31' AND status='ACTIVE')" "LICENCES EXPIRÉES" ;;
            10)
                local uuid
                _prompt "UUID ou nom du client"; uuid=$__prompt_result
                if [[ -n "$uuid" ]]; then
                    local row
                    row=$(_sql "SELECT uuid FROM licenses WHERE uuid='$uuid' OR client_name LIKE '%$(_sql_escape "$uuid")%' LIMIT 1;")
                    [[ -n "$row" ]] && show_license_detail "$row" || { _err "Introuvable."; _press_enter; }
                fi
                ;;
            99) break ;;
            *) _err "Choix invalide."; _press_enter ;;
        esac
    done
}

_menu_export() {
    while true; do
        _header
        echo -e "  ${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
        echo -e "  ${WHITE}  EXPORT / IMPORT${RST}"
        echo -e "  ${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
        echo
        echo -e "  ${CYAN} 1${RST}) ${ICON_EXPORT} ${WHITE}Exporter les licences${RST}"
        echo -e "  ${CYAN} 2${RST}) ${ICON_IMPORT} ${WHITE}Importer des licences${RST}"
        echo -e "  ${CYAN}99${RST}) ${GRAY}Retour${RST}"
        echo
        echo -ne "  ${YELLOW}►${RST} ${WHITE}Choix${RST} : ${RST}" >&2
        local c; read -r c
        case "$c" in
            1) export_licenses ;;
            2) import_licenses ;;
            99) break ;;
            *) _err "Choix invalide."; _press_enter ;;
        esac
    done
}

_menu_backups() {
    while true; do
        _header
        echo -e "  ${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
        echo -e "  ${WHITE}  SAUVEGARDES${RST}"
        echo -e "  ${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
        echo
        echo -e "  ${CYAN} 1${RST}) ${ICON_BACKUP} ${WHITE}Sauvegarder (manuelle)${RST}"
        echo -e "  ${CYAN} 2${RST}) ${ICON_BACKUP} ${WHITE}Sauvegarde quotidienne (auto)${RST}"
        echo -e "  ${CYAN} 3${RST}) ${ICON_BACKUP} ${WHITE}Restaurer une sauvegarde${RST}"
        echo -e "  ${CYAN}99${RST}) ${GRAY}Retour${RST}"
        echo
        echo -ne "  ${YELLOW}►${RST} ${WHITE}Choix${RST} : ${RST}" >&2
        local c; read -r c
        case "$c" in
            1) backup_db "manuel" ;;
            2) daily_backup ;;
            3) restore_backup ;;
            99) break ;;
            *) _err "Choix invalide."; _press_enter ;;
        esac
    done
}

_menu_security() {
    while true; do
        _header
        echo -e "  ${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
        echo -e "  ${WHITE}  INTÉGRITÉ & SÉCURITÉ${RST}"
        echo -e "  ${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
        echo
        echo -e "  ${CYAN} 1${RST}) ${ICON_LOCK} ${WHITE}Vérifier l'intégrité du script${RST}"
        echo -e "  ${CYAN} 2${RST}) ${ICON_LOCK} ${WHITE}Enregistrer le checksum${RST}"
        echo -e "  ${CYAN}99${RST}) ${GRAY}Retour${RST}"
        echo
        echo -ne "  ${YELLOW}►${RST} ${WHITE}Choix${RST} : ${RST}" >&2
        local c; read -r c
        case "$c" in
            1) verify_integrity ;;
            2) store_checksum; _press_enter ;;
            99) break ;;
            *) _err "Choix invalide."; _press_enter ;;
        esac
    done
}

# ==============================================================================
#  CLI — ARGUMENTS DIRECTS
# ==============================================================================

cli_help() {
    cat <<-HELP
${WHITE}VENTES${RST} — Licence Manager v${VERSION}
Usage: $0 [OPTION] [ARGS...]

${WHITE}Options générales :${RST}
  --help, -h         Affiche cette aide
  --version, -v      Affiche la version

${WHITE}Gestion des licences :${RST}
  --create           Mode interactif de création
  --list             Liste toutes les licences
  --detail <uuid>    Carte détaillée d'une licence
  --search <terme>   Rechercher une licence
  --stats            Afficher les statistiques

${WHITE}API (sortie JSON) :${RST}
  --api validate <uuid> <key>    Valide une licence
  --api activate <uuid>          Active une licence suspendue
  --api deactivate <uuid>        Désactive une licence active
  --api renew <uuid> <days>      Renouvelle une licence
  --api checkin <uuid>           Enregistre un checkin

${WHITE}Sauvegardes :${RST}
  --backup           Sauvegarde manuelle
  --restore          Menu de restauration

${WHITE}Utilitaires :${RST}
  --check            Vérification système
  --integrity        Vérification d'intégrité

${WHITE}Exemples :${RST}
  $0 --create
  $0 --list
  $0 --search "Dupont"
  $0 --api validate abc-def 5A8k3...
  $0 --backup
HELP
}

cli_list() {
    local IFS=$'\n'
    local count
    count=$(_sql "SELECT COUNT(*) FROM licenses;" 2>/dev/null || echo 0)
    echo -e "Total: ${count} licence(s)"
    echo
    for row in $(_sql "SELECT uuid, client_name, status, expires_at FROM licenses ORDER BY id DESC;"); do
        IFS='|' read -r uuid name status expires_at <<< "$row"
        printf "%-36s %-20s %-12s %s\n" "$uuid" "$name" "$status" "$expires_at"
    done
}

cli_api() {
    local action="$1"; shift
    case "$action" in
        validate)   api_validate_license "${1:-}" "${2:-}" ;;
        activate)   api_activate "${1:-}" ;;
        deactivate) api_deactivate "${1:-}" ;;
        renew)      api_renew "${1:-}" "${2:-}" ;;
        checkin)    api_checkin "${1:-}" ;;
        *)          echo '{"error":"unknown_action"}'; exit 1 ;;
    esac
}

# ==============================================================================
#  POINT D'ENTRÉE
# ==============================================================================

_main() {
    # Mode CLI (non-interactif) — sans initialisation DB pour les simples requêtes
    if [[ $# -gt 0 ]]; then
        case "$1" in
            --help|-h)      cli_help; exit 0 ;;
            --version|-v)   echo "VENTES v${VERSION}"; exit 0 ;;
        esac
    fi

    _init_db

    if [[ $# -gt 0 ]]; then
        case "$1" in
            --create)       create_license; exit 0 ;;
            --list)         cli_list; exit 0 ;;
            --detail)       shift; show_license_detail "${1:-}"; exit 0 ;;
            --search)       shift; list_licenses "client_name LIKE '%$(_sql_escape "${1:-}")%' OR uuid LIKE '%${1:-}%'" "RECHERCHE: ${1:-}"; exit 0 ;;
            --stats)        show_stats; exit 0 ;;
            --backup)       backup_db "cli"; exit 0 ;;
            --restore)      restore_backup; exit 0 ;;
            --check)        system_check; exit 0 ;;
            --integrity)    verify_integrity; exit 0 ;;
            --api)          shift; cli_api "$@"; exit 0 ;;
            *)              echo "Option inconnue: $1"; cli_help; exit 1 ;;
        esac
    fi

    # Mode interactif
    _main_menu
}

_main "$@"
