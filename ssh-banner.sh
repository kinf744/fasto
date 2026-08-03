#!/bin/bash
# ssh-banner.sh — VPS-PRO dynamic SSH banner (DARNIX style)
# Shown via pam_exec on SSH session open (post-login).
# Reads /etc/kighmu/users/$USER (used/quota/limit) and chage -l (expiration).

R=$'\033[0m'
BOLD=$'\033[1m'
MINT=$'\033[38;5;48m'
BLUE=$'\033[38;5;75m'
REDO=$'\033[38;5;203m'
PINK=$'\033[38;5;213m'
PURPLE=$'\033[38;5;141m'
ORANGE=$'\033[38;5;214m'
WHITE=$'\033[38;5;255m'
GRAY=$'\033[38;5;245m'
CYAN=$'\033[38;5;81m'

USER="${PAM_USER:-${SUDO_USER:-${USER:-$(id -un)}}}"
meta="/etc/kighmu/users/$USER"

plain() { printf '%s' "$1" | sed -r $'s/\x1b\\[[0-9;]*m//g'; }
vislen() { local s; s=$(plain "$1"); printf '%s' "${#s}"; }
repeat() { printf "%${1}s" '' | tr ' ' "$2"; }
pad() {
    local s l
    s=$(plain "$1"); l=${#s}
    printf '%s' "$s"
    while [ "$l" -lt "$2" ]; do printf ' '; l=$((l + 1)); done
}
read_meta() { [ -f "$meta" ] && grep "^$1=" "$meta" | head -1 | cut -d= -f2-; }
fmt_bytes() {
    awk -v b="$1" 'BEGIN{u[0]="B";u[1]="KB";u[2]="MB";u[3]="GB";u[4]="TB";i=0;
        while (b >= 1024 && i < 4) { b /= 1024; i++ }
        printf "%.1f %s", b, u[i]}'
}
gradient() {
    local text="$1" n i c col
    n=${#text}; n=$(( n > 1 ? n : 1 ))
    for ((i = 0; i < ${#text}; i++)); do
        c="${text:$i:1}"
        col=$(( 48 + (214 - 48) * i / n ))
        printf '\033[1;38;5;%sm%s\033[0m' "$col" "$c"
    done
}

used=$(read_meta used);      used=${used:-0}
quota=$(read_meta quota);    quota=${quota:-0}
limit=$(read_meta limit)

exp_raw=""
if command -v chage >/dev/null 2>&1; then
    chage_out=$(chage -l "$USER" 2>/dev/null)
    exp_raw=$(printf '%s\n' "$chage_out" | grep -i "account" | grep -i "expires" | head -1 | cut -d: -f2- | sed 's/^[[:space:]]*//')
fi
days=""
case "$(printf '%s' "$exp_raw" | tr 'A-Z' 'a-z')" in
    never|permanent|"")
        meta_exp=$(read_meta exp)
        if [ -n "$meta_exp" ] && [ "$meta_exp" != "permanent" ]; then
            exp_epoch=$(date -d "$meta_exp" +%s 2>/dev/null)
        fi
        ;;
    *)
        exp_epoch=$(date -d "$exp_raw" +%s 2>/dev/null)
        if [ -z "$exp_epoch" ]; then
            meta_exp=$(read_meta exp)
            [ -n "$meta_exp" ] && [ "$meta_exp" != "permanent" ] && exp_epoch=$(date -d "$meta_exp" +%s 2>/dev/null)
        fi
        ;;
esac
if [ -n "$exp_epoch" ]; then
    now=$(date +%s)
    days=$(( (exp_epoch - now) / 86400 ))
    exp_disp=$(date -d "@$exp_epoch" +%d/%m/%Y)
fi
[ -n "$days" ] || exp_disp="∞"

if [ -n "$days" ]; then
    if [ "$days" -lt 0 ]; then days_str="EXPIRÉ"; days_col=$REDO
    elif [ "$days" -le 7 ]; then days_str="$days j"; days_col=$ORANGE
    else days_str="$days j"; days_col=$MINT; fi
    exp_col=$days_col
else
    days_str="∞"; days_col=$MINT
    exp_col=$MINT
fi

used_str=$(fmt_bytes "$used")
maxv=""
if [ "$quota" -gt 0 ] 2>/dev/null; then
    maxv=" (Max: $(awk -v q="$quota" 'BEGIN{printf "%g", q}') GB)"
    pct=$(awk -v u="$used" -v q="$quota" 'BEGIN{printf "%.0f", u / q / 1073741824 * 100}')
    if [ "$pct" -ge 100 ]; then used_col=$REDO
    elif [ "$pct" -ge 70 ]; then used_col=$ORANGE
    else used_col=$MINT; fi
else
    used_str="Illimité"
    used_col=$MINT
fi

LW=15
rows=()
[ -n "$USER" ] && rows+=("$WHITE$(pad "Utilisateur:" "$LW")$R   $PINK$USER$R")
rows+=("$WHITE$(pad "Expire:" "$LW")$R   $exp_col$exp_disp$R")
rows+=("$WHITE$(pad "Jours restants:" "$LW")$R   $days_col$days_str$R")
rows+=("$WHITE$(pad "Consommé:" "$LW")$R   $used_col$used_str$R$PURPLE$maxv$R")
[ -n "$limit" ] && rows+=("$WHITE$(pad "Limite IP:" "$LW")$R   $BLUE$limit$R")

title="${MINT}⚡${R} $(gradient "VPS-PRO SSH TUNNEL") ${MINT}⚡${R}"
sub="${GRAY}Connexion sécurisée${R}"

inner=0
for r in "${rows[@]}"; do
    l=$(vislen "$r"); [ "$l" -gt "$inner" ] && inner=$l
done
for r in "$title" "$sub"; do
    l=$(vislen "$r"); [ "$l" -gt "$inner" ] && inner=$l
done

b() {
    local s="$1" padn
    padn=$(( inner - $(vislen "$s") )); [ "$padn" -lt 0 ] && padn=0
    printf '%s' "$CYAN┃$R  $s$(repeat "$padn" ' ')  $CYAN┃$R"
}
c() {
    local s="$1" padn lft rgt
    padn=$(( inner - $(vislen "$s") )); [ "$padn" -lt 0 ] && padn=0
    lft=$(( padn / 2 )); rgt=$(( padn - lft ))
    printf '%s' "$CYAN┃$R  $(repeat "$lft" ' ')$s$(repeat "$rgt" ' ')  $CYAN┃$R"
}

top="$CYAN┏$(repeat $((inner + 4)) '━')┓$R"
bot="$CYAN┗$(repeat $((inner + 4)) '━')┛$R"
blank="$CYAN┃$R$(repeat $((inner + 4)) ' ')$CYAN┃$R"
ind="   "

printf '\n'
printf '%s\n' "$ind$top"
printf '%s\n' "$ind$(b "")"
printf '%s\n' "$ind$(c "$title")"
printf '%s\n' "$ind$(b "")"
printf '%s\n' "$ind$(c "$sub")"
printf '%s\n' "$ind$(b "")"
for r in "${rows[@]}"; do printf '%s\n' "$ind$(b "$r")"; done
printf '%s\n' "$ind$(b "")"
printf '%s\n' "$ind$bot"
printf '\n'
