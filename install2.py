#!/usr/bin/env python3
"""Kighmu Panel - VPS Management (Python port of install2.sh)"""

import os, sys, json, subprocess, sqlite3, re, asyncio, logging, base64, signal
import uuid as _uuid, time, shutil, pathlib, socket, hashlib, secrets, fcntl
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Optional

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
log = logging.getLogger("kighmu")

C = {
    "CYAN": "\033[1;38;2;0;200;255m", "YELLOW": "\033[38;2;255;196;0m",
    "WHITE": "\033[38;2;235;235;235m", "GREEN": "\033[1;38;2;0;230;80m",
    "RED": "\033[1;38;2;255;70;70m", "GRAY": "\033[38;2;130;130;140m",
    "KEYBG": "\033[48;2;0;190;90m\033[30m", "BTNBG": "\033[48;2;255;196;0m\033[30m",
    "BOLD": "\033[1m", "RST": "\033[0m",
}
VERSION = "V3.9.9"
USERDIR = Path("/etc/kighmu/users")
STATEDIR = Path("/etc/kighmu/state")
XRAY_USERS = Path("/etc/xray/users.json")
V2RAY_USERS = Path("/etc/v2ray/users.json")
BANNER = [
    '__     ______  ____        ____  ____   ___  ',
    r"\ \   / /  _ \/ ___|      |  _ \|  _ \ / _ \ ",
    r" \ \ / /| |_) \___ \ _____| |_) | |_) | | | |",
    r"  \ V / |  __/ ___) |_____|  __/|  _ <| |_| |",
    r"   \_/  |_|   |____/      |_|   |_| \_\\___/ ",
    '                                             ',
]

def sh(cmd, timeout=300):
    try: return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout).stdout.strip()
    except: return ""

def strip_ansi(s): return re.sub(r'\x1b\[[0-9;]*m', '', s)
def vislen(s): return len(strip_ansi(s))

def clear_screen():
    os.system("stty sane 2>/dev/null")
    subprocess.run("TERM=xterm-256color tput clear 2>/dev/null", shell=True)
    sys.stdout.write("\033[H\033[2J\033[3J")
    sys.stdout.write("\n" * 80)
    sys.stdout.write("\033[H\033[2J\033[3J")
    sys.stdout.flush()

def render_screen(lines):
    w = 0
    for l in lines:
        if l == "%SEP%" or l.startswith("%FREE%"): continue
        v = vislen(l)
        if v > w: w = v
    w += 2; dash = "─" * w
    out = []
    for l in lines:
        if l == "%SEP%": out.append(f"{C['YELLOW']}{dash}{C['RST']}")
        elif l.startswith("%FREE%"): out.append(l[6:])
        else: out.append(l)
    sys.stdout.write("\n".join(out) + "\n\033[J")
    sys.stdout.flush()

def render_panel(lines, prompt=True):
    clear_screen()
    render_screen(lines)
    if prompt:
        sys.stdout.write(f"\n {C['YELLOW']}►{C['RST']} {C['WHITE']}Option : {C['RST']}")
        sys.stdout.flush()

def press_enter():
    sys.stdout.write(f"\n{C['GRAY']} Press ENTER to go back...{C['RST']}")
    sys.stdout.flush()
    input()

def dot(lbl, w=18):
    n = w - len(lbl) - 1
    if n < 1: n = 1
    return f"{lbl} {'•' * n}"

def _client_name():
    try: n = Path('/etc/kighmu/.client_name').read_text().strip()
    except: n = ""
    if not n or n == "Verified": n = "Kighmu"
    return f"Verified - {n} tech tutorials oficial ©"

def _detail_title(mode, proto, variant=""):
    if mode == "created":
        return f" {C['GREEN']}{C['BOLD']}✔ {proto} USER CREATED SUCCESSFULLY{(' ('+variant+')') if variant else ''}{C['RST']}"
    return f" {C['YELLOW']}{C['BOLD']}🧩 {proto} USER DETAILS{(' ('+variant+')') if variant else ''}{C['RST']}"

def get_os():
    try:
        for l in Path("/etc/os-release").read_text().splitlines():
            if l.startswith("PRETTY_NAME="): return l.split("=",1)[1].strip().strip('"')
    except: pass
    return sh("uname -s") or "N/A"
def get_arch(): return sh("uname -m")
def get_cores(): return sh("nproc 2>/dev/null || echo 1")
def get_ipv4():
    for c in ["curl -4 -s --max-time 2 ifconfig.me 2>/dev/null", "curl -4 -s --max-time 2 ipinfo.io/ip 2>/dev/null",
              r"ip -4 addr show 2>/dev/null | grep -oP 'inet \K[\d.]+' | grep -v '^127\.' | head -1",
              r"hostname -I 2>/dev/null | grep -oP '\d+\.\d+\.\d+\.\d+' | head -1"]:
        ip = sh(c)
        if ip: return ip
    return "N/A"
def get_ipv6():
    for c in ["curl -6 -s --max-time 2 ifconfig.me 2>/dev/null", "curl -6 -s --max-time 2 ipinfo.io/ip 2>/dev/null",
              r"ip -6 addr show 2>/dev/null | grep -oP 'inet6 \K[\da-f:]+' | grep -v '^::1\|^fe80\|^fd' | head -1"]:
        ip = sh(c)
        if ip: return ip
    return ""
def get_main_iface():
    iface = sh("ip route get 1 2>/dev/null | head -1 | grep -oP 'dev \\K\\S+'")
    if iface: return iface
    iface = sh("ip -6 route get 2001:4860:4860::8888 2>/dev/null | head -1 | grep -oP 'dev \\K\\S+'")
    if iface: return iface
    for f in ["/proc/net/route", "/proc/net/if_inet6"]:
        try:
            for l in Path(f).read_text().splitlines():
                if l.strip():
                    name = l.split()[-1]
                    if name != "lo": return name
        except: pass
    return "eth0"

def has_ipv4():
    return bool(get_ipv4()) or any(
        sh(f"ip -4 addr show {get_main_iface()} 2>/dev/null | grep -oP 'inet \\K[\\d.]+' | grep -v '^127\\.' | head -1")
    )

def has_ipv6():
    return bool(get_ipv6()) or Path("/proc/sys/net/ipv6/conf/all/disable_ipv6").read_text().strip() == "0" and bool(
        sh(f"ip -6 addr show {get_main_iface()} 2>/dev/null | grep -oP 'inet6 \\K[\\da-f:]+' | grep -v '^::1\\|^fe80\\|^fd' | head -1")
    )

def get_ip(): return get_ipv4()
def get_primary_ip(): return get_ipv6() or get_ipv4()
def get_datetime(): return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
def get_domain():
    for f in ["/etc/kighmu/domain.txt", "/etc/xray/domain", "/etc/v2ray/domain.txt"]:
        try: return Path(f).read_text().strip()
        except: pass
    return get_primary_ip()

def _mem_field(col):
    try: return int(sh(f"free -m | awk '/^Mem:/{{print ${col}}}'"))
    except: return 0
def ram_total_g(): return f"{_mem_field(2)/1024:.1f}"
def ram_free_g(): return f"{_mem_field(7)/1024:.1f}"
def ram_used_g(): return f"{_mem_field(3)/1024:.1f}"
def ram_buffer_m(): return str(_mem_field(6))
def ram_pct():
    t = _mem_field(2); u = _mem_field(3)
    return u*100//t if t else 0
def cpu_pct():
    try:
        with open("/proc/stat") as f: p = f.readline().split()
        i1 = int(p[4])+int(p[5]); b1 = int(p[1])+int(p[2])+int(p[3])+int(p[6])+int(p[7])
        time.sleep(0.2)
        with open("/proc/stat") as f: p = f.readline().split()
        i2 = int(p[4])+int(p[5]); b2 = int(p[1])+int(p[2])+int(p[3])+int(p[6])+int(p[7])
        d = (b2-b1); t = (i2+b2-i1-b1)
        return d*100//t if t > 0 else 0
    except: return 0
def pct_color(p): return f"{C['RED']}{p}%{C['RST']}" if p > 90 else f"{C['YELLOW']}{p}%{C['RST']}"
def count_ssh_total(): return int(sh(r"awk -F: '$3>=1000 && $7 ~ /(bash|sh)$/ {n++} END{print n+0}' /etc/passwd") or "0")
def panel_system_accounts():
    return [l.strip() for l in sh("awk -F: '$3>=1000 && $3<65534 && $6==\"/home/\"$1 && $7 ~ /(bash|sh|nologin)$/ {print $1}' /etc/passwd").splitlines() if l.strip()]
def count_xray_total(): return int(sh("jq '[.vmess,.vless,.trojan]|map(length)|add' /etc/xray/users.json 2>/dev/null") or "0")
def count_total_users():
    if not USERDIR.exists(): return 0
    return sum(1 for f in USERDIR.iterdir() if f.is_file())
def count_locked(): return int(sh(r"awk -F: '$3>=1000 && $2 ~ /^!/ {n++} END{print n+0}' /etc/shadow 2>/dev/null") or "0")

def _count_family(mode, *protos):
    today = date.today().isoformat()
    if not USERDIR.exists(): return 0
    n = 0
    for f in USERDIR.iterdir():
        if not f.is_file(): continue
        p = _meta_get(f.name, "proto")
        if p not in protos: continue
        e = _meta_get(f.name, "exp")
        if mode == "total": n += 1
        elif mode == "exp" and e and e < today: n += 1
        elif mode == "active" and (not e or e >= today): n += 1
    return n
def fam_total(*p): return _count_family("total", *p)
def fam_expired(*p): return _count_family("exp", *p)
def fam_active(*p): return _count_family("active", *p)
def count_expired():
    today = date.today().isoformat()
    if not USERDIR.exists(): return 0
    return sum(1 for f in USERDIR.iterdir() if f.is_file() and (e := _meta_get(f.name, "exp")) and e < today)

def _fmt_bytes(b):
    b = int(b)
    if b >= 1 << 40: return f"{b/(1<<40):.2f}T"
    if b >= 1 << 30: return f"{b/(1<<30):.2f}G"
    if b >= 1 << 20: return f"{b/(1<<20):.0f}M"
    if b >= 1 << 10: return f"{b/(1<<10):.0f}K"
    return f"{b}B"

def _vnstat_data():
    try:
        r = subprocess.run(["vnstat","--json"], capture_output=True, text=True, timeout=10)
        d = json.loads(r.stdout)
        ifaces = d.get("interfaces", [])
        if not ifaces: return "N/A","N/A","N/A"
        t = ifaces[0]["traffic"]
        day = t.get("day", [])
        month = t.get("month", [])
        d_rx = day[-1]["rx"] if day else 0
        d_tx = day[-1]["tx"] if day else 0
        w_rx = sum(x["rx"] for x in day[-7:]) if len(day)>=7 else d_rx
        w_tx = sum(x["tx"] for x in day[-7:]) if len(day)>=7 else d_tx
        m_rx = month[-1]["rx"] if month else 0
        m_tx = month[-1]["tx"] if month else 0
        dw = f"{_fmt_bytes(d_rx+d_tx)}"
        ww = f"{_fmt_bytes(w_rx+w_tx)}"
        mw = f"{_fmt_bytes(m_rx+m_tx)}"
        return dw, ww, mw
    except:
        return "N/A","N/A","N/A"

def flag_status(name):
    f = STATEDIR / name
    return f"{C['GREEN']}[ON]{C['RST']}" if f.exists() else f"{C['RED']}[OFF]{C['RST']}"
def bbr_status():
    return f"{C['GREEN']}[ON]{C['RST']}" if sh("sysctl -n net.ipv4.tcp_congestion_control 2>/dev/null") == "bbr" else f"{C['RED']}[OFF]{C['RST']}"
def svc_status(name):
    return f"{C['GREEN']}[ON]{C['RST']}" if sh(f"systemctl is-active {name} 2>/dev/null") == "active" else f"{C['RED']}[OFF]{C['RST']}"
def loglimit_status():
    return f"{C['GREEN']}[ON]{C['RST']}" if sh("grep -qsE '^[[:space:]]*SystemMaxUse=' /etc/systemd/journald.conf && echo 1 || echo 0") == "1" else f"{C['RED']}[OFF]{C['RST']}"
def sysctl_status():
    return f"{C['GREEN']}[ON]{C['RST']}" if Path("/etc/sysctl.d/99-kighmu.conf").exists() else f"{C['RED']}[OFF]{C['RST']}"
def last_optimized():
    f = STATEDIR / "optimized"
    return f.read_text().strip() if f.exists() and f.stat().st_size > 0 else "NEVER"
def proto_on(*candidates):
    for x in candidates:
        if sh(f"systemctl is-active {x} 2>/dev/null") == "active" or sh(f"command -v {x} 2>/dev/null") != "": return True
    return False

def _svc_ready(svc):
    if svc == "sshd": return True
    if svc == "haproxy":
        return sh("systemctl is-active haproxy 2>/dev/null") == "active" and (":443 " in sh("ss -tlnp 2>/dev/null") or ":8880 " in sh("ss -tlnp 2>/dev/null"))
    cases = {
        "badvpn-7100": sh("systemctl is-active badvpn-7100 2>/dev/null") == "active",
        "dnsdist": sh("systemctl is-active dnsdist 2>/dev/null") == "active",
        "dropbear-custom": sh("systemctl is-active dropbear-custom 2>/dev/null") == "active" and ":109 " in sh("ss -tlnp 2>/dev/null"),
        "v2ray": sh("systemctl is-active v2ray 2>/dev/null") == "active" and ":5401 " in sh("ss -tlnp 2>/dev/null"),
        "xray": sh("systemctl is-active xray 2>/dev/null") == "active",
        "sshws": sh("systemctl is-active sshws 2>/dev/null") == "active" and ":80 " in sh("ss -tlnp 2>/dev/null"),
        "ssl_tls": sh("systemctl is-active ssl_tls 2>/dev/null") == "active" and ":444 " in sh("ss -tlnp 2>/dev/null"),
        "zivpn": sh("systemctl is-active zivpn 2>/dev/null") == "active" and ":5667 " in sh("ss -ulnp 2>/dev/null"),
        "hysteria": sh("systemctl is-active hysteria 2>/dev/null") == "active" and "hysteria" in sh("ss -ulnp 2>/dev/null"),
        "udp-custom": sh("systemctl is-active udp-custom 2>/dev/null") == "active" and ":36712 " in sh("ss -ulnp 2>/dev/null"),
    }
    return cases.get(svc, False)

def _meta_get(user, field):
    if not user: return ""
    f = USERDIR / user
    if not f.is_file(): return ""
    for line in f.read_text().splitlines():
        if line.startswith(f"{field}="): return line.split("=",1)[1]
    return ""
def _meta_set(user, field, value):
    if not user: return
    f = USERDIR / user
    if not f.is_file(): return
    lines = f.read_text().splitlines(); new = []
    found = False
    for line in lines:
        if line.startswith(f"{field}="): new.append(f"{field}={value}"); found = True
        else: new.append(line)
    if not found: new.append(f"{field}={value}")
    f.write_text("\n".join(new) + "\n")

def write_meta(user, proto, exp, limit="", passwd="", uuid="", quota=""):
    USERDIR.mkdir(parents=True, exist_ok=True)
    lines = [f"proto={proto}", f"exp={exp}", f"created={date.today().isoformat()}"]
    if limit: lines.append(f"limit={limit}")
    if passwd: lines.append(f"pass={passwd}")
    if uuid: lines.append(f"uuid={uuid}")
    if quota: lines.append(f"quota={quota}")
    (USERDIR / user).write_text("\n".join(lines) + "\n")

def valid_name(name): return bool(re.match(r'^[a-zA-Z0-9._-]{1,32}$', name))
def exp_in_days(days): return (date.today() + timedelta(days=days)).isoformat()
def gen_uuid(): return str(_uuid.uuid4())
def gen_pass(n=12): return sh(f"openssl rand -base64 {n} | tr -d '=/+' | head -c {n}") or sh(f"head -c {n} /dev/urandom | base64 | tr -d '=/+' | head -c {n}") or "Kighmu2026!"
def is_locked(user): return _meta_get(user, "locked") == "1"

# User CRUD
def create_user(proto, user, days, passwd="", limit="1", quota="0"):
    if not valid_name(user): return 1
    if (USERDIR / user).exists(): return 2
    exp = exp_in_days(days); uuid = ""; proto = proto.lower()
    if proto == "ssh":
        if sh(f"id {user} 2>/dev/null"): return 2
        sh(f"userdel -r {user} 2>/dev/null || true")
        sh(f"useradd -m -s /bin/bash -e {exp} {user} 2>/dev/null")
        if not sh(f"id {user} 2>/dev/null"): return 3
        passwd = passwd or gen_pass()
        sh(f"echo '{user}:{passwd}' | chpasswd 2>/dev/null")
        write_meta(user, "ssh", exp, limit, passwd, "", quota)
        _install_ssh_banner_shell()
        sh(f"usermod -s {SSH_SHELL} {user} 2>/dev/null || true")
        _ssh_quota_apply()
        ns = sh("cat /etc/slowdns/ns.conf 2>/dev/null")
        if ns: sh(f"echo '{user}|{passwd}|{limit}|{exp}|{get_ip()}|{get_domain()}|{ns}' >> /etc/kighmu/users.list 2>/dev/null || true")
    elif proto in ("vmess","vless"):
        uuid = gen_uuid()
        if not XRAY_USERS.exists(): XRAY_USERS.write_text('{"vmess":[],"vless":[],"trojan":[],"shadow":[]}')
        sh(f"jq '.{proto} += [{{\"id\":\"{uuid}\",\"email\":\"{user}\",\"level\":0,\"expire\":\"{exp}\",\"quota\":{float(quota) or 0}}}]' {XRAY_USERS} > /tmp/xu.json 2>/dev/null && mv /tmp/xu.json {XRAY_USERS} 2>/dev/null")
        write_meta(user, proto, exp, "", "", uuid, quota)
        xray_build_config()
    elif proto == "trojan":
        passwd = passwd or gen_pass()
        if not XRAY_USERS.exists(): XRAY_USERS.write_text('{"vmess":[],"vless":[],"trojan":[],"shadow":[]}')
        sh(f"jq '.trojan += [{{\"password\":\"{passwd}\",\"email\":\"{user}\",\"level\":0,\"expire\":\"{exp}\",\"quota\":{float(quota) or 0}}}]' {XRAY_USERS} > /tmp/xu.json 2>/dev/null && mv /tmp/xu.json {XRAY_USERS} 2>/dev/null")
        write_meta(user, "trojan", exp, "", passwd, "", quota)
        xray_build_config()
    elif proto == "v2raydns":
        uuid = gen_uuid()
        write_meta(user, "v2raydns", exp, "", "", uuid, quota)
        v2raydns_apply()
    elif proto == "zivpn":
        passwd = passwd or gen_pass()
        write_meta(user, "zivpn", exp, "", passwd, "", quota)
        zivpn_apply()
    elif proto == "hysteria":
        passwd = passwd or gen_pass()
        write_meta(user, "hysteria", exp, "", passwd, "", quota)
        hysteria_apply()
    else: return 1
    return 0

# ── Apply functions (self-contained, no bash dependency) ───────────────────
def _active_passwords(proto):
    today = date.today().isoformat()
    if not USERDIR.exists(): return []
    passwords = []
    for f in USERDIR.iterdir():
        if not f.is_file(): continue
        if _meta_get(f.name, "proto") != proto: continue
        exp = _meta_get(f.name, "exp")
        if exp and exp < today: continue
        if is_locked(f.name): continue
        p = _meta_get(f.name, "pass")
        if p: passwords.append(p)
    return sorted(set(passwords))

def _reload_passwords(config_path, service, proto):
    config = Path(config_path)
    if not config.exists(): return
    pws = _active_passwords(proto)
    if not pws: pws = ["zi"]
    tmp = config.with_suffix(".json.tmp")
    try:
        data = json.loads(config.read_text())
        data.setdefault("auth", {})["config"] = pws
        tmp.write_text(json.dumps(data, indent=2))
        ok = sh(f"python3 -c 'import json; json.load(open(\"{tmp}\"))' 2>/dev/null && echo OK")
        if ok:
            before = config.read_bytes() if config.exists() else b""
            tmp.replace(config)
            if config.read_bytes() != before:
                sh(f"systemctl restart {service} 2>/dev/null || true")
        else:
            print(f" {C['RED']}✗ {service}: JSON invalide, annulé{C['RST']}")
            tmp.unlink(missing_ok=True)
    except Exception as e:
        print(f" {C['RED']}✗ {service}: {e}{C['RST']}")
        tmp.unlink(missing_ok=True)

def zivpn_apply():
    _reload_passwords("/etc/zivpn/config.json", "zivpn", "zivpn")

def hysteria_apply():
    _reload_passwords("/etc/hysteria/config.json", "hysteria", "hysteria")

def v2raydns_apply():
    V2RAY_CONFIG = Path("/etc/v2ray/config.json")
    USERS_JSON = Path("/etc/v2ray/users.json")
    if not V2RAY_CONFIG.exists(): return
    today = date.today().isoformat()
    clients = []
    if USERDIR.exists():
        for f in USERDIR.iterdir():
            if not f.is_file(): continue
            if _meta_get(f.name, "proto") != "v2raydns": continue
            exp = _meta_get(f.name, "exp")
            if exp and exp < today: continue
            if is_locked(f.name): continue
            uuid = _meta_get(f.name, "uuid")
            if not uuid: continue
            q = float(_meta_get(f.name, "quota") or "0")
            clients.append({"id": uuid, "email": f.name, "level": 0, "quota": q})
    USERS_JSON.write_text(json.dumps({"vless": clients}, indent=2))
    tmp = V2RAY_CONFIG.with_suffix(".json.tmp")
    try:
        data = json.loads(V2RAY_CONFIG.read_text())
        for ib in data.get("inbounds", []):
            if ib.get("tag") == "VLESS-TCP":
                ib["settings"]["clients"] = clients; break
        tmp.write_text(json.dumps(data, indent=2))
        valid = sh(f"python3 -c 'import json; json.load(open(\"{tmp}\"))' 2>/dev/null && echo OK")
        if valid:
            before = V2RAY_CONFIG.read_bytes() if V2RAY_CONFIG.exists() else b""
            tmp.replace(V2RAY_CONFIG)
            if V2RAY_CONFIG.read_bytes() != before:
                sh("systemctl restart v2ray 2>/dev/null || true")
        else:
            print(f" {C['RED']}✗ v2raydns: JSON invalide, annulé{C['RST']}")
            tmp.unlink(missing_ok=True)
    except Exception as e:
        print(f" {C['RED']}✗ v2raydns: {e}{C['RST']}")
        tmp.unlink(missing_ok=True)

# ── Protocol install/uninstall functions (self-contained) ────────────────
def _ensure_nft_base():
    sh("systemctl enable --now nftables 2>/dev/null || true")
    Path("/etc/nftables").mkdir(parents=True, exist_ok=True)
    # Create nftables-tunnel service template for reboot persistence
    svc = """[Unit]
Description=nftables tunnel %i
After=nftables.service
PartOf=nftables.service
ReloadPropagatedFrom=nftables.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f /etc/nftables/%i.nft
ExecStop=/usr/sbin/nft delete table inet %i
[Install]
WantedBy=multi-user.target
"""
    Path("/etc/systemd/system/nftables-tunnel@.service").write_text(svc)
    sh("systemctl daemon-reload 2>/dev/null || true")
    # (bug corrigé) la table kighmu existante ne doit PAS court-circuiter
    # la création du catchall udp-custom (sinon jamais déployé en réinstall)
    if sh("nft list table inet kighmu 2>/dev/null") == "":
        for c in [
            "add table inet kighmu",
            "'add chain inet kighmu input { type filter hook input priority 0; policy accept; }'",
            "'add chain inet kighmu output { type filter hook output priority 0; policy accept; }'",
            "'add chain inet kighmu forward { type filter hook forward priority 0; policy accept; }'",
        ]: sh(f"nft {c} 2>/dev/null || true")
    _configure_resolv()
    _ensure_nat_catchall()

def _deploy_nft(name, nft_src):
    _ensure_nft_base()
    Path("/etc/nftables").mkdir(parents=True, exist_ok=True)
    Path(f"/etc/nftables/{name}.nft").write_text(nft_src)
    ok = sh(f"nft -c -f /etc/nftables/{name}.nft 2>/dev/null && echo OK")
    if ok:
        # Idempotence : supprime la table existante avant rechargement
        # pour eviter le MERGE nft (sinon regles dupliquees en reinstall).
        sh(f"nft delete table inet {name} 2>/dev/null || true")
        sh(f"systemctl enable nftables-tunnel@{name}.service 2>/dev/null || true")
        sh(f"systemctl restart nftables-tunnel@{name}.service 2>/dev/null || true")
        if sh(f"nft list table inet {name} 2>/dev/null") == "":
            sh(f"nft -f /etc/nftables/{name}.nft 2>/dev/null || true")
    else:
        print(f" {C['RED']}✗ nftables {name}: règle invalide, ignorée.{C['RST']}")

def _remove_nft(name):
    sh(f"systemctl disable --now nftables-tunnel@{name}.service 2>/dev/null || true")
    Path(f"/etc/nftables/{name}.nft").unlink(missing_ok=True)
    # Suppression verifiee : si la table persiste (merges/residus), force le delete
    for _ in range(3):
        sh(f"nft delete table inet {name} 2>/dev/null || true")
        if sh(f"nft list table inet {name} 2>/dev/null") == "":
            break

def _configure_resolv():
    resolv = Path("/etc/resolv.conf")
    try:
        current = resolv.read_text().strip()
    except:
        current = ""
    has4 = has_ipv4()
    has6 = has_ipv6()
    desired = []
    if has4:
        desired.extend(["nameserver 1.1.1.1", "nameserver 8.8.8.8"])
    if has6:
        desired.extend(["nameserver 2606:4700:4700::1111", "nameserver 2001:4860:4860::8888"])
    if not desired:
        desired = ["nameserver 1.1.1.1", "nameserver 8.8.8.8"]
    desired_str = "\n".join(desired) + "\n"
    if current != desired_str:
        sh("chattr -i /etc/resolv.conf 2>/dev/null || true")
        resolv.write_text(desired_str)
        sh("chattr +i /etc/resolv.conf 2>/dev/null || true")

def _ensure_nat_catchall():
    # Seulement nécessaire si le tunnel UDP-Custom est installé (port 36712)
    if Path("/etc/udp-custom").exists() or sh("command -v udp-custom 2>/dev/null") != "":
        _deploy_nat_catchall()

def _deploy_nat_catchall():
    iface = get_main_iface()
    # Le catchall (priority -50) capture AVANT les dnat des autres tunnels dont la
    # priority est superieure (hysteria=100). On exclut donc leurs ports pour que
    # chaque tunnel garde le trafic qui lui revient (et on ne casse pas hysteria).
    exclude = [53, 5300]
    if sh("command -v hysteria-linux-amd64 2>/dev/null") != "" or Path("/etc/hysteria").exists():
        exclude.append("20000-50000")
    if sh("command -v zivpn 2>/dev/null") != "" or Path("/etc/zivpn").exists():
        exclude.append("6000-19999")
    if sh("command -v falconserver 2>/dev/null") != "" or Path("/etc/falcon").exists():
        exclude.append("1194")
    excl_str = ", ".join(str(p) for p in exclude)
    nft_src = f"""table inet udp-custom-catchall {{
    chain prerouting {{
        type nat hook prerouting priority -50; policy accept;
        iifname "{iface}" meta nfproto ipv4 udp dport {{ {excl_str} }} return
        iifname "{iface}" meta nfproto ipv4 udp dport 1-65535 dnat to :36712
    }}
}}"""
    Path("/etc/nftables").mkdir(parents=True, exist_ok=True)
    Path("/etc/nftables/udp-custom-catchall.nft").write_text(nft_src)
    svc_path = Path("/etc/systemd/system/nftables-tunnel@.service")
    if not svc_path.exists():
        svc_path.write_text(f"""[Unit]
Description=nftables tunnel %i
After=nftables.service
PartOf=nftables.service
ReloadPropagatedFrom=nftables.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f /etc/nftables/%i.nft
ExecStop=/usr/sbin/nft delete table inet %i
[Install]
WantedBy=multi-user.target
""")
    sh("systemctl daemon-reload 2>/dev/null; systemctl enable --now nftables-tunnel@udp-custom-catchall.service 2>/dev/null || true")
    _deploy_nft_dedup_watchdog()

def _deploy_nft_dedup_watchdog():
    # Preventif : evite/constit le conflit de duplication de tables nftables entre
    # le catchall UDP-Custom (installe, le source) et kighmu/iptables qui injectent
    # leur propre "dnat to :36712" sans exclure le port 53 (ce qui bloque slowdns).
    # Automatic : ce script est lance a chaque reboot + toutes les minutes par cron.
    WATCHDOG = "/usr/local/bin/kighmu-nft-dedup.py"
    src = '''#!/usr/bin/env python3
"""Automatiquement deploye par install2.py. Role: dedup de la table nft
'ip nat' lorsque kighmu/iptables/Docker y ajoutent une règle dnat 1-65535 -> :36712
sans exclure le port 53, ce qui entre en conflit avec le tunnel slowdns (port 53).

La source de verite du DNAT udp-custom est la table inet udp-custom-catchall
(exclut 53/5300). Ce script supprime les regles dnat vers :36712 dupliquees
dans les tables ip nat / ip6 nat, conserve les tables inet udp-custom*, et ne
casse pas Docker (regle jump DOCKER conservee).
"""
import re, subprocess, os
from datetime import datetime

LOG = "/var/log/kighmu-nft-dedup.log"
KEEP_TABLES = {("inet", "udp-custom"), ("inet", "udp-custom-catchall")}
CATCHALL_NFT = "/etc/nftables/udp-custom-catchall.nft"

def log(m):
    try:
        with open(LOG, "a") as f:
            f.write("[%s] %s\\n" % (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), m))
    except Exception:
        pass

def sh(c):
    r = subprocess.run(c, shell=True, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()

def nft(a):
    r = subprocess.run(["nft"] + a, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr

def installed():
    rc, _, _ = sh("command -v udp-custom 2>/dev/null")
    return rc == 0 or os.path.isdir("/etc/udp-custom")

def ensure_catchall():
    if not os.path.exists(CATCHALL_NFT):
        return
    rc, _, _ = nft(["list", "table", "inet", "udp-custom-catchall"])
    if rc != 0:
        nft(["-f", CATCHALL_NFT]); log("recharge catchall"); return
    if "53" not in nft(["list", "table", "inet", "udp-custom-catchall"])[1]:
        nft(["delete", "table", "inet", "udp-custom-catchall"]); nft(["-f", CATCHALL_NFT]); log("recharge catchall (exclusions)")
    sh("systemctl enable nftables-tunnel@udp-custom-catchall.service >/dev/null 2>&1")

def collect():
    rc, out, _ = nft(["-a", "list", "ruleset"])
    res, cur_t, cur_c = [], None, None
    for line in (out or "").splitlines():
        tm = re.match(r"\\s*table\\s+(\\S+)\\s+(\\S+)\\s*\\{", line)
        if tm:
            cur_t, cur_c = (tm.group(1), tm.group(2)), None; continue
        cm = re.match(r"\\s*chain\\s+(\\S+)\\s+.*\\{", line)
        if cm:
            cur_c = cm.group(1); continue
        if cur_t is None or cur_t[0] not in ("ip", "ip6") or cur_t in KEEP_TABLES:
            continue
        if ":36712" in line and "dnat" in line:
            hm = re.search(r"#\\s*handle\\s+(\\d+)", line)
            res.append((cur_t, cur_c, hm.group(1) if hm else None))
    return res

def ensure_slowdns_prio():
    """Garantit la priorite -150 du redirect slowdns (INBATTABLE).
    La table slowdns doit rester exécutée AVANT toute table ip nat (prio -100)
    pour que le port 53 aille toujours à dnsdist, meme si kighmu/iptables
    re-injecte un doublon. Si slowdns est absent, ou a encore l'ancienne prio
    fragile -100, on la recharge depuis le fichier disque (-150)."""
    nf = "/etc/nftables/slowdns.nft"
    if not os.path.exists(nf):
        return
    rc, out, _ = nft(["list", "chain", "inet", "slowdns", "prerouting"])
    # nft affiche la priorite -150 sous le nom "mangle" et -100 sous "dstnat".
    # On accepte donc les deux rendus (-150 explicite ou "mangle") et on rejette
    # explicitement "dstnat" pour ne pas recharger la table a chaque minute.
    good = rc == 0 and ("-150" in out or "mangle" in out) and "dstnat" not in out
    if not good:
        nft(["delete", "table", "inet", "slowdns"])
        r2, _, e2 = nft(["-f", nf])
        log("recharge slowdns prio -150 rc=%d %s" % (r2, e2.strip()[:80]))

def main():
    if not installed(): return
    ensure_catchall()
    ensure_slowdns_prio()
    sh("systemctl disable --now nftables-nat.service >/dev/null 2>&1 || true")
    n = 0
    for (t, c, h) in collect():
        if h and t[0] in ("ip", "ip6") and t not in KEEP_TABLES:
            r = nft(["-a", "delete", "rule", t[0], t[1], c, "handle", h])
            if r[0] == 0:
                n += 1; log("supprime dnat 36712 dupl. %s/%s" % (t[1], c))
    if n: log("dedup: %d regles supprimees" % n)
    else: log("dedup: ok (aucun doublon)")

if __name__ == "__main__":
    main()
'''
    try:
        Path(WATCHDOG).write_text(src)
        sh(f"chmod +x {WATCHDOG}")
        # cron toutes les minutes + au reboot
        sh("systemctl disable --now nftables-nat.service 2>/dev/null || true")
        crontab = sh("crontab -l 2>/dev/null")
        if "kighmu-nft-dedup" not in crontab:
            sh(f"(crontab -l 2>/dev/null | grep -v kighmu-nft-dedup; echo '* * * * * {WATCHDOG} >/dev/null 2>&1'; echo '@reboot {WATCHDOG} >/dev/null 2>&1') | crontab - 2>/dev/null || true")
    except Exception as e:
        print(f" {C['RED']}✗ echec deploiement watchdog dedup : {e}{C['RST']}")

def install_openssh():
    sh("apt-get install -y -qq openssh-server 2>/dev/null || true")
    sh("systemctl enable ssh 2>/dev/null || true; systemctl restart ssh 2>/dev/null || true")
    for line in ["PermitTunnel yes", "AllowTcpForwarding yes", "MaxSessions 1000", "MaxStartups 10000:30:10000"]:
        key = line.split()[0]
        sh(f"sed -i 's/^#{key}.*/{line}/' /etc/ssh/sshd_config 2>/dev/null || echo '{line}' >> /etc/ssh/sshd_config")
    sh("systemctl restart ssh 2>/dev/null || true")

def install_ssh_stack():
    _install_ssh_banner_shell()
    install_openssh()
    install_dropbear()
    _ssh_quota_apply()

def install_ws_stack():
    install_sshws()
    install_ssl_tls()

def uninstall_ws_stack():
    uninstall_sshws()
    uninstall_ssl_tls()

def install_udp_stack():
    install_badvpn()
    install_udp_custom()

def uninstall_udp_stack():
    uninstall_badvpn()
    uninstall_udp_custom()

def install_dropbear():
    if sh("command -v /usr/local/sbin/dropbear 2>/dev/null") != "" and Path("/etc/systemd/system/dropbear-custom.service").exists(): return
    sh("apt-get install -y -qq build-essential bzip2 zlib1g-dev wget tar 2>/dev/null")
    sh("cd /usr/local/src && wget -q 'https://matt.ucc.asn.au/dropbear/releases/dropbear-2022.83.tar.bz2' -O dropbear-2022.83.tar.bz2 2>/dev/null")
    sh("cd /usr/local/src && tar -xjf dropbear-2022.83.tar.bz2 2>/dev/null && cd dropbear-2022.83 && ./configure --prefix=/usr/local >/dev/null 2>&1 && make -j$(nproc) >/dev/null 2>&1 && make install >/dev/null 2>&1")
    Path("/etc/dropbear").mkdir(parents=True, exist_ok=True)
    for key in ["rsa","ecdsa","ed25519"]: sh(f"/usr/local/bin/dropbearkey -t {key} -f /etc/dropbear/dropbear_{key}_host_key >/dev/null 2>&1 || true")
    dropbear_cfg = """Ciphers aes128-ctr,aes256-ctr,aes128-gcm@openssh.com,aes256-gcm@openssh.com,chacha20-poly1305@openssh.com
Macs hmac-sha2-256,hmac-sha2-512,hmac-sha1
KexAlgorithms curve25519-sha256,diffie-hellman-group14-sha256,diffie-hellman-group16-sha512,ecdh-sha2-nistp256,ecdh-sha2-nistp384,ecdh-sha2-nistp521
HostKeyAlgorithms ssh-ed25519,ssh-rsa,ecdsa-sha2-nistp256
"""
    Path("/etc/dropbear/config").write_text(dropbear_cfg)
    svc = """[Unit]
Description=Dropbear Custom (port 109)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0
StartLimitBurst=0
[Service]
Type=simple
ExecStart=/usr/local/sbin/dropbear -F -E -p 109 -R
Restart=always
RestartSec=2
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
"""
    Path("/etc/systemd/system/dropbear-custom.service").write_text(svc)
    sh("systemctl daemon-reload && systemctl enable --now dropbear-custom.service 2>/dev/null || true")
    _deploy_nft("dropbear", 'table inet dropbear { chain input { type filter hook input priority 0; policy accept; tcp dport 109 accept; }; }')
    if sh("systemctl is-active dropbear-custom.service 2>/dev/null")=="active":
        print(f" {C['GREEN']}✔ Dropbear installé et actif (port 109).{C['RST']}")
    else:
        print(f" {C['RED']}✗ Dropbear: échec démarrage.{C['RST']}")
        sh("journalctl -u dropbear-custom.service -n 20 --no-pager")

def uninstall_dropbear():
    sh("systemctl disable --now dropbear-custom.service 2>/dev/null || true")
    for f in ["/etc/systemd/system/dropbear-custom.service"]: Path(f).unlink(missing_ok=True)
    sh("rm -rf /etc/dropbear /usr/local/sbin/dropbear /usr/local/bin/dropbear* 2>/dev/null || true")
    _remove_nft("dropbear"); sh("systemctl daemon-reload 2>/dev/null || true")
    print(f" {C['GREEN']}✔ Dropbear désinstallé.{C['RST']}")

def _ensure_domain():
    df = Path("/etc/kighmu/domain.txt")
    if not df.parent.exists(): df.parent.mkdir(parents=True)
    cur = df.read_text().strip() if df.exists() else ""
    if not cur:
        print(f"\n {C['YELLOW']}⚠ No domain configured yet.{C['RST']}")
        dom = input(f" {C['YELLOW']}►{C['RST']} {C['WHITE']}Enter domain (e.g. vpn.example.com): {C['RST']}").strip()
        while not dom: dom = input(f" {C['RED']}✗{C['RST']} Domain required: ").strip()
        df.write_text(dom + "\n")
        print(f" {C['GREEN']}✔ Domain saved: {dom}{C['RST']}\n")
        return dom
    return cur

def _force_domain():
    df = Path("/etc/kighmu/domain.txt")
    if not df.parent.exists(): df.parent.mkdir(parents=True)
    cur = df.read_text().strip() if df.exists() else ""
    if cur:
        return cur
    print(f"\n {C['YELLOW']}╔═══ CONFIGURATION DOMAINE POUR XRAY ═══╗{C['RST']}")
    dom = input(f" {C['YELLOW']}►{C['RST']} {C['WHITE']}Domain (e.g. vpn.example.com){C['RST']} [{C['GREEN']}{cur}{C['RST']}]: ").strip() or cur
    while not dom: dom = input(f" {C['RED']}✗{C['RST']} Domain required: ").strip()
    df.write_text(dom + "\n")
    print(f" {C['GREEN']}✔ Domain: {dom}{C['RST']}\n")
    return dom

def install_ssl_tls():
    if sh("command -v ssl_tls 2>/dev/null") != "" and Path("/etc/systemd/system/ssl_tls.service").exists():
        print(f" {C['GREEN']}✔ SSL/TLS déjà installé.{C['RST']}");return
    sh("apt-get install -y -qq curl file 2>/dev/null")
    r=sh("curl -fsSL 'https://github.com/kinf744/Kighmu/releases/download/v1.0.0/ssl_tls' -o /usr/local/bin/ssl_tls 2>/dev/null && chmod +x /usr/local/bin/ssl_tls 2>/dev/null && echo OK")
    if "OK" not in r: print(f" {C['RED']}✗ Échec téléchargement ssl_tls.{C['RST']}");return
    if "ELF" not in sh("file /usr/local/bin/ssl_tls 2>/dev/null"):
        print(f" {C['RED']}✗ Binaire ssl_tls invalide (pas un ELF).{C['RST']}");return
    if subprocess.run(["/usr/local/bin/ssl_tls", "--help"], capture_output=True, timeout=5).returncode != 0:
        print(f" {C['RED']}✗ Binaire ssl_tls ne s'exécute pas.{C['RST']}");return
    svc = """[Unit]
Description=Tunnel SSL/TLS (ssl_tls)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0
StartLimitBurst=0
[Service]
Type=simple
ExecStart=/usr/local/bin/ssl_tls -listen 444 -target-host 127.0.0.1 -target-port 1092
Restart=always
RestartSec=2
LimitNOFILE=1048576
StandardOutput=journal
StandardError=journal
[Install]
WantedBy=multi-user.target
"""
    Path("/etc/systemd/system/ssl_tls.service").write_text(svc)
    sh("systemctl daemon-reload 2>/dev/null || true")
    sh("systemctl enable --now ssl_tls.service 2>/dev/null || true")
    sh("systemctl reset-failed ssl_tls.service 2>/dev/null || true")
    _deploy_nft("ssl_tls", 'table inet ssl_tls { chain input { type filter hook input priority 0; policy accept; tcp dport 444 accept; }; chain output { type filter hook output priority 0; policy accept; tcp sport 444 accept; }; }')
    if sh("systemctl is-active ssl_tls.service 2>/dev/null")=="active":
        print(f" {C['GREEN']}✔ SSL/TLS installé et actif.{C['RST']}")
    else: print(f" {C['RED']}✗ SSL/TLS: échec démarrage.{C['RST']}")

def uninstall_ssl_tls():
    sh("systemctl stop ssl_tls.service 2>/dev/null || true")
    sh("systemctl disable ssl_tls.service 2>/dev/null || true")
    Path("/etc/systemd/system/ssl_tls.service").unlink(missing_ok=True)
    sh("rm -f /usr/local/bin/ssl_tls 2>/dev/null || true")
    _remove_nft("ssl_tls")
    sh("systemctl daemon-reload 2>/dev/null || true")
    sh("systemctl reset-failed ssl_tls.service 2>/dev/null || true")
    print(f" {C['GREEN']}✔ SSL/TLS désinstallé.{C['RST']}")

def install_sshws():
    if sh("command -v sshws 2>/dev/null") != "" and Path("/etc/systemd/system/sshws.service").exists():
        print(f" {C['GREEN']}✔ SSHWS déjà installé.{C['RST']}");return
    sh("apt-get install -y -qq curl python3-websockets 2>/dev/null || true")
    if sh("python3 -c 'import websockets' 2>/dev/null && echo OK") != "OK":
        sh("pip3 install websockets --quiet --break-system-packages 2>/dev/null || true")
    r=sh("curl -fsSL 'https://github.com/kinf744/Kighmu/releases/download/v1.0.0/sshws' -o /usr/local/bin/sshws 2>/dev/null && chmod +x /usr/local/bin/sshws 2>/dev/null && echo OK")
    if "OK" not in r: print(f" {C['RED']}✗ Échec téléchargement sshws.{C['RST']}");return
    if "ELF" not in sh("file /usr/local/bin/sshws 2>/dev/null"):
        print(f" {C['RED']}✗ Binaire sshws invalide (pas un ELF).{C['RST']}");return
    r=sh("curl -fsSL 'https://github.com/kinf744/Kighmu/releases/download/v1.0.0/sshws.sha256' -o /tmp/sshws.sha256 2>/dev/null && sha256sum -c /tmp/sshws.sha256 2>/dev/null && echo OK")
    if "OK" not in r: print(f" {C['YELLOW']}⚠ Vérification SHA-256 sshws non disponible (skip).{C['RST']}")
    svc = """[Unit]
Description=SSHWS Slipstream Tunnel
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0
StartLimitBurst=0
[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/sshws -listen 80 -target-host 127.0.0.1 -target-port 1092
Restart=always
RestartSec=2
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
"""
    svc_path = Path("/etc/systemd/system/sshws.service")
    if not svc_path.exists():
        svc_path.write_text(svc)
        sh("systemctl daemon-reload 2>/dev/null || true")
        sh("systemctl enable --now sshws.service 2>/dev/null || true")
    else:
        print(f" {C['YELLOW']}⚠ Service systemd sshws déjà existant.{C['RST']}")
    sh("systemctl reset-failed sshws.service 2>/dev/null || true")
    _deploy_nft("sshws", 'table inet sshws { chain input { type filter hook input priority 0; policy accept; tcp dport 80 accept; }; }')
    _install_ws_proxies()
    if sh("systemctl is-active sshws.service 2>/dev/null")=="active":
        print(f" {C['GREEN']}✔ SSHWS installé et actif.{C['RST']}")
    else: print(f" {C['RED']}✗ SSHWS: échec démarrage.{C['RST']}")

def _install_ws_proxies():
    for name, listen_port, target in [("ws-dropbear", 2095, ("127.0.0.1", 1092)), ("ws-stunnel", 700, ("127.0.0.1", 444))]:
        svc_name = f"{name}.service"
        script = Path(f"/usr/local/bin/{name}.py")
        script.parent.mkdir(parents=True, exist_ok=True)
        ws_py = f'''#!/usr/bin/env python3
import asyncio, websockets, sys
LISTEN = "{listen_port}"
TARGET_HOST = "{target[0]}"
TARGET_PORT = {target[1]}
async def proxy(ws):
    writer = None
    try:
        try:
            reader, writer = await asyncio.open_connection(TARGET_HOST, TARGET_PORT)
        except Exception:
            await asyncio.sleep(2)
            raise
        async def fwd_rx():
            try:
                while True:
                    data = await ws.recv()
                    if isinstance(data, str): data = data.encode()
                    writer.write(data)
                    await writer.drain()
            except: pass
        async def fwd_tx():
            try:
                while True:
                    data = await reader.read(4096)
                    if not data: break
                    await ws.send(data)
            except: pass
        await asyncio.gather(fwd_rx(), fwd_tx())
    except: pass
    finally:
        try: writer.close()
        except: pass
async def main():
    async with websockets.serve(proxy, "0.0.0.0", LISTEN, max_size=2**24):
        await asyncio.Future()
asyncio.run(main())
'''
        script.write_text(ws_py)
        script.chmod(0o755)
        svc_unit = f"""[Unit]
Description={name} WS Proxy
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0
StartLimitBurst=0
[Service]
Type=simple
ExecStart=/usr/bin/python3 {script}
Restart=always
RestartSec=3
LimitNOFILE=1048576
KillMode=mixed
[Install]
WantedBy=multi-user.target
"""
        Path(f"/etc/systemd/system/{svc_name}").write_text(svc_unit)
        sh(f"systemctl daemon-reload 2>/dev/null; systemctl enable --now {svc_name} 2>/dev/null || true")
        _deploy_nft(name, f'table inet {name} {{ chain input {{ type filter hook input priority 0; policy accept; tcp dport {listen_port} accept; }}; }}')

def uninstall_sshws():
    sh("systemctl stop sshws.service 2>/dev/null || true")
    sh("systemctl disable sshws.service 2>/dev/null || true")
    Path("/etc/systemd/system/sshws.service").unlink(missing_ok=True)
    sh("pkill -9 -f /usr/local/bin/sshws 2>/dev/null || true")
    sh("rm -f /usr/local/bin/sshws 2>/dev/null || true")
    sh("rm -rf /var/log/sshws 2>/dev/null || true")
    _remove_nft("sshws")
    for name in ["ws-dropbear", "ws-stunnel"]:
        sh(f"systemctl stop {name}.service 2>/dev/null || true")
        sh(f"systemctl disable {name}.service 2>/dev/null || true")
        Path(f"/etc/systemd/system/{name}.service").unlink(missing_ok=True)
        Path(f"/usr/local/bin/{name}.py").unlink(missing_ok=True)
        _remove_nft(name)
    sh("systemctl daemon-reload 2>/dev/null || true")
    sh("systemctl reset-failed sshws.service 2>/dev/null || true")
    sh('screen -ls 2>/dev/null | awk \'/sshws/ {print $1}\' | xargs -r -n1 screen -S {} -X quit 2>/dev/null || true')
    print(f" {C['GREEN']}✔ SSHWS désinstallé.{C['RST']}")

_ACME_EMAIL = "adrienkiaje@gmail.com"

def _cert_status(cert_file, domain, min_valid_days=7):
    """Retourne (ok, detail) : vérifie qu'un certificat existant est utilisable
    pour `domain` (domaine OK, non auto-signé, non expiré, clé assortie)."""
    p = Path(cert_file)
    if not p.exists():
        return False, "absent"
    both = sh(f"openssl x509 -in {p} -noout -issuer -subject 2>/dev/null")
    if not both or "subject=" not in both:
        return False, "fichier corrompu"
    subject = [l[8:] for l in both.splitlines() if l.startswith("subject=")]
    issuer = [l[7:] for l in both.splitlines() if l.startswith("issuer=")]
    subj = subject[0] if subject else ""
    if not subj:
        return False, "fichier illisible"
    san = sh(f"openssl x509 -in {p} -noout -ext subjectAltName 2>/dev/null")
    if domain not in subj and f"DNS:{domain}" not in san:
        return False, f"domaine différent ({subj})"
    if issuer and issuer[0] == subj:
        return False, "auto-signé"
    rc = subprocess.run(f"openssl x509 -in {p} -noout -checkend {min_valid_days*86400}", shell=True, capture_output=True).returncode
    if rc != 0:
        exp = sh(f"openssl x509 -in {p} -enddate -noout 2>/dev/null | cut -d= -f2")
        return False, f"expire dans < {min_valid_days}j ({exp})"
    key_file = p.parent / "privkey.pem"
    if not key_file.exists():
        return False, "clé privée absente"
    cp = sh(f"openssl x509 -in {p} -noout -pubkey 2>/dev/null | openssl pkey -pubin -outform der 2>/dev/null | sha256sum | cut -d' ' -f1")
    kp = sh(f"openssl pkey -in {key_file} -pubout -outform der 2>/dev/null | sha256sum | cut -d' ' -f1")
    if not cp or cp != kp:
        return False, "clé privée non assortie"
    exp = sh(f"openssl x509 -in {p} -enddate -noout 2>/dev/null | cut -d= -f2")
    return True, exp

def _acme_cert(domain, cert_dir):
    fullchain = Path(cert_dir) / "fullchain.pem"
    privkey = Path(cert_dir) / "privkey.pem"
    ok, detail = _cert_status(fullchain, domain)
    if ok and privkey.exists():
        print(f" {C['GREEN']}✔ Certificat TLS valide trouvé (expire: {detail}) — réutilisation.{C['RST']}")
        return True
    if detail != "absent":
        print(f" {C['YELLOW']}⚠ Certificat existant inutilisable ({detail}) — émission d'un nouveau.{C['RST']}")
    print(f" {C['YELLOW']}► Génération certificat Let's Encrypt pour {domain}...{C['RST']}")
    Path(cert_dir).mkdir(parents=True, exist_ok=True)
    sh("command -v acme.sh >/dev/null || curl -fsSL https://get.acme.sh | sh 2>/dev/null || true")
    sh("systemctl stop sshws 2>/dev/null || true")
    acme = sh("which acme.sh 2>/dev/null || echo ~/.acme.sh/acme.sh")
    acme = acme.strip() or "/root/.acme.sh/acme.sh"
    cmd = f"{acme} --issue --standalone -d {domain} --keylength ec-256 --server letsencrypt --email {_ACME_EMAIL} --force 2>&1"
    r = sh(cmd, timeout=120)
    if "success" in r.lower():
        reloadcmd = f"cat {fullchain} {privkey} > /etc/xray/xray.pem && cat {fullchain} {privkey} > /etc/haproxy/panel.pem && chmod 600 /etc/xray/xray.pem /etc/haproxy/panel.pem && systemctl reload haproxy"
        sh(f"{acme} --installcert -d {domain} --fullchainpath {fullchain} --keypath {privkey} --reloadcmd '{reloadcmd}' --force 2>/dev/null || true")
    ok, detail = _cert_status(fullchain, domain)
    if ok and privkey.exists():
        print(f" {C['GREEN']}✔ Certificat TLS valide créé (expire: {detail}).{C['RST']}")
        sh("systemctl start sshws 2>/dev/null || true")
        return True
    print(f" {C['RED']}✗ Échec ACME ({detail}) — certificat auto-signé utilisé.{C['RST']}")
    sh("systemctl start sshws 2>/dev/null || true")
    return False

def install_badvpn():
    if sh("command -v badvpn-udpgw 2>/dev/null") != "" and Path("/etc/systemd/system/badvpn-7100.service").exists(): return
    sh("apt-get install -y -qq cmake build-essential git 2>/dev/null")
    sh("cd /tmp && rm -rf badvpn && git clone --depth 1 https://github.com/ambrop72/badvpn.git 2>/dev/null")
    sh("cd /tmp/badvpn && mkdir -p build && cd build && cmake .. -DBUILD_NOTHING_BY_DEFAULT=1 -DBUILD_UDPGW=1 >/dev/null 2>&1 && make -j$(nproc) >/dev/null 2>&1 && cp udpgw/badvpn-udpgw /usr/local/bin/ && chmod +x /usr/local/bin/badvpn-udpgw")
    for port in ["7100","7200","7300"]:
        Path(f"/etc/systemd/system/badvpn-{port}.service").write_text(f"""[Unit]
Description=BadVPN UDPGW {port}
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0
StartLimitBurst=0
[Service]
Type=simple
ExecStart=/usr/local/bin/badvpn-udpgw --listen-addr 0.0.0.0:{port} --max-clients 999
Restart=always
RestartSec=2
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
""")
    sh("systemctl daemon-reload 2>/dev/null || true")
    for port in ["7100","7200","7300"]: sh(f"systemctl enable --now badvpn-{port}.service 2>/dev/null || true")
    _deploy_nft("badvpn", 'table inet badvpn { chain input { type filter hook input priority 0; policy accept; udp dport {7100,7200,7300} accept; }; }')
    print(f" {C['GREEN']}✔ BadVPN installé (UDP 7100,7200,7300).{C['RST']}")

def uninstall_badvpn():
    for port in ["7100","7200","7300"]: sh(f"systemctl disable --now badvpn-{port}.service 2>/dev/null || true")
    for port in ["7100","7200","7300"]: Path(f"/etc/systemd/system/badvpn-{port}.service").unlink(missing_ok=True)
    sh("rm -f /usr/local/bin/badvpn-udpgw 2>/dev/null || true"); _remove_nft("badvpn"); sh("systemctl daemon-reload 2>/dev/null || true")
    print(f" {C['GREEN']}✔ BadVPN désinstallé.{C['RST']}")

def install_udp_custom():
    if sh("command -v udp-custom 2>/dev/null") != "" and Path("/etc/systemd/system/udp-custom.service").exists():
        print(f" {C['GREEN']}✔ UDP-Custom déjà installé.{C['RST']}");return
    sh("apt-get install -y -qq curl 2>/dev/null")
    r=sh("curl -fsSL 'https://github.com/kinf744/Kighmu/releases/download/v1.0.0/udp-custom' -o /usr/local/bin/udp-custom 2>/dev/null && chmod +x /usr/local/bin/udp-custom 2>/dev/null && echo OK")
    if "OK" not in r: print(f" {C['RED']}✗ Échec téléchargement udp-custom.{C['RST']}");return
    Path("/etc/udp-custom").mkdir(parents=True, exist_ok=True)
    Path("/etc/udp-custom/config.json").write_text('{"listen":":36712","exclude_port":[53,5300],"timeout":600,"auth":{"mode":"passwords","config":[]}}')
    Path("/etc/udp-custom/users.list").touch()
    Path("/etc/udp-custom/users.list").chmod(0o600)
    svc = """[Unit]
Description=UDP Custom
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0
StartLimitBurst=0
[Service]
Type=simple
ExecStart=/usr/local/bin/udp-custom server -c /etc/udp-custom/config.json
Restart=always
RestartSec=5
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
"""
    Path("/etc/systemd/system/udp-custom.service").write_text(svc)
    sh("systemctl daemon-reload && systemctl enable --now udp-custom.service 2>/dev/null || true")
    iface = get_main_iface()
    _deploy_nft("udp-custom", f'table inet udp-custom {{ chain input {{ type filter hook input priority 0; policy accept; udp dport 36712 accept; }}; chain prerouting {{ type nat hook prerouting priority -100; iifname "{iface}" udp dport {{ 53, 5300 }} return; iifname "{iface}" udp dport 2900-5600 dnat to :36712; }}; }}')
    if sh("systemctl is-active udp-custom.service 2>/dev/null")=="active":
        IP = sh("hostname -I | awk '{print $1}'")
        print(f" {C['GREEN']}✔ UDP-Custom installé et actif sur {IP}:36712{C['RST']}")
        print(f" {C['YELLOW']}⚠ Auth activée — ajoutez des utilisateurs via le menu SSH{C['RST']}")
    else:
        print(f" {C['RED']}✗ UDP-Custom: échec démarrage.{C['RST']}")
        sh("journalctl -u udp-custom.service -n 20 --no-pager")

def uninstall_udp_custom():
    sh("systemctl disable --now udp-custom.service 2>/dev/null || true")
    Path("/etc/systemd/system/udp-custom.service").unlink(missing_ok=True)
    sh("rm -f /usr/local/bin/udp-custom 2>/dev/null; rm -rf /etc/udp-custom 2>/dev/null || true")
    _remove_nft("udp-custom")
    # nettoyage watchdog dedup + catchall (aucun tunnel UDP-Custom restant)
    _remove_nft("udp-custom-catchall")
    sh("rm -f /usr/local/bin/kighmu-nft-dedup.py /var/log/kighmu-nft-dedup.log 2>/dev/null || true")
    sh("(crontab -l 2>/dev/null | grep -v kighmu-nft-dedup) | crontab - 2>/dev/null || true")
    # restaure le service kighmu (nftables-nat) desactive par le watchdog
    sh("systemctl enable nftables-nat.service >/dev/null 2>&1 || true")
    sh("systemctl daemon-reload 2>/dev/null || true")
    print(f" {C['GREEN']}✔ UDP-Custom désinstallé.{C['RST']}")

def _ask_slowdns_mtu():
    mtu_file = Path("/etc/slowdns/mtu")
    cur = mtu_file.read_text().strip() if mtu_file.exists() else "512"
    print(f"\n {C['YELLOW']}⚠ MTU du tunnel SlowDNS (recommandé: 512, 1200, 1400).{C['RST']}")
    m = input(f" {C['YELLOW']}►{C['RST']} {C['WHITE']}MTU (def {cur}): {C['RST']}").strip()
    if not m.isdigit() or int(m) < 100:
        m = cur if cur.isdigit() else "512"
    return m

def install_slowdns():
    if sh("command -v dnstt-server 2>/dev/null") != "" and Path("/etc/systemd/system/dnsdist.service").exists() and Path("/etc/systemd/system/slowdns-ns4.service").exists(): return
    sh("systemctl disable --now slowdns-router 2>/dev/null || true")
    sh("rm -f /usr/local/bin/slowdns-router /etc/systemd/system/slowdns-router.service 2>/dev/null || true")
    sh("apt-get install -y -qq curl jq wget dnsdist nftables 2>/dev/null")
    DIR = Path("/etc/slowdns")
    DIR.mkdir(parents=True, exist_ok=True)
    (DIR / "ns4").mkdir(parents=True, exist_ok=True)
    (DIR / "nv4").mkdir(parents=True, exist_ok=True)
    DNSTT_PRIV = "4ab3af05fc004cb69d50c89de2cd5d138be1c397a55788b8867088e801f7fcaa"
    DNSTT_PUB = "2cb39d63928451bd67f5954ffa5ac16c8d903562a10c4b21756de4f1a82d581c"
    (DIR / "server.key").write_text(DNSTT_PRIV + "\n")
    (DIR / "server.pub").write_text(DNSTT_PUB + "\n")
    sh("chmod 600 /etc/slowdns/server.key 2>/dev/null || true")
    tmp = sh("mktemp 2>/dev/null") or "/tmp/dnstt-server"
    if sh("command -v dnstt-server 2>/dev/null") != "":
        print(f" {C['GREEN']}✔ dnstt-server déjà présent.{C['RST']}")
    else:
        r = sh(f"curl -fsSL 'https://dnstt-server-client.s3.amazonaws.com/dnstt-server-linux-amd64' -o {tmp} 2>/dev/null && stat -c%s {tmp} 2>/dev/null")
        try: size = int(r)
        except: size = 0
        if size < 1048576:
            print(f" {C['RED']}✗ Binaire dnstt-server corrompu ({size} octets).{C['RST']}")
            sh(f"rm -f {tmp} 2>/dev/null || true")
        else:
            sh(f"mv {tmp} /usr/local/bin/dnstt-server && chmod +x /usr/local/bin/dnstt-server")
    domain = _ensure_domain() or get_ip()
    ns4 = sh("head -1 /etc/slowdns/ns.conf 2>/dev/null")
    nv4 = sh("head -1 /etc/slowdns/nv4/ns.conf 2>/dev/null")
    if not ns4:
        print(f"\n {C['YELLOW']}⚠ NS4 subdomain not configured.{C['RST']}")
        default_ns4 = "ns4." + ".".join(domain.split(".")[-2:]) if len(domain.split(".")) > 2 else "ns4." + domain
        ns4 = input(f" {C['YELLOW']}►{C['RST']} {C['WHITE']}NS4 subdomain (e.g. {default_ns4}): {C['RST']}").strip() or default_ns4
    if not nv4:
        print(f"\n {C['YELLOW']}⚠ NV4 subdomain not configured.{C['RST']}")
        default_nv4 = "nv4." + ".".join(domain.split(".")[-2:]) if len(domain.split(".")) > 2 else "nv4." + domain
        nv4 = input(f" {C['YELLOW']}►{C['RST']} {C['WHITE']}NV4 subdomain (e.g. {default_nv4}): {C['RST']}").strip() or default_nv4
    (DIR / "ns.conf").write_text(ns4 + "\n")
    (DIR / "nv4/ns.conf").write_text(nv4 + "\n")
    print(f" {C['GREEN']}✔ SlowDNS config: NS4={ns4}, NV4={nv4}{C['RST']}")
    mtu = _ask_slowdns_mtu()
    Path(DIR / "install.env").write_text("MODE=man\nNS4=%s\nNV4=%s\nMTU=%s\n" % (ns4, nv4, mtu))
    (DIR / "mtu").write_text(str(mtu) + "\n")

    PORT1 = 5353; PORT2 = 5354
    DNSDIST_PORT = 5300
    _ensure_ssh_lb_haproxy()
    n4s = f"#!/bin/bash\nNS=$(cat /etc/slowdns/ns.conf)\nexec /usr/local/bin/dnstt-server -udp 0.0.0.0:{PORT1} -mtu {mtu} -privkey-file /etc/slowdns/server.key $NS 127.0.0.1:1092\n"
    nv4s = f"#!/bin/bash\nNV4=$(cat /etc/slowdns/nv4/ns.conf)\nexec /usr/local/bin/dnstt-server -udp 0.0.0.0:{PORT2} -mtu {mtu} -privkey-file /etc/slowdns/server.key $NV4 127.0.0.1:5401\n"
    Path("/usr/local/bin/slowdns-ns4-start.sh").write_text(n4s)
    Path("/usr/local/bin/slowdns-nv4-start.sh").write_text(nv4s)
    for f in ["/usr/local/bin/slowdns-ns4-start.sh","/usr/local/bin/slowdns-nv4-start.sh"]: Path(f).chmod(0o755)
    for svc_name in ["slowdns-ns4","slowdns-nv4"]:
        logfile = f"/var/log/slowdns/{svc_name}.log"
        svc = f"""[Unit]
Description=SlowDNS DNSTT {svc_name}
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0
StartLimitBurst=0
[Service]
ExecStartPre=/bin/sleep 5
ExecStart=/usr/local/bin/{svc_name}-start.sh
Restart=always
RestartSec=5
LimitNOFILE=1048576
KillMode=process
KillSignal=SIGTERM
TimeoutStopSec=10
StandardOutput=append:{logfile}
StandardError=append:{logfile}
[Install]
WantedBy=multi-user.target
"""
        Path(f"/etc/systemd/system/{svc_name}.service").write_text(svc)
        sh(f"systemctl daemon-reload 2>/dev/null || true")
        sh(f"systemctl enable --now {svc_name}.service 2>/dev/null || true")

    sh("systemctl stop dnsdist 2>/dev/null || true")
    Path("/etc/systemd/system/dnsdist.service.d").mkdir(parents=True, exist_ok=True)
    Path("/etc/systemd/system/dnsdist.service.d/restart.conf").write_text("""[Unit]
StartLimitIntervalSec=0
StartLimitBurst=0
[Service]
Restart=always
RestartSec=5
""")
    dnsdist_conf = f"""setSecurityPollSuffix("")
setACL({{"0.0.0.0/0", "::/0"}})
addLocal("0.0.0.0:{DNSDIST_PORT}")
newServer({{address="127.0.0.1:{PORT1}", pool="ns4"}})
newServer({{address="127.0.0.1:{PORT2}", pool="nv4"}})
addAction(makeRule("{ns4}."), PoolAction("ns4"))
addAction(makeRule("{nv4}."), PoolAction("nv4"))
addAction(AllRule(), RCodeAction(5))
"""
    Path("/etc/dnsdist/dnsdist.conf").write_text(dnsdist_conf)
    Path("/var/log/slowdns").mkdir(parents=True, exist_ok=True)

    _deploy_nft("slowdns", f"""table inet slowdns {{
    chain prerouting {{
        type nat hook prerouting priority -150;
        udp dport 53 redirect to :{DNSDIST_PORT}
        tcp dport 53 redirect to :{DNSDIST_PORT}
    }}
    chain output {{
        type nat hook output priority -150;
        udp dport 53 fib daddr type local redirect to :{DNSDIST_PORT}
        tcp dport 53 fib daddr type local redirect to :{DNSDIST_PORT}
    }}
    chain input {{
        type filter hook input priority 0; policy accept;
        udp dport 53 accept
        udp dport {DNSDIST_PORT} accept
        udp dport {PORT1} accept
        udp dport {PORT2} accept
        tcp dport 109 accept
        tcp dport 5401 accept
    }}
}}""")
    sh("systemctl daemon-reload 2>/dev/null || true")
    sh("systemctl enable dnsdist 2>/dev/null || true")
    for s in ["dnsdist","slowdns-ns4","slowdns-nv4"]:
        sh(f"systemctl restart {s}.service 2>/dev/null || true")
        time.sleep(1)
    sh("chattr -i /etc/resolv.conf 2>/dev/null || true")
    Path("/etc/resolv.conf").write_text("nameserver 1.1.1.1\nnameserver 8.8.8.8\n")
    sh("chattr +i /etc/resolv.conf 2>/dev/null || true")

    watchdog = """#!/bin/bash
LOG=/var/log/slowdns/watchdog.log
ts() { date '+%Y-%m-%d %H:%M:%S'; }
for svc in dnsdist slowdns-ns4 slowdns-nv4; do
  systemctl is-active --quiet "$svc" || { systemctl restart "$svc"; echo "[$(ts)] $svc redemarre" >> "$LOG"; }
done
"""
    Path("/usr/local/bin/slowdns-watchdog.sh").write_text(watchdog)
    Path("/usr/local/bin/slowdns-watchdog.sh").chmod(0o755)
    crontab = sh("crontab -l 2>/dev/null")
    if "slowdns-watchdog" not in crontab:
        sh("(crontab -l 2>/dev/null | grep -v slowdns-watchdog; echo '*/15 * * * * /usr/local/bin/slowdns-watchdog.sh') | crontab - 2>/dev/null || true")

    Path("/etc/logrotate.d/slowdns").write_text("""/var/log/slowdns/*.log {
    daily
    rotate 7
    compress
    missingok
    notifempty
    copytruncate
}
""")

    print(f" {C['GREEN']}✔ SlowDNS installé (53→{DNSDIST_PORT} via dnsfast).{C['RST']}")

def configure_slowdns():
    DIR = Path("/etc/slowdns")
    DNSDIST_CONF = Path("/etc/dnsdist/dnsdist.conf")
    if not DIR.exists(): return
    ns4_cur = (DIR / "ns.conf").read_text().strip() if (DIR / "ns.conf").exists() else "non défini"
    nv4_cur = (DIR / "nv4/ns.conf").read_text().strip() if (DIR / "nv4/ns.conf").exists() else "non défini"
    mtu_cur = (DIR / "mtu").read_text().strip() if (DIR / "mtu").exists() else "512"
    print(f"NS4 actuel: {ns4_cur}")
    print(f"NV4 actuel: {nv4_cur}")
    print(f"MTU actuel: {mtu_cur}")
    new_ns4 = input("Nouveau NS4 (vide = inchangé): ").strip()
    new_nv4 = input("Nouveau NV4 (vide = inchangé): ").strip()
    new_mtu = input(f"Nouveau MTU (vide = inchangé, recommandé 512/1200/1400): ").strip()
    mtu_changed = bool(new_mtu and new_mtu.isdigit() and int(new_mtu) >= 100 and new_mtu != mtu_cur)
    if mtu_changed:
        mtu_cur = new_mtu
        (DIR / "mtu").write_text(mtu_cur + "\n")
    if new_ns4 and new_ns4 != ns4_cur:
        (DIR / "ns.conf").write_text(new_ns4 + "\n")
        n4s = f"#!/bin/bash\nNS=$(cat {DIR}/ns.conf)\nexec /usr/local/bin/dnstt-server -udp :5353 -mtu {mtu_cur} -privkey-file {DIR}/server.key $NS 127.0.0.1:109\n"
        Path("/usr/local/bin/slowdns-ns4-start.sh").write_text(n4s)
        Path("/usr/local/bin/slowdns-ns4-start.sh").chmod(0o755)
        sh("systemctl restart slowdns-ns4 2>/dev/null || true")
        print(f"NS4 mis à jour: {new_ns4}")
    if new_nv4 and new_nv4 != nv4_cur:
        (DIR / "nv4/ns.conf").write_text(new_nv4 + "\n")
        nv4s = f"#!/bin/bash\nNV4=$(cat {DIR}/nv4/ns.conf)\nexec /usr/local/bin/dnstt-server -udp :5354 -mtu {mtu_cur} -privkey-file {DIR}/server.key $NV4 127.0.0.1:5401\n"
        Path("/usr/local/bin/slowdns-nv4-start.sh").write_text(nv4s)
        Path("/usr/local/bin/slowdns-nv4-start.sh").chmod(0o755)
        sh("systemctl restart slowdns-nv4 2>/dev/null || true")
        print(f"NV4 mis à jour: {new_nv4}")
    if mtu_changed:
        n4s = f"#!/bin/bash\nNS=$(cat {DIR}/ns.conf)\nexec /usr/local/bin/dnstt-server -udp :5353 -mtu {mtu_cur} -privkey-file {DIR}/server.key $NS 127.0.0.1:109\n"
        nv4s = f"#!/bin/bash\nNV4=$(cat {DIR}/nv4/ns.conf)\nexec /usr/local/bin/dnstt-server -udp :5354 -mtu {mtu_cur} -privkey-file {DIR}/server.key $NV4 127.0.0.1:5401\n"
        Path("/usr/local/bin/slowdns-ns4-start.sh").write_text(n4s)
        Path("/usr/local/bin/slowdns-nv4-start.sh").write_text(nv4s)
        for f in ["/usr/local/bin/slowdns-ns4-start.sh","/usr/local/bin/slowdns-nv4-start.sh"]: Path(f).chmod(0o755)
        sh("systemctl restart slowdns-ns4 2>/dev/null || true")
        sh("systemctl restart slowdns-nv4 2>/dev/null || true")
        print(f"MTU mis à jour: {mtu_cur}")
    if new_ns4 or new_nv4:
        ns4 = (DIR / "ns.conf").read_text().strip() if (DIR / "ns.conf").exists() else ns4_cur
        nv4 = (DIR / "nv4/ns.conf").read_text().strip() if (DIR / "nv4/ns.conf").exists() else nv4_cur
        if DNSDIST_CONF.exists():
            dnsdist_conf = f"""setSecurityPollSuffix("")
setACL({{"0.0.0.0/0", "::/0"}})
addLocal("0.0.0.0:5300")
newServer({{address="127.0.0.1:5353", pool="ns4"}})
newServer({{address="127.0.0.1:5354", pool="nv4"}})
addAction(makeRule("{ns4}."), PoolAction("ns4"))
addAction(makeRule("{nv4}."), PoolAction("nv4"))
addAction(AllRule(), RCodeAction(5))
"""
            DNSDIST_CONF.write_text(dnsdist_conf)
            sh("systemctl restart dnsdist 2>/dev/null || true")
            print("dnsdist mit à jour avec les nouveaux NS")

def uninstall_slowdns():
    for s in ["slowdns-ns4","slowdns-nv4","slowdns-router","dnsdist"]:
        sh(f"systemctl disable --now {s}.service 2>/dev/null || true")
        Path(f"/etc/systemd/system/{s}.service").unlink(missing_ok=True)
    sh("rm -f /usr/local/bin/dnstt-server /usr/local/bin/slowdns-router /usr/local/bin/slowdns-*-start.sh /usr/local/bin/slowdns-watchdog.sh 2>/dev/null || true")
    sh("rm -rf /etc/slowdns /var/log/slowdns /root/Kighmu/slowdns-router /etc/dnsdist 2>/dev/null || true")
    sh("rm -f /etc/dnsdist/dnsdist.conf /etc/logrotate.d/slowdns /etc/sysctl.d/99-slowdns.conf 2>/dev/null || true")
    sh("rm -rf /etc/systemd/system/dnsdist.service.d 2>/dev/null || true")
    Path("/etc/logrotate.d/slowdns").unlink(missing_ok=True)
    _remove_nft("slowdns")
    sh("apt-get remove -y -qq dnsdist 2>/dev/null || true")
    sh("chattr -i /etc/resolv.conf 2>/dev/null; systemctl daemon-reload 2>/dev/null || true")
    Path("/etc/resolv.conf").write_text("nameserver 1.1.1.1\nnameserver 8.8.8.8\n")
    sh("chattr +i /etc/resolv.conf 2>/dev/null || true")
    sh("crontab -l 2>/dev/null | grep -v slowdns-watchdog | crontab - 2>/dev/null || true")
    print(f" {C['GREEN']}✔ SlowDNS désinstallé.{C['RST']}")

def xray_gen_config():
    XRAY_CONFIG = Path("/etc/xray/config.json")
    inbounds = [
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
        {"tag":"VLESS-HUpgrade","port":10018,"listen":"127.0.0.1","protocol":"vless","settings":{"clients":[],"decryption":"none"},"streamSettings":{"network":"httpupgrade","security":"none","httpupgradeSettings":{"path":"/vless-hupgrade"}}},
        {"tag":"api","port":10085,"listen":"127.0.0.1","protocol":"dokodemo-door","settings":{"address":"127.0.0.1"}}
    ]
    config = {
        "log": {"loglevel": "warning", "access": "/var/log/xray/access.log", "error": "/var/log/xray/error.log"},
        "inbounds": inbounds,
        "outbounds": [{"tag":"direct","protocol":"freedom","settings":{}}],
        "stats": {},
        "policy": {"levels":{"0":{"statsUserUplink":True,"statsUserDownlink":True}},"system":{"statsInboundUplink":True,"statsInboundDownlink":True}},
        "api": {"tag":"api","services":["HandlerService","StatsService"]},
        "routing": {"rules":[{"type":"field","inboundTag":"api","outboundTag":"api"}]}
    }
    XRAY_CONFIG.write_text(json.dumps(config, indent=2))

SSH_HAPROXY_CFG = """global
    daemon
    maxconn 65535

defaults
    mode tcp
    option dontlognull
    timeout connect 5s
    timeout client 86400s
    timeout server 86400s
    timeout tunnel 86400s
    retries 3

frontend ssh-lb
    bind 127.0.0.1:1092
    default_backend ssh-mixed

backend ssh-mixed
    balance roundrobin
    server dropbear 127.0.0.1:109 check
    server sshd 127.0.0.1:22 check
"""

SSH_HAPROXY_SVC = """[Unit]
Description=HAProxy SSH LB (SlowDNS/SSH tunnels - independent of Xray)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0
StartLimitBurst=0

[Service]
Type=forking
PIDFile=/run/haproxy-ssh.pid
ExecStart=/usr/sbin/haproxy -f /etc/haproxy/ssh-haproxy.cfg -p /run/haproxy-ssh.pid
ExecReload=/usr/sbin/haproxy -f /etc/haproxy/ssh-haproxy.cfg -c -q
ExecReload=/bin/kill -USR2 $MAINPID
KillMode=mixed
Restart=always
RestartSec=3
SuccessExitStatus=143

[Install]
WantedBy=multi-user.target
"""

def _ensure_ssh_lb_haproxy():
    ssh_cfg = Path("/etc/haproxy/ssh-haproxy.cfg")
    if not ssh_cfg.exists() or "ssh-lb" not in ssh_cfg.read_text():
        Path("/etc/haproxy").mkdir(parents=True, exist_ok=True)
        ssh_cfg.write_text(SSH_HAPROXY_CFG)
    Path("/etc/systemd/system/haproxy-ssh.service").write_text(SSH_HAPROXY_SVC)
    sh("systemctl daemon-reload 2>/dev/null || true")
    sh("systemctl enable --now haproxy-ssh 2>/dev/null || true")
    main_cfg = Path("/etc/haproxy/haproxy.cfg")
    if main_cfg.exists() and "ssh-lb" in main_cfg.read_text():
        _strip_ssh_lb(main_cfg)
        sh("systemctl reload haproxy 2>/dev/null || true")

def _strip_ssh_lb(cfg_path):
    try:
        lines = Path(cfg_path).read_text().splitlines()
    except: return
    out = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        if line.strip().startswith(("frontend ssh-lb", "backend ssh-mixed")):
            i += 1
            while i < n and (not lines[i].strip() or lines[i].startswith(("    ", "\t"))):
                i += 1
            continue
        out.append(line)
        i += 1
    txt = "\n".join(out)
    txt = re.sub(r"\n{3,}", "\n\n", txt)
    Path(cfg_path).write_text(txt.strip() + "\n")

def xray_gen_haproxy():
    PEM_DIR = "/etc/xray"
    panel_crt = f"{PEM_DIR}/xray.pem"
    domain = sh("cat /etc/kighmu/domain.txt 2>/dev/null") or "localhost"
    haproxy_cfg = f"""global
    daemon
    maxconn 65535
    tune.ssl.default-dh-param 2048
    ssl-default-bind-ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384
    ssl-default-bind-options no-sslv3 no-tlsv10 no-tlsv11
    ssl-server-verify none

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

frontend xray-ntls
    bind *:8880
    tcp-request inspect-delay 5s
    tcp-request content accept if {{ req.len ge 21 }}
    acl is_h2         req.payload(0,3) -m bin 505249
    acl is_http       req.payload(0,5) -m bin 474554202f
    acl is_post       req.payload(0,4) -m bin 504f5354
    acl is_vless      req.payload(0,1) -m bin 00
    acl is_vmess      req.payload(0,1) -m bin 01
    acl is_vless_ws   req.payload(0,11) -m bin 474554202f766c65737320
    acl is_vmess_ws   req.payload(0,11) -m bin 474554202f766d65737320
    acl is_trojan_ws  req.payload(0,12) -m bin 474554202f74726f6a616e20
    acl is_v2ray_ukj  req.payload(1,16) -m bin f4521f537e4640cfb84986a87f05cadf
    acl is_v2ray_opl  req.payload(1,16) -m bin ee0e0e9c928b40f2a9830299f38ad9b5
    use_backend grpc_router        if is_h2
    use_backend xray-vless-ws      if is_vless_ws
    use_backend xray-vmess-ws      if is_vmess_ws
    use_backend xray-trojan-ws     if is_trojan_ws
    use_backend grpc_router        if is_http or is_post
    use_backend xray-vmess-tcp     if is_vmess
    use_backend xray-trojan-tcp    if !is_vless
    use_backend v2ray-tcp          if is_v2ray_ukj or is_v2ray_opl
    default_backend xray-vless-tcp

frontend xray-tls
    bind *:443 ssl crt {panel_crt} alpn h2,http/1.1
    tcp-request inspect-delay 5s
    tcp-request content accept if {{ req.len ge 21 }}
    acl is_h2         req.payload(0,3) -m bin 505249
    acl is_http       req.payload(0,5) -m bin 474554202f
    acl is_post       req.payload(0,4) -m bin 504f5354
    acl is_vless      req.payload(0,1) -m bin 00
    acl is_vmess      req.payload(0,1) -m bin 01
    acl is_vless_ws   req.payload(0,11) -m bin 474554202f766c65737320
    acl is_vmess_ws   req.payload(0,11) -m bin 474554202f766d65737320
    acl is_trojan_ws  req.payload(0,12) -m bin 474554202f74726f6a616e20
    acl is_v2ray_ukj  req.payload(1,16) -m bin f4521f537e4640cfb84986a87f05cadf
    acl is_v2ray_opl  req.payload(1,16) -m bin ee0e0e9c928b40f2a9830299f38ad9b5
    use_backend grpc_router        if is_h2
    use_backend xray-vless-ws      if is_vless_ws
    use_backend xray-vmess-ws      if is_vmess_ws
    use_backend xray-trojan-ws     if is_trojan_ws
    use_backend grpc_router        if is_http or is_post
    use_backend xray-vmess-tcp     if is_vmess
    use_backend xray-trojan-tcp    if !is_vless
    use_backend v2ray-tcp          if is_v2ray_ukj or is_v2ray_opl
    default_backend xray-vless-tcp

frontend grpc_router
    bind 127.0.0.1:9898
    mode http
    timeout http-request 5s
    use_backend xray-vmess-grpc   if {{ path_beg /vmess-grpc }}
    use_backend xray-vless-grpc   if {{ path_beg /vless-grpc }}
    use_backend xray-trojan-grpc  if {{ path_beg /trojan-grpc }}
    use_backend xray-vmess-grpc   if {{ path_beg /vmess-h2 }}
    use_backend xray-vless-grpc   if {{ path_beg /vless-h2 }}
    use_backend xray-trojan-grpc  if {{ path_beg /trojan-h2 }}
    use_backend xray-vmess-xhttp  if {{ path_beg /vmess-xhttp }}
    use_backend xray-vless-xhttp  if {{ path_beg /vless-xhttp }}
    use_backend xray-trojan-xhttp if {{ path_beg /trojan-xhttp }}
    use_backend xray-vless-hupgrade  if {{ path_beg /vless-hupgrade }}
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
backend v2ray-tcp
    server s1 127.0.0.1:5401
"""
    Path("/etc/haproxy/haproxy.cfg").write_text(haproxy_cfg)
    _ensure_ssh_lb_haproxy()

def xray_build_config():
    XRAY_CONFIG = Path("/etc/xray/config.json")
    if not XRAY_CONFIG.exists(): return
    try:
        XRAY_USERS.parent.mkdir(parents=True, exist_ok=True)
        today = date.today().isoformat()
        fresh = {"vmess": [], "vless": [], "trojan": [], "shadow": []}
        if USERDIR.exists():
            for f in USERDIR.iterdir():
                if not f.is_file(): continue
                p = _meta_get(f.name, "proto")
                if p not in ("vmess", "vless", "trojan"): continue
                exp = _meta_get(f.name, "exp")
                if exp and exp < today: continue
                if is_locked(f.name): continue
                q = float(_meta_get(f.name, "quota") or "0")
                if p in ("vmess","vless"):
                    uuid = _meta_get(f.name, "uuid")
                    if not uuid: continue
                    fresh[p].append({"id": uuid, "email": f.name, "level": 0, "expire": exp, "quota": q})
                elif p == "trojan":
                    pw = _meta_get(f.name, "pass")
                    if not pw: continue
                    fresh["trojan"].append({"password": pw, "email": f.name, "level": 0, "expire": exp, "quota": q})
        XRAY_USERS.write_text(json.dumps(fresh, indent=2))
        users = fresh
        config = json.loads(XRAY_CONFIG.read_text())
        tag_map = {
            "VMess-TCP":"vmess","VMess-WS":"vmess","VMess-TLS":"vmess","VMess-WSS":"vmess","VMess-XHTTP":"vmess","VMess-gRPC":"vmess",
            "VLESS-TCP":"vless","VLESS-WS":"vless","VLESS-TLS":"vless","VLESS-WSS":"vless","VLESS-XHTTP":"vless","VLESS-gRPC":"vless","VLESS-HUpgrade":"vless",
            "Trojan-TCP":"trojan","Trojan-WS":"trojan","Trojan-XHTTP":"trojan","Trojan-gRPC":"trojan",
            "Shadowsocks":"shadow"
        }
        for inbound in config.get("inbounds", []):
            tag = inbound.get("tag","")
            p = tag_map.get(tag)
            if not p:
                continue
            ulist = users.get(p, [])
            if not ulist:
                inbound["settings"]["clients"] = []
                continue
            if p == "shadow" and "method" in ulist[0]:
                inbound["settings"] = {"method":ulist[0]["method"],"password":ulist[0]["password"],"network":"tcp,udp","level":0}
            else:
                clients = []
                for u in ulist:
                    if "id" in u:
                        c = {"id":u["id"],"level":0,"email":u.get("email","")}
                        if inbound["protocol"]=="vless" and "flow" in u:
                            c["flow"] = u["flow"]
                        clients.append(c)
                    elif "password" in u:
                        clients.append({"password":u["password"],"level":0,"email":u.get("email","")})
                inbound["settings"]["clients"] = clients
        tmp = XRAY_CONFIG.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(config, indent=2))
        ok = sh(f"python3 -c 'import json; json.load(open(\"{tmp}\"))' 2>/dev/null && echo OK")
        if ok:
            before = XRAY_CONFIG.read_bytes() if XRAY_CONFIG.exists() else b""
            tmp.replace(XRAY_CONFIG)
            if XRAY_CONFIG.read_bytes() != before:
                sh("systemctl restart xray 2>/dev/null || true")
        else:
            print(f" {C['RED']}✗ xray: config invalide après build, annulé{C['RST']}")
            tmp.unlink(missing_ok=True)
    except Exception as e:
        print(f" {C['RED']}✗ xray_build_config: {e}{C['RST']}")

def _rebuild_xray_users():
    XRAY_USERS.parent.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    fresh = {"vmess": [], "vless": [], "trojan": [], "shadow": []}
    if USERDIR.exists():
        for f in USERDIR.iterdir():
            if not f.is_file(): continue
            p = _meta_get(f.name, "proto")
            if p not in ("vmess", "vless", "trojan"): continue
            exp = _meta_get(f.name, "exp")
            if exp and exp < today: continue
            if is_locked(f.name): continue
            q = float(_meta_get(f.name, "quota") or "0")
            if p in ("vmess", "vless"):
                uuid = _meta_get(f.name, "uuid")
                if not uuid: continue
                fresh[p].append({"id": uuid, "email": f.name, "level": 0, "expire": exp, "quota": q})
            elif p == "trojan":
                pw = _meta_get(f.name, "pass")
                if not pw: continue
                fresh["trojan"].append({"password": pw, "email": f.name, "level": 0, "expire": exp, "quota": q})
    XRAY_USERS.write_text(json.dumps(fresh, indent=2))

def xray_add_user(proto, user, cred, exp, quota):
    XRAY_USERS.parent.mkdir(parents=True, exist_ok=True)
    if not XRAY_USERS.exists():
        XRAY_USERS.write_text('{"vmess":[],"vless":[],"trojan":[],"shadow":[]}')
    idkey = {"vmess":"id","vless":"id","trojan":"password"}.get(proto, "id")
    sh(f"jq '.{proto} += [{{\"{idkey}\":\"{cred}\",\"email\":\"{user}\",\"level\":0,\"expire\":\"{exp}\",\"quota\":{float(quota or 0)}}}]' {XRAY_USERS} > /tmp/xu.json 2>/dev/null && mv /tmp/xu.json {XRAY_USERS} 2>/dev/null")

def xray_del_user(user):
    if not XRAY_USERS.exists(): return
    sh(f"jq '.vmess |= map(select(.email!=\"{user}\")) | .vless |= map(select(.email!=\"{user}\")) | .trojan |= map(select(.email!=\"{user}\"))' {XRAY_USERS} > /tmp/xu.json 2>/dev/null && mv /tmp/xu.json {XRAY_USERS} 2>/dev/null")

def xray_reload():
    xray_build_config()

def install_xray():
    if sh("command -v xray 2>/dev/null") != "" and Path("/etc/systemd/system/xray.service").exists() and Path("/etc/xray/config.json").exists():
        print(f" {C['GREEN']}✔ Xray déjà installé.{C['RST']}");return
    DOMAIN = _force_domain()
    sh("apt-get install -y -qq haproxy curl socat wget unzip jq ca-certificates 2>/dev/null || true")
    if sh("command -v xray 2>/dev/null") == "":
        print(f" {C['YELLOW']}► Installation de Xray...{C['RST']}")
        r=sh("curl -fsSL https://raw.githubusercontent.com/XTLS/Xray-install/main/install-release.sh | bash 2>&1")
        if "success" not in r.lower() and sh("command -v xray 2>/dev/null") == "":
            print(f" {C['RED']}✗ Échec installation Xray: téléchargement impossible.{C['RST']}")
            print(f" {C['YELLOW']}► Vérifiez votre connexion Internet ou installez Xray manuellement.{C['RST']}")
            return
    Path("/etc/xray").mkdir(parents=True, exist_ok=True)
    Path("/var/log/xray").mkdir(parents=True, exist_ok=True)
    sh("rm -f /var/log/xray/access.log /var/log/xray/error.log 2>/dev/null; touch /var/log/xray/access.log /var/log/xray/error.log 2>/dev/null || true")
    if not XRAY_USERS.exists(): _rebuild_xray_users()
    ok=_acme_cert(DOMAIN, "/etc/xray")
    if not ok:
        print(f" {C['YELLOW']}⚠ ACME failed for {DOMAIN}, generating self-signed cert...{C['RST']}")
        sh(f"openssl req -x509 -newkey rsa:2048 -keyout /etc/xray/privkey.pem -out /etc/xray/fullchain.pem -nodes -days 3650 -subj '/CN={DOMAIN}' 2>/dev/null")
    if not Path("/etc/xray/xray.pem").exists() or Path("/etc/xray/xray.pem").stat().st_mtime < Path("/etc/xray/fullchain.pem").stat().st_mtime:
        crt=Path("/etc/xray/fullchain.pem")
        key=Path("/etc/xray/privkey.pem")
        sh(f"cat {crt} {key} > /etc/xray/xray.pem 2>/dev/null || true")
        sh(f"cat {crt} {key} > /etc/haproxy/panel.pem 2>/dev/null || true")
    sh("chmod 600 /etc/xray/xray.key /etc/xray/xray.pem /etc/xray/privkey.pem 2>/dev/null || true")
    xray_gen_config()
    xray_gen_haproxy()
    svc = """[Unit]
Description=Xray Service
After=network-online.target nss-lookup.target
Wants=network-online.target
StartLimitIntervalSec=0
StartLimitBurst=0
[Service]
User=root
CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_DAC_OVERRIDE
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_DAC_OVERRIDE
NoNewPrivileges=true
ExecStart=/usr/local/bin/xray -config /etc/xray/config.json
Restart=always
RestartSec=5s
LimitNOFILE=1048576
[Install]
WantedBy=multi-user.target
"""
    Path("/etc/systemd/system/xray.service").write_text(svc)
    sh("rm -rf /etc/systemd/system/xray.service.d /etc/systemd/system/xray@.service.d 2>/dev/null || true")
    Path("/etc/systemd/system/haproxy.service.d").mkdir(parents=True, exist_ok=True)
    Path("/etc/systemd/system/haproxy.service.d/override.conf").write_text("[Unit]\nStartLimitIntervalSec=0\nStartLimitBurst=0\n[Service]\nRestart=always\nRestartSec=5s\n")
    _deploy_nft("xray", 'table inet xray { chain input { type filter hook input priority 0; policy accept; tcp dport {443,8880} accept; }; }')
    xray_build_config()
    sh("systemctl daemon-reload 2>/dev/null || true")
    sh("systemctl enable --now xray haproxy 2>/dev/null || true; sleep 2")
    crontab_cmds = [
        "*/15 * * * * systemctl is-active --quiet xray || systemctl restart xray >> /var/log/xray-watchdog.log 2>&1",
        "*/5 * * * * systemctl is-active --quiet haproxy || systemctl restart haproxy >> /var/log/haproxy-watchdog.log 2>&1",
        "*/3 * * * * systemctl is-active --quiet hysteria || systemctl restart hysteria >> /var/log/hysteria-watchdog.log 2>&1",
        "*/3 * * * * systemctl is-active --quiet zivpn || systemctl restart zivpn >> /var/log/zivpn-watchdog.log 2>&1",
        "*/3 * * * * systemctl is-active --quiet udp-custom || systemctl restart udp-custom >> /var/log/udp-custom-watchdog.log 2>&1",
        "*/3 * * * * systemctl is-active --quiet sshws || systemctl restart sshws >> /var/log/sshws-watchdog.log 2>&1",
        "*/3 * * * * systemctl is-active --quiet ssl_tls || systemctl restart ssl_tls >> /var/log/ssl_tls-watchdog.log 2>&1",
        "*/3 * * * * systemctl is-active --quiet dropbear-custom || systemctl restart dropbear-custom >> /var/log/dropbear-watchdog.log 2>&1",
        "0 0 1 * * vnstat --reset 2>/dev/null || true",
        "0 6 * * * /usr/local/bin/kighmu-bot --reseller-cleanup 2>/dev/null || true",
        "*/5 * * * * /usr/local/bin/kighmu-bot --ssh-quota-sync 2>/dev/null || true",
        "*/5 * * * * /usr/local/bin/kighmu-bot --quota-enforce 2>/dev/null || true"
    ]
    existing = sh("crontab -l 2>/dev/null")
    for cmd in crontab_cmds:
        if cmd not in existing:
            sh(f'(crontab -l 2>/dev/null; echo "{cmd}") | crontab - 2>/dev/null || true')
    _install_xray_watchdog()
    x_ok=sh("systemctl is-active xray 2>/dev/null")
    h_ok=sh("systemctl is-active haproxy 2>/dev/null")
    if x_ok=="active" and h_ok=="active":
        print(f" {C['GREEN']}✔ Xray + HAProxy installés et actifs.{C['RST']}")
    else:
        print(f" {C['YELLOW']}⚠ Xray={x_ok} HAProxy={h_ok}.{C['RST']}")

def _install_xray_watchdog():
    watchdog_script = r"""#!/bin/bash
XRAY_BIN="/usr/local/bin/xray"; XRAY_CONFIG="/etc/xray/config.json"; WATCHDOG_LOG="/var/log/xray-watchdog.log"
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$WATCHDOG_LOG"; }
systemctl is-active --quiet xray 2>/dev/null && exit 0
log "[WATCHDOG] Xray INACTIF --- reparation..."
[[ ! -x "$XRAY_BIN" ]] && { log "Binaire manquant"; exit 1; }
if [[ -f "$XRAY_CONFIG" ]] && ! jq empty "$XRAY_CONFIG" 2>/dev/null; then
    cp "$XRAY_CONFIG" "${XRAY_CONFIG}.corrupted.$(date +%s)"; log "Config corrompue"
    python3 - <<'PYEOF'
import json
from pathlib import Path
try:
    u = json.loads(Path("/etc/xray/users.json").read_text()) if Path("/etc/xray/users.json").exists() else {"vmess":[],"vless":[],"trojan":[],"shadow":[]}
except Exception:
    u = {"vmess":[],"vless":[],"trojan":[],"shadow":[]}
cfg = {"log":{"loglevel":"warning","access":"/var/log/xray/access.log","error":"/var/log/xray/error.log"},"inbounds":[{"tag":"VMess-TCP","port":10001,"listen":"127.0.0.1","protocol":"vmess","settings":{"clients":[]},"streamSettings":{"network":"tcp","security":"none"}}],"outbounds":[{"protocol":"freedom","settings":{}}]}
Path("/etc/xray/config.json").write_text(json.dumps(cfg, indent=2))
PYEOF
    log "Config regeneree (minimum)"
fi
for port in $(jq -r '.inbounds[].port' "$XRAY_CONFIG" 2>/dev/null); do
    pid=$(ss -tlnp | grep ":$port " | grep -v xray | grep -oP 'pid=\K[0-9]+' | head -1)
    [[ -n "$pid" ]] && { kill "$pid" 2>/dev/null || true; log "Port $port libere (PID $pid)"; }
done
systemctl start xray 2>/dev/null; sleep 3
systemctl is-active --quiet xray 2>/dev/null && log "[WATCHDOG] Xray redemarre !" || log "[WATCHDOG] Echec demarrage"
"""
    Path("/etc/kighmu/xray-watchdog.sh").write_text(watchdog_script)
    sh("chmod +x /etc/kighmu/xray-watchdog.sh 2>/dev/null || true")
    if "xray-watchdog.sh" not in sh("crontab -l 2>/dev/null"):
        sh('(crontab -l 2>/dev/null; echo "* * * * * /etc/kighmu/xray-watchdog.sh") | crontab - 2>/dev/null || true')
    wd_svc = """[Unit]
Description=Xray Watchdog Service
After=network.target
[Service]
Type=oneshot
ExecStart=/etc/kighmu/xray-watchdog.sh
User=root
"""
    wd_timer = """[Unit]
Description=Xray Watchdog Timer
Requires=xray-watchdog.service
[Timer]
OnBootSec=30
OnUnitActiveSec=120
Unit=xray-watchdog.service
[Install]
WantedBy=timers.target
"""
    Path("/etc/systemd/system/xray-watchdog.service").write_text(wd_svc)
    Path("/etc/systemd/system/xray-watchdog.timer").write_text(wd_timer)
    sh("systemctl daemon-reload 2>/dev/null; systemctl enable --now xray-watchdog.timer 2>/dev/null || true")

def uninstall_xray():
    sh("systemctl disable --now xray 2>/dev/null || true")
    if sh("command -v v2ray 2>/dev/null") == "":
        sh("systemctl disable --now haproxy 2>/dev/null || true")
    sh("rm -f /usr/local/bin/xray /usr/local/bin/xray-* 2>/dev/null; rm -rf /etc/xray /var/log/xray 2>/dev/null || true")
    sh("rm -f /etc/systemd/system/xray.service /etc/systemd/system/xray-watchdog.service /etc/systemd/system/xray-watchdog.timer 2>/dev/null; rm -rf /etc/systemd/system/haproxy.service.d 2>/dev/null || true")
    sh("rm -f /etc/kighmu/xray-watchdog.sh 2>/dev/null || true")
    sh(r"crontab -l 2>/dev/null | grep -v 'xray-watchdog\|haproxy-watchdog\|vnstat --reset' | crontab - 2>/dev/null || true")
    _remove_nft("xray"); sh("systemctl daemon-reload 2>/dev/null || true")

def install_v2ray():
    if sh("command -v v2ray 2>/dev/null") != "" and Path("/etc/systemd/system/v2ray.service").exists():
        print(f" {C['GREEN']}✔ V2ray déjà installé.{C['RST']}");return
    _ensure_domain()
    sh("sysctl -w net.core.rmem_default=26214400 net.core.wmem_default=26214400 net.core.rmem_max=67108864 net.core.wmem_max=67108864 net.core.optmem_max=25165824 net.core.netdev_max_backlog=250000 net.ipv4.tcp_rmem='4096 87380 33554432' net.ipv4.tcp_wmem='4096 65536 33554432' net.ipv4.tcp_congestion_control=bbr net.core.default_qdisc=fq net.ipv4.ip_forward=1 net.ipv4.udp_mem='102400 873800 16777216' net.ipv4.tcp_fastopen=3 net.ipv4.tcp_mtu_probing=1 2>/dev/null || true")
    if not Path("/etc/sysctl.d/99-v2ray.conf").exists():
        Path("/etc/sysctl.d/99-v2ray.conf").write_text("net.core.rmem_default=26214400\nnet.core.wmem_default=26214400\nnet.core.rmem_max=67108864\nnet.core.wmem_max=67108864\nnet.core.optmem_max=25165824\nfs.file-max=1000000\nnet.core.netdev_max_backlog=250000\nnet.ipv4.tcp_rmem=4096 87380 33554432\nnet.ipv4.tcp_wmem=4096 65536 33554432\nnet.ipv4.tcp_congestion_control=bbr\nnet.core.default_qdisc=fq\nnet.ipv4.ip_forward=1\nnet.ipv4.udp_mem=102400 873800 16777216\nnet.ipv4.tcp_fastopen=3\nnet.ipv4.tcp_mtu_probing=1\n")
    iface = sh("ip route show default 2>/dev/null") or ""
    iface = iface.split("dev ")[-1].split()[0] if "dev " in iface else ""
    if iface:
        sh(f"tc qdisc del dev {iface} root 2>/dev/null || true")
        sh(f"tc qdisc add dev {iface} root fq 2>/dev/null || true")
    sh("curl -fsSL https://raw.githubusercontent.com/v2fly/fhs-install-v2ray/master/install-release.sh | bash 2>/dev/null || true")
    if sh("command -v v2ray 2>/dev/null") == "":
        print(f" {C['RED']}✗ Échec installation V2ray.{C['RST']}");return
    Path("/etc/v2ray").mkdir(parents=True, exist_ok=True)
    Path("/var/log/v2ray").mkdir(parents=True, exist_ok=True)
    V2RAY_CONFIG = Path("/etc/v2ray/config.json")
    v2cfg = {
        "log": {"loglevel": "warning", "access": "/var/log/v2ray/access.log", "error": "/var/log/v2ray/error.log"},
        "inbounds": [{
            "port": 5401, "listen": "0.0.0.0", "protocol": "vless",
            "settings": {"clients": [], "decryption": "none"},
            "streamSettings": {"network": "tcp", "security": "none"},
            "tag": "VLESS-TCP"
        }, {
            "tag": "api", "port": 10086, "listen": "127.0.0.1",
            "protocol": "dokodemo-door", "settings": {"address": "127.0.0.1"}
        }],
        "outbounds": [{"protocol": "freedom", "settings": {}}],
        "stats": {},
        "policy": {"levels": {"0": {"statsUserUplink": True, "statsUserDownlink": True}}, "system": {"statsInboundUplink": True, "statsInboundDownlink": True}},
        "api": {"tag": "api", "services": ["HandlerService", "StatsService"]},
        "routing": {"rules": [{"type": "field", "inboundTag": "api", "outboundTag": "api"}]}
    }
    V2RAY_CONFIG.write_text(json.dumps(v2cfg, indent=2))
    if not V2RAY_USERS.exists():
        V2RAY_USERS.write_text('{"vless":[]}')
    _deploy_nft("v2ray", 'table inet v2ray { chain input { type filter hook input priority 0; policy accept; tcp dport 5401 accept; }; chain output { type filter hook output priority 0; policy accept; tcp sport 5401 accept; }; }')
    v2svc="""[Unit]
Description=V2Ray Service
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0
StartLimitBurst=0
[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/v2ray run -config /etc/v2ray/config.json
Restart=always
RestartSec=5
LimitNOFILE=65536
KillMode=process
KillSignal=SIGTERM
TimeoutStopSec=10
[Install]
WantedBy=multi-user.target
"""
    Path("/etc/systemd/system/v2ray.service").write_text(v2svc)
    sh("rm -f /etc/systemd/system/v2ray@.service 2>/dev/null; rm -rf /etc/systemd/system/v2ray.service.d 2>/dev/null || true")
    sh("systemctl daemon-reload && systemctl enable --now v2ray 2>/dev/null || true")
    v2raydns_apply()
    if "v2ray-watchdog" not in sh("crontab -l 2>/dev/null"):
        sh('(crontab -l 2>/dev/null; echo "*/2 * * * * systemctl is-active --quiet v2ray || systemctl restart v2ray") | crontab - 2>/dev/null || true')
    if sh("systemctl is-active v2ray 2>/dev/null")=="active":
        print(f" {C['GREEN']}✔ V2ray-DNS installé et actif (port 5401).{C['RST']}")
    else:
        print(f" {C['RED']}✗ V2ray-DNS: échec démarrage.{C['RST']}")

def uninstall_v2ray():
    sh("systemctl disable --now v2ray 2>/dev/null || true")
    sh("rm -f /usr/local/bin/v2ray 2>/dev/null; rm -rf /etc/v2ray 2>/dev/null || true")
    _remove_nft("v2ray"); sh("systemctl daemon-reload 2>/dev/null || true")
    print(f" {C['GREEN']}✔ V2ray désinstallé.{C['RST']}")

def install_hysteria():
    if sh("command -v hysteria-linux-amd64 2>/dev/null") != "" and Path("/etc/systemd/system/hysteria.service").exists():
        print(f" {C['GREEN']}✔ Hysteria déjà installé.{C['RST']}");return
    r=sh("curl -fsSL 'https://github.com/apernet/hysteria/releases/download/v1.3.4/hysteria-linux-amd64' -o /usr/local/bin/hysteria-linux-amd64 2>/dev/null && chmod +x /usr/local/bin/hysteria-linux-amd64 2>/dev/null && echo OK")
    if "OK" not in r: print(f" {C['RED']}✗ Échec téléchargement Hysteria.{C['RST']}");return
    Path("/etc/hysteria").mkdir(parents=True, exist_ok=True)
    DOMAIN = _ensure_domain() or "hysteria.local"
    if not Path("/etc/hysteria/hysteria.crt").exists():
        sh(f"openssl req -x509 -newkey rsa:2048 -keyout /etc/hysteria/hysteria.key -out /etc/hysteria/hysteria.crt -nodes -days 3650 -subj '/CN={DOMAIN}' 2>/dev/null")
    sh("chmod 600 /etc/hysteria/hysteria.key 2>/dev/null; chmod 644 /etc/hysteria/hysteria.crt 2>/dev/null || true")
    hy_cfg = '{\"listen\":\":20000\",\"cert\":\"/etc/hysteria/hysteria.crt\",\"key\":\"/etc/hysteria/hysteria.key\",\"obfs\":\"hysteria\",\"up_mbps\":150,\"down_mbps\":150,\"recv_window_conn\":33554432,\"recv_window_client\":67108864,\"disable_mtu_discovery\":false,\"max_conn_client\":4096,\"exclude_port\":[53,5300,4466,36712,5667,20000],\"auth\":{\"mode\":\"passwords\",\"config\":[\"zi\"]}}'
    Path("/etc/hysteria/config.json").write_text(hy_cfg)
    svc = """[Unit]
Description=Hysteria Tunnel (v1.3.4)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0
StartLimitBurst=0
[Service]
Type=simple
ExecStart=/usr/local/bin/hysteria-linux-amd64 server -c /etc/hysteria/config.json
WorkingDirectory=/etc/hysteria
Restart=always
RestartSec=10
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW
LimitNOFILE=1048576
LimitNPROC=infinity
LimitMEMLOCK=infinity
StandardOutput=append:/var/log/hysteria.log
StandardError=append:/var/log/hysteria.log
[Install]
WantedBy=multi-user.target
"""
    Path("/etc/systemd/system/hysteria.service").write_text(svc)
    iface = get_main_iface()
    _deploy_nft("hysteria", f'table inet hysteria {{ chain input {{ type filter hook input priority 0; policy accept; udp dport 20000-50000 accept; }}; chain prerouting {{ type nat hook prerouting priority dstnat; policy accept; iifname "{iface}" udp dport 20000-50000 dnat to :20000; }}; }}')
    sh("systemctl daemon-reload && systemctl enable --now hysteria.service 2>/dev/null || true")
    hysteria_apply()
    if sh("systemctl is-active hysteria.service 2>/dev/null")=="active":
        print(f" {C['GREEN']}✔ Hysteria installé et actif (port 20000).{C['RST']}")
    else: print(f" {C['RED']}✗ Hysteria: échec démarrage.{C['RST']}")

def uninstall_hysteria():
    sh("systemctl disable --now hysteria.service 2>/dev/null || true")
    for f in ["/etc/systemd/system/hysteria.service"]: Path(f).unlink(missing_ok=True)
    sh("rm -f /usr/local/bin/hysteria-linux-amd64 2>/dev/null; rm -rf /etc/hysteria 2>/dev/null || true")
    _remove_nft("hysteria")
    # Regenere le catchall udp-custom sans l'exclusion hysteria (devenue obsolete)
    _ensure_nat_catchall()
    sh("systemctl daemon-reload 2>/dev/null || true")
    print(f" {C['GREEN']}✔ Hysteria désinstallé.{C['RST']}")

def install_zivpn():
    if sh("command -v zivpn 2>/dev/null") != "" and Path("/etc/systemd/system/zivpn.service").exists():
        print(f" {C['GREEN']}✔ ZIVPN déjà installé.{C['RST']}");return
    r=sh("curl -fsSL 'https://github.com/kinf744/Kighmu/releases/download/v1.0.0/udp-zivpn-linux-amd64' -o /usr/local/bin/zivpn 2>/dev/null && chmod +x /usr/local/bin/zivpn 2>/dev/null && echo OK")
    if "OK" not in r: print(f" {C['RED']}✗ Échec téléchargement ZIVPN.{C['RST']}");return
    Path("/etc/zivpn").mkdir(parents=True, exist_ok=True)
    DOMAIN = _ensure_domain() or "zivpn.local"
    sh(f"openssl req -x509 -newkey rsa:2048 -keyout /etc/zivpn/zivpn.key -out /etc/zivpn/zivpn.crt -nodes -days 3650 -subj '/CN={DOMAIN}' 2>/dev/null")
    sh("chmod 600 /etc/zivpn/zivpn.key 2>/dev/null; chmod 644 /etc/zivpn/zivpn.crt 2>/dev/null || true")
    zi_cfg = '{\"listen\":\":5667\",\"cert\":\"/etc/zivpn/zivpn.crt\",\"key\":\"/etc/zivpn/zivpn.key\",\"obfs\":\"zivpn\",\"recv_window_conn\":15728640,\"recv_window_client\":67108864,\"disable_mtu_discovery\":false,\"max_conn_client\":4096,\"exclude_port\":[53,5300,4466,36712,20000],\"auth\":{\"mode\":\"passwords\",\"config\":[\"zi\"]}}'
    Path("/etc/zivpn/config.json").write_text(zi_cfg)
    svc = """[Unit]
Description=ZIVPN UDP Server (High-Speed)
After=network-online.target
Wants=network-online.target
StartLimitIntervalSec=0
StartLimitBurst=0
[Service]
Type=simple
ExecStart=/usr/local/bin/zivpn server -c /etc/zivpn/config.json
WorkingDirectory=/etc/zivpn
Restart=always
RestartSec=10
AmbientCapabilities=CAP_NET_ADMIN CAP_NET_BIND_SERVICE CAP_NET_RAW
LimitNOFILE=1048576
LimitNPROC=infinity
LimitMEMLOCK=infinity
StandardOutput=append:/var/log/zivpn.log
StandardError=append:/var/log/zivpn.log
[Install]
WantedBy=multi-user.target
"""
    Path("/etc/systemd/system/zivpn.service").write_text(svc)
    iface = get_main_iface()
    _deploy_nft("zivpn", f'table inet zivpn {{ chain input {{ type filter hook input priority 0; policy accept; udp dport 5667 accept; udp dport 6000-19999 accept; }}; chain prerouting {{ type nat hook prerouting priority -100; iifname "{iface}" udp dport 6000-19999 dnat to :5667; }}; }}')
    sh("systemctl daemon-reload && systemctl enable --now zivpn.service 2>/dev/null || true")
    zivpn_apply()
    if sh("systemctl is-active zivpn.service 2>/dev/null")=="active":
        print(f" {C['GREEN']}✔ ZIVPN installé et actif (port 5667).{C['RST']}")
    else: print(f" {C['RED']}✗ ZIVPN: échec démarrage.{C['RST']}")

def uninstall_zivpn():
    sh("systemctl disable --now zivpn.service 2>/dev/null || true")
    for f in ["/etc/systemd/system/zivpn.service"]: Path(f).unlink(missing_ok=True)
    sh("rm -f /usr/local/bin/zivpn 2>/dev/null; rm -rf /etc/zivpn 2>/dev/null || true")
    _remove_nft("zivpn")
    # Regenere le catchall udp-custom sans l'exclusion zivpn (devenue obsolete)
    _ensure_nat_catchall()
    sh("systemctl daemon-reload 2>/dev/null || true")
    print(f" {C['GREEN']}✔ ZIVPN désinstallé.{C['RST']}")

def setup_config():
    df=Path("/etc/kighmu/domain.txt")
    if not df.parent.exists(): df.parent.mkdir(parents=True)
    cur=df.read_text().strip() if df.exists() else ""
    print(f"\n {C['CYAN']}━━━ CONFIGURATION ━━━{C['RST']}")
    dom=input(f" Domain name (e.g. vpn.example.com) [{C['GREEN']}{cur or 'required'}{C['RST']}]: ").strip() or cur
    while not dom: dom=input(f" Domain required: ").strip()
    df.write_text(dom+"\n")
    Path("/etc/slowdns/ns4").mkdir(parents=True,exist_ok=True)
    Path("/etc/slowdns/nv4").mkdir(parents=True,exist_ok=True)
    nsc=Path("/etc/slowdns/ns.conf")
    nv4c=Path("/etc/slowdns/nv4/ns.conf")
    cur4=nsc.read_text().strip() if nsc.exists() else ""
    curv4=nv4c.read_text().strip() if nv4c.exists() else ""
    ns4=input(f" NS4 subdomain (e.g. ns4.{dom}) [{C['GREEN']}{cur4 or 'ns4.'+dom}{C['RST']}]: ").strip() or cur4 or "ns4."+dom
    nv4=input(f" NV4 subdomain (e.g. nv4.{dom}) [{C['GREEN']}{curv4 or 'nv4.'+dom}{C['RST']}]: ").strip() or curv4 or "nv4."+dom
    nsc.write_text(ns4+"\n");nv4c.write_text(nv4+"\n")
    print(f" {C['GREEN']}✔ Domain: {dom}, NS4: {ns4}, NV4: {nv4}{C['RST']}\n")

def _install_global_watchdog():
    script = """#!/bin/bash
# Kighmu global tunnel watchdog — relance les services au boot et apres crash
LOG=/var/log/kighmu-watchdog.log
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" >> "$LOG"; }
for svc in haproxy xray v2ray hysteria zivpn udp-custom sshws ssl_tls dropbear-custom slowdns-ns4 slowdns-nv4 dnsdist badvpn-7100 badvpn-7200 badvpn-7300 kighmu-bot; do
    systemctl is-enabled --quiet "$svc" 2>/dev/null || continue
    if ! systemctl is-active --quiet "$svc" 2>/dev/null; then
        systemctl reset-failed "$svc" 2>/dev/null || true
        systemctl start "$svc" 2>/dev/null && log "$svc relance" || log "$svc ECHEC"
    fi
done
"""
    Path("/usr/local/bin/kighmu-watchdog.sh").write_text(script)
    Path("/usr/local/bin/kighmu-watchdog.sh").chmod(0o755)
    cr = sh("crontab -l 2>/dev/null")
    if "kighmu-watchdog.sh" not in cr:
        sh("(crontab -l 2>/dev/null; echo '@reboot /usr/local/bin/kighmu-watchdog.sh >/dev/null 2>&1') | crontab - 2>/dev/null || true")

def install_all_missing():
    for fn in [install_ssh_stack, install_ssl_tls, install_sshws, install_xray, install_v2ray, install_badvpn, install_udp_custom, install_slowdns, install_hysteria, install_zivpn]:
        fn()
    _install_global_watchdog()
    sh("systemctl daemon-reload 2>/dev/null || true")

def uninstall_all_active(silent=False):
    if not silent:
        clear_screen()
        print(f" {C['RED']}╔════════════════════════════════════════╗{C['RST']}")
        print(f" {C['RED']}║{C['RST']}         {C['WHITE']}DÉSINSTALLATION TOTALE{C['RST']}         {C['RED']}║{C['RST']}")
        print(f" {C['RED']}╚════════════════════════════════════════╝{C['RST']}\n")
        print(f" {C['YELLOW']}⚠{C['RST']} {C['WHITE']}Cette action va supprimer TOUS les tunnels :{C['RST']}")
        print(f" {C['GRAY']}  • SSH / Dropbear      • WS-EPRO (SSH-WS)      • SSL / TLS{C['RST']}")
        print(f" {C['GRAY']}  • XRAY                • V2RAY-DNS             • BadVPN{C['RST']}")
        print(f" {C['GRAY']}  • UDP Custom          • SlowDNS               • Hysteria{C['RST']}")
        print(f" {C['GRAY']}  • ZIVPN               • HAProxy               • NFTables{C['RST']}\n")
        c = input(f" {C['RED']}► Tapez 'yes' pour confirmer :{C['RST']} ").strip().lower()
        if c != "yes":
            print(f" {C['GREEN']}✔ Annulé.{C['RST']}")
            press_enter()
            return
    for fn in [uninstall_zivpn, uninstall_hysteria, uninstall_slowdns, uninstall_udp_custom, uninstall_badvpn, uninstall_v2ray, uninstall_xray, uninstall_sshws, uninstall_ssl_tls, uninstall_dropbear]:
        fn()
    sh("systemctl disable --now haproxy 2>/dev/null || true")
    for svc in ["nftables-tunnel@badvpn","nftables-tunnel@dropbear","nftables-tunnel@hysteria","nftables-tunnel@slowdns","nftables-tunnel@v2ray","nftables-tunnel@xray","nftables-tunnel@zivpn","nftables-tunnel@sshws","nftables-tunnel@ssl_tls","nftables-tunnel@udp-custom","badvpn-7100","badvpn-7200","badvpn-7300"]:
        sh(f"systemctl stop --now {svc} 2>/dev/null || true")
        sh(f"systemctl disable {svc} 2>/dev/null || true")
    sh("systemctl daemon-reload && systemctl reset-failed 2>/dev/null || true")
    for tbl in ["badvpn","dropbear","hysteria","slowdns","v2ray","xray","zivpn","sshws","ssl_tls","udp-custom","udp-custom-catchall"]:
        sh(f"nft delete table inet {tbl} 2>/dev/null || true")
    # Ne PAS supprimer ip nat / ip6 nat en bloc (tables partagees avec Docker/kighmu).
    # On retire seulement les regles dnat/redirect pilotees par le panel.
    for fam in ["ip", "ip6"]:
        for r in ["dnat to :36712", "dnat to :20000", "dnat to :5667", "redirect to :5300", "redirect to :53"]:
            sh(f"nft list chain {fam} nat prerouting 2>/dev/null | grep -q '{r}' && nft --handle list chain {fam} nat prerouting 2>/dev/null | grep '{r}' | sed -n 's/.*# handle \\([0-9]*\\).*/\\1/p' | while read h; do nft delete rule {fam} nat prerouting handle $h 2>/dev/null; done || true")
    sh("systemctl disable --now nftables-nat.service nftables-tunnel.service 2>/dev/null || true")
    print(f"\n {C['RED']}✔ Tous les tunnels ont été désinstallés.{C['RST']}")
    if not silent:
        press_enter()

def install_telegram_bot():
    clear_screen()
    print(f" {C['CYAN']}━━━ TELEGRAM BOT ━━━{C['RST']}")
    token = input(" Telegram Bot Token (from @BotFather): ").strip()
    if not token: print(f" {C['RED']}✗ Token required{C['RST']}"); press_enter(); return
    aid_s = input(" Your Telegram User ID (numeric): ").strip()
    if not aid_s.isdigit(): print(f" {C['RED']}✗ Valid numeric ID required{C['RST']}"); press_enter(); return
    sh("apt-get install -y -qq python3 python3-pip 2>/dev/null")
    sh("pip3 install python-telegram-bot --quiet --break-system-packages 2>/dev/null || pip3 install python-telegram-bot --quiet 2>/dev/null || true")
    BOT_DIR = Path("/etc/kighmu/bot")
    BOT_DIR.mkdir(parents=True, exist_ok=True)
    (BOT_DIR / "config.json").write_text(json.dumps({"token": token, "admin_id": int(aid_s)}, indent=2))
    # Copy self as bot script
    bot_script = Path("/usr/local/bin/kighmu-bot")
    bot_script.write_text(Path(sys.argv[0]).read_text())
    bot_script.chmod(0o755)
    svc = f"""[Unit]
Description=Kighmu Telegram Bot
After=network.target
StartLimitIntervalSec=0
StartLimitBurst=0
[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/bin/kighmu-bot --bot
WorkingDirectory=/etc/kighmu/bot
Restart=always
RestartSec=10
StandardOutput=append:/var/log/kighmu-bot.log
StandardError=append:/var/log/kighmu-bot.log
[Install]
WantedBy=multi-user.target
"""
    Path("/etc/systemd/system/kighmu-bot.service").write_text(svc)
    sh("systemctl daemon-reload && systemctl enable --now kighmu-bot 2>/dev/null || true")

def uninstall_telegram_bot(silent=False):
    sh("systemctl stop kighmu-bot 2>/dev/null || true; systemctl disable kighmu-bot 2>/dev/null || true")
    sh("systemctl stop kighmu-reseller-* 2>/dev/null || true; systemctl disable kighmu-reseller-* 2>/dev/null || true")
    for f in Path("/etc/systemd/system").glob("kighmu-reseller-*.service"):
        f.unlink(missing_ok=True)
    for f in ["/etc/systemd/system/kighmu-bot.service","/usr/local/bin/kighmu-bot"]:
        Path(f).unlink(missing_ok=True)
    sh("rm -rf /etc/kighmu/bot /var/log/kighmu-bot.log 2>/dev/null || true")
    sh("pkill -f 'kighmu.*--bot' 2>/dev/null || true; pkill -f 'kighmu.*--reseller-bot' 2>/dev/null || true")
    existing = sh("crontab -l 2>/dev/null")
    for pat in ["kighmu-bot","reseller-cleanup"]:
        if pat in existing:
            sh(f'(crontab -l 2>/dev/null | grep -v "{pat}" | crontab - 2>/dev/null) || true')
    sh("pip3 uninstall python-telegram-bot -y --break-system-packages 2>/dev/null || pip3 uninstall python-telegram-bot -y 2>/dev/null || true")
    sh("systemctl daemon-reload 2>/dev/null || true")
    print(f" {C['GREEN']}✔ Telegram Bot complètement désinstallé{C['RST']}")
    if not silent:
        press_enter()

# ── Update functions ──────────────────────────────────────────────────────────
def upd_check():
    print(f" {C['YELLOW']}Checking for updates...{C['RST']}")
    sh("cd /root && git fetch origin 2>/dev/null || cd /root/fasto-push && git fetch origin 2>/dev/null || true")

def upd_update():
    print(f" {C['YELLOW']}Updating...{C['RST']}")
    sh("cd /root && git pull origin main 2>/dev/null || cd /root/fasto-push && git pull origin main 2>/dev/null || true")

def upd_changelog():
    print(f" {C['YELLOW']}Changelog:{C['RST']}")
    sh("cd /root && git log --oneline -10 2>/dev/null || cd /root/fasto-push && git log --oneline -10 2>/dev/null || echo 'No git history'")

def upd_reinstall():
    c = input(f" {C['RED']}Reinstall? (will keep users) [y/N]: {C['RST']}").strip().lower()
    if c == 'y': install_all_missing()

def upd_remove():
    clear_screen()
    print(f" {C['RED']}╔════════════════════════════════════════╗{C['RST']}")
    print(f" {C['RED']}║{C['RST']}         {C['WHITE']}DÉSINSTALLATION TOTALE{C['RST']}         {C['RED']}║{C['RST']}")
    print(f" {C['RED']}╚════════════════════════════════════════╝{C['RST']}\n")
    print(f" {C['YELLOW']}⚠{C['RST']} {C['WHITE']}Cette action va supprimer:{C['RST']}")
    print(f" {C['GRAY']}  • Tous les tunnels et services{C['RST']}")
    print(f" {C['GRAY']}  • Tous les utilisateurs{C['RST']}")
    print(f" {C['GRAY']}  • Le panneau de contrôle{C['RST']}\n")
    c = input(f" {C['RED']}► Tapez 'yes' pour confirmer :{C['RST']} ").strip().lower()
    if c != "yes":
        print(f" {C['GREEN']}✔ Annulé.{C['RST']}")
        press_enter()
        return
    _auto_uninstall_all()

def _auto_uninstall_all():
    uninstall_all_active(silent=True)
    uninstall_telegram_bot(silent=True)
    for r in reseller_list(): reseller_remove_service(r["id"])
    pats = "kighmu|xray|v2ray|slowdns|dnsdist|haproxy|hysteria|zivpn|sshws|ssl_tls|udp-custom|badvpn|dropbear-custom|ws-dropbear|nftables-nat|nftables-restore|nftables-tunnel"
    units = sh(f"systemctl list-unit-files 2>/dev/null | awk '{{print $1}}' | grep -E '^({pats})[-@]?[^.]*\\.(service|timer)$' | sort -u")
    for u in units.splitlines():
        sh(f"systemctl disable --now {u} 2>/dev/null || true")
    for pat in ["kighmu-*","kighmu@*","xray*","v2ray*","slowdns*","dnsdist*","haproxy*","hysteria*","zivpn*","sshws*","ssl_tls*","udp-custom*","badvpn-*","badvpn@*","dropbear-custom*","ws-dropbear*","nftables-nat*","nftables-restore*","nftables-tunnel@*"]:
        for f in Path("/etc/systemd/system").glob(pat):
            sh(f"rm -rf {f} 2>/dev/null || true")
    for b in ["kighmu","kighmu.bak","kighmu-panel","kighmu-panel.sh","kighmu.pps_backup","kighmu-bot","kighmu-watchdog.sh","menu","menu.pps_backup","menu-ssh","install2","panel_install.py","ventes","sshws","ssl_tls","xray","v2ray","dnstt-server","dnstt-client","badvpn-udpgw","udp-custom","hysteria-linux-amd64","zivpn","slowdns-ns4-start.sh","slowdns-nv4-start.sh","slowdns-watchdog.sh","init-nftables-kighmu.sh"]:
        sh(f"rm -f /usr/local/bin/{b} 2>/dev/null || true")
    sh("rm -f /usr/local/bin/xray-* /usr/local/bin/dropbear* /usr/local/sbin/dropbear 2>/dev/null || true")
    for u in panel_system_accounts():
        sh(f"userdel -f {u} 2>/dev/null || true")
        sh(f"rm -rf /home/{u} 2>/dev/null || true")
    if USERDIR.exists():
        for uf in USERDIR.iterdir():
            if uf.is_file() and _meta_get(uf.name, "proto") == "ssh":
                sh(f"userdel -f {uf.name} 2>/dev/null || true")
    for d in ["/etc/kighmu","/etc/ventes","/etc/xray","/etc/v2ray","/etc/slowdns","/etc/hysteria","/etc/zivpn","/etc/udp-custom","/etc/dnsdist","/etc/nftables","/etc/haproxy","/etc/sshws","/etc/ssl_tls","/etc/dropbear","/etc/logrotate.d/slowdns"]:
        sh(f"rm -rf {d} 2>/dev/null || true")
    for d in ["/var/log/xray","/var/log/slowdns","/var/log/hysteria","/var/log/v2ray","/var/log/sshws","/var/log/ssl_tls","/var/log/zivpn","/var/log/kighmu"]:
        sh(f"rm -rf {d} 2>/dev/null || true")
    for f in ["/var/log/haproxy.log*","/var/log/haproxy-watchdog.log","/var/log/hysteria.log","/var/log/zivpn.log","/var/log/udp-custom.log","/var/log/kighmu-bot.log","/var/log/kighmu-install.log","/var/log/kighmu-panel.log","/var/log/kighmu-reseller-*.log","/var/log/xray-watchdog.log","/var/log/v2ray_watchdog.log*","/var/log/v2ray_install.log","/var/log/restart_v2ray.log","/var/log/slowdns-watchdog.log","/var/log/auto-clean.log","/var/log/dnsdist*"]:
        sh(f"rm -rf {f} 2>/dev/null || true")
    for f in ["/etc/sysctl.d/99-kighmu.conf","/etc/sysctl.d/99-slowdns.conf"]:
        Path(f).unlink(missing_ok=True)
    sh("chattr -i /etc/resolv.conf 2>/dev/null || true")
    Path("/etc/resolv.conf").write_text("nameserver 1.1.1.1\nnameserver 8.8.8.8\n")
    sh("crontab -l > /root/crontab.backup 2>/dev/null || true")
    sh("crontab -r 2>/dev/null || true")
    sh("nft flush ruleset 2>/dev/null || true")
    if Path("/etc/nftables.conf").exists():
        sh("nft -f /etc/nftables.conf 2>/dev/null || true")
    sh("apt-get remove -y -qq haproxy dnsdist 2>/dev/null || true")
    sh("rm -rf /root/Kighmu /root/fasto /root/backup /tmp/nuitka-build /root/backup-* /root/backup_users*.json 2>/dev/null || true")
    sh("rm -f /root/install2.py /root/install2.bin /root/install.sh /root/ventes.sh /root/apply_and_check.sh /root/apply_xray.py /root/check_xray.py /root/check_tunnels.sh /root/auto_install.py 2>/dev/null || true")
    sh("sysctl --system 2>/dev/null || true")
    sh("systemctl daemon-reload && systemctl reset-failed 2>/dev/null || true")
    sh("rm -f /etc/systemd/system/kighmu-reseller-*.service /etc/systemd/system/slowdns-router.service /etc/systemd/system/xray-watchdog.* /etc/systemd/system/kighmu-watchdog.* /etc/systemd/system/slowdns-watchdog.* 2>/dev/null || true")
    sh("systemctl daemon-reload && systemctl reset-failed 2>/dev/null || true")
    print(f"\n {C['RED']}✔ Kighmu Panel — désinstallé complètement.{C['RST']}")
    sh("pkill -f kighmu 2>/dev/null || true; pkill -f install2 2>/dev/null || true; pkill -f ventes 2>/dev/null || true")
    os._exit(0)

def delete_user(user):
    f = USERDIR / user
    if not f.exists() and user not in panel_system_accounts(): return 2
    proto = _meta_get(user, "proto")
    had_file = f.exists()
    # Retirer le meta AVANT de régénérer les configs (v2raydns/zivpn/hysteria
    # reconstruisent depuis USERDIR : si le fichier existe encore, le user reste
    # dans la config => suppression incomplète lors du nettoyage).
    f.unlink(missing_ok=True)
    if proto == "ssh" or (not had_file and user in panel_system_accounts()):
        sh(f"userdel -f {user} 2>/dev/null || true")
        sh(f"rm -rf /home/{user} 2>/dev/null || true")
        sh(f"sed -i '/^{user}|/d' /etc/kighmu/users.list 2>/dev/null || true")
    elif proto in ("vmess","vless","trojan","xray"):
        for p in ("vmess","vless","trojan"):
            sh(f"jq '.{p} |= map(select(.email!=\"{user}\"))' {XRAY_USERS} > /tmp/xu.json 2>/dev/null && mv /tmp/xu.json {XRAY_USERS} 2>/dev/null")
        xray_build_config()
    else:
        if proto == "zivpn": zivpn_apply()
        elif proto == "hysteria": hysteria_apply()
        elif proto == "v2raydns": v2raydns_apply()
    if proto == "ssh": _ssh_quota_apply()
    return 0

def renew_user(user, days):
    if not (USERDIR / user).exists(): return 2
    proto = _meta_get(user, "proto"); exp = exp_in_days(days)
    keep = {}
    for k in ("used","quota_hit","locked","exp_lock","reseller","shell","passwd_set"):
        v = _meta_get(user, k)
        if v: keep[k] = v
    write_meta(user, proto, exp, _meta_get(user,"limit"), _meta_get(user,"pass"), _meta_get(user,"uuid"), _meta_get(user,"quota"))
    for k, v in keep.items(): _meta_set(user, k, v)
    if proto == "ssh": sh(f"chage -E {exp} {user} 2>/dev/null")
    elif proto == "v2raydns":
        if _meta_get(user,"locked")=="1" and (_meta_get(user,"exp_lock")=="1" or _meta_get(user,"quota_hit")=="1"):
            _meta_set(user,"exp_lock","0"); _meta_set(user,"quota_hit","0"); _meta_set(user,"locked","0")
        v2raydns_apply()
    elif proto in ("vmess","vless","trojan","xray"):
        if _meta_get(user,"locked")=="1" and (_meta_get(user,"exp_lock")=="1" or _meta_get(user,"quota_hit")=="1"):
            _meta_set(user,"exp_lock","0"); _meta_set(user,"quota_hit","0"); _meta_set(user,"locked","0")
        xray_build_config()
    elif proto == "zivpn":
        if _meta_get(user,"locked")=="1" and _meta_get(user,"exp_lock")=="1":
            _meta_set(user,"exp_lock","0"); _meta_set(user,"locked","0")
        zivpn_apply()
    elif proto == "hysteria":
        if _meta_get(user,"locked")=="1" and _meta_get(user,"exp_lock")=="1":
            _meta_set(user,"exp_lock","0"); _meta_set(user,"locked","0")
        hysteria_apply()
    if proto == "ssh": _ssh_expiry_unlock(user)
    return 0

def set_user_quota(user, quota):
    if not (USERDIR/user).exists(): return False
    _meta_set(user, "quota", str(quota))
    proto=_meta_get(user,"proto")
    if proto in ("vmess","vless","trojan","xray"):
        if _meta_get(user,"quota_hit")=="1":
            _meta_set(user,"quota_hit","0"); _meta_set(user,"locked","0")
        xray_build_config()
    elif proto=="v2raydns":
        if _meta_get(user,"quota_hit")=="1":
            _meta_set(user,"quota_hit","0"); _meta_set(user,"locked","0")
        v2raydns_apply()
    elif proto=="ssh":
        if _meta_get(user,"quota_hit")=="1":
            _meta_set(user,"quota_hit","0")
            unlock_user(user)
        _ssh_quota_apply()
    return True

def lock_user(user):
    if not (USERDIR / user).exists(): return 2
    proto = _meta_get(user, "proto")
    if proto == "ssh": sh(f"passwd -l {user} &>/dev/null")
    _meta_set(user, "locked", "1")
    if proto == "v2raydns": v2raydns_apply()
    elif proto == "zivpn": zivpn_apply()
    elif proto == "hysteria": hysteria_apply()
    return 0
def unlock_user(user):
    if not (USERDIR / user).exists(): return 2
    proto = _meta_get(user, "proto")
    if proto == "ssh": sh(f"passwd -u {user} &>/dev/null")
    _meta_set(user, "locked", "0")
    if proto == "v2raydns": v2raydns_apply()
    elif proto == "zivpn": zivpn_apply()
    elif proto == "hysteria": hysteria_apply()
    return 0

def change_password(user, newpass=""):
    if not (USERDIR / user).exists(): return ""
    proto = _meta_get(user, "proto"); newpass = newpass or gen_pass()
    if proto == "ssh": sh(f"echo '{user}:{newpass}' | chpasswd 2>/dev/null")
    elif proto == "trojan":
        _meta_set(user, "pass", newpass)
        xray_build_config()
    else:
        if proto == "zivpn": zivpn_apply()
        elif proto == "hysteria": hysteria_apply()
        elif proto == "v2raydns": v2raydns_apply()
    _meta_set(user, "pass", newpass)
    return newpass

def delete_expired_users():
    today = date.today().isoformat(); n = 0
    if not USERDIR.exists(): return 0
    for f in list(USERDIR.iterdir()):
        if not f.is_file(): continue
        e = _meta_get(f.name, "exp")
        if e and e < today and delete_user(f.name) == 0: n += 1
    return n

def quota_enforce():
    """Bloque les comptes ayant dépassé leur quota de données (ou expirés) :
    Xray/V2Ray-DNS sont retirés des configs JSON, SSH est verrouillé.
    Réactive automatiquement un compte dès que son quota est remis et qu'il
    repasse sous la limite. Appelé régulièrement par cron (--quota-enforce)."""
    today = date.today().isoformat()
    if not USERDIR.exists(): return (0, 0)
    blocked = restored = 0
    xray_changed = v2ray_changed = False
    for f in list(USERDIR.iterdir()):
        if not f.is_file(): continue
        user = f.name
        proto = _meta_get(user, "proto")
        q = float(_meta_get(user, "quota") or "0")
        exp = _meta_get(user, "exp")
        expired = bool(exp) and exp != "permanent" and exp < today
        if proto == "ssh":
            if expired:
                if not is_locked(user):
                    _meta_set(user, "locked", "1"); _meta_set(user, "exp_lock", "1")
                    sh(f"passwd -l {user} 2>/dev/null || true"); blocked += 1
            elif q > 0 and get_ssh_traffic(user) >= q * 1024**3:
                if not is_locked(user):
                    _meta_set(user, "quota_hit", "1"); _meta_set(user, "locked", "1")
                    sh(f"passwd -l {user} 2>/dev/null || true")
                    _ssh_tracker_kill(user, _ssh_tracker_state()); blocked += 1
            elif is_locked(user) and _meta_get(user, "quota_hit") == "1" and not expired and (q <= 0 or get_ssh_traffic(user) < q * 1024**3):
                _meta_set(user, "quota_hit", "0"); unlock_user(user); _ssh_quota_apply(); restored += 1
        elif proto in ("vmess","vless","trojan"):
            if expired or (q > 0 and get_xray_traffic(user) >= q * 1024**3):
                if not is_locked(user):
                    _meta_set(user, "locked", "1"); _meta_set(user, "quota_hit", "1"); xray_changed = True; blocked += 1
            elif is_locked(user) and _meta_get(user, "quota_hit") == "1" and not expired and (q <= 0 or get_xray_traffic(user) < q * 1024**3):
                _meta_set(user, "locked", "0"); _meta_set(user, "quota_hit", "0"); xray_changed = True; restored += 1
        elif proto == "v2raydns":
            if expired or (q > 0 and get_v2ray_traffic(user) >= q * 1024**3):
                if not is_locked(user):
                    _meta_set(user, "locked", "1"); _meta_set(user, "quota_hit", "1"); v2ray_changed = True; blocked += 1
            elif is_locked(user) and _meta_get(user, "quota_hit") == "1" and not expired and (q <= 0 or get_v2ray_traffic(user) < q * 1024**3):
                _meta_set(user, "locked", "0"); _meta_set(user, "quota_hit", "0"); v2ray_changed = True; restored += 1
        elif proto in ("zivpn","hysteria"):
            if expired and not is_locked(user):
                _meta_set(user, "locked", "1"); _meta_set(user, "exp_lock", "1")
                if proto == "zivpn": zivpn_apply()
                else: hysteria_apply()
                blocked += 1
    if xray_changed: xray_build_config()
    if v2ray_changed: v2raydns_apply()
    return (blocked, restored)

def _ssh_expiry_enforce():
    """Lock SSH accounts whose expiry has passed. Dropbear ignores shadow expiry
    (no PAM), so the only reliable block is `passwd -l`. Called from the 5-min cron."""
    today = date.today().isoformat()
    n = 0
    if not USERDIR.exists(): return 0
    for f in list(USERDIR.iterdir()):
        if not f.is_file(): continue
        user = f.name
        if _meta_get(user, "proto") != "ssh": continue
        e = _meta_get(user, "exp")
        if not e or e == "permanent" or e >= today: continue
        if _meta_get(user, "locked") == "1": continue
        sh(f"passwd -l {user} 2>/dev/null || true")
        _meta_set(user, "locked", "1")
        _meta_set(user, "exp_lock", "1")
        n += 1
    return n

def _ssh_expiry_unlock(user):
    if not user or not (USERDIR / user).is_file(): return
    if _meta_get(user, "exp_lock") != "1": return
    sh(f"passwd -u {user} 2>/dev/null || true")
    _meta_set(user, "locked", "0")
    _meta_set(user, "exp_lock", "0")

def vmess_link_b64(uuid, host, port, net, tls, path_or_svc, ps, sni):
    obj = {"v":"2","ps":ps,"add":host,"port":str(port),"id":uuid,"aid":"0","scy":"auto",
           "net":net,"type":"multi" if net=="grpc" else "none","path":path_or_svc,"tls":tls,"sni":sni}
    if net == "ws": obj["host"] = host
    return "vmess://" + base64.urlsafe_b64encode(json.dumps(obj, separators=(',',':')).encode()).decode().rstrip("=")

def exp_color(d):
    if not d: return f"{C['GREEN']}permanent{C['RST']}"
    try:
        days = (datetime.strptime(d,"%Y-%m-%d").date() - date.today()).days
        if days < 0: return f"{C['RED']}{d} (expired){C['RST']}"
        if days <= 7: return f"{C['YELLOW']}{d} ({days}d left){C['RST']}"
        return f"{C['GREEN']}{d} ({days}d left){C['RST']}"
    except: return f"{C['WHITE']}{d}{C['RST']}"

def push_header(out, mode, *menu_lines):
    out.append("%SEP%")
    for ln in menu_lines: out.append(ln)
    if mode == "full": out.append(f" {C['YELLOW']}○{C['RST']} {C['WHITE']}SCRIPT :{C['RST']} {C['WHITE']}Kighmu Panel{C['RST']}   {C['GRAY']}•{C['RST']}   {C['WHITE']}VERSION :{C['RST']} {C['GREEN']}{VERSION}{C['RST']}")
    out.extend(["%SEP%", f" {C['KEYBG']} Key: [ {_client_name()} ] {C['RST']}", "%SEP%"])

# Screen functions
def scr_main():
    TOT=count_total_users();EXP=count_expired()
    DW,WW,MW=_vnstat_data()
    OS=get_os();ARCH=get_arch();CORES=get_cores();DT=get_datetime()
    IP=get_ipv6() or get_ipv4()
    RT=ram_total_g();RF=ram_free_g();RU=ram_used_g();RPCT=ram_pct();CPCT=cpu_pct();BUF=ram_buffer_m()
    ports=[("SSH","22","sshd"),("Dropbear","109","dropbear-custom"),("V2Ray-DNS","5401","v2ray"),
           ("HAProxy","447","haproxy"),("SSH-WS","80","sshws"),("SSH-SSL","444","ssl_tls"),
            ("Xray","8880/443","xray"),("SlowDNS","5300","dnsdist"),("ZIVPN","5667","zivpn"),
           ("Hysteria","20000","hysteria"),("BadVPN","7100-7300","badvpn-7100"),("UDP-Custom","36712","udp-custom")]
    cw=max(len(f"{n}: {p}") for n,p,_ in ports) if ports else 20
    pg=[""]
    for i,(n,p,s) in enumerate(ports):
        d=f"{n}: {p}"
        dot_s=f"{C['GREEN']}●{C['RST']}" if _svc_ready(s) else f"{C['RED']}○{C['RST']}"
        c=f" {dot_s} {C['WHITE']}{d:<{cw}}{C['RST']} "
        if i%3==0 and i>0: pg.append("")
        pg[-1]+=c
    ST_OPT=flag_status("optimized");ST_AUTO=flag_status("autostart")
    ml=["MANAGE USERS (SSH/XRAY/V2RAY/ZIVPN/HYSTERIA)","OPTIMIZE VPS","AUTO-START SCRIPT","PROTOCOL INSTALLER"]
    mw=max(len(l) for l in ml)
    mi=[f" {C['GREEN']}[01]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ml[0]}{C['RST']}",
        f" {C['GREEN']}[02]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ml[1]:<{mw}}{C['RST']}  {ST_OPT}",
        f" {C['GREEN']}[03]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ml[2]:<{mw}}{C['RST']}  {ST_AUTO}",
        f" {C['GREEN']}[04]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ml[3]}{C['RST']}"]
    L=["%SEP%"]+[f"{C['CYAN']}{b}{C['RST']}" for b in BANNER]+[
        "%SEP%",f" {C['YELLOW']}○{C['RST']} {C['WHITE']}USERS:{C['RST']} {C['WHITE']}[{TOT}]{C['RST']}  {C['GRAY']}•{C['RST']}  {C['WHITE']}EXP:{C['RST']} {C['RED']}[{EXP}]{C['RST']}  {C['GRAY']}•{C['RST']}  {C['WHITE']}TRAFIC (D/W/M):{C['RST']} {C['GREEN']}{DW}{C['RST']}/{C['YELLOW']}{WW}{C['RST']}/{C['RED']}{MW}{C['RST']}",
        f" {C['YELLOW']}○{C['RST']} {C['WHITE']}S.O:{C['RST']} {C['WHITE']}{OS}{C['RST']}  {C['GRAY']}•{C['RST']}  {C['WHITE']}Base:{C['RST']} {C['WHITE']}{ARCH}{C['RST']}  {C['GRAY']}•{C['RST']}  {C['WHITE']}CPU's:{C['RST']} {C['WHITE']}{CORES}{C['RST']}",
        f" {C['YELLOW']}○{C['RST']} {C['WHITE']}IP:{C['RST']} {C['WHITE']}{IP}{C['RST']}  {C['GRAY']}•{C['RST']}  {C['WHITE']}TIME:{C['RST']} {C['WHITE']}{DT}{C['RST']}",
        "%SEP%",f" {C['KEYBG']} Key: [ {_client_name()} ] {C['RST']}   {C['GRAY']}({VERSION}){C['RST']}","%SEP%"]
    L+=pg+["%SEP%",
        f" {C['WHITE']}TOTAL:{C['RST']} {C['WHITE']}{RT}G{C['RST']}  {C['GRAY']}•{C['RST']}  {C['WHITE']}M|LIBRE:{C['RST']} {C['GREEN']}{RF}G{C['RST']}  {C['GRAY']}•{C['RST']}  {C['WHITE']}EN USO:{C['RST']} {C['YELLOW']}{RU}G{C['RST']}",
        f" {C['WHITE']}U/RAM:{C['RST']} {pct_color(RPCT)}  {C['GRAY']}•{C['RST']}  {C['WHITE']}U/CPU:{C['RST']} {pct_color(CPCT)}  {C['GRAY']}•{C['RST']}  {C['WHITE']}BUFFER:{C['RST']} {C['WHITE']}{BUF}M{C['RST']}","%SEP%"]+mi+[
        "%SEP%",f" {C['GREEN']}[05]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}UPDATE / REMOVE{C['RST']}     {C['GRAY']}|{C['RST']}     {C['BTNBG']} [0] ⇦ [ EXIT ] {C['RST']}","%SEP%"]
    render_panel(L)

def scr_manage_users():
    TOT=count_total_users();EXP=count_expired()
    L=[];push_header(L,"full",f" {C['YELLOW']}○{C['RST']} {C['WHITE']}MENU :{C['RST']} {C['WHITE']}MANAGE USERS{C['RST']}")
    L+=[f" {C['YELLOW']}○{C['RST']} {C['WHITE']}TOTAL USERS:{C['RST']} {C['WHITE']}[{TOT}]{C['RST']}        {C['YELLOW']}○{C['RST']} {C['WHITE']}EXPIRED:{C['RST']} {C['RED']}[{EXP}]{C['RST']}","%SEP%",
        f" {C['GREEN']}[01]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}SSH (WS/SSL/SlowDNS/UDP-Custom/BadVPN){C['RST']}",
        f" {C['GREEN']}[02]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}XRAY (Vmess/Vless/Trojan){C['RST']}",
        f" {C['GREEN']}[03]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}V2RAY-DNS{C['RST']}",
        f" {C['GREEN']}[04]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}ZIVPN{C['RST']}",
        f" {C['GREEN']}[05]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}HYSTERIA{C['RST']}","%SEP%",
        f" {C['BTNBG']} [0] ⇦ [ BACK TO MAIN MENU ] {C['RST']}","%SEP%"]
    render_panel(L)

def scr_optimize():
    SG=flag_status("optimized");SB=bbr_status();SL=loglimit_status();SS=sysctl_status();LO=last_optimized()
    ol=["ENABLE OPTIMIZATION","BBR (TCP CONGESTION CONTROL)","SWAP CONFIGURATION","CLEAN CACHE / TEMP FILES",
        "LIMIT LOG SIZE (JOURNALCTL)","CLEAN TUNNEL LOGS","DISABLE UNUSED SERVICES","NETWORK / SYSCTL TUNING",
        "RUN FULL OPTIMIZATION (ALL ABOVE)","RESTORE DEFAULT SETTINGS"]
    ow=max(len(l) for l in ol)
    L=[];push_header(L,"full",f" {C['YELLOW']}○{C['RST']} {C['WHITE']}MENU :{C['RST']} {C['WHITE']}OPTIMIZE VPS{C['RST']}")
    L.append(f" {C['YELLOW']}○{C['RST']} {C['WHITE']}STATUS:{C['RST']} {SG}        {C['YELLOW']}○{C['RST']} {C['WHITE']}LAST OPTIMIZED:{C['RST']} {C['WHITE']}{LO}{C['RST']}")
    L.append("%SEP%")
    L+=[f" {C['GREEN']}[01]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ol[0]:<{ow}}{C['RST']}  {SG}",
        f" {C['GREEN']}[02]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ol[1]:<{ow}}{C['RST']}  {SB}",
        f" {C['GREEN']}[03]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ol[2]}{C['RST']}",
        f" {C['GREEN']}[04]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ol[3]}{C['RST']}",
        f" {C['GREEN']}[05]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ol[4]:<{ow}}{C['RST']}  {SL}",
        f" {C['GREEN']}[06]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ol[5]}{C['RST']}",
        f" {C['GREEN']}[07]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ol[6]}{C['RST']}",
        f" {C['GREEN']}[08]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ol[7]:<{ow}}{C['RST']}  {SS}"]
    L+=["%SEP%",f" {C['GREEN']}[09]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['GREEN']}{ol[8]}{C['RST']}",
        f" {C['GREEN']}[10]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ol[9]:<{ow}}{C['RST']}  {C['RED']}[!]{C['RST']}",
        "%SEP%",f" {C['BTNBG']} [0] ⇦ [ BACK TO MAIN MENU ] {C['RST']}","%SEP%"]
    render_panel(L)

def scr_protocol_installer():
    st={"ssh":proto_on("dropbear-custom","dropbear"),"ws":proto_on("sshws","ws-epro"),
        "ssl":proto_on("ssl_tls"),"xray":proto_on("xray"),"v2ray":proto_on("v2ray"),
        "badvpn":proto_on("badvpn-udpgw"),"udp":proto_on("udp-custom"),
        "slowdns":proto_on("dnsdist","slowdns-ns4","slowdns-nv4"),
        "hyst":proto_on("hysteria"),"zivpn":proto_on("zivpn"),
        "bot":Path("/usr/local/bin/kighmu").exists() and sh("systemctl is-active kighmu-bot 2>/dev/null")=="active"}
    pl=["SSH / DROPBEAR","WS-EPRO (SSH-WS)","SSL / TLS","XRAY (VMESS/VLESS/TROJAN)","V2RAY-DNS",
        "BADVPN (UDPGW)","UDP CUSTOM","SLOWDNS","HYSTERIA","ZIVPN","INSTALL ALL MISSING","UNINSTALL ALL ACTIVE","TELEGRAM BOT"]
    pw=max(len(l) for l in pl)
    def pil(i,l,s,w):
        sc=f"{C['GREEN']}[ON]{C['RST']} " if s else f"{C['RED']}[OFF]{C['RST']}"
        ac=f"{C['YELLOW']}⇨{C['RST']} {C['RED']}[ Uninstall ]{C['RST']}" if s else f"{C['YELLOW']}⇨{C['RST']} {C['GREEN']}[ Install ]{C['RST']}"
        return f" {C['GREEN']}[{i}]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{l:<{pw}}{C['RST']}  {sc}   {ac}"
    L=[];push_header(L,"full",f" {C['YELLOW']}○{C['RST']} {C['WHITE']}MENU :{C['RST']} {C['WHITE']}PROTOCOL INSTALLER{C['RST']}")
    sv=list(st.values())
    L+=[pil(f"{i+1:02d}",pl[i],sv[i] if i<len(sv) else False,pw) for i in range(10)]
    L+=["%SEP%",f" {C['GREEN']}[11]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['GREEN']}{pl[10]}{C['RST']}",
        f" {C['GREEN']}[12]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{pl[11]:<{pw}}{C['RST']}  {C['RED']}[!]{C['RST']}"]
    haproxy_st = f"{C['GREEN']}[ON]{C['RST']}" if Path("/etc/xray/config.json").exists() and sh("systemctl is-active haproxy 2>/dev/null") == "active" else f"{C['RED']}[OFF]{C['RST']}"
    bst = st["bot"]
    L+=[f" {C['GREEN']}[13]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['GREEN']}INSTALL TELEGRAM BOT{C['RST']}",
        f" {C['GREEN']}[14]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['RED']}UNINSTALL TELEGRAM BOT{C['RST']}" + (f"  {C['GREEN']}[ON]{C['RST']}" if bst else f"  {C['RED']}[OFF]{C['RST']}"),
        "%SEP%",
        f" {C['YELLOW']}○{C['RST']} {C['GRAY']}Dependencies (auto-installed with Xray):{C['RST']}",
        f" {C['YELLOW']}○{C['RST']} {C['WHITE']}HAProxy{C['RST']} {haproxy_st}          {C['GRAY']}(TLS 443 / NTLS 8880){C['RST']}",
        "%SEP%",f" {C['BTNBG']} [0] ⇦ [ BACK TO MAIN MENU ] {C['RST']}","%SEP%"]
    render_panel(L)

def scr_update_remove():
    SB=flag_status("backup_before_update")
    ul=["CHECK FOR UPDATES","DOMAIN & TUNNEL SETTINGS","UPDATE SCRIPT (LATEST VERSION)","CHANGELOG / VERSION HISTORY",
        "BACKUP BEFORE UPDATE","REINSTALL SCRIPT (CLEAN)","REMOVE SCRIPT (UNINSTALL)"]
    uw=max(len(l) for l in ul)
    L=[];push_header(L,"full",f" {C['YELLOW']}○{C['RST']} {C['WHITE']}MENU :{C['RST']} {C['WHITE']}UPDATE / REMOVE{C['RST']}")
    L+=[f" {C['GREEN']}[01]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ul[0]:<{uw}}{C['RST']}  {C['RED']}[!]{C['RST']}",
        f" {C['GREEN']}[02]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ul[1]:<{uw}}{C['RST']}  {C['RED']}[!]{C['RST']}",
        f" {C['GREEN']}[03]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ul[2]}{C['RST']}",
        f" {C['GREEN']}[04]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ul[3]}{C['RST']}",
        f" {C['GREEN']}[05]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ul[4]:<{uw}}{C['RST']}  {SB}",
        f" {C['GREEN']}[06]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['RED']}{ul[5]:<{uw}}{C['RST']}  {C['RED']}[!]{C['RST']}",
        f" {C['GREEN']}[07]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['RED']}{ul[6]:<{uw}}{C['RST']}  {C['RED']}[!]{C['RST']}",
        "%SEP%",f" {C['BTNBG']} [0] ⇦ [ BACK TO MAIN MENU ] {C['RST']}","%SEP%"]
    render_panel(L)

def scr_domain_tunnel():
    ul=["CHANGE / UPDATE DOMAIN","UPDATE DOMAIN + ACME TLS (XRAY)","CHANGE SLOWDNS NAMESERVERS (NS)"]
    uw=max(len(l) for l in ul)
    L=[];push_header(L,"full",f" {C['YELLOW']}○{C['RST']} {C['WHITE']}MENU :{C['RST']} {C['WHITE']}DOMAIN & TUNNEL{C['RST']}")
    L+=[f" {C['GREEN']}[01]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ul[0]:<{uw}}{C['RST']}",
        f" {C['GREEN']}[02]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ul[1]:<{uw}}{C['RST']}",
        f" {C['GREEN']}[03]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}{ul[2]:<{uw}}{C['RST']}",
        "%SEP%",f" {C['BTNBG']} [0] ⇦ [ BACK TO UPDATE / REMOVE MENU ] {C['RST']}","%SEP%"]
    render_panel(L)

def _get_current_domain():
    df = Path("/etc/kighmu/domain.txt")
    return df.read_text().strip() if df.exists() else ""

def _valid_domain(d):
    return "." in d and bool(re.match(r'^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$', d))

def _ui_change_domain():
    cur = _get_current_domain()
    print(f" {C['YELLOW']}○{C['RST']} {C['WHITE']}CHANGE / UPDATE DOMAIN{C['RST']}")
    print(f" {C['GRAY']}Current domain: {C['GREEN']}{cur or 'none'}{C['RST']}\n")
    nd = input(f" {C['YELLOW']}►{C['RST']} {C['WHITE']}New domain (empty = cancel): {C['RST']}").strip().lower()
    if not nd:
        print(f" {C['YELLOW']}⚠ Annulé.{C['RST']}");return
    if not _valid_domain(nd):
        print(f" {C['RED']}✗ Domaine invalide.{C['RST']}");return
    if nd == cur:
        print(f" {C['YELLOW']}⚠ Domain unchanged.{C['RST']}");return
    Path("/etc/kighmu/domain.txt").write_text(nd + "\n")
    print(f" {C['GREEN']}✔ Domain updated: {C['WHITE']}{cur or 'none'} → {nd}{C['RST']}")
    print(f" {C['GRAY']}Note: DNS A/AAAA de {nd} doit pointer vers l'IP du serveur.{C['RST']}")

def _xray_rebuild_pem():
    crt=Path("/etc/xray/fullchain.pem")
    key=Path("/etc/xray/privkey.pem")
    if crt.exists() and key.exists():
        sh(f"cat {crt} {key} > /etc/xray/xray.pem 2>/dev/null || true")
        sh(f"cat {crt} {key} > /etc/haproxy/panel.pem 2>/dev/null || true")
        sh("chmod 600 /etc/xray/xray.pem /etc/haproxy/panel.pem 2>/dev/null || true")

def _ui_domain_acme_xray():
    cur = _get_current_domain()
    print(f" {C['YELLOW']}○{C['RST']} {C['WHITE']}UPDATE DOMAIN + ACME TLS (XRAY){C['RST']}")
    print(f" {C['GRAY']}Current domain: {C['GREEN']}{cur or 'none'}{C['RST']}\n")
    nd = input(f" {C['YELLOW']}►{C['RST']} {C['WHITE']}New domain (empty = reuse current): {C['RST']}").strip().lower()
    if nd:
        if not _valid_domain(nd):
            print(f" {C['RED']}✗ Domaine invalide.{C['RST']}");return
        Path("/etc/kighmu/domain.txt").write_text(nd + "\n")
        print(f" {C['GREEN']}✔ Domain updated: {nd}{C['RST']}")
    else:
        nd = cur
        if not nd:
            print(f" {C['RED']}✗ No domain configured.{C['RST']}");return
    if sh("command -v xray 2>/dev/null") == "":
        print(f" {C['RED']}✗ Xray non installé.{C['RST']}");return
    ok=_acme_cert(nd, "/etc/xray")
    if not ok:
        print(f" {C['YELLOW']}⚠ Certificat auto-signé utilisé.{C['RST']}")
    _xray_rebuild_pem()
    xray_gen_haproxy()
    sh("systemctl reload haproxy 2>/dev/null || systemctl restart haproxy 2>/dev/null || true")
    print(f" {C['GREEN']}✔ Xray tunnel mis à jour pour {nd}.{C['RST']}")

def menu_domain_tunnel():
    while True:
        scr_domain_tunnel();CH=input().strip()
        if CH in("1","01"): _ui_change_domain();press_enter()
        elif CH in("2","02"): _ui_domain_acme_xray();press_enter()
        elif CH in("3","03"): configure_slowdns();press_enter()
        elif CH in("0",): return

# Optimization
def opt_enable():
    STATEDIR.mkdir(parents=True,exist_ok=True);(STATEDIR/"optimized").write_text(get_datetime())
    print(f" {C['GREEN']}✔{C['RST']} {C['WHITE']}Optimization enabled.{C['RST']}")
def opt_bbr():
    sh("modprobe tcp_bbr 2>/dev/null || true; modprobe sch_fq 2>/dev/null || true")
    sh("echo 'tcp_bbr' >> /etc/modules-load.d/bbr.conf 2>/dev/null || true")
    sh("sysctl -w net.ipv4.tcp_congestion_control=bbr 2>/dev/null")
    print(f" {C['GREEN']}✔{C['RST']} {C['WHITE']}BBR enabled.{C['RST']}")
def opt_swap():
    sh("fallocate -l 1G /swapfile 2>/dev/null || dd if=/dev/zero of=/swapfile bs=1M count=1024 2>/dev/null")
    sh("chmod 600 /swapfile && mkswap /swapfile 2>/dev/null && swapon /swapfile 2>/dev/null")
    if not sh("grep swapfile /etc/fstab 2>/dev/null"): sh("echo '/swapfile none swap sw 0 0' >> /etc/fstab")
def opt_clean():
    sh("apt-get clean 2>/dev/null || true; journalctl --vacuum-time=3d 2>/dev/null || true; rm -rf /tmp/* 2>/dev/null || true")
    print(f" {C['GREEN']}✔{C['RST']} {C['WHITE']}Cache cleaned.{C['RST']}")
def opt_loglimit():
    sh("echo 'SystemMaxUse=50M' >> /etc/systemd/journald.conf 2>/dev/null || true; systemctl restart systemd-journald 2>/dev/null || true")
    print(f" {C['GREEN']}✔{C['RST']} {C['WHITE']}Log limit set.{C['RST']}")
def opt_logclean():
    sh("find /var/log -name '*.log' -mtime +6 -delete 2>/dev/null || true; find /var/log -name '*.gz' -delete 2>/dev/null || true")
    sh("truncate -s 0 /var/log/syslog 2>/dev/null || true")
    print(f" {C['GREEN']}✔{C['RST']} {C['WHITE']}Old logs cleaned.{C['RST']}")
def opt_disable_services():
    for s in ["cups","bluetooth","avahi-daemon","postfix","snapd"]: sh(f"systemctl disable --now {s} 2>/dev/null || true")
    print(f" {C['GREEN']}✔{C['RST']} {C['WHITE']}Unused services disabled.{C['RST']}")
def opt_sysctl():
    kv={"net.core.rmem_default":67108864,"net.core.wmem_default":67108864,"net.core.rmem_max":67108864,"net.core.wmem_max":67108864,
        "net.core.netdev_max_backlog":50000,"net.core.optmem_max":67108864,"net.core.default_qdisc":"fq",
        "net.ipv4.tcp_congestion_control":"bbr","net.ipv4.ip_forward":1,"net.ipv4.udp_mem":"25600 51200 102400",
        "fs.file-max":512000,"net.ipv4.tcp_fastopen":3,"net.ipv4.tcp_mtu_probing":1,"net.ipv4.tcp_syncookies":1,
        "net.ipv4.tcp_tw_reuse":1,"net.ipv4.tcp_fin_timeout":30,"net.ipv4.tcp_keepalive_time":1200,
        "net.ipv4.ip_local_port_range":"1024 65535","net.ipv4.tcp_slow_start_after_idle":0}
    Path("/etc/sysctl.d/99-kighmu.conf").write_text("\n".join(f"{k}={v}" for k,v in kv.items())+"\n")
    sh("sysctl --system 2>/dev/null || true");print(f" {C['GREEN']}✔{C['RST']} {C['WHITE']}Sysctl tuning applied.{C['RST']}")
def opt_full():
    for fn in[opt_bbr,opt_swap,opt_clean,opt_loglimit,opt_logclean,opt_disable_services,opt_sysctl]: fn()
    opt_enable()
def opt_restore():
    Path("/etc/sysctl.d/99-kighmu.conf").unlink(missing_ok=True);sh("sysctl --system 2>/dev/null || true")
    f=STATEDIR/"optimized";f.exists() and f.unlink()
    print(f" {C['YELLOW']}⚠{C['RST']} {C['WHITE']}Default settings restored.{C['RST']}")
def toggle_flag(name):
    STATEDIR.mkdir(parents=True,exist_ok=True);f=STATEDIR/name
    f.unlink() if f.exists() else f.write_text("1")

def cleanup_panel_residues():
    for f in Path("/root").iterdir():
        if f.is_file() and f.suffix in (".sh",".exp",".py") and f.name not in ("install.sh","install2.py","ventes.sh"):
            if f.name in ("ssh.sh","udp.sh","xray-v2ray.sh","install-kighmu.exp","install2.sh.backup.original","restart_bins.sh","restart_v2ray.sh","start_bot.sh","restore_users.py","verify.py","uninstall_all.py"):
                f.unlink(missing_ok=True)
    for p in ["/root/PPS_TECH","/root/PPS","/root/panel","/etc/PPS_TECH","/etc/PPS"]:
        d=Path(p)
        if d.exists(): sh(f"rm -rf {p} 2>/dev/null || true")
    for svc in ["pps","PPS","PPS_TECH","menu-ssh","menu-ssh-v2"]:
        f=Path(f"/etc/systemd/system/{svc}.service")
        if f.exists(): f.unlink(); sh(f"systemctl disable {svc}.service 2>/dev/null || true")
    for m in ["/usr/local/bin/menu-ssh","/usr/local/bin/menu"]:
        p=Path(m)
        if p.exists():
            cnt=p.read_text() if p.is_file() else ""
            if "kighmu" not in cnt.lower():
                p.unlink(missing_ok=True)
    for f in Path("/etc").glob("*.bak"): f.unlink(missing_ok=True)
    for f in Path("/etc").glob("*_backup"): sh(f"rm -rf {f} 2>/dev/null || true")
    sh("pkill -f 'PPS_TECH' 2>/dev/null || true")
    sh("pkill -f 'menu-ssh' 2>/dev/null || true")

def main_menu():
    cleanup_panel_residues()
    while True:
        scr_main()
        CH=input().strip()
        if CH in("1","01"): menu_manage_users()
        elif CH in("2","02"): menu_optimize()
        elif CH in("3","03"): toggle_flag("autostart")
        elif CH in("4","04"): menu_protocol_installer()
        elif CH in("5","05"): menu_update_remove()
        elif CH in("0",): clear_screen();break

def menu_manage_users():
    cleanup_panel_residues()
    while True:
        scr_manage_users()
        CH=input().strip()
        if CH in("1","01"): submenu_family("SSH",["ssh"])
        elif CH in("2","02"): submenu_family("XRAY",["vmess","vless","trojan"])
        elif CH in("3","03"): submenu_family("V2RAY-DNS",["v2raydns"])
        elif CH in("4","04"): submenu_family("ZIVPN",["zivpn"])
        elif CH in("5","05"): submenu_family("HYSTERIA",["hysteria"])
        elif CH in("0",): return

def submenu_family(title,protos):
    cleanup_panel_residues()
    while True:
        TOT=fam_total(*protos);EXP=fam_expired(*protos)
        L=[];push_header(L,"full",f" {C['YELLOW']}○{C['RST']} {C['WHITE']}MENU :{C['RST']} {C['WHITE']}MANAGE USERS ▸ {title}{C['RST']}")
        L+=[f" {C['YELLOW']}○{C['RST']} {C['WHITE']}TOTAL {title} USERS:{C['RST']} {C['WHITE']}[{TOT}]{C['RST']}     {C['YELLOW']}○{C['RST']} {C['WHITE']}EXPIRED:{C['RST']} {C['RED']}[{EXP}]{C['RST']}",
            "%SEP%",
            f" {C['GREEN']}[01]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}CREATE USER{C['RST']}",
            f" {C['GREEN']}[02]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}LIST USERS{C['RST']}",
            f" {C['GREEN']}[03]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}DELETE USER{C['RST']}",
            f" {C['GREEN']}[04]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}RENEW / EXTEND USER{C['RST']}",
            f" {C['GREEN']}[05]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}LOCK / UNLOCK USER{C['RST']}",
            f" {C['GREEN']}[06]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}CHANGE PASSWORD{C['RST']}",
            f" {C['GREEN']}[07]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}CONNECTION INFO{C['RST']}",
            f" {C['GREEN']}[08]{C['RST']} {C['YELLOW']}⇨{C['RST']} {C['WHITE']}DELETE EXPIRED USERS (BULK){C['RST']}          {C['RED']}[!]{C['RST']}",
            "%SEP%",f" {C['BTNBG']} [0] ⇦ [ BACK TO MANAGE USERS ] {C['RST']}","%SEP%"]
        render_panel(L)
        CH=input().strip()
        if CH in("1","01"): ui_create_wizard(protos)
        elif CH in("2","02"): ui_list_users(title,protos)
        elif CH in("3","03"): ui_delete_wizard(protos)
        elif CH in("4","04"): ui_renew_wizard()
        elif CH in("5","05"): ui_lock_wizard()
        elif CH in("6","06"): ui_passwd_wizard()
        elif CH in("7","07"): ui_info_wizard()
        elif CH in("8","08"): ui_delete_expired_wizard()
        elif CH in("0",): return

def menu_optimize():
    cleanup_panel_residues()
    while True:
        scr_optimize();CH=input().strip()
        if CH in("1","01"): opt_enable()
        elif CH in("2","02"): opt_bbr()
        elif CH in("3","03"): opt_swap()
        elif CH in("4","04"): opt_clean()
        elif CH in("5","05"): opt_loglimit()
        elif CH in("6","06"): opt_logclean()
        elif CH in("7","07"): opt_disable_services()
        elif CH in("8","08"): opt_sysctl()
        elif CH in("9","09"): opt_full()
        elif CH in("10",): opt_restore()
        elif CH in("0",): return

def proto_action(title, install_fn, uninstall_fn, configure_fn=None):
    clear_screen()
    print(f" {C['CYAN']}{title}{C['RST']}\n")
    print(f"   {C['GREEN']}1{C['RST']}) Install / Repair")
    print(f"   {C['RED']}2{C['RST']}) Uninstall")
    if configure_fn:
        print(f"   {C['YELLOW']}3{C['RST']}) Configure")
    print(f"   {C['GRAY']}0{C['RST']}) Back")
    a = input(f"\n {C['YELLOW']}►{C['RST']} Choice: ").strip().translate({c:None for c in range(32)})
    if a == "1": install_fn()
    elif a == "2": uninstall_fn()
    elif a == "3" and configure_fn: configure_fn()
    press_enter()

def menu_protocol_installer():
    cleanup_panel_residues()
    while True:
        scr_protocol_installer();CH=input().strip()
        if CH in ("1","01"): proto_action("SSH / DROPBEAR (ports 22 / 109)", install_ssh_stack, uninstall_dropbear)
        elif CH in ("2","02"): proto_action("WS-EPRO (SSH-WS port 80)", install_sshws, uninstall_sshws)
        elif CH in ("3","03"): proto_action("SSL/TLS (port 444 → 109)", install_ssl_tls, uninstall_ssl_tls)
        elif CH in ("4","04"): proto_action("XRAY + HAProxy (443 / 8880 / 9898)", install_xray, uninstall_xray)
        elif CH in ("5","05"): proto_action("V2RAY-DNS (VLESS TCP 5401)", install_v2ray, uninstall_v2ray)
        elif CH in ("6","06"): proto_action("BADVPN (UDPGW 7100/7200/7300)", install_badvpn, uninstall_badvpn)
        elif CH in ("7","07"): proto_action("UDP CUSTOM (36712)", install_udp_custom, uninstall_udp_custom)
        elif CH in ("8","08"): proto_action("SLOWDNS (53/5353/5354)", install_slowdns, uninstall_slowdns, configure_slowdns)
        elif CH in ("9","09"): proto_action("HYSTERIA (20000-50000)", install_hysteria, uninstall_hysteria)
        elif CH in ("10",): proto_action("ZIVPN (5667 / 6000-19999)", install_zivpn, uninstall_zivpn)
        elif CH in ("11","12"): (install_all_missing if CH=="11" else uninstall_all_active)();press_enter()
        elif CH=="13": install_telegram_bot()
        elif CH=="14": uninstall_telegram_bot()
        elif CH=="0": return

def menu_update_remove():
    cleanup_panel_residues()
    while True:
        scr_update_remove();CH=input().strip()
        if CH in("1","01"): upd_check();press_enter()
        elif CH in("2","02"): menu_domain_tunnel()
        elif CH in("3","03"): upd_update();press_enter()
        elif CH in("4","04"): upd_changelog();press_enter()
        elif CH in("5","05"): toggle_flag("backup_before_update")
        elif CH in("6","06"): upd_reinstall();press_enter()
        elif CH in("7","07"): upd_remove()
        elif CH in("0",): return

def ui_create_wizard(protos):
    cleanup_panel_residues();clear_screen()
    proto=protos[0]
    if len(protos)>1:
        print(f" {C['YELLOW']}○{C['RST']} {C['WHITE']}CREATE USER — CHOOSE PROTOCOL{C['RST']}\n")
        for i,p in enumerate(protos,1):
            print(f"   {C['GREEN']}{i}{C['RST']}) {C['WHITE']}{p.upper()}{C['RST']}")
        print(f"   {C['GRAY']}0{C['RST']}) Cancel")
        sel=input(f"\n {C['YELLOW']}►{C['RST']} Protocol: ").strip()
        if not sel.isdigit() or int(sel)<1 or int(sel)>len(protos):
            press_enter();return
        proto=protos[int(sel)-1]
    clear_screen()
    print(f" {C['YELLOW']}○{C['RST']} {C['WHITE']}CREATE {proto.upper()} USER{C['RST']}\n")
    user=input(f" {C['YELLOW']}►{C['RST']} {C['WHITE']}Username: {C['RST']}").strip()
    if not valid_name(user): print(f" {C['RED']}✗ Invalid username{C['RST']}");press_enter();return
    if (USERDIR/user).exists(): print(f" {C['RED']}✗ User already exists{C['RST']}");press_enter();return
    ds=input(f" {C['YELLOW']}►{C['RST']} {C['WHITE']}Days (def 30): {C['RST']}").strip();days=int(ds) if ds.isdigit() else 30
    passwd=""
    if proto in("ssh","trojan","zivpn","hysteria"): passwd=input(f" {C['YELLOW']}►{C['RST']} {C['WHITE']}Password (empty=auto): {C['RST']}").strip()
    limit="1"
    if proto=="ssh": l=input(f" {C['YELLOW']}►{C['RST']} {C['WHITE']}Limit (def 1): {C['RST']}").strip();limit=l if l.isdigit() else "1"
    quota="0"
    if proto in("vmess","vless","trojan","v2raydns","ssh"):
        q=input(f" {C['YELLOW']}►{C['RST']} {C['WHITE']}Quota GB (0=unlimited): {C['RST']}").strip()
        quota=q if re.match(r'^[0-9]+\.?[0-9]*$',q) else "0"
    rc=create_user(proto,user,days,passwd,limit,quota)
    if rc==0:
        exp=_meta_get(user,"exp");p=_meta_get(user,"pass");uuid=_meta_get(user,"uuid");q=_meta_get(user,"quota") or "0"
        if proto=="ssh":
            clear_screen()
            show_ssh_details_screen("created",user,p or passwd,exp,q)
        elif proto in("vmess","vless","trojan","v2raydns"):
            clear_screen()
            show_detail_screen("created",proto.upper(),user,uuid=uuid,exp=exp,quota=q,passwd=p or passwd)
        elif proto=="zivpn":
            clear_screen()
            show_zivpn_details_screen("created",user,p or passwd,exp)
        elif proto=="hysteria":
            clear_screen()
            show_hysteria_details_screen("created",user,p or passwd,exp,q)
        else: print(f" {C['GREEN']}✔{C['RST']} {C['WHITE']}{proto.upper()} user '{user}' created.{C['RST']}");press_enter()
    elif rc==1: print(f" {C['RED']}✗ Invalid username{C['RST']}");press_enter()
    elif rc==2: print(f" {C['RED']}✗ User exists{C['RST']}");press_enter()
    else: print(f" {C['RED']}✗ System error{C['RST']}");press_enter()

def ui_list_users(title,protos):
    cleanup_panel_residues();clear_screen();L=[];today=date.today().isoformat()
    push_header(L,"simple",f" {C['YELLOW']}○{C['RST']} {C['WHITE']}MENU :{C['RST']} {C['WHITE']}{title} ▸ LIST USERS{C['RST']}")
    L+=[f" {'USERNAME':<14} {'EXPIRES':<10} {'STATUS':<8} {'TRAFFIC (USED/TOTAL)':<22}",
        f" {C['GRAY']}{'────────':<14} {'──────':<10} {'──────':<8} {'──────────────────':<22}{C['RST']}"]
    n=0
    if USERDIR.exists():
        for f in sorted(USERDIR.iterdir()):
            if not f.is_file(): continue
            p=_meta_get(f.name,"proto")
            if p not in protos: continue
            e=_meta_get(f.name,"exp")
            if _meta_get(f.name,"quota_hit")=="1": st=f"{C['RED']}QUOTA{C['RST']}"
            elif is_locked(f.name): st=f"{C['RED']}LOCKED{C['RST']}"
            elif e and e<today: st=f"{C['RED']}EXPIRED{C['RST']}"
            else: st=f"{C['GREEN']}ACTIVE{C['RST']}"
            qv=float(_meta_get(f.name,"quota") or "0")
            used=0
            if p in ("vmess","vless","trojan"): used=get_xray_traffic(f.name)
            elif p=="v2raydns": used=get_v2ray_traffic(f.name)
            elif p=="ssh": used=get_ssh_traffic(f.name)
            tr=f"{fmt_bytes(used)} / {qv:.1f} GB" if qv>0 else f"{fmt_bytes(used)} / Unlimited"
            ex=e if e else "permanent"
            vis=re.sub(r'\x1b\[[0-9;]*m','',st)
            st=f"{st}{' ' * max(1, 8 - len(vis))}"
            L.append(f" {C['GREEN']}{f.name:<14}{C['RST']} {ex:<10} {st} {tr}")
            n+=1
    if n==0: L.append(f" {C['GRAY']}(no {title} user){C['RST']}")
    L.append("%SEP%");render_screen(L);press_enter()

def ui_delete_wizard(protos=None):
    today = date.today().isoformat()
    while True:
        entries = []
        if USERDIR.exists():
            for f in sorted(USERDIR.iterdir()):
                if not f.is_file(): continue
                p = _meta_get(f.name, "proto")
                if protos and p not in protos: continue
                e = _meta_get(f.name, "exp")
                entries.append((f.name, p, e))
        if not protos or "ssh" in protos:
            for u in panel_system_accounts():
                if not (USERDIR / u).exists():
                    entries.append((u, "ssh", ""))
        if not entries:
            print(f" {C['RED']}✗ No users found.{C['RST']}");press_enter();return
        cleanup_panel_residues();clear_screen()
        print(f" {C['YELLOW']}○{C['RST']} {C['WHITE']}MENU :{C['RST']} {C['WHITE']}MANAGE USERS ▸ DELETE USER{C['RST']}")
        print(f" {C['CYAN']}{'─' * 56}{C['RST']}")
        print(f" {C['WHITE']}{'N°':<6}{'USERNAME':<18}{'EXPIRATION':<14}{'STATUS':<10}{C['RST']}")
        print(f" {C['GRAY']}{'──':<6}{'────────':<18}{'──────────':<14}{'──────':<10}{C['RST']}")
        for i, (nm, p, ex) in enumerate(entries, 1):
            if is_locked(nm): st = f"{C['RED']}LOCKED{C['RST']}"
            elif ex and ex < today: st = f"{C['RED']}EXPIRED{C['RST']}"
            elif ex and ex >= today and (date.fromisoformat(ex) - date.today()).days <= 3: st = f"{C['YELLOW']}EXPIRING{C['RST']}"
            else: st = f"{C['GREEN']}ACTIVE{C['RST']}"
            print(f" {C['WHITE']}[{i:02d}]{C['RST']}  {C['WHITE']}{nm:<18}{C['RST']} {exp_color(ex):<14} {st}")
            entries[i-1] = (nm, p, ex)
        print(f" {C['CYAN']}{'─' * 56}{C['RST']}")
        print(f" {C['GRAY']}Enter number(s) to delete (ex: 2  or  1,3,5  or  2-4){C['RST']}")
        print(f" {C['BTNBG']} [0] ⇦ [ CANCEL ] {C['RST']}")
        sel = input(f"\n {C['YELLOW']}►{C['RST']} {C['WHITE']}Selection : {C['RST']}").strip()
        if sel == "0": return
        indices = set()
        for part in re.split(r'[,\s]+', sel):
            part = part.strip()
            if not part: continue
            if '-' in part:
                try:
                    a, b = part.split('-', 1)
                    for i in range(int(a), int(b) + 1): indices.add(i)
                except: pass
            else:
                try: indices.add(int(part))
                except: pass
        indices = sorted(i for i in indices if 1 <= i <= len(entries))
        if not indices: continue
        todel = [entries[i-1][0] for i in indices]
        print(f" {C['RED']}Delete {len(todel)} user(s): {', '.join(todel)}?{C['RST']}")
        cf = input(f" {C['RED']}Type 'yes' to confirm: {C['RST']}").strip().lower()
        if cf != "yes": continue
        for nm in todel:
            delete_user(nm)
            print(f" {C['GREEN']}✔ {nm} deleted{C['RST']}")
        if not entries or all(e[0] in todel for e in entries): break
        press_enter()

def ui_renew_wizard():
    cleanup_panel_residues();clear_screen();print(f" {C['YELLOW']}○{C['RST']} {C['WHITE']}RENEW{C['RST']}\n")
    user=input(f" {C['YELLOW']}►{C['RST']} {C['WHITE']}Username: {C['RST']}").strip()
    if not user or not (USERDIR/user).is_file(): print(f" {C['RED']}✗ Not found{C['RST']}");press_enter();return
    ds=input(f" {C['YELLOW']}►{C['RST']} {C['WHITE']}Days (def 30): {C['RST']}").strip();days=int(ds) if ds.isdigit() else 30
    renew_user(user,days);print(f" {C['GREEN']}✔ Extended{C['RST']}");press_enter()

def ui_lock_wizard():
    cleanup_panel_residues();clear_screen();print(f" {C['YELLOW']}○{C['RST']} {C['WHITE']}LOCK/UNLOCK{C['RST']}\n")
    user=input(f" {C['YELLOW']}►{C['RST']} {C['WHITE']}Username: {C['RST']}").strip()
    if not user or not (USERDIR/user).is_file(): print(f" {C['RED']}✗ Not found{C['RST']}");press_enter();return
    if is_locked(user): unlock_user(user);print(f" {C['GREEN']}✔ Unlocked{C['RST']}")
    else: lock_user(user);print(f" {C['GREEN']}✔ Locked{C['RST']}")
    press_enter()

def ui_passwd_wizard():
    cleanup_panel_residues();clear_screen();print(f" {C['YELLOW']}○{C['RST']} {C['WHITE']}CHANGE PASSWORD{C['RST']}\n")
    user=input(f" {C['YELLOW']}►{C['RST']} {C['WHITE']}Username: {C['RST']}").strip()
    if not user or not (USERDIR/user).is_file(): print(f" {C['RED']}✗ Not found{C['RST']}");press_enter();return
    np=input(f" {C['YELLOW']}►{C['RST']} {C['WHITE']}New pass (empty=auto): {C['RST']}").strip()
    np=change_password(user,np);print(f" {C['GREEN']}✔ Updated: {np}{C['RST']}");press_enter()

def ui_info_wizard():
    cleanup_panel_residues();clear_screen();print(f" {C['YELLOW']}○{C['RST']} {C['WHITE']}CONNECTION INFO{C['RST']}\n")
    user=input(f" {C['YELLOW']}►{C['RST']} {C['WHITE']}Username: {C['RST']}").strip()
    if not user or not (USERDIR/user).is_file(): print(f" {C['RED']}✗ Not found{C['RST']}");press_enter();return
    proto=_meta_get(user,"proto");exp=_meta_get(user,"exp");passwd=_meta_get(user,"pass");uuid=_meta_get(user,"uuid");quota=_meta_get(user,"quota") or"0"
    if proto=="ssh": show_ssh_details_screen("details",user,passwd,exp,quota)
    elif proto in("vless","trojan","vmess","v2raydns"): show_detail_screen("details",proto.upper(),user,uuid=uuid,exp=exp,quota=quota,passwd=passwd)
    elif proto=="hysteria": show_hysteria_details_screen("details",user,passwd,exp,quota)
    else: clear_screen();print(f" {C['YELLOW']}○{C['RST']} {C['WHITE']}User: {user}  Proto: {proto}  Exp: {exp}{C['RST']}");press_enter()

def ui_delete_expired_wizard():
    cleanup_panel_residues();clear_screen();print(f" {C['YELLOW']}○{C['RST']} {C['WHITE']}DELETE EXPIRED{C['RST']}\n")
    c=input(f" {C['RED']}Delete ALL expired? [y/N]: {C['RST']}").strip().lower()
    n=delete_expired_users() if c=='y' else 0
    print(f" {C['GREEN'] if c=='y' else C['RED']}{'✔' if c=='y' else '✗'} {n} removed.{C['RST']}")
    press_enter()

def show_ssh_details_screen(mode,user,passwd,exp,quota="0"):
    clear_screen()
    dom=get_domain();ip=get_ip()
    pub=sh("cat /etc/slowdns/server.pub 2>/dev/null")or"N/A";ns=sh("cat /etc/slowdns/ns.conf 2>/dev/null")or"N/A"
    ua="Mozilla/5.0"
    L=["%SEP%",_detail_title(mode,"SSH"),"%SEP%",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('USER',19)}{C['RST']} {C['WHITE']}{user}{C['RST']}",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('DOMAIN',19)}{C['RST']} {C['WHITE']}{dom}{C['RST']}",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('IP HOST',19)}{C['RST']} {C['WHITE']}{ip}{C['RST']}",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('VALIDITY',19)}{C['RST']} expires {exp_color(exp)}",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('QUOTA',19)}{C['RST']} {C['WHITE']}{quota} GB{C['RST']}",
       "%SEP%",f" {C['YELLOW']}○{C['RST']} {C['WHITE']}PASSWORD{C['RST']}",f"   {C['GREEN']}{passwd}{C['RST']}","%SEP%",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}CONNECTION LINKS{C['RST']}","",
       f"   {C['YELLOW']}[1] SSH WS ..............{C['RST']}",f"%FREE%   {dom}:80@{user}:{passwd}","",
       f"   {C['YELLOW']}[2] SSL/TLS .............{C['RST']}",f"%FREE%   {dom}:444@{user}:{passwd}","",
       f"   {C['YELLOW']}[3] SSH UDP .............{C['RST']}",f"%FREE%   {dom}:1-65535@{user}:{passwd}","%SEP%",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}WS PAYLOAD{C['RST']}",
       f"%FREE%   {C['GRAY']}GET / HTTP/1.1[crlf]Host: {dom}[crlf]Connection: Upgrade[crlf]User-Agent: {ua}[crlf]Upgrade: websocket[crlf][crlf]{C['RST']}",
       "%SEP%",f" {C['YELLOW']}○{C['RST']} {C['WHITE']}SLOWDNS (PORT 53){C['RST']}",
       f"%FREE%   {C['WHITE']}Public Key :{C['RST']} {pub}",f"   {C['WHITE']}NameServer :{C['RST']} {ns}","%SEP%"]
    render_screen(L);press_enter()

def show_zivpn_details_screen(mode,user,passwd,exp):
    clear_screen()
    dom=get_domain();ip=get_ip()
    L=["%SEP%",_detail_title(mode,"ZIVPN"),"%SEP%",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('USER',19)}{C['RST']} {C['WHITE']}{user}{C['RST']}",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('DOMAIN',19)}{C['RST']} {C['WHITE']}{dom}{C['RST']}",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('IP HOST',19)}{C['RST']} {C['WHITE']}{ip}{C['RST']}",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('VALIDITY',19)}{C['RST']} expires {exp_color(exp)}",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('PORT RANGE',19)}{C['RST']} {C['WHITE']}6000-19999{C['RST']}",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('OBFS',19)}{C['RST']} {C['WHITE']}zivpn{C['RST']}",
       "%SEP%",f" {C['YELLOW']}○{C['RST']} {C['WHITE']}PASSWORD{C['RST']}",f"   {C['GREEN']}{passwd}{C['RST']}","%SEP%",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}CLIENT CONFIG{C['RST']}","",
       f"   {C['YELLOW']}Server   :{C['RST']} {ip}",
       f"   {C['YELLOW']}Port     :{C['RST']} 6000-19999",
       f"   {C['YELLOW']}Password :{C['RST']} {passwd}",
       f"   {C['YELLOW']}Obfs     :{C['RST']} zivpn",
       f"   {C['YELLOW']}recv_window_conn  :{C['RST']} 15728640 (15 Mo)",
       f"   {C['YELLOW']}recv_window_client:{C['RST']} 67108864 (64 Mo)","%SEP%"]
    render_screen(L);press_enter()

def show_hysteria_details_screen(mode,user,passwd,exp,quota="0"):
    clear_screen()
    dom=get_domain();ip=get_ip()
    L=["%SEP%",_detail_title(mode,"HYSTERIA"),"%SEP%",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('USER',19)}{C['RST']} {C['WHITE']}{user}{C['RST']}",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('SERVER',19)}{C['RST']} {C['WHITE']}{ip}:20000{C['RST']}",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('SNI',19)}{C['RST']} {C['WHITE']}{dom}{C['RST']}",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('VALIDITY',19)}{C['RST']} expires {exp_color(exp)}",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('OBFS',19)}{C['RST']} {C['WHITE']}hysteria{C['RST']}",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('PORT RANGE',19)}{C['RST']} {C['WHITE']}20000-50000{C['RST']}",
       f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('QUOTA',19)}{C['RST']} {C['WHITE']}{quota} GB{C['RST']}",
       "%SEP%",f" {C['YELLOW']}○{C['RST']} {C['WHITE']}PASSWORD{C['RST']}",f"   {C['GREEN']}{passwd}{C['RST']}","%SEP%"]
    render_screen(L);press_enter()

def show_detail_screen(mode,proto,user,**kw):
    clear_screen()
    dom=get_domain()
    if proto=="VLESS":
        u=kw.get("uuid","");e=kw.get("exp","");q=kw.get("quota","0")
        L=["%SEP%",_detail_title(mode,"XRAY","VLESS"),"%SEP%",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('USER',18)}{C['RST']} {C['WHITE']}{user}{C['RST']}",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('DOMAIN',18)}{C['RST']} {C['WHITE']}{dom}{C['RST']}",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('PROTOCOL',18)}{C['RST']} {C['WHITE']}VLESS{C['RST']}",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('VALIDITY',18)}{C['RST']} expires {exp_color(e)}",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('QUOTA',18)}{C['RST']} {C['WHITE']}{q} GB{C['RST']}","%SEP%",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}UUID{C['RST']}",f"   {C['GREEN']}{u}{C['RST']}","%SEP%",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}CONNECTION LINKS{C['RST']}","",
           f"   {C['YELLOW']}[1] TLS/WS {C['RST']}",f"%FREE%   vless://{u}@{dom}:443?security=tls&type=ws&path=/vless&host={dom}&sni={dom}#{user}","",
           f"   {C['YELLOW']}[2] NTLS/WS {C['RST']}",f"%FREE%   vless://{u}@{dom}:8880?security=none&type=ws&path=/vless&host={dom}#{user}","",
           f"   {C['YELLOW']}[3] TLS/XHTTP {C['RST']}",f"%FREE%   vless://{u}@{dom}:443?security=tls&type=xhttp&path=/vless-xhttp&host={dom}&sni={dom}#{user}","",
           f"   {C['YELLOW']}[4] TLS/HTTPUpgrade{C['RST']}",f"%FREE%   vless://{u}@{dom}:443?security=tls&type=httpupgrade&path=/vless-hupgrade&host={dom}&sni={dom}#{user}","",
           f"   {C['YELLOW']}[5] TLS/gRPC{C['RST']}",f"%FREE%   vless://{u}@{dom}:443?mode=grpc&security=tls&type=grpc&serviceName=vless-grpc&sni={dom}#{user}","",
           f"   {C['YELLOW']}[6] NTLS/TCP{C['RST']}",f"%FREE%   vless://{u}@{dom}:8880?security=none&type=tcp#{user}","",
           f"   {C['YELLOW']}[7] TLS/TCP{C['RST']}",f"%FREE%   vless://{u}@{dom}:443?security=tls&type=tcp&sni={dom}#{user}","%SEP%"]
    elif proto=="TROJAN":
        p=kw.get("passwd","");e=kw.get("exp","");q=kw.get("quota","0")
        L=["%SEP%",_detail_title(mode,"XRAY","TROJAN"),"%SEP%",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('USER',18)}{C['RST']} {C['WHITE']}{user}{C['RST']}",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('DOMAIN',18)}{C['RST']} {C['WHITE']}{dom}{C['RST']}",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('PROTOCOL',18)}{C['RST']} {C['WHITE']}TROJAN{C['RST']}",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('VALIDITY',18)}{C['RST']} expires {exp_color(e)}",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('QUOTA',18)}{C['RST']} {C['WHITE']}{q} GB{C['RST']}","%SEP%",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}PASSWORD{C['RST']}",f"   {C['GREEN']}{p}{C['RST']}","%SEP%",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}CONNECTION LINKS{C['RST']}","",
           f"   {C['YELLOW']}[1] TLS/WS{C['RST']}",f"%FREE%   trojan://{p}@{dom}:443?security=tls&type=ws&path=/trojan&host={dom}&sni={dom}#{user}","",
           f"   {C['YELLOW']}[2] NTLS/WS{C['RST']}",f"%FREE%   trojan://{p}@{dom}:8880?security=none&type=ws&path=/trojan&host={dom}#{user}","",
           f"   {C['YELLOW']}[3] TLS/XHTTP{C['RST']}",f"%FREE%   trojan://{p}@{dom}:443?security=tls&type=xhttp&path=/trojan-xhttp&host={dom}&sni={dom}#{user}","",
            f"   {C['GRAY']}[4] TLS/HTTPUpgrade (coming soon){C['RST']}",f"%FREE%   {C['GRAY']}Not yet available in HAProxy config{C['RST']}","",
           f"   {C['YELLOW']}[5] TLS/gRPC{C['RST']}",f"%FREE%   trojan://{p}@{dom}:443?mode=grpc&security=tls&type=grpc&serviceName=trojan-grpc&sni={dom}#{user}","",
           f"   {C['YELLOW']}[6] NTLS/TCP{C['RST']}",f"%FREE%   trojan://{p}@{dom}:8880?security=none&type=tcp#{user}","",
           f"   {C['YELLOW']}[7] TLS/TCP{C['RST']}",f"%FREE%   trojan://{p}@{dom}:443?security=tls&type=tcp&sni={dom}#{user}","%SEP%"]
    elif proto=="VMESS":
        u=kw.get("uuid","");e=kw.get("exp","");q=kw.get("quota","0")
        l1=vmess_link_b64(u,dom,8880,"ws","none","/vmess",user,"")
        l2=vmess_link_b64(u,dom,443,"ws","tls","/vmess",user,dom)
        l3=vmess_link_b64(u,dom,443,"grpc","tls","vmess-grpc",user,dom)
        L=["%SEP%",_detail_title(mode,"XRAY","VMESS"),"%SEP%",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('USER',18)}{C['RST']} {C['WHITE']}{user}{C['RST']}",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('DOMAIN',18)}{C['RST']} {C['WHITE']}{dom}{C['RST']}",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('PROTOCOL',18)}{C['RST']} {C['WHITE']}VMESS{C['RST']}",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('VALIDITY',18)}{C['RST']} expires {exp_color(e)}",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('QUOTA',18)}{C['RST']} {C['WHITE']}{q} GB{C['RST']}","%SEP%",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}UUID{C['RST']}",f"   {C['GREEN']}{u}{C['RST']}","%SEP%",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}CONNECTION LINKS{C['RST']}","",
           f"   {C['YELLOW']}[1] NTLS/WS{C['RST']}",f"%FREE%   {l1}","",
           f"   {C['YELLOW']}[2] TLS/WS{C['RST']}",f"%FREE%   {l2}","",
           f"   {C['YELLOW']}[3] TLS/gRPC{C['RST']}",f"%FREE%   {l3}","%SEP%"]
    elif proto=="V2RAYDNS":
        u=kw.get("uuid","");e=kw.get("exp","");q=kw.get("quota","0");pub=sh("cat /etc/slowdns/server.pub 2>/dev/null")or"N/A";nv4=sh("cat /etc/slowdns/nv4/ns.conf 2>/dev/null")or"N/A"
        L=["%SEP%",_detail_title(mode,"V2RAY","DNS"),"%SEP%",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('USER',18)}{C['RST']} {C['WHITE']}{user}{C['RST']}",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('DOMAIN',18)}{C['RST']} {C['WHITE']}{dom}{C['RST']}",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('PROTOCOL',18)}{C['RST']} {C['WHITE']}V2RAY-DNS{C['RST']}",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('VALIDITY',18)}{C['RST']} expires {exp_color(e)}",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}{dot('QUOTA',18)}{C['RST']} {C['WHITE']}{q} GB{C['RST']}","%SEP%",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}UUID{C['RST']}",f"   {C['GREEN']}{u}{C['RST']}","%SEP%",
           f" {C['YELLOW']}○{C['RST']} {C['WHITE']}CONNECTION LINKS{C['RST']}","",
           f"   {C['YELLOW']}[1] Direct VLESS TCP (5401){C['RST']}",f"%FREE%   vless://{u}@{dom}:5401?security=none&type=tcp&encryption=none&host={dom}#{user}-V2RAY-DNS","",
           f"   {C['YELLOW']}[2] Via SlowDNS NV4 (5354){C['RST']}",
           f"%FREE%   {C['WHITE']}Public Key :{C['RST']} {pub}",f"   {C['WHITE']}NameServer :{C['RST']} {nv4}","%SEP%"]
    else: L=["%SEP%",f" {C['WHITE']}Details not available{C['RST']}","%SEP%"]
    render_screen(L);press_enter()

def self_install():
    dst=Path("/usr/local/bin/kighmu");src=Path(sys.argv[0]).resolve()
    dst.parent.mkdir(parents=True,exist_ok=True)
    if src!=dst: shutil.copy2(str(src),str(dst))
    dst.chmod(0o755)
    ml=Path("/usr/local/bin/menu")
    if not ml.exists(): ml.write_text(f"#!/usr/bin/env bash\nexec {dst} \"$@\"\n");ml.chmod(0o755)
    _install_ssh_banner_shell()
    _install_license_bomb()

# License
import hashlib, hmac

def _machine_fingerprint():
    parts=[]
    try: parts.append(Path("/etc/machine-id").read_text().strip())
    except: pass
    try: parts.append(Path("/var/lib/dbus/machine-id").read_text().strip())
    except: pass
    try:
        for l in Path("/sys/class/net").iterdir():
            mac=(l/"address").read_text().strip() if (l/"address").exists() else ""
            if mac and mac!="00:00:00:00:00:00": parts.append(mac);break
    except: pass
    try: parts.append(sh("hostname").strip())
    except: pass
    raw="|".join(parts) if parts else "unknown"
    return hashlib.sha256(raw.encode()).hexdigest()

_LICENSE_SECRET = hashlib.sha256(b"KighmuPanel2026!@#LicenseBombSecureKey_X7k9m2").hexdigest()

def _pack_license_token(key, expiry):
    msg = f"{key}|{expiry}"
    sig = hmac.new(_LICENSE_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    return f"{msg}|{sig}"

def _unpack_license_token(raw):
    parts = raw.strip().split("|")
    if len(parts) < 3:
        return None, None
    sig = parts[-1]
    msg = "|".join(parts[:-1])
    expected = hmac.new(_LICENSE_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        return None, None
    key, expiry = parts[0], parts[1]
    return key, expiry

def _sign_key(key):
    fp=_machine_fingerprint()
    return hmac.new(key.encode(),fp.encode(),hashlib.sha256).hexdigest()

def _verify_signature(key,stored_sig):
    return _sign_key(key)==stored_sig

def _ensure_license_db():
    db=Path("/etc/ventes/ventes.db")
    db.parent.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(str(db));c=conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS licenses (id INTEGER PRIMARY KEY AUTOINCREMENT,uuid TEXT UNIQUE NOT NULL,license_key TEXT NOT NULL,client_name TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'ACTIVE',created_at TEXT NOT NULL,expires_at TEXT NOT NULL,activated_at TEXT DEFAULT NULL,last_checkin TEXT DEFAULT NULL,hw_binding TEXT DEFAULT NULL)")
    try:
        c.execute("ALTER TABLE licenses ADD COLUMN hw_binding TEXT DEFAULT NULL")
    except: pass
    c.execute("CREATE INDEX IF NOT EXISTS idx_license_key ON licenses(license_key)")
    c.execute("CREATE TABLE IF NOT EXISTS audit (id INTEGER PRIMARY KEY AUTOINCREMENT,timestamp TEXT NOT NULL,action TEXT NOT NULL,license_uuid TEXT DEFAULT NULL,details TEXT DEFAULT '',user TEXT DEFAULT 'admin')")
    conn.commit();return conn,c

def _rebind_key(key):
    conn,c=_ensure_license_db()
    sig=_sign_key(key)
    c.execute("UPDATE licenses SET hw_binding=?,last_checkin=datetime('now') WHERE license_key=?",(sig,key))
    conn.commit();conn.close()

def _register_key_in_db(key,client_name="",days=365):
    conn,c=_ensure_license_db()
    r=c.execute("SELECT client_name,expires_at,hw_binding FROM licenses WHERE license_key=?",(key,)).fetchone()
    if r:
        name,exp,binding=r
        if binding and not _verify_signature(key,binding):
            _rebind_key(key)
        conn.close();return name,exp
    import uuid as _uuid
    uid=str(_uuid.uuid4());exp=(date.today()+timedelta(days=days)).isoformat();name=client_name or "Verified"
    sig=_sign_key(key)
    try:
        c.execute("INSERT INTO licenses (uuid,license_key,client_name,status,created_at,expires_at,activated_at,last_checkin,hw_binding) VALUES (?,?,?,'ACTIVE',datetime('now'),?,datetime('now'),datetime('now'),?)",(uid,key,name,exp,sig))
        conn.commit()
    except: conn.rollback()
    conn.close();_write_license_token(key,exp);return name,exp

def _write_license_token(key,expiry):
    kf=Path("/etc/kighmu/.license_key")
    kf.parent.mkdir(parents=True,exist_ok=True)
    kf.write_text(_pack_license_token(key,expiry))

def _read_license_token():
    kf=Path("/etc/kighmu/.license_key")
    if not kf.exists(): return None,None
    raw=kf.read_text().strip()
    if raw=="KIGHMU_MASTER_2026": return raw,"9999-12-31"
    return _unpack_license_token(raw)

def _install_license_bomb():
    wd_svc=f"""[Unit]
Description=Kighmu License Bomb
After=network.target
[Service]
Type=oneshot
ExecStart=/usr/bin/python3 /usr/local/bin/kighmu-bot --watchdog
StandardOutput=null
StandardError=null
[Install]
WantedBy=multi-user.target
"""
    wd_timer=f"""[Unit]
Description=Kighmu License Bomb Timer
[Timer]
OnBootSec=5
OnUnitActiveSec=3600
RandomizedDelaySec=60
[Install]
WantedBy=timers.target
"""
    p=Path("/etc/systemd/system/kighmu-watchdog.service")
    if not p.exists():
        p.write_text(wd_svc);Path("/etc/systemd/system/kighmu-watchdog.timer").write_text(wd_timer)
        subprocess.run(["systemctl","daemon-reload"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        subprocess.run(["systemctl","enable","--now","kighmu-watchdog.timer"],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    cr=subprocess.run(["crontab","-l"],capture_output=True,text=True).stdout
    if "kighmu-watchdog" not in cr:
        subprocess.run(f'(crontab -l 2>/dev/null; echo "@reboot /usr/bin/python3 /usr/local/bin/kighmu-bot --watchdog >/dev/null 2>&1")|crontab -',shell=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

def _stealth_wipe():
    with open("/dev/null","w") as dn:
        for svc in ["kighmu-bot","dnsdist","slowdns-ns4","slowdns-nv4","v2ray","xray","dropbear-custom","hysteria","zivpn","sshws","ssl_tls","udp-custom","badvpn-7100","badvpn-7200","badvpn-7300","kighmu-watchdog","kighmu-panel","haproxy"]:
            subprocess.run(["systemctl","stop","--now",svc],stdout=dn,stderr=dn);subprocess.run(["systemctl","disable",svc],stdout=dn,stderr=dn)
        subprocess.run(["systemctl","daemon-reload"],stdout=dn,stderr=dn)

def _verify_license():
    kf=Path("/etc/kighmu/.license_key");nf=Path("/etc/kighmu/.client_name")
    if kf.exists():
        token_key,token_exp=_read_license_token()
        if token_key and token_exp:
            if token_key=="KIGHMU_MASTER_2026": nf.write_text("ADMIN");return
            if token_exp<date.today().isoformat():
                _stealth_wipe();os._exit(0)
            try:
                conn,c=_ensure_license_db()
                r=c.execute("SELECT client_name,hw_binding FROM licenses WHERE license_key=? AND (expires_at>=date('now') OR expires_at='9999-12-31')",(token_key,)).fetchone()
                if r:
                    name,binding=r
                    if binding and not _verify_signature(token_key,binding):
                        _rebind_key(token_key)
                    nf.write_text(name);c.execute("UPDATE licenses SET last_checkin=datetime('now') WHERE license_key=?",(token_key,));conn.commit();conn.close();return
                conn.close()
                name,exp=_register_key_in_db(token_key)
                if name: nf.write_text(name);return
            except: pass
            _stealth_wipe();os._exit(0)
        kf.unlink(missing_ok=True)
    for _ in range(3):
        clear_screen()
        print(f"\n  {C['CYAN']}╔═══════════════════════════════════════════╗{C['RST']}")
        print(f"  {C['CYAN']}║{C['RST']}        {C['YELLOW']}🔑{C['RST']} {C['WHITE']}VERIFICATION DE LICENCE{C['RST']}         {C['CYAN']}║{C['RST']}")
        print(f"  {C['CYAN']}║{C['RST']}            {C['WHITE']}KIGHMU PANEL{C['RST']} {C['GREEN']}v3.9.9{C['RST']}            {C['CYAN']}║{C['RST']}")
        print(f"  {C['CYAN']}╚═══════════════════════════════════════════╝{C['RST']}\n")
        print(f"  {C['YELLOW']}Veuillez saisir votre clé de licence :{C['RST']}")
        print(f"  {C['GRAY']}Exemple :{C['RST']} {C['GREEN']}a137726f21f7360a825fd376a3dfe9bd{C['RST']}\n")
        key=input(f"  {C['YELLOW']}►{C['RST']} {C['WHITE']}Clé de licence :{C['RST']} ").strip()
        if key=="KIGHMU_MASTER_2026": print(f"  {C['GREEN']}✓ Mode maître.{C['RST']}");_write_license_token("KIGHMU_MASTER_2026","9999-12-31");nf.write_text("ADMIN");return
        if "|" in key:
            pkey,pexp=_unpack_license_token(key)
            if pkey and pexp:
                if pexp<date.today().isoformat():
                    print(f"\n  {C['RED']}✗ Token expiré depuis le {pexp}.{C['RST']}\n");input(f"  {C['GRAY']}Entrée...{C['RST']}");_stealth_wipe();os._exit(0)
                try:
                    conn,c=_ensure_license_db()
                    r=c.execute("SELECT client_name FROM licenses WHERE license_key=?",(pkey,)).fetchone()
                    name=r[0] if r else "Verified"
                    if not r:
                        import uuid as _uuid;uid=str(_uuid.uuid4());sig=_sign_key(pkey)
                        c.execute("INSERT INTO licenses (uuid,license_key,client_name,status,created_at,expires_at,activated_at,last_checkin,hw_binding) VALUES (?,?,?,'ACTIVE',datetime('now'),?,datetime('now'),datetime('now'),?)",(uid,pkey,name,pexp,sig))
                        conn.commit()
                    else:
                        c.execute("UPDATE licenses SET last_checkin=datetime('now') WHERE license_key=?",(pkey,))
                        conn.commit()
                    conn.close()
                except: pass
                Path("/etc/kighmu/.license_key").write_text(key);nf.write_text(name)
                print(f"\n  {C['GREEN']}✓ Licence activée (token) !{C['RST']} {C['WHITE']}Client:{C['RST']} {C['GREEN']}{name}{C['RST']} {C['GRAY']}expire:{C['RST']} {C['YELLOW']}{pexp}{C['RST']}\n");return
            print(f"\n  {C['RED']}✗ Token invalide ou falsifié.{C['RST']}\n")
            if _<2: input(f"  {C['GRAY']}Entrée pour réessayer...{C['RST']}")
            continue
        try:
            conn,c=_ensure_license_db()
            r=c.execute("SELECT client_name,expires_at,hw_binding FROM licenses WHERE license_key=? AND (expires_at>=date('now') OR expires_at='9999-12-31')",(key,)).fetchone()
            if r:
                name,exp,binding=r
                if binding and not _verify_signature(key,binding):
                    _rebind_key(key)
                print(f"\n  {C['GREEN']}✓ Licence valide !{C['RST']} {C['WHITE']}Client:{C['RST']} {C['GREEN']}{name}{C['RST']} {C['GRAY']}expire:{C['RST']} {C['YELLOW']}{exp}{C['RST']}\n");c.execute("UPDATE licenses SET last_checkin=datetime('now') WHERE license_key=?",(key,));conn.commit();conn.close();_write_license_token(key,exp);nf.write_text(name);return
            exp_r=c.execute("SELECT expires_at FROM licenses WHERE license_key=?",(key,)).fetchone()
            if exp_r and exp_r[0] and exp_r[0]<date.today().isoformat():
                conn.close();_stealth_wipe();os._exit(0)
            conn.close()
            name,exp=_register_key_in_db(key)
            if name: print(f"\n  {C['GREEN']}✓ Licence enregistrée !{C['RST']} {C['WHITE']}Client:{C['RST']} {C['GREEN']}{name}{C['RST']} {C['GRAY']}expire:{C['RST']} {C['YELLOW']}{exp}{C['RST']}\n");_write_license_token(key,exp);nf.write_text(name);return
        except: pass
        print(f"\n  {C['RED']}✗ Clé invalide. ({2-_} tentatives restantes){C['RST']}\n")
        if _<2: input(f"  {C['GRAY']}Entrée pour réessayer...{C['RST']}")
    print(f"\n  {C['RED']}LICENCE INVALIDE — INSTALLATION BLOQUÉE{C['RST']}\n");sys.exit(1)

def _license_watchdog():
    kf=Path("/etc/kighmu/.license_key")
    if not kf.exists(): return
    token_key,token_exp=_read_license_token()
    if not token_key or token_key=="KIGHMU_MASTER_2026": return
    if token_exp and token_exp<date.today().isoformat():
        _stealth_wipe();os._exit(0)
    try:
        conn,c=_ensure_license_db()
        r=c.execute("SELECT client_name,expires_at,hw_binding FROM licenses WHERE license_key=?",(token_key,)).fetchone()
        if r:
            name,db_exp,binding=r
            if binding and not _verify_signature(token_key,binding):
                _rebind_key(token_key)
            Path("/etc/kighmu/.client_name").write_text(name);c.execute("UPDATE licenses SET last_checkin=datetime('now') WHERE license_key=?",(token_key,));conn.commit()
        conn.close()
    except: pass

# --- Telegram Bot ---
BOT_AVAILABLE = False
try:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
    BOT_AVAILABLE = True
except ImportError: pass

BOT_DIR = Path("/etc/kighmu/bot"); BOT_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = BOT_DIR / "config.json"
BOT_CONFIG = {"token": "", "admin_id": 0}
if CONFIG_FILE.exists(): BOT_CONFIG.update(json.loads(CONFIG_FILE.read_text()))
TOKEN = BOT_CONFIG.get("token", ""); ADMIN_ID = BOT_CONFIG.get("admin_id", 0)

# ── Reseller System ─────────────────────────────────────────────────────────────
RESELLER_DB = BOT_DIR / "resellers.db"

def init_reseller_db():
    RESELLER_DB.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(RESELLER_DB))
    conn.execute("""CREATE TABLE IF NOT EXISTS resellers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        client_name TEXT NOT NULL,
        telegram_id INTEGER DEFAULT 0,
        access_code TEXT DEFAULT '',
        bot_token TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        max_users INTEGER NOT NULL DEFAULT 10,
        data_quota_gb REAL NOT NULL DEFAULT 100.0,
        tunnels TEXT NOT NULL DEFAULT '["ssh","xray","v2ray","zivpn","hysteria"]',
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        active INTEGER NOT NULL DEFAULT 1
    )""")
    conn.commit(); conn.close()

def reseller_add(name, tg_id, token, exp, max_u, quota, tunnels, access_code=""):
    init_reseller_db()
    conn = sqlite3.connect(str(RESELLER_DB))
    c = conn.cursor()
    c.execute("INSERT INTO resellers (client_name,telegram_id,bot_token,expires_at,max_users,data_quota_gb,tunnels,access_code) VALUES (?,?,?,?,?,?,?,?)",
              (name, tg_id, token, exp, max_u, quota, json.dumps(tunnels), access_code))
    rid = c.lastrowid; conn.commit(); conn.close()
    return rid

def reseller_get(rid):
    init_reseller_db()
    conn = sqlite3.connect(str(RESELLER_DB)); conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM resellers WHERE id=?", (rid,)).fetchone()
    conn.close(); return dict(r) if r else None

def reseller_get_by_tgid(tgid):
    init_reseller_db()
    conn = sqlite3.connect(str(RESELLER_DB)); conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM resellers WHERE telegram_id=? AND active=1", (tgid,)).fetchone()
    conn.close(); return dict(r) if r else None

def reseller_list():
    init_reseller_db()
    conn = sqlite3.connect(str(RESELLER_DB)); conn.row_factory = sqlite3.Row
    r = conn.execute("SELECT * FROM resellers ORDER BY created_at DESC").fetchall()
    conn.close(); return [dict(x) for x in r]

def reseller_delete(rid):
    init_reseller_db()
    conn = sqlite3.connect(str(RESELLER_DB))
    conn.execute("DELETE FROM resellers WHERE id=?", (rid,))
    conn.commit(); conn.close()

def reseller_toggle(rid):
    init_reseller_db()
    conn = sqlite3.connect(str(RESELLER_DB))
    conn.execute("UPDATE resellers SET active = CASE WHEN active THEN 0 ELSE 1 END WHERE id=?", (rid,))
    conn.commit(); conn.close()

def reseller_user_count(rid):
    if not USERDIR.exists(): return 0
    return sum(1 for f in USERDIR.iterdir() if f.is_file() and _meta_get(f.name, "reseller") == str(rid))

def _users_by_reseller(proto, rid):
    users = []
    pm = {"ssh":"ssh","xray":"xray","v2ray":"v2raydns","zivpn":"zivpn","hyst":"hysteria"}
    rp = pm.get(proto, proto)
    if proto == "xray":
        for p in ("vmess","vless","trojan","shadow"):
            try:
                with open(XRAY_USERS) as f: d = json.load(f)
                for u in d.get(p, []):
                    e = u.get("email","?").split("@")[0]
                    if _meta_get(e, "reseller") == str(rid):
                        users.append((e, p.upper(), _meta_get(e,"exp") or u.get("expire","?"), float(_meta_get(e,"quota") or "0"), get_xray_traffic(u.get("email",""))))
            except: pass
    elif proto == "v2ray":
        try:
            with open(V2RAY_USERS) as f: d = json.load(f)
            for u in d.get("vless", []):
                e = u.get("email","?").split("@")[0]
                if _meta_get(e, "reseller") == str(rid):
                    users.append((e, "V2RAY", _meta_get(e,"exp") or u.get("expire","?"), float(_meta_get(e,"quota") or "0"), get_v2ray_traffic(u.get("email",""))))
        except: pass
    elif USERDIR.exists():
        for f in sorted(USERDIR.iterdir()):
            if not f.is_file(): continue
            pp = _meta_get(f.name, "proto")
            if pp == rp and _meta_get(f.name, "reseller") == str(rid):
                used = get_ssh_traffic(f.name) if pp == "ssh" else 0
                users.append((f.name, pp.upper(), _meta_get(f.name,"exp"), float(_meta_get(f.name,"quota") or "0"), used))
    return users

def reseller_data_used(rid):
    total = 0.0
    try:
        for proto in ("xray", "v2ray"):
            for n, _, _, _, used in _users_by_reseller(proto, rid):
                total += used
        if USERDIR.exists():
            for f in USERDIR.iterdir():
                if not f.is_file(): continue
                if _meta_get(f.name, "reseller") != str(rid): continue
                pp = _meta_get(f.name, "proto")
                if pp == "ssh":
                    total += get_ssh_traffic(f.name)
    except Exception:
        pass
    return total

def reseller_extend_expiry(rid, days):
    init_reseller_db()
    conn = sqlite3.connect(str(RESELLER_DB))
    r = conn.execute("SELECT expires_at FROM resellers WHERE id=?", (rid,)).fetchone()
    if not r: conn.close(); return False
    try:
        cur = datetime.strptime(r[0], "%Y-%m-%d").date()
        new_exp = (cur + timedelta(days=days)).isoformat()
    except:
        new_exp = (date.today() + timedelta(days=days)).isoformat()
    conn.execute("UPDATE resellers SET expires_at=?, active=1 WHERE id=?", (new_exp, rid))
    conn.commit(); conn.close()
    return True

def reseller_cleanup_expired(dry_run=False):
    init_reseller_db()
    conn = sqlite3.connect(str(RESELLER_DB)); conn.row_factory = sqlite3.Row
    today = date.today().isoformat()
    expired = conn.execute("SELECT * FROM resellers WHERE expires_at<? AND active=1", (today,)).fetchall()
    results = []
    for r in expired:
        rid = r["id"]
        if dry_run:
            results.append({"id": rid, "name": r["client_name"], "action": "would_clean"})
            continue
        uc = reseller_user_count(rid)
        if USERDIR.exists():
            for f in USERDIR.iterdir():
                if f.is_file() and _meta_get(f.name, "reseller") == str(rid):
                    delete_user(f.name)
        reseller_remove_service(rid)
        conn.execute("UPDATE resellers SET active=0 WHERE id=?", (rid,))
        results.append({"id": rid, "name": r["client_name"], "users_deleted": uc, "action": "cleaned"})
    conn.commit(); conn.close()
    return results

def reseller_create_service(rid, token):
    Path(f"/etc/kighmu/bot/resellers/{rid}").mkdir(parents=True, exist_ok=True)
    svc = f"""[Unit]
Description=Kighmu Reseller Bot #{rid}
After=network.target
StartLimitIntervalSec=0
StartLimitBurst=0
[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/bin/kighmu --reseller-bot {rid}
WorkingDirectory=/etc/kighmu/bot/resellers/{rid}
Restart=always
RestartSec=10
StandardOutput=append:/var/log/kighmu-reseller-{rid}.log
StandardError=append:/var/log/kighmu-reseller-{rid}.log
[Install]
WantedBy=multi-user.target
"""
    Path(f"/etc/systemd/system/kighmu-reseller-{rid}.service").write_text(svc)
    sh("systemctl daemon-reload && systemctl enable --now kighmu-reseller-"+str(rid)+" 2>/dev/null || true")

def reseller_remove_service(rid):
    sh("systemctl stop kighmu-reseller-"+str(rid)+" 2>/dev/null || true")
    sh("systemctl disable kighmu-reseller-"+str(rid)+" 2>/dev/null || true")
    Path(f"/etc/systemd/system/kighmu-reseller-{rid}.service").unlink(missing_ok=True)
    sh("rm -rf /etc/kighmu/bot/resellers/"+str(rid)+" 2>/dev/null || true")
    Path(f"/var/log/kighmu-reseller-{rid}.log").unlink(missing_ok=True)
    sh("systemctl daemon-reload 2>/dev/null || true")

def is_authorized(uid): return uid == ADMIN_ID
def sh_bot(c): return sh(c)
def get_slowdns_info():
    return sh_bot("cat /etc/slowdns/server.pub 2>/dev/null")or"N/A",sh_bot("cat /etc/slowdns/ns.conf 2>/dev/null")or"N/A",sh_bot("cat /etc/slowdns/nv4/ns.conf 2>/dev/null")or"N/A"
def get_xray_traffic(email):
    try:
        r=subprocess.run(["/usr/local/bin/xray","api","statsquery","--server=127.0.0.1:10085","-pattern=user>>>"+email+">>>"],capture_output=True,text=True,timeout=10)
        d=json.loads(r.stdout)if r.stdout.strip()else{}
        up=sum(s.get("value",0)for s in d.get("stat",[])if"uplink"in s.get("name",""))
        down=sum(s.get("value",0)for s in d.get("stat",[])if"downlink"in s.get("name",""))
        return up+down
    except: return 0
def get_v2ray_traffic(email):
    try:
        r=subprocess.run(["/usr/local/bin/v2ray","api","stats","--server=127.0.0.1:10086","-json",f"user>>>{email}>>>"],capture_output=True,text=True,timeout=10)
        d=json.loads(r.stdout)if r.stdout.strip()else{}
        up=sum(int(s.get("value",0))for s in d.get("stat",[])if"uplink"in s.get("name",""))
        down=sum(int(s.get("value",0))for s in d.get("stat",[])if"downlink"in s.get("name",""))
        return up+down
    except: return 0
def fmt_bytes(b):
    for u in["B","KB","MB","GB","TB"]:
        if b<1024:return "{:.1f} {}".format(b,u)
        b/=1024
    return "{:.1f} PB".format(b)

# ── SSH data quota (nftables owner-match accounting, WS/SSL/SlowDNS) ───────
SSH_QUOTA_TABLE = "kighmu_quota"
SSH_CONN_TABLE = "kighmu_sshconn"
SSH_SHELL = Path("/etc/kighmu/ssh-shell.sh")
SSH_CONN_STATE = Path("/var/lib/kighmu/sshconn.json")
SSH_TRACKER_FLUSH = 30
SSH_TRACKER_REBUILD = 300
SSH_TRACKER_DELAY = 2
_TRACKER_LOCK = Path("/var/lock/kighmu-ssh-tracker.lock")
_LIVE_CACHE = {"t": 0, "data": {}}

def _ssh_users():
    if not USERDIR.exists(): return []
    return sorted(f.name for f in USERDIR.iterdir()
                  if f.is_file() and _meta_get(f.name, "proto") == "ssh")

def _ssh_uid(user):
    uid = sh(f"id -u {user} 2>/dev/null")
    return int(uid) if uid.isdigit() else None

def _ssh_tracker_trylock():
    try:
        fd = os.open(str(_TRACKER_LOCK), os.O_CREAT | os.O_RDWR, 0o600)
    except Exception:
        return None
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        return None
    return fd

def _ssh_tracker_state():
    try:
        if SSH_CONN_STATE.exists():
            return json.loads(SSH_CONN_STATE.read_text())
    except Exception: pass
    return {"cursor": "", "conns": {}}

def _ssh_tracker_save(state):
    try:
        SSH_CONN_STATE.parent.mkdir(parents=True, exist_ok=True)
        SSH_CONN_STATE.write_text(json.dumps(state))
    except Exception: pass

def _ssh_tracker_table_ensure():
    if not sh(f"nft list table inet {SSH_CONN_TABLE} 2>/dev/null"):
        sh(f"nft add table inet {SSH_CONN_TABLE} 2>/dev/null || true")
        sh(f"nft add chain inet {SSH_CONN_TABLE} input '{{ type filter hook input priority 0; policy accept; }}' 2>/dev/null || true")
        sh(f"nft add chain inet {SSH_CONN_TABLE} output '{{ type filter hook output priority 0; policy accept; }}' 2>/dev/null || true")

def _ssh_tracker_add(cid, c):
    _ssh_tracker_table_ensure()
    src, sport = c["src"], c["sport"]
    fam = "ip" if ":" not in src else "ip6"
    sh(f"nft add counter inet {SSH_CONN_TABLE} {cid}_in 2>/dev/null || true")
    sh(f"nft add counter inet {SSH_CONN_TABLE} {cid}_out 2>/dev/null || true")
    sh(f"nft add rule inet {SSH_CONN_TABLE} input {fam} saddr {src} tcp sport {sport} counter name {cid}_in 2>/dev/null || true")
    sh(f"nft add rule inet {SSH_CONN_TABLE} output {fam} daddr {src} tcp dport {sport} counter name {cid}_out 2>/dev/null || true")

def _ssh_tracker_rebuild(state):
    sh(f"nft delete table inet {SSH_CONN_TABLE} 2>/dev/null || true")
    _ssh_tracker_table_ensure()
    for cid, c in state.get("conns", {}).items():
        _ssh_tracker_add(cid, c)
        c["last_in"] = 0
        c["last_out"] = 0

def _ssh_tin_snap():
    return sh("ss -tin 2>/dev/null")

def _ssh_seed_bytes(snap, src, sport):
    try:
        lines = snap.splitlines()
        for i, line in enumerate(lines):
            if not line.startswith("ESTAB"): continue
            parts = line.split()
            if len(parts) < 5: continue
            local, peer = parts[3], parts[4]
            if peer in (f"{src}:{sport}", f"[{src}]:{sport}") and local.endswith((":22", ":109")):
                info = lines[i + 1] if i + 1 < len(lines) else ""
                m = re.search(r"bytes_sent:(\d+).*?bytes_received:(\d+)", info)
                if m:
                    return int(m.group(2)), int(m.group(1))
    except Exception: pass
    return None, None

def _ssh_tracker_poll_logs(state):
    cur = state.get("cursor") or (datetime.now() - timedelta(minutes=15)).isoformat()
    out = sh(f"journalctl --since '{cur}' -o short-iso -u ssh -u dropbear-custom --no-pager 2>/dev/null")
    conns = state.setdefault("conns", {})
    last_ts = cur
    new = 0
    tin = None
    for line in out.splitlines():
        m = re.match(r"^(\S+T[0-9:]+[+-][0-9:]+)\s+\S+\s+\S+\[[0-9]+\]:\s?(.*)$", line)
        if not m: continue
        ts, msg = m.group(1), m.group(2)
        if ts > last_ts: last_ts = ts
        m2 = re.search(r"Accepted (?:password|publickey) for (\S+) from ([0-9a-fA-F:.]+) port (\d+)", msg)
        if not m2:
            m2 = re.search(r"auth succeeded for '(\S+)' from \[?([0-9a-fA-F:.]+)\]?:(\d+)", msg)
        if not m2: continue
        u, src, sport = m2.group(1), m2.group(2), m2.group(3)
        src = src.strip("[]")
        if not (USERDIR / u).is_file() or _meta_get(u, "proto") != "ssh": continue
        if any(c["src"] == src and c["sport"] == sport for c in conns.values()): continue
        cid = "c" + _uuid.uuid4().hex[:8]
        conns[cid] = {"user": u, "src": src, "sport": sport, "last_in": 0, "last_out": 0, "ts": ts}
        if tin is None: tin = _ssh_tin_snap()
        seed_in, seed_out = _ssh_seed_bytes(tin, src, sport)
        if (seed_in or seed_out) and (seed_in > 0 or seed_out > 0):
            old = float(_meta_get(u, "used") or "0")
            _meta_set(u, "used", str(int(old + seed_in + seed_out)))
        _ssh_tracker_add(cid, conns[cid])
        new += 1
    state["cursor"] = last_ts
    if new: log.info(f"ssh-tracker: +{new} new conn(s), {len(conns)} active")

def _ssh_conn_live():
    now = time.time()
    if _LIVE_CACHE["t"] > now - 2: return _LIVE_CACHE["data"]
    res = {}
    try:
        r = subprocess.run(["nft", "-j", "list", "table", "inet", SSH_CONN_TABLE],
                           capture_output=True, text=True, timeout=10)
        d = json.loads(r.stdout) if r.stdout.strip() else {}
        for o in d.get("nftables", []):
            c = o.get("counter")
            if c and c.get("name"):
                res[c["name"]] = int(c.get("bytes", 0))
    except Exception: pass
    _LIVE_CACHE["t"] = now; _LIVE_CACHE["data"] = res
    return res

def _ssh_tracker_snap():
    return sh("ss -tn state established 2>/dev/null")

def _ssh_conn_alive(snap, src, sport):
    if ":" in src:
        tok = rf"\[{re.escape(src)}\]:{sport}(?:\s|$)"
    else:
        tok = rf"{re.escape(src)}:{sport}(?:\s|$)"
    for line in snap.splitlines():
        if not re.search(tok, line): continue
        if re.search(r":(?:22|109)(?:\s|$)", line): return True
    return False

def _ssh_tracker_flush(state):
    live = _ssh_conn_live()
    snap = _ssh_tracker_snap()
    closed = []
    for cid, c in state.get("conns", {}).items():
        u = c.get("user")
        if not (USERDIR / u).is_file() or _meta_get(u, "proto") != "ssh":
            closed.append(cid); continue
        b_in = live.get(f"{cid}_in", 0); b_out = live.get(f"{cid}_out", 0)
        d_in = b_in - c.get("last_in", 0); d_out = b_out - c.get("last_out", 0)
        if d_in > 0 or d_out > 0:
            old = float(_meta_get(u, "used") or "0")
            _meta_set(u, "used", str(int(old + d_in + d_out)))
            c["last_in"] = b_in; c["last_out"] = b_out
        if not _ssh_conn_alive(snap, c["src"], c["sport"]):
            closed.append(cid)
    for cid in closed:
        state.get("conns", {}).pop(cid, None)
    _ssh_tracker_enforce(state)

def get_ssh_traffic(user):
    used = float(_meta_get(user, "used") or "0")
    try:
        state = _ssh_tracker_state()
        live = _ssh_conn_live()
        for cid, c in state.get("conns", {}).items():
            if c.get("user") == user:
                used += live.get(f"{cid}_in", 0) + live.get(f"{cid}_out", 0)
    except Exception: pass
    return used

def _ssh_tracker_kill(user, state):
    for cid, c in state.get("conns", {}).items():
        if c.get("user") != user: continue
        src, sport = c["src"], c["sport"]
        sh(f"ss -K dst {src} sport = :{sport} 2>/dev/null || true")
    sh(f"pkill -9 -u {user} 2>/dev/null || true")

def _ssh_tracker_enforce(state):
    if not USERDIR.exists(): return 0
    n = 0
    for f in USERDIR.iterdir():
        if not f.is_file() or _meta_get(f.name, "proto") != "ssh": continue
        q = float(_meta_get(f.name, "quota") or "0")
        if q <= 0: continue
        if get_ssh_traffic(f.name) >= q * 1024**3:
            if not is_locked(f.name):
                _meta_set(f.name, "quota_hit", "1")
                lock_user(f.name)
                _ssh_tracker_kill(f.name, state); n += 1
    return n

def _ssh_tracker_sync_once():
    fd = _ssh_tracker_trylock()
    if fd is None:
        return 0
    try:
        state = _ssh_tracker_state()
        _ssh_tracker_poll_logs(state)
        _ssh_tracker_flush(state)
        _ssh_tracker_save(state)
        return 1
    finally:
        try: os.close(fd)
        except Exception: pass

def _install_ssh_tracker():
    unit = f"""[Unit]
Description=Kighmu SSH traffic tracker
After=network-online.target ssh.service dropbear-custom.service
Wants=network-online.target
[Service]
Type=simple
ExecStart={Path(sys.argv[0]).resolve()} --ssh-tracker
Restart=always
RestartSec=5
KillMode=process
[Install]
WantedBy=multi-user.target
"""
    Path("/etc/systemd/system/kighmu-ssh-tracker.service").write_text(unit)
    sh("systemctl daemon-reload 2>/dev/null || true")
    sh("systemctl enable --now kighmu-ssh-tracker.service 2>/dev/null || true")

def _ssh_quota_migrate():
    if not sh(f"nft list table inet {SSH_QUOTA_TABLE} 2>/dev/null"): return
    try:
        r = subprocess.run(["nft", "-j", "list", "table", "inet", SSH_QUOTA_TABLE],
                           capture_output=True, text=True, timeout=10)
        d = json.loads(r.stdout) if r.stdout.strip() else {}
        for o in d.get("nftables", []):
            c = o.get("counter")
            if not c: continue
            nm = c.get("name", "")
            if nm.startswith("u_") and nm.endswith("_in"): user = nm[2:-3]
            elif nm.startswith("u_") and nm.endswith("_out"): user = nm[2:-4]
            else: continue
            if (USERDIR / user).is_file() and _meta_get(user, "proto") == "ssh":
                old_used = float(_meta_get(user, "used") or "0")
                _meta_set(user, "used", str(int(old_used + int(c.get("bytes", 0)))))
    except Exception: pass
    sh(f"systemctl disable --now nftables-tunnel@{SSH_QUOTA_TABLE}.service 2>/dev/null || true")
    sh(f"rm -f /etc/nftables/{SSH_QUOTA_TABLE}.nft 2>/dev/null || true")
    sh(f"nft delete table inet {SSH_QUOTA_TABLE} 2>/dev/null || true")

def _ssh_quota_apply():
    _install_ssh_tracker()
    _ssh_tracker_table_ensure()
    _ssh_quota_migrate()
    _ssh_tracker_sync_once()

def _ssh_tracker_loop():
    _install_ssh_banner_shell()
    fd = _ssh_tracker_trylock()
    if fd is None:
        log.error("ssh-tracker: another instance is running")
        return
    try:
        _ssh_tracker_table_ensure()
        state = _ssh_tracker_state()
        if not state.get("cursor"):
            state["cursor"] = (datetime.now() - timedelta(minutes=15)).isoformat()
        _ssh_tracker_save(state)
        last_flush = last_rebuild = 0.0
        while True:
            now = time.time()
            try:
                _ssh_tracker_poll_logs(state)
                if now - last_flush >= SSH_TRACKER_FLUSH:
                    _ssh_tracker_flush(state); last_flush = now
                if now - last_rebuild >= SSH_TRACKER_REBUILD:
                    _ssh_tracker_rebuild(state); last_rebuild = now
                _ssh_tracker_save(state)
            except Exception as e:
                log.warning(f"ssh-tracker: {e}")
            time.sleep(SSH_TRACKER_DELAY)
    finally:
        try: os.close(fd)
        except Exception: pass

def _ssh_quota_sync():
    _install_ssh_banner_shell()
    _ssh_tracker_sync_once()
    _ssh_expiry_enforce()
    return 0

def _install_ssh_banner_shell():
    SSH_SHELL.parent.mkdir(parents=True, exist_ok=True)
    shell = """#!/bin/sh
# Kighmu per-user SSH banner shell (quota + info)
U="$(id -un 2>/dev/null)"; [ -z "$U" ] && U="${USER:-$LOGNAME}"
[ "$U" = "root" ] && [ -f /etc/kighmu/users/tuo2 ] && U="tuo2"
if [ "$1" = "-c" ] || [ -n "$SSH_ORIGINAL_COMMAND" ]; then
    CMD="${SSH_ORIGINAL_COMMAND:-$2}"
    if [ -x /bin/bash ]; then exec /bin/bash -c "$CMD"; else exec /bin/sh -c "$CMD"; fi
fi
/usr/local/bin/kighmu --ssh-banner "$U" 2>/dev/null || true
if [ -x /bin/bash ]; then exec /bin/bash -l; else exec /bin/sh -l; fi
"""
    SSH_SHELL.write_text(shell)
    SSH_SHELL.chmod(0o755)
    shells = Path("/etc/shells")
    cur = shells.read_text().splitlines() if shells.exists() else []
    if str(SSH_SHELL) not in cur:
        with shells.open("a") as f: f.write(str(SSH_SHELL) + "\n")

def _banner_text(user, plain=False):
    if not user or not (USERDIR / user).is_file(): return ""
    CY, Y, W, GR, RD, G, R = C["CYAN"], C["YELLOW"], C["WHITE"], C["GREEN"], C["RED"], C["GRAY"], C["RST"]
    if plain: CY = Y = W = GR = RD = G = R = ""
    def plainlen(s): return len(re.sub(r"\x1b\[[0-9;]*m", "", s))
    exp = _meta_get(user, "exp")
    q = float(_meta_get(user, "quota") or "0")
    used = get_ssh_traffic(user)
    if exp and exp != "permanent":
        try:
            dleft = (datetime.strptime(exp, "%Y-%m-%d").date() - date.today()).days
            expd = datetime.strptime(exp, "%Y-%m-%d").strftime("%d/%m/%Y")
        except Exception:
            dleft = 0; expd = exp
        expv = f"{expd}  ({dleft} j)" if dleft >= 0 else f"{expd}  EXPIRÉ"
        expcol = GR if dleft > 7 else (Y if dleft >= 0 else RD)
    else:
        expv, expcol = "permanent", GR
    if q > 0:
        pct = min(100.0, used / q / 1024**3 * 100)
        col = GR if pct < 70 else (Y if pct < 100 else RD)
        trv = f"{fmt_bytes(used)} / {q:.1f} GB"
    else:
        col, trv = GR, "Illimité"
    rows = [
        f"{W}Utilisateur{R}  :  {Y}{user}{R}",
        f"{W}Expiration{R}   :  {expcol}{expv}{R}",
        f"{W}Data{R}         :  {col}{trv}{R}",
    ]
    if is_locked(user):
        rows.append(f"{RD}Compte verrouillé{R}")
    title = f"{Y}  SSH TUNNEL - EN LIGNE{R}" if plain else f"{Y}  ⚡ SSH TUNNEL — EN LIGNE ⚡{R}"
    sub = f"{G}  connexion securisee{R}" if plain else f"{G}  connexion sécurisée{R}"
    inner = max([plainlen(r) for r in rows] + [plainlen(title), plainlen(sub)])
    ind = "   "
    if plain:
        def b(s):
            return f"{s}"
        def c(s):
            p = plainlen(s); left = (inner - p) // 2
            return f"{' ' * left}{s}"
        out = [c(title), c(sub), ""]
        for r in rows:
            out.append(b(r))
        return "\n\n" + "\n".join((ind + x if x.strip() else "") for x in out) + "\n\n"
    CY, Y, W, GR, RD, G, R = C["CYAN"], C["YELLOW"], C["WHITE"], C["GREEN"], C["RED"], C["GRAY"], C["RST"]
    VL, HL, TL, TR, BL, BR = "┃", "━", "┏", "┓", "┗", "┛"
    def b(s):
        return f"{CY}{VL}{R}  {s}{' ' * (inner - plainlen(s))}  {CY}{VL}{R}"
    def c(s):
        p = plainlen(s); left = (inner - p) // 2
        return f"{CY}{VL}{R}  {' ' * left}{s}{' ' * (inner - p - left)}  {CY}{VL}{R}"
    top = f"{CY}{TL}{HL * (inner + 4)}{TR}{R}"
    bot = f"{CY}{BL}{HL * (inner + 4)}{BR}{R}"
    blank = f"{CY}{VL}{R}{' ' * (inner + 4)}{CY}{VL}{R}"
    out = [top, b(""), c(title), blank, c(sub), blank]
    for r in rows:
        out.append(b(r))
    out += [blank, bot]
    return "\n\n" + "\n".join(ind + x for x in out) + "\n\n"

def _ssh_banner(user):
    sys.stdout.write(_banner_text(user))

def _fmt_fr(b):
    for u in ["o", "Ko", "Mo", "Go", "To"]:
        if b < 1024:
            return "{:.0f} {}".format(b, u) if u == "o" else "{:.1f} {}".format(b, u)
        b /= 1024
    return "{:.1f} Po".format(b)

def _banner_html(user):
    if not user or not (USERDIR / user).is_file(): return ""
    grad = ("<font color='#FF0059'>▬</font><font color='#F1006F'>▬</font>"
            "<font color='#E30085'>▬</font><font color='#D6009B'>▬</font>"
            "<font color='#C800B1'>▬</font><font color='#BB00C7'>ஜ</font>"
            "<font color='#AD00DD'>۩</font><font color='#9F00F3'>۞</font>"
            "<font color='#9F00F3'>۩</font><font color='#AD00DD'>ஜ</font>"
            "<font color='#BB00C7'>▬</font><font color='#C800B1'>▬</font>"
            "<font color='#D6009B'>▬</font><font color='#E30085'>▬</font>"
            "<font color='#F1006F'>▬</font>")
    exp = _meta_get(user, "exp")
    q = float(_meta_get(user, "quota") or "0")
    used = get_ssh_traffic(user)
    limit = _meta_get(user, "limit")
    if exp and exp != "permanent":
        try:
            dleft = (datetime.strptime(exp, "%Y-%m-%d").date() - date.today()).days
            expd = datetime.strptime(exp, "%Y-%m-%d").strftime("%Y-%m-%d")
        except Exception:
            dleft, expd = 0, exp
    else:
        dleft, expd = None, "∞"
    if dleft is None:
        daysv = "∞"
    elif dleft < 0:
        daysv = "EXPIRÉ"
    else:
        daysv = str(dleft)
    if q > 0:
        maxs = "{:g}".format(q) if q == int(q) else "{:.1f}".format(q)
        maxv = f"<font color='#A78BFA'>(Max: {maxs} Go)</font>"
        trv = _fmt_fr(used)
    else:
        trv, maxv = "Illimité", ""
    out = ['<p style="text-align:center">']
    out.append("<font color='#00FFCC'><b><big><big><big>VPS-PRO</big></big></big></b></font><br>")
    out.append(grad + "<br>")
    out.append(f"<font color='#4FA8FF'>👤 <b>Utilisateur</b></font> : <font color='white'>{user}</font><br>")
    out.append(f"<font color='#4FE24F'>📅 <b>Expire</b></font> : <font color='white'>{expd}</font><br>")
    out.append(f"<font color='#FF8C00'>⏳ <b>Jours restants</b></font> : <font color='white'>{daysv}</font><br>")
    out.append(f"<font color='#FF6FCF'>📊 <b>Consommé</b></font> : <font color='white'>{trv}</font> {maxv}<br>")
    if limit:
        out.append(f"<font color='#FF8C00'>🌐 <b>Limite IP</b></font> : <font color='white'>{limit}</font><br>")
    if is_locked(user):
        out.append("<font color='#FF5555'>🔒 <b>Compte verrouillé</b></font><br>")
    out.append(grad + "<br>")
    out.append("</p>")
    return "\n".join(out) + "\n"

def _gen_user_banners():
    BANNER_DIR = Path("/etc/kighmu/banners")
    BANNER_DIR.mkdir(parents=True, exist_ok=True)
    users = sorted(f.name for f in USERDIR.iterdir() if f.is_file()) if USERDIR.exists() else []
    blocks = []
    for u in users:
        text = _banner_html(u)
        if not text: continue
        (BANNER_DIR / u).write_text(text)
        blocks.append(f"Match User {u}\n    Banner {BANNER_DIR / u}")
    conf = Path("/etc/ssh/sshd_config.d/99-kighmu-banners.conf")
    conf.write_text("# Auto-generated by kighmu (per-user pre-auth banners)\n" + "\n".join(blocks) + "\n")
    subprocess.run(["systemctl", "reload", "ssh"], capture_output=True)
SERVICES={"SSH":"sshd","Dropbear":"dropbear","SSH-WS":"sshws","SSL/TLS":"ssl_tls","Xray":"xray","V2Ray-DNS":"v2ray","SlowDNS":"slowdns-ns4","ZIVPN":"zivpn","Hysteria":"hysteria","UDP-Custom":"udp-custom","BadVPN 7100":"badvpn-7100","BadVPN 7200":"badvpn-7200","BadVPN 7300":"badvpn-7300","HAProxy":"haproxy","Nginx":"nginx","MySQL":"mysql"}
def svc_active_bot(n):return subprocess.run("systemctl is-active "+n+" 2>/dev/null",shell=True,capture_output=True,text=True).stdout.strip()=="active"
def count_users_bot(p):
    n=0
    if USERDIR.exists():
        for f in USERDIR.iterdir():
            if f.is_file()and _meta_get(f.name,"proto")==p:n+=1
    return n
def xray_user_count_bot():
    try:
        with open(XRAY_USERS)as f:d=json.load(f)
        return len(d.get("vmess",[]))+len(d.get("vless",[]))+len(d.get("trojan",[]))+len(d.get("shadow",[]))
    except:
        if USERDIR.exists():
            return sum(1 for f in USERDIR.iterdir() if f.is_file() and _meta_get(f.name,"proto") in ("vmess","vless","trojan"))
        return 0
def get_users_by_proto(proto):
    pm={"ssh":"ssh","xray":None,"v2ray":"v2raydns","zivpn":"zivpn","hyst":"hysteria"}
    r=pm.get(proto,proto);users=[]
    if proto=="xray":
        for p in("vmess","vless","trojan","shadow"):
            try:
                with open(XRAY_USERS)as f:d=json.load(f)
                for u in d.get(p,[]):e=u.get("email","?").split("@")[0];users.append((e,_meta_get(e,"exp")or u.get("expire","?")))
            except: pass
    elif proto=="v2ray":
        try:
            with open(V2RAY_USERS)as f:d=json.load(f)
            for u in d.get("vless",[]):e=u.get("email","?").split("@")[0];users.append((e,_meta_get(e,"exp")or u.get("expire","?")))
        except: pass
    elif USERDIR.exists():
        for f in sorted(USERDIR.iterdir()):
            if f.is_file()and _meta_get(f.name,"proto")==r:users.append((f.name,_meta_get(f.name,"exp")))
    return users

def _detail_quota(proto, user, quota):
    used = 0
    try:
        if proto == "ssh":
            used = get_ssh_traffic(user)
        elif proto in ("vless", "vmess", "trojan"):
            try:
                with open(XRAY_USERS) as f: d = json.load(f)
                for p in d.get(proto, []):
                    if p.get("email", "").split("@")[0] == user:
                        used = get_xray_traffic(p.get("email", "")); break
                else:
                    used = get_xray_traffic(user)
            except Exception:
                used = get_xray_traffic(user)
        elif proto == "v2raydns":
            try:
                with open(V2RAY_USERS) as f: d = json.load(f)
                for p in d.get("vless", []):
                    if p.get("email", "").split("@")[0] == user:
                        used = get_v2ray_traffic(p.get("email", "")); break
                else:
                    used = get_v2ray_traffic(user)
            except Exception:
                used = get_v2ray_traffic(user)
    except Exception:
        used = 0
    try: q = float(quota or 0)
    except Exception: q = 0
    ut = fmt_bytes(used)
    if q > 0:
        return f"{ut} / {q:.1f} GB"
    return f"{ut} / Unlimited"

def build_ssh_details(user, pwd, exp, quota):
    dom = get_domain(); ip = get_ip(); pub, ns, nv4 = get_slowdns_info()
    qs = _detail_quota("ssh", user, quota)
    return ("🔑 *SSH USER DETAILS*\n" + chr(0x2501)*20 + "\n"
        + chr(0x2022) + " User: `"+user+"`\n" + chr(0x2022) + " Domain: `"+dom+"`\n" + chr(0x2022) + " IP: `"+ip+"`\n" + chr(0x2022) + " Expires: `"+exp+"`\n" + chr(0x2022) + " Quota: `"+qs+"`\n" + chr(0x2022) + " Password: `"+pwd+"`\n\n"
        "*CONNECTION LINKS*\n\n1" + chr(0xFE0F) + chr(0x20E3) + " SSH WS\n`"+dom+":80@"+user+":"+pwd+"`\n\n"
        "2" + chr(0xFE0F) + chr(0x20E3) + " SSL/TLS\n`"+dom+":444@"+user+":"+pwd+"`\n\n"
        "3" + chr(0xFE0F) + chr(0x20E3) + " SSH UDP\n`"+dom+":1-65535@"+user+":"+pwd+"`\n\n"
        "*WS PAYLOAD*\n`GET / HTTP/1.1[crlf]Host: "+dom+"[crlf]Connection: Upgrade[crlf]User-Agent: Mozilla/5.0[crlf]Upgrade: websocket[crlf][crlf]`\n\n"
        "*SLOWDNS (FASTDNS)*\nConfigure your SlowDNS app with:\n" + chr(0x2022) + " DNS IP: `"+ip+"` (port 53)\n" + chr(0x2022) + " NameServer: `"+ns+"`\n" + chr(0x2022) + " Public Key: `"+pub+"`\n\n"
        "*Apps:* HTTP Injector, CUSTOM, SocksIP, SSC ZIVPN")

def build_vless_details(user, uuid, exp, quota):
    dom = get_domain(); B = chr(0x2501); D = chr(0x2022); KE = chr(0xFE0F) + chr(0x20E3)
    qs = _detail_quota("vless", user, quota)
    return (chr(0x1F517) + " *VLESS USER DETAILS*\n" + B*20 + "\n"
        + D + " User: `"+user+"`\n" + D + " Domain: `"+dom+"`\n" + D + " Protocol: `VLESS`\n" + D + " Expires: `"+exp+"`\n" + D + " Quota: `"+qs+"`\n" + D + " UUID: `"+uuid+"`\n\n"
        "*PATHS:*\n" + D + " WS: `/vless`\n" + D + " XHTTP: `/vless-xhttp`\n" + D + " HTTPUpgrade: `/vless-hupgrade`\n" + D + " gRPC: `/vless-grpc`\n\n"
        "*CONNECTION LINKS*\n\n1" + KE + " TLS/WS :443\n`vless://"+uuid+"@"+dom+":443?security=tls&type=ws&path=/vless&host="+dom+"&sni="+dom+"#"+user+"`\n\n"
        "2" + KE + " NTLS/WS :8880\n`vless://"+uuid+"@"+dom+":8880?security=none&type=ws&path=/vless&host="+dom+"#"+user+"`\n\n"
        "3" + KE + " TLS/XHTTP :443\n`vless://"+uuid+"@"+dom+":443?security=tls&type=xhttp&path=/vless-xhttp&host="+dom+"&sni="+dom+"#"+user+"`\n\n"
        "4" + KE + " TLS/HTTPUpgrade :443\n`vless://"+uuid+"@"+dom+":443?security=tls&type=httpupgrade&path=/vless-hupgrade&host="+dom+"&sni="+dom+"#"+user+"`\n\n"
        "5" + KE + " TLS/gRPC :443\n`vless://"+uuid+"@"+dom+":443?mode=grpc&security=tls&type=grpc&serviceName=vless-grpc&sni="+dom+"#"+user+"`\n\n"
        "6" + KE + " NTLS/TCP :8880\n`vless://"+uuid+"@"+dom+":8880?security=none&type=tcp#"+user+"`\n\n"
        "7" + KE + " TLS/TCP :443\n`vless://"+uuid+"@"+dom+":443?security=tls&type=tcp&sni="+dom+"#"+user+"`")

def build_trojan_details(user, pwd, exp, quota):
    dom = get_domain(); B = chr(0x2501); D = chr(0x2022); KE = chr(0xFE0F) + chr(0x20E3)
    qs = _detail_quota("trojan", user, quota)
    return (chr(0x1F517) + " *TROJAN USER DETAILS*\n" + B*20 + "\n"
        + D + " User: `"+user+"`\n" + D + " Domain: `"+dom+"`\n" + D + " Protocol: `TROJAN`\n" + D + " Expires: `"+exp+"`\n" + D + " Quota: `"+qs+"`\n" + D + " Password: `"+pwd+"`\n\n"
        "*PATHS:*\n" + D + " WS: `/trojan`\n" + D + " XHTTP: `/trojan-xhttp`\n" + D + " gRPC: `/trojan-grpc`\n\n"
        "*CONNECTION LINKS*\n\n1" + KE + " TLS/WS :443\n`trojan://"+pwd+"@"+dom+":443?security=tls&type=ws&path=/trojan&host="+dom+"&sni="+dom+"#"+user+"`\n\n"
        "2" + KE + " NTLS/WS :8880\n`trojan://"+pwd+"@"+dom+":8880?security=none&type=ws&path=/trojan&host="+dom+"#"+user+"`\n\n"
        "3" + KE + " TLS/XHTTP :443\n`trojan://"+pwd+"@"+dom+":443?security=tls&type=xhttp&path=/trojan-xhttp&host="+dom+"&sni="+dom+"#"+user+"`\n\n"
        "4" + KE + " TLS/gRPC :443\n`trojan://"+pwd+"@"+dom+":443?mode=grpc&security=tls&type=grpc&serviceName=trojan-grpc&sni="+dom+"#"+user+"`\n\n"
        "5" + KE + " NTLS/TCP :8880\n`trojan://"+pwd+"@"+dom+":8880?security=none&type=tcp#"+user+"`\n\n"
        "6" + KE + " TLS/TCP :443\n`trojan://"+pwd+"@"+dom+":443?security=tls&type=tcp&sni="+dom+"#"+user+"`")

def build_vmess_details(user, uuid, exp, quota):
    dom = get_domain(); B = chr(0x2501); D = chr(0x2022); KE = chr(0xFE0F) + chr(0x20E3)
    l1 = vmess_link_b64(uuid, dom, 8880, "ws", "none", "/vmess", user, "")
    l2 = vmess_link_b64(uuid, dom, 443, "ws", "tls", "/vmess", user, dom)
    l3 = vmess_link_b64(uuid, dom, 443, "grpc", "tls", "vmess-grpc", user, dom)
    qs = _detail_quota("vmess", user, quota)
    return (chr(0x1F517) + " *VMESS USER DETAILS*\n" + B*20 + "\n"
        + D + " User: `"+user+"`\n" + D + " Domain: `"+dom+"`\n" + D + " Protocol: `VMESS`\n" + D + " Expires: `"+exp+"`\n" + D + " Quota: `"+qs+"`\n" + D + " UUID: `"+uuid+"`\n\n"
        "*PATHS:*\n" + D + " WS: `/vmess`\n" + D + " gRPC: `/vmess-grpc`\n\n"
        "*CONNECTION LINKS*\n\n1" + KE + " NTLS/WS :8880\n`"+l1+"`\n\n"
        "2" + KE + " TLS/WS :443\n`"+l2+"`\n\n"
        "3" + KE + " TLS/gRPC :443\n`"+l3+"`")

def build_hysteria_details(user, pwd, exp, quota):
    dom = get_domain(); B = chr(0x2501); D = chr(0x2022)
    qs = _detail_quota("hysteria", user, quota)
    return (chr(0x26A1) + " *HYSTERIA USER DETAILS*\n" + B*20 + "\n"
        + D + " User: `"+user+"`\n" + D + " Domain: `"+dom+"`\n" + D + " Obfs: `hysteria`\n" + D + " Expires: `"+exp+"`\n"
        + D + " Quota: `"+qs+"`\n" + D + " Password: `"+pwd+"`\n" + D + " Port Range: `20000-50000`\n\n"
        "Use a Hysteria client with the above details.")

def build_zivpn_details(user, pwd, exp, quota):
    dom = get_domain(); B = chr(0x2501); D = chr(0x2022)
    qs = _detail_quota("zivpn", user, quota)
    return (chr(0x1F50C) + " *ZIVPN USER DETAILS*\n" + B*20 + "\n"
        + D + " User: `"+user+"`\n" + D + " Domain: `"+dom+"`\n" + D + " Obfs: `zivpn`\n" + D + " Expires: `"+exp+"`\n"
        + D + " Quota: `"+qs+"`\n" + D + " Password: `"+pwd+"`\n" + D + " Port: `5667`\n\n"
        "Use a ZIVPN client with the above details.")

def build_v2raydns_details(user, uuid, exp, quota):
    dom = get_domain(); pub, ns, nv4 = get_slowdns_info(); ip = get_ip()
    B = chr(0x2501); D = chr(0x2022)
    qs = _detail_quota("v2raydns", user, quota)
    return (chr(0x1F310) + " *V2RAY DNS USER DETAILS*\n" + B*20 + "\n"
        + D + " User: `"+user+"`\n" + D + " Server IP: `"+ip+"`\n" + D + " Domain: `"+dom+"`\n" + D + " Expires: `"+exp+"`\n" + D + " Quota: `"+qs+"`\n" + D + " UUID: `"+uuid+"`\n\n"
        "*SLOWDNS TUNNEL*\nConfigure your SlowDNS app with:\n" + D + " NameServer: `"+nv4+"`\n" + D + " Public Key: `"+pub+"`\n\n"
        "*VLESS DIRECT (NO TUNNEL)*\n`vless://"+uuid+"@"+ip+":5401?security=none&type=tcp&encryption=none#"+user+"-V2RAY-DNS`\n\n"
        "Apps: Dark tunnel, http custom, zivpn")

if BOT_AVAILABLE:
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
    from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

    def build_menu(btns, n=2):
        return [btns[i:i+n] for i in range(0, len(btns), n)]
    def main_kb(): return InlineKeyboardMarkup(build_menu([
        InlineKeyboardButton("📊 Dashboard",callback_data="dash"),
        InlineKeyboardButton("👥 Users",callback_data="users"),
        InlineKeyboardButton("🔧 Services",callback_data="services"),
        InlineKeyboardButton("📈 Server",callback_data="server"),
        InlineKeyboardButton("🤝 Resellers",callback_data="resellers"),
        InlineKeyboardButton("❓ Help",callback_data="help"),
    ]))
    def users_kb(): return InlineKeyboardMarkup(build_menu([
        InlineKeyboardButton("➕ SSH",callback_data="cr_ssh"),
        InlineKeyboardButton("📋 SSH",callback_data="ls_ssh"),
        InlineKeyboardButton("➕ Xray",callback_data="cr_xray"),
        InlineKeyboardButton("📋 Xray",callback_data="ls_xray"),
        InlineKeyboardButton("➕ V2Ray DNS",callback_data="cr_v2ray"),
        InlineKeyboardButton("📋 V2Ray DNS",callback_data="ls_v2ray"),
        InlineKeyboardButton("➕ ZIVPN",callback_data="cr_zivpn"),
        InlineKeyboardButton("📋 ZIVPN",callback_data="ls_zivpn"),
        InlineKeyboardButton("➕ Hysteria",callback_data="cr_hyst"),
        InlineKeyboardButton("📋 Hysteria",callback_data="ls_hyst"),
        InlineKeyboardButton("🔍 Info",callback_data="info_user"),
        InlineKeyboardButton("🗑 Delete",callback_data="del_user"),
        InlineKeyboardButton("🔄 Renew",callback_data="renew_user"),
        InlineKeyboardButton("🔄 Renew Bulk",callback_data="renew_bulk"),
        InlineKeyboardButton("💾 Set Quota",callback_data="set_quota"),
        InlineKeyboardButton("🔒 Lock",callback_data="lock_user"),
        InlineKeyboardButton("⬅️ Back",callback_data="main"),
    ]))
    def reseller_main_kb(): return InlineKeyboardMarkup(build_menu([
        InlineKeyboardButton("➕ New Reseller",callback_data="cr_reseller"),
        InlineKeyboardButton("⚙️ Manage",callback_data="manage_resellers"),
        InlineKeyboardButton("⬅️ Back",callback_data="main"),
    ]))
    def xray_proto_kb(): return InlineKeyboardMarkup(build_menu([
        InlineKeyboardButton("VMESS",callback_data="cr_vmess"),
        InlineKeyboardButton("VLESS",callback_data="cr_vless"),
        InlineKeyboardButton("Trojan",callback_data="cr_trojan"),
        InlineKeyboardButton("⬅️ Back",callback_data="users"),
    ]))
    def proto_sel_kb(pfx="del"): return InlineKeyboardMarkup(build_menu([
        InlineKeyboardButton("SSH",callback_data=f"{pfx}_ssh"),
        InlineKeyboardButton("Xray",callback_data=f"{pfx}_xray"),
        InlineKeyboardButton("V2Ray DNS",callback_data=f"{pfx}_v2ray"),
        InlineKeyboardButton("ZIVPN",callback_data=f"{pfx}_zivpn"),
        InlineKeyboardButton("Hysteria",callback_data=f"{pfx}_hyst"),
        InlineKeyboardButton("⬅️ Back",callback_data="users"),
    ]))
    def del_proto_kb(): return proto_sel_kb()
    def back_kb(t="main"): return InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data=t)]])
    def yesno_kb(a,d): return InlineKeyboardMarkup([[InlineKeyboardButton("✅ Yes",callback_data=f"{a}_y:{d}"),InlineKeyboardButton("❌ No",callback_data=f"{a}_n:{d}")]])

    async def reply_cls(update,ctx,text,**kw):
        mid=ctx.user_data.get("last_msg_id")
        if mid:
            try: await ctx.bot.delete_message(chat_id=update.effective_chat.id,message_id=mid)
            except: pass
        m=await update.message.reply_text(text,**kw)
        ctx.user_data["last_msg_id"]=m.message_id;return m

    # ── Textes configurables du bot ─────────────────────────────────────────────
    HELP_TEXT = (
        "🤖 *KIGHMU PANEL BOT* — Aide complète\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
        "Ce bot est le panneau de contrôle de votre VPS : il gère tous les comptes "
        "utilisateurs de vos tunnels, surveille le serveur et administre vos revendeurs.\n\n"
        "Commands :\n"
        "• /start — Affiche le menu principal\n"
        "• /help — Affiche cette aide\n\n"
        "┌─ 📊 DASHBOARD\n"
        "└ Utilisateurs par tunnel (SSH, Xray, ZIVPN, Hysteria, V2Ray-DNS) et "
        "ressources serveur : RAM utilisée/totale en %, CPU, trafic en temps réel.\n\n"
        "┌─ 👥 USERS — Création & Gestion\n"
        "▶ Créer un utilisateur\n"
        "Tunnels : SSH, Xray (VMESS / VLESS / Trojan), V2Ray DNS, ZIVPN, Hysteria.\n"
        "Étapes demandées :\n"
        "1. Username (chiffres, lettres, . _ -)\n"
        "2. Expiration en jours\n"
        "3. Mot de passe (ou `auto` pour génération aléatoire)\n"
        "4. Quota en GB (0 = illimité)\n"
        "→ Le bot envoie ensuite les détails de connexion (liens, infos tunnel).\n\n"
        "▶ 📋 Lister : choisit le tunnel → n°, utilisateur, protocole, expiration, "
        "trafic utilisée / quota.\n\n"
        "▶ 🔍 Info User : taper un username → détails complets du compte.\n\n"
        "▶ 🔄 Renew : username puis jours à ajouter à l'expiration.\n"
        "▶ 🔄 Renew Bulk : format `nombres jours` — ex. `1,3-5 30`.\n\n"
        "▶ 💾 Set Quota : format `nombres quota_GB` — ex. `1,3-5 50`.\n\n"
        "▶ 🔒 Lock/Unlock : bloque/débloque un compte sans le supprimer.\n\n"
        "▶ 🗑 Delete : un username, ou plusieurs par numéros/plages (ex. `1,3-5,7`).\n\n"
        "┌─ 🔧 SERVICES\n"
        "└ État de tous les services/protocoles (🟢 actif / 🔴 arrêté).\n\n"
        "┌─ 📈 SERVER\n"
        "└ OS, architecture, cœurs, uptime, IP publique.\n\n"
        "┌─ 🤝 RESELLERS (réservé à l'admin)\n"
        "Vous créez des sous-revendeurs disposant chacun de leur propre bot et quota.\n\n"
        "▶ ➕ New Reseller : nom → ID Telegram (0 = public) → token du bot revendeur\n"
        "→ expiration en jours → max d'utilisateurs → quota data GB → tunnels autorisés\n"
        "→ code d'accès (pour bot public).\n\n"
        "▶ ⚙️ Manage : activer/désactiver, supprimer (+son bot), prolonger l'expiration,\n"
        "modifier max users, modifier le quota GB.\n\n"
        "Les comptes des revendeurs sont comptés automatiquement. Les revendeurs "
        "expirés sont désactivés automatiquement chaque jour."
    )

    async def start(update,ctx):
        if not is_authorized(update.effective_user.id): await update.message.reply_text("⛔ Unauthorized.");return
        await show_main(update,ctx)

    async def cmd_help(update,ctx):
        if not is_authorized(update.effective_user.id): await update.message.reply_text("⛔ Unauthorized.");return
        try: await update.message.reply_text(HELP_TEXT,reply_markup=back_kb("main"),parse_mode="Markdown")
        except Exception: await update.message.reply_text(HELP_TEXT)

    async def show_main(update,ctx,edit=False):
        u=xray_user_count_bot()+count_users_bot("ssh")+count_users_bot("zivpn")+count_users_bot("hysteria")+count_users_bot("v2raydns")
        t=f"🤖 *KIGHMU PANEL BOT*\n━━━━━━━━━━━━━━━━━━━━━\n👥 Total Users: `{u}`\n🌐 IP: `{get_ip()}`\n📌 Domain: `{get_domain()}`\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n━━━━━━━━━━━━━━━━━━━━━"
        if edit: await update.callback_query.edit_message_text(t,reply_markup=main_kb(),parse_mode="Markdown")
        else: await update.message.reply_text(t,reply_markup=main_kb(),parse_mode="Markdown")

    async def callback_handler(update,ctx):
        q=update.callback_query;await q.answer()
        ctx.user_data["last_msg_id"]=q.message.message_id
        if not is_authorized(q.from_user.id): await q.edit_message_text("⛔ Unauthorized.");return
        d=q.data
        if d=="main": await show_main(update,ctx,edit=True)
        elif d=="dash":
            ux=xray_user_count_bot();us=count_users_bot("ssh");uz=count_users_bot("zivpn");uh=count_users_bot("hysteria");uv=count_users_bot("v2raydns")
            rt=sh_bot("free -m | awk '/^Mem:/{printf \"%.1f\", $2/1024}'")
            ru=sh_bot("free -m | awk '/^Mem:/{printf \"%.1f\", $3/1024}'")
            rp=sh_bot("free -m | awk '/^Mem:/{printf \"%d\", $3*100/$2}'")
            cp=sh_bot("top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | cut -d. -f1")
            dd, _dw, dm = _vnstat_data()
            t=f"📊 *DASHBOARD*\n━━━━━━━━━━━━━━━━━━━━━\n*USERS*\n• SSH: `{us}`\n• Xray: `{ux}`\n• ZIVPN: `{uz}`\n• Hysteria: `{uh}`\n• V2Ray-DNS: `{uv}`\n\n*DATA (VNSTAT)*\n• Aujourd'hui: `{dd}`\n• Ce mois: `{dm}`\n\n*RESOURCES*\n• RAM: `{ru}G / {rt}G` ({rp}%)\n• CPU: `{cp}%`"
            await q.edit_message_text(t,reply_markup=back_kb("main"),parse_mode="Markdown")
        elif d=="users": await q.edit_message_text("👥 *User Management*\nSelect an option:",reply_markup=users_kb(),parse_mode="Markdown")
        elif d=="services":
            l=["🔧 *SERVICES STATUS*\n"];ok=0
            for n,s in SERVICES.items():a=svc_active_bot(s);l.append(f"{'🟢' if a else '🔴'} {n}");ok+=a
            l.append(f"\n✅ {ok}/{len(SERVICES)} active")
            await q.edit_message_text("\n".join(l),reply_markup=back_kb("main"),parse_mode="Markdown")
        elif d=="server":
            upt=sh_bot("uptime -p 2>/dev/null | sed 's/up //'") or "N/A"
            t=f"🖥 *SERVER INFO*\n━━━━━━━━━━━━━━━━━━━━━\n• OS: `{get_os()}`\n• Arch: `{sh_bot('uname -m')}`\n• Cores: `{sh_bot('nproc 2>/dev/null || echo 1')}`\n• Uptime: `{upt}`\n• IP: `{get_ip()}`"
            await q.edit_message_text(t,reply_markup=back_kb("main"),parse_mode="Markdown")
        elif d=="cr_xray": await q.edit_message_text("Select Xray protocol:",reply_markup=xray_proto_kb(),parse_mode="Markdown")
        elif d=="cr_reseller":
            ctx.user_data["cr_reseller"]={};ctx.user_data["cr_step"]="name"
            await q.edit_message_text("✏️ Reseller client name:",reply_markup=back_kb("resellers"))
        elif d=="cr_rsel_done":
            crd=ctx.user_data.get("cr_reseller",{});tl=crd.get("tunnels",[])
            if not tl:await q.edit_message_text("❌ Select at least 1 tunnel.",reply_markup=back_kb("resellers"));return
            ctx.user_data["cr_step"]="done"
            rid=reseller_add(crd["name"],crd.get("tgid",0),crd["token"],crd["exp"],crd["max_u"],crd["quota"],tl,crd.get("access_code",""))
            reseller_create_service(rid,crd["token"])
            await q.edit_message_text(f"✅ Reseller #{rid} `{crd['name']}` created!\nService started.",reply_markup=back_kb("resellers"),parse_mode="Markdown")
            ctx.user_data.pop("cr_reseller",None);ctx.user_data.pop("cr_step",None)
        elif d.startswith("cr_rsel_"):
            tunnel=d[8:];crd=ctx.user_data.get("cr_reseller",{});sl=crd.get("tunnels",[])
            if tunnel in sl:sl.remove(tunnel)
            else:sl.append(tunnel)
            crd["tunnels"]=sl;ctx.user_data["cr_reseller"]=crd
            btns=[];all_t=["ssh","xray","v2ray","zivpn","hyst"]
            for t in all_t:mark="✅"if t in sl else"⬜";btns.append(InlineKeyboardButton(f"{mark} {t.upper()}",callback_data=f"cr_rsel_{t}"))
            btns.append(InlineKeyboardButton("✅ Done",callback_data="cr_rsel_done"))
            kb=InlineKeyboardMarkup([btns[i:i+3]for i in range(0,len(btns),3)]+[[btns[-1]]])
            await q.edit_message_text("Select tunnels for reseller:",reply_markup=kb)
        elif d.startswith("cr_"):
            p=d[3:];ctx.user_data["cr_proto"]=p;ctx.user_data["step"]="cr_user"
            pn={"vmess":"VMESS","vless":"VLESS","trojan":"Trojan","ssh":"SSH","v2ray":"V2Ray DNS","zivpn":"ZIVPN","hyst":"Hysteria"}.get(p,p)
            await q.edit_message_text(f"✏️ Username for *{pn}*:",parse_mode="Markdown")
        elif d.startswith("ls_"):
            p=d[3:];pn={"ssh":"SSH","xray":"Xray","v2ray":"V2Ray DNS","zivpn":"ZIVPN","hyst":"Hysteria"}.get(p,p);rows=[]
            if p=="xray":
                for qp in("vmess","vless","trojan","shadow"):
                    try:
                        with open(XRAY_USERS)as f:d2=json.load(f)
                        for u in d2.get(qp,[]):e=u.get("email","?").split("@")[0];rows.append((e,qp.upper(),_meta_get(e,"exp")or u.get("expire","?"),float(_meta_get(e,"quota")or"0"),get_xray_traffic(u.get("email",""))))
                    except: pass
            elif p=="v2ray":
                try:
                    with open(V2RAY_USERS)as f:d2=json.load(f)
                    for u in d2.get("vless",[]):e=u.get("email","?").split("@")[0];rows.append((e,"V2RAY",_meta_get(e,"exp")or u.get("expire","?"),float(_meta_get(e,"quota")or"0"),get_v2ray_traffic(u.get("email",""))))
                except: pass
            elif USERDIR.exists():
                for f in sorted(USERDIR.iterdir()):
                    if not f.is_file():continue
                    pp=_meta_get(f.name,"proto")
                    if(p=="ssh"and pp=="ssh")or(p=="zivpn"and pp=="zivpn")or(p=="hyst"and pp=="hysteria"):
                        rows.append((f.name,pp.upper(),_meta_get(f.name,"exp"),float(_meta_get(f.name,"quota")or"0"),get_ssh_traffic(f.name) if pp=="ssh" else 0))
            if not rows and p in("xray","v2ray") and USERDIR.exists():
                for f in sorted(USERDIR.iterdir()):
                    if not f.is_file():continue
                    pp=_meta_get(f.name,"proto")
                    if p=="xray" and pp in("vmess","vless","trojan"):
                        rows.append((f.name,pp.upper(),_meta_get(f.name,"exp"),float(_meta_get(f.name,"quota")or"0"),get_xray_traffic(f.name)))
                    elif p=="v2ray" and pp=="v2raydns":
                        rows.append((f.name,"V2RAY",_meta_get(f.name,"exp"),float(_meta_get(f.name,"quota")or"0"),get_v2ray_traffic(f.name)))
            if not rows: t=f"📋 *No {pn} users.*"
            else:
                l=[f"📋 *{pn}* ({len(rows)})\n\n",f"`  User      Proto    Exp         Traffic`",f"`{'─'*54}`"]
                for r in rows:n2,p2,x,qv,used=r;u2=fmt_bytes(used);t2=f"{u2} / {qv} GB"if qv>0 else f"{u2} / Unlimited";l.append(f"`  {n2:<10}{p2:<9}{x:<11}{t2}`")
                t="\n".join(l)
            try: await q.edit_message_text(t,reply_markup=back_kb("users"),parse_mode="Markdown")
            except: await q.edit_message_text(t.replace('*','').replace('`',''),reply_markup=back_kb("users"))
        elif d=="info_user": ctx.user_data["step"]="info_user";await q.edit_message_text("🔍 Username:",reply_markup=back_kb("users"))
        elif d=="del_user": ctx.user_data["step"]="del_sel_proto";await q.edit_message_text("🗑 Select:",reply_markup=del_proto_kb(),parse_mode="Markdown")
        elif d.startswith("del_proto_"):
            p=d[10:];ctx.user_data["del_proto"]=p;ctx.user_data["step"]="del_choose";users=get_users_by_proto(p)
            if not users: await q.edit_message_text(f"📋 No {p.upper()} users.",reply_markup=back_kb("del_user"),parse_mode="Markdown");ctx.user_data.clear();return
            l=[f"🗑 *{p.upper()} USERS*\nEnter numbers:\n"]+[f"`{i}.` {n} – exp: {e}"for i,(n,e)in enumerate(users,1)]
            await q.edit_message_text("\n".join(l),reply_markup=back_kb("del_user"),parse_mode="Markdown");ctx.user_data["del_users"]=users
        elif d=="renew_bulk": await q.edit_message_text("Select protocol:",reply_markup=proto_sel_kb("renew_bulk"),parse_mode="Markdown")
        elif d.startswith("renew_bulk_"):
            p=d[11:];ctx.user_data["renew_proto"]=p;users=get_users_by_proto(p)
            if not users: await q.edit_message_text(f"📋 No {p.upper()} users.",reply_markup=back_kb("users"),parse_mode="Markdown");ctx.user_data.clear();return
            l=[f"🔄 *{p.upper()} USERS*\nEnter: `numbers days`\nExample: `1,3-5 30`\n"]+[f"`{i}.` {n} – exp: {e}"for i,(n,e)in enumerate(users,1)]
            await q.edit_message_text("\n".join(l),reply_markup=back_kb("users"),parse_mode="Markdown");ctx.user_data["renew_users"]=users;ctx.user_data["step"]="renew_bulk_days"
        elif d=="set_quota": await q.edit_message_text("Select protocol:",reply_markup=proto_sel_kb("setquota"),parse_mode="Markdown")
        elif d.startswith("setquota_"):
            p=d[9:];ctx.user_data["sq_proto"]=p;users=get_users_by_proto(p)
            if not users: await q.edit_message_text(f"📋 No {p.upper()} users.",reply_markup=back_kb("users"),parse_mode="Markdown");ctx.user_data.clear();return
            l=[f"💾 *{p.upper()} USERS*\nEnter: `numbers quota_GB`\nExample: `1,3-5 50`\n"]+[f"`{i}.` {n} – exp: {e} – quota: {_detail_quota(_meta_get(n,'proto') or p, n, _meta_get(n,'quota') or '0')}"for i,(n,e)in enumerate(users,1)]
            await q.edit_message_text("\n".join(l),reply_markup=back_kb("users"),parse_mode="Markdown");ctx.user_data["sq_users"]=users;ctx.user_data["step"]="set_quota_val"
        elif d=="renew_user": ctx.user_data["step"]="renew_user";await q.edit_message_text("🔄 Username:",reply_markup=back_kb("users"))
        elif d=="lock_user": ctx.user_data["step"]="lock_user";await q.edit_message_text("🔒 Username:",reply_markup=back_kb("users"))
        elif d.startswith("confirm_del_"):user=d[12:];delete_user(user);await q.edit_message_text(f"✅ `{user}` deleted.",reply_markup=back_kb("users"),parse_mode="Markdown")
        elif d.startswith("confirm_lock_"):
            user=d[13:]
            if (USERDIR/user).exists():
                if is_locked(user): unlock_user(user);t=f"🔓 `{user}` unlocked."
                else: lock_user(user);t=f"🔒 `{user}` locked."
                await q.edit_message_text(t,reply_markup=back_kb("users"),parse_mode="Markdown")
            else: await q.edit_message_text(f"❌ `{user}` not found.",reply_markup=back_kb("users"),parse_mode="Markdown")
        elif d=="help":
            h="""🤖 *KIGHMU PANEL BOT* v3.9.9
━━━━━━━━━━━━━━━━━━━━━━━━━━━━
*/start* – Show main menu

📊 *DASHBOARD*
Server stats: users, expiry, traffic (day/week/month), OS, CPU, RAM, disk, active protocols.

👥 *USERS – Create & Manage*
Create: SSH – Xray (VMESS/VLESS/Trojan) – V2Ray DNS – ZIVPN – Hysteria
• Username → Expiry days → Password (or `auto`) → Quota GB
• Passwords auto-generated if empty / `auto`

List by protocol – view all users with expiry & traffic.

Info: tap 🔍 Info User → enter username → full connection details.

Renew: tap 🔄 Renew → username → days.
Renew Bulk: tap 🔄 Renew Bulk → proto → `numbers days` (e.g. `1,3-5 30`).

Lock/Unlock: toggle access without deleting.

Delete: single user or bulk (comma/range, e.g. `1,3-5,7`).

🔧 *SERVICES*
Status of all protocols (🟢 active / 🔴 stopped).
Control via main panel menu (option 4 Protocol Installer).

📈 *SERVER*
OS, architecture, CPU cores, uptime, public IP.

🤝 *RESELLERS*
➕ New Reseller: name → TG ID (0=public) → bot token → expiry days → max users → quota GB → tunnels → access code

⚙️ Manage: tap a reseller number →
• 🔄 Toggle Active – enable/disable
• 🗑 Delete – remove reseller + bot service
• 📅 Extend Expiry – add days
• 👥 Max Users – update user limit
• 💾 Data Quota – update GB limit

Reseller user count is auto-calculated from actual users.
Expired resellers auto-deactivated daily by cron.

💡 Tip: Use `auto` as password for random generation."""
            await q.edit_message_text(h,reply_markup=back_kb("main"),parse_mode="Markdown")
        elif d=="resellers":
            await q.edit_message_text("🤝 *RESELLERS*\nChoose an option:",reply_markup=reseller_main_kb(),parse_mode="Markdown")
        elif d=="manage_resellers":
            rl=reseller_list()
            if not rl:
                await q.edit_message_text("🤝 *No resellers yet.*",reply_markup=back_kb("resellers"),parse_mode="Markdown")
            else:
                l=["🤝 *MANAGE RESELLERS*\n"]
                for r in rl:
                    status="🟢"if r["active"]else"🔴";u=reseller_user_count(r["id"])
                    l.append(f"{status} #{r['id']} *{r['client_name']}* – 👥 {u}/{r['max_users']} – 📅 {r['expires_at']}")
                num_btns=[InlineKeyboardButton(str(r["id"]),callback_data=f"view_reseller_{r['id']}")for r in rl]
                kb_rows=[num_btns[i:i+5]for i in range(0,len(num_btns),5)]
                kb_rows.append([InlineKeyboardButton("⬅️ Back",callback_data="resellers")])
                await q.edit_message_text("\n".join(l),reply_markup=InlineKeyboardMarkup(kb_rows),parse_mode="Markdown")
        elif d.startswith("view_reseller_"):
            rid=int(d[14:]);r=reseller_get(rid)
            if not r:await q.edit_message_text("❌ Reseller not found.",reply_markup=back_kb("resellers"));return
            s="🟢 Active"if r["active"]else"🔴 Inactive";u=reseller_user_count(rid)
            tl=", ".join(json.loads(r["tunnels"]))
            t=f"🤝 *Reseller #{rid}*\n━━━━━━━━━━━━━━━━\n• Name: `{r['client_name']}`\n• TG ID: `{r['telegram_id']}`\n• Status: {s}\n• Expires: `{r['expires_at']}`\n• Users: `{u}/{r['max_users']}`\n• Data Quota: `{fmt_bytes(reseller_data_used(rid))} / {r['data_quota_gb']} GB`\n• Tunnels: `{tl}`"
            kb=InlineKeyboardMarkup([[InlineKeyboardButton("🔄 Toggle Active",callback_data=f"toggle_reseller_{rid}"),InlineKeyboardButton("🗑 Delete",callback_data=f"del_cfm_reseller_{rid}")],[InlineKeyboardButton("📅 Extend Expiry",callback_data=f"extend_reseller_{rid}"),InlineKeyboardButton("👥 Max Users",callback_data=f"maxu_reseller_{rid}")],[InlineKeyboardButton("💾 Data Quota",callback_data=f"quota_reseller_{rid}"),InlineKeyboardButton("🔑 Access Code",callback_data=f"code_reseller_{rid}")],[InlineKeyboardButton("⬅️ Back",callback_data="resellers")]])
            await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
        elif d.startswith("toggle_reseller_"):
            rid=int(d[16:]);reseller_toggle(rid);r=reseller_get(rid)
            await q.edit_message_text(f"🔄 Reseller #{rid} {'activated' if r['active'] else 'deactivated'}.",reply_markup=back_kb("resellers"))
        elif d.startswith("del_cfm_reseller_"):
            rid=int(d[17:]);r=reseller_get(rid)
            if r:
                if USERDIR.exists():
                    for f in USERDIR.iterdir():
                        if f.is_file() and _meta_get(f.name,"reseller")==str(rid):delete_user(f.name)
                reseller_remove_service(rid);reseller_delete(rid)
            await q.edit_message_text(f"🗑 Reseller #{rid} + all their users deleted.",reply_markup=back_kb("resellers"))
        elif d.startswith("extend_reseller_"):
            rid=int(d[16:]);r=reseller_get(rid)
            if not r:await q.edit_message_text("❌ Reseller not found.",reply_markup=back_kb("resellers"));return
            ctx.user_data["extend_rid"]=rid;ctx.user_data["step"]="extend_reseller"
            await q.edit_message_text(f"📅 Additional *days* for `{r['client_name']}` (current: {r['expires_at']}):",reply_markup=back_kb("resellers"),parse_mode="Markdown")
        elif d.startswith("maxu_reseller_"):
            rid=int(d[14:]);r=reseller_get(rid)
            if not r:await q.edit_message_text("❌ Reseller not found.",reply_markup=back_kb("resellers"));return
            ctx.user_data["edit_rid"]=rid;ctx.user_data["step"]="edit_maxu"
            await q.edit_message_text(f"👥 New *max users* for `{r['client_name']}` (current: {r['max_users']}):",reply_markup=back_kb("resellers"),parse_mode="Markdown")
        elif d.startswith("quota_reseller_"):
            rid=int(d[15:]);r=reseller_get(rid)
            if not r:await q.edit_message_text("❌ Reseller not found.",reply_markup=back_kb("resellers"));return
            ctx.user_data["edit_rid"]=rid;ctx.user_data["step"]="edit_quota"
            await q.edit_message_text(f"💾 New *data quota (GB)* for `{r['client_name']}` (current: {r['data_quota_gb']}):",reply_markup=back_kb("resellers"),parse_mode="Markdown")
        elif d.startswith("code_reseller_"):
            rid=int(d[14:]);r=reseller_get(rid)
            if not r:await q.edit_message_text("❌ Reseller not found.",reply_markup=back_kb("resellers"));return
            cur=r["access_code"] or "—"
            t=f"🔑 *Access Code — Reseller #{rid}*\n━━━━━━━━━━━━━━━━\n• Name: `{r['client_name']}`\n• Current code: `{cur}`\n\n" \
              "Send the new access code (or `clear` to remove it):"
            ctx.user_data["code_rid"]=rid;ctx.user_data["step"]="edit_code"
            kb=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data=f"view_reseller_{rid}")]])
            await q.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
    async def text_handler(update,ctx):
        if not is_authorized(update.effective_user.id): await update.message.reply_text("⛔ Unauthorized.");return
        text=update.message.text.strip();step=ctx.user_data.get("step","");proto=ctx.user_data.get("cr_proto","")
        mid=ctx.user_data.get("last_msg_id")
        if mid:
            try: await ctx.bot.delete_message(chat_id=update.effective_chat.id,message_id=mid)
            except: pass
        try: await update.message.delete()
        except: pass
        if step=="cr_user":
            if not re.match(r'^[a-zA-Z0-9._-]+$',text): await update.message.reply_text("❌ Invalid username.");return
            ctx.user_data["cr_username"]=text;ctx.user_data["step"]="cr_days";await reply_cls(update,ctx,"✏️ Expiry in *days*:",parse_mode="Markdown")
        elif step=="cr_days":
            if not text.isdigit()or int(text)<1: await update.message.reply_text("❌ >=1");return
            ctx.user_data["cr_days"]=text
            if proto in("ssh","zivpn","hyst","trojan"):ctx.user_data["step"]="cr_pass";await reply_cls(update,ctx,"✏️ Password (or `auto`):",parse_mode="Markdown")
            else:ctx.user_data["step"]="cr_quota";await reply_cls(update,ctx,"✏️ Quota GB (0=unlimited):",parse_mode="Markdown")
        elif step=="cr_pass":
            p=text if text!="auto"else gen_pass();ctx.user_data["cr_pass"]=p
            if proto in("trojan","ssh"):ctx.user_data["step"]="cr_quota";await reply_cls(update,ctx,"✏️ Quota GB (0=unlimited):",parse_mode="Markdown")
            else:ctx.user_data["cr_quota"]="0";await do_create(update,ctx)
        elif step=="cr_quota":
            if not re.match(r'^[0-9]+\.?[0-9]*$',text): await update.message.reply_text("❌ Invalid number.");return
            ctx.user_data["cr_quota"]=text if float(text)>0 else"0";await do_create(update,ctx)
        elif step=="info_user":
            user=text
            if not (USERDIR/user).exists():await reply_cls(update,ctx,f"❌ `{user}` not found.",reply_markup=back_kb("users"),parse_mode="Markdown");ctx.user_data.clear();return
            p=_meta_get(user,"proto");e=_meta_get(user,"exp");pw=_meta_get(user,"pass");u=_meta_get(user,"uuid");q=_meta_get(user,"quota")or"0"
            bd={"ssh":build_ssh_details,"vless":build_vless_details,"trojan":build_trojan_details,"vmess":build_vmess_details,"zivpn":build_zivpn_details,"hysteria":build_hysteria_details,"v2raydns":build_v2raydns_details}
            fn=bd.get(p)
            if fn:
                if p in("vless","vmess","v2raydns"):txt=fn(user,u or "?",e,q)
                else:txt=fn(user,pw or user,e,q)
            else:txt=f"👤 *User: {user}*\nProto: `{p}`\nExp: `{e}`"
            await reply_cls(update,ctx,txt,reply_markup=back_kb("users"),parse_mode="Markdown");ctx.user_data.clear()
        elif step=="del_choose":
            users=ctx.user_data.get("del_users",[])
            if not users:await reply_cls(update,ctx,"❌ No users.",reply_markup=back_kb("users"));ctx.user_data.clear();return
            nums=set()
            for pt in text.replace(" ","").split(","):
                if not pt:continue
                if"-"in pt:
                    a,b=pt.split("-",1)
                    if a.isdigit()and b.isdigit():nums.update(range(int(a),int(b)+1))
                elif pt.isdigit():nums.add(int(pt))
            td=[users[n-1][0]for n in sorted(nums)if 1<=n<=len(users)]
            if not td:await update.message.reply_text("❌ No valid numbers.");return
            for u in td:delete_user(u)
            await reply_cls(update,ctx,f"🗑 Deleted `{len(td)}` user(s).",reply_markup=back_kb("users"),parse_mode="Markdown");ctx.user_data.clear()
        elif step=="del_user":
            user=text
            if not(USERDIR/user).exists():await reply_cls(update,ctx,f"❌ `{user}` not found.",reply_markup=back_kb("users"),parse_mode="Markdown")
            else:await reply_cls(update,ctx,f"🗑 Delete `{user}`?",reply_markup=yesno_kb("confirm_del",user),parse_mode="Markdown")
            ctx.user_data.clear()
        elif step=="renew_user":
            user=text
            if not(USERDIR/user).exists():await reply_cls(update,ctx,f"❌ `{user}` not found.",reply_markup=back_kb("users"),parse_mode="Markdown");ctx.user_data.clear();return
            ctx.user_data["renew_user"]=user;ctx.user_data["step"]="renew_days";await reply_cls(update,ctx,"✏️ Additional *days*:",parse_mode="Markdown")
        elif step=="renew_days":
            if not text.isdigit()or int(text)<1:await update.message.reply_text("❌ >=1");return
            user=ctx.user_data.get("renew_user","");days=int(text)
            old=_meta_get(user,"exp")
            if old and old!="permanent":
                try:ne=(datetime.strptime(old,"%Y-%m-%d")+timedelta(days=days)).strftime("%Y-%m-%d")
                except:ne=sh(f"date -d '+{days}days' +%Y-%m-%d")
            else:ne=sh(f"date -d '+{days}days' +%Y-%m-%d")
            _meta_set(user,"exp",ne)
            if _meta_get(user,"proto")=="ssh":sh(f"chage -E {ne} {user} 2>/dev/null")
            await reply_cls(update,ctx,f"✅ `{user}` → `{ne}`",reply_markup=back_kb("users"),parse_mode="Markdown");ctx.user_data.clear()
        elif step=="renew_bulk_days":
            parts=text.rsplit(None,1)
            if len(parts)!=2 or not parts[1].isdigit():await update.message.reply_text("❌ Usage: `numbers days`  e.g. `1,3-5 30`");return
            nums,days=set(),int(parts[1])
            for pt in parts[0].replace(" ","").split(","):
                if"-"in pt:
                    a,b=pt.split("-",1)
                    if a.isdigit()and b.isdigit():nums.update(range(int(a),int(b)+1))
                elif pt.isdigit():nums.add(int(pt))
            users=ctx.user_data.get("renew_users",[])
            td=[users[n-1][0]for n in sorted(nums)if 1<=n<=len(users)]
            if not td:await update.message.reply_text("❌ No valid numbers.");return
            for u in td:
                old=_meta_get(u,"exp")
                if old and old!="permanent":
                    try:ne=(datetime.strptime(old,"%Y-%m-%d")+timedelta(days=days)).strftime("%Y-%m-%d")
                    except:ne=sh(f"date -d '+{days}days' +%Y-%m-%d")
                else:ne=sh(f"date -d '+{days}days' +%Y-%m-%d")
                _meta_set(u,"exp",ne)
                if _meta_get(u,"proto")=="ssh":sh(f"chage -E {ne} {u} 2>/dev/null")
            await reply_cls(update,ctx,f"✅ Renewed `{len(td)}` user(s) +{days} days",reply_markup=back_kb("users"),parse_mode="Markdown");ctx.user_data.clear()
        elif step=="set_quota_val":
            parts=text.rsplit(None,1)
            if len(parts)!=2 or not re.match(r'^[0-9]+\.?[0-9]*$',parts[1]):await update.message.reply_text("❌ Usage: `numbers quota_GB`  e.g. `1,3-5 50`");return
            nums,q=set(),float(parts[1])
            for pt in parts[0].replace(" ","").split(","):
                if"-"in pt:
                    a,b=pt.split("-",1)
                    if a.isdigit()and b.isdigit():nums.update(range(int(a),int(b)+1))
                elif pt.isdigit():nums.add(int(pt))
            users=ctx.user_data.get("sq_users",[])
            td=[users[n-1][0]for n in sorted(nums)if 1<=n<=len(users)]
            if not td:await update.message.reply_text("❌ No valid numbers.");return
            for u in td:set_user_quota(u,q)
            await reply_cls(update,ctx,f"✅ Quota set to `{q} GB` for `{len(td)}` user(s)",reply_markup=back_kb("users"),parse_mode="Markdown");ctx.user_data.clear()
        elif step=="lock_user":
            user=text
            if not(USERDIR/user).exists():await reply_cls(update,ctx,f"❌ `{user}` not found.",reply_markup=back_kb("users"),parse_mode="Markdown")
            else:await reply_cls(update,ctx,f"🔒 Toggle `{user}`?",reply_markup=yesno_kb("confirm_lock",user),parse_mode="Markdown")
            ctx.user_data.clear()
        elif step=="edit_maxu":
            if not text.isdigit()or int(text)<1:await reply_cls(update,ctx,"❌ Enter a positive number:");return
            rid=ctx.user_data.get("edit_rid",0);init_reseller_db()
            conn=sqlite3.connect(str(RESELLER_DB))
            conn.execute("UPDATE resellers SET max_users=? WHERE id=?",(int(text),rid))
            conn.commit();conn.close()
            r=reseller_get(rid);await reply_cls(update,ctx,f"✅ `{r['client_name']}` max users → `{text}`",reply_markup=back_kb("resellers"),parse_mode="Markdown")
            ctx.user_data.clear()
        elif step=="edit_quota":
            if not re.match(r'^[0-9]+\.?[0-9]*$',text):await reply_cls(update,ctx,"❌ Invalid number:");return
            rid=ctx.user_data.get("edit_rid",0);init_reseller_db()
            conn=sqlite3.connect(str(RESELLER_DB))
            conn.execute("UPDATE resellers SET data_quota_gb=? WHERE id=?",(float(text),rid))
            conn.commit();conn.close()
            r=reseller_get(rid);await reply_cls(update,ctx,f"✅ `{r['client_name']}` quota → `{text} GB`",reply_markup=back_kb("resellers"),parse_mode="Markdown")
            ctx.user_data.clear()
        elif step=="extend_reseller":
            if not text.isdigit()or int(text)<1:await reply_cls(update,ctx,"❌ Enter a positive number of days:");return
            rid=ctx.user_data.get("extend_rid",0)
            if reseller_extend_expiry(rid,int(text)):
                r=reseller_get(rid);await reply_cls(update,ctx,f"✅ `{r['client_name']}` extended → `{r['expires_at']}`",reply_markup=back_kb("resellers"),parse_mode="Markdown")
            else:await reply_cls(update,ctx,"❌ Reseller not found.",reply_markup=back_kb("resellers"))
            ctx.user_data.clear()
        elif step=="edit_code":
            rid=ctx.user_data.get("code_rid",0);r=reseller_get(rid)
            if not r:await reply_cls(update,ctx,"❌ Reseller not found.",reply_markup=back_kb("resellers"));ctx.user_data.clear();return
            code="" if text.strip().lower()=="clear"else text.strip()
            init_reseller_db()
            conn=sqlite3.connect(str(RESELLER_DB))
            conn.execute("UPDATE resellers SET access_code=? WHERE id=?",(code,rid))
            conn.commit();conn.close()
            msg=f"🔑 Access code for `{r['client_name']}`: `{code}`"if code else f"🔑 Access code removed for `{r['client_name']}`."
            await reply_cls(update,ctx,msg,reply_markup=back_kb("resellers"),parse_mode="Markdown")
            ctx.user_data.clear()
        elif ctx.user_data.get("cr_step")=="name":
            crd=ctx.user_data.get("cr_reseller",{});crd["name"]=text;ctx.user_data["cr_reseller"]=crd
            ctx.user_data["cr_step"]="tgid";await reply_cls(update,ctx,"✏️ Reseller Telegram ID (0=public, multiple users):",parse_mode="Markdown")
        elif ctx.user_data.get("cr_step")=="tgid":
            if not text.isdigit():await reply_cls(update,ctx,"❌ Must be numeric (0 = public):");return
            crd=ctx.user_data.get("cr_reseller",{});crd["tgid"]=int(text);ctx.user_data["cr_reseller"]=crd
            ctx.user_data["cr_step"]="access_code";await reply_cls(update,ctx,"✏️ Access code for public bot (or /skip):",parse_mode="Markdown")
        elif ctx.user_data.get("cr_step")=="access_code":
            crd=ctx.user_data.get("cr_reseller",{});crd["access_code"]="" if text=="/skip"else text;ctx.user_data["cr_reseller"]=crd
            ctx.user_data["cr_step"]="token";await reply_cls(update,ctx,"✏️ Reseller Bot Token (from @BotFather):",parse_mode="Markdown")
        elif ctx.user_data.get("cr_step")=="token":
            if len(text)<10:await reply_cls(update,ctx,"❌ Token too short:");return
            crd=ctx.user_data.get("cr_reseller",{});crd["token"]=text;ctx.user_data["cr_reseller"]=crd
            ctx.user_data["cr_step"]="exp";await reply_cls(update,ctx,"✏️ Expiry in days (e.g. 30, 365):",parse_mode="Markdown")
        elif ctx.user_data.get("cr_step")=="exp":
            if not text.isdigit()or int(text)<1:await reply_cls(update,ctx,"❌ >=1");return
            crd=ctx.user_data.get("cr_reseller",{});crd["exp"]=exp_in_days(int(text));ctx.user_data["cr_reseller"]=crd
            ctx.user_data["cr_step"]="max_u";await reply_cls(update,ctx,"✏️ Max users reseller can create:",parse_mode="Markdown")
        elif ctx.user_data.get("cr_step")=="max_u":
            if not text.isdigit()or int(text)<1:await reply_cls(update,ctx,"❌ >=1");return
            crd=ctx.user_data.get("cr_reseller",{});crd["max_u"]=int(text);ctx.user_data["cr_reseller"]=crd
            ctx.user_data["cr_step"]="quota";await reply_cls(update,ctx,"✏️ Data quota GB per reseller (0=unlimited):",parse_mode="Markdown")
        elif ctx.user_data.get("cr_step")=="quota":
            if not re.match(r'^[0-9]+\.?[0-9]*$',text):await reply_cls(update,ctx,"❌ Invalid number.");return
            crd=ctx.user_data.get("cr_reseller",{});crd["quota"]=float(text)if float(text)>0 else 0;ctx.user_data["cr_reseller"]=crd
            sl=crd.get("tunnels",[]);all_t=["ssh","xray","v2ray","zivpn","hyst"]
            btns=[]
            for t in all_t:btns.append(InlineKeyboardButton(f"⬜ {t.upper()}",callback_data=f"cr_rsel_{t}"))
            btns.append(InlineKeyboardButton("✅ Done",callback_data="cr_rsel_done"))
            kb=InlineKeyboardMarkup([btns[i:i+3]for i in range(0,len(btns),3)]+[[btns[-1]]])
            await reply_cls(update,ctx,"Select tunnels for reseller, then Done:",reply_markup=kb)

    async def do_create(update,ctx):
        proto=ctx.user_data.get("cr_proto","");user=ctx.user_data.get("cr_username","")
        days=ctx.user_data.get("cr_days","30");pwd=ctx.user_data.get("cr_pass","");quota=ctx.user_data.get("cr_quota","0")
        pm={"ssh":"ssh","vmess":"vmess","vless":"vless","trojan":"trojan","v2ray":"v2raydns","zivpn":"zivpn","hyst":"hysteria"}
        nm={"ssh":"SSH","vmess":"VMESS","vless":"VLESS","trojan":"Trojan","v2ray":"V2Ray DNS","zivpn":"ZIVPN","hyst":"Hysteria"}
        rp=pm.get(proto,proto);pn=nm.get(proto,rp.upper());exp=exp_in_days(int(days))
        rc=create_user(rp,user,int(days),pwd,"1",quota)
        if rc!=0:
            msgs={1:"Invalid username",2:"Already exists"}
            await update.message.reply_text(f"❌ {msgs.get(rc,'Error')}.",reply_markup=back_kb("users"),parse_mode="Markdown")
            ctx.user_data.clear();return
        apw=_meta_get(user,"pass")or pwd;uuid=_meta_get(user,"uuid")or ""
        bd={"ssh":build_ssh_details,"vless":build_vless_details,"trojan":build_trojan_details,"vmess":build_vmess_details,"zivpn":build_zivpn_details,"hysteria":build_hysteria_details,"v2raydns":build_v2raydns_details}
        fn=bd.get(rp)
        if fn:
            if rp in("vless","vmess","v2raydns"):txt=fn(user,uuid or "?",exp,quota)
            else:txt=fn(user,apw or user,exp,quota)
        else:txt=f"✅ *{pn} created!*\nUser: `{user}`\nExp: `{exp}`"
        await reply_cls(update,ctx,txt,reply_markup=back_kb("users"),parse_mode="Markdown");ctx.user_data.clear()

    async def error_handler(update,ctx):
        log.error(f"Update {update} caused error {ctx.error}")

async def _admin_post_init(app):
        try:
            await app.bot.set_my_commands([("start","Démarrer le bot"),("help","Comment utiliser le bot")])
        except Exception as e: log.error(f"set_my_commands(admin) failed: {e}")

def run_bot():
    if not BOT_AVAILABLE: log.error("python-telegram-bot not installed");return
    if not TOKEN: log.error("No bot token");return
    app=Application.builder().token(TOKEN).post_init(_admin_post_init).build()
    app.add_handler(CommandHandler("start",start))
    app.add_handler(CommandHandler("help",cmd_help))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_handler))
    app.add_error_handler(error_handler)
    log.info("Kighmu Bot started");app.run_polling(allowed_updates=Update.ALL_TYPES)

# ── Reseller Bot ─────────────────────────────────────────────────────────────────
if BOT_AVAILABLE:
    def _r_access_path(rid):
        return STATEDIR / f"reseller_access_{rid}.json"

    def _r_access_authorized(rid, tgid):
        try:
            p = _r_access_path(rid)
            if not p.exists(): return False
            return str(tgid) in json.loads(p.read_text()).get("authorized", [])
        except: return False

    def _r_access_grant(rid, tgid):
        try:
            STATEDIR.mkdir(parents=True, exist_ok=True)
            p = _r_access_path(rid)
            d = json.loads(p.read_text()) if p.exists() else {"authorized": []}
            if str(tgid) not in d["authorized"]: d["authorized"].append(str(tgid))
            p.write_text(json.dumps(d, indent=2))
        except Exception as e:
            log.error(f"access grant failed: {e}")

    def _r_auth(update, r):
        if not r or not r["active"]: return "deny", "⛔ Reseller account disabled."
        if r["expires_at"] < date.today().isoformat(): return "deny", "⛔ Account expired, contact admin."
        if r["telegram_id"] != 0 and update.effective_user.id != r["telegram_id"]: return "deny", "⛔ Unauthorized."
        if r["access_code"] and r["telegram_id"] == 0 and not _r_access_authorized(r["id"], update.effective_user.id):
            return "code", ""
        return "ok", ""

    RESELLER_HELP = (
        "🤝 *Reseller Bot* — Aide complète\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        "Ce bot vous permet de gérer *vos* utilisateurs, dans la limite des tunnels "
        "autorisés par votre abonnement revendeur.\n\n"
        "Commands :\n"
        "• /start — Affiche mon espace\n"
        "• /help — Affiche cette aide\n\n"
        "┌─ 👥 MES USERS\n"
        "└ Résumé : vos utilisateurs par tunnel (SSH, Xray, V2Ray DNS, ZIVPN, "
        "Hysteria) et votre total (utilisés / maximum autorisé).\n\n"
        "┌─ ➕ CRÉER UN UTILISATEUR\n"
        "1. Choisissez le tunnel autorisé (bouton Create)\n"
        "2. Username (chiffres, lettres, . _ -)\n"
        "3. Expiration en jours\n"
        "4. Mot de passe (ou `auto`)\n"
        "5. Quota en GB (0 = illimité)\n"
        "→ Le bot vous envoie les détails de connexion.\n\n"
        "┌─ 📋 LISTER\n"
        "└ Tunnel choisi → vos utilisateurs avec n°, expiration et trafic utilisée / quota.\n\n"
        "┌─ 🔄 RENOUVELER\n"
        "└ Username puis jours à ajouter.\n\n"
        "┌─ 💾 DÉFINIR LE QUOTA\n"
        "└ Username puis quota en GB (0 = illimité).\n\n"
        "┌─ 🗑 SUPPRIMER\n"
        "└ Tunnel puis numéros (ex. `1,3-5`), uniquement vos utilisateurs.\n\n"
        "┌─ ℹ️ VOS LIMITES\n"
        "• Vous ne gérez QUE vos comptes.\n"
        "• Max utilisateurs : votre plafond (utilisés / max).\n"
        "• Tunnels : uniquement ceux autorisés par l'administrateur.\n"
        "• Expiration : celle de votre compte revendeur.\n\n"
        "En cas de blocage ou de limite atteinte, contactez votre administrateur."
    )

    async def cmd_help_reseller(update,ctx):
        rid=ctx.bot_data.get("reseller_id",0);r=reseller_get(rid)
        ok,msg=_r_auth(update,r)
        if ok=="code":
            ctx.user_data["r_step"]="r_access";await update.message.reply_text("🔑 Enter access code:",parse_mode="Markdown")
            return
        if ok!="ok":await update.message.reply_text(msg);return
        try: await update.message.reply_text(RESELLER_HELP,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data="r_main")]]),parse_mode="Markdown")
        except Exception: await update.message.reply_text(RESELLER_HELP)

    async def start_reseller(update,ctx):
        rid=ctx.bot_data.get("reseller_id",0);r=reseller_get(rid)
        ok,msg=_r_auth(update,r)
        if ok=="code":
            ctx.user_data["r_step"]="r_access";await update.message.reply_text("🔑 Enter access code:",parse_mode="Markdown")
            return
        if ok!="ok":await update.message.reply_text(msg);return
        await show_main_reseller(update,ctx)

    async def show_main_reseller(update,ctx,edit=False):
        rid=ctx.bot_data.get("reseller_id",0);r=reseller_get(rid)
        if not r:return
        u=reseller_user_count(rid);exp=r["expires_at"];tl=", ".join(json.loads(r["tunnels"]))
        auth_str="👤 Public bot" if r["telegram_id"]==0 else f"👤 Authorized: `{r['telegram_id']}`"
        t=f"🤝 *Reseller: {r['client_name']}*\n━━━━━━━━━━━━━━━━\n• Users: `{u}/{r['max_users']}`\n• Expires: `{exp}`\n• Tunnels: `{tl}`\n{auth_str}"
        kb=InlineKeyboardMarkup(build_menu([InlineKeyboardButton("👥 My Users",callback_data="r_users"),InlineKeyboardButton("❓ Help",callback_data="r_help")]))
        if edit:await update.callback_query.edit_message_text(t,reply_markup=kb,parse_mode="Markdown")
        else:await update.message.reply_text(t,reply_markup=kb,parse_mode="Markdown")

    def reseller_users_kb(rid):
        r=reseller_get(rid);tl=json.loads(r["tunnels"])if r else[]
        btns=[]
        for t in tl:
            names={"ssh":"SSH","xray":"Xray","v2ray":"V2Ray DNS","zivpn":"ZIVPN","hyst":"Hysteria"}
            btns.append(InlineKeyboardButton(f"➡️ Create {names.get(t,t)}",callback_data=f"r_cr_{t}"))
            btns.append(InlineKeyboardButton(f"📋 List {names.get(t,t)}",callback_data=f"r_ls_{t}"))
        btns.append(InlineKeyboardButton("🔄 Renew",callback_data="r_renew"))
        btns.append(InlineKeyboardButton("💾 Set Quota",callback_data="r_setquota"))
        btns.append(InlineKeyboardButton("🗑 Delete",callback_data="r_del"))
        btns.append(InlineKeyboardButton("⬅️ Back",callback_data="r_main"))
        return InlineKeyboardMarkup(build_menu(btns))

    def r_del_proto_kb(rid):
        r=reseller_get(rid);tl=json.loads(r["tunnels"])if r else[]
        names={"ssh":"SSH","xray":"Xray","v2ray":"V2Ray DNS","zivpn":"ZIVPN","hyst":"Hysteria"}
        btns=[]
        for t in tl:btns.append(InlineKeyboardButton(f"🗑 {names.get(t,t)}",callback_data=f"r_del_proto_{t}"))
        btns.append(InlineKeyboardButton("⬅️ Back",callback_data="r_users"))
        return InlineKeyboardMarkup(build_menu(btns))

    async def callback_handler_reseller(update,ctx):
        q=update.callback_query;await q.answer()
        rid=ctx.bot_data.get("reseller_id",0);r=reseller_get(rid)
        ok,msg=_r_auth(update,r)
        if ok=="code":
            ctx.user_data["r_step"]="r_access";await q.edit_message_text("🔑 Enter access code:",parse_mode="Markdown")
            return
        if ok!="ok":await q.edit_message_text(msg);return
        d=q.data
        if d=="r_main":await show_main_reseller(update,ctx,edit=True)
        elif d=="r_users":
            tl=json.loads(r["tunnels"])
            l=["👥 *MY USERS*\n"]
            for t in tl:
                names={"ssh":"SSH","xray":"Xray","v2ray":"V2Ray DNS","zivpn":"ZIVPN","hyst":"Hysteria"}
                cnt=len(_users_by_reseller(t,rid))
                l.append(f"• {names.get(t,t)}: `{cnt}`")
            l.append(f"\nTotal: `{reseller_user_count(rid)}/{r['max_users']}`")
            await q.edit_message_text("\n".join(l),reply_markup=reseller_users_kb(rid),parse_mode="Markdown")
        elif d=="r_renew":
            ctx.user_data["r_step"]="r_renew_user";await q.edit_message_text("🔄 Username to renew:",parse_mode="Markdown")
        elif d=="r_setquota":
            ctx.user_data["r_step"]="r_setquota_user";await q.edit_message_text("💾 Username to set quota:",parse_mode="Markdown")
        elif d=="r_del":
            await q.edit_message_text("🗑 Select protocol to delete:",reply_markup=r_del_proto_kb(rid))
        elif d.startswith("r_del_proto_"):
            p=d[12:];ctx.user_data["r_del_proto"]=p;ctx.user_data["r_step"]="r_del_choose"
            users=_users_by_reseller(p,rid)
            if not users:await q.edit_message_text(f"📋 No {p.upper()} users.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data="r_del")]]));ctx.user_data.clear();return
            l=[f"🗑 *{p.upper()} USERS*\nEnter numbers to delete:\n"]+[f"`{i}.` {n} – exp: {e}"for i,(n,e,_,_,_)in enumerate(users,1)]
            ctx.user_data["r_del_users"]=users
            await q.edit_message_text("\n".join(l),reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data="r_del")]]),parse_mode="Markdown")
        elif d=="r_cr_xray":
            await q.edit_message_text("Select Xray protocol:",reply_markup=InlineKeyboardMarkup(build_menu([InlineKeyboardButton("VMESS",callback_data="r_cr_vmess"),InlineKeyboardButton("VLESS",callback_data="r_cr_vless"),InlineKeyboardButton("Trojan",callback_data="r_cr_trojan"),InlineKeyboardButton("⬅️ Back",callback_data="r_users")])))
        elif d.startswith("r_cr_"):
            p=d[5:];ctx.user_data["r_proto"]=p;ctx.user_data["r_step"]="r_user";ctx.user_data["r_rid"]=rid
            await q.edit_message_text(f"✏️ Username:",parse_mode="Markdown")
        elif d.startswith("r_ls_"):
            p=d[5:];names={"ssh":"SSH","xray":"Xray","v2ray":"V2Ray DNS","zivpn":"ZIVPN","hyst":"Hysteria"}
            users=_users_by_reseller(p,rid)
            if users:
                l=[f"📋 *{names.get(p,p)}* ({len(users)})\n",f"`  #  User         Exp         Traffic`",f"`{'─'*44}`"]
                for i,(n,_,e,qu,used)in enumerate(users,1):
                    u2=fmt_bytes(used);t2=f"{u2} / {qu} GB"if qu>0 else f"{u2} / Unlimited"
                    l.append(f"`{i:>3}. {n:<14}{e:<11}{t2}`")
                t="\n".join(l)
            else:t=f"📋 No {names.get(p,p)} users."
            try:await q.edit_message_text(t,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data="r_users")]]),parse_mode="Markdown")
            except:await q.edit_message_text(t.replace('*','').replace('`',''),reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data="r_users")]]))
        elif d=="r_help":
            await q.edit_message_text(
                "🤖 *Reseller Bot Help*\n"
                "━━━━━━━━━━━━━━━━━━━━\n"
                "👥 *My Users*\n"
                "Liste vos users par tunnel avec leur état, expiration et trafic.\n\n"
                "➕ *Create*\n"
                "1) Choisissez le tunnel (ex: SSH, Xray, V2Ray DNS)\n"
                "2) Envoyez le *username*\n"
                "3) Envoyez l'*expiration en jours*\n"
                "4) Mot de passe (ou `auto`)\n"
                "5) Quota GB (0 = illimité)\n"
                "Les détails de connexion vous sont envoyés automatiquement.\n\n"
                "📋 *List*\n"
                "Affiche vos users du tunnel choisi : n°, user, expiration, trafic utilisée / quota.\n\n"
                "🔄 *Renew*\n"
                "Renouvelle un user : envoyez le username puis le nombre de jours à ajouter.\n\n"
                "💾 *Set Quota*\n"
                "Modifie le quota data d'un user : username puis quota en GB (0 = illimité).\n\n"
                "🗑 *Delete*\n"
                "Choisissez le tunnel, puis envoyez les numéros à supprimer (ex: `1,3-5`).\n\n"
                "ℹ️ *Règles*\n"
                "• Limite: `users / max_users` de votre abonnement\n"
                "• Tunnels autorisés: ceux de votre abonnement\n"
                "• Vous ne pouvez gérer que VOS users\n"
                "• Expiration: celle de votre compte revendeur\n\n"
                "Contactez votre administrateur pour toute question.",
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data="r_main")]]),parse_mode="Markdown")
        elif d.startswith("r_confirm_del_"):
            user=d[14:];delete_user(user);await q.edit_message_text(f"✅ `{user}` deleted.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data="r_users")]]),parse_mode="Markdown")

    async def text_handler_reseller(update,ctx):
        rid=ctx.bot_data.get("reseller_id",0);r=reseller_get(rid)
        text=update.message.text.strip()
        if ctx.user_data.get("r_step")=="r_access":
            if r and r["access_code"] and text==r["access_code"]:
                _r_access_grant(rid, update.effective_user.id)
                ctx.user_data.pop("r_step",None)
                await show_main_reseller(update,ctx)
            else:
                await update.message.reply_text("❌ Wrong access code, try again:",parse_mode="Markdown")
            return
        ok,msg=_r_auth(update,r)
        if ok=="code":
            ctx.user_data["r_step"]="r_access";await update.message.reply_text("🔑 Enter access code:",parse_mode="Markdown")
            return
        if ok!="ok":await update.message.reply_text(msg);return
        step=ctx.user_data.get("r_step","");proto=ctx.user_data.get("r_proto","")
        rid2=ctx.user_data.get("r_rid",rid)
        mid=ctx.user_data.get("r_last_msg_id")
        if mid:
            try:await ctx.bot.delete_message(chat_id=update.effective_chat.id,message_id=mid)
            except:pass
        try:await update.message.delete()
        except:pass
        if step=="r_user":
            if not re.match(r'^[a-zA-Z0-9._-]+$',text):await update.message.reply_text("❌ Invalid username.");return
            ctx.user_data["r_username"]=text;ctx.user_data["r_step"]="r_days"
            await update.message.reply_text("✏️ Expiry in *days*:",parse_mode="Markdown")
        elif step=="r_days":
            if not text.isdigit()or int(text)<1:await update.message.reply_text("❌ >=1");return
            ctx.user_data["r_days"]=text
            if proto in("ssh","zivpn","hyst"):ctx.user_data["r_step"]="r_pass";await update.message.reply_text("✏️ Password (or `auto`):",parse_mode="Markdown")
            else:ctx.user_data["r_step"]="r_quota";await update.message.reply_text("✏️ Quota GB (0=unlimited):",parse_mode="Markdown")
        elif step=="r_pass":
            p=text if text!="auto"else gen_pass();ctx.user_data["r_pass"]=p
            if proto in("trojan","ssh"):ctx.user_data["r_step"]="r_quota";await update.message.reply_text("✏️ Quota GB (0=unlimited):",parse_mode="Markdown")
            else:ctx.user_data["r_quota"]="0";await do_create_reseller(update,ctx,rid2)
        elif step=="r_quota":
            if not re.match(r'^[0-9]+\.?[0-9]*$',text):await update.message.reply_text("❌ Invalid number.");return
            ctx.user_data["r_quota"]=text if float(text)>0 else"0";await do_create_reseller(update,ctx,rid2)
        elif step=="r_del_choose":
            users=ctx.user_data.get("r_del_users",[])
            if not users:await update.message.reply_text("❌ No users.");ctx.user_data.clear();return
            nums=set()
            for pt in text.replace(" ","").split(","):
                if not pt:continue
                if"-"in pt:
                    a,b=pt.split("-",1)
                    if a.isdigit()and b.isdigit():nums.update(range(int(a),int(b)+1))
                elif pt.isdigit():nums.add(int(pt))
            td=[users[n-1][0]for n in sorted(nums)if 1<=n<=len(users)]
            if not td:await update.message.reply_text("❌ No valid numbers.");return
            for u in td:
                if _meta_get(u,"reseller")==str(rid):delete_user(u)
            await update.message.reply_text(f"🗑 Deleted `{len(td)}` user(s).",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data="r_users")]]),parse_mode="Markdown");ctx.user_data.clear()
        elif step=="r_renew_user":
            user=text
            if not(USERDIR/user).exists():await update.message.reply_text(f"❌ `{user}` not found.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data="r_users")]]));ctx.user_data.clear();return
            ctx.user_data["r_renew_user"]=user;ctx.user_data["r_step"]="r_renew_days"
            await update.message.reply_text("✏️ Additional *days*:",parse_mode="Markdown")
        elif step=="r_renew_days":
            if not text.isdigit()or int(text)<1:await update.message.reply_text("❌ >=1");return
            user=ctx.user_data.get("r_renew_user","");days=int(text)
            if _meta_get(user,"reseller")!=str(rid):await update.message.reply_text("❌ Not your user.");ctx.user_data.clear();return
            old=_meta_get(user,"exp")
            if old and old!="permanent":
                try:ne=(datetime.strptime(old,"%Y-%m-%d")+timedelta(days=days)).strftime("%Y-%m-%d")
                except:ne=sh(f"date -d '+{days}days' +%Y-%m-%d")
            else:ne=sh(f"date -d '+{days}days' +%Y-%m-%d")
            _meta_set(user,"exp",ne)
            if _meta_get(user,"proto")=="ssh":sh(f"chage -E {ne} {user} 2>/dev/null")
            await update.message.reply_text(f"✅ `{user}` → `{ne}`",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data="r_users")]]),parse_mode="Markdown");ctx.user_data.clear()
        elif step=="r_setquota_user":
            user=text
            if not(USERDIR/user).exists():await update.message.reply_text(f"❌ `{user}` not found.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data="r_users")]]));ctx.user_data.clear();return
            if _meta_get(user,"reseller")!=str(rid):await update.message.reply_text("❌ Not your user.");ctx.user_data.clear();return
            ctx.user_data["r_sq_user"]=user;ctx.user_data["r_step"]="r_setquota_val"
            await update.message.reply_text("✏️ New quota in *GB* (0=unlimited):",parse_mode="Markdown")
        elif step=="r_setquota_val":
            if not re.match(r'^[0-9]+\.?[0-9]*$',text):await update.message.reply_text("❌ Invalid number.");return
            user=ctx.user_data.get("r_sq_user","");q=float(text)
            set_user_quota(user,q)
            await update.message.reply_text(f"✅ `{user}` quota → `{q} GB`",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data="r_users")]]),parse_mode="Markdown");ctx.user_data.clear()

    async def do_create_reseller(update,ctx,rid):
        r=reseller_get(rid)
        if not r:await update.message.reply_text("❌ Reseller disabled.");return
        uc=reseller_user_count(rid)
        if uc>=r["max_users"]:await update.message.reply_text(f"❌ User limit reached ({r['max_users']}).");ctx.user_data.clear();return
        proto=ctx.user_data.get("r_proto","");user=ctx.user_data.get("r_username","")
        days=ctx.user_data.get("r_days","30");pwd=ctx.user_data.get("r_pass","");quota=ctx.user_data.get("r_quota","0")
        pm={"ssh":"ssh","xray":"xray","v2ray":"v2raydns","zivpn":"zivpn","hyst":"hysteria"}
        nm={"ssh":"SSH","xray":"Xray","v2ray":"V2Ray DNS","zivpn":"ZIVPN","hyst":"Hysteria"}
        rp=pm.get(proto,proto)
        # Check tunnel allowed
        tl=json.loads(r["tunnels"])
        if proto not in tl and rp not in tl:await update.message.reply_text(f"❌ Tunnel not allowed.");ctx.user_data.clear();return
        exp=exp_in_days(int(days))
        rc=create_user(rp,user,int(days),pwd,"1",quota)
        if rc!=0:
            msgs={1:"Invalid username",2:"Already exists"}
            await update.message.reply_text(f"❌ {msgs.get(rc,'Error')}.",reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data="r_users")]]))
            ctx.user_data.clear();return
        _meta_set(user,"reseller",str(rid))
        apw=_meta_get(user,"pass")or pwd;uuid=_meta_get(user,"uuid")or""
        bd={"ssh":build_ssh_details,"vless":build_vless_details,"trojan":build_trojan_details,"vmess":build_vmess_details,"zivpn":build_zivpn_details,"hysteria":build_hysteria_details,"v2raydns":build_v2raydns_details}
        fn=bd.get(rp)
        if fn:
            if rp in("vless","vmess","v2raydns"):txt=fn(user,uuid or "?",exp,quota)
            else:txt=fn(user,apw or user,exp,quota)
        else:txt=f"✅ *{nm.get(proto,rp.upper())} created!*\nUser: `{user}`\nExp: `{exp}`"
        await update.message.reply_text(txt,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back",callback_data="r_users")]]),parse_mode="Markdown")
        ctx.user_data.clear()

async def _reseller_post_init(app):
        try:
            await app.bot.set_my_commands([("start","Démarrer le bot"),("help","Comment utiliser le bot")])
        except Exception as e: log.error(f"set_my_commands(reseller) failed: {e}")

def run_reseller_bot(rid):
    r=reseller_get(rid)
    if not r:log.error(f"Reseller #{rid} not found");return
    if not BOT_AVAILABLE:log.error("python-telegram-bot not installed");return
    if not r["bot_token"]:log.error(f"Reseller #{rid} has no token");return
    app=Application.builder().token(r["bot_token"]).post_init(_reseller_post_init).build()
    app.bot_data["reseller_id"]=rid
    app.bot_data["reseller"]=r
    app.add_handler(CommandHandler("start",start_reseller))
    app.add_handler(CommandHandler("help",cmd_help_reseller))
    app.add_handler(CallbackQueryHandler(callback_handler_reseller))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_handler_reseller))
    log.info(f"Reseller Bot #{rid} started");app.run_polling(allowed_updates=Update.ALL_TYPES)
def _sigint_handler(sig, frame):
    sys.stdout.write("\n")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, _sigint_handler)
    logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == "--install":
            self_install()
            clear_screen()
            _verify_license()
            install_dropbear()
            main_menu()
        elif arg == "--watchdog":
            _license_watchdog()
            sys.exit(0)
        elif arg == "--install-all":
            self_install()
            _verify_license()
            setup_config()
            install_all_missing()
            print("Installation complete. Use --menu for interactive menu.")
            sys.exit(0)
        elif arg == "--menu":
            self_install()
            _verify_license()
            main_menu()
        elif arg == "--auto-uninstall":
            _auto_uninstall_all()
            sys.exit(0)
        elif arg == "--bot":
            run_bot()
        elif arg == "--reseller-bot":
            if len(sys.argv)>2:run_reseller_bot(int(sys.argv[2]))
            else:log.error("Usage: --reseller-bot <id>")
        elif arg == "--reseller-cleanup":
            results = reseller_cleanup_expired()
            for r in results:
                log.info(f"Cleaned reseller #{r['id']} {r['name']}: {r['users_deleted']} users deleted")
            sys.exit(0)
        elif arg == "--quota-enforce":
            b, r = quota_enforce()
            log.info(f"quota-enforce: {b} blocked, {r} restored")
            sys.exit(0)
        elif arg == "--ssh-quota-sync":
            _install_ssh_banner_shell()
            _gen_user_banners()
            _ssh_quota_sync()
            sys.exit(0)
        elif arg == "--ssh-quota-apply":
            _install_ssh_banner_shell()
            _gen_user_banners()
            _ssh_quota_apply()
            sys.exit(0)
        elif arg == "--ssh-tracker":
            _ssh_tracker_loop()
            sys.exit(0)
        elif arg == "--ssh-banner":
            if len(sys.argv)>2: _ssh_banner(sys.argv[2])
            sys.exit(0)
        elif arg == "--render":
            renders = {"main": scr_main, "manage": scr_manage_users, "optimize": scr_optimize,
                       "installer": scr_protocol_installer, "update": scr_update_remove}
            renders.get(sys.argv[2], scr_main)()
            print(); sys.exit(0)
        else:
            # Unknown arg → ignore, show menu below
            pass
    else:
        # No args → interactive menu
        self_install()
        _verify_license()
        main_menu()
