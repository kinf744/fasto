#!/usr/bin/env bash
# ==============================================================================
#  KIGHMU PANEL — V3.9.9
#  Panneau de contrôle VPS (SSH / Xray / V2Ray-DNS / ZIVPN / Hysteria / ...)
#  Fichier unique — nftables only — sans panel web, sans bot telegram
#  PROPRIÉTAIRE — Distribution non autorisée interdite.
# ==============================================================================

# ── Protection anti-copie / anti-débogage ─────────────────────────────────────
_secure_init() {
    # Détection debugger (strace, gdb, ltrace) via /proc
    if [[ -f /proc/self/status ]]; then
        local tracer
        tracer=$(grep -oP '^TracerPid:\s*\K\d+' /proc/self/status 2>/dev/null || echo 0)
        if [[ "$tracer" != "0" ]]; then
            echo -e "\033[0;31mERROR: Debugging detected.\033[0m" >&2
            exit 1
        fi
    fi
    # Vérification racine
    [[ $EUID -eq 0 ]] || { echo -e "\033[0;31mERROR: Root required.\033[0m" >&2; exit 1; }
    # Umask restrictif : aucun droit pour groupe/autres
    umask 077
    # Verrouillage des permissions du script lui-même
    [[ -f "$0" ]] && chmod 700 "$0" 2>/dev/null || true
}
_secure_init

# ── Vérification de licence ───────────────────────────────────────────────────
# L'utilisateur doit saisir une clé de licence valide (créée via ventes.sh).
_verify_license() {
    local CYAN=$'\e[38;2;0;200;255m'   YELLOW=$'\e[38;2;255;196;0m'
    local WHITE=$'\e[38;2;235;235;235m' GREEN=$'\e[1;38;2;0;230;80m'
    local RED=$'\e[1;38;2;255;70;70m'   GRAY=$'\e[38;2;120;120;120m'
    local RST=$'\e[0m'                  BLD=$'\e[1m'
    local MAGENTA=$'\e[38;2;200;100;255m' BLUE=$'\e[38;2;80;160;255m'

    # Activer sqlite3 si nécessaire
    command -v sqlite3 &>/dev/null || {
        echo -e " ${YELLOW}[!]${RST} Installation de sqlite3..."
        apt-get update -qq 2>/dev/null && apt-get install -y -qq sqlite3 2>/dev/null || true
    }

    local db="/etc/ventes/ventes.db"
    local tries=0 key="" name="" expires="" status_text=""
    local ok=0

    # Si une clé est déjà enregistrée et valide → on passe
    if [[ -f /etc/kighmu/.license_key ]]; then
        local stored_key
        stored_key=$(cat /etc/kighmu/.license_key 2>/dev/null || echo "")
        if [[ -n "$stored_key" && "$stored_key" != "KIGHMU_MASTER_2026" ]] && [[ -f "$db" ]]; then
            local row
            row=$(sqlite3 "$db" "SELECT client_name FROM licenses WHERE license_key='$stored_key' AND status='ACTIVE' AND (expires_at >= date('now') OR expires_at='9999-12-31');" 2>/dev/null)
            if [[ -n "$row" ]]; then
                echo "$row" > /etc/kighmu/.client_name 2>/dev/null || true
                sqlite3 "$db" "UPDATE licenses SET last_checkin=datetime('now') WHERE license_key='$stored_key';" 2>/dev/null || true
                return 0
            fi
        fi
        [[ "$stored_key" == "KIGHMU_MASTER_2026" ]] && { echo "ADMIN" > /etc/kighmu/.client_name 2>/dev/null || true; return 0; }
    fi

    while (( tries < 3 && ok == 0 )); do
        clear
        echo
        echo -e "  ${BLUE}╔══════════════════════════════════════════════════════╗${RST}"
        echo -e "  ${BLUE}║${RST}         ${WHITE}🔑 VERIFICATION DE LICENCE${RST}${BLUE}                ║${RST}"
        echo -e "  ${BLUE}║${RST}         ${GRAY}KIGHMU PANEL v3.9.9${RST}${BLUE}                         ║${RST}"
        echo -e "  ${BLUE}╚══════════════════════════════════════════════════════╝${RST}"
        echo
        echo -e "  ${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
        echo -e "  ${WHITE}  Veuillez saisir votre clé de licence pour continuer${RST}"
        echo -e "  ${YELLOW}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${RST}"
        echo
        echo -e "  ${GRAY}  Exemple : a137726f21f7360a825fd376a3dfe9bd${RST}"
        echo

        if [[ ! -f "$db" ]]; then
            echo -e "  ${YELLOW}⚠${RST}  ${WHITE}Aucune base de licence trouvée.${RST}"
            echo -e "  ${GRAY}  Exécutez d'abord ventes.sh pour créer une licence.${RST}"
            echo
        fi

        echo -ne "  ${CYAN}►${RST} ${WHITE}Clé de licence :${RST} " >&2
        read -r key
        key="${key// /}"

        # Mode bypass : maître
        if [[ "$key" == "KIGHMU_MASTER_2026" ]]; then
            echo -e "  ${GREEN}✓${RST}  ${WHITE}Mode maître activé.${RST}"
            mkdir -p /etc/kighmu 2>/dev/null
            echo "ADMIN" > /etc/kighmu/.client_name 2>/dev/null || true
            chmod 600 /etc/kighmu/.client_name 2>/dev/null || true
            ok=1; break
        fi

        # Vérification dans la base
        if [[ -f "$db" ]]; then
            local row
            row=$(sqlite3 "$db" "SELECT client_name, expires_at, status FROM licenses WHERE license_key='$key' AND status='ACTIVE' AND (expires_at >= date('now') OR expires_at='9999-12-31');" 2>/dev/null)
            if [[ -n "$row" ]]; then
                IFS='|' read -r name expires status_text <<< "$row"
                echo
                echo -e "  ${GREEN}✔${RST}  ${WHITE}Licence valide !${RST}"
                echo -e "  ${GRAY}  Client : ${WHITE}${name}${RST}${GRAY} | expire : ${WHITE}${expires}${RST}"
                echo
                # Marquer le checkin
                sqlite3 "$db" "UPDATE licenses SET last_checkin=datetime('now') WHERE license_key='$key';" 2>/dev/null || true
                mkdir -p /etc/kighmu 2>/dev/null
                echo "$key" > /etc/kighmu/.license_key
                echo "$name" > /etc/kighmu/.client_name
                chmod 600 /etc/kighmu/.license_key /etc/kighmu/.client_name
                echo -e "  ${GRAY}Installation autorisée.${RST}"
                ok=1; break
            fi
            echo
            echo -e "  ${RED}✗${RST}  ${WHITE}Clé invalide ou licence expirée.${RST}"
        else
            echo
            echo -e "  ${RED}✗${RST}  ${WHITE}Aucune base de licence disponible.${RST}"
            echo -e "  ${GRAY}  Contactez l'administrateur.${RST}"
        fi

        tries=$((tries + 1))
        local remaining=$((3 - tries))
        echo
        echo -e "  ${YELLOW}⚠${RST}  ${WHITE}Il vous reste ${remaining} tentative(s).${RST}"
        echo
        if (( tries < 3 )); then
            echo -ne "  ${GRAY}Appuyez sur Entrée pour réessayer...${RST}" >&2; read -r
        fi
    done

    if (( ok == 0 )); then
        echo
        echo -e "  ${RED}╔════════════════════════════════════════════╗${RST}"
        echo -e "  ${RED}║${RST}  ${WHITE}LICENCE INVALIDE — INSTALLATION BLOQUÉE${RST}${RED}    ║${RST}"
        echo -e "  ${RED}╚════════════════════════════════════════════╝${RST}"
        echo
        exit 1
    fi
}

# S'assurer d'un locale UTF-8 (comptage correct des caractères box-drawing) ----
if ! locale 2>/dev/null | grep -qiE 'UTF-8'; then
    export LC_ALL=C.UTF-8 2>/dev/null || export LC_ALL=en_US.UTF-8 2>/dev/null || true
fi

# ==============================================================================
#  SECTION 1 — PALETTE DE COULEURS (définie UNE SEULE FOIS)
# ==============================================================================
CYAN=$'\e[1;38;2;0;200;255m'     # Bannière ASCII (cyan gras)
YELLOW=$'\e[38;2;255;196;0m'     # Séparateurs ─, puces ○, flèches ⇨ ►
WHITE=$'\e[38;2;235;235;235m'    # Labels, texte standard, noms d'options
GREEN=$'\e[1;38;2;0;230;80m'     # Statuts [ON], numéros de menu [0X]
RED=$'\e[1;38;2;255;70;70m'      # Statuts [OFF], alertes, valeurs > 90%
GRAY=$'\e[38;2;130;130;140m'     # Version, texte secondaire, "Press ENTER..."
KEYBG=$'\e[48;2;0;190;90m\e[30m' # Fond vert + texte noir : bloc "Key: Verified"
BTNBG=$'\e[48;2;255;196;0m\e[30m' # Fond jaune + texte noir : boutons [EXIT]/[BACK]
BOLD=$'\e[1m'
RESET=$'\e[0m'

VERSION="V3.9.9"
_client_name() { local n; n=$(cat /etc/kighmu/.client_name 2>/dev/null || echo "---"); printf '%s' "Verified - ${n} tech tutorials oficial ©"; }

# ==============================================================================
#  HELPERS DE RENDU DYNAMIQUE (réutilisés par TOUS les écrans)
# ==============================================================================

# Retire les séquences ANSI pour mesurer la largeur visible réelle d'une ligne
strip_ansi() { printf '%s' "$1" | sed -E 's/\x1b\[[0-9;]*m//g'; }

# Longueur visible (en caractères) d'une chaîne colorée
vislen() { local s; s=$(strip_ansi "$1"); printf '%s' "${#s}"; }

# Rendu d'un écran complet à partir d'un tableau de lignes.
#   - Le token %SEP% devient un séparateur ─ dont la largeur est calculée
#     dynamiquement : (ligne de contenu la plus longue) + 2.
#   - Une ligne préfixée %FREE% est affichée telle quelle mais EXCLUE du calcul
#     de largeur (liens de connexion, WS payload : peuvent dépasser volontairement).
#   - Aucune largeur codée en dur, aucun tput cols.
render_screen() {
    local -n _lines=$1
    local w=0 l vl
    for l in "${_lines[@]}"; do
        [[ "$l" == "%SEP%" ]]   && continue
        [[ "$l" == "%FREE%"* ]] && continue
        vl=$(vislen "$l")
        (( vl > w )) && w=$vl
    done
    w=$(( w + 2 ))
    local dash; dash=$(printf '─%.0s' $(seq 1 "$w"))
    for l in "${_lines[@]}"; do
        if [[ "$l" == "%SEP%" ]]; then
            echo -e "${YELLOW}${dash}${RESET}"
        elif [[ "$l" == "%FREE%"* ]]; then
            echo -e "${l#%FREE%}"
        else
            echo -e "$l"
        fi
    done
}

# Pause lecture seule (écrans détails/logs) : n'importe quelle touche revient
press_enter() { echo; echo -ne "${GRAY} Press ENTER to go back...${RESET}"; read -r _; }

# --- Helpers d'affichage pour écrans de détails ---
get_domain() {
    local d
    d=$(cat /etc/kighmu/domain.txt 2>/dev/null)
    [[ -z "$d" ]] && d=$(cat /etc/xray/domain 2>/dev/null)
    [[ -z "$d" ]] && d=$(cat /etc/v2ray/domain.txt 2>/dev/null)
    [[ -z "$d" ]] && d=$(get_ip)
    printf '%s' "$d"
}
# Leader pointillé : "LABEL ........" complété jusqu'à largeur W
dot() {
    local lbl="$1" w="${2:-18}" n
    n=$(( w - ${#lbl} - 1 )); (( n < 1 )) && n=1
    printf '%s %s' "$lbl" "$(printf '.%.0s' $(seq 1 "$n"))"
}
# Couleur d'expiration : vert > 7 j, jaune 1-7 j, rouge si expiré
exp_color() {
    local d="$1" now days
    [[ -z "$d" ]] && { echo -e "${GREEN}permanent${RESET}"; return; }
    now=$(date +%s)
    local t; t=$(date -d "$d" +%s 2>/dev/null) || { echo -e "${WHITE}${d}${RESET}"; return; }
    days=$(( (t - now) / 86400 ))
    if   (( days < 0 ));  then echo -e "${RED}${d} (expired)${RESET}"
    elif (( days <= 7 )); then echo -e "${YELLOW}${d} (${days}d left)${RESET}"
    else                       echo -e "${GREEN}${d} (${days}d left)${RESET}"
    fi
}
# Encodeur lien VMess : objet JSON base64 (net=ws|grpc, tls on/off)
vmess_link() {
    local uuid="$1" host="$2" port="$3" net="$4" tls="$5" pathOrSvc="$6" ps="$7" sni="$8"
    local json
    if [[ "$net" == "grpc" ]]; then
        json=$(printf '{"v":"2","ps":"%s","add":"%s","port":"%s","id":"%s","aid":"0","scy":"auto","net":"grpc","type":"multi","path":"%s","tls":"%s","sni":"%s"}' \
            "$ps" "$host" "$port" "$uuid" "$pathOrSvc" "$tls" "$sni")
    else
        json=$(printf '{"v":"2","ps":"%s","add":"%s","port":"%s","id":"%s","aid":"0","scy":"auto","net":"ws","type":"none","host":"%s","path":"%s","tls":"%s","sni":"%s"}' \
            "$ps" "$host" "$port" "$uuid" "$host" "$pathOrSvc" "$tls" "$sni")
    fi
    printf 'vmess://%s' "$(printf '%s' "$json" | base64 -w0 2>/dev/null || printf '%s' "$json" | base64 | tr -d '\n')"
}

# ==============================================================================
#  COLLECTEURS DE DONNÉES SYSTÈME RÉELLES (jamais simulées)
# ==============================================================================
USERDIR="${USERDIR:-/etc/kighmu/users}"    # métadonnées comptes (expiry, limite, ...)
STATEDIR="${STATEDIR:-/etc/kighmu/state}"  # bascules de fonctionnalités

get_os()      { . /etc/os-release 2>/dev/null; printf '%s' "${PRETTY_NAME:-$(uname -s)}"; }
get_arch()    { uname -m; }
get_cores()   { nproc 2>/dev/null || echo 1; }
get_ip()      {
    local ip
    ip=$(curl -s --max-time 2 ifconfig.me 2>/dev/null)
    [[ -z "$ip" ]] && ip=$(curl -s --max-time 2 ipinfo.io/ip 2>/dev/null)
    [[ -z "$ip" ]] && ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    printf '%s' "${ip:-N/A}"
}
get_datetime() { date '+%Y-%m-%d %H:%M:%S'; }

# --- RAM (Mo bruts convertis, jamais de Ko) ---
_mem_field() { free -m | awk -v c="$1" '/^Mem:/{print $c}'; }
ram_total_g() { awk "BEGIN{printf \"%.1f\", $(_mem_field 2)/1024}"; }
ram_free_g()  { awk "BEGIN{printf \"%.1f\", $(_mem_field 7)/1024}"; }   # available
ram_used_g()  { awk "BEGIN{printf \"%.1f\", $(_mem_field 3)/1024}"; }
ram_buffer_m(){ _mem_field 6; }                                        # buff/cache
ram_pct()     { local t u; t=$(_mem_field 2); u=$(_mem_field 3); (( t==0 )) && { echo 0; return; }; echo $(( u*100/t )); }

# --- CPU % instantané (delta /proc/stat) ---
cpu_pct() {
    local a b c d e f g
    read -r _ a b c d e f g _ < /proc/stat
    local idle1=$((d+e)) busy1=$((a+b+c+f+g))
    sleep 0.2
    read -r _ a b c d e f g _ < /proc/stat
    local idle2=$((d+e)) busy2=$((a+b+c+f+g))
    local didle=$((idle2-idle1)) dbusy=$((busy2-busy1)) tot=$((idle2+busy2-idle1-busy1))
    (( tot<=0 )) && { echo 0; return; }
    echo $(( dbusy*100/tot ))
}

# Colore un pourcentage : rouge si > 90, sinon jaune vif
pct_color() { local p=$1; if (( p > 90 )); then echo -e "${RED}${p}%${RESET}"; else echo -e "${YELLOW}${p}%${RESET}"; fi; }

# --- Comptage utilisateurs / connexions ---
# ONLINE fiable : compte les sessions authentifiées réelles, pas les sockets.
#   OpenSSH  → processus enfant "sshd: <user>" ou "sshd: <user>@pts" (exclut
#              les lignes [priv]/[listener]/[net]/[accepted] et le master -D).
#   Dropbear → processus enfants (total dropbear - 1 master).
# Couvre WS/SSL/SlowDNS qui aboutissent tous sur sshd(22) ou dropbear(109),
# donc aucun double comptage.
_openssh_sessions() {
    ps -eo cmd= 2>/dev/null | grep -cE '^sshd(-session)?: [^ ]+(@[^ ]+)?$'
}
_dropbear_sessions() {
    local t; t=$(pgrep -x dropbear 2>/dev/null | wc -l)
    (( t > 0 )) && echo $(( t - 1 )) || echo 0
}
count_ssh_online() {
    local o d; o=$(_openssh_sessions); d=$(_dropbear_sessions)
    echo $(( o + d ))
}
# Détail par utilisateur (username|since_epoch), une ligne par session
ssh_online_detail() {
    ps -eo pid=,lstart=,cmd= 2>/dev/null | awk '
        {
            # champs 1=pid, 2..6=lstart (Www Mmm dd HH:MM:SS YYYY), 7+=cmd
            pid=$1
            cmd=""
            for(i=7;i<=NF;i++){cmd=cmd (i>7?" ":"") $i}
            if (cmd ~ /^sshd(-session)?: [^ ]+(@[^ ]+)?$/) {
                u=cmd; sub(/^sshd(-session)?: /,"",u); sub(/@.*/,"",u)
                since=$2" "$3" "$4" "$5" "$6
                print u"|"since
            }
        }'
}
count_ssh_total() { awk -F: '$3>=1000 && $7 ~ /(bash|sh)$/ {n++} END{print n+0}' /etc/passwd; }
count_xray_total(){ jq '[.vmess,.vless,.trojan]|map(length)|add' /etc/xray/users.json 2>/dev/null || echo 0; }

count_total_users() { echo $(( $(count_ssh_total) + $(count_xray_total) )); }

# --- Compteurs par famille (total / expirés), source = fichiers de comptes ---
# Format attendu d'un fichier utilisateur $USERDIR/<name> : lignes clé=valeur
#   proto=ssh|vmess|vless|trojan|v2raydns|zivpn|hysteria
#   exp=YYYY-MM-DD
_family_file_field() { grep -oP "^$2=\K.*" "$1" 2>/dev/null; }

# Compte les fichiers de $USERDIR dont proto ∈ liste passée ($2...) ; $1 = mode
#   mode "total"   → tous ; "exp" → expirés ; "active" → non expirés
_count_family() {
    local mode="$1"; shift
    local -a protos=("$@")
    local today n=0 f p e match
    today=$(date +%Y-%m-%d)
    [[ -d "$USERDIR" ]] || { echo 0; return; }
    for f in "$USERDIR"/*; do
        [[ -f "$f" ]] || continue
        p=$(_family_file_field "$f" proto); match=0
        for x in "${protos[@]}"; do [[ "$p" == "$x" ]] && match=1 && break; done
        (( match )) || continue
        e=$(_family_file_field "$f" exp)
        case "$mode" in
            total)  (( n++ )) ;;
            exp)    [[ -n "$e" && "$e" < "$today" ]] && (( n++ )) ;;
            active) [[ -z "$e" || ! "$e" < "$today" ]] && (( n++ )) ;;
        esac
    done
    echo "$n"
}
fam_total()  { _count_family total  "$@"; }
fam_expired(){ _count_family exp    "$@"; }
fam_active() { _count_family active "$@"; }
count_expired() {
    local n=0 today f exp
    today=$(date +%Y-%m-%d)
    [[ -d "$USERDIR" ]] || { echo 0; return; }
    for f in "$USERDIR"/*; do
        [[ -f "$f" ]] || continue
        exp=$(grep -oP '^exp=\K.*' "$f" 2>/dev/null)
        [[ -n "$exp" && "$exp" < "$today" ]] && (( n++ ))
    done
    echo "$n"
}
count_locked() { awk -F: '$3>=1000 && $2 ~ /^!/ {n++} END{print n+0}' /etc/shadow 2>/dev/null || echo 0; }

# Statut d'un service systemd → [ON] vert / [OFF] rouge
svc_status() {
    if systemctl is-active --quiet "$1" 2>/dev/null; then
        echo -e "${GREEN}[ON]${RESET}"
    else
        echo -e "${RED}[OFF]${RESET}"
    fi
}
# Statut d'une bascule (fichier marqueur) → [ON]/[OFF]
flag_status() { if [[ -f "$STATEDIR/$1" ]]; then echo -e "${GREEN}[ON]${RESET}"; else echo -e "${RED}[OFF]${RESET}"; fi; }

# ---- Détections réelles pour OPTIMIZE VPS -----------------------------------
# BBR actif si le congestion control courant est bbr
bbr_status() {
    local cc; cc=$(sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null)
    if [[ "$cc" == "bbr" ]]; then echo -e "${GREEN}[ON]${RESET}"; else echo -e "${RED}[OFF]${RESET}"; fi
}
# Limite des logs journald active si SystemMaxUse est défini (non commenté)
loglimit_status() {
    if grep -qsE '^[[:space:]]*SystemMaxUse=' /etc/systemd/journald.conf 2>/dev/null; then
        echo -e "${GREEN}[ON]${RESET}"
    else
        echo -e "${RED}[OFF]${RESET}"
    fi
}
# Tuning sysctl appliqué si notre fichier drop-in existe
sysctl_status() {
    if [[ -f /etc/sysctl.d/99-kighmu.conf ]]; then echo -e "${GREEN}[ON]${RESET}"; else echo -e "${RED}[OFF]${RESET}"; fi
}
# Date de dernière optimisation (contenu du marqueur) ou NEVER
last_optimized() {
    local f="$STATEDIR/optimized"
    if [[ -s "$f" ]]; then cat "$f"; else echo "NEVER"; fi
}

# Intervalle de rafraîchissement du compteur online (secondes), défaut 5
refresh_interval() {
    local f="$STATEDIR/refresh_interval" v
    v=$(cat "$f" 2>/dev/null)
    [[ "$v" =~ ^[0-9]+$ && "$v" -gt 0 ]] && echo "$v" || echo 5
}

# ---- Détection réelle d'installation d'un protocole -------------------------
# proto_on <candidat...> : vrai si un des services systemd est actif OU si un
# binaire du même nom est présent dans le PATH. Sert au PROTOCOL INSTALLER.
proto_on() {
    local x
    for x in "$@"; do
        systemctl is-active --quiet "$x" 2>/dev/null && return 0
        command -v "$x" >/dev/null 2>&1 && return 0
    done
    return 1
}

# ==============================================================================
#  BANNIÈRE ASCII "KIGHMU" (style figlet 'standard' — cyan gras)
# ==============================================================================
# Tableau global de lignes (embarqué, aucune dépendance figlet à l'exécution)
BANNER_LINES=(
'     _  _____ ____ _   _ __  __ _   _ '
'    | |/ /_ _/ ___| | | |  \/  | | | |'
"    | ' / | | |  _| |_| | |\\/| | | | |"
'    | . \ | | |_| |  _  | |  | | |_| |'
'    |_|\_\___\____|_| |_|_|  |_|\___/ '
)

# ==============================================================================
#  SECTION 2 — PANNEAU PRINCIPAL
# ==============================================================================
scr_main() {
    clear

    # -- Données réelles recalculées à chaque affichage --
    local ONL EXP KILL TOT OS ARCH CORES IP DT
    ONL=$(count_ssh_online); EXP=$(count_expired); KILL=$(count_locked); TOT=$(count_total_users)
    OS=$(get_os); ARCH=$(get_arch); CORES=$(get_cores); IP=$(get_ip); DT=$(get_datetime)

    local RT RF RU RPCT CPCT BUF
    RT=$(ram_total_g); RF=$(ram_free_g); RU=$(ram_used_g)
    RPCT=$(ram_pct); CPCT=$(cpu_pct); BUF=$(ram_buffer_m)

    # -- Grille de protocoles (tableau nom:port, colonnes dynamiques) --
    local ports=(
        "SSH:22"            "Dropbear:109"      "V2Ray-DNS:5401"
        "HAProxy:447"       "SSH-WS:80"         "SSH-SSL:444"
        "Xray:8880/443"     "SlowDNS:5300"      "ZIVPN:5667"
        "Hysteria:20000"    "BadVPN:7100-7300"  "UDP-Custom:36712"
    )
    # largeur de colonne = plus long "NAME: PORT" du tableau
    local cw=0 p nm pr disp
    for p in "${ports[@]}"; do
        nm=${p%%:*}; pr=${p#*:}; disp="${nm}: ${pr}"
        (( ${#disp} > cw )) && cw=${#disp}
    done
    local pg=() row="" i=0
    for p in "${ports[@]}"; do
        nm=${p%%:*}; pr=${p#*:}; disp="${nm}: ${pr}"
        row+=$(printf " ${YELLOW}○${RESET} ${WHITE}%-*s${RESET} " "$cw" "$disp")
        (( i++ ))
        if (( i % 3 == 0 )); then pg+=("$row"); row=""; fi
    done
    [[ -n "$row" ]] && pg+=("$row")

    # -- Statuts dynamiques des options --
    local ST_OPT ST_ONL ST_AUTO
    ST_OPT=$(flag_status optimized)
    ST_ONL=$(flag_status online_counter)
    ST_AUTO=$(flag_status autostart)

    # -- Lignes de menu : padding dynamique pour aligner les statuts --
    local m_labels=(
        "MANAGE USERS (SSH/XRAY/V2RAY/ZIVPN/HYSTERIA)"
        "OPTIMIZE VPS"
        "ONLINE USERS COUNTER"
        "AUTO-START SCRIPT"
        "PROTOCOL INSTALLER"
    )
    local mw=0 lbl
    for lbl in "${m_labels[@]}"; do (( ${#lbl} > mw )) && mw=${#lbl}; done
    local menu1 menu2 menu3 menu4 menu5
    menu1=$(printf " ${GREEN}[01]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%s${RESET}" "${m_labels[0]}")
    menu2=$(printf " ${GREEN}[02]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%-*s${RESET}  %b" "$mw" "${m_labels[1]}" "$ST_OPT")
    menu3=$(printf " ${GREEN}[03]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%-*s${RESET}  %b" "$mw" "${m_labels[2]}" "$ST_ONL")
    menu4=$(printf " ${GREEN}[04]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%-*s${RESET}  %b" "$mw" "${m_labels[3]}" "$ST_AUTO")
    menu5=$(printf " ${GREEN}[05]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%s${RESET}" "${m_labels[4]}")

    # -- Construction de l'écran --
    local L=( "%SEP%" )
    local bl
    for bl in "${BANNER_LINES[@]}"; do L+=( "${CYAN}${bl}${RESET}" ); done
    L+=( "           ${WHITE}👤 $(_client_name)${RESET}" )
    L+=(
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}ONLINES:${RESET} ${GREEN}[${ONL}]${RESET}  ${GRAY}•${RESET}  ${WHITE}EXP:${RESET} ${RED}[${EXP}]${RESET}  ${GRAY}•${RESET}  ${WHITE}KILL:${RESET} ${RED}[${KILL}]${RESET}  ${GRAY}•${RESET}  ${WHITE}TOTAL:${RESET} ${WHITE}[${TOT}]${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}S.O:${RESET} ${WHITE}${OS}${RESET}  ${GRAY}•${RESET}  ${WHITE}Base:${RESET} ${WHITE}${ARCH}${RESET}  ${GRAY}•${RESET}  ${WHITE}CPU's:${RESET} ${WHITE}${CORES}${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}IP:${RESET} ${WHITE}${IP}${RESET}  ${GRAY}•${RESET}  ${WHITE}TIME:${RESET} ${WHITE}${DT}${RESET}"
        "%SEP%"
        " ${KEYBG} Key: [ $(_client_name) ] ${RESET}   ${GRAY}(${VERSION})${RESET}"
        "%SEP%"
    )
    L+=("${pg[@]}")
    L+=(
        "%SEP%"
        " ${WHITE}TOTAL:${RESET} ${WHITE}${RT}G${RESET}  ${GRAY}•${RESET}  ${WHITE}M|LIBRE:${RESET} ${GREEN}${RF}G${RESET}  ${GRAY}•${RESET}  ${WHITE}EN USO:${RESET} ${YELLOW}${RU}G${RESET}"
        " ${WHITE}U/RAM:${RESET} $(pct_color "$RPCT")  ${GRAY}•${RESET}  ${WHITE}U/CPU:${RESET} $(pct_color "$CPCT")  ${GRAY}•${RESET}  ${WHITE}BUFFER:${RESET} ${WHITE}${BUF}M${RESET}"
        "%SEP%"
        "$menu1"
        "$menu2"
        "$menu3"
        "$menu4"
        "$menu5"
        "%SEP%"
        " ${GREEN}[06]${RESET} ${YELLOW}⇨${RESET} ${WHITE}UPDATE / REMOVE${RESET}     ${GRAY}|${RESET}     ${BTNBG} [0] ⇦ [ EXIT ] ${RESET}"
        "%SEP%"
    )
    render_screen L
    echo
    echo -ne " ${YELLOW}►${RESET} ${WHITE}Option : ${RESET}"
}

# ==============================================================================
#  HELPER : en-tête commun des sous-menus (ajoute des lignes à un array)
# ==============================================================================
# Usage : push_header OUT_ARRAY MODE "ligne MENU" ["ligne 2" ...]
#   MODE "full"   → ajoute une ligne SCRIPT/VERSION après les lignes MENU
#   MODE "simple" → pas de ligne SCRIPT/VERSION
#   Toujours suivi de la ligne Key encadrée (fond vert/noir).
push_header() {
    local -n _out=$1; local mode="$2"; shift 2
    _out+=( "%SEP%" )
    local ln
    for ln in "$@"; do _out+=( "$ln" ); done
    [[ "$mode" == "full" ]] && _out+=( " ${YELLOW}○${RESET} ${WHITE}SCRIPT :${RESET} ${WHITE}Kighmu Panel${RESET}   ${GRAY}•${RESET}   ${WHITE}VERSION :${RESET} ${GREEN}${VERSION}${RESET}" )
    _out+=( "%SEP%" " ${KEYBG} Key: [ $(_client_name) ] ${RESET}" "%SEP%" )
}

# ==============================================================================
#  SECTION 3 — MANAGE USERS (sélection de famille)
# ==============================================================================
scr_manage_users() {
    clear
    local TOT ONL EXP
    TOT=$(count_total_users); ONL=$(count_ssh_online); EXP=$(count_expired)
    local L=()
    push_header L full " ${YELLOW}○${RESET} ${WHITE}MENU :${RESET} ${WHITE}MANAGE USERS${RESET}"
    L+=(
        " ${YELLOW}○${RESET} ${WHITE}TOTAL USERS:${RESET} ${WHITE}[${TOT}]${RESET}        ${YELLOW}○${RESET} ${WHITE}ONLINE NOW:${RESET} ${GREEN}[${ONL}]${RESET}        ${YELLOW}○${RESET} ${WHITE}EXPIRED:${RESET} ${RED}[${EXP}]${RESET}"
        "%SEP%"
        " ${GREEN}[01]${RESET} ${YELLOW}⇨${RESET} ${WHITE}SSH (WS/SSL/SlowDNS/UDP-Custom/BadVPN)${RESET}"
        " ${GREEN}[02]${RESET} ${YELLOW}⇨${RESET} ${WHITE}XRAY (Vmess/Vless/Trojan)${RESET}"
        " ${GREEN}[03]${RESET} ${YELLOW}⇨${RESET} ${WHITE}V2RAY-DNS${RESET}"
        " ${GREEN}[04]${RESET} ${YELLOW}⇨${RESET} ${WHITE}ZIVPN${RESET}"
        " ${GREEN}[05]${RESET} ${YELLOW}⇨${RESET} ${WHITE}HYSTERIA${RESET}"
        "%SEP%"
        " ${BTNBG} [0] ⇦ [ BACK TO MAIN MENU ] ${RESET}"
        "%SEP%"
    )
    render_screen L
    echo
    echo -ne " ${YELLOW}►${RESET} ${WHITE}Option : ${RESET}"
}

# ------------------------------------------------------------------------------
#  Générateur de sous-panneau de gestion (SSH / XRAY / V2RAY-DNS / ZIVPN / HYST.)
# ------------------------------------------------------------------------------
# $1 titre-court (SSH/XRAY/...)  $2 sous-titre (2e ligne ○)  $3 label back
# $4 show_online (1/0)  $5 label du bandeau (ex: "SSH")  $6.. protos comptés
_user_subpanel() {
    clear
    local short="$1" subtitle="$2" back="$3" show_online="$4" statlabel="$5"; shift 5
    local -a protos=("$@")
    local TOT EXP ONL
    TOT=$(fam_total "${protos[@]}"); EXP=$(fam_expired "${protos[@]}")
    local L=()
    push_header L full \
        " ${YELLOW}○${RESET} ${WHITE}MENU :${RESET} ${WHITE}MANAGE USERS ▸ ${short}${RESET}" \
        " ${YELLOW}○${RESET} ${subtitle}"
    # Bandeau de stats (avec ou sans ONLINE)
    if [[ "$show_online" == "1" ]]; then
        ONL=$(count_ssh_online)
        L+=( " ${YELLOW}○${RESET} ${WHITE}TOTAL ${statlabel} USERS:${RESET} ${WHITE}[${TOT}]${RESET}     ${YELLOW}○${RESET} ${WHITE}ONLINE:${RESET} ${GREEN}[${ONL}]${RESET}     ${YELLOW}○${RESET} ${WHITE}EXPIRED:${RESET} ${RED}[${EXP}]${RESET}" )
    else
        L+=( " ${YELLOW}○${RESET} ${WHITE}TOTAL ${statlabel} USERS:${RESET} ${WHITE}[${TOT}]${RESET}     ${YELLOW}○${RESET} ${WHITE}EXPIRED:${RESET} ${RED}[${EXP}]${RESET}" )
    fi
    L+=(
        "%SEP%"
        " ${GREEN}[01]${RESET} ${YELLOW}⇨${RESET} ${WHITE}CREATE USER${RESET}"
        " ${GREEN}[02]${RESET} ${YELLOW}⇨${RESET} ${WHITE}LIST USERS${RESET}"
        " ${GREEN}[03]${RESET} ${YELLOW}⇨${RESET} ${WHITE}DELETE USER${RESET}"
        " ${GREEN}[04]${RESET} ${YELLOW}⇨${RESET} ${WHITE}RENEW / EXTEND USER${RESET}"
        " ${GREEN}[05]${RESET} ${YELLOW}⇨${RESET} ${WHITE}LOCK / UNLOCK USER${RESET}"
        " ${GREEN}[06]${RESET} ${YELLOW}⇨${RESET} ${WHITE}CHANGE PASSWORD${RESET}"
        " ${GREEN}[07]${RESET} ${YELLOW}⇨${RESET} ${WHITE}CONNECTION INFO${RESET}"
        " ${GREEN}[08]${RESET} ${YELLOW}⇨${RESET} ${WHITE}DELETE EXPIRED USERS (BULK)${RESET}          ${RED}[!]${RESET}"
        "%SEP%"
        " ${BTNBG} [0] ⇦ [ ${back} ] ${RESET}"
        "%SEP%"
    )
    render_screen L
    echo
    echo -ne " ${YELLOW}►${RESET} ${WHITE}Option : ${RESET}"
}

scr_users_ssh() {
    _user_subpanel "SSH" \
        "${WHITE}TUNNELS: WS / SSL / SlowDNS / UDP-Custom / BadVPN${RESET}" \
        "BACK TO MANAGE USERS" 1 "SSH" \
        ssh
}
scr_users_xray() {
    _user_subpanel "XRAY" \
        "${WHITE}PROTO: Vmess / Vless / Trojan${RESET}" \
        "BACK TO MANAGE USERS" 0 "XRAY" \
        vmess vless trojan
}
scr_users_v2raydns() {
    _user_subpanel "V2RAY-DNS" \
        "${WHITE}VLESS over DNS (SlowDNS NV4)${RESET}" \
        "BACK TO MANAGE USERS" 0 "V2RAY-DNS" \
        v2raydns
}
scr_users_zivpn() {
    _user_subpanel "ZIVPN" \
        "${WHITE}UDP obfuscated tunnel${RESET}" \
        "BACK TO MANAGE USERS" 0 "ZIVPN" \
        zivpn
}
scr_users_hysteria() {
    _user_subpanel "HYSTERIA" \
        "${WHITE}UDP high-speed tunnel${RESET}" \
        "BACK TO MANAGE USERS" 0 "HYSTERIA" \
        hysteria
}

# ------------------------------------------------------------------------------
#  XRAY ▸ CREATE USER : choix du sous-protocole
# ------------------------------------------------------------------------------
scr_xray_create_select() {
    clear
    local L=()
    push_header L simple " ${YELLOW}○${RESET} ${WHITE}MENU :${RESET} ${WHITE}MANAGE USERS ▸ XRAY ▸ CREATE USER${RESET}"
    L+=(
        " ${WHITE}Select sub-protocol :${RESET}"
        "%SEP%"
        " ${GREEN}[01]${RESET} ${YELLOW}⇨${RESET} ${WHITE}VMESS${RESET}"
        " ${GREEN}[02]${RESET} ${YELLOW}⇨${RESET} ${WHITE}VLESS${RESET}"
        " ${GREEN}[03]${RESET} ${YELLOW}⇨${RESET} ${WHITE}TROJAN${RESET}"
        "%SEP%"
        " ${BTNBG} [0] ⇦ [ CANCEL ] ${RESET}"
        "%SEP%"
    )
    render_screen L
    echo
    echo -ne " ${YELLOW}►${RESET} ${WHITE}Option : ${RESET}"
}


# ==============================================================================
#  SECTION 5 — OPTIMIZE VPS
# ==============================================================================
scr_optimize() {
    clear
    local ST_GLOBAL ST_BBR ST_LOG ST_SYS LASTOPT
    ST_GLOBAL=$(flag_status optimized)
    ST_BBR=$(bbr_status)
    ST_LOG=$(loglimit_status)
    ST_SYS=$(sysctl_status)
    LASTOPT=$(last_optimized)

    # -- Libellés du menu : padding dynamique pour aligner les statuts --
    local o_labels=(
        "ENABLE OPTIMIZATION"
        "BBR (TCP CONGESTION CONTROL)"
        "SWAP CONFIGURATION"
        "CLEAN CACHE / TEMP FILES"
        "LIMIT LOG SIZE (JOURNALCTL)"
        "DISABLE UNUSED SERVICES"
        "NETWORK / SYSCTL TUNING"
        "RUN FULL OPTIMIZATION (ALL ABOVE)"
        "RESTORE DEFAULT SETTINGS"
    )
    local ow=0 lbl
    for lbl in "${o_labels[@]}"; do (( ${#lbl} > ow )) && ow=${#lbl}; done

    local o1 o2 o3 o4 o5 o6 o7 o8 o9
    o1=$(printf " ${GREEN}[01]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%-*s${RESET}  %b" "$ow" "${o_labels[0]}" "$ST_GLOBAL")
    o2=$(printf " ${GREEN}[02]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%-*s${RESET}  %b" "$ow" "${o_labels[1]}" "$ST_BBR")
    o3=$(printf " ${GREEN}[03]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%s${RESET}" "${o_labels[2]}")
    o4=$(printf " ${GREEN}[04]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%s${RESET}" "${o_labels[3]}")
    o5=$(printf " ${GREEN}[05]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%-*s${RESET}  %b" "$ow" "${o_labels[4]}" "$ST_LOG")
    o6=$(printf " ${GREEN}[06]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%s${RESET}" "${o_labels[5]}")
    o7=$(printf " ${GREEN}[07]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%-*s${RESET}  %b" "$ow" "${o_labels[6]}" "$ST_SYS")
    o8=$(printf " ${GREEN}[08]${RESET} ${YELLOW}⇨${RESET} ${GREEN}%s${RESET}" "${o_labels[7]}")
    o9=$(printf " ${GREEN}[09]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%-*s${RESET}  ${RED}[!]${RESET}" "$ow" "${o_labels[8]}")

    local L=()
    push_header L full " ${YELLOW}○${RESET} ${WHITE}MENU :${RESET} ${WHITE}OPTIMIZE VPS${RESET}"
    L+=(
        " ${YELLOW}○${RESET} ${WHITE}STATUS:${RESET} ${ST_GLOBAL}        ${YELLOW}○${RESET} ${WHITE}LAST OPTIMIZED:${RESET} ${WHITE}${LASTOPT}${RESET}"
        "%SEP%"
        "$o1"
        "$o2"
        "$o3"
        "$o4"
        "$o5"
        "$o6"
        "$o7"
        "%SEP%"
        "$o8"
        "$o9"
        "%SEP%"
        " ${BTNBG} [0] ⇦ [ BACK TO MAIN MENU ] ${RESET}"
        "%SEP%"
    )
    render_screen L
    echo
    echo -ne " ${YELLOW}►${RESET} ${WHITE}Option : ${RESET}"
}


# ==============================================================================
#  SECTION 6 — ONLINE USERS COUNTER
# ==============================================================================
# NB : seul SSH a un comptage online fiable → pas de détail Xray/V2Ray/Zivpn/Hyst.
scr_online_counter() {
    clear
    local ONL ITV ST_AUTO
    ONL=$(count_ssh_online)
    ITV=$(refresh_interval)
    ST_AUTO=$(flag_status online_counter)

    local c_labels=(
        "VIEW DETAILS (SSH USERS + IP)"
        "REFRESH NOW"
        "TOGGLE AUTO-REFRESH"
        "SET REFRESH INTERVAL"
        "KICK / DISCONNECT USER"
        "EXPORT LOG (ONLINE HISTORY)"
    )
    local cw=0 lbl
    for lbl in "${c_labels[@]}"; do (( ${#lbl} > cw )) && cw=${#lbl}; done

    local c1 c2 c3 c4 c5 c6
    c1=$(printf " ${GREEN}[01]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%s${RESET}" "${c_labels[0]}")
    c2=$(printf " ${GREEN}[02]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%s${RESET}" "${c_labels[1]}")
    c3=$(printf " ${GREEN}[03]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%-*s${RESET}  %b" "$cw" "${c_labels[2]}" "$ST_AUTO")
    c4=$(printf " ${GREEN}[04]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%s${RESET}" "${c_labels[3]}")
    c5=$(printf " ${GREEN}[05]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%s${RESET}" "${c_labels[4]}")
    c6=$(printf " ${GREEN}[06]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%s${RESET}" "${c_labels[5]}")

    # Bandeau REFRESH : AUTO (Xs) si activé, sinon MANUAL
    local refline
    if [[ "$ST_AUTO" == *"[ON]"* ]]; then
        refline=" ${YELLOW}○${RESET} ${WHITE}SSH ONLINE:${RESET} ${GREEN}[${ONL}]${RESET}          ${YELLOW}○${RESET} ${WHITE}REFRESH:${RESET} ${GREEN}AUTO (${ITV}s)${RESET}"
    else
        refline=" ${YELLOW}○${RESET} ${WHITE}SSH ONLINE:${RESET} ${GREEN}[${ONL}]${RESET}          ${YELLOW}○${RESET} ${WHITE}REFRESH:${RESET} ${GRAY}MANUAL${RESET}"
    fi

    local L=()
    push_header L full " ${YELLOW}○${RESET} ${WHITE}MENU :${RESET} ${WHITE}ONLINE USERS COUNTER${RESET}"
    L+=(
        "$refline"
        "%SEP%"
        "$c1"
        "$c2"
        "$c3"
        "$c4"
        "$c5"
        "$c6"
        "%SEP%"
        " ${BTNBG} [0] ⇦ [ BACK TO MAIN MENU ] ${RESET}"
        "%SEP%"
    )
    render_screen L
    echo
    echo -ne " ${YELLOW}►${RESET} ${WHITE}Option : ${RESET}"
}

# ---- 6.1 VIEW DETAILS : tableau aligné USERNAME / CONNECTIONS / SINCE --------
scr_online_details() {
    clear
    local L=()
    push_header L simple " ${YELLOW}○${RESET} ${WHITE}MENU :${RESET} ${WHITE}ONLINE USERS ▸ DETAILS${RESET}"

    # En-têtes de colonnes (largeurs fixes alignées)
    L+=(
        "$(printf " ${WHITE}%-15s %-18s %-10s${RESET}" "USERNAME" "CONNECTIONS" "SINCE")"
        "$(printf " ${GRAY}%-15s %-18s %-10s${RESET}" "────────" "───────────" "─────")"
    )

    # Lignes de données : agréger les sessions par utilisateur
    local rows; rows=$(ssh_online_detail 2>/dev/null)
    if [[ -z "$rows" ]]; then
        L+=( " ${GRAY}(no active SSH session)${RESET}" )
    else
        # compter connexions par user + garder la 1re heure "since"
        local data
        data=$(echo "$rows" | awk -F'|' '
            { cnt[$1]++; if(!($1 in first)) first[$1]=$2 }
            END { for(u in cnt) print u"|"cnt[u]"|"first[u] }' | sort)
        local u c s hhmm
        while IFS='|' read -r u c s; do
            [[ -z "$u" ]] && continue
            # extraire HH:MM:SS depuis "Www Mmm dd HH:MM:SS YYYY"
            hhmm=$(echo "$s" | awk '{print $4}')
            [[ -z "$hhmm" ]] && hhmm="$s"
            L+=( "$(printf " ${GREEN}%-15s${RESET} ${YELLOW}%-18s${RESET} ${WHITE}%-10s${RESET}" "$u" "[$c]" "$hhmm")" )
        done <<< "$data"
    fi

    L+=( "%SEP%" )
    render_screen L
    press_enter
}


# ==============================================================================
#  SECTION 7 — PROTOCOL INSTALLER
# ==============================================================================
# Chaque ligne = bascule Install/Uninstall selon l'état réel détecté.
# HAProxy = dépendance auto de Xray (TLS 443 / NTLS 8880) → bloc informatif, non sélectionnable.
scr_protocol_installer() {
    clear
    # Détection réelle par protocole
    local s_ssh s_ws s_ssl s_xray s_v2ray s_badvpn s_udpcustom s_hyst s_zivpn s_slowdns
    proto_on sshd dropbear dropbear-custom && s_ssh=on || s_ssh=off
    proto_on sshws ws-epro            && s_ws=on     || s_ws=off
    proto_on ssl_tls stunnel4         && s_ssl=on    || s_ssl=off
    proto_on xray                     && s_xray=on   || s_xray=off
    proto_on v2ray                    && s_v2ray=on  || s_v2ray=off
    proto_on badvpn-udpgw badvpn      && s_badvpn=on || s_badvpn=off
    proto_on udp-custom               && s_udpcustom=on || s_udpcustom=off
    proto_on hysteria hysteria-server && s_hyst=on   || s_hyst=off
    proto_on zivpn                    && s_zivpn=on  || s_zivpn=off
    proto_on slowdns                  && s_slowdns=on || s_slowdns=off

    # rend une paire "[STATUT] ⇨ [Action]" alignée
    _pi_line() {
        local idx="$1" label="$2" st="$3" w="$4" stcol action
        if [[ "$st" == "on" ]]; then
            stcol="${GREEN}[ON]${RESET} "; action="${YELLOW}⇨${RESET} ${RED}[ Uninstall ]${RESET}"
        else
            stcol="${RED}[OFF]${RESET}"; action="${YELLOW}⇨${RESET} ${GREEN}[ Install ]${RESET}"
        fi
        printf " ${GREEN}[%s]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%-*s${RESET}  %b   %b" \
            "$idx" "$w" "$label" "$stcol" "$action"
    }

    local p_labels=(
        "SSH / DROPBEAR"
        "WS-EPRO (SSH-WS)"
        "SSL / TLS"
        "XRAY (VMESS/VLESS/TROJAN)"
        "V2RAY-DNS"
        "BADVPN (UDPGW)"
        "UDP CUSTOM"
        "SLOWDNS"
        "HYSTERIA"
        "ZIVPN"
        "INSTALL ALL MISSING"
        "UNINSTALL ALL ACTIVE"
    )
    local pw=0 lbl
    for lbl in "${p_labels[@]}"; do (( ${#lbl} > pw )) && pw=${#lbl}; done

    local p1 p2 p3 p4 p5 p6 p7 p8 p9 p10 p11 p12
    p1=$(_pi_line 01 "${p_labels[0]}" "$s_ssh"    "$pw")
    p2=$(_pi_line 02 "${p_labels[1]}" "$s_ws"     "$pw")
    p3=$(_pi_line 03 "${p_labels[2]}" "$s_ssl"    "$pw")
    p4=$(_pi_line 04 "${p_labels[3]}" "$s_xray"   "$pw")
    p5=$(_pi_line 05 "${p_labels[4]}" "$s_v2ray"  "$pw")
    p6=$(_pi_line 06 "${p_labels[5]}" "$s_badvpn" "$pw")
    p7=$(_pi_line 07 "${p_labels[6]}" "$s_udpcustom" "$pw")
    # SLOWDNS : pas une bascule → [!] + Configure
    p8=$(printf " ${GREEN}[08]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%-*s${RESET}  ${RED}[!]${RESET}    ${YELLOW}⇨${RESET} ${CYAN}Configure${RESET}" "$pw" "${p_labels[7]}")
    p9=$(_pi_line 09 "${p_labels[8]}" "$s_hyst"   "$pw")
    p10=$(_pi_line 10 "${p_labels[9]}" "$s_zivpn"  "$pw")
    p11=$(printf " ${GREEN}[11]${RESET} ${YELLOW}⇨${RESET} ${GREEN}%s${RESET}" "${p_labels[10]}")
    p12=$(printf " ${GREEN}[12]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%-*s${RESET}  ${RED}[!]${RESET}" "$pw" "${p_labels[11]}")
    unset -f _pi_line

    local L=()
    push_header L full " ${YELLOW}○${RESET} ${WHITE}MENU :${RESET} ${WHITE}PROTOCOL INSTALLER${RESET}"
    L+=(
        "$p1"
        "$p2"
        "$p3"
        "$p4"
        "$p5"
        "$p6"
        "$p7"
        "$p8"
        "$p9"
        "$p10"
        "%SEP%"
        "$p11"
        "$p12"
        "%SEP%"
        " ${YELLOW}○${RESET} ${GRAY}Dependencies (auto-installed with Xray):${RESET}"
        " ${YELLOW}○${RESET} ${GRAY}HAProxy .......... included    (TLS 443 / NTLS 8880)${RESET}"
        "%SEP%"
        " ${BTNBG} [0] ⇦ [ BACK TO MAIN MENU ] ${RESET}"
        "%SEP%"
    )
    render_screen L
    echo
    echo -ne " ${YELLOW}►${RESET} ${WHITE}Option : ${RESET}"
}


# ==============================================================================
#  SECTION 8 — UPDATE / REMOVE
# ==============================================================================
# [05]/[06] : libellé en ROUGE (action destructive) + confirmation obligatoire.
# [04] BACKUP : bascule ; crée backup_YYYYMMDD_HHMMSS.tar.gz du dossier de config.
scr_update_remove() {
    clear
    local ST_BACKUP
    ST_BACKUP=$(flag_status backup_before_update)

    local u_labels=(
        "CHECK FOR UPDATES"
        "UPDATE SCRIPT (LATEST VERSION)"
        "CHANGELOG / VERSION HISTORY"
        "BACKUP BEFORE UPDATE"
        "REINSTALL SCRIPT (CLEAN)"
        "REMOVE SCRIPT (UNINSTALL)"
    )
    local uw=0 lbl
    for lbl in "${u_labels[@]}"; do (( ${#lbl} > uw )) && uw=${#lbl}; done

    local u1 u2 u3 u4 u5 u6
    u1=$(printf " ${GREEN}[01]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%-*s${RESET}  ${RED}[!]${RESET}" "$uw" "${u_labels[0]}")
    u2=$(printf " ${GREEN}[02]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%s${RESET}" "${u_labels[1]}")
    u3=$(printf " ${GREEN}[03]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%s${RESET}" "${u_labels[2]}")
    u4=$(printf " ${GREEN}[04]${RESET} ${YELLOW}⇨${RESET} ${WHITE}%-*s${RESET}  %b" "$uw" "${u_labels[3]}" "$ST_BACKUP")
    # [05]/[06] : libellé lui-même en rouge + [!]
    u5=$(printf " ${GREEN}[05]${RESET} ${YELLOW}⇨${RESET} ${RED}%-*s${RESET}  ${RED}[!]${RESET}" "$uw" "${u_labels[4]}")
    u6=$(printf " ${GREEN}[06]${RESET} ${YELLOW}⇨${RESET} ${RED}%-*s${RESET}  ${RED}[!]${RESET}" "$uw" "${u_labels[5]}")

    local L=()
    push_header L full " ${YELLOW}○${RESET} ${WHITE}MENU :${RESET} ${WHITE}UPDATE / REMOVE${RESET}"
    L+=(
        "$u1"
        "$u2"
        "$u3"
        "$u4"
        "$u5"
        "$u6"
        "%SEP%"
        " ${BTNBG} [0] ⇦ [ BACK TO MAIN MENU ] ${RESET}"
        "%SEP%"
    )
    render_screen L
    echo
    echo -ne " ${YELLOW}►${RESET} ${WHITE}Option : ${RESET}"
}


# ==============================================================================
#  SECTION 4 — ÉCRANS "CONNECTION INFO" / FIN DE CRÉATION (lecture seule)
# ==============================================================================
# Titre : ✔ ... CREATED SUCCESSFULLY (vert) si mode=created,
#         🧩 ... USER DETAILS (jaune) si mode=details
_detail_title() {
    local mode="$1" proto="$2" variant="$3" txt
    if [[ "$mode" == "created" ]]; then
        txt=" ${GREEN}${BOLD}✔ ${proto} USER CREATED SUCCESSFULLY${variant:+ ($variant)}${RESET}"
    else
        txt=" ${YELLOW}${BOLD}🧩 ${proto} USER DETAILS${variant:+ ($variant)}${RESET}"
    fi
    printf '%s' "$txt"
}

# ---- 4.1 VLESS : identifiant UUID, 7 liens ----
show_vless_details() {
    clear
    local mode="$1" user="$2" uuid="$3" exp="$4" quota="${5:-0}" protoname="${6:-XRAY}"
    local dom; dom=$(get_domain)
    local L=(
        "%SEP%"
        "$(_detail_title "$mode" "$protoname" "VLESS")"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}$(dot USER 18)${RESET} ${WHITE}${user}${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot DOMAIN 18)${RESET} ${WHITE}${dom}${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot PROTOCOL 18)${RESET} ${WHITE}VLESS${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot VALIDITY 18)${RESET} expires $(exp_color "$exp")"
        " ${YELLOW}○${RESET} ${WHITE}$(dot QUOTA 18)${RESET} ${WHITE}${quota} GB${RESET}"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}UUID${RESET}"
        "   ${GREEN}${uuid}${RESET}"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}PATHS${RESET}"
        "   ${WHITE}$(dot WS 15)${RESET} /vless"
        "   ${WHITE}$(dot XHTTP 15)${RESET} /vless-xhttp"
        "   ${WHITE}$(dot HTTPUpgrade 15)${RESET} /vless-hupgrade"
        "   ${WHITE}$(dot gRPC 15)${RESET} /vless-grpc"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}CONNECTION LINKS${RESET}"
        ""
        "   ${YELLOW}[1] TLS  / WS ...........${RESET}"
        "%FREE%   vless://${uuid}@${dom}:443?security=tls&type=ws&path=/vless&host=${dom}&sni=${dom}#${user}"
        ""
        "   ${YELLOW}[2] NTLS / WS ...........${RESET}"
        "%FREE%   vless://${uuid}@${dom}:8880?security=none&type=ws&path=/vless&host=${dom}#${user}"
        ""
        "   ${YELLOW}[3] TLS  / XHTTP ........${RESET}"
        "%FREE%   vless://${uuid}@${dom}:443?security=tls&type=xhttp&path=/vless-xhttp&host=${dom}&sni=${dom}#${user}"
        ""
        "   ${YELLOW}[4] TLS  / HTTPUpgrade ..${RESET}"
        "%FREE%   vless://${uuid}@${dom}:443?security=tls&type=httpupgrade&path=/vless-hupgrade&host=${dom}&sni=${dom}#${user}"
        ""
        "   ${YELLOW}[5] TLS  / gRPC .........${RESET}"
        "%FREE%   vless://${uuid}@${dom}:443?mode=grpc&security=tls&type=grpc&serviceName=vless-grpc&sni=${dom}#${user}"
        ""
        "   ${YELLOW}[6] NTLS / TCP ..........${RESET}"
        "%FREE%   vless://${uuid}@${dom}:8880?security=none&type=tcp#${user}"
        ""
        "   ${YELLOW}[7] TLS  / TCP ..........${RESET}"
        "%FREE%   vless://${uuid}@${dom}:443?security=tls&type=tcp&sni=${dom}#${user}"
        "%SEP%"
    )
    render_screen L
    press_enter
}

# ---- 4.2 TROJAN : identifiant PASSWORD, 7 liens ----
show_trojan_details() {
    clear
    local mode="$1" user="$2" pass="$3" exp="$4" quota="${5:-0}"
    local dom; dom=$(get_domain)
    local L=(
        "%SEP%"
        "$(_detail_title "$mode" "XRAY" "TROJAN")"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}$(dot USER 18)${RESET} ${WHITE}${user}${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot DOMAIN 18)${RESET} ${WHITE}${dom}${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot PROTOCOL 18)${RESET} ${WHITE}TROJAN${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot VALIDITY 18)${RESET} expires $(exp_color "$exp")"
        " ${YELLOW}○${RESET} ${WHITE}$(dot QUOTA 18)${RESET} ${WHITE}${quota} GB${RESET}"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}PASSWORD${RESET}"
        "   ${GREEN}${pass}${RESET}"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}PATHS${RESET}"
        "   ${WHITE}$(dot WS 15)${RESET} /trojan"
        "   ${WHITE}$(dot XHTTP 15)${RESET} /trojan-xhttp"
        "   ${WHITE}$(dot HTTPUpgrade 15)${RESET} /trojan-hupgrade"
        "   ${WHITE}$(dot gRPC 15)${RESET} /trojan-grpc"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}CONNECTION LINKS${RESET}"
        ""
        "   ${YELLOW}[1] TLS  / WS ...........${RESET}"
        "%FREE%   trojan://${pass}@${dom}:443?security=tls&type=ws&path=/trojan&host=${dom}&sni=${dom}#${user}"
        ""
        "   ${YELLOW}[2] NTLS / WS ...........${RESET}"
        "%FREE%   trojan://${pass}@${dom}:8880?security=none&type=ws&path=/trojan&host=${dom}#${user}"
        ""
        "   ${YELLOW}[3] TLS  / XHTTP ........${RESET}"
        "%FREE%   trojan://${pass}@${dom}:443?security=tls&type=xhttp&path=/trojan-xhttp&host=${dom}&sni=${dom}#${user}"
        ""
        "   ${YELLOW}[4] TLS  / HTTPUpgrade ..${RESET}"
        "%FREE%   trojan://${pass}@${dom}:443?security=tls&type=httpupgrade&path=/trojan-hupgrade&host=${dom}&sni=${dom}#${user}"
        ""
        "   ${YELLOW}[5] TLS  / gRPC .........${RESET}"
        "%FREE%   trojan://${pass}@${dom}:443?mode=grpc&security=tls&type=grpc&serviceName=trojan-grpc&sni=${dom}#${user}"
        ""
        "   ${YELLOW}[6] NTLS / TCP ..........${RESET}"
        "%FREE%   trojan://${pass}@${dom}:8880?security=none&type=tcp#${user}"
        ""
        "   ${YELLOW}[7] TLS  / TCP ..........${RESET}"
        "%FREE%   trojan://${pass}@${dom}:443?security=tls&type=tcp&sni=${dom}#${user}"
        "%SEP%"
    )
    render_screen L
    press_enter
}

# ---- 4.3 VMESS : identifiant UUID, 3 liens base64 ----
show_vmess_details() {
    clear
    local mode="$1" user="$2" uuid="$3" exp="$4" quota="${5:-0}"
    local dom; dom=$(get_domain)
    local l1 l2 l3
    l1=$(vmess_link "$uuid" "$dom" 8880 ws  none "/vmess" "$user" "")
    l2=$(vmess_link "$uuid" "$dom" 443  ws  tls  "/vmess" "$user" "$dom")
    l3=$(vmess_link "$uuid" "$dom" 443  grpc tls "vmess-grpc" "$user" "$dom")
    local L=(
        "%SEP%"
        "$(_detail_title "$mode" "XRAY" "VMESS")"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}$(dot USER 18)${RESET} ${WHITE}${user}${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot DOMAIN 18)${RESET} ${WHITE}${dom}${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot PROTOCOL 18)${RESET} ${WHITE}VMESS${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot VALIDITY 18)${RESET} expires $(exp_color "$exp")"
        " ${YELLOW}○${RESET} ${WHITE}$(dot QUOTA 18)${RESET} ${WHITE}${quota} GB${RESET}"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}UUID${RESET}"
        "   ${GREEN}${uuid}${RESET}"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}PATHS${RESET}"
        "   ${WHITE}$(dot WS 15)${RESET} /vmess"
        "   ${WHITE}$(dot gRPC 15)${RESET} /vmess-grpc"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}CONNECTION LINKS${RESET}"
        ""
        "   ${YELLOW}[1] NTLS / WS ...........${RESET}"
        "%FREE%   ${l1}"
        ""
        "   ${YELLOW}[2] TLS  / WS ...........${RESET}"
        "%FREE%   ${l2}"
        ""
        "   ${YELLOW}[3] TLS  / gRPC .........${RESET}"
        "%FREE%   ${l3}"
        "%SEP%"
    )
    render_screen L
    press_enter
}

# ---- 4.4 HYSTERIA ----
show_hysteria_details() {
    clear
    local mode="$1" user="$2" pass="$3" exp="$4" quota="${5:-0}"
    local dom; dom=$(get_domain)
    local L=(
        "%SEP%"
        "$(_detail_title "$mode" "HYSTERIA" "")"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}$(dot USER 19)${RESET} ${WHITE}${user}${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot DOMAIN 19)${RESET} ${WHITE}${dom}${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot OBFS 19)${RESET} ${WHITE}hysteria${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot VALIDITY 19)${RESET} expires $(exp_color "$exp")"
        " ${YELLOW}○${RESET} ${WHITE}$(dot QUOTA 19)${RESET} ${WHITE}${quota} GB${RESET}"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}PASSWORD${RESET}"
        "   ${GREEN}${pass}${RESET}"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}PORT${RESET}"
        "   ${WHITE}20000-50000${RESET}"
        "%SEP%"
    )
    render_screen L
    press_enter
}

# ---- 4.5 ZIVPN ----
show_zivpn_details() {
    clear
    local mode="$1" user="$2" pass="$3" exp="$4" quota="${5:-0}"
    local dom; dom=$(get_domain)
    local L=(
        "%SEP%"
        "$(_detail_title "$mode" "ZIVPN" "")"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}$(dot USER 19)${RESET} ${WHITE}${user}${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot DOMAIN 19)${RESET} ${WHITE}${dom}${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot OBFS 19)${RESET} ${WHITE}zivpn${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot VALIDITY 19)${RESET} expires $(exp_color "$exp")"
        " ${YELLOW}○${RESET} ${WHITE}$(dot QUOTA 19)${RESET} ${WHITE}${quota} GB${RESET}"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}PASSWORD${RESET}"
        "   ${GREEN}${pass}${RESET}"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}PORT${RESET}"
        "   ${WHITE}5667${RESET}"
        "%SEP%"
    )
    render_screen L
    press_enter
}

# ---- 4.6 V2RAY-DNS ----
show_v2raydns_details() {
    clear
    local mode="$1" user="$2" uuid="$3" exp="$4" quota="${5:-0}"
    local dom pubkey ns4 nv4
    dom=$(get_domain)
    pubkey=$(cat /etc/slowdns/server.pub 2>/dev/null || echo "N/A")
    nv4=$(cat /etc/slowdns/nv4/ns.conf 2>/dev/null || echo "N/A")
    local L=(
        "%SEP%"
        "$(_detail_title "$mode" "V2RAY-DNS" "")"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}$(dot USER 19)${RESET} ${WHITE}${user}${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot DOMAIN 19)${RESET} ${WHITE}${dom}${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot VALIDITY 19)${RESET} expires $(exp_color "$exp")"
        " ${YELLOW}○${RESET} ${WHITE}$(dot QUOTA 19)${RESET} ${WHITE}${quota} GB${RESET}"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}PORTS${RESET}"
        "   ${WHITE}$(dot 'FastDNS UDP' 14)${RESET} 5354"
        "   ${WHITE}$(dot 'V2Ray TCP' 14)${RESET} 5401"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}UUID${RESET}"
        "   ${GREEN}${uuid}${RESET}"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}SLOWDNS CONFIG (PORT 5354)${RESET}"
        "   ${WHITE}$(dot 'Public Key' 12)${RESET} ${pubkey}"
        "   ${WHITE}$(dot NameServer 12)${RESET} ${nv4}"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}V2RAY-DNS LINK${RESET}"
        "%FREE%   vless://${uuid}@${dom}:5401?type=tcp&encryption=none&host=${dom}#${user}-V2RAY-DNS"
        "%SEP%"
    )
    render_screen L
    press_enter
}

# ---- 4.7 SSH ----
show_ssh_details() {
    clear
    local mode="$1" user="$2" pass="$3" exp="$4" quota="${5:-0}"
    local dom ip pubkey ns ua
    dom=$(get_domain); ip=$(get_ip)
    pubkey=$(cat /etc/slowdns/server.pub 2>/dev/null || echo "N/A")
    ns=$(cat /etc/slowdns/ns.conf 2>/dev/null || echo "N/A")
    ua="Mozilla/5.0"
    local L=(
        "%SEP%"
        "$(_detail_title "$mode" "SSH" "")"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}$(dot USER 19)${RESET} ${WHITE}${user}${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot DOMAIN 19)${RESET} ${WHITE}${dom}${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot 'IP HOST' 19)${RESET} ${WHITE}${ip}${RESET}"
        " ${YELLOW}○${RESET} ${WHITE}$(dot VALIDITY 19)${RESET} expires $(exp_color "$exp")"
        " ${YELLOW}○${RESET} ${WHITE}$(dot QUOTA 19)${RESET} ${WHITE}${quota} GB${RESET}"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}PASSWORD${RESET}"
        "   ${GREEN}${pass}${RESET}"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}CONNECTION LINKS${RESET}"
        ""
        "   ${YELLOW}[1] SSH WS ..............${RESET}"
        "%FREE%   ${dom}:80@${user}:${pass}"
        ""
        "   ${YELLOW}[2] SSL/TLS .............${RESET}"
        "%FREE%   ${dom}:444@${user}:${pass}"
        ""
        "   ${YELLOW}[3] PROXY WS ............${RESET}"
        "%FREE%   ${dom}:9090@${user}:${pass}"
        ""
        "   ${YELLOW}[4] SSH UDP .............${RESET}"
        "%FREE%   ${dom}:1-65535@${user}:${pass}"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}WS PAYLOAD${RESET}"
        "%FREE%   ${GRAY}GET / HTTP/1.1[crlf]Host: ${dom}[crlf]Connection: Upgrade[crlf]User-Agent: ${ua}[crlf]Upgrade: websocket[crlf][crlf]${RESET}"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}FASTDNS CONFIG (PORT 5300)${RESET}"
        "%FREE%   ${WHITE}Public Key :${RESET} ${pubkey}"
        "   ${WHITE}NameServer :${RESET} ${ns}"
        "%SEP%"
        " ${YELLOW}○${RESET} ${WHITE}COMPATIBLE APPS${RESET}"
        "   ${WHITE}HTTP Injector, CUSTOM, SocksIP, SSC ZIVPN${RESET}"
        "%SEP%"
    )
    render_screen L
    press_enter
}


# ==============================================================================
#  SÉCURITÉ — Intégrité & permissions
# ==============================================================================
CHKSUM_FILE="${CHKSUM_FILE:-/etc/kighmu/.checksum}"

# Verrouille les permissions de tous les fichiers/dossiers sensibles
_secure_permissions() {
    chmod 700 "$0" 2>/dev/null || true
    chmod 750 /etc/kighmu 2>/dev/null || true
    chmod 750 /etc/kighmu/users 2>/dev/null || true
    chmod 750 /etc/kighmu/bandwidth 2>/dev/null || true
    chmod 750 /etc/kighmu/state 2>/dev/null || true
    chmod 700 /usr/local/bin/kighmu 2>/dev/null || true
    find /etc/kighmu/users -type f -exec chmod 600 {} + 2>/dev/null || true
    find /etc/kighmu/bandwidth -type f -exec chmod 600 {} + 2>/dev/null || true
    find /etc/kighmu/state -type f -exec chmod 600 {} + 2>/dev/null || true
}

# Calcule l'empreinte SHA256 du script lui-même
_script_checksum() {
    if command -v sha256sum &>/dev/null; then
        sha256sum "$0" 2>/dev/null | cut -d' ' -f1
    else
        sha256sum "$0" 2>/dev/null | cut -d' ' -f1 || shasum -a 256 "$0" 2>/dev/null | cut -d' ' -f1 || echo ""
    fi
}

# Stocke le checksum de référence (à faire après installation)
store_checksum() {
    local csum
    csum=$(_script_checksum)
    [[ -n "$csum" ]] && echo "$csum $0" > "$CHKSUM_FILE" && chmod 600 "$CHKSUM_FILE"
}

# Vérifie que le script n'a pas été modifié
verify_integrity() {
    [[ -f "$CHKSUM_FILE" ]] || { echo "INFO: Aucun checksum de référence." >&2; return 1; }
    local stored current
    stored=$(cut -d' ' -f1 < "$CHKSUM_FILE" 2>/dev/null || echo "")
    current=$(_script_checksum)
    if [[ -z "$stored" || -z "$current" ]]; then
        echo "WARN: Impossible de vérifier l'intégrité." >&2
        return 1
    fi
    if [[ "$stored" != "$current" ]]; then
        echo "ALERTE: Le script a été modifié ! (checksum mismatch)" >&2
        echo "  Référence: $stored" >&2
        echo "  Actuel:    $current" >&2
        return 1
    fi
    return 0
}

# ==============================================================================
#  LOGIQUE MÉTIER — GESTION DES UTILISATEURS (source de vérité unifiée)
# ==============================================================================
# Modèle : un fichier par compte dans $USERDIR/<user> avec les champs :
#   proto=ssh|vmess|vless|trojan|v2raydns|zivpn|hysteria
#   exp=YYYY-MM-DD          (date d'expiration)
#   limit=N                 (connexions simultanées ; SSH seulement, optionnel)
#   pass=...                (mot de passe en clair pour affichage ; non-SSH)
#   uuid=...                (vmess/vless/v2raydns)
#   created=YYYY-MM-DD
# Les comptes SSH sont AUSSI de vrais comptes système (useradd + chage).
# Les comptes Xray sont AUSSI injectés dans /etc/xray/users.json.
XRAY_USERS="${XRAY_USERS:-/etc/xray/users.json}"

# ---- Générateurs ----
gen_uuid() { uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid; }
gen_pass() { openssl rand -base64 12 2>/dev/null | tr -dc 'A-Za-z0-9' | head -c 12; }

# ---- Accès fichier méta ----
_meta_file()  { echo "$USERDIR/$1"; }
_meta_get()   { grep -oP "^$2=\K.*" "$USERDIR/$1" 2>/dev/null; }
_meta_exists(){ [[ -f "$USERDIR/$1" ]]; }

# Validation nom d'utilisateur (lettres/chiffres/._- , 1-32)
valid_name() { [[ "$1" =~ ^[a-zA-Z0-9._-]{1,32}$ ]]; }

# Calcule une date d'expiration à +N jours (portable)
exp_in_days() { date -d "+$1 days" +%Y-%m-%d 2>/dev/null || date -v +"$1"d +%Y-%m-%d 2>/dev/null; }

# Écrit/rafraîchit le fichier méta (préserve l'ordre, champs optionnels vides ignorés)
write_meta() {
    local user="$1" proto="$2" exp="$3" limit="$4" pass="$5" uuid="$6" quota="$7"
    mkdir -p "$USERDIR" 2>/dev/null
    {
        echo "proto=$proto"
        echo "exp=$exp"
        [[ -n "$limit" ]] && echo "limit=$limit"
        [[ -n "$pass"  ]] && echo "pass=$pass"
        [[ -n "$uuid"  ]] && echo "uuid=$uuid"
        [[ -n "$quota" ]] && echo "quota=$quota"
        echo "created=$(date +%Y-%m-%d)"
    } > "$USERDIR/$user"
}

# ---- Xray users.json : init + ajout/suppression ----
_xray_init_json() {
    [[ -f "$XRAY_USERS" ]] && return 0
    mkdir -p "$(dirname "$XRAY_USERS")" 2>/dev/null
    echo '{"vmess":[],"vless":[],"trojan":[]}' > "$XRAY_USERS"
}
# ajoute {email,id/password,expiry} dans le tableau du protocole
xray_add_user() {
    local proto="$1" user="$2" cred="$3" exp="$4" tmp
    _xray_init_json
    local key idkey
    case "$proto" in
        vmess|vless) idkey="id" ;;
        trojan)      idkey="password" ;;
        *) return 1 ;;
    esac
    tmp=$(mktemp)
    jq --arg u "$user" --arg c "$cred" --arg e "$exp" --arg ik "$idkey" \
       ".$proto += [{(\$ik):\$c, \"email\":\$u, \"level\":0, \"expire\":\$e}]" \
       "$XRAY_USERS" > "$tmp" 2>/dev/null && mv "$tmp" "$XRAY_USERS" || rm -f "$tmp"
}
xray_del_user() {
    local user="$1" tmp
    [[ -f "$XRAY_USERS" ]] || return 0
    tmp=$(mktemp)
    jq --arg u "$user" \
       '.vmess |= map(select(.email!=$u)) | .vless |= map(select(.email!=$u)) | .trojan |= map(select(.email!=$u))' \
       "$XRAY_USERS" > "$tmp" 2>/dev/null && mv "$tmp" "$XRAY_USERS" || rm -f "$tmp"
}
# recharge Xray si présent (non fatal en test) : reconstruit la config depuis
# users.json (fonction fournie par le bloc installateur) puis redémarre.
xray_reload() {
    command -v xray_build_config >/dev/null 2>&1 && xray_build_config 2>/dev/null || true
    systemctl restart xray 2>/dev/null || true
}

# ==============================================================================
#  CRÉATION D'UTILISATEUR
# ==============================================================================
# create_user <proto> <user> <days> [pass] [limit]
#   Retour : 0 OK, 1 nom invalide, 2 déjà existant, 3 échec système
create_user() {
    local proto="$1" user="$2" days="$3" pass="$4" limit="$5" quota="$6"
    valid_name "$user" || return 1
    _meta_exists "$user" && return 2
    local exp; exp=$(exp_in_days "$days")
    local uuid=""

    case "$proto" in
        ssh)
            id "$user" &>/dev/null && return 2
            useradd -M -s /usr/sbin/nologin -e "$exp" "$user" 2>/dev/null || return 3
            [[ -z "$pass" ]] && pass=$(gen_pass)
            echo "$user:$pass" | chpasswd 2>/dev/null || return 3
            write_meta "$user" ssh "$exp" "${limit:-1}" "$pass" "" "" "$quota"
            ;;
        vmess|vless)
            uuid=$(gen_uuid)
            xray_add_user "$proto" "$user" "$uuid" "$exp"
            write_meta "$user" "$proto" "$exp" "" "" "$uuid" "$quota"
            xray_reload
            ;;
        trojan)
            [[ -z "$pass" ]] && pass=$(gen_pass)
            xray_add_user trojan "$user" "$pass" "$exp"
            write_meta "$user" trojan "$exp" "" "$pass" "" "$quota"
            xray_reload
            ;;
        v2raydns)
            uuid=$(gen_uuid)
            write_meta "$user" v2raydns "$exp" "" "" "$uuid" "$quota"
            v2raydns_apply 2>/dev/null || true
            ;;
        zivpn)
            [[ -z "$pass" ]] && pass=$(gen_pass)
            write_meta "$user" zivpn "$exp" "" "$pass" "" "$quota"
            zivpn_apply 2>/dev/null || true
            ;;
        hysteria)
            [[ -z "$pass" ]] && pass=$(gen_pass)
            write_meta "$user" hysteria "$exp" "" "$pass" "" "$quota"
            hysteria_apply 2>/dev/null || true
            ;;
        *) return 1 ;;
    esac
    return 0
}

# ==============================================================================
#  SUPPRESSION / RENEW / LOCK / PASSWORD
# ==============================================================================
delete_user() {
    local user="$1" proto
    _meta_exists "$user" || return 2
    proto=$(_meta_get "$user" proto)
    case "$proto" in
        ssh) userdel -f "$user" 2>/dev/null || true ;;
        vmess|vless|trojan) xray_del_user "$user"; xray_reload ;;
        zivpn) rm -f "$USERDIR/$user"; zivpn_apply 2>/dev/null || true ;;
        hysteria) rm -f "$USERDIR/$user"; hysteria_apply 2>/dev/null || true ;;
        v2raydns) rm -f "$USERDIR/$user"; v2raydns_apply 2>/dev/null || true ;;
    esac
    rm -f "$USERDIR/$user"
    return 0
}

renew_user() {
    local user="$1" days="$2" proto exp
    _meta_exists "$user" || return 2
    proto=$(_meta_get "$user" proto)
    exp=$(exp_in_days "$days")
    # réécrit le champ exp en conservant les autres
    local limit pass uuid
    limit=$(_meta_get "$user" limit); pass=$(_meta_get "$user" pass); uuid=$(_meta_get "$user" uuid); quota=$(_meta_get "$user" quota)
    write_meta "$user" "$proto" "$exp" "$limit" "$pass" "$uuid" "$quota"
    [[ "$proto" == "ssh" ]] && chage -E "$exp" "$user" 2>/dev/null
    case "$proto" in
        vmess|vless|trojan) xray_del_user "$user"
            xray_add_user "$proto" "$user" "${uuid:-$pass}" "$exp"; xray_reload ;;
    esac
    return 0
}

# lock/unlock (SSH via passwd -l/-u ; autres via champ locked=)
lock_user() {
    local user="$1" proto; _meta_exists "$user" || return 2
    proto=$(_meta_get "$user" proto)
    if [[ "$proto" == "ssh" ]]; then passwd -l "$user" &>/dev/null; fi
    grep -q '^locked=' "$USERDIR/$user" 2>/dev/null || echo "locked=1" >> "$USERDIR/$user"
    return 0
}
unlock_user() {
    local user="$1" proto; _meta_exists "$user" || return 2
    proto=$(_meta_get "$user" proto)
    if [[ "$proto" == "ssh" ]]; then passwd -u "$user" &>/dev/null; fi
    sed -i '/^locked=/d' "$USERDIR/$user" 2>/dev/null
    return 0
}
is_locked() { grep -q '^locked=1' "$USERDIR/$1" 2>/dev/null; }

change_password() {
    local user="$1" newpass="$2" proto; _meta_exists "$user" || return 2
    proto=$(_meta_get "$user" proto)
    [[ -z "$newpass" ]] && newpass=$(gen_pass)
    case "$proto" in
        ssh) echo "$user:$newpass" | chpasswd 2>/dev/null || return 3 ;;
        trojan) xray_del_user "$user"
            xray_add_user trojan "$user" "$newpass" "$(_meta_get "$user" exp)"; xray_reload ;;
        zivpn) zivpn_apply 2>/dev/null || true ;;
        hysteria) hysteria_apply 2>/dev/null || true ;;
        *) : ;;  # vmess/vless utilisent un UUID, pas de mot de passe
    esac
    sed -i '/^pass=/d' "$USERDIR/$user" 2>/dev/null
    echo "pass=$newpass" >> "$USERDIR/$user"
    echo "$newpass"
    return 0
}

# supprime tous les comptes expirés (toutes familles) ; renvoie le nombre supprimé
delete_expired_users() {
    local today f u exp n=0
    today=$(date +%Y-%m-%d)
    [[ -d "$USERDIR" ]] || { echo 0; return; }
    for f in "$USERDIR"/*; do
        [[ -f "$f" ]] || continue
        exp=$(grep -oP '^exp=\K.*' "$f" 2>/dev/null)
        if [[ -n "$exp" && "$exp" < "$today" ]]; then
            u=$(basename "$f"); delete_user "$u" && (( n++ ))
        fi
    done
    echo "$n"
}

# ==============================================================================
#  LISTE DES UTILISATEURS D'UNE FAMILLE (tableau coloré aligné)
# ==============================================================================
# scr_list_users <titre-court> <proto...>
scr_list_users() {
    clear
    local short="$1"; shift
    local -a protos=("$@")
    local L=()
    push_header L simple " ${YELLOW}○${RESET} ${WHITE}MENU :${RESET} ${WHITE}${short} ▸ LIST USERS${RESET}"
    L+=(
        "$(printf " ${WHITE}%-18s %-12s %-14s %-8s${RESET}" "USERNAME" "PROTO" "EXPIRES" "STATUS")"
        "$(printf " ${GRAY}%-18s %-12s %-14s %-8s${RESET}" "────────" "─────" "───────" "──────")"
    )
    local today f u p e match x n=0
    today=$(date +%Y-%m-%d)
    if [[ -d "$USERDIR" ]]; then
        for f in "$USERDIR"/*; do
            [[ -f "$f" ]] || continue
            p=$(grep -oP '^proto=\K.*' "$f"); match=0
            for x in "${protos[@]}"; do [[ "$p" == "$x" ]] && match=1 && break; done
            (( match )) || continue
            u=$(basename "$f"); e=$(grep -oP '^exp=\K.*' "$f")
            local stat
            if is_locked "$u"; then stat="${RED}LOCKED${RESET}"
            elif [[ -n "$e" && "$e" < "$today" ]]; then stat="${RED}EXPIRED${RESET}"
            else stat="${GREEN}ACTIVE${RESET}"; fi
            L+=( "$(printf " ${GREEN}%-18s${RESET} ${WHITE}%-12s${RESET} %-14s %b" "$u" "$p" "$(exp_color "$e")" "$stat")" )
            (( n++ ))
        done
    fi
    (( n == 0 )) && L+=( " ${GRAY}(no ${short} user)${RESET}" )
    L+=( "%SEP%" )
    render_screen L
    press_enter
}

# ==============================================================================
#  AFFICHAGE CONNECTION INFO pour un user existant (route vers show_*_details)
# ==============================================================================
show_user_info() {
    local user="$1" proto exp pass uuid quota
    _meta_exists "$user" || { clear; echo; _msg_err "Utilisateur '$user' introuvable."; press_enter; return; }
    proto=$(_meta_get "$user" proto); exp=$(_meta_get "$user" exp)
    pass=$(_meta_get "$user" pass);   uuid=$(_meta_get "$user" uuid)
    quota=$(_meta_get "$user" quota); quota="${quota:-0}"
    case "$proto" in
        vless)   show_vless_details    details "$user" "$uuid" "$exp" "$quota" ;;
        trojan)  show_trojan_details   details "$user" "$pass" "$exp" "$quota" ;;
        vmess)   show_vmess_details    details "$user" "$uuid" "$exp" "$quota" ;;
        hysteria)show_hysteria_details details "$user" "$pass" "$exp" "$quota" ;;
        zivpn)   show_zivpn_details    details "$user" "$pass" "$exp" "$quota" ;;
        ssh)     show_ssh_details      details "$user" "$pass" "$exp" "$quota" ;;
        v2raydns)show_v2raydns_details details "$user" "$uuid" "$exp" "$quota" ;;
        *) clear; echo; _msg_err "Protocole inconnu pour '$user' ($proto)."; press_enter ;;
    esac
}

# ==============================================================================
#  PROMPTS INTERACTIFS (invites colorées + validation)
# ==============================================================================
_ask() { local p="$1" v; echo -ne " ${YELLOW}►${RESET} ${WHITE}${p}: ${RESET}" >&2; read -r v; echo "$v"; }
_ask_days() { local d; d=$(_ask "Duration in days (default 30)"); [[ "$d" =~ ^[0-9]+$ ]] || d=30; echo "$d"; }
_msg_ok()  { echo -e " ${GREEN}✔ $1${RESET}"; }
_msg_err() { echo -e " ${RED}✗ $1${RESET}"; }

# Wrapper interactif de création : ui_create <proto> [variant-for-xray]
ui_create() {
    local proto="$1"
    clear
    echo -e " ${YELLOW}○${RESET} ${WHITE}CREATE ${proto^^} USER${RESET}"; echo
    local user days pass="" limit="" quota=0
    user=$(_ask "Username")
    if ! valid_name "$user"; then _msg_err "Invalid username"; press_enter; return; fi
    if _meta_exists "$user"; then _msg_err "User already exists"; press_enter; return; fi
    days=$(_ask_days)
    [[ "$proto" == "ssh" || "$proto" == "trojan" || "$proto" == "zivpn" || "$proto" == "hysteria" ]] && {
        pass=$(_ask "Password (empty = auto)")
    }
    [[ "$proto" == "ssh" ]] && { limit=$(_ask "Connection limit (default 1)"); [[ "$limit" =~ ^[0-9]+$ ]] || limit=1; }
    {
        local q
        q=$(_ask "Data quota in GB (0 = unlimited, e.g. 10.5)")
        [[ "$q" =~ ^[0-9]+\.?[0-9]*$ ]] && quota="$q" || quota=0
    }

    create_user "$proto" "$user" "$days" "$pass" "$limit" "$quota"
    case $? in
        0) # succès → afficher l'écran de détails "created"
           local exp uuid p quota
           exp=$(_meta_get "$user" exp); uuid=$(_meta_get "$user" uuid); p=$(_meta_get "$user" pass)
           quota=$(_meta_get "$user" quota); quota="${quota:-0}"
           case "$proto" in
             vless)   show_vless_details    created "$user" "$uuid" "$exp" "$quota" ;;
             trojan)  show_trojan_details   created "$user" "$p" "$exp" "$quota" ;;
             vmess)   show_vmess_details    created "$user" "$uuid" "$exp" "$quota" ;;
             hysteria)show_hysteria_details created "$user" "$p" "$exp" "$quota" ;;
             zivpn)   show_zivpn_details    created "$user" "$p" "$exp" "$quota" ;;
             ssh)     show_ssh_details      created "$user" "$p" "$exp" "$quota" ;;
             v2raydns)show_v2raydns_details created "$user" "$uuid" "$exp" "$quota" ;;
           esac ;;
        1) _msg_err "Invalid username"; press_enter ;;
        2) _msg_err "User already exists"; press_enter ;;
        3) _msg_err "System error (useradd/chpasswd)"; press_enter ;;
    esac
}

ui_delete() {
    local fam="$1"; clear
    echo -e " ${YELLOW}○${RESET} ${WHITE}DELETE ${fam^^} USER${RESET}"; echo
    local user; user=$(_ask "Username to delete")
    if ! _meta_exists "$user"; then _msg_err "User not found"; press_enter; return; fi
    echo -ne " ${RED}Confirm deletion of '$user'? [y/N]: ${RESET}"; read -r c
    [[ "$c" =~ ^[yY]$ ]] || { echo; _msg_err "Cancelled"; press_enter; return; }
    delete_user "$user" && _msg_ok "User '$user' deleted." || _msg_err "Deletion failed."
    press_enter
}

ui_renew() {
    clear; echo -e " ${YELLOW}○${RESET} ${WHITE}RENEW / EXTEND USER${RESET}"; echo
    local user days; user=$(_ask "Username")
    _meta_exists "$user" || { _msg_err "User not found"; press_enter; return; }
    days=$(_ask_days)
    renew_user "$user" "$days" && _msg_ok "User '$user' extended to $(_meta_get "$user" exp)." || _msg_err "Renew failed."
    press_enter
}

ui_lock() {
    clear; echo -e " ${YELLOW}○${RESET} ${WHITE}LOCK / UNLOCK USER${RESET}"; echo
    local user; user=$(_ask "Username")
    _meta_exists "$user" || { _msg_err "User not found"; press_enter; return; }
    if is_locked "$user"; then
        unlock_user "$user" && _msg_ok "User '$user' unlocked."
    else
        lock_user "$user" && _msg_ok "User '$user' locked."
    fi
    press_enter
}

ui_passwd() {
    clear; echo -e " ${YELLOW}○${RESET} ${WHITE}CHANGE PASSWORD${RESET}"; echo
    local user np; user=$(_ask "Username")
    _meta_exists "$user" || { _msg_err "User not found"; press_enter; return; }
    np=$(_ask "New password (empty = auto)")
    np=$(change_password "$user" "$np") && _msg_ok "Password updated: $np" || _msg_err "Change failed."
    press_enter
}

ui_info() {
    clear; echo -e " ${YELLOW}○${RESET} ${WHITE}CONNECTION INFO${RESET}"; echo
    local user; user=$(_ask "Username")
    show_user_info "$user"
}

ui_delete_expired() {
    clear; echo -e " ${YELLOW}○${RESET} ${WHITE}DELETE EXPIRED USERS (BULK)${RESET}"; echo
    echo -ne " ${RED}Delete ALL expired users? [y/N]: ${RESET}"; read -r c
    [[ "$c" =~ ^[yY]$ ]] || { echo; _msg_err "Cancelled"; press_enter; return; }
    local n; n=$(delete_expired_users)
    _msg_ok "$n expired user(s) removed."
    press_enter
}


# ==============================================================================
#  TUNNEL INSTALLERS — nftables-only (aucun iptables)
#  Source de vérité unifiée : $USERDIR ; projection vers chaque backend via *_apply
# ==============================================================================

# --- shim log/warn/err/pause (réutilise la palette + press_enter du panneau) ---
if ! declare -F log  >/dev/null; then log()  { echo -e " ${GREEN}[✓]${RESET} $*"; }; fi
if ! declare -F warn >/dev/null; then warn() { echo -e " ${YELLOW}[!]${RESET} $*"; }; fi
if ! declare -F err  >/dev/null; then err()  { echo -e " ${RED}[✗]${RESET} $*"; }; fi
if ! declare -F pause >/dev/null; then pause() { [[ -n "${SKIP_PAUSE:-}" ]] && return 0; press_enter; }; fi

# --- constantes backends ---
ZIVPN_BIN="${ZIVPN_BIN:-/usr/local/bin/zivpn}";                 ZIVPN_SERVICE="${ZIVPN_SERVICE:-zivpn.service}"
ZIVPN_CONFIG="${ZIVPN_CONFIG:-/etc/zivpn/config.json}"
HY_BIN="${HY_BIN:-/usr/local/bin/hysteria-linux-amd64}";        HY_SERVICE="${HY_SERVICE:-hysteria.service}"
HY_CONFIG="${HY_CONFIG:-/etc/hysteria/config.json}"
XRAY_BIN="${XRAY_BIN:-/usr/local/bin/xray}";                    XRAY_CONFIG="${XRAY_CONFIG:-/etc/xray/config.json}"
XRAY_DOMAIN="${XRAY_DOMAIN:-/etc/xray/domain}";                 XRAY_LOG="${XRAY_LOG:-/var/log/xray}"
V2RAY_BIN="${V2RAY_BIN:-/usr/local/bin/v2ray}";                 V2RAY_CONFIG="${V2RAY_CONFIG:-/etc/v2ray/config.json}"

# ------------------------------------------------------------------------------
#  NFTABLES — service template + tables dédiées (policy accept : ouvre, sans deny)
# ------------------------------------------------------------------------------
setup_nftables_base() {
    systemctl enable --now nftables 2>/dev/null || true
    mkdir -p /etc/nftables
    cat > /etc/systemd/system/nftables-tunnel@.service << 'UNIT'
[Unit]
Description=nftables tunnel %i
Before=nftables.service
PartOf=nftables.service
ReloadPropagatedFrom=nftables.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f /etc/nftables/%i.nft
ExecStop=/usr/sbin/nft delete table inet %i
[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload 2>/dev/null || true
    # table de base kighmu (jamais de policy drop)
    if ! nft list table inet kighmu 2>/dev/null | grep -q .; then
        nft add table inet kighmu 2>/dev/null || true
        nft 'add chain inet kighmu input   { type filter hook input priority 0; policy accept; }' 2>/dev/null || true
        nft 'add chain inet kighmu output  { type filter hook output priority 0; policy accept; }' 2>/dev/null || true
        nft 'add chain inet kighmu forward { type filter hook forward priority 0; policy accept; }' 2>/dev/null || true
    fi
}

deploy_nft_tunnel() {
    local name="$1" nft_src="$2"
    [[ -f /etc/systemd/system/nftables-tunnel@.service ]] || setup_nftables_base
    mkdir -p /etc/nftables; echo "$nft_src" > "/etc/nftables/${name}.nft"
    if nft -c -f "/etc/nftables/${name}.nft" 2>/dev/null; then
        systemctl enable --now "nftables-tunnel@${name}.service" 2>/dev/null || true
        systemctl restart "nftables-tunnel@${name}.service" 2>/dev/null || true
        log "nftables $name chargée"
    else err "nftables $name invalide"; rm -f "/etc/nftables/${name}.nft"; fi
}

remove_nft_tunnel() {
    local name="$1"
    systemctl disable --now "nftables-tunnel@${name}.service" 2>/dev/null || true
    rm -f "/etc/nftables/${name}.nft"; nft delete table inet "$name" 2>/dev/null || true
    systemctl daemon-reload 2>/dev/null || true
}

# ------------------------------------------------------------------------------
#  OPTIMISATIONS RÉSEAU (BBR + buffers 67 Mo + FQ) — requis par les tunnels UDP
# ------------------------------------------------------------------------------
apply_network_optimizations() {
    modprobe tcp_bbr 2>/dev/null || true; modprobe sch_fq 2>/dev/null || true
    local KEYS=(
        net.core.rmem_default net.core.wmem_default net.core.rmem_max net.core.wmem_max
        net.core.netdev_max_backlog net.core.optmem_max net.core.default_qdisc
        net.ipv4.tcp_congestion_control net.ipv4.ip_forward net.ipv4.udp_mem
        fs.file-max net.ipv4.tcp_fastopen net.ipv4.tcp_mtu_probing
    )
    for KEY in "${KEYS[@]}"; do sed -i "/^${KEY}=/d" /etc/sysctl.conf 2>/dev/null || true; done
    cat >> /etc/sysctl.conf << 'SYSEOF'

# === Kighmu High-Speed ===
net.core.rmem_default=26214400
net.core.wmem_default=26214400
net.core.rmem_max=67108864
net.core.wmem_max=67108864
net.core.optmem_max=25165824
fs.file-max=1000000
net.core.netdev_max_backlog=250000
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr
net.ipv4.ip_forward=1
net.ipv4.udp_mem=102400 873800 16777216
net.ipv4.tcp_fastopen=3
net.ipv4.tcp_mtu_probing=1
SYSEOF
    sysctl -p >/dev/null 2>&1 || true
    local IFACE; IFACE=$(ip route show default 2>/dev/null | awk '/default/ {print $5}' | head -1)
    [[ -n "$IFACE" ]] && { tc qdisc del dev "$IFACE" root 2>/dev/null || true; tc qdisc add dev "$IFACE" root fq 2>/dev/null || true; }
    log "Optimisations réseau: BBR + buffers 67 Mo + FQ"
}

# ==============================================================================
#  PROJECTIONS BACKEND (USERDIR → config native)  — appelées par create/delete
# ==============================================================================
# liste les mots de passe actifs (non expirés, non verrouillés) d'un proto
_active_passwords() {
    local today f p exp; today=$(date +%Y-%m-%d)
    [[ -d "$USERDIR" ]] || return 0
    for f in "$USERDIR"/*; do
        [[ -f "$f" ]] || continue
        [[ "$(grep -oP '^proto=\K.*' "$f" 2>/dev/null)" == "$1" ]] || continue
        exp=$(grep -oP '^exp=\K.*' "$f" 2>/dev/null); [[ -n "$exp" && "$exp" < "$today" ]] && continue
        grep -q '^locked=1' "$f" 2>/dev/null && continue
        p=$(grep -oP '^pass=\K.*' "$f" 2>/dev/null); [[ -n "$p" ]] && echo "$p"
    done
}

_json_reload_passwords() {   # $1=config $2=service — .auth.config=[passwords]
    local cfg="$1" svc="$2" pw tmp
    [[ -f "$cfg" ]] || return 0
    pw=$(_active_passwords "${3:-}" | sort -u | paste -sd, -); [[ -z "$pw" ]] && pw="zi"
    tmp=$(mktemp)
    if jq --arg pw "$pw" '.auth.config = ($pw | split(","))' "$cfg" > "$tmp" 2>/dev/null && jq empty "$tmp" >/dev/null 2>&1; then
        mv "$tmp" "$cfg"; systemctl restart "$svc" 2>/dev/null || true
    else rm -f "$tmp"; fi
}

zivpn_apply()    { _json_reload_passwords "$ZIVPN_CONFIG" "$ZIVPN_SERVICE" zivpn; }
hysteria_apply() { _json_reload_passwords "$HY_CONFIG"    "$HY_SERVICE"    hysteria; }

# v2ray-dns : projette les uuid v2raydns actifs dans /etc/v2ray/config.json
v2raydns_apply() {
    [[ -f "$V2RAY_CONFIG" ]] || return 0
    local today f uuid exp clients tmp; today=$(date +%Y-%m-%d); clients="[]"
    for f in "$USERDIR"/*; do
        [[ -f "$f" ]] || continue
        [[ "$(grep -oP '^proto=\K.*' "$f" 2>/dev/null)" == "v2raydns" ]] || continue
        exp=$(grep -oP '^exp=\K.*' "$f" 2>/dev/null); [[ -n "$exp" && "$exp" < "$today" ]] && continue
        grep -q '^locked=1' "$f" 2>/dev/null && continue
        uuid=$(grep -oP '^uuid=\K.*' "$f" 2>/dev/null); [[ -z "$uuid" ]] && continue
        clients=$(echo "$clients" | jq --arg id "$uuid" --arg em "$(basename "$f")" '. += [{"id":$id,"email":$em,"level":0}]' 2>/dev/null)
    done
    tmp=$(mktemp)
    if jq --argjson c "$clients" '.inbounds[0].settings.clients = $c' "$V2RAY_CONFIG" > "$tmp" 2>/dev/null && jq empty "$tmp" >/dev/null 2>&1; then
        mv "$tmp" "$V2RAY_CONFIG"; systemctl restart v2ray 2>/dev/null || true
    else rm -f "$tmp"; fi
}

# ==============================================================================
#  SSH / DROPBEAR / SSL-TLS / SSH-WS
# ==============================================================================
install_openssh() {
    echo -e " ${CYAN}━━━ OpenSSH ━━━${RESET}"
    apt-get install -y -qq openssh-server 2>/dev/null || true
    systemctl enable ssh 2>/dev/null || true; systemctl restart ssh 2>/dev/null || true
    sed -i 's/^#PermitTunnel.*/PermitTunnel yes/' /etc/ssh/sshd_config 2>/dev/null || echo "PermitTunnel yes" >> /etc/ssh/sshd_config
    sed -i 's/^#AllowTcpForwarding.*/AllowTcpForwarding yes/' /etc/ssh/sshd_config 2>/dev/null || echo "AllowTcpForwarding yes" >> /etc/ssh/sshd_config
    systemctl restart ssh 2>/dev/null || true
    log "OpenSSH actif (port 22)"; pause
}

install_dropbear() {
    echo -e " ${CYAN}━━━ Dropbear (port 109) ━━━${RESET}"
    if ! command -v /usr/local/sbin/dropbear &>/dev/null; then
        apt-get install -y -qq build-essential bzip2 zlib1g-dev wget tar 2>/dev/null
        cd /usr/local/src
        wget -q "https://matt.ucc.asn.au/dropbear/releases/dropbear-2022.83.tar.bz2" -O dropbear-2022.83.tar.bz2 2>/dev/null || { err "Téléchargement échoué"; pause; return; }
        tar -xjf dropbear-2022.83.tar.bz2 2>/dev/null; cd dropbear-2022.83
        ./configure --prefix=/usr/local >/dev/null 2>&1; make -j"$(nproc)" >/dev/null 2>&1; make install >/dev/null 2>&1
        local DIR="/etc/dropbear"; mkdir -p "$DIR"
        for key in rsa ecdsa ed25519; do /usr/local/bin/dropbearkey -t "$key" -f "$DIR/dropbear_${key}_host_key" >/dev/null 2>&1 || true; done
        chmod 600 "$DIR"/*_host_key 2>/dev/null || true
        echo "Bienvenue sur Kighmu - Connexion autorisée" > "$DIR/banner.txt"
    fi
    cat > /etc/systemd/system/dropbear-custom.service << 'UNIT'
[Unit]
Description=Dropbear Custom (port 109)
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
ExecStart=/usr/local/sbin/dropbear -F -E -p 109 -w -g -b /etc/dropbear/banner.txt -R
Restart=always
RestartSec=2
StartLimitIntervalSec=0
StartLimitBurst=0
User=root
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload && systemctl enable --now dropbear-custom.service 2>/dev/null || true
    deploy_nft_tunnel dropbear 'table inet dropbear { chain input { type filter hook input priority 0; policy accept; tcp dport 109 accept; }; }'
    log "Dropbear actif (port 109)"; pause
}

uninstall_dropbear() {
    systemctl disable --now dropbear-custom.service 2>/dev/null || true
    rm -f /etc/systemd/system/dropbear-custom.service; rm -rf /etc/dropbear
    rm -f /usr/local/sbin/dropbear /usr/local/bin/dropbear*
    remove_nft_tunnel dropbear; systemctl daemon-reload; log "Dropbear supprimé"; pause
}

install_ssl_tls() {
    echo -e " ${CYAN}━━━ SSL/TLS Tunnel (port 444 → 109) ━━━${RESET}"
    if ! command -v ssl_tls &>/dev/null; then
        apt-get install -y -qq curl file 2>/dev/null
        local url="https://github.com/kinf744/Kighmu/releases/download/v1.0.0/ssl_tls" tmp; tmp=$(mktemp -d)
        pushd "$tmp" >/dev/null || return 1
        curl -fsSL "$url" -o ssl_tls 2>/dev/null && chmod +x ssl_tls && file ssl_tls | grep -q ELF && install -m 0755 ssl_tls /usr/local/bin/ssl_tls
        popd >/dev/null 2>&1 || true; rm -rf "$tmp"
    fi
    cat > /etc/systemd/system/ssl_tls.service << 'UNIT'
[Unit]
Description=Tunnel SSL/TLS (ssl_tls)
After=network.target
Wants=network.target
[Service]
Type=simple
ExecStart=/usr/local/bin/ssl_tls -listen 444 -target-host 127.0.0.1 -target-port 109
Restart=always
RestartSec=2
StartLimitIntervalSec=0
StartLimitBurst=0
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload && systemctl enable --now ssl_tls.service 2>/dev/null || true
    deploy_nft_tunnel ssl_tls 'table inet ssl_tls { chain input { type filter hook input priority 0; policy accept; tcp dport 444 accept; }; chain output { type filter hook output priority 0; policy accept; tcp sport 444 accept; }; }'
    log "SSL/TLS actif (port 444 → 109)"; pause
}

uninstall_ssl_tls() {
    systemctl disable --now ssl_tls.service 2>/dev/null || true; rm -f /etc/systemd/system/ssl_tls.service
    rm -f /usr/local/bin/ssl_tls; remove_nft_tunnel ssl_tls; systemctl daemon-reload; log "ssl_tls supprimé"; pause
}

install_sshws() {
    echo -e " ${CYAN}━━━ SSH WS (port 80 → 109) ━━━${RESET}"
    if ! command -v sshws &>/dev/null; then
        apt-get install -y -qq curl 2>/dev/null
        local url="https://github.com/kinf744/Kighmu/releases/download/v1.0.0" tmp; tmp=$(mktemp -d)
        pushd "$tmp" >/dev/null || return 1
        curl -LO "$url/sshws" 2>/dev/null && chmod +x sshws && install -m 0755 sshws /usr/local/bin/sshws
        popd >/dev/null 2>&1 || true; rm -rf "$tmp"
    fi
    cat > /etc/systemd/system/sshws.service << 'UNIT'
[Unit]
Description=SSHWS Slipstream Tunnel
After=network.target
[Service]
Type=simple
ExecStart=/usr/local/bin/sshws -listen 80 -target-host 127.0.0.1 -target-port 109
Restart=always
RestartSec=2
StartLimitIntervalSec=0
StartLimitBurst=0
User=root
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload && systemctl enable --now sshws.service 2>/dev/null || true
    deploy_nft_tunnel sshws 'table inet sshws { chain input { type filter hook input priority 0; policy accept; tcp dport 80 accept; }; }'
    log "SSH WS actif (port 80 → 109)"; pause
}

uninstall_sshws() {
    systemctl disable --now sshws.service 2>/dev/null || true; rm -f /etc/systemd/system/sshws.service
    rm -f /usr/local/bin/sshws; remove_nft_tunnel sshws; systemctl daemon-reload; log "sshws supprimé"; pause
}

# ==============================================================================
#  SLOWDNS (dnstt + routeur Go interne) — 53 → 5353 (SSH) / 5354 (V2Ray)
# ==============================================================================
install_slowdns() {
    echo -e " ${CYAN}━━━ SlowDNS (53→5353/5354) ━━━${RESET}"
    command -v dnstt-server &>/dev/null && { warn "SlowDNS déjà installé"; pause; return; }
    apt-get install -y -qq curl jq wget golang-go 2>/dev/null
    local DIR="/etc/slowdns"; mkdir -p "$DIR/ns4" "$DIR/nv4" /var/log/slowdns /root/Kighmu/slowdns-router
    local DNSTT_PRIV="4ab3af05fc004cb69d50c89de2cd5d138be1c397a55788b8867088e801f7fcaa"
    local DNSTT_PUB="2cb39d63928451bd67f5954ffa5ac16c8d903562a10c4b21756de4f1a82d581c"
    printf '%s\n' "$DNSTT_PRIV" > "$DIR/server.key"; printf '%s\n' "$DNSTT_PUB" > "$DIR/server.pub"
    chmod 600 "$DIR/server.key"; chmod 644 "$DIR/server.pub"
    local tmp; tmp=$(mktemp)
    curl -fsSL "https://dnstt-server-client.s3.amazonaws.com/dnstt-server-linux-amd64" -o "$tmp" 2>/dev/null
    mv "$tmp" /usr/local/bin/dnstt-server; chmod +x /usr/local/bin/dnstt-server

    local NS4 NV4
    NS4=$(head -1 "$DIR/ns.conf" 2>/dev/null || echo ""); [[ "$NS4" == *"."* ]] || NS4=""
    NV4=$(head -1 "$DIR/nv4/ns.conf" 2>/dev/null || echo ""); [[ "$NV4" == *"."* ]] || NV4=""
    if [[ -z "$NS4" ]]; then read -rp " NS4 (ex: ns4.votre-domaine.com): " NS4; NS4=${NS4:-ns4.kighmu.local}; fi
    if [[ -z "$NV4" ]]; then read -rp " NV4 (ex: nv4.votre-domaine.com): " NV4; NV4=${NV4:-nv4.kighmu.local}; fi
    echo "$NS4" > "$DIR/ns.conf"; echo "$NV4" > "$DIR/nv4/ns.conf"
    printf 'MODE=man\nNS4=%s\nNV4=%s\n' "$NS4" "$NV4" > "$DIR/install.env"

    cat > /usr/local/bin/slowdns-ns4-start.sh << STARTEOF
#!/bin/bash
NS=\$(cat $DIR/ns.conf)
exec /usr/local/bin/dnstt-server -udp 0.0.0.0:5353 -privkey-file $DIR/server.key \$NS 127.0.0.1:109
STARTEOF
    cat > /usr/local/bin/slowdns-nv4-start.sh << STARTEOF
#!/bin/bash
NV4=\$(cat $DIR/nv4/ns.conf)
exec /usr/local/bin/dnstt-server -udp 0.0.0.0:5354 -privkey-file $DIR/server.key \$NV4 127.0.0.1:5401
STARTEOF
    chmod +x /usr/local/bin/slowdns-ns4-start.sh /usr/local/bin/slowdns-nv4-start.sh

    for svc in slowdns-ns4 slowdns-nv4; do
        cat > "/etc/systemd/system/${svc}.service" << UNIT
[Unit]
Description=SlowDNS $svc
After=network-online.target
Wants=network-online.target
[Service]
Type=simple
ExecStartPre=/bin/sleep 5
ExecStart=/usr/local/bin/${svc}-start.sh
Restart=always
RestartSec=5
StartLimitIntervalSec=0
StartLimitBurst=0
LimitNOFILE=1048576
StandardOutput=append:/var/log/slowdns/${svc}.log
StandardError=append:/var/log/slowdns/${svc}.log
[Install]
WantedBy=multi-user.target
UNIT
        systemctl daemon-reload && systemctl enable --now "${svc}.service" 2>/dev/null || true
    done

    cat > /root/Kighmu/slowdns-router/main.go << 'GOEOF'
package main

import (
	"fmt"
	"log"
	"net"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"
	"time"
)

type route struct {
	domain string
	addr   *net.UDPAddr
}

type stats struct {
	mu      sync.Mutex
	total   int64
	routed  map[string]int64
	refused int64
	errors  int64
}

func getEnv(key, fallback string) string {
	if v := os.Getenv(key); v != "" { return v }
	return fallback
}

func getEnvInt(key string, fallback int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := fmt.Sscanf(v, "%d", &fallback); n == 1 && err == nil { return fallback }
	}
	return fallback
}

func main() {
	listen := getEnv("LISTEN", "0.0.0.0:53")
	timeout := time.Duration(getEnvInt("TIMEOUT", 5)) * time.Second
	verbose := os.Getenv("VERBOSE") == "1"
	routesDef := getEnv("ROUTES", "")
	if routesDef == "" { log.Fatal("ROUTES required") }

	var routes []route
	for _, part := range strings.Split(routesDef, ",") {
		part = strings.TrimSpace(part)
		if part == "" { continue }
		eq := strings.IndexByte(part, '=')
		if eq < 1 { log.Fatalf("invalid route %q", part) }
		domain := strings.ToLower(strings.TrimSuffix(part[:eq], "."))
		addr, err := net.ResolveUDPAddr("udp4", part[eq+1:])
		if err != nil { log.Fatalf("resolve: %v", err) }
		routes = append(routes, route{domain: domain, addr: addr})
	}

	var st stats; st.routed = make(map[string]int64)
	laddr, _ := net.ResolveUDPAddr("udp4", listen)
	conn, err := net.ListenUDP("udp4", laddr)
	if err != nil { log.Fatalf("listen: %v", err) }
	defer conn.Close()

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM, syscall.SIGUSR1)
	go func() {
		for sig := range sigCh {
			if sig == syscall.SIGUSR1 { printStats(&st) } else { conn.Close(); return }
		}
	}()

	log.Printf("slowdns-router on %s", listen)
	for _, r := range routes { log.Printf("  %s -> %s", r.domain, r.addr) }

	buf := make([]byte, 4096)
	for {
		n, clientAddr, err := conn.ReadFromUDP(buf)
		if err != nil { break }
		st.mu.Lock(); st.total++; st.mu.Unlock()
		packet := make([]byte, n); copy(packet, buf[:n])
		go handle(conn, clientAddr, packet, routes, timeout, verbose, &st)
	}
	printStats(&st)
}

func handle(conn *net.UDPConn, clientAddr *net.UDPAddr, packet []byte, routes []route, timeout time.Duration, verbose bool, st *stats) {
	qname, err := extractQName(packet)
	if err != nil { return }
	qname = strings.ToLower(qname)
	if !strings.HasSuffix(qname, ".") { qname += "." }

	for _, r := range routes {
		if strings.HasSuffix(qname, r.domain+".") {
			resp, err := forward(packet, r.addr, timeout)
			if err != nil {
				st.mu.Lock(); st.errors++; st.mu.Unlock()
				sendRefused(conn, clientAddr, packet)
				return
			}
			st.mu.Lock(); st.routed[r.domain]++; st.mu.Unlock()
			conn.WriteToUDP(resp, clientAddr)
			return
		}
	}
	st.mu.Lock(); st.refused++; st.mu.Unlock()
	sendRefused(conn, clientAddr, packet)
}

func extractQName(packet []byte) (string, error) {
	if len(packet) < 12 { return "", fmt.Errorf("too short") }
	var labels []string; pos := 12
	for {
		if pos >= len(packet) { return "", fmt.Errorf("truncated") }
		length := int(packet[pos])
		if length == 0 { pos++; break }
		if length&0xC0 != 0 { return "", fmt.Errorf("compressed") }
		pos++
		if pos+length > len(packet) { return "", fmt.Errorf("overflow") }
		labels = append(labels, string(packet[pos:pos+length]))
		pos += length
	}
	return strings.Join(labels, "."), nil
}

func forward(packet []byte, backend *net.UDPAddr, timeout time.Duration) ([]byte, error) {
	bc, err := net.DialUDP("udp4", nil, backend)
	if err != nil { return nil, err }
	defer bc.Close()
	bc.SetDeadline(time.Now().Add(timeout))
	if _, err := bc.Write(packet); err != nil { return nil, err }
	resp := make([]byte, 4096)
	n, err := bc.Read(resp)
	if err != nil { return nil, err }
	out := make([]byte, n); copy(out, resp[:n])
	return out, nil
}

func sendRefused(conn *net.UDPConn, clientAddr *net.UDPAddr, req []byte) {
	if len(req) < 12 { return }
	resp := make([]byte, len(req)); copy(resp, req)
	resp[2] = (req[2] & 0x01) | 0x80
	resp[3] = 0x85; resp[6] = 0; resp[7] = 0
	resp[8] = 0; resp[9] = 0; resp[10] = 0; resp[11] = 0
	conn.WriteToUDP(resp, clientAddr)
}

func printStats(st *stats) {
	st.mu.Lock(); defer st.mu.Unlock()
	fmt.Fprintf(os.Stderr, "\n--- stats ---\ntotal: %d\n", st.total)
	for d, c := range st.routed { fmt.Fprintf(os.Stderr, "  %s: %d\n", d, c) }
	fmt.Fprintf(os.Stderr, "refused: %d\nerrors: %d\n------------\n", st.refused, st.errors)
}
GOEOF

    ( cd /root/Kighmu/slowdns-router && go mod init slowdns-router 2>/dev/null && go build -o slowdns-router . 2>/dev/null && cp slowdns-router /usr/local/bin/slowdns-router 2>/dev/null ) || true

    cat > /etc/systemd/system/slowdns-router.service << UNIT
[Unit]
Description=SlowDNS Go Router
After=network-online.target slowdns-ns4.service slowdns-nv4.service
Wants=network-online.target
StartLimitIntervalSec=0
[Service]
Type=simple
Environment=LISTEN=0.0.0.0:53
Environment=ROUTES=$NS4=127.0.0.1:5353,$NV4=127.0.0.1:5354
Environment=TIMEOUT=5
ExecStart=/usr/local/bin/slowdns-router
Restart=always
RestartSec=3
LimitNOFILE=1048576
KillMode=mixed
[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload && systemctl enable --now slowdns-router.service 2>/dev/null || true

    deploy_nft_tunnel slowdns 'table inet slowdns { chain prerouting { type nat hook prerouting priority -100; }; chain input { type filter hook input priority 0; policy accept; udp dport 53 accept; udp dport 5353 accept; udp dport 5354 accept; tcp dport 109 accept; tcp dport 5401 accept; }; }'
    chattr -i /etc/resolv.conf 2>/dev/null || true
    printf 'nameserver 1.1.1.1\nnameserver 8.8.8.8\n' > /etc/resolv.conf
    chattr +i /etc/resolv.conf 2>/dev/null || true
    log "SlowDNS actif  —  NS4: $NS4 → SSH(109) | NV4: $NV4 → V2Ray(5401)"; pause
}

uninstall_slowdns() {
    for svc in slowdns-ns4 slowdns-nv4 slowdns-router; do systemctl disable --now "$svc" 2>/dev/null || true; done
    rm -f /etc/systemd/system/slowdns-ns4.service /etc/systemd/system/slowdns-nv4.service /etc/systemd/system/slowdns-router.service
    rm -f /usr/local/bin/dnstt-server /usr/local/bin/slowdns-router /usr/local/bin/slowdns-ns4-start.sh /usr/local/bin/slowdns-nv4-start.sh
    rm -rf /etc/slowdns /var/log/slowdns /root/Kighmu/slowdns-router
    systemctl daemon-reload; remove_nft_tunnel slowdns
    chattr -i /etc/resolv.conf 2>/dev/null || true
    log "SlowDNS supprimé"; pause
}

# ==============================================================================
#  BADVPN + UDP CUSTOM
# ==============================================================================
install_badvpn() {
    echo -e " ${CYAN}━━━ BadVPN (udpgw 7100/7200/7300) ━━━${RESET}"
    if ! command -v badvpn-udpgw &>/dev/null; then
        apt-get install -y -qq cmake build-essential git 2>/dev/null
        cd /tmp; rm -rf badvpn
        git clone --depth 1 https://github.com/ambrop72/badvpn.git 2>/dev/null
        cd badvpn; mkdir -p build; cd build
        cmake .. -DBUILD_NOTHING_BY_DEFAULT=1 -DBUILD_UDPGW=1 >/dev/null 2>&1
        make -j"$(nproc)" >/dev/null 2>&1; cp udpgw/badvpn-udpgw /usr/local/bin/; chmod +x /usr/local/bin/badvpn-udpgw
    fi
    for port in 7100 7200 7300; do
        cat > "/etc/systemd/system/badvpn@${port}.service" << UNIT
[Unit]
Description=BadVPN UDPGW $port
After=network.target
[Service]
Type=simple
ExecStart=/usr/local/bin/badvpn-udpgw --listen-addr 127.0.0.1:$port --max-clients 2048
Restart=always
RestartSec=2
StartLimitIntervalSec=0
StartLimitBurst=0
User=root
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
UNIT
        systemctl enable --now "badvpn@${port}.service" 2>/dev/null || true
    done
    deploy_nft_tunnel badvpn 'table inet badvpn { chain input { type filter hook input priority 0; policy accept; tcp dport { 7100,7200,7300 } accept; }; }'
    log "BadVPN actif (ports 7100/7200/7300)"; pause
}

uninstall_badvpn() {
    for port in 7100 7200 7300; do systemctl disable --now "badvpn@${port}.service" 2>/dev/null || true; rm -f "/etc/systemd/system/badvpn@${port}.service"; done
    rm -f /usr/local/bin/badvpn-udpgw; remove_nft_tunnel badvpn; log "BadVPN supprimé"; pause
}

install_udp_custom() {
    echo -e " ${CYAN}━━━ UDP Custom (port 36712) ━━━${RESET}"
    if ! command -v udp-custom &>/dev/null; then
        apt-get install -y -qq wget jq 2>/dev/null
        wget -q "https://github.com/kinf744/Kighmu/releases/download/v1.0.0/udp-custom" -O /usr/local/bin/udp-custom
        chmod +x /usr/local/bin/udp-custom
    fi
    mkdir -p /etc/udp-custom
    cat > /etc/udp-custom/config.json << 'EOF'
{"listen":":36712","auth":{"mode":"passwords","config":["zi"]},"exclude_port":[53,5300,4466,5667,20000]}
EOF
    cat > /etc/systemd/system/udp-custom.service << 'UNIT'
[Unit]
Description=UDP Custom Server
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0
[Service]
Type=simple
ExecStart=/usr/local/bin/udp-custom server -c /etc/udp-custom/config.json --exclude "53,5300,5353,5354,5667,6000-50000"
WorkingDirectory=/etc/udp-custom
Restart=always
RestartSec=10
AmbientCapabilities=CAP_NET_BIND_SERVICE CAP_NET_RAW
LimitNOFILE=1048576
StandardOutput=append:/var/log/udp-custom.log
StandardError=append:/var/log/udp-custom.log
[Install]
WantedBy=multi-user.target
UNIT
    systemctl daemon-reload 2>/dev/null || true
    systemctl enable --now udp-custom 2>/dev/null || true
    deploy_nft_tunnel udp-custom 'table inet udp-custom { chain input { type filter hook input priority 0; policy accept; udp dport 36712 accept; }; chain prerouting { type nat hook prerouting priority -100; udp dport != { 53, 5300, 5353, 5354, 5667, 6000-50000 } dnat to :36712; }; }'
    log "UDP Custom actif (port 36712)"; pause
}

uninstall_udp_custom() {
    systemctl disable --now udp-custom 2>/dev/null || true; rm -f /etc/systemd/system/udp-custom.service
    rm -f /usr/local/bin/udp-custom; rm -rf /etc/udp-custom
    remove_nft_tunnel udp-custom; log "UDP Custom supprimé"; pause
}

# ==============================================================================
#  ZIVPN
# ==============================================================================
install_zivpn() {
    echo -e " ${CYAN}━━━ ZIVPN ━━━${RESET}"
    systemctl stop zivpn 2>/dev/null || true
    apt-get install -y -qq wget curl jq openssl iproute2 2>/dev/null
    if [[ ! -x "$ZIVPN_BIN" ]]; then
        wget -q "https://github.com/kinf744/Kighmu/releases/download/v1.0.0/udp-zivpn-linux-amd64" -O "$ZIVPN_BIN"; chmod +x "$ZIVPN_BIN"
    fi
    mkdir -p /etc/zivpn
    local DOMAIN; if [[ -n "${SKIP_PAUSE:-}" ]]; then DOMAIN="zivpn.local"; else read -rp " Domaine ZIVPN [zivpn.local]: " DOMAIN; DOMAIN=${DOMAIN:-zivpn.local}; fi
    echo "$DOMAIN" > /etc/zivpn/domain.txt
    openssl req -x509 -newkey rsa:2048 -keyout /etc/zivpn/zivpn.key -out /etc/zivpn/zivpn.crt -nodes -days 3650 -subj "/CN=$DOMAIN" 2>/dev/null
    chmod 600 /etc/zivpn/zivpn.key; chmod 644 /etc/zivpn/zivpn.crt
    cat > "$ZIVPN_CONFIG" << 'EOF'
{"listen":":5667","cert":"/etc/zivpn/zivpn.crt","key":"/etc/zivpn/zivpn.key","obfs":"zivpn","recv_window_conn":15728640,"recv_window_client":67108864,"disable_mtu_discovery":false,"max_conn_client":4096,"exclude_port":[53,5300,4466,36712,20000],"auth":{"mode":"passwords","config":["zi"]}}
EOF
    cat > "/etc/systemd/system/$ZIVPN_SERVICE" << SVCEOF
[Unit]
Description=ZIVPN UDP Server (High-Speed)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0
[Service]
Type=simple
ExecStart=$ZIVPN_BIN server -c $ZIVPN_CONFIG
WorkingDirectory=/etc/zivpn
Restart=always
RestartSec=10
StartLimitBurst=0
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW
LimitNOFILE=1048576
LimitNPROC=infinity
LimitMEMLOCK=infinity
StandardOutput=append:/var/log/zivpn.log
StandardError=append:/var/log/zivpn.log
[Install]
WantedBy=multi-user.target
SVCEOF
    systemctl daemon-reload && systemctl enable "$ZIVPN_SERVICE" 2>/dev/null || true
    deploy_nft_tunnel zivpn 'table inet zivpn { chain input { type filter hook input priority 0; policy accept; udp dport 5667 accept; udp dport 6000-19999 accept; }; chain prerouting { type nat hook prerouting priority -100; udp dport 6000-19999 dnat to :5667; }; }'
    apply_network_optimizations
    zivpn_apply
    systemctl start "$ZIVPN_SERVICE" 2>/dev/null || true; sleep 2
    systemctl is-active --quiet "$ZIVPN_SERVICE" && log "ZIVPN actif ($(get_ip):6000-19999 → 5667)" || err "ZIVPN ne démarre pas"
    pause
}

uninstall_zivpn() {
    systemctl stop "$ZIVPN_SERVICE" 2>/dev/null || true; systemctl disable "$ZIVPN_SERVICE" 2>/dev/null || true
    rm -f "/etc/systemd/system/$ZIVPN_SERVICE" "$ZIVPN_BIN"; rm -rf /etc/zivpn
    remove_nft_tunnel zivpn; log "ZIVPN supprimé"; pause
}

# ==============================================================================
#  HYSTERIA v1.3.4
# ==============================================================================
install_hysteria() {
    echo -e " ${CYAN}━━━ Hysteria v1.3.4 ━━━${RESET}"
    systemctl stop hysteria 2>/dev/null || true
    apt-get install -y -qq wget curl jq openssl iproute2 2>/dev/null
    if [[ ! -x "$HY_BIN" ]]; then
        wget -q "https://github.com/apernet/hysteria/releases/download/v1.3.4/hysteria-linux-amd64" -O "$HY_BIN"; chmod +x "$HY_BIN"
    fi
    mkdir -p /etc/hysteria
    local DOMAIN; if [[ -n "${SKIP_PAUSE:-}" ]]; then DOMAIN="hysteria.local"; else read -rp " Domaine Hysteria [hysteria.local]: " DOMAIN; DOMAIN=${DOMAIN:-hysteria.local}; fi
    echo "$DOMAIN" > /etc/hysteria/domain.txt
    openssl req -x509 -newkey rsa:2048 -keyout /etc/hysteria/hysteria.key -out /etc/hysteria/hysteria.crt -nodes -days 3650 -subj "/CN=$DOMAIN" 2>/dev/null
    chmod 600 /etc/hysteria/hysteria.key; chmod 644 /etc/hysteria/hysteria.crt
    cat > "$HY_CONFIG" << 'EOF'
{"listen":":20000","cert":"/etc/hysteria/hysteria.crt","key":"/etc/hysteria/hysteria.key","obfs":"hysteria","up_mbps":150,"down_mbps":150,"recv_window_conn":33554432,"recv_window_client":67108864,"disable_mtu_discovery":false,"max_conn_client":4096,"exclude_port":[53,5300,4466,36712,5667,20000],"auth":{"mode":"passwords","config":["zi"]}}
EOF
    cat > "/etc/systemd/system/$HY_SERVICE" << SVCEOF
[Unit]
Description=HYSTERIA UDP Server (High-Speed)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0
[Service]
Type=simple
ExecStart=$HY_BIN server -c $HY_CONFIG
WorkingDirectory=/etc/hysteria
Restart=always
RestartSec=10
StartLimitBurst=0
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW
LimitNOFILE=1048576
LimitNPROC=infinity
LimitMEMLOCK=infinity
StandardOutput=append:/var/log/hysteria.log
StandardError=append:/var/log/hysteria.log
[Install]
WantedBy=multi-user.target
SVCEOF
    systemctl daemon-reload && systemctl enable "$HY_SERVICE" 2>/dev/null || true
    deploy_nft_tunnel hysteria 'table inet hysteria { chain input { type filter hook input priority 0; policy accept; udp dport 20000 accept; udp dport 20000-50000 accept; }; chain prerouting { type nat hook prerouting priority -100; udp dport 20000-50000 dnat to :20000; }; }'
    apply_network_optimizations
    hysteria_apply
    systemctl start "$HY_SERVICE" 2>/dev/null || true; sleep 2
    systemctl is-active --quiet "$HY_SERVICE" && log "Hysteria actif ($(get_ip):20000-50000 → 20000)" || err "Hysteria ne démarre pas"
    pause
}

uninstall_hysteria() {
    systemctl stop "$HY_SERVICE" 2>/dev/null || true; systemctl disable "$HY_SERVICE" 2>/dev/null || true
    rm -f "/etc/systemd/system/$HY_SERVICE" "$HY_BIN"; rm -rf /etc/hysteria
    remove_nft_tunnel hysteria; log "Hysteria supprimé"; pause
}

# ==============================================================================
#  V2RAY-DNS (backend VLESS TCP :5401, cible NV4 de SlowDNS)
# ==============================================================================
v2ray_gen_config() {
    local uuid="$1"; mkdir -p /etc/v2ray /var/log/v2ray
    cat > "$V2RAY_CONFIG" << V2CONFEOF
{
  "log": {"loglevel":"warning","access":"/var/log/v2ray/access.log","error":"/var/log/v2ray/error.log"},
  "inbounds": [{
    "port": 5401, "listen": "0.0.0.0", "protocol": "vless",
    "settings": {"clients": [{"id":"$uuid","email":"default@v2ray","level":0}],"decryption":"none"},
    "streamSettings": {"network":"tcp","security":"none"},
    "tag": "VLESS-TCP"
  }],
  "outbounds": [{"protocol":"freedom","settings":{}}],
  "stats": {},
  "policy": {"levels":{"0":{"statsUserUplink":true,"statsUserDownlink":true}},"system":{"statsInboundUplink":true,"statsInboundDownlink":true}},
  "api": {"tag":"api","services":["HandlerService","StatsService"]},
  "routing": {"rules":[{"type":"field","inboundTag":"api","outboundTag":"api"}]}
}
V2CONFEOF
}

install_v2ray() {
    echo -e " ${CYAN}━━━ V2Ray-DNS (VLESS TCP :5401) ━━━${RESET}"
    apt-get install -y -qq jq unzip wget 2>/dev/null
    if [[ ! -x "$V2RAY_BIN" ]]; then
        local tmp; tmp=$(mktemp)
        wget -q "https://github.com/v2fly/v2ray-core/releases/latest/download/v2ray-linux-64.zip" -O "$tmp"
        rm -rf /tmp/v2ray; unzip -o "$tmp" -d /tmp/v2ray >/dev/null 2>&1
        mv /tmp/v2ray/v2ray "$V2RAY_BIN"; chmod +x "$V2RAY_BIN"; rm -f "$tmp"
    fi
    mkdir -p /etc/v2ray /var/log/v2ray
    local DOMAIN; if [[ -n "${SKIP_PAUSE:-}" ]]; then DOMAIN=$(get_ip); else read -rp " Domaine [$(get_ip)]: " DOMAIN; DOMAIN=${DOMAIN:-$(get_ip)}; fi
    echo "$DOMAIN" > /etc/v2ray/domain.txt
    local UUID; UUID=$(gen_uuid); v2ray_gen_config "$UUID"
    cat > /etc/systemd/system/v2ray.service << 'V2SVCEOF'
[Unit]
Description=V2Ray Service
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0
[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/v2ray run -config /etc/v2ray/config.json
Restart=always
RestartSec=5
StartLimitBurst=0
LimitNOFILE=65536
KillMode=process
KillSignal=SIGTERM
TimeoutStopSec=10
[Install]
WantedBy=multi-user.target
V2SVCEOF
    systemctl daemon-reload && systemctl enable --now v2ray 2>/dev/null || true
    deploy_nft_tunnel v2ray 'table inet v2ray { chain input { type filter hook input priority 0; policy accept; tcp dport 5401 accept; }; chain output { type filter hook output priority 0; policy accept; tcp sport 5401 accept; }; }'
    v2raydns_apply
    log "V2Ray-DNS actif (port 5401, VLESS TCP)"; pause
}

uninstall_v2ray() {
    systemctl stop v2ray 2>/dev/null || true; systemctl disable v2ray 2>/dev/null || true
    rm -f /etc/systemd/system/v2ray.service "$V2RAY_BIN"; rm -rf /etc/v2ray /var/log/v2ray
    remove_nft_tunnel v2ray; systemctl daemon-reload; log "V2Ray-DNS supprimé"; pause
}

# ==============================================================================
#  XRAY (18 inbounds 127.0.0.1:10001-10018, security:none) + HAProxy (TLS/sniff)
# ==============================================================================
xray_gen_config() {
    mkdir -p /etc/xray "$XRAY_LOG"
    cat > "$XRAY_CONFIG" << 'CONFEOF'
{
  "log": { "loglevel": "warning", "access": "/var/log/xray/access.log", "error": "/var/log/xray/error.log" },
  "inbounds": [
    {"tag":"VMess-TCP","port":10001,"listen":"127.0.0.1","protocol":"vmess","settings":{"clients":[]},"streamSettings":{"network":"tcp","security":"none"}},
    {"tag":"VMess-WS","port":10002,"listen":"127.0.0.1","protocol":"vmess","settings":{"clients":[]},"streamSettings":{"network":"ws","security":"none","wsSettings":{"path":"/vmess"}}},
    {"tag":"VMess-TLS","port":10003,"listen":"127.0.0.1","protocol":"vmess","settings":{"clients":[]},"streamSettings":{"network":"tcp","security":"none"}},
    {"tag":"VMess-WSS","port":10004,"listen":"127.0.0.1","protocol":"vmess","settings":{"clients":[]},"streamSettings":{"network":"ws","security":"none","wsSettings":{"path":"/vmess"}}},
    {"tag":"VLESS-TCP","port":10005,"listen":"127.0.0.1","protocol":"vless","settings":{"clients":[],"decryption":"none"},"streamSettings":{"network":"tcp","security":"none"}},
    {"tag":"VLESS-WS","port":10006,"listen":"127.0.0.1","protocol":"vless","settings":{"clients":[],"decryption":"none"},"streamSettings":{"network":"ws","security":"none","wsSettings":{"path":"/vless"}}},
    {"tag":"VLESS-TLS","port":10007,"listen":"127.0.0.1","protocol":"vless","settings":{"clients":[],"decryption":"none"},"streamSettings":{"network":"tcp","security":"none"}},
    {"tag":"VLESS-WSS","port":10008,"listen":"127.0.0.1","protocol":"vless","settings":{"clients":[],"decryption":"none"},"streamSettings":{"network":"ws","security":"none","wsSettings":{"path":"/vless"}}},
    {"tag":"Trojan-TCP","port":10009,"listen":"127.0.0.1","protocol":"trojan","settings":{"clients":[]},"streamSettings":{"network":"tcp","security":"none"}},
    {"tag":"Trojan-WS","port":10010,"listen":"127.0.0.1","protocol":"trojan","settings":{"clients":[]},"streamSettings":{"network":"ws","security":"none","wsSettings":{"path":"/trojan"}}},
    {"tag":"Shadowsocks","port":10011,"listen":"127.0.0.1","protocol":"shadowsocks","settings":{"clients":[],"network":"tcp,udp"},"streamSettings":{"network":"tcp","security":"none"}},
    {"tag":"VLESS-XHTTP","port":10012,"listen":"127.0.0.1","protocol":"vless","settings":{"clients":[],"decryption":"none"},"streamSettings":{"network":"xhttp","security":"none","xhttpSettings":{"path":"/vless-xhttp"}}},
    {"tag":"VLESS-gRPC","port":10013,"listen":"127.0.0.1","protocol":"vless","settings":{"clients":[],"decryption":"none"},"streamSettings":{"network":"grpc","security":"none","grpcSettings":{"serviceName":"vless-grpc"}}},
    {"tag":"VMess-XHTTP","port":10014,"listen":"127.0.0.1","protocol":"vmess","settings":{"clients":[]},"streamSettings":{"network":"xhttp","security":"none","xhttpSettings":{"path":"/vmess-xhttp"}}},
    {"tag":"VMess-gRPC","port":10015,"listen":"127.0.0.1","protocol":"vmess","settings":{"clients":[]},"streamSettings":{"network":"grpc","security":"none","grpcSettings":{"serviceName":"vmess-grpc"}}},
    {"tag":"Trojan-XHTTP","port":10016,"listen":"127.0.0.1","protocol":"trojan","settings":{"clients":[]},"streamSettings":{"network":"xhttp","security":"none","xhttpSettings":{"path":"/trojan-xhttp"}}},
    {"tag":"Trojan-gRPC","port":10017,"listen":"127.0.0.1","protocol":"trojan","settings":{"clients":[]},"streamSettings":{"network":"grpc","security":"none","grpcSettings":{"serviceName":"trojan-grpc"}}},
    {"tag":"VLESS-HUpgrade","port":10018,"listen":"127.0.0.1","protocol":"vless","settings":{"clients":[],"decryption":"none"},"streamSettings":{"network":"httpupgrade","security":"none","httpupgradeSettings":{"path":"/vless-hupgrade"}}}
  ],
  "outbounds": [{"tag":"direct","protocol":"freedom","settings":{}}],
  "stats": {},
  "policy": { "levels": { "0": { "statsUserUplink": true, "statsUserDownlink": true } }, "system": { "statsInboundUplink": true, "statsInboundDownlink": true } },
  "api": { "tag": "api", "services": ["HandlerService","StatsService"] },
  "routing": { "rules": [{"type":"field","inboundTag":"api","outboundTag":"api"}] }
}
CONFEOF
}

xray_gen_haproxy() {
    mkdir -p /etc/haproxy
    cat > /etc/haproxy/haproxy.cfg << 'HAPEOF'
global
    daemon
    maxconn 65535
    tune.ssl.default-dh-param 2048
    ssl-default-bind-ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384
    ssl-default-bind-options no-sslv3 no-tlsv10 no-tlsv11

defaults
    mode tcp
    log global
    option tcplog
    option dontlognull
    timeout connect 5s
    timeout client 86400s
    timeout server 86400s
    timeout tunnel 86400s
    retries 3

# NTLS (Non-TLS) frontend :8880 — sniff par signature d'octets
frontend xray-ntls
    bind *:8880
    tcp-request inspect-delay 5s
    tcp-request content accept if { req.len ge 21 }
    acl is_h2         req.payload(0,3) -m bin 505249
    acl is_http       req.payload(0,4) -m bin 474554202f
    acl is_post       req.payload(0,4) -m bin 504f5354
    acl is_vless      req.payload(0,1) -m bin 00
    acl is_vless_ws   req.payload(0,11) -m bin 474554202f766c65737320
    acl is_vmess_ws   req.payload(0,12) -m bin 474554202f766d65737320
    acl is_trojan_ws  req.payload(0,13) -m bin 474554202f74726f6a616e20
    use_backend grpc_router        if is_h2
    use_backend xray-vless-ws      if is_vless_ws
    use_backend xray-vmess-ws      if is_vmess_ws
    use_backend xray-trojan-ws     if is_trojan_ws
    use_backend grpc_router        if is_http or is_post
    use_backend xray-vmess-tcp     if !is_vless
    default_backend xray-vless-tcp

# TLS Frontend :443 — HAProxy termine le TLS puis forward en clair vers Xray
frontend xray-tls
    bind *:443 ssl crt /etc/xray/xray.pem alpn h2,http/1.1
    tcp-request inspect-delay 5s
    tcp-request content accept if { req.len ge 5 }
    acl is_h2         req.payload(0,3) -m bin 505249
    acl is_http       req.payload(0,4) -m bin 474554202f
    acl is_post       req.payload(0,4) -m bin 504f5354
    acl is_vless      req.payload(0,1) -m bin 00
    acl is_vless_ws   req.payload(0,11) -m bin 474554202f766c65737320
    acl is_vmess_ws   req.payload(0,12) -m bin 474554202f766d65737320
    acl is_trojan_ws  req.payload(0,13) -m bin 474554202f74726f6a616e20
    use_backend grpc_router        if is_h2
    use_backend xray-vless-ws      if is_vless_ws
    use_backend xray-vmess-ws      if is_vmess_ws
    use_backend xray-trojan-ws     if is_trojan_ws
    use_backend grpc_router        if is_http or is_post
    use_backend xray-vmess-tcp     if !is_vless
    default_backend xray-vless-tcp

# Routeur gRPC/XHTTP interne (mode http)
frontend grpc_router
    bind 127.0.0.1:9898
    mode http
    timeout http-request 5s
    use_backend xray-vmess-grpc   if { path_beg /vmess-grpc }
    use_backend xray-vless-grpc   if { path_beg /vless-grpc }
    use_backend xray-trojan-grpc  if { path_beg /trojan-grpc }
    use_backend xray-vmess-grpc   if { path_beg /vmess-h2 }
    use_backend xray-vless-grpc   if { path_beg /vless-h2 }
    use_backend xray-trojan-grpc  if { path_beg /trojan-h2 }
    use_backend xray-vmess-xhttp  if { path_beg /vmess-xhttp }
    use_backend xray-vless-xhttp  if { path_beg /vless-xhttp }
    use_backend xray-trojan-xhttp if { path_beg /trojan-xhttp }
    use_backend xray-vless-hupgrade  if { path_beg /vless-hupgrade }
    default_backend xray-vless-grpc

backend grpc_router
    server grpc_http 127.0.0.1:9898

backend xray-vmess-tcp
    server s1 127.0.0.1:10001
backend xray-vmess-ws
    server s1 127.0.0.1:10002
backend xray-vless-tcp
    server s1 127.0.0.1:10005
backend xray-vless-ws
    server s1 127.0.0.1:10006
backend xray-vless-tls
    server s1 127.0.0.1:10007
backend xray-trojan-tcp
    server s1 127.0.0.1:10009
backend xray-trojan-ws
    server s1 127.0.0.1:10010
backend xray-ss
    server s1 127.0.0.1:10011
backend xray-vless-xhttp
    mode http
    server s1 127.0.0.1:10012
backend xray-vless-grpc
    mode http
    server s1 127.0.0.1:10013
backend xray-vmess-xhttp
    mode http
    server s1 127.0.0.1:10014
backend xray-vmess-grpc
    mode http
    server s1 127.0.0.1:10015
backend xray-trojan-xhttp
    mode http
    server s1 127.0.0.1:10016
backend xray-trojan-grpc
    mode http
    server s1 127.0.0.1:10017
backend xray-vless-hupgrade
    mode http
    server s1 127.0.0.1:10018
HAPEOF
}

# rebuild config.json à partir de $XRAY_USERS (source projetée par xray_add_user)
xray_build_config() {
    [[ -f "$XRAY_CONFIG" ]] || return 0
    local config users sanitized tmp
    config=$(cat "$XRAY_CONFIG")
    users=$(cat "$XRAY_USERS" 2>/dev/null || echo '{"vmess":[],"vless":[],"trojan":[],"shadow":[]}')
    sanitized=$(echo "$users" | jq '
        .vmess  |= (. // [] | map(if has("uuid") then .id = .uuid | del(.uuid) else . end)) |
        .vless  |= (. // [] | map(if has("uuid") then .id = .uuid | del(.uuid) else . end)) |
        .trojan |= (. // [] | map(if has("uuid") then .password = .uuid | del(.uuid) else . end)) |
        .shadow |= (. // [])
    ' 2>/dev/null || echo "$users")
    tmp=$(mktemp)
    echo "$config" | jq --argjson users "$sanitized" '
        (.inbounds[] | select(.tag == "VMess-TCP")   .settings.clients) = $users.vmess |
        (.inbounds[] | select(.tag == "VMess-WS")    .settings.clients) = $users.vmess |
        (.inbounds[] | select(.tag == "VMess-TLS")   .settings.clients) = $users.vmess |
        (.inbounds[] | select(.tag == "VMess-WSS")   .settings.clients) = $users.vmess |
        (.inbounds[] | select(.tag == "VMess-XHTTP") .settings.clients) = $users.vmess |
        (.inbounds[] | select(.tag == "VMess-gRPC")  .settings.clients) = $users.vmess |
        (.inbounds[] | select(.tag == "VLESS-TCP")   .settings.clients) = $users.vless |
        (.inbounds[] | select(.tag == "VLESS-WS")    .settings.clients) = $users.vless |
        (.inbounds[] | select(.tag == "VLESS-TLS")   .settings.clients) = $users.vless |
        (.inbounds[] | select(.tag == "VLESS-WSS")   .settings.clients) = $users.vless |
        (.inbounds[] | select(.tag == "VLESS-XHTTP") .settings.clients) = $users.vless |
        (.inbounds[] | select(.tag == "VLESS-gRPC")  .settings.clients) = $users.vless |
        (.inbounds[] | select(.tag == "VLESS-HUpgrade").settings.clients) = $users.vless |
        (.inbounds[] | select(.tag == "Trojan-TCP")  .settings.clients) = $users.trojan |
        (.inbounds[] | select(.tag == "Trojan-WS")   .settings.clients) = $users.trojan |
        (.inbounds[] | select(.tag == "Trojan-XHTTP").settings.clients) = $users.trojan |
        (.inbounds[] | select(.tag == "Trojan-gRPC") .settings.clients) = $users.trojan |
        (.inbounds[] | select(.tag == "Shadowsocks") .settings.clients) = $users.shadow
    ' > "$tmp" 2>/dev/null && jq empty "$tmp" >/dev/null 2>&1 && mv "$tmp" "$XRAY_CONFIG" || rm -f "$tmp"
    systemctl restart xray 2>/dev/null || true
}

install_xray() {
    echo -e " ${CYAN}━━━ Xray + HAProxy ━━━${RESET}"
    local IP DOMAIN; IP=$(get_ip)
    if [[ -n "${SKIP_PAUSE:-}" ]]; then DOMAIN="$IP"; else read -rp " Domaine (TLS) [$IP]: " DOMAIN; DOMAIN=${DOMAIN:-$IP}; fi
    apt-get update -qq 2>/dev/null
    apt-get install -y -qq haproxy curl socat xz-utils wget unzip jq ca-certificates lsof libcap2-bin 2>/dev/null
    systemctl stop haproxy xray 2>/dev/null || true
    mkdir -p /etc/xray "$XRAY_LOG"; echo "$DOMAIN" > "$XRAY_DOMAIN"

    if [[ ! -x "$XRAY_BIN" ]]; then
        local VER="26.1.23" _cwd; _cwd=$(pwd)
        rm -rf /tmp/xray_inst; mkdir -p /tmp/xray_inst; cd /tmp/xray_inst
        curl -L -o xray.zip "https://github.com/XTLS/Xray-core/releases/download/v${VER}/xray-linux-64.zip" 2>/dev/null || \
            curl -L -o xray.zip "https://github.com/XTLS/Xray-core/releases/latest/download/xray-linux-64.zip" 2>/dev/null
        unzip -o xray.zip >/dev/null 2>&1; mv -f xray "$XRAY_BIN"; chmod +x "$XRAY_BIN"
        setcap 'cap_net_bind_service=+ep' "$XRAY_BIN" 2>/dev/null || true
        cd "$_cwd" 2>/dev/null || cd /; rm -rf /tmp/xray_inst
    fi
    touch "$XRAY_LOG/access.log" "$XRAY_LOG/error.log"

    # Certificat TLS (acme.sh standalone si vrai domaine, sinon auto-signé)
    if [[ "$DOMAIN" != "$IP" && "$DOMAIN" =~ \. ]]; then
        command -v acme.sh >/dev/null 2>&1 || curl -fsSL https://get.acme.sh | bash 2>/dev/null || true
        ~/.acme.sh/acme.sh --set-default-ca --server letsencrypt 2>/dev/null || true
        local acme_ports acme_ok=""; acme_ports=$(ss -tlnp 2>/dev/null | awk '{print $4}' | grep -oP ':80$' | head -1)
        if [[ -n "$acme_ports" ]]; then
            warn "Port 80 occupe, arret temporaire des services pour acme.sh..."
            systemctl stop sshws ssl_tls stunnel4 nginx apache2 2>/dev/null || true
            sleep 1
        fi
        ~/.acme.sh/acme.sh --issue --standalone -d "$DOMAIN" --keylength ec-256 2>/dev/null && acme_ok=1
        if [[ -n "$acme_ports" ]]; then
            systemctl start sshws ssl_tls stunnel4 nginx apache2 2>/dev/null || true
        fi
        if [[ -n "$acme_ok" ]]; then
            ~/.acme.sh/acme.sh --installcert -d "$DOMAIN" --fullchainpath /etc/xray/xray.crt --keypath /etc/xray/xray.key --ecc 2>/dev/null || true
        fi
    fi
    [[ -f /etc/xray/xray.crt ]] || openssl req -x509 -newkey rsa:2048 -keyout /etc/xray/xray.key -out /etc/xray/xray.crt -nodes -days 3650 -subj "/CN=$DOMAIN" 2>/dev/null
    cat /etc/xray/xray.crt /etc/xray/xray.key > /etc/xray/xray.pem
    chmod 600 /etc/xray/xray.key /etc/xray/xray.pem

    xray_gen_config; xray_gen_haproxy
    [[ -f "$XRAY_USERS" ]] || echo '{"vmess":[],"vless":[],"trojan":[],"shadow":[]}' > "$XRAY_USERS"

    cat > /etc/systemd/system/xray.service << 'XSVCEOF'
[Unit]
Description=Xray Service
After=network-online.target nss-lookup.target
Wants=network-online.target
StartLimitIntervalSec=0
[Service]
User=root
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE
NoNewPrivileges=true
ExecStart=/usr/local/bin/xray -config /etc/xray/config.json
Restart=always
RestartSec=5s
StartLimitIntervalSec=0
StartLimitBurst=0
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
XSVCEOF
    mkdir -p /etc/systemd/system/haproxy.service.d
    printf '[Service]\nRestart=always\nStartLimitIntervalSec=0\nStartLimitBurst=0\n' > /etc/systemd/system/haproxy.service.d/override.conf
    systemctl daemon-reload
    xray_build_config
    systemctl enable --now xray haproxy 2>/dev/null || true; sleep 2

    (crontab -l 2>/dev/null | grep -v "xray-watchdog\|haproxy-watchdog"; echo "*/15 * * * * systemctl is-active --quiet xray || systemctl restart xray >> /var/log/xray-watchdog.log 2>&1"; echo "*/5 * * * * systemctl is-active --quiet haproxy || systemctl restart haproxy >> /var/log/haproxy-watchdog.log 2>&1") | crontab - 2>/dev/null || true
    systemctl is-active --quiet xray && log "Xray actif: 443 (TLS), 8880 (NTLS), 9898 (gRPC/XHTTP)" || err "Xray ne démarre pas"
    pause
}

uninstall_xray() {
    systemctl stop xray haproxy 2>/dev/null || true; systemctl disable xray haproxy 2>/dev/null || true
    rm -f /etc/systemd/system/xray.service; rm -rf /etc/systemd/system/haproxy.service.d
    rm -f "$XRAY_BIN"; rm -rf /etc/xray "$XRAY_LOG"
    systemctl daemon-reload
    crontab -l 2>/dev/null | grep -v "xray-watchdog\|haproxy-watchdog" | crontab - 2>/dev/null || true
    log "Xray supprimé"; pause
}

# ==============================================================================
#  GROUPES + INSTALL/UNINSTALL ALL  (appelés par menu_protocol_installer)
# ==============================================================================
install_ssh_stack()   { install_openssh; install_dropbear; }
install_ws_stack()    { install_sshws;   install_ssl_tls;  }
uninstall_ws_stack()  { uninstall_sshws; uninstall_ssl_tls; }
install_udp_stack()   { install_badvpn;  install_udp_custom; }
uninstall_udp_stack() { uninstall_badvpn; uninstall_udp_custom; }

install_all_missing() {
    clear; echo -e " ${CYAN}${WHITE}INSTALL ALL MISSING${RESET}\n"
    export SKIP_PAUSE=1
    command -v /usr/local/sbin/dropbear &>/dev/null || install_ssh_stack
    command -v sshws &>/dev/null || install_sshws
    command -v ssl_tls &>/dev/null || install_ssl_tls
    command -v badvpn-udpgw &>/dev/null || install_badvpn
    command -v udp-custom &>/dev/null || install_udp_custom
    command -v dnstt-server &>/dev/null || install_slowdns
    [[ -x "$XRAY_BIN" ]]  || install_xray
    [[ -x "$V2RAY_BIN" ]] || install_v2ray
    [[ -x "$ZIVPN_BIN" ]] || install_zivpn
    [[ -x "$HY_BIN" ]]    || install_hysteria
    unset SKIP_PAUSE
    _secure_permissions
    store_checksum
    # Installer le cron de vérification de licence
    _install_license_cron
    log "Installation des protocoles manquants terminée"; press_enter
}

# ── Cron de vérification de licence ──────────────────────────────────────────
_install_license_cron() {
    local cron_line="0 6 * * * root /usr/local/bin/kighmu --watchdog > /dev/null 2>&1"
    local cron_file="/etc/cron.d/kighmu-license"
    echo "$cron_line" > "$cron_file" 2>/dev/null
    chmod 644 "$cron_file" 2>/dev/null
    # Fallback crontab si /etc/cron.d/ non supporté
    if ! grep -q 'kighmu-license' /etc/crontab 2>/dev/null; then
        echo "$cron_line" >> /etc/crontab 2>/dev/null || true
    fi
}

uninstall_all_active() {
    clear; echo -e " ${RED}${WHITE}UNINSTALL ALL ACTIVE${RESET}\n"
    echo -ne " ${RED}Confirmer la suppression de TOUS les protocoles ? [y/N]: ${RESET}"; read -r c
    [[ "$c" =~ ^[yY]$ ]] || { echo; _msg_err "Annulé"; press_enter; return; }
    export SKIP_PAUSE=1
    uninstall_dropbear; uninstall_ws_stack; uninstall_udp_stack
    uninstall_slowdns; uninstall_xray; uninstall_v2ray; uninstall_zivpn; uninstall_hysteria
    unset SKIP_PAUSE
    log "Tous les protocoles actifs supprimés"; press_enter
}

# petit sélecteur install/uninstall par protocole
proto_action() {   # $1=titre $2=fn_install $3=fn_uninstall
    clear
    echo -e " ${CYAN}${1}${RESET}\n"
    echo -e "   ${GREEN}1${RESET}) Install / Repair"
    echo -e "   ${RED}2${RESET}) Uninstall"
    echo -e "   ${GRAY}0${RESET}) Back"
    echo -ne "\n Choice: "; read -r a
    case "$a" in
        1) "$2" ;;
        2) "$3" ;;
        *) : ;;
    esac
}

# ==============================================================================
#  LOGIQUE — OPTIMIZE VPS / ONLINE COUNTER / UPDATE-REMOVE  (section métier #3)
# ==============================================================================
SELF_PATH="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || echo /usr/local/bin/kighmu)"
SCRIPT_RAW_URL="https://raw.githubusercontent.com/kinf744/Tyiop24/main/install2.sh"

# --- horodatage / marqueur d'optimisation ---
opt_stamp() { mkdir -p "$STATEDIR"; date '+%Y-%m-%d %H:%M' > "$STATEDIR/optimized"; }

# --- [07] tuning sysctl (drop-in dédié → sysctl_status=ON) ---
opt_sysctl() {
    modprobe tcp_bbr 2>/dev/null || true; modprobe sch_fq 2>/dev/null || true
    cat > /etc/sysctl.d/99-kighmu.conf << 'SYSEOF'
# === Kighmu sysctl tuning ===
net.core.rmem_default=26214400
net.core.wmem_default=26214400
net.core.rmem_max=67108864
net.core.wmem_max=67108864
net.core.optmem_max=25165824
net.core.netdev_max_backlog=250000
net.core.somaxconn=4096
net.core.default_qdisc=fq
net.ipv4.tcp_congestion_control=bbr
net.ipv4.ip_forward=1
net.ipv4.udp_mem=102400 873800 16777216
net.ipv4.tcp_fastopen=3
net.ipv4.tcp_mtu_probing=1
net.ipv4.tcp_tw_reuse=1
net.ipv4.tcp_fin_timeout=15
fs.file-max=1000000
SYSEOF
    sysctl --system >/dev/null 2>&1 || sysctl -p /etc/sysctl.d/99-kighmu.conf >/dev/null 2>&1 || true
    local IFACE; IFACE=$(ip route show default 2>/dev/null | awk '/default/ {print $5}' | head -1)
    [[ -n "$IFACE" ]] && { tc qdisc del dev "$IFACE" root 2>/dev/null || true; tc qdisc add dev "$IFACE" root fq 2>/dev/null || true; }
}

# --- [02] BBR seul ---
opt_bbr() {
    modprobe tcp_bbr 2>/dev/null || true
    sysctl -w net.core.default_qdisc=fq >/dev/null 2>&1 || true
    sysctl -w net.ipv4.tcp_congestion_control=bbr >/dev/null 2>&1 || true
    grep -qs '^net.ipv4.tcp_congestion_control=bbr' /etc/sysctl.d/99-kighmu-bbr.conf 2>/dev/null || \
        printf 'net.core.default_qdisc=fq\nnet.ipv4.tcp_congestion_control=bbr\n' > /etc/sysctl.d/99-kighmu-bbr.conf
}

# --- [03] swap ---
opt_swap() {
    local sz="${1:-1G}"
    if swapon --show 2>/dev/null | grep -q '/swapfile'; then warn "Swap déjà actif"; return 0; fi
    fallocate -l "$sz" /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=1024 2>/dev/null
    chmod 600 /swapfile; mkswap /swapfile >/dev/null 2>&1; swapon /swapfile 2>/dev/null || true
    grep -q '/swapfile' /etc/fstab 2>/dev/null || echo '/swapfile none swap sw 0 0' >> /etc/fstab
    log "Swap $sz activé"
}

# --- [04] nettoyage caches / temp ---
opt_clean() {
    apt-get clean 2>/dev/null || true; apt-get autoremove -y -qq 2>/dev/null || true
    journalctl --vacuum-size=100M >/dev/null 2>&1 || true
    sync; echo 3 > /proc/sys/vm/drop_caches 2>/dev/null || true
    find /tmp -mindepth 1 -mtime +1 -delete 2>/dev/null || true
    rm -rf /var/tmp/* 2>/dev/null || true
    log "Caches, journaux et fichiers temporaires nettoyés"
}

# --- [05] limite taille des logs journald (loglimit_status=ON) ---
opt_loglimit() {
    mkdir -p /etc/systemd
    if grep -qsE '^[[:space:]]*#?SystemMaxUse=' /etc/systemd/journald.conf 2>/dev/null; then
        sed -i 's/^[[:space:]]*#\?SystemMaxUse=.*/SystemMaxUse=200M/' /etc/systemd/journald.conf
    else
        echo "SystemMaxUse=200M" >> /etc/systemd/journald.conf
    fi
    systemctl restart systemd-journald 2>/dev/null || true
    log "Taille des logs limitée à 200 Mo"
}

# --- [06] désactive quelques services inutiles s'ils sont présents ---
opt_disable_services() {
    local s; local svcs=(apache2 avahi-daemon cups bluetooth modemmanager whoopsie)
    for s in "${svcs[@]}"; do
        systemctl list-unit-files 2>/dev/null | grep -q "^${s}.service" && systemctl disable --now "$s" 2>/dev/null || true
    done
    log "Services inutiles désactivés (si présents)"
}

# --- [01] activation globale ---
opt_enable() {
    clear; echo -e " ${CYAN}${WHITE}ENABLE OPTIMIZATION${RESET}\n"
    opt_sysctl; opt_bbr; opt_stamp; mkdir -p "$STATEDIR"; : > "$STATEDIR/optimized_flag"
    _msg_ok "Optimisation activée (sysctl + BBR)."; press_enter
}

# --- [08] optimisation complète ---
opt_full() {
    clear; echo -e " ${CYAN}${WHITE}RUN FULL OPTIMIZATION${RESET}\n"
    opt_sysctl; opt_bbr; opt_loglimit; opt_swap 1G; opt_disable_services; opt_clean
    opt_stamp; : > "$STATEDIR/optimized_flag"
    _msg_ok "Optimisation complète appliquée."; press_enter
}

# --- [09] restauration ---
opt_restore() {
    clear; echo -e " ${RED}${WHITE}RESTORE DEFAULT SETTINGS${RESET}\n"
    echo -ne " ${RED}Restaurer les réglages par défaut ? [y/N]: ${RESET}"; read -r c
    [[ "$c" =~ ^[yY]$ ]] || { echo; _msg_err "Annulé"; press_enter; return; }
    rm -f /etc/sysctl.d/99-kighmu.conf /etc/sysctl.d/99-kighmu-bbr.conf
    sed -i '/^SystemMaxUse=/d' /etc/systemd/journald.conf 2>/dev/null || true
    systemctl restart systemd-journald 2>/dev/null || true
    sysctl --system >/dev/null 2>&1 || true
    rm -f "$STATEDIR/optimized" "$STATEDIR/optimized_flag"
    _msg_ok "Réglages par défaut restaurés."; press_enter
}

# petit wrapper : exécute une action d'optimisation puis pause
opt_run() { clear; echo -e " ${CYAN}${WHITE}$1${RESET}\n"; "$2"; opt_stamp; press_enter; }

# ------------------------------------------------------------------------------
#  ONLINE COUNTER — actions
# ------------------------------------------------------------------------------
oc_set_interval() {
    clear; echo -e " ${YELLOW}○${RESET} ${WHITE}SET REFRESH INTERVAL${RESET}\n"
    local v; v=$(_ask "Interval (secondes, 1-60)")
    if [[ "$v" =~ ^[0-9]+$ && "$v" -ge 1 && "$v" -le 60 ]]; then
        mkdir -p "$STATEDIR"; echo "$v" > "$STATEDIR/refresh_interval"; _msg_ok "Intervalle réglé à ${v}s."
    else _msg_err "Valeur invalide (1-60)."; fi
    press_enter
}

oc_kick() {
    clear; echo -e " ${YELLOW}○${RESET} ${WHITE}KICK / DISCONNECT USER${RESET}\n"
    local u; u=$(_ask "Username à déconnecter")
    [[ -z "$u" ]] && { _msg_err "Aucun utilisateur."; press_enter; return; }
    if id "$u" &>/dev/null || _meta_exists "$u"; then
        pkill -KILL -u "$u" 2>/dev/null || true
        pkill -KILL -f "sshd:.*$u" 2>/dev/null || true
        _msg_ok "Sessions de '$u' terminées."
    else _msg_err "Utilisateur '$u' introuvable."; fi
    press_enter
}

oc_export() {
    clear; echo -e " ${YELLOW}○${RESET} ${WHITE}EXPORT LOG (ONLINE HISTORY)${RESET}\n"
    local dir="/var/log/kighmu" f
    mkdir -p "$dir"; f="$dir/online-$(date '+%Y%m%d-%H%M%S').log"
    { echo "# Kighmu online snapshot $(date '+%Y-%m-%d %H:%M:%S')";
      echo "# SSH online: $(count_ssh_online 2>/dev/null || echo 0)";
      ssh_online_detail 2>/dev/null || true; } > "$f"
    _msg_ok "Export écrit : $f"; press_enter
}

# ------------------------------------------------------------------------------
#  UPDATE / REMOVE — actions
# ------------------------------------------------------------------------------
upd_check() {
    clear; echo -e " ${YELLOW}○${RESET} ${WHITE}CHECK FOR UPDATES${RESET}\n"
    command -v curl >/dev/null 2>&1 || { _msg_err "curl requis."; press_enter; return; }
    local tmp; tmp=$(mktemp)
    if curl -fsSL "$SCRIPT_RAW_URL" -o "$tmp" 2>/dev/null; then
        local rl ll; rl=$(sha256sum "$tmp" | awk '{print $1}'); ll=$(sha256sum "$SELF_PATH" 2>/dev/null | awk '{print $1}')
        if [[ "$rl" == "$ll" ]]; then _msg_ok "Déjà à jour (${VERSION})."
        else echo -e " ${YELLOW}Une nouvelle version est disponible.${RESET}"; echo -e " ${GRAY}local : $ll${RESET}"; echo -e " ${GRAY}remote: $rl${RESET}"; fi
    else _msg_err "Impossible de contacter le dépôt."; fi
    rm -f "$tmp"; press_enter
}

upd_update() {
    clear; echo -e " ${YELLOW}○${RESET} ${WHITE}UPDATE SCRIPT${RESET}\n"
    command -v curl >/dev/null 2>&1 || { _msg_err "curl requis."; press_enter; return; }
    if [[ -f "$STATEDIR/backup_before_update" ]]; then
        cp -f "$SELF_PATH" "${SELF_PATH}.bak.$(date '+%Y%m%d%H%M%S')" 2>/dev/null && echo -e " ${GRAY}Sauvegarde créée.${RESET}"
    fi
    local tmp; tmp=$(mktemp)
    if curl -fsSL "$SCRIPT_RAW_URL" -o "$tmp" 2>/dev/null && bash -n "$tmp" 2>/dev/null; then
        install -m 0755 "$tmp" "$SELF_PATH" && _msg_ok "Mise à jour installée. Relancez le panneau."
    else _msg_err "Échec du téléchargement ou script invalide."; fi
    rm -f "$tmp"; press_enter
}

upd_changelog() {
    clear; echo -e " ${YELLOW}○${RESET} ${WHITE}CHANGELOG / VERSION HISTORY${RESET}\n"
    echo -e " ${WHITE}${VERSION}${RESET}"
    echo -e "   ${GRAY}• Fichier unique, panneau terminal professionnel${RESET}"
    echo -e "   ${GRAY}• Tunnels 100% nftables (aucun iptables)${RESET}"
    echo -e "   ${GRAY}• Xray 18 inbounds + HAProxy (TLS 443 / NTLS 8880)${RESET}"
    echo -e "   ${GRAY}• Sans panel web ni bot telegram${RESET}"
    press_enter
}

upd_reinstall() {
    clear; echo -e " ${RED}${WHITE}REINSTALL SCRIPT (CLEAN)${RESET}\n"
    echo -ne " ${RED}Réinstaller la dernière version proprement ? [y/N]: ${RESET}"; read -r c
    [[ "$c" =~ ^[yY]$ ]] || { echo; _msg_err "Annulé"; press_enter; return; }
    upd_update
}

upd_remove() {
    clear; echo -e " ${RED}${WHITE}REMOVE SCRIPT (UNINSTALL)${RESET}\n"
    echo -e " ${RED}Ceci supprime le panneau. Les tunnels installés ne sont PAS touchés.${RESET}"
    echo -ne " ${RED}Tapez 'REMOVE' pour confirmer : ${RESET}"; read -r c
    [[ "$c" == "REMOVE" ]] || { echo; _msg_err "Annulé"; press_enter; return; }
    rm -f "$SELF_PATH" /usr/local/bin/kighmu /usr/local/bin/menu 2>/dev/null || true
    _msg_ok "Panneau supprimé. (Données /etc/kighmu conservées.)"; press_enter; clear; exit 0
}

# ── Vérificateur de licence (cron + démarrage) ────────────────────────────────
# S'appelle via le cron ou au lancement du menu.
# Si la licence est expirée → désinstallation complète automatique.
# ── Désinstallation complète automatique (sans aucune confirmation) ───────────
_auto_uninstall_all() {
    export SKIP_PAUSE=1
    uninstall_dropbear; uninstall_ws_stack; uninstall_udp_stack
    uninstall_slowdns; uninstall_xray; uninstall_v2ray; uninstall_zivpn; uninstall_hysteria
    rm -rf /etc/kighmu /usr/local/bin/kighmu /usr/local/bin/menu 2>/dev/null || true
    rm -f /root/install2.sh 2>/dev/null || true
    rm -f /etc/cron.d/kighmu-license 2>/dev/null || true
    sed -i '/kighmu-license/d' /etc/crontab 2>/dev/null || true
    unset SKIP_PAUSE
    echo
    echo -e " ${RED}╔════════════════════════════════════════════╗${RST}"
    echo -e " ${RED}║${RST}  ${WHITE}LICENCE EXPIRÉE — SYSTÈME RÉINITIALISÉ${RST}${RED}    ║${RST}"
    echo -e " ${RED}║${RST}  ${GRAY}Tous les tunnels et le panneau${RST}${RED}              ║${RST}"
    echo -e " ${RED}║${RST}  ${GRAY}ont été supprimés du serveur.${RST}${RED}               ║${RST}"
    echo -e " ${RED}╚════════════════════════════════════════════╝${RST}"
    echo
}

_license_watchdog() {
    local key_file="/etc/kighmu/.license_key"
    local db="/etc/ventes/ventes.db"

    [[ ! -f "$key_file" ]] && return 0
    local key
    key=$(cat "$key_file" 2>/dev/null) || return 0
    [[ -z "$key" || "$key" == "KIGHMU_MASTER_2026" ]] && return 0

    if [[ ! -f "$db" ]]; then
        echo -e " ${RED}[✗]${RESET} Base de licence introuvable. Désinstallation complète..."
        _auto_uninstall_all
        return 1
    fi

    local row
    row=$(sqlite3 "$db" "SELECT status, expires_at, client_name FROM licenses WHERE license_key='$key' AND status='ACTIVE' AND (expires_at >= date('now') OR expires_at='9999-12-31');" 2>/dev/null)
    if [[ -z "$row" ]]; then
        local why
        why=$(sqlite3 "$db" "SELECT status FROM licenses WHERE license_key='$key';" 2>/dev/null)
        if [[ -z "$why" ]]; then
            echo -e " ${RED}[✗]${RESET} Licence '${key:0:12}...' introuvable. Désinstallation complète..."
        else
            echo -e " ${RED}[✗]${RESET} Licence '${key:0:12}...' statut=${why}. Désinstallation complète..."
        fi
        _auto_uninstall_all
        exit 1
    fi
    local cname
    cname=$(echo "$row" | cut -d'|' -f3)
    echo "$cname" > /etc/kighmu/.client_name 2>/dev/null || true
    sqlite3 "$db" "UPDATE licenses SET last_checkin=datetime('now') WHERE license_key='$key';" 2>/dev/null || true
    return 0
}

main_menu() {
    _license_watchdog
    while true; do
        scr_main
        read -r CH
        case "$CH" in
            1|01) menu_manage_users ;;
            2|02) menu_optimize ;;
            3|03) menu_online_counter ;;
            4|04) toggle_autostart ;;
            5|05) menu_protocol_installer ;;
            6|06) menu_update_remove ;;
            0)    clear; exit 0 ;;
            *)    : ;;   # entrée invalide → réaffiche
        esac
    done
}

# ------------------------------------------------------------------------------
#  CONTRÔLEUR — helpers communs
# ------------------------------------------------------------------------------
# Bascule d'un marqueur d'état (fichier dans STATEDIR)
toggle_flag() { mkdir -p "$STATEDIR" 2>/dev/null; if [[ -f "$STATEDIR/$1" ]]; then rm -f "$STATEDIR/$1"; else : > "$STATEDIR/$1"; fi; }
toggle_autostart() { toggle_flag autostart; }

# ------------------------------------------------------------------------------
#  CONTRÔLEUR — [01] MANAGE USERS (sélection de famille → sous-panneau)
# ------------------------------------------------------------------------------
menu_manage_users() {
    while true; do
        scr_manage_users
        read -r CH
        case "$CH" in
            1|01) submenu_family scr_users_ssh       ssh ;;
            2|02) submenu_family scr_users_xray      xray ;;
            3|03) submenu_family scr_users_v2raydns  v2raydns ;;
            4|04) submenu_family scr_users_zivpn     zivpn ;;
            5|05) submenu_family scr_users_hysteria  hysteria ;;
            0)    return ;;
            *)    : ;;
        esac
    done
}

# Sous-panneau d'une famille : $1 = fonction d'écran, $2 = clé famille
submenu_family() {
    local screen="$1" fam="$2"
    # protos comptés pour LIST (xray = 3 protos, sinon la famille elle-même)
    local -a lprotos
    case "$fam" in
        xray) lprotos=(vmess vless trojan) ;;
        *)    lprotos=("$fam") ;;
    esac
    while true; do
        "$screen"
        read -r CH
        case "$CH" in
            1|01) if [[ "$fam" == "xray" ]]; then submenu_xray_create
                  else ui_create "$fam"; fi ;;
            2|02) scr_list_users "${fam^^}" "${lprotos[@]}" ;;
            3|03) ui_delete "$fam" ;;
            4|04) ui_renew ;;
            5|05) ui_lock ;;
            6|06) ui_passwd ;;
            7|07) ui_info ;;
            8|08) ui_delete_expired ;;
            0)    return ;;
            *)    : ;;
        esac
    done
}

# Écran de sélection du protocole Xray avant création
submenu_xray_create() {
    while true; do
        scr_xray_create_select
        read -r CH
        case "$CH" in
            1|01) ui_create vmess ;;
            2|02) ui_create vless ;;
            3|03) ui_create trojan ;;
            0)    return ;;
            *)    : ;;
        esac
    done
}

# ------------------------------------------------------------------------------
#  CONTRÔLEUR — [02] OPTIMIZE VPS
# ------------------------------------------------------------------------------
menu_optimize() {
    while true; do
        scr_optimize
        read -r CH
        case "$CH" in
            1|01) opt_enable ;;
            2|02) opt_run "BBR (TCP CONGESTION CONTROL)" opt_bbr ;;
            3|03) opt_run "SWAP CONFIGURATION" opt_swap ;;
            4|04) opt_run "CLEAN CACHE / TEMP FILES" opt_clean ;;
            5|05) opt_run "LIMIT LOG SIZE (JOURNALCTL)" opt_loglimit ;;
            6|06) opt_run "DISABLE UNUSED SERVICES" opt_disable_services ;;
            7|07) opt_run "NETWORK / SYSCTL TUNING" opt_sysctl ;;
            8|08) opt_full ;;
            9|09) opt_restore ;;
            0)    return ;;
            *)    : ;;
        esac
    done
}

# ------------------------------------------------------------------------------
#  CONTRÔLEUR — [03] ONLINE USERS COUNTER
# ------------------------------------------------------------------------------
menu_online_counter() {
    while true; do
        scr_online_counter
        read -r CH
        case "$CH" in
            1|01) scr_online_details ;;
            2|02) : ;;   # REFRESH NOW → simple ré-affichage de la boucle
            3|03) toggle_flag online_counter ;;
            4|04) oc_set_interval ;;
            5|05) oc_kick ;;
            6|06) oc_export ;;
            0)    return ;;
            *)    : ;;
        esac
    done
}

# ------------------------------------------------------------------------------
#  CONTRÔLEUR — [05] PROTOCOL INSTALLER
# ------------------------------------------------------------------------------
menu_protocol_installer() {
    while true; do
        scr_protocol_installer
        read -r CH
        case "$CH" in
            1|01) proto_action "SSH / DROPBEAR (ports 22 / 109)"   install_ssh_stack   uninstall_dropbear ;;
            2|02) proto_action "WS-EPRO (SSH-WS port 80)"         install_sshws       uninstall_sshws ;;
            3|03) proto_action "SSL/TLS (port 444 → 109)"         install_ssl_tls     uninstall_ssl_tls ;;
            4|04) proto_action "XRAY + HAProxy (443 / 8880 / 9898)" install_xray       uninstall_xray ;;
            5|05) proto_action "V2RAY-DNS (VLESS TCP 5401)"        install_v2ray       uninstall_v2ray ;;
            6|06) proto_action "BADVPN (UDPGW 7100/7200/7300)"     install_badvpn      uninstall_badvpn ;;
            7|07) proto_action "UDP CUSTOM (36712)"                install_udp_custom  uninstall_udp_custom ;;
            8|08) proto_action "SLOWDNS (53 → 5353/5354)"          install_slowdns     uninstall_slowdns ;;
            9|09) proto_action "HYSTERIA (20000-50000)"            install_hysteria    uninstall_hysteria ;;
            10)   proto_action "ZIVPN (5667 / 6000-19999)"         install_zivpn       uninstall_zivpn ;;
            11)   install_all_missing ;;
            12)   uninstall_all_active ;;
            0)    return ;;
            *)    : ;;
        esac
    done
}

# ------------------------------------------------------------------------------
#  CONTRÔLEUR — [06] UPDATE / REMOVE
# ------------------------------------------------------------------------------
menu_update_remove() {
    while true; do
        scr_update_remove
        read -r CH
        case "$CH" in
            1|01) upd_check ;;
            2|02) upd_update ;;
            3|03) upd_changelog ;;
            4|04) toggle_flag backup_before_update ;;
            5|05) upd_reinstall ;;
            6|06) upd_remove ;;
            0)    return ;;
            *)    : ;;
        esac
    done
}

# ==============================================================================
#  ENTRÉE
# ==============================================================================
# Installe le script en commande système : `menu` (et alias `kighmu`) ouvrent le panneau.
self_install() {
    local dst="/usr/local/bin/kighmu" src
    src="$(readlink -f "${BASH_SOURCE[0]}" 2>/dev/null || echo "$0")"
    [[ -z "$src" || ! -f "$src" ]] && return 1
    mkdir -p /usr/local/bin
    # copie le script si la cible diffère (évite d'écraser une exécution en cours)
    if [[ "$src" != "$dst" ]]; then
        install -m 0755 "$src" "$dst" 2>/dev/null || { cp -f "$src" "$dst" && chmod 0755 "$dst"; }
    else
        chmod 0755 "$dst" 2>/dev/null || true
    fi
    # commande `menu` → lance le panneau
    ln -sf "$dst" /usr/local/bin/menu 2>/dev/null || \
        { printf '#!/usr/bin/env bash\nexec %s "$@"\n' "$dst" > /usr/local/bin/menu && chmod 0755 /usr/local/bin/menu; }
    return 0
}

# Si le fichier est sourcé (tests, réutilisation de fonctions), on n'exécute rien.
if [[ "${BASH_SOURCE[0]}" != "${0}" ]]; then
    return 0 2>/dev/null || true
fi

case "${1:-}" in
    --install)  # bootstrap : installe la commande `menu` puis ouvre le panneau
        self_install && { clear; echo -e " ${GREEN:-}${WHITE:-}✓ Commande 'menu' installée.${RESET:-}"; sleep 1; }
        _verify_license
        _license_watchdog
        main_menu ;;
    --watchdog) # exécution silencieuse (cron / démarrage) — pas de vérif clé
        _license_watchdog
        exit $? ;;
    --auto-uninstall) # forcer la désinstallation complète (appelé par le watchdog)
        _auto_uninstall_all
        exit 0 ;;
    --render) shift
        case "${1:-main}" in
            main)         scr_main ;;
            manage)       scr_manage_users ;;
            ssh)          scr_users_ssh ;;
            xray)         scr_users_xray ;;
            v2raydns)     scr_users_v2raydns ;;
            zivpn)        scr_users_zivpn ;;
            hysteria)     scr_users_hysteria ;;
            xray-create)  scr_xray_create_select ;;
            optimize)     scr_optimize ;;
            online)       scr_online_counter ;;
            online-details) scr_online_details ;;
            installer)    scr_protocol_installer ;;
            update)       scr_update_remove ;;
            vless-detail)     show_vless_details    "${2:-created}" carol   1f8b0c2e-4d5a-4b6c-8e9f-0a1b2c3d4e5f 2026-08-15 50 ;;
            trojan-detail)    show_trojan_details   "${2:-created}" erin    Tr0j4nP4ss2026 2026-07-25 30 ;;
            vmess-detail)     show_vmess_details    "${2:-created}" dave    9c8b7a6d-5e4f-3a2b-1c0d-9e8f7a6b5c4d 2026-07-20 0 ;;
            hysteria-detail)  show_hysteria_details "${2:-created}" frank   HyPass2026 2026-09-01 ;;
            zivpn-detail)     show_zivpn_details    "${2:-created}" grace   ZiPass2026 2026-07-23 ;;
            ssh-detail)       show_ssh_details      "${2:-created}" alice   Al1cePass 2026-12-31 ;;
        esac
        echo; exit 0 ;;
    *) self_install 2>/dev/null || true; _verify_license; _license_watchdog; main_menu ;;
esac
