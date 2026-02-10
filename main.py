from flask import Flask, request, jsonify, redirect, url_for, session, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
import json
import sqlite3
import secrets
import hashlib
import datetime
import os
import html as html_module
from functools import wraps
from werkzeug.utils import secure_filename
from collections import OrderedDict
import os
import mysql.connector
from flask import Flask, request, render_template, redirect
try:
    from mcstatus import JavaServer

    MCSTATUS_AVAILABLE = True
except ImportError:
    MCSTATUS_AVAILABLE = False

try:
    from mcrcon import MCRcon

    MCRCON_AVAILABLE = True
except ImportError:
    MCRCON_AVAILABLE = False

app = Flask(__name__)
app.secret_key = secrets.token_hex(64)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
app.config['ALLOWED_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'gif'}
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

socketio = SocketIO(app, cors_allowed_origins="*", async_mode='threading')

def get_real_online(ip_address):
    if not MCSTATUS_AVAILABLE:
        return None
    try:
        if ':' in ip_address:
            server = JavaServer.lookup(ip_address)
        else:
            server = JavaServer.lookup(ip_address)
        status = server.status()
        return status.players.online
    except Exception:
        return 0


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def get_db():
    conn = sqlite3.connect('elitemc.db')
    conn.row_factory = sqlite3.Row
    return conn


def sanitize(text: str) -> str:
    return html_module.escape(str(text))


def execute_purchase(minecraft_nick: str, pkg, server_mode=None):
    """
    server_mode: 'anarchy' yoki 'smp' - faqat Unban/Unmute uchun
    """
    if not MCRCON_AVAILABLE:
        return False, "RCON moduli yo'q"
    try:
        conn = get_db()
        settings = {r['key']: r['value'] for r in conn.execute('SELECT key, value FROM settings').fetchall()}
        conn.close()

        cat = pkg['category']

        # Agar services (Unban/Unmute) va server_mode berilgan bo'lsa
        if cat == 'services' and server_mode:
            prefix = server_mode  # 'anarchy' yoki 'smp'
        elif cat == 'anarchy':
            prefix = "anarchy"
        elif cat == 'smp':
            prefix = "smp"
        else:
            prefix = "anarchy"

        host = settings.get(f'{prefix}_rcon_host')
        port = settings.get(f'{prefix}_rcon_port')
        pwd = settings.get(f'{prefix}_rcon_password')

        if not host or not pwd:
            return False, f"{prefix.upper()} RCON sozlanmagan"

        cmd = ""
        if cat in ['anarchy', 'smp']:
            cmd = f"lp user {minecraft_nick} parent set {pkg['name']}"
        elif cat == 'keys' and 'DT' in pkg['name']:
            cmd = f"crates key give {minecraft_nick} economy 1"
        elif cat == 'services':
            if 'Unban' in pkg['name']:
                cmd = f"pardon {minecraft_nick}"
            elif 'Unmute' in pkg['name']:
                cmd = f"unmute {minecraft_nick}"
        elif cat == 'token':
            cmd = f"playerpoints give {minecraft_nick} {int(pkg['name'].split()[0])}"

        with MCRcon(host, pwd, port=int(port)) as mcr:
            resp = mcr.command(cmd)
            return True, resp
    except Exception as e:
        return False, str(e)


def init_db():
    conn = get_db()
    c = conn.cursor()

    # 1. Jadvallarni yaratish (TARTIB BILAN)
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     username
                     TEXT
                     UNIQUE,
                     email
                     TEXT
                     UNIQUE,
                     password
                     TEXT,
                     balance
                     REAL
                     DEFAULT
                     0,
                     tokens
                     INTEGER
                     DEFAULT
                     0,
                     is_admin
                     BOOLEAN
                     DEFAULT
                     0,
                     minecraft_nick
                     TEXT,
                     created_at
                     TIMESTAMP
                     DEFAULT
                     CURRENT_TIMESTAMP
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS packages
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     category
                     TEXT,
                     name
                     TEXT,
                     description
                     TEXT,
                     price
                     REAL,
                     duration
                     TEXT,
                     features
                     TEXT,
                     color
                     TEXT
                     DEFAULT
                     '#3b82f6',
                     is_active
                     BOOLEAN
                     DEFAULT
                     1
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     key
                     TEXT
                     UNIQUE,
                     value
                     TEXT
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS news
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     title
                     TEXT,
                     content
                     TEXT,
                     image
                     TEXT,
                     created_at
                     TIMESTAMP
                     DEFAULT
                     CURRENT_TIMESTAMP
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS purchases
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     user_id
                     INTEGER,
                     package_id
                     INTEGER,
                     amount
                     REAL,
                     package_name
                     TEXT,
                     minecraft_nick
                     TEXT,
                     status
                     TEXT
                     DEFAULT
                     'completed',
                     created_at
                     TIMESTAMP
                     DEFAULT
                     CURRENT_TIMESTAMP
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS balance_deposits
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     user_id
                     INTEGER,
                     amount
                     REAL,
                     card_number
                     TEXT,
                     transaction_id
                     TEXT,
                     screenshot
                     TEXT,
                     status
                     TEXT
                     DEFAULT
                     'pending',
                     admin_comment
                     TEXT,
                     created_at
                     TIMESTAMP
                     DEFAULT
                     CURRENT_TIMESTAMP
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS support_tickets
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     user_id
                     INTEGER,
                     subject
                     TEXT,
                     status
                     TEXT
                     DEFAULT
                     'open',
                     created_at
                     TIMESTAMP
                     DEFAULT
                     CURRENT_TIMESTAMP
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS support_messages
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     ticket_id
                     INTEGER,
                     user_id
                     INTEGER,
                     message
                     TEXT,
                     is_admin_reply
                     BOOLEAN
                     DEFAULT
                     0,
                     created_at
                     TIMESTAMP
                     DEFAULT
                     CURRENT_TIMESTAMP
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS player_stats
    (
        id
        INTEGER
        PRIMARY
        KEY
        AUTOINCREMENT,
        minecraft_nick
        TEXT,
        server_type
        TEXT,
        kills
        INTEGER
        DEFAULT
        0,
        deaths
        INTEGER
        DEFAULT
        0,
        time_played
        TEXT
        DEFAULT
        '0h',
        level
        INTEGER
        DEFAULT
        1,
        money
        REAL
        DEFAULT
        0,
        last_updated
        TIMESTAMP
        DEFAULT
        CURRENT_TIMESTAMP,
        UNIQUE
                 (
        minecraft_nick,
        server_type
                 ))''')

    # 2. Eskilarini tozalash (Xatolarni oldini olish uchun)
    c.execute('DELETE FROM packages')

    # 3. KEYS BO'LIMI (Do'konning Keys tabida ko'rinadi)
    c.execute(
        "INSERT INTO packages (category, name, description, price, duration, features, color) VALUES ('keys', 'DT Case', '1x DT Case Key', 10000, '1 dona', 'Noyob buyumlar kaliti', '#f43f5e')")

    # 4. XIZMATLAR BO'LIMI (Do'konning Xizmatlar tabida ko'rinadi)
    c.execute(
        "INSERT INTO packages (category, name, description, price, duration, features, color) VALUES ('services', 'Unmute', 'Chatdan unmute', 5000, 'Bir martalik', 'Chatda yozish imkoni', '#10b981')")
    c.execute(
        "INSERT INTO packages (category, name, description, price, duration, features, color) VALUES ('services', 'Unban', 'Serverdan unban', 15000, 'Bir martalik', 'Serverga qayta kirish', '#ef4444')")

    # 5. ANARXIYA RANKLARI (30, 90, UMRBOT variantlari bilan)
    anarchy_ranks = [
        ('VIP', 'Anarxiya ranki', 2000, 4000, 6000, '/wb, /ec, 7 slot', '#60a5fa'),
        ('VIP+', 'Anarxiya ranki', 5000, 9000, 13000, '/anvil, /near, Kit VIP+', '#3b82f6'),
        ('LEGEND', 'Anarxiya ranki', 8000, 15000, 21000, '/time set, Kit Legend', '#8b5cf6'),
        ('DONATOR', 'Anarxiya ranki', 11000, 20000, 28000, '/jump, Kit Donator', '#d946ef'),
        ('GOLD', 'Anarxiya ranki', 14000, 24000, 35000, '/feed, Kit Gold', '#eab308'),
        ('NITRO', 'Anarxiya ranki', 17000, 30000, 43000, '/speed, Kit Nitro', '#f97316'),
        ('COMET', 'Anarxiya ranki', 22000, 39000, 56000, '/bc, Kit Comet', '#06b6d4'),
        ('HERO', 'Anarxiya ranki', 32000, 55000, 79000, '/prefix, Kit Hero', '#6366f1'),
        ('ULTRA', 'Anarxiya ranki', 40000, 70000, 100000, '/ban, Kit Ultra', '#ef4444'),
        ('PRIME', 'Anarxiya ranki', 80000, 140000, 200000, '/fly, Kit Prime', '#10b981'),
    ]
    for name, desc, p30, p90, pUmr, feat, col in anarchy_ranks:
        c.execute(
            'INSERT INTO packages (category, name, description, price, duration, features, color) VALUES (?,?,?,?,?,?,?)',
            ('anarchy', name, desc, p30, '30', feat, col))
        c.execute(
            'INSERT INTO packages (category, name, description, price, duration, features, color) VALUES (?,?,?,?,?,?,?)',
            ('anarchy', name, desc, p90, '90', feat, col))
        c.execute(
            'INSERT INTO packages (category, name, description, price, duration, features, color) VALUES (?,?,?,?,?,?,?)',
            ('anarchy', name, desc, pUmr, 'UMRBOT', feat, col))

    # 6. SMP+ RANKLARI
    c.execute(
        'INSERT INTO packages (category, name, description, price, duration, features, color) VALUES (?,?,?,?,?,?,?)',
        ('smp', 'SMP+', 'SMP Server Rank', 20000, '30', 'SMP Maxsus imkoniyatlar', '#00ff88'))
    c.execute(
        'INSERT INTO packages (category, name, description, price, duration, features, color) VALUES (?,?,?,?,?,?,?)',
        ('smp', 'SMP+', 'SMP Server Rank', 35000, '90', 'SMP Maxsus imkoniyatlar', '#00ff88'))
    c.execute(
        'INSERT INTO packages (category, name, description, price, duration, features, color) VALUES (?,?,?,?,?,?,?)',
        ('smp', 'SMP+', 'SMP Server Rank', 50000, 'UMRBOT', 'SMP Maxsus imkoniyatlar', '#00ff88'))

    # 7. TOKEN PAKETLARI (Kalkulyatordan tashqari tayyor paketlar)
    token_packages = [('1000 Token', 1200, '1000 token'), ('5000 Token', 6000, '5000 token'),
                      ('10000 Token', 12000, '10000 token')]
    for name, price, feat in token_packages:
        c.execute(
            'INSERT INTO packages (category, name, description, price, duration, features, color) VALUES (?,?,?,?,?,?,?)',
            ('token', name, 'Server valyutasi', price, 'Bir martalik', feat, '#fbbf24'))

    # 8. SOZLAMALAR (SETTINGS)
    defaults = [
        ('admin_card_number', 'EliteMc ⚡️5614 6819 0152 9887'),
        ('admin_card_name', 'T. SH'),
        ('site_name', 'EliteMC'),
        ('server_ip', 'mc.elitemc.uz'),
        ('rcon_host', '185.130.212.39'),
        ('rcon_port', '25496'),
        ('rcon_password', '@shoxauz054uzcvre@$%'),
        ('music_url', 'https://www.youtube.com/embed/atgjKEgSqSU'),
        ('music_enabled', '1')
    ]
    for k, v in defaults:
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (k, v))

    # 9. ADMIN AKKAUNTI
    admin_pw = hashlib.sha256('ssmertnix_legend'.encode()).hexdigest()
    c.execute(
        'INSERT OR IGNORE INTO users (username, email, password, is_admin, minecraft_nick) VALUES (?, ?, ?, ?, ?)',
        ('admin', 'admin@elitemc.uz', admin_pw, 1, 'Admin'))

    conn.commit()
    conn.close()


def login_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*a, **kw)

    return wrapper


def admin_required(f):
    @wraps(f)
    def wrapper(*a, **kw):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        conn = get_db()
        user = conn.execute('SELECT is_admin FROM users WHERE id=?', (session['user_id'],)).fetchone()
        conn.close()
        if not user or not user['is_admin']:
            return redirect(url_for('index'))
        return f(*a, **kw)

    return wrapper


# ═══════════════════════════════════════════════
# RENDER PAGE — full shell with CSS + music + status
# ═══════════════════════════════════════════════

def render_page(body_content: str, **kwargs) -> str:
    conn = get_db()
    settings = {r['key']: r['value'] for r in conn.execute('SELECT key,value FROM settings').fetchall()}
    conn.close()

    if kwargs.get('logged_in'):
        nav_user = """
                <li><a href="/rules"><i class="fas fa-book"></i> <span>Qoidalar</span></a></li>
                <li><a href="/support"><i class="fas fa-headset"></i> <span>Support</span></a></li>
                <li><a href="/balance"><i class="fas fa-wallet"></i> <span>Balans</span></a></li>
                <li><a href="/profile"><i class="fas fa-user-circle"></i> <span>Profil</span></a></li>
                """ + ('<li><a href="/admin"><i class="fas fa-bolt"></i> <span>Admin</span></a></li>' if kwargs.get(
            'is_admin') else '') + """
                <li><a href="/logout" class="nav-logout"><i class="fas fa-sign-out-alt"></i> <span>Chiqish</span></a></li>
            """
    else:
        nav_user = """
                <li><a href="/rules"><i class="fas fa-book"></i> <span>Qoidalar</span></a></li>
                <li><a href="/login" class="btn-nav btn-nav-outline"><i class="fas fa-sign-in-alt"></i> <span>Kirish</span></a></li>
                <li><a href="/register" class="btn-nav btn-nav-primary"><i class="fas fa-user-plus"></i> <span>Ro'yxat</span></a></li>
            """

    music_url = settings.get('music_url', '')
    music_enabled = settings.get('music_enabled', '1')
    has_music = (music_enabled == '1' and music_url != '')
    music_iframe_html = f'<iframe class="music-iframe" id="musicIframe" src="{music_url}" allow="autoplay; encrypted-media"></iframe>' if has_music else ''
    music_playing_class = 'playing' if has_music else ''
    music_init_js = 'true' if has_music else 'false'
    server_ip = settings.get('server_ip', 'mc.elitemc.uz')

    return f'''<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>EliteMC — Uzbekistandagi N1 Minecraft SERVER</title>
<link rel="icon" type="image/png" href="/static/favicon.png"/>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Rajdhani:wght@300;400;500;600;700&family=Space+Grotesk:wght@300;400;500;600;700&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/>
<style>
:root {{
    --primary:#00ff88; --primary-dim:rgba(0,255,136,.35); --primary-glow:rgba(0,255,136,.55);
    --secondary:#0099ff; --accent:#ff0099; --accent2:#a855f7;
    --dark:#060a16; --glass:rgba(20,26,48,.55);
    --text:#dce4f0; --text-dim:#6b7a9a; --text-bright:#fff;
    --success:#00ff88; --warning:#ffaa00; --danger:#ff3366;
    --radius:16px; --radius-sm:10px; --radius-lg:24px;
    --shadow:0 8px 40px rgba(0,0,0,.5);
    --glow-green:0 0 30px rgba(0,255,136,.3);
    --transition:.3s cubic-bezier(.4,0,.2,1);
}}
*{{margin:0;padding:0;box-sizing:border-box;}}
html{{scroll-behavior:smooth;}}
body{{font-family:'Rajdhani',sans-serif;background:var(--dark);color:var(--text);line-height:1.6;overflow-x:hidden;min-height:100vh;}}

main {{
    opacity: 0;
    transform: translateY(20px);
    animation: pageLoad 0.5s cubic-bezier(0.4, 0, 0.2, 1) forwards;
    animation-delay: 0.1s;
}}

@keyframes pageLoad {{
    to {{
        opacity: 1;
        transform: translateY(0);
    }}
}}

body.page-transitioning main {{
    animation: pageOut 0.35s cubic-bezier(0.4, 0, 0.6, 1) forwards;
}}

@keyframes pageOut {{
    to {{
        opacity: 0;
        transform: translateY(-10px);
    }}
}}

/* ─── ESKI KODLAR DAVOMI ─── */
body::before{{content:'';position:fixed;inset:0;z-index:0;pointer-events:none;background-image:linear-gradient(rgba(0,255,136,.025) 1px,transparent 1px),linear-gradient(90deg,rgba(0,255,136,.025) 1px,transparent 1px);background-size:60px 60px;animation:gridDrift 25s linear infinite;}}
@keyframes gridDrift{{to{{background-position:60px 60px;}}}}
.orb{{position:fixed;border-radius:50%;pointer-events:none;z-index:0;filter:blur(90px);opacity:.18;animation:orbFloat 18s ease-in-out infinite alternate;}}
.orb-1{{width:500px;height:500px;background:#00ff88;top:-100px;left:-150px;}}
.orb-2{{width:400px;height:400px;background:#0099ff;bottom:-80px;right:-120px;animation-delay:4s;}}
.orb-3{{width:300px;height:300px;background:#a855f7;top:50%;left:50%;transform:translate(-50%,-50%);animation-delay:8s;}}
@keyframes orbFloat{{0%{{transform:scale(1) translate(0,0);}}100%{{transform:scale(1.3) translate(30px,-40px);}}}}
main{{position:relative;z-index:2;padding-top:80px;min-height:100vh;opacity:0;}}
.container{{max-width:1320px;margin:0 auto;padding:0 1.5rem;}}

main {{
    position:relative;
    z-index:2;
    padding-top:80px;
    min-height:100vh;
    opacity: 0;
    transform: translateY(30px) scale(0.98);
    animation: pageEnterExtra 0.6s cubic-bezier(0.4, 0, 0.2, 1) forwards;
    animation-delay: 0.3s;
}}

@keyframes pageEnterExtra {{
    to {{ opacity: 1; transform: translateY(0) scale(1); }}
}}

body.page-exit main {{
    animation: pageExitExtra 0.4s ease forwards;
}}

@keyframes pageExitExtra {{
    to {{ opacity: 0; transform: translateY(-15px) scale(0.96); filter: blur(3px); }}
}}

/* NAV */
nav{{position:fixed;top:0;left:0;width:100%;z-index:9999;background:rgba(6,10,22,.8);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);border-bottom:1px solid rgba(0,255,136,.12);box-shadow:0 4px 32px rgba(0,0,0,.6);}}
nav .container{{display:flex;justify-content:space-between;align-items:center;padding:1rem 1.5rem;}}
.logo{{font-family:'Orbitron',sans-serif;font-size:1.7rem;font-weight:900;background:linear-gradient(135deg,var(--primary),var(--secondary));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;letter-spacing:3px;text-decoration:none;display:flex;align-items:center;gap:.5rem;}}
.logo-icon{{font-size:1.4rem;-webkit-text-fill-color:var(--primary);animation:logoSwing 3s ease-in-out infinite;}}
@keyframes logoSwing{{0%,100%{{transform:rotate(-5deg);}}50%{{transform:rotate(5deg);}}}}
.nav-links{{display:flex;gap:.8rem;align-items:center;list-style:none;}}
.nav-links a{{color:var(--text-dim);text-decoration:none;font-weight:600;font-size:.95rem;padding:.5rem 1rem;border-radius:var(--radius-sm);transition:var(--transition);display:flex;align-items:center;gap:.4rem;}}
.nav-links a:hover{{color:var(--primary);background:rgba(0,255,136,.08);}}
.nav-links a i{{font-size:.85rem;}}
.nav-logout{{color:var(--danger)!important;}}
.nav-logout:hover{{background:rgba(255,51,102,.1)!important;color:var(--danger)!important;}}
.btn-nav{{font-weight:700;font-size:.9rem;padding:.45rem 1.1rem;border-radius:var(--radius-sm);text-decoration:none;display:flex;align-items:center;gap:.35rem;transition:var(--transition);}}
.btn-nav-outline{{border:1.5px solid var(--primary);color:var(--primary);}}
.btn-nav-outline:hover{{background:var(--primary);color:var(--dark);box-shadow:var(--glow-green);}}
.btn-nav-primary{{background:linear-gradient(135deg,var(--primary),var(--secondary));color:var(--dark);box-shadow:0 4px 18px var(--primary-dim);}}
.btn-nav-primary:hover{{transform:translateY(-2px);box-shadow:0 6px 28px var(--primary-dim);}}



.hero{{text-align:center;padding:10rem 0 4rem;position:relative;overflow:hidden;}}
.hero-glow{{position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);width:800px;height:800px;background:radial-gradient(circle,rgba(0,255,136,.12) 0%,transparent 70%);animation:heroBreath 5s ease-in-out infinite;pointer-events:none;}}
@keyframes heroBreath{{0%,100%{{transform:translate(-50%,-50%) scale(1);opacity:.5;}}50%{{transform:translate(-50%,-50%) scale(1.15);opacity:.8;}}}}
.glitch-text{{font-family:'Orbitron',sans-serif;font-size:clamp(3rem,8vw,5rem);text-shadow:0 0 20px var(--primary);margin-bottom:.5rem;color:#fff;position:relative;z-index:1;animation:fadeDown .8s ease-out both;}}
@keyframes fadeDown{{from{{opacity:0;transform:translateY(-30px);}}to{{opacity:1;transform:translateY(0);}}}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(20px);}}to{{opacity:1;transform:translateY(0);}}}}


/* (Server status, Card, Table, Form, Support, Toast, Footer stillari) */
.server-ip-box{{display:inline-flex;align-items:center;gap:1rem;background:linear-gradient(135deg,rgba(0,255,136,.1),rgba(0,153,255,.1));border:1.5px solid rgba(0,255,136,.4);border-radius:var(--radius);padding:1rem 2rem;margin:1.2rem 0;cursor:pointer;position:relative;z-index:1;transition:var(--transition);box-shadow:0 6px 30px rgba(0,255,136,.15);animation:fadeUp .8s .3s ease-out both;}}
.server-ip-box:hover{{transform:scale(1.04);box-shadow:var(--glow-green);border-color:var(--primary);}}
.server-ip-box .ip-text{{font-family:'Space Grotesk',monospace;font-size:1.5rem;font-weight:700;color:var(--primary);letter-spacing:1px;}}
.server-ip-box .ip-icon{{color:var(--text-dim);font-size:1rem;transition:var(--transition);}}
.server-ip-box:hover .ip-icon{{color:var(--primary);transform:scale(1.3);}}
.server-status-bar{{position:relative;z-index:1;display:flex;justify-content:center;gap:1.2rem;flex-wrap:wrap;margin:2rem auto 0;max-width:960px;}}
.status-card{{background:rgba(14,18,34,.75);border:1px solid rgba(0,255,136,.16);border-radius:14px;padding:.95rem 1.4rem;display:flex;align-items:center;gap:.9rem;backdrop-filter:blur(12px);position:relative;overflow:hidden;transition:var(--transition);flex:1 1 190px;max-width:260px;animation:cardPop .55s cubic-bezier(.34,1.56,.64,1) both;}}
.status-card:nth-child(1){{animation-delay:.08s;}}
.status-card:nth-child(2){{animation-delay:.2s;}}
.status-card:nth-child(3){{animation-delay:.32s;}}
.status-card:nth-child(4){{animation-delay:.44s;}}
@keyframes cardPop{{from{{opacity:0;transform:translateY(22px) scale(.93);}}to{{opacity:1;transform:translateY(0) scale(1);}}}}
.status-card::before{{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(0,255,136,.05),transparent 60%);opacity:0;transition:var(--transition);}}
.status-card:hover{{border-color:var(--primary);box-shadow:var(--glow-green);transform:translateY(-3px);}}
.status-card:hover::before{{opacity:1;}}
.status-card.pulse-green .status-icon{{box-shadow:0 0 0 0 rgba(0,255,136,.5);animation:statusPulse 2s ease-in-out infinite;}}
@keyframes statusPulse{{0%{{box-shadow:0 0 0 0 rgba(0,255,136,.6);}}70%{{box-shadow:0 0 0 10px rgba(0,255,136,0);}}100%{{box-shadow:0 0 0 0 rgba(0,255,136,0);}}}}
.status-icon{{width:40px;height:40px;border-radius:11px;display:flex;align-items:center;justify-content:center;font-size:1.1rem;flex-shrink:0;position:relative;z-index:1;}}
.status-icon.green{{background:rgba(0,255,136,.12);color:var(--primary);}}
.status-icon.blue{{background:rgba(0,153,255,.12);color:var(--secondary);}}
.status-icon.purple{{background:rgba(168,85,247,.12);color:#c084fc;}}
.status-icon.orange{{background:rgba(249,115,22,.12);color:#fb923c;}}
.status-info{{position:relative;z-index:1;}}
.status-label{{display:block;font-size:.68rem;color:var(--text-dim);text-transform:uppercase;letter-spacing:1.2px;font-weight:600;margin-bottom:.12rem;}}
.status-value{{display:block;font-family:'Orbitron',sans-serif;font-size:1rem;font-weight:700;color:#fff;}}
.status-value .dim{{color:var(--text-dim);font-size:.78rem;font-weight:400;font-family:'Rajdhani',sans-serif;}}
.live-dot{{display:inline-block;width:7px;height:7px;border-radius:50%;background:var(--primary);margin-right:4px;vertical-align:middle;animation:liveBlink 1.4s ease-in-out infinite;}}
@keyframes liveBlink{{0%,100%{{opacity:1;}}50%{{opacity:.2;}}}}
.rank-chips{{display:flex;justify-content:center;gap:.45rem;flex-wrap:wrap;margin-top:1.6rem;position:relative;z-index:1;}}
.rank-chip{{font-family:'Orbitron',sans-serif;font-size:.6rem;font-weight:700;padding:.28rem .7rem;border-radius:20px;letter-spacing:.8px;text-transform:uppercase;border:1px solid;animation:chipSlide .5s cubic-bezier(.34,1.56,.64,1) both;transition:var(--transition);cursor:default;}}
.rank-chip:hover{{transform:translateY(-2px) scale(1.1);}}
@keyframes chipSlide{{from{{opacity:0;transform:translateX(-16px) scale(.82);}}to{{opacity:1;transform:translateX(0) scale(1);}}}}
.btn{{display:inline-flex;align-items:center;justify-content:center;gap:.5rem;padding:.9rem 2rem;border-radius:var(--radius-sm);font-weight:700;font-size:1rem;text-decoration:none;border:none;cursor:pointer;transition:var(--transition);position:relative;overflow:hidden;font-family:'Rajdhani',sans-serif;}}
.btn::after{{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(255,255,255,.15),transparent);opacity:0;transition:var(--transition);}}
.btn:hover::after{{opacity:1;}}
.btn-primary{{background:linear-gradient(135deg,var(--primary),var(--secondary));color:var(--dark);box-shadow:0 4px 20px var(--primary-dim);}}
.btn-primary:hover{{transform:translateY(-2px);box-shadow:0 8px 32px var(--primary-dim);}}
.btn-secondary{{background:linear-gradient(135deg,var(--accent2),var(--accent));color:#fff;box-shadow:0 4px 20px rgba(168,85,247,.3);}}
.btn-secondary:hover{{transform:translateY(-2px);box-shadow:0 8px 32px rgba(168,85,247,.4);}}
.btn-outline{{background:transparent;border:1.5px solid var(--primary);color:var(--primary);}}
.btn-outline:hover{{background:var(--primary);color:var(--dark);box-shadow:var(--glow-green);}}
.btn-danger{{background:linear-gradient(135deg,#ff3366,#e11d48);color:#fff;box-shadow:0 4px 18px rgba(255,51,102,.35);}}
.btn-danger:hover{{transform:translateY(-2px);box-shadow:0 8px 28px rgba(255,51,102,.45);}}
.btn-full{{width:100%;}}
.btn-sm{{padding:.5rem 1rem;font-size:.85rem;}}
.card{{background:var(--glass);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);border:1px solid rgba(0,255,136,.13);border-radius:var(--radius-lg);padding:2rem;box-shadow:var(--shadow);margin-bottom:1.5rem;position:relative;overflow:hidden;}}
.card::before{{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--primary),var(--secondary),transparent);opacity:.5;}}
.card-header{{padding-bottom:1.2rem;margin-bottom:1.5rem;border-bottom:1px solid rgba(255,255,255,.07);display:flex;align-items:center;gap:.8rem;}}
.card-header h2{{font-family:'Orbitron',sans-serif;font-size:1.35rem;color:var(--primary);font-weight:700;}}
.card-header i{{color:var(--primary);font-size:1.2rem;}}
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1.2rem;margin:3rem 0;}}
.stat-card{{background:var(--glass);backdrop-filter:blur(14px);border:1px solid rgba(0,255,136,.12);border-radius:var(--radius);padding:2rem 1.5rem;text-align:center;transition:var(--transition);position:relative;overflow:hidden;}}
.stat-card::before{{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(0,255,136,.04),rgba(0,153,255,.04));opacity:0;transition:var(--transition);}}
.stat-card:hover{{transform:translateY(-6px);border-color:var(--primary);box-shadow:var(--glow-green);}}
.stat-card:hover::before{{opacity:1;}}
.stat-card i{{font-size:2rem;color:var(--primary);margin-bottom:.6rem;display:block;position:relative;z-index:1;}}
.stat-card h3{{font-family:'Orbitron',sans-serif;font-size:1.8rem;color:var(--primary);margin:.4rem 0;position:relative;z-index:1;}}
.stat-card p{{color:var(--text-dim);font-size:.9rem;font-weight:500;position:relative;z-index:1;}}
.section-title{{text-align:center;margin:3.5rem 0 2rem;}}
.section-title h2{{font-family:'Orbitron',sans-serif;font-size:clamp(1.8rem,4vw,2.8rem);font-weight:900;background:linear-gradient(135deg,var(--primary),var(--secondary));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;position:relative;display:inline-block;}}
.section-title h2::after{{content:'';position:absolute;bottom:-10px;left:50%;transform:translateX(-50%);width:70px;height:3px;background:linear-gradient(90deg,transparent,var(--primary),transparent);border-radius:2px;}}
.packages{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:1.5rem;margin:2rem 0 3rem;}}
.package-card{{background:var(--glass);backdrop-filter:blur(14px);border:1.5px solid rgba(255,255,255,.08);border-radius:var(--radius-lg);padding:2rem 1.5rem;transition:var(--transition);position:relative;overflow:hidden;display:flex;flex-direction:column;}}
.package-card::before{{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,transparent,var(--pkg-color,var(--primary)),transparent);}}
.package-card:hover{{transform:translateY(-8px);border-color:var(--pkg-color,var(--primary));box-shadow:0 12px 40px rgba(0,0,0,.4);}}
.pkg-badge{{position:absolute;top:12px;right:12px;background:linear-gradient(135deg,var(--pkg-color,var(--primary)),rgba(0,0,0,.6));color:#fff;font-size:.7rem;font-weight:700;padding:.25rem .6rem;border-radius:20px;text-transform:uppercase;letter-spacing:1px;}}
.package-name{{font-family:'Orbitron',sans-serif;font-size:1.5rem;font-weight:900;text-align:center;margin-bottom:.3rem;position:relative;z-index:1;}}
.package-desc{{text-align:center;color:var(--text-dim);font-size:.9rem;margin-bottom:1rem;position:relative;z-index:1;}}
.package-price{{font-family:'Orbitron',sans-serif;font-size:2rem;font-weight:900;text-align:center;color:var(--primary);margin:1rem 0;position:relative;z-index:1;}}
.package-price span{{font-size:.85rem;color:var(--text-dim);font-weight:400;font-family:'Rajdhani',sans-serif;}}
.package-features{{list-style:none;margin:1rem 0;flex-grow:1;position:relative;z-index:1;}}
.package-features li{{padding:.45rem 0;border-bottom:1px solid rgba(255,255,255,.05);display:flex;align-items:center;gap:.6rem;font-size:.9rem;color:var(--text-dim);transition:var(--transition);}}
.package-features li:hover{{color:var(--text);padding-left:6px;}}
.package-features li i{{color:var(--primary);font-size:.8rem;flex-shrink:0;}}
.table-wrap{{overflow-x:auto;border-radius:var(--radius);}}
table{{width:100%;border-collapse:collapse;margin:.5rem 0;}}
table thead{{background:linear-gradient(135deg,rgba(0,255,136,.15),rgba(0,153,255,.15));}}
table thead th{{padding:1rem 1.2rem;text-align:left;color:var(--primary);font-weight:700;font-size:.85rem;text-transform:uppercase;letter-spacing:.8px;font-family:'Space Grotesk',sans-serif;border-bottom:1px solid rgba(0,255,136,.2);white-space:nowrap;}}
table tbody tr{{transition:var(--transition);border-bottom:1px solid rgba(255,255,255,.04);}}
table tbody tr:hover{{background:rgba(0,255,136,.04);}}
table tbody td{{padding:.9rem 1.2rem;font-size:.92rem;color:var(--text);}}
.badge{{display:inline-block;padding:.3rem .85rem;border-radius:20px;font-size:.78rem;font-weight:700;text-transform:uppercase;letter-spacing:.8px;}}
.badge-pending{{background:rgba(255,170,0,.12);color:var(--warning);border:1px solid rgba(255,170,0,.3);}}
.badge-approved,.badge-success{{background:rgba(0,255,136,.12);color:var(--success);border:1px solid rgba(0,255,136,.3);}}
.badge-rejected,.badge-danger{{background:rgba(255,51,102,.12);color:var(--danger);border:1px solid rgba(255,51,102,.3);}}
.badge-open{{background:rgba(0,153,255,.12);color:var(--secondary);border:1px solid rgba(0,153,255,.3);}}
.badge-answered{{background:rgba(168,85,247,.12);color:#c084fc;border:1px solid rgba(168,85,247,.3);}}
.badge-closed{{background:rgba(107,114,154,.12);color:var(--text-dim);border:1px solid rgba(107,114,154,.3);}}
.balance-hero{{background:linear-gradient(135deg,rgba(168,85,247,.25),rgba(255,0,153,.2));border:1px solid rgba(168,85,247,.3);border-radius:var(--radius-lg);padding:2.5rem;text-align:center;margin:1.5rem 0;position:relative;overflow:hidden;}}
.balance-hero::before{{content:'';position:absolute;top:-60%;right:-30%;width:80%;height:200%;background:radial-gradient(circle,rgba(255,255,255,.06) 0%,transparent 70%);animation:shimmerMove 4s ease-in-out infinite alternate;}}
@keyframes shimmerMove{{0%{{transform:translate(0,0);}}100%{{transform:translate(-40px,20px);}}}}
.balance-hero h3{{color:var(--text-dim);font-size:1rem;margin-bottom:.5rem;position:relative;z-index:1;text-transform:uppercase;letter-spacing:1px;}}
.balance-amount{{font-family:'Orbitron',sans-serif;font-size:2.8rem;font-weight:900;color:#fff;position:relative;z-index:1;}}
.balance-amount span{{font-size:1rem;color:var(--text-dim);font-weight:400;font-family:'Rajdhani',sans-serif;}}
.alert{{padding:1rem 1.2rem;border-radius:var(--radius-sm);margin:1rem 0;display:flex;align-items:flex-start;gap:.8rem;}}
.alert i{{flex-shrink:0;font-size:1.1rem;margin-top:.15rem;}}
.alert-warning{{background:rgba(255,170,0,.08);border:1px solid rgba(255,170,0,.25);color:var(--warning);}}
.alert-info{{background:rgba(0,153,255,.08);border:1px solid rgba(0,153,255,.25);color:var(--secondary);}}
.tabs{{display:flex;gap:.6rem;margin:1.5rem 0;flex-wrap:wrap;}}
.tab{{padding:.6rem 1.2rem;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);border-radius:var(--radius-sm);color:var(--text-dim);text-decoration:none;font-weight:600;font-size:.88rem;transition:var(--transition);display:flex;align-items:center;gap:.4rem;}}
.tab:hover{{background:rgba(0,255,136,.08);color:var(--primary);border-color:rgba(0,255,136,.25);}}
.tab.active{{background:linear-gradient(135deg,var(--primary),var(--secondary));color:var(--dark);border-color:transparent;font-weight:700;}}
.form-group{{margin-bottom:1.4rem;}}
.form-group label{{display:block;margin-bottom:.5rem;color:var(--text);font-weight:600;font-size:.92rem;}}
.form-group label i{{color:var(--primary);margin-right:.4rem;font-size:.85rem;}}
.form-group input,.form-group textarea,.form-group select{{width:100%;padding:.85rem 1rem;background:rgba(255,255,255,.04);border:1.5px solid rgba(255,255,255,.1);border-radius:var(--radius-sm);color:var(--text);font-size:.95rem;font-family:'Rajdhani',sans-serif;transition:var(--transition);}}
.form-group input:focus,.form-group textarea:focus,.form-group select:focus{{outline:none;border-color:var(--primary);background:rgba(0,255,136,.05);box-shadow:var(--glow-green);}}
.form-group textarea{{resize:vertical;min-height:100px;}}
.form-group select option{{background:#0e1222;color:var(--text);}}
.file-upload{{position:relative;}}
.file-upload input[type=file]{{position:absolute;inset:0;opacity:0;cursor:pointer;z-index:2;}}
.file-upload-label{{display:flex;flex-direction:column;align-items:center;gap:.4rem;padding:1.5rem;background:rgba(0,255,136,.05);border:2px dashed rgba(0,255,136,.3);border-radius:var(--radius-sm);text-align:center;cursor:pointer;transition:var(--transition);}}
.file-upload-label:hover{{background:rgba(0,255,136,.1);border-color:var(--primary);}}
.file-upload-label i{{font-size:1.6rem;color:var(--primary);}}
.file-upload-label p{{color:var(--text-dim);font-size:.88rem;}}
.image-preview{{max-width:100%;border-radius:var(--radius-sm);border:1px solid rgba(0,255,136,.3);margin-top:.8rem;}}
.toast{{position:fixed;top:90px;right:1.5rem;z-index:99999;background:rgba(14,18,34,.92);backdrop-filter:blur(16px);border:1px solid rgba(0,255,136,.25);border-radius:var(--radius);padding:1rem 1.4rem;box-shadow:0 8px 36px rgba(0,0,0,.5);display:flex;align-items:center;gap:.8rem;max-width:340px;animation:toastSlide .35s cubic-bezier(.4,0,.2,1) both;color:var(--text);font-size:.92rem;}}
.toast.hide{{animation:toastSlide .3s cubic-bezier(.4,0,.2,1) reverse both;}}
.toast i{{font-size:1.2rem;flex-shrink:0;}}
.toast.success i{{color:var(--success);}}
.toast.error i{{color:var(--danger);}}
@keyframes toastSlide{{from{{opacity:0;transform:translateX(110%);}}to{{opacity:1;transform:translateX(0);}}}}
.support-list{{display:flex;flex-direction:column;gap:.7rem;}}
.ticket-row{{background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07);border-radius:var(--radius);padding:1rem 1.2rem;display:flex;align-items:center;justify-content:space-between;gap:1rem;transition:var(--transition);text-decoration:none;flex-wrap:wrap;}}
.ticket-row:hover{{background:rgba(0,255,136,.06);border-color:rgba(0,255,136,.2);}}
.ticket-row-left{{display:flex;align-items:center;gap:.9rem;flex-grow:1;}}
.ticket-id{{font-family:'Orbitron',sans-serif;font-size:.75rem;color:var(--primary);background:rgba(0,255,136,.1);padding:.3rem .7rem;border-radius:6px;font-weight:700;white-space:nowrap;}}
.ticket-subject{{font-weight:600;color:var(--text);font-size:.95rem;}}
.ticket-meta{{font-size:.78rem;color:var(--text-dim);margin-top:.15rem;}}
.ticket-row-right{{display:flex;align-items:center;gap:.7rem;}}
.chat-header{{display:flex;align-items:center;justify-content:space-between;padding:1rem 0;border-bottom:1px solid rgba(255,255,255,.07);margin-bottom:1rem;flex-shrink:0;}}
.chat-header-left{{display:flex;align-items:center;gap:.8rem;}}
.chat-ticket-id{{font-family:'Orbitron',sans-serif;font-size:.75rem;color:var(--primary);background:rgba(0,255,136,.1);padding:.25rem .6rem;border-radius:6px;}}
.chat-title{{font-weight:700;color:var(--text);font-size:1rem;}}
.chat-online{{display:flex;align-items:center;gap:.35rem;font-size:.78rem;color:var(--success);}}
.chat-online::before{{content:'';display:block;width:7px;height:7px;background:var(--success);border-radius:50%;animation:onlinePulse 2s ease-in-out infinite;}}
@keyframes onlinePulse{{0%,100%{{box-shadow:0 0 0 0 rgba(0,255,136,.5);}}50%{{box-shadow:0 0 0 5px transparent;}}}}
.messages-area{{flex-grow:1;overflow-y:auto;padding:.5rem 0;display:flex;flex-direction:column;gap:.7rem;min-height:320px;max-height:460px;scroll-behavior:smooth;}}
.messages-area::-webkit-scrollbar{{width:5px;}}
.messages-area::-webkit-scrollbar-thumb{{background:rgba(0,255,136,.2);border-radius:3px;}}
.msg{{display:flex;gap:.7rem;align-items:flex-end;}}
.msg.mine{{flex-direction:row-reverse;}}
.msg-avatar{{width:32px;height:32px;border-radius:50%;flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:.75rem;font-weight:700;color:#fff;}}
.msg-avatar.user-av{{background:linear-gradient(135deg,var(--secondary),var(--accent2));}}
.msg-avatar.admin-av{{background:linear-gradient(135deg,var(--primary),var(--secondary));color:var(--dark);}}
.msg-bubble{{max-width:72%;padding:.65rem 1rem;border-radius:18px;font-size:.92rem;line-height:1.5;word-break:break-word;}}
.msg.mine .msg-bubble{{background:linear-gradient(135deg,var(--primary),var(--secondary));color:var(--dark);border-bottom-right-radius:4px;box-shadow:0 3px 12px rgba(0,255,136,.25);}}
.msg:not(.mine) .msg-bubble{{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.1);color:var(--text);border-bottom-left-radius:4px;}}
.msg-meta{{font-size:.7rem;color:var(--text-dim);margin-top:.2rem;display:flex;align-items:center;gap:.3rem;}}
.msg.mine .msg-meta{{justify-content:flex-end;}}
.msg-meta .admin-tag{{color:var(--primary);font-weight:700;text-transform:uppercase;font-size:.65rem;letter-spacing:.5px;}}
.chat-input-area{{display:flex;gap:.6rem;padding-top:1rem;border-top:1px solid rgba(255,255,255,.07);flex-shrink:0;}}
.chat-input-area input{{flex-grow:1;}}
.typing-indicator{{display:flex;align-items:center;gap:.35rem;padding:.5rem 0;color:var(--text-dim);font-size:.82rem;min-height:28px;}}
.typing-dots{{display:flex;gap:3px;}}
.typing-dots span{{display:block;width:6px;height:6px;background:var(--text-dim);border-radius:50%;animation:typeDot .8s ease-in-out infinite;}}
.typing-dots span:nth-child(2){{animation-delay:.15s;}}
.typing-dots span:nth-child(3){{animation-delay:.3s;}}
@keyframes typeDot{{0%,60%,100%{{transform:translateY(0);opacity:.4;}}30%{{transform:translateY(-4px);opacity:1;}}}}
footer{{position:relative;z-index:2;margin-top:4rem;background:linear-gradient(180deg,var(--dark) 0%,rgba(6,10,22,.95) 100%);border-top:1px solid rgba(0,255,136,.1);padding:3rem 0 1.5rem;}}
footer::before{{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,transparent,var(--primary),var(--secondary),var(--accent),transparent);opacity:.4;}}
.footer-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:2.5rem;margin-bottom:2.5rem;}}
.footer-col h4{{font-family:'Orbitron',sans-serif;font-size:.95rem;color:var(--primary);margin-bottom:1rem;font-weight:700;}}
.footer-col p,.footer-col li{{color:var(--text-dim);font-size:.88rem;line-height:1.8;}}
.footer-col ul{{list-style:none;}}
.footer-col ul li a{{color:var(--text-dim);text-decoration:none;transition:var(--transition);display:inline-flex;align-items:center;gap:.3rem;}}
.footer-col ul li a:hover{{color:var(--primary);}}
.social-row{{display:flex;gap:.8rem;margin-top:1rem;}}
.social-btn{{width:40px;height:40px;border-radius:10px;display:flex;align-items:center;justify-content:center;background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);color:var(--text-dim);font-size:1rem;text-decoration:none;transition:var(--transition);}}
.social-btn:hover{{transform:translateY(-3px);color:#fff;}}
.social-btn.discord:hover{{background:#5865F2;border-color:#5865F2;box-shadow:0 6px 20px rgba(88,101,242,.4);}}
.social-btn.instagram:hover{{background:linear-gradient(135deg,#E1306C,#F77737);border-color:transparent;}}
.social-btn.telegram:hover{{background:#0088cc;border-color:#0088cc;}}
.social-btn.youtube:hover{{background:#FF0000;border-color:#FF0000;}}
.footer-bottom{{text-align:center;padding-top:2rem;border-top:1px solid rgba(255,255,255,.06);color:var(--text-dim);font-size:.82rem;}}
.music-player{{
    position:fixed;bottom:24px;right:24px;z-index:9998;
    width:54px;height:54px;border-radius:50%;
    background:linear-gradient(135deg,var(--primary),var(--secondary));
    box-shadow:0 6px 28px rgba(0,255,136,.35);
    display:flex;align-items:center;justify-content:center;
    cursor:pointer;transition:var(--transition);
    border:none;outline:none;
}}
.music-player:hover{{transform:scale(1.12);box-shadow:0 8px 36px rgba(0,255,136,.5);}}
.music-player i{{font-size:1.25rem;color:var(--dark);transition:var(--transition);}}
.music-player.playing::before{{
    content:'';position:absolute;inset:-5px;border-radius:50%;
    border:2.5px solid var(--primary);
    animation:ringPulse 1.6s ease-out infinite;
}}
@keyframes ringPulse{{0%{{transform:scale(1);opacity:.7;}}100%{{transform:scale(1.5);opacity:0;}}}}
.music-iframe{{position:fixed;bottom:-999px;right:-999px;width:1px;height:1px;opacity:0;border:none;pointer-events:none;}}
@media(max-width:768px){{
    .hero{{padding:7rem 0 3rem;}}
    .glitch-text{{font-size:2.2rem;}}
    .nav-links{{gap:.3rem;}}
    .nav-links a{{padding:.4rem .6rem;font-size:.82rem;}}
    .nav-links a span{{display:none;}}
    .packages{{grid-template-columns:1fr;}}
    .stats{{grid-template-columns:repeat(2,1fr);}}
    .messages-area{{max-height:320px;}}
    .msg-bubble{{max-width:80%;}}
    table{{font-size:.82rem;}}
    table thead th,table tbody td{{padding:.7rem .8rem;}}
    .server-status-bar{{gap:.7rem;}}
    .status-card{{flex:1 1 130px;max-width:100%;padding:.75rem .9rem;}}
    .rank-chips{{gap:.3rem;}}
    .rank-chip{{font-size:.53rem;padding:.22rem .55rem;}}
}}
@media(max-width:480px){{
    .stats{{grid-template-columns:1fr 1fr;}}
    .status-card{{flex:1 1 100%;}}
}}
</style>
</head>
<body>

<div class="orb orb-1"></div>
<div class="orb orb-2"></div>
<div class="orb orb-3"></div>

{music_iframe_html}

<button class="music-player {music_playing_class}" id="musicToggleBtn" onclick="toggleMusic()" title="Musiqa">
    <i class="fas fa-music" id="musicIcon"></i>
</button>

<nav>
<div class="container">
    <a href="/" class="logo"><span class="logo-icon">⚔️</span> EliteMC</a>
    <ul class="nav-links">
        <li><a href="/"><i class="fas fa-home"></i> <span>Asosiy</span></a></li>
        <li><a href="/news"><i class="fas fa-newspaper"></i> <span>Yangiliklar</span></a></li>
        <li><a href="/shop"><i class="fas fa-shopping-cart"></i> <span>Do'kon</span></a></li>
        {nav_user}
    </ul>
</div>
</nav>

<main>{body_content}</main>

<footer>
<div class="container">
    <div class="footer-grid">
        <div class="footer-col">
            <h4>⚔️ EliteMC.uz</h4>
            <p>O'zbekistonning eng yaxshi Minecraft serveri.</p>
            <p style="margin-top:.6rem;"><strong style="color:var(--text);">Server IP:</strong> {server_ip}</p>
        </div>
        <div class="footer-col">
            <h4>🔗 Sahifalar</h4>
            <ul>
                <li><a href="/"><i class="fas fa-home"></i> Bosh sahifa</a></li>
                <li><a href="/shop"><i class="fas fa-shopping-cart"></i> Do'kon</a></li>
                <li><a href="/support"><i class="fas fa-headset"></i> Support</a></li>
                <li><a href="/register"><i class="fas fa-user-plus"></i> Ro'yxatdan o'tish</a></li>
            </ul>
        </div>
        <div class="footer-col">
            <h4>📱 Ijtimoiy Tarmoqlar</h4>
            <div class="social-row">
                <a href="{settings.get('discord_link', '#')}" class="social-btn discord" target="_blank"><i class="fab fa-discord"></i></a>
                <a href="{settings.get('instagram_link', '#')}" class="social-btn instagram" target="_blank"><i class="fab fa-instagram"></i></a>
                <a href="{settings.get('telegram_link', '#')}" class="social-btn telegram" target="_blank"><i class="fab fa-telegram"></i></a>
                <a href="{settings.get('youtube_link', '#')}" class="social-btn youtube" target="_blank"><i class="fab fa-youtube"></i></a>
            </div>
        </div>
    </div>
    <div class="footer-bottom"><p>© 2026 EliteMC.uz — Barcha huquqlar himoyalangan.</p></div>
</div>
</footer>

<div id="toastRoot"></div>

<script>
document.addEventListener('DOMContentLoaded', () => {{
    document.querySelectorAll('a').forEach(link => {{
        link.addEventListener('click', function(e) {{
            const href = this.getAttribute('href');
            if (href && href.startsWith('/') && !href.startsWith('#') && this.target !== '_blank') {{
                e.preventDefault();
                document.body.classList.add('page-transitioning');
                setTimeout(() => {{ window.location.href = href; }}, 350);
            }}
        }});
    }});
}});

// ─── Music ───
let _musicPlaying = {music_init_js};
let _musicSrc = '{music_url}';
function toggleMusic() {{
    const btn = document.getElementById('musicToggleBtn');
    const icon = document.getElementById('musicIcon');
    const iframe = document.getElementById('musicIframe');
    _musicPlaying = !_musicPlaying;
    if (_musicPlaying) {{
        btn.classList.add('playing');
        icon.classList.replace('fa-volume-xmark','fa-music');
        if (iframe) iframe.src = _musicSrc;
    }} else {{
        btn.classList.remove('playing');
        icon.classList.replace('fa-music','fa-volume-xmark');
        if (iframe) iframe.src = '';
    }}
}}

// ─── Toast ───
let _toastTimer=null;
function showToast(msg,type='success'){{
    if(_toastTimer) clearTimeout(_toastTimer);
    const el=document.getElementById('toastRoot');
    const ic=type==='success'?'fa-check-circle':'fa-exclamation-circle';
    el.innerHTML=`<div class="toast ${{type}}"><i class="fas ${{ic}}"></i><span>${{msg}}</span></div>`;
    _toastTimer=setTimeout(()=>{{ const t=el.querySelector('.toast'); if(t){{t.classList.add('hide');setTimeout(()=>el.innerHTML='',350);}} }},3200);
}}

// ─── Copy IP ───
document.querySelectorAll('.server-ip-box').forEach(el=>{{
    el.addEventListener('click',()=>navigator.clipboard.writeText(el.querySelector('.ip-text').textContent.trim()).then(()=>showToast('Server IP nusxalandi! ✅')));
}});

// ─── AJAX form ───
async function ajaxForm(fid,url){{
    const form=document.getElementById(fid);
    if(!form) return;
    form.addEventListener('submit',async e=>{{
        e.preventDefault();
        const d=Object.fromEntries(new FormData(form));
        try{{
            const r=await fetch(url,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}});
            const j=await r.json();
            showToast(j.message,j.success?'success':'error');
            if(j.success&&j.redirect) setTimeout(()=>window.location.href=j.redirect,1400);
        }}catch(e){{showToast('Xatolik yuz berdi!','error');}}
    }});
}}
ajaxForm('loginForm','/login');
ajaxForm('registerForm','/register');

// ─── File preview ───
document.querySelectorAll('input[type=file]').forEach(inp=>{{
    inp.addEventListener('change',function(e){{
        const f=e.target.files[0];
        if(f&&f.type.startsWith('image/')){{
            const r=new FileReader();
            r.onload=ev=>{{
                const grp=inp.closest('.form-group');
                let p=grp.querySelector('.image-preview');
                if(p) p.remove();
                const img=document.createElement('img');
                img.src=ev.target.result; img.className='image-preview';
                grp.appendChild(img);
            }};
            r.readAsDataURL(f);
        }}
    }});
}});

// ─── BUY FUNCTIONS (YANGILANGAN) ───

// 1. Rank/Key olish (Nik so'raydi)
async function buyRank(pkgId){{
    const nick = prompt("Qaysi nikga sotib olmoqchisiz?");
    if(!nick) return;
    if(!confirm(nick + " uchun ushbu narsani sotib olasizmi?")) return;

    try{{
        const r=await fetch('/buy_rank/'+pkgId, {{
            method:'POST',
            headers:{{'Content-Type':'application/json'}},
            body: JSON.stringify({{ nick: nick }})
        }});
        const j=await r.json(); 
        showToast(j.message, j.success?'success':'error');
        if(j.success) setTimeout(()=>location.reload(),1800);
    }}catch(e){{showToast('Xatolik!','error');}}
}}

// 2. Token narxini hisoblash
function calcTokenPrice() {{
    const el = document.getElementById('tokenAmount');
    if(!el) return;
    const amount = el.value;
    const price = amount * 1.2; 
    document.getElementById('tokenPriceDisplay').innerText = price.toLocaleString() + " so'm";
}}

// 3. Token olish (Custom)
async function buyCustomTokens() {{
    const amount = document.getElementById('tokenAmount').value;
    const nick = prompt("Tokenlar qaysi nikga berilsin?");

    if(!amount || !nick) return showToast("Nik va summani kiriting!", "error");

    try {{
        const r = await fetch('/buy_token_custom', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{ amount: amount, nick: nick }})
        }});
        const j = await r.json();
        showToast(j.message, j.success ? 'success' : 'error');
        if(j.success) setTimeout(()=>location.reload(), 1800);
    }} catch(e) {{ showToast('Xatolik!', 'error'); }}
}}

// ─── ADMIN ACTIONS ───
async function approveDeposit(id){{
    const c=prompt('Izoh (ixtiyoriy):')||'';
    try{{
        const r=await fetch('/admin/approve_deposit/'+id,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{comment:c}})}});
        const j=await r.json(); showToast(j.message,j.success?'success':'error');
        if(j.success) setTimeout(()=>location.reload(),1200);
    }}catch(e){{showToast('Xatolik!','error');}}
}}
async function rejectDeposit(id){{
    const c=prompt('Rad etish sababi:');
    if(!c) return;
    try{{
        const r=await fetch('/admin/reject_deposit/'+id,{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{comment:c}})}});
        const j=await r.json(); showToast(j.message,j.success?'success':'error');
        if(j.success) setTimeout(()=>location.reload(),1200);
    }}catch(e){{showToast('Xatolik!','error');}}
}}
async function saveSettings(){{
    const form=document.getElementById('settingsForm');
    const d=Object.fromEntries(new FormData(form));
    try{{
        const r=await fetch('/admin/settings',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}});
        const j=await r.json(); showToast(j.message,j.success?'success':'error');
    }}catch(e){{showToast('Xatolik!','error');}}
}}

# ... (yuqoridagi kodlar: approveDeposit, rejectDeposit va saveSettings funksiyalari)

async function saveSettings(){{
    const form=document.getElementById('settingsForm');
    const d=Object.fromEntries(new FormData(form));
    try{{
        const r=await fetch('/admin/settings',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}});
        const j=await r.json(); showToast(j.message,j.success?'success':'error');
    }}catch(e){{showToast('Xatolik!','error');}}
}}

// ─── YANGILIK QO'SHISH (YANGI KOD) ───
const _newsForm = document.getElementById('addNewsForm');
if (_newsForm) {{
    _newsForm.addEventListener('submit', async (e) => {{
        e.preventDefault();
        const formData = new FormData(_newsForm); 
        try {{
            const r = await fetch('/admin/add_news', {{
                method: 'POST',
                body: formData 
            }});
            const j = await r.json();
            showToast(j.message, j.success ? 'success' : 'error');
            if (j.success) setTimeout(() => location.reload(), 1500);
        }} catch (err) {{
            showToast("Xatolik yuz berdi", 'error');
        }}
    }});
}}

</script>
</body>
</html>'''

# ═══════════════════════════════════════════════
# INDEX
# ═══════════════════════════════════════════════

@app.route('/')
def index():
    conn = get_db()
    settings = {r['key']: r['value'] for r in conn.execute('SELECT key,value FROM settings').fetchall()}
    all_news = conn.execute('SELECT * FROM news ORDER BY created_at DESC LIMIT 6').fetchall()
    total_users = conn.execute('SELECT COUNT(*) as c FROM users WHERE is_admin=0').fetchone()['c']
    total_purchases = conn.execute('SELECT COUNT(*) as c FROM purchases').fetchone()['c']
    total_revenue = conn.execute('SELECT COALESCE(SUM(amount),0) as s FROM purchases').fetchone()['s']
    ranks = conn.execute(
        "SELECT DISTINCT name, color FROM packages WHERE category='anarchy' AND is_active=1").fetchall()
    conn.close()

    # AVTOMATIK ONLINE TEKSHIRISH
    server_ip = settings.get('server_ip', 'elitemc.uz')
    real_online = get_real_online(server_ip)
    # Agar server ochib qolsa bazadagi eski raqamni yoki 0 ni oladi
    display_online = real_online if real_online is not None else settings.get('online_players', '0')

    trailer_html = ''
    if settings.get('show_trailer') == '1' and settings.get('trailer_url'):
        trailer_html = f'<div style="margin:0 auto 2rem;max-width:800px;border:2px solid var(--primary);border-radius:20px;overflow:hidden;box-shadow:var(--glow-green);position:relative;z-index:1;"><iframe width="100%" height="400" src="{settings.get("trailer_url")}" frameborder="0" allowfullscreen></iframe></div>'

    news_html = ''.join([
        f'<div class="card"><h3 style="color:var(--primary);font-family:Orbitron,sans-serif;font-size:1rem;">{sanitize(n["title"])}</h3><p style="font-size:.78rem;opacity:.5;margin:.3rem 0 .6rem;">{str(n["created_at"])[:16]}</p><p style="font-size:.88rem;">{sanitize(n["content"][:120])}...</p></div>'
        for n in all_news
    ])

    chips = ''
    for i, r in enumerate(ranks):
        delay = i * 0.07
        chips += f'<span class="rank-chip" style="color:{r["color"]};border-color:{r["color"]};background:{r["color"]}18;animation-delay:{delay}s;">{sanitize(r["name"])}</span>'

    content = f'''
    <div class="hero">
        <div class="hero-glow"></div>
        <div class="container">
            {trailer_html}
            <h1 class="glitch-text">EliteMC.uz</h1>
            <p style="position:relative;z-index:1;color:var(--text-dim);font-size:1.05rem;animation:fadeUp .8s .15s ease-out both;">Uzbekistandagi N1 Minecraft Serveri</p>

            <div class="server-ip-box">
                <span class="ip-text">{server_ip}</span>
                <span class="ip-icon"><i class="fas fa-copy"></i></span>
            </div>

            <div class="server-status-bar">
                <div class="status-card pulse-green">
                    <div class="status-icon green"><span class="live-dot"></span><i class="fas fa-signal"></i></div>
                    <div class="status-info">
                        <span class="status-label">Online Players</span>
                        <span class="status-value">{display_online} <span class="dim">/ 2026</span></span>
                    </div>
                </div>
                <div class="status-card">
                    <div class="status-icon blue"><i class="fas fa-layer-group"></i></div>
                    <div class="status-info">
                        <span class="status-label">Version</span>
                        <span class="status-value">{settings.get('server_version', '1.13 - 1.21.x')}</span>
                    </div>
                </div>
                <div class="status-card">
                    <div class="status-icon purple"><i class="fas fa-users"></i></div>
                    <div class="status-info">
                        <span class="status-label">Registered</span>
                        <span class="status-value">{total_users} <span class="dim">players</span></span>
                    </div>
                </div>
                <div class="status-card">
                    <div class="status-icon orange"><i class="fas fa-trophy"></i></div>
                    <div class="status-info">
                        <span class="status-label">Purchases</span>
                        <span class="status-value">{total_purchases} <span class="dim">total</span></span>
                    </div>
                </div>
            </div>
            <div class="rank-chips">{chips}</div>
        </div>
    </div>
    <div class="container">
        <div class="stats">
            <div class="stat-card"><i class="fas fa-users"></i><h3>{total_users}</h3><p>Foydalanuvchilar</p></div>
            <div class="stat-card"><i class="fas fa-shopping-bag"></i><h3>{total_purchases}</h3><p>Xaridlar</p></div>
            <div class="stat-card"><i class="fas fa-coins"></i><h3>{total_revenue:,.0f}</h3><p>Jami daromad</p></div>
        </div>
        <div class="section-title"><h2>📰 Yangiliklar</h2></div>
        <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:1.5rem;">
            {news_html if news_html else '<p style="text-align:center;grid-column:1/-1;opacity:.5;">Yangiliklar hozircha yoq</p>'}
        </div>
    </div>'''
    return render_page(content, logged_in='user_id' in session, is_admin=session.get('is_admin', False))


@app.route('/news')
def news_page():
    conn = get_db()
    all_news = conn.execute('SELECT * FROM news ORDER BY created_at DESC').fetchall()
    conn.close()

    news_html = ""
    for n in all_news:
        news_html += f'''
        <div class="card">
            <div class="card-header"><i class="fas fa-newspaper"></i><h2>{sanitize(n['title'])}</h2></div>
            <p style="color:var(--text-dim);font-size:0.85rem;margin-bottom:1rem;">{n['created_at']}</p>
            <div style="line-height:1.8; color:var(--text);">{sanitize(n['content'])}</div>
        </div>
        '''

    content = f'''
    <div class="container" style="padding-top:2rem; max-width:900px;">
        <div class="section-title"><h2>📰 Barcha Yangiliklar</h2></div>
        {news_html if news_html else '<p style="text-align:center; opacity:0.5;">Yangiliklar mavjud emas.</p>'}
    </div>
    '''
    return render_page(content, logged_in='user_id' in session, is_admin=session.get('is_admin', False))


@app.route('/admin/add_news', methods=['POST'])
@admin_required
def add_news():
    title = request.form.get('title', '').strip()
    content = request.form.get('content', '').strip()
    image_url = None

    if not title or not content:
        return jsonify(success=False, message="Sarlavha va matn talab qilinadi!")

    # Rasm yuklash
    if 'image' in request.files:
        file = request.files['image']
        if file and file.filename and allowed_file(file.filename):
            filename = secure_filename(file.filename)
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            name, ext = os.path.splitext(filename)
            unique_filename = f"{name}_{timestamp}{ext}"

            filepath = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file.save(filepath)

            image_url = f"/static/uploads/{unique_filename}"

    try:
        import json

        news_file = "news.json"

        # Oldingi news yuklash
        try:
            with open(news_file, "r", encoding="utf-8") as f:
                news_list = json.load(f)
        except:
            news_list = []

        # Yangi news qo‘shish
        news_list.append({
            "title": title,
            "content": content,
            "image": image_url,
            "time": datetime.datetime.now().isoformat()
        })

        # Saqlash
        with open(news_file, "w", encoding="utf-8") as f:
            json.dump(news_list, f, indent=4, ensure_ascii=False)

        return jsonify(success=True, message="Yangilik muvaffaqiyatli qo‘shildi!")

    except Exception as e:
        return jsonify(success=False, message=f"Xatolik: {str(e)}")



@app.route('/admin/news/delete/<int:nid>', methods=['POST'])
@admin_required
def delete_news(nid):
    # BU YERDA HAM SURILISHI KERAK
    conn = get_db()
    conn.execute('DELETE FROM news WHERE id=?', (nid,))
    conn.commit()
    conn.close()
    return jsonify(success=True, message="Yangilik o'chirildi!")



# ═══════════════════════════════════════════════
# AUTH
# ═══════════════════════════════════════════════

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        username = sanitize(data.get('username', ''))
        email = sanitize(data.get('email', ''))
        # .encode() va hexdigest() to'g'ri ishlashi uchun hashlib import qilingan bo'lishi kerak
        password = hashlib.sha256(data.get('password', '').encode()).hexdigest()
        minecraft_nick = sanitize(data.get('minecraft_nick', ''))

        try:
            conn = get_db()
            conn.execute('INSERT INTO users (username,email,password,minecraft_nick) VALUES (?,?,?,?)',
                         (username, email, password, minecraft_nick))
            conn.commit()
            conn.close()
            return jsonify(success=True, message="Ro'yxatdan muvaffaqiyatli o'tdingiz!", redirect='/login')
        except sqlite3.IntegrityError:
            return jsonify(success=False, message='Bu username yoki email allaqachon mavjud!')

    # GET so'rovi uchun qism (if dan tashqarida, lekin funksiya ichida)
    content = '''
    <div class="container" style="max-width:480px;margin:6rem auto 4rem;">
        <div class="card">
            <div class="card-header"><i class="fas fa-user-plus"></i><h2>Ro'yxatdan O'tish</h2></div>
            <form id="registerForm">
                <div class="form-group"><label><i class="fas fa-user"></i> Username</label><input type="text" name="username" required placeholder="Sizning ism..."></div>
                <div class="form-group"><label><i class="fas fa-envelope"></i> Email</label><input type="email" name="email" required placeholder="siz@mail.com"></div>
                <div class="form-group"><label><i class="fas fa-lock"></i> Parol</label><input type="password" name="password" required placeholder="••••••••"></div>
                <div class="form-group"><label><i class="fas fa-gamepad"></i> Minecraft Nick</label><input type="text" name="minecraft_nick" required placeholder="Steve"></div>
                <button type="submit" class="btn btn-primary btn-full"><i class="fas fa-user-plus"></i> Ro'yxatdan O'tish</button>
            </form>
            <p style="text-align:center;margin-top:1.2rem;color:var(--text-dim);font-size:.9rem;">Akkountingiz bormi? <a href="/login" style="color:var(--primary);text-decoration:none;font-weight:600;">Kirish</a></p>
        </div>

        <script>
        document.getElementById('registerForm').addEventListener('submit', async (e) => {
            e.preventDefault();
            const formData = new FormData(e.target);
            const data = Object.fromEntries(formData.entries());

            const r = await fetch('/register', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(data)
            });

            const j = await r.json();
            showToast(j.message, j.success ? 'success' : 'error');

            if(j.success && j.redirect) {
                setTimeout(() => window.location.href = j.redirect, 1500);
            }
        });
        </script>
    </div>'''

    return render_page(content, logged_in=False)


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        username = data.get('username', '')
        password = hashlib.sha256(data.get('password', '').encode()).hexdigest()
        conn = get_db()
        user = conn.execute('SELECT * FROM users WHERE username=? AND password=?', (username, password)).fetchone()
        conn.close()
        if user:
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['is_admin'] = bool(user['is_admin'])
            return jsonify(success=True, message='Xush kelibsiz!', redirect='/profile')
        return jsonify(success=False, message="Username yoki parol noto'g'ri!")
    content = '''
    <div class="container" style="max-width:440px;margin:6rem auto 4rem;">
        <div class="card">
            <div class="card-header"><i class="fas fa-sign-in-alt"></i><h2>Kirish</h2></div>
            <form id="loginForm">
                <div class="form-group"><label><i class="fas fa-user"></i> Username</label><input type="text" name="username" required placeholder="Sizning ism..."></div>
                <div class="form-group"><label><i class="fas fa-lock"></i> Parol</label><input type="password" name="password" required placeholder="••••••••"></div>
                <button type="submit" class="btn btn-primary btn-full"><i class="fas fa-sign-in-alt"></i> Kirish</button>
            </form>
            <p style="text-align:center;margin-top:1.2rem;color:var(--text-dim);font-size:.9rem;">Akkountingiz yo'qmi? <a href="/register" style="color:var(--primary);text-decoration:none;font-weight:600;">Ro'yxatdan O'tish</a></p>
        </div>
    </div>'''
    return render_page(content, logged_in=False)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# ═══════════════════════════════════════════════
# SHOP & BUY
# ═══════════════════════════════════════════════

@app.route('/shop')
def shop():
    conn = get_db()
    packages = conn.execute("SELECT * FROM packages WHERE is_active=1 ORDER BY category, price ASC").fetchall()
    conn.close()

    categories = {'anarchy': [], 'smp': [], 'keys': [], 'services': []}

    for p in packages:
        cat = p['category']
        if cat in categories:
            categories[cat].append(dict(p))
        elif cat == 'token':
            pass  # Token alohida chiqadi
        else:
            if 'anarchy' not in categories: categories['anarchy'] = []
            categories['anarchy'].append(dict(p))

    def generate_html(pkg_list):
        if not pkg_list: return ""
        grouped = OrderedDict()
        for p in pkg_list:
            name = p['name']
            if name not in grouped: grouped[name] = []
            grouped[name].append(p)

        html_out = ''
        for name, variants in grouped.items():
            base = variants[0]
            features = [sanitize(f.strip()) for f in base['features'].split(',')]
            feats_li = ''.join(f'<li><i class="fas fa-check-circle"></i>{f}</li>' for f in features)

            select_opts = ''
            for v in variants:
                dur = 'UMRBOT' if v['duration'] == 'UMRBOT' else v['duration']
                select_opts += f'<option value="{v["id"]}">{dur} — {v["price"]:,.0f} so\'m</option>'

            btn = f'<button class="btn btn-primary btn-full" onclick="buySelectedRank(this)"><i class="fas fa-shopping-basket"></i> Sotib Olish</button>' if 'user_id' in session else '<a href="/login" class="btn btn-primary btn-full">Kirish Kerak</a>'

            html_out += f'''
            <div class="package-card" style="--pkg-color:{base['color']};">
                <div class="pkg-badge" style="background:{base['color']};">{base['category'].upper()}</div>
                <div class="package-name" style="color:{base['color']}">{sanitize(name)}</div>
                <div class="package-desc">{sanitize(base['description'])}</div>
                <div class="package-price" style="color:{base['color']}">{base['price']:,.0f} <span>so'm</span></div>
                <ul class="package-features">{feats_li}</ul>
                <div class="form-group" style="margin-bottom:.8rem;">
                    <select class="pkg-select" onchange="updatePkgPrice(this)">{select_opts}</select>
                </div>
                {btn}
            </div>'''
        return html_out

    html_anarchy = generate_html(categories['anarchy'])
    html_smp = generate_html(categories['smp'])
    html_keys = generate_html(categories['keys'])
    html_services = generate_html(categories['services'])

    # TOKEN KALKULYATORI
    html_token = '''
    <div class="card" style="grid-column: 1 / -1; max-width: 600px; margin: 0 auto; border-color: #fbbf24;">
        <div class="card-header"><i class="fas fa-coins" style="color:#fbbf24;"></i><h2>Token Sotib Olish</h2></div>
        <div style="padding:1rem;">
            <div class="form-group">
                <label>Token miqdori</label>
                <input type="number" id="tokenAmount" placeholder="Masalan: 1000" oninput="calcTokenPrice()">
            </div>
            <div style="display:flex;justify-content:space-between;margin-bottom:1rem;background:rgba(255,255,255,0.05);padding:1rem;border-radius:10px;">
                <span>Narxi:</span>
                <strong style="color:var(--primary);font-size:1.2rem;" id="tokenPriceDisplay">0 so'm</strong>
            </div>
            ''' + (
        f'<button class="btn btn-primary btn-full" onclick="buyCustomTokens()">Sotib Olish</button>' if 'user_id' in session else '<a href="/login" class="btn btn-primary btn-full">Kirish Kerak</a>') + '''
        </div>
        <p style="text-align:center;font-size:0.8rem;color:var(--text-dim);margin-top:10px;">Kurs: 1 Token = 1.2 so'm</p>
    </div>
    '''

    content = f'''
    <div class="container" style="padding-top:2rem;">
        <div class="section-title"><h2>🛒 Do'kon</h2></div>

        <div class="tabs" style="justify-content:center;margin-bottom:2rem;">
            <button onclick="openTab('anarchy')" class="tab active" id="btn-anarchy">⚔️ Anarxiya</button>
            <button onclick="openTab('smp')" class="tab" id="btn-smp">🌲 SMP</button>
            <button onclick="openTab('keys')" class="tab" id="btn-keys">🔑 Keys</button>
            <button onclick="openTab('services')" class="tab" id="btn-services">🛠️ Xizmatlar</button>
            <button onclick="openTab('token')" class="tab" id="btn-token">🪙 Tokenlar</button>
        </div>

        <div id="tab-anarchy" class="packages">{html_anarchy}</div>
        <div id="tab-smp" class="packages" style="display:none;">{html_smp}</div>
        <div id="tab-keys" class="packages" style="display:none;">{html_keys}</div>
        <div id="tab-services" class="packages" style="display:none;">{html_services}</div>
        <div id="tab-token" class="packages" style="display:none;">{html_token}</div>
    </div>
    <script>
    function openTab(name){{
        ['anarchy','smp','token','keys','services'].forEach(t=>{{
            const el = document.getElementById('tab-'+t);
            const btn = document.getElementById('btn-'+t);
            if(el) el.style.display='none';
            if(btn) btn.classList.remove('active');
        }});
        document.getElementById('tab-'+name).style.display='grid';
        document.getElementById('btn-'+name).classList.add('active');
    }}
    function updatePkgPrice(sel){{
        const card=sel.closest('.package-card');
        const txt=sel.options[sel.selectedIndex].textContent;
        const m=txt.match(/([\\d,]+)\\s*so/);
        if(m) card.querySelector('.package-price').innerHTML=m[1]+' <span>so\\'m</span>';
    }}
    function buySelectedRank(btn){{
        const card=btn.closest('.package-card');
        buyRank(card.querySelector('.pkg-select').value);
    }}
    </script>'''
    return render_page(content, logged_in='user_id' in session, is_admin=session.get('is_admin', False))


@app.route('/buy_rank/<int:package_id>', methods=['POST'])
@login_required
def buy_rank(package_id):
    # Frontdan nikni olamiz
    data = request.get_json(force=True, silent=True) or {}
    custom_nick = data.get('nick')

    conn = get_db()
    pkg = conn.execute('SELECT * FROM packages WHERE id=?', (package_id,)).fetchone()
    user = conn.execute('SELECT balance FROM users WHERE id=?', (session['user_id'],)).fetchone()

    if not pkg:
        conn.close()
        return jsonify(success=False, message='Tovar topilmadi!')

    if not custom_nick:
        conn.close()
        return jsonify(success=False, message="Iltimos, o'yinchi nikini kiriting!")

    if not user or user['balance'] < pkg['price']:
        conn.close()
        return jsonify(success=False, message="Mablag' yetarli emas!")

    # Nikni yangilaymiz
    nick = custom_nick
    new_bal = user['balance'] - pkg['price']

    ok, resp = execute_purchase(nick, pkg)

    if ok:
        conn.execute('UPDATE users SET balance=? WHERE id=?', (new_bal, session['user_id']))
        conn.execute('INSERT INTO purchases (user_id,package_id,amount,package_name,minecraft_nick) VALUES (?,?,?,?,?)',
                     (session['user_id'], package_id, pkg['price'], pkg['name'], nick))
        conn.commit()
        conn.close()
        return jsonify(success=True, message=f"{nick} ga {pkg['name']} berildi!", new_balance=new_bal)

    conn.close()
    return jsonify(success=False, message=f"Server xatosi: {resp}")


# ═══════════════════════════════════════════════
# BALANCE
# ═══════════════════════════════════════════════

@app.route('/rules')
def rules():
    content = '''
    <div class="container" style="padding-top:2rem; padding-bottom: 3rem;">
        <div class="section-title"><h2>❄️ EliteMC - Qoidalar</h2></div>

        <div class="card" style="margin-bottom: 2rem;">
            <div class="card-header">
                <i class="fas fa-book-open"></i>
                <h2>Server Qoidalari</h2>
            </div>
            <div style="display: flex; flex-direction: column; gap: 15px; font-size: 1.1rem; color: var(--text);">
                <div style="padding: 12px 15px; background: rgba(255, 51, 102, 0.1); border-left: 5px solid #ff3366; border-radius: 8px; display: flex; justify-content: space-between; align-items: center;">
                    <span><b>SO'KINISH</b></span>
                    <span style="color: var(--text-dim);">2 SOAT MUTE 🔕</span>
                </div>

                <div style="padding: 12px 15px; background: rgba(0, 255, 136, 0.1); border-left: 5px solid var(--primary); border-radius: 8px; display: flex; justify-content: space-between; align-items: center;">
                    <span><b>CHEATERLIK</b></span>
                    <span style="color: var(--text-dim);">2 KUN BAN ✨</span>
                </div>

                <div style="padding: 12px 15px; background: rgba(255, 170, 0, 0.1); border-left: 5px solid var(--warning); border-radius: 8px; display: flex; justify-content: space-between; align-items: center;">
                    <span><b>REKLAMA QILISH</b></span>
                    <span style="color: var(--text-dim);">1 KUN MUTE 🔕</span>
                </div>

                <div style="padding: 12px 15px; background: rgba(168, 85, 247, 0.1); border-left: 5px solid var(--accent2); border-radius: 8px; display: flex; justify-content: space-between; align-items: center;">
                    <span><b>JINSIY MOTERALLAR (CHAT)</b></span>
                    <span style="color: var(--text-dim);">6 SOAT MUTE ⚡</span>
                </div>

                <div style="padding: 12px 15px; background: rgba(0, 153, 255, 0.1); border-left: 5px solid var(--secondary); border-radius: 8px; display: flex; justify-content: space-between; align-items: center;">
                    <span><b>YOLG'ON MA'LUMOT TARQATISH</b></span>
                    <span style="color: var(--text-dim);">10 KUN BAN ✨</span>
                </div>
            </div>
        </div>

        <div class="card" style="border: 2px solid var(--warning); background: rgba(255, 170, 0, 0.05);">
            <div class="card-header">
                <i class="fas fa-star" style="color: var(--warning);"></i>
                <h2 style="color: var(--warning);">⭐ HELPER YOKI MODER UCHUN</h2>
            </div>
            <div style="display: flex; flex-direction: column; gap: 15px; font-size: 1.1rem;">
                <div style="padding: 10px; border: 1px dashed var(--warning); border-radius: 8px; color: #fff;">
                    ❌ <b>BESABAB MUTE</b> - ISHDAN OZOD QILINADI ‼️
                </div>
                <div style="padding: 10px; border: 1px dashed var(--warning); border-radius: 8px; color: #fff;">
                    ❌ <b>BESABAB BAN</b> - ISHDAN OZOD QILINADI ‼️
                </div>
            </div>
        </div>
    </div>
    '''
    return render_page(content, logged_in='user_id' in session, is_admin=session.get('is_admin', False))


@app.route('/balance')
@login_required
def balance():
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    deposits = conn.execute('SELECT * FROM balance_deposits WHERE user_id=? ORDER BY created_at DESC',
                            (session['user_id'],)).fetchall()
    settings = {r['key']: r['value'] for r in conn.execute('SELECT key,value FROM settings').fetchall()}
    conn.close()
    rows_html = ''
    for d in deposits:
        sc = 'pending' if d['status'] == 'pending' else ('approved' if d['status'] == 'approved' else 'rejected')
        st = '⏳ Kutilmoqda' if d['status'] == 'pending' else (
            '✅ Tasdiqlandi' if d['status'] == 'approved' else '❌ Rad etildi')
        rows_html += f'<tr><td>#{d["id"]}</td><td><strong>{d["amount"]:,.0f} so\'m</strong></td><td><span class="badge badge-{sc}">{st}</span></td><td>{str(d["created_at"])[:16]}</td><td>{d["admin_comment"] or "—"}</td></tr>'
    content = f'''
    <div class="container" style="max-width:780px;margin:0 auto;padding-top:2rem;">
        <div class="section-title"><h2>💰 Balans</h2></div>
        <div class="balance-hero"><h3>Joriy Balans</h3><div class="balance-amount">{user['balance']:,.0f} <span>so'm</span></div></div>
        <div class="card">
            <div class="card-header"><i class="fas fa-credit-card"></i><h2>Balansga Pul Qo'shish</h2></div>
            <div class="alert alert-warning"><i class="fas fa-exclamation-triangle"></i><div><strong>Diqqat!</strong> Pul o'tkazishdan oldin quyidagi ma'lumotlarni o'qing.</div></div>
            <div class="alert alert-info"><i class="fas fa-credit-card"></i><div><strong>Admin Karta:</strong><br/>💳 {settings.get('admin_card_number', '')}<br/>👤 {settings.get('admin_card_name', '')}</div></div>
            <form action="/deposit_balance" method="POST" enctype="multipart/form-data">
                <div class="form-group"><label><i class="fas fa-money-bill-wave"></i> Summa (so'm)</label><input type="number" name="amount" required min="1000" placeholder="10000"></div>
                <div class="form-group"><label><i class="fas fa-credit-card"></i> Karta raqami</label><input type="text" name="card_number" required placeholder="8600 **** **** ****"></div>
                <div class="form-group"><label><i class="fas fa-hashtag"></i> Transaksiya ID</label><input type="text" name="transaction_id" required placeholder="TXN12345678"></div>
                <div class="form-group"><label><i class="fas fa-camera"></i> Skrinshot (ixtiyoriy)</label><div class="file-upload"><input type="file" name="screenshot" accept="image/*"><div class="file-upload-label"><i class="fas fa-cloud-upload-alt"></i><p>Rasmni surting yoki bosing</p></div></div></div>
                <button type="submit" class="btn btn-primary btn-full"><i class="fas fa-paper-plane"></i> So'rov Yuborish</button>
            </form>
        </div>
        <div class="card">
            <div class="card-header"><i class="fas fa-history"></i><h2>To'lov Tarixi</h2></div>
            <div class="table-wrap"><table>
                <thead><tr><th>#</th><th>Summa</th><th>Status</th><th>Sana</th><th>Izoh</th></tr></thead>
                <tbody>{rows_html or '<tr><td colspan="5" style="text-align:center;color:var(--text-dim);padding:1.5rem;">Tolovlar yoq</td></tr>'}</tbody>
            </table></div>
        </div>
    </div>'''
    return render_page(content, logged_in=True, is_admin=session.get('is_admin', False))


@app.route('/deposit_balance', methods=['POST'])
@login_required
def deposit_balance():
    amount = request.form.get('amount')
    card_number = sanitize(request.form.get('card_number', ''))
    transaction_id = sanitize(request.form.get('transaction_id', ''))
    screenshot = None
    if 'screenshot' in request.files:
        f = request.files['screenshot']
        if f and allowed_file(f.filename):
            fname = secure_filename(f"{session['user_id']}_{datetime.datetime.now().timestamp()}_{f.filename}")
            f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
            screenshot = f'/static/uploads/{fname}'
    conn = get_db()
    conn.execute(
        'INSERT INTO balance_deposits (user_id,amount,card_number,transaction_id,screenshot) VALUES (?,?,?,?,?)',
        (session['user_id'], amount, card_number, transaction_id, screenshot))
    conn.commit();
    conn.close()
    return redirect(url_for('balance'))


# ═══════════════════════════════════════════════
# PROFILE
# ═══════════════════════════════════════════════


@app.route('/profile')
@login_required
def profile():
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    purchases = conn.execute('SELECT * FROM purchases WHERE user_id=? ORDER BY created_at DESC',
                             (session['user_id'],)).fetchall()

    res_spent = conn.execute('SELECT SUM(amount) as s FROM purchases WHERE user_id=?', (session['user_id'],)).fetchone()
    join_date = str(user['created_at'])[:10]
    user_tokens = user['tokens'] if user['tokens'] else 0
    conn.close()

    pur_html = ''
    for p in purchases:
        pur_html += f'<tr><td>#{p["id"]}</td><td><strong>{sanitize(p["package_name"])}</strong></td><td>{p["amount"]:,.0f}</td><td>{str(p["created_at"])[:16]}</td><td><span class="badge badge-success">✅ {sanitize(p["status"])}</span></td></tr>'

    content = f'''
    <style>
        .stat-grid-box {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 1rem; margin-top: 1rem; }}
        .game-stat {{ background: rgba(0,0,0,0.3); padding: 1rem; border-radius: 10px; border: 1px solid rgba(255,255,255,0.05); display: flex; align-items: center; gap: 1rem; }}
        .game-stat h4 {{ font-size: 0.8rem; color: #6b7a9a; margin-bottom: 0.2rem; }}
        .game-stat .val {{ font-family: 'Orbitron'; font-size: 1.2rem; color: #fff; }}
    </style>
    <div class="container" style="max-width:1100px;margin:0 auto;padding-top:2rem;">
        <div class="section-title"><h2>👤 Profil</h2></div>
        <div style="display:grid;grid-template-columns: 1fr; gap: 2rem;">
            <div>
                <div class="card">
                    <div class="card-header"><i class="fas fa-id-card"></i><h2>Info</h2></div>
                    <div style="text-align:center;margin-bottom:1.5rem;">
                        <img src="https://mc-heads.net/avatar/{user['minecraft_nick']}/100" style="border-radius:50%;margin-bottom:1rem;">
                        <h3>{sanitize(user['minecraft_nick'])}</h3>
                        <p style="color:#6b7a9a;">{sanitize(user['username'])}</p>
                    </div>
                    <div style="padding:0.8rem;background:rgba(255,255,255,0.03);border-radius:8px;display:flex;justify-content:space-between;">
                        <span>Balans</span><strong>{user['balance']:,.0f}</strong>
                    </div>
                </div>
            </div>
            </div>
        <div class="card" style="margin-top:2rem;">
            <div class="card-header"><h2>Xaridlar</h2></div>
            <div class="table-wrap"><table><thead><tr><th>#</th><th>Nomi</th><th>Narx</th><th>Sana</th><th>Status</th></tr></thead><tbody>{pur_html or '<tr><td colspan="5">Bosh</td></tr>'}</tbody></table></div>
        </div>
    </div>'''
    return render_page(content, logged_in=True, is_admin=session.get('is_admin', False))


# ═══════════════════════════════════════════════
# SUPPORT
# ═══════════════════════════════════════════════

@app.route('/support')
@login_required
def support():
    conn = get_db()
    tickets = conn.execute('SELECT * FROM support_tickets WHERE user_id=? ORDER BY created_at DESC',
                           (session['user_id'],)).fetchall()
    conn.close()
    list_html = ''
    for t in tickets:
        bc = 'badge-open' if t['status'] == 'open' else (
            'badge-answered' if t['status'] == 'answered' else 'badge-closed')
        lb = 'Ochiq' if t['status'] == 'open' else ('Javob berildi' if t['status'] == 'answered' else 'Yopilgan')
        list_html += f'<a href="/support/{t["id"]}" class="ticket-row" style="text-decoration:none;"><div class="ticket-row-left"><span class="ticket-id">#{t["id"]}</span><div><div class="ticket-subject">{sanitize(t["subject"])}</div><div class="ticket-meta"><i class="fas fa-clock"></i> {str(t["created_at"])[:16]}</div></div></div><div class="ticket-row-right"><span class="badge {bc}">{lb}</span><span class="btn btn-outline btn-sm"><i class="fas fa-eye"></i> Ko\'rish</span></div></a>'
    if not list_html:
        list_html = '<div style="text-align:center;color:var(--text-dim);padding:2.5rem 0;"><i class="fas fa-inbox" style="font-size:2.5rem;margin-bottom:.8rem;display:block;opacity:.4;"></i>Murojaatlar hali yo\'q</div>'
    content = f'''
    <div class="container" style="max-width:780px;margin:0 auto;padding-top:2rem;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1.5rem;flex-wrap:wrap;gap:.8rem;">
            <div class="section-title" style="margin:0;text-align:left;"><h2>🛠️ Support</h2></div>
            <a href="/support/new" class="btn btn-primary btn-sm"><i class="fas fa-plus"></i> Yangi Murojaat</a>
        </div>
        <div class="card"><div class="support-list">{list_html}</div></div>
    </div>'''
    return render_page(content, logged_in=True, is_admin=session.get('is_admin', False))


@app.route('/support/new', methods=['GET', 'POST'])
@login_required
def new_ticket():
    if request.method == 'POST':
        subject = sanitize(request.form.get('subject', ''))
        message = sanitize(request.form.get('message', ''))
        conn = get_db()
        conn.execute('INSERT INTO support_tickets (user_id,subject) VALUES (?,?)', (session['user_id'], subject))
        ticket_id = conn.execute('SELECT last_insert_rowid() as id').fetchone()['id']
        conn.execute('INSERT INTO support_messages (ticket_id,user_id,message) VALUES (?,?,?)',
                     (ticket_id, session['user_id'], message))
        conn.commit();
        conn.close()
        return redirect(url_for('view_ticket', ticket_id=ticket_id))
    content = '''
    <div class="container" style="max-width:720px;margin:0 auto;padding-top:2rem;">
        <div class="card">
            <div class="card-header"><i class="fas fa-pen-fancy"></i><h2>Yangi Murojaat</h2></div>
            <form method="POST">
                <div class="form-group"><label><i class="fas fa-heading"></i> Mavzu</label><input type="text" name="subject" required placeholder="Masalan: To'lov o'tmadi..."></div>
                <div class="form-group"><label><i class="fas fa-comment-dots"></i> Xabar</label><textarea name="message" rows="4" required placeholder="Muammoni batafsil yozing..."></textarea></div>
                <div style="display:flex;gap:.6rem;">
                    <button type="submit" class="btn btn-primary"><i class="fas fa-paper-plane"></i> Yuborish</button>
                    <a href="/support" class="btn btn-outline"><i class="fas fa-arrow-left"></i> Bekor</a>
                </div>
            </form>
        </div>
    </div>'''
    return render_page(content, logged_in=True, is_admin=session.get('is_admin', False))


@app.route('/support/<int:ticket_id>', methods=['GET', 'POST'])
@login_required
def view_ticket(ticket_id):
    conn = get_db()
    if request.method == 'POST':
        message = sanitize(request.form.get('message', ''))
        is_admin = 1 if session.get('is_admin') else 0
        conn.execute('INSERT INTO support_messages (ticket_id,user_id,message,is_admin_reply) VALUES (?,?,?,?)',
                     (ticket_id, session['user_id'], message, is_admin))
        conn.execute('UPDATE support_tickets SET status=? WHERE id=?', ('answered' if is_admin else 'open', ticket_id))
        conn.commit()
    ticket = conn.execute('SELECT * FROM support_tickets WHERE id=?', (ticket_id,)).fetchone()
    if not ticket or (ticket['user_id'] != session['user_id'] and not session.get('is_admin')):
        conn.close();
        return redirect(url_for('support'))
    messages = conn.execute(
        'SELECT sm.*, u.username FROM support_messages sm JOIN users u ON sm.user_id=u.id WHERE ticket_id=? ORDER BY sm.created_at ASC',
        (ticket_id,)).fetchall()
    conn.close()
    msgs_html = ''
    for m in messages:
        is_mine = (m['user_id'] == session['user_id'])
        cls = 'msg mine' if is_mine else 'msg'
        av = 'user-av' if is_mine else 'admin-av'
        al = sanitize(m['username'][0].upper()) if m['username'] else '?'
        at = '<span class="admin-tag"><i class="fas fa-bolt"></i> Admin</span> ' if m['is_admin_reply'] else ''
        msgs_html += f'<div class="{cls}"><div class="msg-avatar {av}">{al}</div><div><div class="msg-bubble">{sanitize(m["message"])}</div><div class="msg-meta">{at}{sanitize(m["username"])} • {str(m["created_at"])[:16]}</div></div></div>'
    bc = 'badge-open' if ticket['status'] == 'open' else (
        'badge-answered' if ticket['status'] == 'answered' else 'badge-closed')
    lb = 'Ochiq' if ticket['status'] == 'open' else ('Javob berildi' if ticket['status'] == 'answered' else 'Yopilgan')
    content = f'''
    <div class="container" style="max-width:780px;margin:0 auto;padding-top:2rem;">
        <div class="card" style="display:flex;flex-direction:column;">
            <div class="chat-header">
                <div class="chat-header-left">
                    <a href="/support" class="btn btn-outline btn-sm"><i class="fas fa-arrow-left"></i></a>
                    <span class="chat-ticket-id">#{ticket['id']}</span>
                    <div><div class="chat-title">{sanitize(ticket['subject'])}</div><span class="badge {bc}" style="font-size:.7rem;">{lb}</span></div>
                </div>
                <div class="chat-online">Online</div>
            </div>
            <div class="messages-area" id="messagesArea">{msgs_html}</div>
            <div class="typing-indicator" id="typingIndicator" style="display:none;"><div class="typing-dots"><span></span><span></span><span></span></div><span id="typingWho">Admin</span> yozmoqda...</div>
            <div class="chat-input-area">
                <input type="text" id="chatInput" placeholder="Xabar yozing..." autocomplete="off"/>
                <button class="btn btn-primary btn-sm" id="sendBtn"><i class="fas fa-paper-plane"></i></button>
            </div>
        </div>
    </div>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
    <script>
    (function(){{
        const TID={ticket_id}, UID={session['user_id']}, IS_ADMIN={'true' if session.get('is_admin') else 'false'}, UNAME='{sanitize(session.get("username", ""))}';
        const area=document.getElementById('messagesArea'), inp=document.getElementById('chatInput'), btn=document.getElementById('sendBtn');
        const typEl=document.getElementById('typingIndicator'), typWho=document.getElementById('typingWho');
        function scrollBot(){{area.scrollTop=area.scrollHeight;}} scrollBot();
        let socket=null;
        try{{socket=io();}}catch(e){{}}
        if(socket){{
            socket.emit('join_ticket',{{ticket_id:TID}});
            socket.on('new_message',d=>{{ if(d.ticket_id!==TID||d.user_id===UID) return; appendMsg(d); scrollBot(); }});
            socket.on('typing',d=>{{ if(d.ticket_id!==TID||d.user_id===UID) return; typWho.textContent=d.username; typEl.style.display='flex'; clearTimeout(typEl._t); typEl._t=setTimeout(()=>typEl.style.display='none',2500); }});
            let tt=null;
            inp.addEventListener('input',()=>{{ if(!tt){{socket.emit('typing',{{ticket_id:TID,user_id:UID,username:UNAME}}); tt=setTimeout(()=>tt=null,1200);}} }});
        }}
        function appendMsg(d){{
            const mine=(d.user_id===UID), cls=mine?'msg mine':'msg', av=mine?'user-av':'admin-av';
            const al=(d.username||'?')[0].toUpperCase();
            const at=d.is_admin?'<span class="admin-tag"><i class="fas fa-bolt"></i> Admin</span> ':'';
            const now=new Date().toLocaleString('uz-UZ',{{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}});
            const div=document.createElement('div'); div.className=cls;
            div.innerHTML='<div class="msg-avatar '+av+'">'+al+'</div><div><div class="msg-bubble">'+d.message+'</div><div class="msg-meta">'+at+d.username+' • '+now+'</div></div>';
            area.appendChild(div);
        }}
        async function send(){{
            const t=inp.value.trim(); if(!t) return; inp.value='';
            const o={{ticket_id:TID,user_id:UID,username:UNAME,message:t,is_admin:IS_ADMIN}};
            appendMsg(o); scrollBot();
            if(socket) socket.emit('send_message',o);
            try{{await fetch('/support/'+TID+'/send',{{method:'POST',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{message:t}})}});}}catch(e){{}}
        }}
        btn.addEventListener('click',send);
        inp.addEventListener('keydown',e=>{{if(e.key==='Enter'&&!e.shiftKey){{e.preventDefault();send();}}}}); 
    }})();
    </script>'''
    return render_page(content, logged_in=True, is_admin=session.get('is_admin', False))


@app.route('/support/<int:ticket_id>/send', methods=['POST'])
@login_required
def send_support_message(ticket_id):
    data = request.get_json(force=True, silent=True) or {}
    message = sanitize(data.get('message', ''))
    if not message: return jsonify(success=False, message='Xabar bo\'sh!')
    conn = get_db()
    ticket = conn.execute('SELECT * FROM support_tickets WHERE id=?', (ticket_id,)).fetchone()
    if not ticket or (ticket['user_id'] != session['user_id'] and not session.get('is_admin')):
        conn.close();
        return jsonify(success=False, message='Ruxsat yo\'q!')
    is_admin = 1 if session.get('is_admin') else 0
    conn.execute('INSERT INTO support_messages (ticket_id,user_id,message,is_admin_reply) VALUES (?,?,?,?)',
                 (ticket_id, session['user_id'], message, is_admin))
    conn.execute('UPDATE support_tickets SET status=? WHERE id=?', ('answered' if is_admin else 'open', ticket_id))
    conn.commit();
    conn.close()
    return jsonify(success=True)


# ═══════════════════════════════════════════════
# WEBSOCKET
# ═══════════════════════════════════════════════

@socketio.on('join_ticket')
def handle_join(data):
    join_room(f"ticket_{data.get('ticket_id')}")


@socketio.on('disconnect')
def handle_disconnect():
    pass


@socketio.on('send_message')
def handle_send_message(data):
    emit('new_message', data, to=f"ticket_{data.get('ticket_id')}", include_sender=False)


@socketio.on('typing')
def handle_typing(data):
    emit('typing', data, to=f"ticket_{data.get('ticket_id')}", include_sender=False)


@app.route('/buy_token_custom', methods=['POST'])
@login_required
def buy_token_custom():
    data = request.get_json(force=True)
    try:
        amount = int(data.get('amount', 0))
        nick = sanitize(data.get('nick', ''))

        if amount < 100:
            return jsonify(success=False, message="Minimal 100 token!")
        if not nick:
            return jsonify(success=False, message="Nik kiritilmadi!")

        # KURS: 1 Token = 1.2 so'm
        price = amount * 1.2

        conn = get_db()
        user = conn.execute('SELECT balance FROM users WHERE id=?', (session['user_id'],)).fetchone()

        if user['balance'] < price:
            conn.close()
            return jsonify(success=False, message=f"Mablag' yetarli emas! {price:,.0f} so'm kerak.")

        # RCON COMMAND
        cmd = f"playerpoints give {nick} {amount}"

        if MCRCON_AVAILABLE:
            conn_set = get_db()
            settings = {r['key']: r['value'] for r in conn_set.execute('SELECT key, value FROM settings').fetchall()}
            conn_set.close()
            with MCRcon(settings.get('rcon_host'), settings.get('rcon_password'),
                        port=int(settings.get('rcon_port'))) as mcr:
                mcr.command(cmd)

        new_bal = user['balance'] - price
        conn.execute('UPDATE users SET balance=? WHERE id=?', (new_bal, session['user_id']))
        conn.execute('INSERT INTO purchases (user_id, amount, package_name, minecraft_nick) VALUES (?, ?, ?, ?)',
                     (session['user_id'], price, f"{amount} Token", nick))
        conn.commit()
        conn.close()

        return jsonify(success=True, message=f"{nick} ga {amount} Token berildi!", new_balance=new_bal)

    except Exception as e:
        return jsonify(success=False, message=f"Xatolik: {str(e)}")


# ═══════════════════════════════════════════════
# ADMIN
# ═══════════════════════════════════════════════


# ═══════════════════════════════════════════════
# ADMIN - RANKLARNI BOSHQARISH (PROFESSIONAL)
# ═══════════════════════════════════════════════
@app.route('/admin/ranks')
@admin_required
def admin_ranks():
    """Ranklarni boshqarish - Professional modal bilan"""
    content = """
    <div class="container">
        <div class="card">
            <div class="card-header">
                <i class="fas fa-crown"></i>
                <h2>Ranklarni Boshqarish</h2>
            </div>
            <p style="color:var(--text-dim);margin-bottom:1.5rem">
                Ranklarni kategoriyalar bo'yicha boshqaring
            </p>

            <button onclick="showAddModal()" class="btn" style="margin-bottom:2rem">
                <i class="fas fa-plus-circle"></i> Yangi Rank
            </button>
            <form id="addNewsForm">
    <div class="form-group">
        <label>Sarlavha</label>
        <input type="text" name="title" required placeholder="Yangilik nomi...">
    </div>
    <div class="form-group">
        <label>Rasm (Ixtiyoriy)</label>
        <div class="file-upload">
            <input type="file" name="image" accept="image/*">
            <div class="file-upload-label">
                <i class="fas fa-image"></i>
                <p>Rasmni tanlang</p>
            </div>
        </div>
        <div class="image-preview-container" style="margin-top:10px;"></div> 
    </div>
    <div class="form-group">
        <label>Matn</label>
        <textarea name="content" required placeholder="Batafsil..."></textarea>
    </div>
    <button type="submit" class="btn btn-primary btn-full">Chiqarish</button>
</form>

            <div id="ranksContainer"></div>
        </div>
    </div>

    <div id="rankModal" class="modal-overlay">
        <div class="modal-content">
            <div class="modal-header">
                <h2 id="modalTitle"><i class="fas fa-crown"></i> Yangi Rank</h2>
                <button onclick="closeModal()" class="modal-close">
                    <i class="fas fa-times"></i>
                </button>
            </div>

            <form id="rankForm" onsubmit="return handleSubmit(event)">
                <input type="hidden" id="rankId">

                <div class="form-row">
                    <div class="form-group">
                        <label><i class="fas fa-tag"></i> Rank Nomi *</label>
                        <input type="text" id="rankName" required placeholder="VIP, Premium...">
                    </div>

                    <div class="form-group">
                        <label><i class="fas fa-folder"></i> Kategoriya *</label>
                        <select id="rankCategory" required>
                            <option value="">Tanlang...</option>
                            <option value="anarchy">⚔️ Anarxiya</option>
                            <option value="smp">🌲 SMP</option>
                            <option value="keys">🔑 Kalitlar</option>
                            <option value="services">🛠️ Xizmatlar</option>
                            <option value="token">🪙 Tokenlar</option>
                        </select>
                    </div>
                </div>

                <div class="form-group">
                    <label><i class="fas fa-align-left"></i> Tavsif</label>
                    <textarea id="rankDesc" rows="2" placeholder="Qisqacha tavsif..."></textarea>
                </div>

                <div class="form-row">
                    <div class="form-group">
                        <label><i class="fas fa-money-bill-wave"></i> Narxi (so'm) *</label>
                        <input type="number" id="rankPrice" required placeholder="10000">
                    </div>

                    <div class="form-group">
                        <label><i class="fas fa-clock"></i> Davomiyligi *</label>
                        <input type="text" id="rankDuration" required placeholder="30 kun, UMRBOQIY">
                    </div>
                </div>

                <div class="form-group">
                    <label><i class="fas fa-list-check"></i> Imkoniyatlar <small>(vergul bilan)</small></label>
                    <textarea id="rankFeatures" rows="3" placeholder="Kit access, Fly, /home 5"></textarea>
                </div>

                <div class="form-row">
                    <div class="form-group">
                        <label><i class="fas fa-palette"></i> Rang *</label>
                        <div style="display:flex;gap:0.5rem;align-items:center">
                            <input type="color" id="rankColorPicker" value="#3b82f6" style="width:50px;height:40px;border:2px solid var(--border);border-radius:8px;cursor:pointer;background:none">
                            <input type="text" id="rankColor" value="#3b82f6" placeholder="#3b82f6" style="flex:1">
                        </div>
                    </div>

                    <div class="form-group">
                        <label><i class="fas fa-toggle-on"></i> Holat</label>
                        <select id="rankActive">
                            <option value="1">✅ Aktiv</option>
                            <option value="0">❌ Nofaol</option>
                        </select>
                    </div>
                </div>

                <div class="modal-footer">
                    <button type="submit" class="btn btn-primary">
                        <i class="fas fa-save"></i> Saqlash
                    </button>
                    <button type="button" onclick="closeModal()" class="btn btn-secondary">
                        <i class="fas fa-times"></i> Bekor qilish
                    </button>
                </div>
            </form>
        </div>
    </div>

    <style>
    .modal-overlay {
        display: none;
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0, 0, 0, 0.85);
        backdrop-filter: blur(5px);
        z-index: 9999;
        padding: 2rem;
        overflow-y: auto;
        animation: fadeIn 0.3s;
    }
    .modal-overlay.active {
        display: flex;
        align-items: center;
        justify-content: center;
    }

    @keyframes fadeIn {
        from {opacity: 0;}
        to {opacity: 1;}
    }
    .modal-content {
        background: var(--bg-secondary);
        border-radius: 16px;
        max-width: 700px;
        width: 100%;
        border: 2px solid var(--accent);
        box-shadow: 0 20px 60px rgba(0, 217, 255, 0.4);
        animation: slideUp 0.3s;
        max-height: 90vh;
        overflow-y: auto;
    }

    @keyframes slideUp {
        from {transform: translateY(50px); opacity: 0;}
        to {transform: translateY(0); opacity: 1;}
    }
    .modal-header {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1.5rem 2rem;
        border-bottom: 2px solid var(--border);
        background: linear-gradient(135deg, rgba(0, 217, 255, 0.1), rgba(168, 85, 247, 0.1));
    }
    .modal-header h2 {
        color: var(--accent);
        font-family: 'Orbitron', sans-serif;
        font-size: 1.5rem;
        margin: 0;
    }
    .modal-close {
        background: none;
        border: none;
        color: var(--text);
        font-size: 1.5rem;
        cursor: pointer;
        padding: 0.5rem;
        transition: all 0.3s;
        border-radius: 8px;
    }
    .modal-close:hover {
        background: rgba(239, 68, 68, 0.2);
        color: #ef4444;
    }
    .modal-content form {
        padding: 2rem;
    }
    .modal-footer {
        display: flex;
        gap: 1rem;
        margin-top: 2rem;
        padding-top: 1.5rem;
        border-top: 2px solid var(--border);
    }
    .modal-footer .btn {
        flex: 1;
    }
    .btn-secondary {
        background: rgba(100, 100, 100, 0.3);
        border: 1px solid rgba(200, 200, 200, 0.2);
    }
    .btn-secondary:hover {
        background: rgba(100, 100, 100, 0.5);
    }
    .form-row {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 1rem;
    }

    .rank-category {
        margin-bottom: 2.5rem;
        padding: 2rem;
        background: linear-gradient(135deg, rgba(0, 217, 255, 0.05), rgba(168, 85, 247, 0.05));
        border-radius: 16px;
        border: 1px solid var(--border);
    }
    .rank-category h3 {
        color: var(--accent);
        margin-bottom: 1.5rem;
        font-size: 1.5rem;
        display: flex;
        align-items: center;
        gap: 1rem;
        font-family: 'Orbitron', sans-serif;
    }
    .rank-group {
        background: var(--card-bg);
        border: 2px solid var(--border);
        border-radius: 12px;
        padding: 1.5rem;
        margin-bottom: 1.5rem;
        transition: all 0.3s;
    }
    .rank-group:hover {
        transform: translateY(-3px);
        box-shadow: 0 10px 30px rgba(0, 217, 255, 0.2);
        border-color: var(--accent);
    }
    .rank-header {
        display: flex;
        justify-content: space-between;
        align-items: flex-start;
        margin-bottom: 1rem;
        padding-bottom: 1rem;
        border-bottom: 2px solid var(--border);
    }
    .rank-title {
        font-size: 1.8rem;
        font-weight: 700;
        font-family: 'Orbitron', sans-serif;
    }
    .variant-list {
        display: grid;
        gap: 0.8rem;
        margin-top: 1rem;
    }
    .variant-item {
        background: rgba(0, 217, 255, 0.05);
        padding: 1rem 1.5rem;
        border-radius: 8px;
        border: 1px solid var(--border);
        display: flex;
        justify-content: space-between;
        align-items: center;
        transition: all 0.3s;
    }
    .variant-item:hover {
        background: rgba(0, 217, 255, 0.1);
        border-color: var(--accent);
        transform: translateX(5px);
    }
    .variant-info {
        display: flex;
        gap: 2rem;
        align-items: center;
        flex: 1;
    }
    .variant-duration {
        font-weight: 600;
        color: var(--accent);
        min-width: 120px;
    }
    .variant-price {
        font-weight: 700;
        font-size: 1.3rem;
    }
    .variant-badge {
        padding: 0.3rem 0.8rem;
        border-radius: 20px;
        font-size: 0.75rem;
        font-weight: 700;
    }
    .variant-actions {
        display: flex;
        gap: 0.5rem;
    }
    .btn-icon {
        padding: 0.6rem 0.9rem;
        min-width: auto;
    }
    </style>

    <script>
    const categoryNames = {
        'anarchy': '⚔️ Anarxiya',
        'smp': '🌲 SMP',
        'keys': '🔑 Kalitlar',
        'services': '🛠️ Xizmatlar',
        'token': '🪙 Tokenlar'
    };

    let allPackages = [];
    let editMode = false;

    // Rang sinxronizatsiyasi
    document.getElementById('rankColorPicker').addEventListener('input', (e) => {
        document.getElementById('rankColor').value = e.target.value;
    });
    document.getElementById('rankColor').addEventListener('input', (e) => {
        const color = e.target.value;
        if (/^#[0-9A-F]{6}$/i.test(color)) {
            document.getElementById('rankColorPicker').value = color;
        }
    });

    async function loadRanks() {
        const res = await fetch('/api/packages');
        allPackages = await res.json();

        // Guruhlantirilgan ko'rinish
        const categories = {};
        allPackages.forEach(pkg => {
            if (!categories[pkg.category]) categories[pkg.category] = {};
            if (!categories[pkg.category][pkg.name]) categories[pkg.category][pkg.name] = [];
            categories[pkg.category][pkg.name].push(pkg);
        });

        const container = document.getElementById('ranksContainer');
        let html = '';

        for (const [category, ranks] of Object.entries(categories)) {
            const catName = categoryNames[category] || category.toUpperCase();
            const totalRanks = Object.keys(ranks).length;
            const totalVariants = Object.values(ranks).flat().length;

            html += `
            <div class="rank-category">
                <h3>
                    ${catName}
                    <span style="color:var(--text-dim);font-size:0.9rem;font-weight:400;margin-left:auto">
                        ${totalRanks} rank • ${totalVariants} variant
                    </span>
                </h3>`;

            for (const [rankName, variants] of Object.entries(ranks)) {
                const baseRank = variants[0];
                const features = baseRank.features ? baseRank.features.split(',') : [];

                html += `
                <div class="rank-group" style="border-color: ${baseRank.color}">
                    <div class="rank-header">
                        <div style="flex:1">
                            <div class="rank-title" style="color: ${baseRank.color}">
                                ${rankName}
                            </div>
                            <p style="color:var(--text-dim);font-size:0.9rem;margin:0.5rem 0 0 0">
                                ${baseRank.description || 'Tavsif kiritilmagan'}
                            </p>
                        </div>
                    </div>`;

                if (features.length > 0) {
                    html += `
                    <div style="margin-bottom:1rem">
                        <strong style="color:var(--accent);font-size:0.85rem;text-transform:uppercase;letter-spacing:1px">
                            <i class="fas fa-star"></i> Imkoniyatlar:
                        </strong>
                        <div style="display:flex;flex-wrap:wrap;gap:0.5rem;margin-top:0.5rem">
                            ${features.map(f => `
                                <span style="background:rgba(34,197,94,0.2);color:#22c55e;padding:0.3rem 0.8rem;border-radius:20px;font-size:0.8rem;border:1px solid #22c55e">
                                    <i class="fas fa-check"></i> ${f.trim()}
                                </span>
                            `).join('')}
                        </div>
                    </div>`;
                }

                html += `<div class="variant-list">`;

                variants.forEach(variant => {
                    const statusClass = variant.is_active ? 'badge-success' : 'badge-failed';
                    const statusText = variant.is_active ? '✅ Aktiv' : '❌ Nofaol';

                    html += `
                    <div class="variant-item">
                        <div class="variant-info">
                            <div class="variant-duration">
                                <i class="fas fa-clock"></i> ${variant.duration}
                            </div>
                            <div class="variant-price" style="color:${variant.color}">
                                ${variant.price.toLocaleString()} <span style="font-size:0.85rem;opacity:0.8">so'm</span>
                            </div>
                            <span class="variant-badge ${statusClass}">${statusText}</span>
                        </div>
                        <div class="variant-actions">
                            <button onclick="editRank(${variant.id})" class="btn btn-icon" title="Tahrirlash">
                                <i class="fas fa-edit"></i>
                            </button>
                            <button onclick="deleteRank(${variant.id}, '${variant.name}', '${variant.duration}')" class="btn btn-danger btn-icon" title="O'chirish">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    </div>`;
                });

                html += `</div></div>`;
            }

            html += `</div>`;
        }

        container.innerHTML = html || '<p style="text-align:center;color:var(--text-dim);padding:3rem">Hech qanday rank yo\'q</p>';
    }

    function showAddModal() {
        editMode = false;
        document.getElementById('modalTitle').innerHTML = '<i class="fas fa-plus-circle"></i> Yangi Rank Qo\'shish';
        document.getElementById('rankForm').reset();
        document.getElementById('rankId').value = '';
        document.getElementById('rankColorPicker').value = '#3b82f6';
        document.getElementById('rankColor').value = '#3b82f6';
        document.getElementById('rankModal').classList.add('active');
    }

    function editRank(id) {
        editMode = true;
        const pkg = allPackages.find(p => p.id === id);
        if (!pkg) return;

        document.getElementById('modalTitle').innerHTML = '<i class="fas fa-edit"></i> Rankni Tahrirlash';
        document.getElementById('rankId').value = pkg.id;
        document.getElementById('rankName').value = pkg.name;
        document.getElementById('rankCategory').value = pkg.category;
        document.getElementById('rankDesc').value = pkg.description || '';
        document.getElementById('rankPrice').value = pkg.price;
        document.getElementById('rankDuration').value = pkg.duration;
        document.getElementById('rankFeatures').value = pkg.features || '';
        document.getElementById('rankColor').value = pkg.color;
        document.getElementById('rankColorPicker').value = pkg.color;
        document.getElementById('rankActive').value = pkg.is_active ? '1' : '0';
        document.getElementById('rankModal').classList.add('active');
    }

    function closeModal() {
        document.getElementById('rankModal').classList.remove('active');
    }

    async function handleSubmit(e) {
        e.preventDefault();

        const data = {
            name: document.getElementById('rankName').value,
            category: document.getElementById('rankCategory').value,
            description: document.getElementById('rankDesc').value,
            price: parseFloat(document.getElementById('rankPrice').value),
            duration: document.getElementById('rankDuration').value,
            features: document.getElementById('rankFeatures').value,
            color: document.getElementById('rankColor').value,
            is_active: parseInt(document.getElementById('rankActive').value)
        };

        const id = document.getElementById('rankId').value;
        const url = editMode ? `/admin/edit_rank/${id}` : '/admin/add_rank';

        const res = await fetch(url, {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        });

        const result = await res.json();

        if (result.success) {
            closeModal();
            loadRanks();
            alert(result.message);
        } else {
            alert('Xatolik: ' + (result.message || 'Noma\'lum xatolik'));
        }

        return false;
    }

    async function deleteRank(id, name, duration) {
        if (!confirm(`"${name} (${duration})" ni o'chirishga ishonchingiz komilmi?`)) return;

        const res = await fetch(`/admin/delete_rank/${id}`, {method: 'POST'});
        const result = await res.json();

        if (result.success) {
            loadRanks();
            alert(result.message);
        } else {
            alert('Xatolik: ' + (result.message || 'Noma\'lum xatolik'));
        }
    }

    // ESC tugmasi bilan yopish
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeModal();
    });

    // Modal tashqarisiga bosish bilan yopish
    document.getElementById('rankModal').addEventListener('click', (e) => {
        if (e.target.id === 'rankModal') closeModal();
    });

    loadRanks();
    </script>
    """

    return render_page(content, logged_in=True, is_admin=True)


@app.route('/admin/add_rank', methods=['POST'])
@admin_required
def add_rank():
    data = request.get_json()
    conn = get_db()
    conn.execute("""INSERT INTO packages (category, name, description, price, duration, features, color, is_active)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
    (data.get('category'), data.get('name'), data.get('description', ''),
     data.get('price', 0), data.get('duration', ''), data.get('features', ''),
     data.get('color', '#3b82f6'), data.get('is_active', 1)))
    conn.commit()
    conn.close()
    return jsonify(success=True, message='Rank muvaffaqiyatli qo\'shildi!')


@app.route('/admin/edit_rank/<int:rank_id>', methods=['POST'])
@admin_required
def edit_rank(rank_id):
    data = request.get_json()
    conn = get_db()
    conn.execute("""UPDATE packages SET name=?, description=?, price=?, duration=?, features=?, color=?, category=?, is_active=? WHERE id=?""",
    (data.get('name'), data.get('description'), data.get('price'), data.get('duration'),
     data.get('features'), data.get('color'), data.get('category'), data.get('is_active', 1), rank_id))
    conn.commit()
    conn.close()
    return jsonify(success=True, message='Rank muvaffaqiyatli yangilandi!')


@app.route('/admin/delete_rank/<int:rank_id>', methods=['POST'])
@admin_required
def delete_rank(rank_id):
    conn = get_db()
    conn.execute('DELETE FROM packages WHERE id=?', (rank_id,))
    conn.commit()
    conn.close()
    return jsonify(success=True, message='Rank o\'chirildi!')


@app.route('/admin')
@admin_required
def admin_panel():
    conn = get_db()
    pending = conn.execute(
        'SELECT bd.*, u.username as uname, u.minecraft_nick as mc FROM balance_deposits bd JOIN users u ON bd.user_id=u.id WHERE bd.status=\'pending\' ORDER BY bd.created_at DESC').fetchall()
    total_users = conn.execute('SELECT COUNT(*) as c FROM users WHERE is_admin=0').fetchone()['c']
    total_deposits = conn.execute("SELECT COUNT(*) as c FROM balance_deposits WHERE status='approved'").fetchone()['c']
    total_purchases = conn.execute('SELECT COUNT(*) as c FROM purchases').fetchone()['c']
    total_revenue = conn.execute('SELECT COALESCE(SUM(amount),0) as s FROM purchases').fetchone()['s']
    open_tickets = conn.execute("SELECT COUNT(*) as c FROM support_tickets WHERE status='open'").fetchone()['c']
    conn.close()
    ph = ''
    for d in pending:
        ss = f'<a href="{d["screenshot"]}" target="_blank" class="btn btn-outline btn-sm"><i class="fas fa-image"></i></a>' if \
            d['screenshot'] else ''
        ph += f'<tr><td>#{d["id"]}</td><td><strong>{sanitize(d["uname"])}</strong><br/><span style="color:var(--text-dim);font-size:.8rem;">{sanitize(d["mc"] or "—")}</span></td><td>{d["amount"]:,.0f} so\'m</td><td>{sanitize(d["card_number"])}</td><td>{sanitize(d["transaction_id"])}</td><td>{str(d["created_at"])[:16]}</td><td style="display:flex;gap:.4rem;flex-wrap:wrap;">{ss}<button onclick="approveDeposit({d["id"]})" class="btn btn-primary btn-sm"><i class="fas fa-check"></i> Tasdiqlash</button><button onclick="rejectDeposit({d["id"]})" class="btn btn-danger btn-sm"><i class="fas fa-times"></i> Rad</button></td></tr>'
    if not ph:
        ph = '<tr><td colspan="7" style="text-align:center;color:var(--text-dim);padding:1.5rem;">Kutilayotgan to\'lovlar yo\'q</td></tr>'
    ot_badge = f'<span class="badge badge-open" style="font-size:.65rem;padding:.15rem .5rem;">{open_tickets}</span>' if open_tickets else ''
    content = f'''
    <div class="container" style="padding-top:2rem;">
        <div class="section-title"><h2>⚡ Admin Panel</h2></div>
        <div class="stats">
            <div class="stat-card"><i class="fas fa-users"></i><h3>{total_users}</h3><p>Foydalanuvchilar</p></div>
            <div class="stat-card"><i class="fas fa-check-circle"></i><h3>{total_deposits}</h3><p>Tasdiqlangan to'lovlar</p></div>
            <div class="stat-card"><i class="fas fa-shopping-cart"></i><h3>{total_purchases}</h3><p>Sotilgan paketlar</p></div>
            <div class="stat-card"><i class="fas fa-coins"></i><h3>{total_revenue:,.0f}</h3><p>Jami daromad</p></div>
        </div>
        <div class="tabs">
            <a href="/admin" class="tab active"><i class="fas fa-tachometer-alt"></i> Dashboard</a>
            <a href="/admin/news" class="tab"><i class="fas fa-newspaper"></i> Yangiliklar</a>
            <a href="/admin/deposits?status=all" class="tab"><i class="fas fa-credit-card"></i> To'lovlar</a>
            <a href="/admin/users" class="tab"><i class="fas fa-users"></i> Users</a>
            <a href="/admin/support" class="tab"><i class="fas fa-headset"></i> Support {ot_badge}</a>
            <a href="/admin/settings" class="tab"><i class="fas fa-cog"></i> Settings</a>
        </div>
        <div class="card">
            <div class="card-header"><i class="fas fa-hourglass-half"></i><h2>Kutilayotgan To'lovlar</h2></div>
            <div class="table-wrap"><table>
                <thead><tr><th>#</th><th>User</th><th>Summa</th><th>Karta</th><th>TXN</th><th>Sana</th><th>Amal</th></tr></thead>
                <tbody>{ph}</tbody>
            </table></div>
        </div>
    </div>'''
    return render_page(content, logged_in=True, is_admin=True)


@app.route('/admin/approve_deposit/<int:did>', methods=['POST'])
@admin_required
def approve_deposit(did):
    data = request.get_json(force=True, silent=True) or {}
    comment = sanitize(data.get('comment', ''))
    conn = get_db()
    dep = conn.execute('SELECT * FROM balance_deposits WHERE id=?', (did,)).fetchone()
    if dep and dep['status'] == 'pending':
        conn.execute('UPDATE users SET balance=balance+? WHERE id=?', (dep['amount'], dep['user_id']))
        conn.execute('UPDATE balance_deposits SET status=?,admin_comment=? WHERE id=?', ('approved', comment, did))
        conn.commit();
        conn.close()
        return jsonify(success=True, message="To'lov tasdiqlandi!")
    conn.close()
    return jsonify(success=False, message='Xatolik!')


@app.route('/admin/reject_deposit/<int:did>', methods=['POST'])
@admin_required
def reject_deposit(did):
    data = request.get_json(force=True, silent=True) or {}
    comment = sanitize(data.get('comment', ''))
    conn = get_db()
    dep = conn.execute('SELECT * FROM balance_deposits WHERE id=?', (did,)).fetchone()
    if dep and dep['status'] == 'pending':
        conn.execute('UPDATE balance_deposits SET status=?,admin_comment=? WHERE id=?', ('rejected', comment, did))
        conn.commit();
        conn.close()
        return jsonify(success=True, message="To'lov rad etildi!")
    conn.close()
    return jsonify(success=False, message='Xatolik!')


@app.route('/admin/deposits')
@admin_required
def admin_deposits():
    sf = request.args.get('status', 'all')
    conn = get_db()
    q = 'SELECT bd.*, u.username as uname FROM balance_deposits bd JOIN users u ON bd.user_id=u.id'
    params = []
    if sf != 'all': q += ' WHERE bd.status=?'; params.append(sf)
    q += ' ORDER BY bd.created_at DESC'
    deposits = conn.execute(q, params).fetchall()
    conn.close()
    rows = ''
    for d in deposits:
        sc = 'pending' if d['status'] == 'pending' else ('approved' if d['status'] == 'approved' else 'rejected')
        st = '⏳ Kutilmoqda' if d['status'] == 'pending' else (
            '✅ Tasdiqlandi' if d['status'] == 'approved' else '❌ Rad etildi')
        ss = f'<a href="{d["screenshot"]}" target="_blank" class="btn btn-outline btn-sm"><i class="fas fa-image"></i></a>' if \
            d['screenshot'] else ''
        rows += f'<tr><td>#{d["id"]}</td><td><strong>{sanitize(d["uname"])}</strong></td><td>{d["amount"]:,.0f} so\'m</td><td>{sanitize(d["card_number"])}</td><td><span class="badge badge-{sc}">{st}</span></td><td>{str(d["created_at"])[:16]}</td><td>{ss}</td></tr>'
    content = f'''
    <div class="container" style="padding-top:2rem;">
        <div class="section-title"><h2>💳 To'lovlar</h2></div>
        <div class="tabs">
            <a href="/admin" class="tab"><i class="fas fa-tachometer-alt"></i> Dashboard</a>
            <a href="/admin/deposits?status=all" class="tab {'active' if sf == 'all' else ''}">Barchasi</a>
            <a href="/admin/deposits?status=pending" class="tab {'active' if sf == 'pending' else ''}">⏳ Kutilmoqda</a>
            <a href="/admin/deposits?status=approved" class="tab {'active' if sf == 'approved' else ''}">✅ Tasdiqlangan</a>
            <a href="/admin/deposits?status=rejected" class="tab {'active' if sf == 'rejected' else ''}">❌ Rad etilgan</a>
        </div>
        <div class="card"><div class="table-wrap"><table>
            <thead><tr><th>#</th><th>User</th><th>Summa</th><th>Karta</th><th>Status</th><th>Sana</th><th>Screenshot</th></tr></thead>
            <tbody>{rows or '<tr><td colspan="7" style="text-align:center;color:var(--text-dim);padding:1.5rem;">Malumotlar yoq</td></tr>'}</tbody>
        </table></div></div>
    </div>'''
    return render_page(content, logged_in=True, is_admin=True)


@app.route('/admin/users')
@admin_required
def admin_users():
    conn = get_db()
    users = conn.execute('SELECT * FROM users ORDER BY created_at DESC').fetchall()
    conn.close()
    rows = ''
    for u in users:
        rows += f'<tr><td>#{u["id"]}</td><td><strong>{sanitize(u["username"])}</strong></td><td>{sanitize(u["minecraft_nick"] or "—")}</td><td>{u["balance"]:,} so\'m</td><td><div style="display:flex;gap:5px;align-items:center;"><input type="number" id="bal_{u["id"]}" placeholder="Balans" style="width:90px;padding:.4rem .5rem;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.1);border-radius:6px;color:var(--text);font-size:.82rem;"><button class="btn btn-primary btn-sm" onclick="updateBal({u["id"]})" style="padding:.35rem .7rem;"><i class="fas fa-check"></i></button><button class="btn btn-danger btn-sm" onclick="setZero({u["id"]})" style="padding:.35rem .7rem;"><i class="fas fa-trash"></i></button></div></td></tr>'
    content = f'''
    <div class="container" style="padding-top:2rem;">
        <div class="section-title"><h2>👥 Foydalanuvchilar</h2></div>
        <div class="tabs"><a href="/admin" class="tab"><i class="fas fa-tachometer-alt"></i> Dashboard</a><a href="/admin/users" class="tab active"><i class="fas fa-users"></i> Users</a></div>
        <div class="card"><div class="table-wrap"><table>
            <thead><tr><th>ID</th><th>Username</th><th>MC Nick</th><th>Balans</th><th>Balans Tahrir</th></tr></thead>
            <tbody>{rows}</tbody>
        </table></div></div>
    </div>
    <script>
    async function updateBal(uid){{
        const val=document.getElementById('bal_'+uid).value;
        if(val==='') return showToast('Qiymat kiriting!','error');
        const r=await fetch('/admin/update_balance',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:'user_id='+uid+'&new_balance='+val}});
        if(r.ok){{showToast('Balans yangilandi!');location.reload();}}
    }}
    async function setZero(uid){{
        if(!confirm('Balansni 0 qilishga ishonchingiz komilmi?')) return;
        const r=await fetch('/admin/update_balance',{{method:'POST',headers:{{'Content-Type':'application/x-www-form-urlencoded'}},body:'user_id='+uid+'&new_balance=0'}});
        if(r.ok){{showToast('Balans 0 qilib qo\\'yildi!');location.reload();}}
    }}
    </script>'''
    return render_page(content, logged_in=True, is_admin=True)


@app.route('/admin/update_balance', methods=['POST'])
@admin_required
def update_balance():
    user_id = request.form.get('user_id')
    new_balance = request.form.get('new_balance')
    if user_id and new_balance is not None:
        conn = get_db()
        conn.execute('UPDATE users SET balance=? WHERE id=?', (new_balance, user_id))
        conn.commit();
        conn.close()
    return redirect(url_for('admin_users'))


@app.route('/admin/support')
@admin_required
def admin_support_list():
    conn = get_db()
    tickets = conn.execute(
        "SELECT st.*, u.username as uname FROM support_tickets st JOIN users u ON st.user_id=u.id ORDER BY CASE WHEN st.status='open' THEN 0 WHEN st.status='answered' THEN 1 ELSE 2 END, st.created_at DESC").fetchall()
    conn.close()
    lh = ''
    for t in tickets:
        bc = 'badge-open' if t['status'] == 'open' else (
            'badge-answered' if t['status'] == 'answered' else 'badge-closed')
        lb = 'Ochiq' if t['status'] == 'open' else ('Javob berildi' if t['status'] == 'answered' else 'Yopilgan')
        lh += f'<a href="/support/{t["id"]}" class="ticket-row" style="text-decoration:none;"><div class="ticket-row-left"><span class="ticket-id">#{t["id"]}</span><div><div class="ticket-subject">{sanitize(t["subject"])}</div><div class="ticket-meta"><i class="fas fa-user"></i> {sanitize(t["uname"])} • <i class="fas fa-clock"></i> {str(t["created_at"])[:16]}</div></div></div><div class="ticket-row-right"><span class="badge {bc}">{lb}</span><span class="btn btn-primary btn-sm"><i class="fas fa-reply"></i> Javob</span></div></a>'
    if not lh:
        lh = '<div style="text-align:center;color:var(--text-dim);padding:2.5rem;"><i class="fas fa-check-circle" style="font-size:2rem;color:var(--success);margin-bottom:.6rem;display:block;"></i>Barcha murojaatlar hal qilib tashlangan!</div>'
    content = f'''
    <div class="container" style="max-width:860px;margin:0 auto;padding-top:2rem;">
        <div class="section-title"><h2>⚡ Admin Support</h2></div>
        <div class="tabs"><a href="/admin" class="tab"><i class="fas fa-tachometer-alt"></i> Dashboard</a><a href="/admin/support" class="tab active"><i class="fas fa-headset"></i> Support</a></div>
        <div class="card"><div class="support-list">{lh}</div></div>
    </div>'''
    return render_page(content, logged_in=True, is_admin=True)


@app.route('/admin/edit_rank/<int:rank_id>', methods=['POST'])
@admin_required
def admin_edit_rank(rank_id):
    try:
        data = request.get_json()
        conn = get_db()
        conn.execute('''UPDATE packages SET 
                        name=?, description=?, price=?, 
                        duration=?, features=?, color=?, 
                        category=?, is_active=?
                        WHERE id=?''',
                     (data['name'], data['description'], data['price'],
                      data['duration'], data['features'], data['color'],
                      data['category'], data.get('is_active', 1), rank_id))
        conn.commit()
        conn.close()
        return jsonify(success=True, message='Rank yangilandi!')
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@app.route('/admin/delete_rank/<int:rank_id>', methods=['POST'])
@admin_required
def admin_delete_rank(rank_id):
    try:
        conn = get_db()
        conn.execute('DELETE FROM packages WHERE id=?', (rank_id,))
        conn.commit()
        conn.close()
        return jsonify(success=True, message='Rank o\'chirildi!')
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@app.route('/admin/add_rank', methods=['POST'])
@admin_required
def admin_add_rank():
    try:
        data = request.get_json()
        conn = get_db()
        conn.execute('''INSERT INTO packages 
                        (category, name, description, price, duration, features, color, is_active)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                     (data['category'], data['name'], data['description'],
                      data['price'], data['duration'], data['features'],
                      data.get('color', '#3b82f6'), data.get('is_active', 1)))
        conn.commit()
        conn.close()
        return jsonify(success=True, message='Rank qo\'shildi!')
    except Exception as e:
        return jsonify(success=False, message=str(e)), 500


@app.route('/admin/settings', methods=['GET', 'POST'])
@admin_required
def admin_settings():
    conn = get_db()
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        for k, v in data.items():
            conn.execute('INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)', (sanitize(k), sanitize(v)))
        conn.commit()
        conn.close()
        return jsonify(success=True, message='Saqlandi!')

    settings = {r['key']: r['value'] for r in conn.execute('SELECT key,value FROM settings').fetchall()}
    conn.close()

    def inp(name, typ='text', ph=''):
        val = settings.get(name, '')
        return f'<input type="{typ}" name="{name}" value="{sanitize(val)}" form="settingsForm" placeholder="{ph}">'

    content = f'''
    <div class="container" style="max-width:800px;margin:0 auto;padding-top:2rem;">
        <div class="section-title"><h2>⚙️ Sozlamalar</h2></div>
<div class="card">
                <div class="card-header"><i class="fas fa-crown"></i><h2>Ranklar Boshqaruvi</h2></div>
                <div id="ranksContainer" style="max-height:500px;overflow-y:auto;"></div>
                <button onclick="showAddRankModal()" class="btn btn-success" style="width:100%;margin-top:1rem;">
                    <i class="fas fa-plus"></i> Yangi Rank Qo'shish
                </button>
            </div>
        <form id="settingsForm">
        <div class="card">
                <div class="card-header"><i class="fas fa-crown"></i><h2>Ranklar Boshqaruvi</h2></div>
                <div id="ranksContainer"></div>
                <button onclick="showAddRankModal()" class="btn btn-success" style="width:100%;margin-top:1rem;">
                    <i class="fas fa-plus"></i> Yangi Rank Qo'shish
                </button>
            </div>
        </form>
        <script>
        async function loadRanks() {{
            const res = await fetch('/api/packages');
            const data = await res.json();
            const container = document.getElementById('ranksContainer');

            let html = '';
            for(let pkg of data) {{
                const badge = pkg.is_active ? '<span style="color:green;font-weight:bold;">✓ Aktiv</span>' : '<span style="color:red;font-weight:bold;">✗ Nofaol</span>';
                html += `
                    <div style="border-bottom:1px solid var(--border);padding:1rem;background:var(--card-bg);margin-bottom:0.5rem;border-radius:8px;">
                        <div style="display:flex;justify-content:space-between;align-items:start;">
                            <div style="flex:1;">
                                <div style="font-size:1.1rem;font-weight:bold;color:${{pkg.color}};">${{pkg.name}}</div>
                                <div style="color:var(--text-dim);font-size:0.85rem;margin-top:0.2rem;">
                                    <i class="fas fa-tag"></i> ${{pkg.category}} • ${{badge}}
                                </div>
                                <div style="margin-top:0.5rem;color:var(--text);">${{pkg.description}}</div>
                                <div style="margin-top:0.3rem;">
                                    <span style="color:var(--primary);font-weight:bold;">${{pkg.price.toLocaleString()}} so'm</span>
                                    <span style="color:var(--text-dim);margin-left:1rem;">⏱ ${{pkg.duration}}</span>
                                </div>
                            </div>
                            <div style="display:flex;gap:0.5rem;">
                                <button onclick="editRank(${{pkg.id}})" class="btn btn-sm" style="background:var(--primary);">
                                    <i class="fas fa-edit"></i> Tahrirlash
                                </button>
                                <button onclick="deleteRank(${{pkg.id}}, '${{pkg.name}}')" class="btn btn-sm" style="background:var(--danger);">
                                    <i class="fas fa-trash"></i>
                                </button>
                            </div>
                        </div>
                    </div>`;
            }}
            container.innerHTML = html || '<p style="text-align:center;color:var(--text-dim);padding:2rem;">Hech qanday rank mavjud emas</p>';
        }}

        async function editRank(id) {{
            const res = await fetch('/api/packages');
            const data = await res.json();
            const pkg = data.find(p => p.id === id);
            if(!pkg) return alert('Rank topilmadi!');

            const newName = prompt('Rank nomi:', pkg.name);
            if(!newName) return;

            const newDesc = prompt('Tavsif:', pkg.description);
            if(newDesc === null) return;

            const newPrice = prompt('Narxi (so\\'m):', pkg.price);
            if(newPrice === null) return;

            const newDuration = prompt('Muddati:', pkg.duration);
            if(newDuration === null) return;

            const newFeatures = prompt('Imkoniyatlar (vergul bilan):', pkg.features);
            if(newFeatures === null) return;

            const newColor = prompt('Rang kodi (masalan: #3b82f6):', pkg.color);
            if(newColor === null) return;

            const newCategory = prompt('Kategoriya (anarchy/smp/keys/services/token):', pkg.category);
            if(newCategory === null) return;

            const isActive = confirm('Rank aktiv bo\\'lsinmi?') ? 1 : 0;

            const response = await fetch(`/admin/edit_rank/${{id}}`, {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    name: newName,
                    description: newDesc,
                    price: parseFloat(newPrice),
                    duration: newDuration,
                    features: newFeatures,
                    color: newColor,
                    category: newCategory,
                    is_active: isActive
                }})
            }});

            const result = await response.json();
            alert(result.message);
            if(result.success) loadRanks();
        }}

        async function deleteRank(id, name) {{
            if(!confirm(`"${{name}}" rankini o'chirib tashlashga ishonchingiz komilmi?\\n\\nBu amalni qaytarib bo'lmaydi!`)) return;

            const response = await fetch(`/admin/delete_rank/${{id}}`, {{
                method: 'POST'
            }});

            const result = await response.json();
            alert(result.message);
            if(result.success) loadRanks();
        }}

        async function showAddRankModal() {{
            const name = prompt('Rank nomi:');
            if(!name) return;

            const description = prompt('Tavsif:');
            if(!description) return;

            const price = prompt('Narxi (so\\'m):');
            if(!price) return;

            const duration = prompt('Muddati (masalan: 30 kun):');
            if(!duration) return;

            const features = prompt('Imkoniyatlar (vergul bilan ajratilgan):');
            if(!features) return;

            const color = prompt('Rang kodi (masalan: #3b82f6):', '#3b82f6');
            const category = prompt('Kategoriya (anarchy/smp/keys/services/token):', 'anarchy');

            const response = await fetch('/admin/add_rank', {{
                method: 'POST',
                headers: {{'Content-Type': 'application/json'}},
                body: JSON.stringify({{
                    name, description, 
                    price: parseFloat(price), 
                    duration, features, 
                    color: color || '#3b82f6', 
                    category: category || 'anarchy',
                    is_active: 1
                }})
            }});

            const result = await response.json();
            alert(result.message);
            if(result.success) loadRanks();
        }}

        document.addEventListener('DOMContentLoaded', loadRanks);
        </script>

        <button onclick="saveSettings()" class="btn btn-primary btn-full" style="margin-bottom:3rem;">Saqlash</button>
    </div>

    <script>
    // Ranklar ro'yxatini yuklash
    async function loadRanks() {{
        const res = await fetch('/api/packages');
        const data = await res.json();
        const container = document.getElementById('ranksContainer');

        let html = '';
        for(let pkg of data) {{
            const badge = pkg.is_active ? '<span style="color:green;">✓ Aktiv</span>' : '<span style="color:red;">✗ O\'chirilgan</span>';
            html += `
                <div style="border-bottom:1px solid var(--border);padding:1rem 0;">
                    <div style="display:flex;justify-content:space-between;align-items:start;">
                        <div>
                            <strong>${{pkg.name}}</strong> <small>(${{pkg.category}})</small> ${{badge}}
                            <div style="color:var(--text-dim);font-size:0.9rem;">${{pkg.description}}</div>
                            <div style="color:var(--primary);margin-top:0.3rem;">${{pkg.price}} so'm</div>
                        </div>
                        <div>
                            <button onclick="editRank(${{pkg.id}})" class="btn btn-sm" style="margin-right:0.5rem;">
                                <i class="fas fa-edit"></i>
                            </button>
                            <button onclick="deleteRank(${{pkg.id}}, '${{pkg.name}}')" class="btn btn-sm" style="background:var(--danger);">
                                <i class="fas fa-trash"></i>
                            </button>
                        </div>
                    </div>
                </div>`;
        }}
        container.innerHTML = html || '<p style="text-align:center;color:var(--text-dim);padding:2rem;">Hech qanday rank yo\'q</p>';
    }}

    // Rankni tahrirlash
    async function editRank(id) {{
        const res = await fetch('/api/packages');
        const data = await res.json();
        const pkg = data.find(p => p.id === id);

        const newName = prompt('Rank nomi:', pkg.name);
        if(!newName) return;

        const newDesc = prompt('Tavsifi:', pkg.description);
        const newPrice = prompt('Narxi (so\'m):', pkg.price);
        const newDuration = prompt('Davomiyligi:', pkg.duration);
        const newFeatures = prompt('Imkoniyatlar (vergul bilan):', pkg.features);
        const newColor = prompt('Rang (hex):', pkg.color);
        const newCategory = prompt('Kategoriya (anarchy/smp/keys/services/token):', pkg.category);
        const isActive = confirm('Aktiv bo\'lsinmi?') ? 1 : 0;

        const response = await fetch(`/admin/edit_rank/${{id}}`, {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify({{
                name: newName,
                description: newDesc || pkg.description,
                price: parseFloat(newPrice) || pkg.price,
                duration: newDuration || pkg.duration,
                features: newFeatures || pkg.features,
                color: newColor || pkg.color,
                category: newCategory || pkg.category,
                is_active: isActive
            }})
        }});

        const result = await response.json();
        alert(result.message);
        if(result.success) loadRanks();
    }}

    // Rankni o'chirish
    async function deleteRank(id, name) {{
        if(!confirm(`"${{name}}" rankni o'chirishga ishonchingiz komilmi?`)) return;

        const response = await fetch(`/admin/delete_rank/${{id}}`, {{
            method: 'POST'
        }});

        const result = await response.json();
        alert(result.message);
        if(result.success) loadRanks();
    }}

    // Yangi rank qo'shish
    function showAddRankModal() {{
        const name = prompt('Rank nomi:');
        if(!name) return;

        const description = prompt('Tavsifi:');
        const price = prompt('Narxi (so\'m):');
        const duration = prompt('Davomiyligi (masalan: 30 kun):');
        const features = prompt('Imkoniyatlar (vergul bilan ajratilgan):');
        const color = prompt('Rang (hex, masalan #3b82f6):', '#3b82f6');
        const category = prompt('Kategoriya (anarchy/smp/keys/services/token):', 'anarchy');

        addRank({{
            name, description, price: parseFloat(price), duration, features, color, category
        }});
    }}

    async function addRank(data) {{
        const response = await fetch('/admin/add_rank', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/json'}},
            body: JSON.stringify(data)
        }});

        const result = await response.json();
        alert(result.message);
        if(result.success) loadRanks();
    }}


    loadRanks();
    </script>
            <div class="card">
                <div class="card-header"><h2>Trayler Sozlamalari</h2></div>
                <div class="form-group"><label>Trayler ko'rsatilsinmi?</label>
                    <select name="show_trailer" form="settingsForm">
                        <option value="1" {'selected' if settings.get('show_trailer') == '1' else ''}>Ha</option>
                        <option value="0" {'selected' if settings.get('show_trailer') == '0' else ''}>Yo'q</option>
                    </select>
                </div>
                <div class="form-group"><label>YouTube Embed URL</label>{inp('trailer_url')}</div>
            </div>

            <div class="card">
                <div class="card-header"><i class="fas fa-skull"></i><h2>Anarxiya RCON</h2></div>
                <div class="form-group"><label>Host</label>{inp('anarchy_rcon_host')}</div>
                <div class="form-group"><label>Port</label>{inp('anarchy_rcon_port', 'number')}</div>
                <div class="form-group"><label>Parol</label>{inp('anarchy_rcon_password', 'password')}</div>
            </div>

            <div class="card">
                <div class="card-header"><i class="fas fa-tree"></i><h2>SMP RCON</h2></div>
                <div class="form-group"><label>Host</label>{inp('smp_rcon_host')}</div>
                <div class="form-group"><label>Port</label>{inp('smp_rcon_port', 'number')}</div>
                <div class="form-group"><label>Parol</label>{inp('smp_rcon_password', 'password')}</div>
            </div>
            <div class="card">
                <div class="card-header"><i class="fas fa-music"></i><h2>Media</h2></div>
                <div class="form-group"><label>Musiqa URL</label>{inp('music_url')}</div>
                <div class="form-group"><label>Musiqa yoqilgan?</label>
                    <select name="music_enabled" form="settingsForm">
                        <option value="1" {'selected' if settings.get('music_enabled') == '1' else ''}>Ha</option>
                        <option value="0" {'selected' if settings.get('music_enabled') == '0' else ''}>Yo'q</option>
                    </select>
                </div>
            </div>
        </form>

        <button onclick="saveSettings()" class="btn btn-primary btn-full" style="margin-bottom:3rem;">Saqlash</button>
    </div>'''
    return render_page(content, logged_in=True, is_admin=True)


# ═══════════════════════════════════════════════
# STATIC / API / ENTRY
# ═══════════════════════════════════════════════

@app.route('/static/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/api/packages')
def api_packages():
    conn = get_db()
    packages = [dict(row) for row in conn.execute('SELECT * FROM packages').fetchall()]
    conn.close()
    return jsonify(packages)


@app.route('/api/stats')
def api_stats():
    conn = get_db()
    tu = conn.execute('SELECT COUNT(*) as c FROM users WHERE is_admin=0').fetchone()['c']
    tp = conn.execute('SELECT COUNT(*) as c FROM purchases').fetchone()['c']
    tr = conn.execute('SELECT COALESCE(SUM(amount),0) as s FROM purchases').fetchone()['s']
    conn.close()
    return jsonify(total_users=tu, total_purchases=tp, total_revenue=tr)


# ---------------------------------------------------
#  API - SERVERDAN STATISTIKANI QABUL QILISH UCHUN
# ---------------------------------------------------
@app.route('/api/update_stats', methods=['POST'])
def update_player_stats():
    SECRET_TOKEN = "ssmernix_legend_teams"

    try:
        data = request.get_json(force=True, silent=True)

        if not data or data.get('token') != SECRET_TOKEN:
            return jsonify(success=False, message="Xato token!")

        nick = data.get('nick')
        srv = data.get('server')
        kills = int(data.get('kills', 0))
        deaths = int(data.get('deaths', 0))
        time_played = data.get('time_played', '0h')
        money = float(data.get('money', 0))

        if not nick or not srv:
            return jsonify(success=False, message="Nik yoki Server turi yo'q")

        conn = get_db()
        # Bazaga yozish (agar bor bo'lsa yangilash, yo'q bo'lsa yaratish)
        conn.execute('''INSERT INTO player_stats (minecraft_nick, server_type, kills, deaths, time_played, money)
                        VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(minecraft_nick, server_type) 
                        DO
        UPDATE SET
            kills=?,
            deaths=?,
            time_played=?,
            money=?,
            last_updated= CURRENT_TIMESTAMP''',
                     (nick, srv, kills, deaths, time_played, money,
                      kills, deaths, time_played, money))
        conn.commit()
        conn.close()
        return jsonify(success=True, message="Statistika yangilandi")

    except Exception as e:
        return jsonify(success=False, error=str(e))


# Database yaratish (agar yo'q bo'lsa)
if not os.path.exists('elitemc.db'):
    print("=" * 62)
    print("  🔄 DATABASE YARATILMOQDA...")
    print("=" * 62)
    init_db()
    print("  ✅ DATABASE TAYYOR!")
    print("=" * 62)

# ═══════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════

if __name__ == '__main__':
    # Faqat local test uchun
    port = int(os.environ.get("PORT", 5000))
    
    print("=" * 62)
    print("  🎮  EliteMC.uz — Ultra Premium Donate Platform")
    print("=" * 62)
    print(f"  📍 URL          : http://0.0.0.0:{port}")
    print(f"  👤 Admin        : admin / ssmertnix_legend")
    print("=" * 62)

    socketio.run(app, host='0.0.0.0', port=port, debug=False)
else:
    # Gunicorn uchun (production)
    print("🚀 Production mode - Gunicorn")False)

