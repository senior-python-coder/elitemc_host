from flask import Flask, request, jsonify, redirect, url_for, session, send_from_directory
from flask_socketio import SocketIO, emit, join_room, leave_room
import sqlite3
import secrets
import hashlib
import datetime
import os
import html as html_module
from functools import wraps
from werkzeug.utils import secure_filename


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


def allowed_file(filename: str) -> bool:
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


def get_db():
    """Return a fresh SQLite connection with row_factory."""
    conn = sqlite3.connect('elitemc.db')
    conn.row_factory = sqlite3.Row
    return conn


def dict_from_row(row):
    """Safely convert a sqlite3.Row to dict."""
    return dict(row) if row else {}


def sanitize(text: str) -> str:
    """HTML-escape user input to prevent XSS."""
    return html_module.escape(str(text))




def give_rank_to_player(minecraft_nick: str, rank_name: str):
    if not MCRCON_AVAILABLE:
        return False, "mcrcon package is not installed."
    try:
        conn = get_db()
        settings = {r['key']: r['value'] for r in conn.execute('SELECT key, value FROM settings').fetchall()}
        conn.close()
        with MCRcon(
            settings.get('rcon_host', 'localhost'),
            settings.get('rcon_password', ''),
            port=int(settings.get('rcon_port', '25575'))
        ) as mcr:
            response = mcr.command(f"lp user {minecraft_nick} parent set {rank_name}")
            return True, response
    except Exception as e:
        return False, str(e)


def init_db():
    conn = get_db()
    c = conn.cursor()

    # 1. Jadvallarni yaratish
    c.execute('''CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, email TEXT UNIQUE, password TEXT, balance REAL DEFAULT 0, tokens INTEGER DEFAULT 0, is_admin BOOLEAN DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS packages (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, description TEXT, price REAL, duration TEXT, features TEXT, color TEXT DEFAULT '#3b82f6', is_active BOOLEAN DEFAULT 1)''')
    c.execute('''CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT UNIQUE, value TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS news (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, content TEXT, image TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS purchases (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, package_id INTEGER, amount REAL, package_name TEXT, minecraft_nick TEXT, status TEXT DEFAULT 'completed', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS balance_deposits (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, amount REAL, card_number TEXT, transaction_id TEXT, screenshot TEXT, status TEXT DEFAULT 'pending', admin_comment TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS support_tickets (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, subject TEXT, status TEXT DEFAULT 'open', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS support_messages (id INTEGER PRIMARY KEY AUTOINCREMENT, ticket_id INTEGER, user_id INTEGER, message TEXT, is_admin_reply BOOLEAN DEFAULT 0, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')


    admin_pw = hashlib.sha256('ssmertnix_legend'.encode()).hexdigest()
    c.execute('INSERT OR IGNORE INTO users (username, email, password, is_admin) VALUES (?, ?, ?, ?)',
              ('admin', 'admin@elitemc.uz', admin_pw, 1))

    # 3. Ranklarni (33 ta tarif) qo'shish
    c.execute('DELETE FROM packages')
    ranks_data = [
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
        ('SMP+', 'SMP serveri uchun', 20000, 35000, 50000, 'SMP+ kitlari', '#00ff88'),
    ]

    for name, desc, p30, p90, pUmr, feat, col in ranks_data:
        c.execute('INSERT INTO packages (name, description, price, duration, features, color) VALUES (?,?,?,?,?,?)', (name, desc, p30, '30', feat, col))
        c.execute('INSERT INTO packages (name, description, price, duration, features, color) VALUES (?,?,?,?,?,?)', (name, desc, p90, '90', feat, col))
        c.execute('INSERT INTO packages (name, description, price, duration, features, color) VALUES (?,?,?,?,?,?)', (name, desc, pUmr, 'UMRBOT', feat, col))

    # 4. Defaults
    defaults = [
        ('admin_card_number', '8600 1234 5678 9012'),
        ('admin_card_name', 'ADMIN ADMINOV'),
        ('site_name', 'EliteMC.uz'),
        ('server_ip', 'mc.elitemc.uz'),
        ('rcon_host', 'localhost'),
        ('rcon_port', '25575'),
        ('rcon_password', 'password'),
        ('trailer_url', 'https://www.youtube.com/embed/pC8FVFj7NFk'),
        ('show_trailer', '1'),
        ('discord_link', 'https://discord.com/invite/EbJ2cpkwuZ'),
        ('instagram_link', 'https://instagram.com/soon'),
        ('telegram_link', 'https://t.me/EliteMcChannel'),
        ('youtube_link', 'https://youtube.com/@ssmertnix'),
        ('online_players', '124'),
        ('server_version', '1.13 - 1.21.x'),
        ('token_price', '1.2')
    ]
    for k, v in defaults:
        c.execute('INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)', (k, v))

    conn.commit()
    conn.close()


# ═══════════════════════════════════════════════
# AUTH DECORATORS
# ═══════════════════════════════════════════════

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
# GLOBAL CSS + HTML SHELL  (render_page)
# ═══════════════════════════════════════════════

def render_page(body_content: str, **kwargs) -> str:
    conn = get_db()
    settings = {r['key']: r['value'] for r in conn.execute('SELECT key,value FROM settings').fetchall()}
    conn.close()

    # ── nav user section ──
    if kwargs.get('logged_in'):
        nav_user = f"""
            <li><a href="/support"><i class="fas fa-headset"></i> Support</a></li>
            <li><a href="/balance"><i class="fas fa-wallet"></i> Balans</a></li>
            <li><a href="/profile"><i class="fas fa-user-circle"></i> Profil</a></li>
            {'<li><a href="/admin"><i class="fas fa-bolt"></i> Admin</a></li>' if kwargs.get('is_admin') else ''}
            <li><a href="/logout" class="nav-logout"><i class="fas fa-sign-out-alt"></i> Chiqish</a></li>
        """
    else:
        nav_user = """
            <li><a href="/login" class="btn-nav btn-nav-outline"><i class="fas fa-sign-in-alt"></i> Kirish</a></li>
            <li><a href="/register" class="btn-nav btn-nav-primary"><i class="fas fa-user-plus"></i> Ro'yxat</a></li>
        """

    return f'''<!DOCTYPE html>
<html lang="uz">
<head>
<meta charset="UTF-8">
<link href="https://fonts.googleapis.com/css2?family=Montserrat:wght@400;700&family=Poppins:wght@300;600&display=swap" rel="stylesheet">
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1.0"/>
<title>EliteMC — Uzbekistandagi N1 Minecraft SERVER</title>
<link href="https://fonts.googleapis.com/css2?family=Orbitron:wght@400;700;900&family=Rajdhani:wght@300;400;500;600;700&family=Space+Grotesk:wght@300;400;500;600;700&display=swap" rel="stylesheet"/>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css"/>
<style>
    .animated-info {{ display: flex; justify-content: center; gap: 1rem; flex-wrap: wrap; margin-top: 2rem; }}
    .info-badge {{
        background: rgba(0, 255, 136, 0.1); border: 1px solid var(--primary);
        padding: 0.6rem 1.2rem; border-radius: 50px; font-weight: 700; color: var(--primary);
        animation: floatBadge 3s infinite ease-in-out; text-transform: uppercase; letter-spacing: 1px;
    }}
    .info-badge:nth-child(2) {{ animation-delay: 0.5s; border-color: var(--secondary); color: var(--secondary); }}
    .info-badge:nth-child(3) {{ animation-delay: 1s; border-color: var(--accent); color: var(--accent); }}
    @keyframes floatBadge {{ 0%, 100% {{ transform: translateY(0); }} 50% {{ transform: translateY(-10px); }} }}
    .glitch-text {{ font-family: 'Orbitron', sans-serif; font-size: clamp(3rem, 8vw, 5rem); text-shadow: 0 0 20px var(--primary); margin-bottom: 1rem; color: #fff; }}
    
    
    

/* ═══════════ RESET & ROOT ═══════════ */
:root {{
    --primary:#00ff88; --primary-dim:rgba(0,255,136,.35); --primary-glow:rgba(0,255,136,.55);
    --secondary:#0099ff; --accent:#ff0099; --accent2:#a855f7;
    --dark:#060a16; --dark-card:rgba(14,18,34,.85); --dark-card-solid:#0e1222;
    --dark-hover:#141b2e; --glass:rgba(20,26,48,.55);
    --text:#dce4f0; --text-dim:#6b7a9a; --text-bright:#fff;
    --success:#00ff88; --warning:#ffaa00; --danger:#ff3366;
    --radius:16px; --radius-sm:10px; --radius-lg:24px;
    --shadow:0 8px 40px rgba(0,0,0,.5);
    --glow-green:0 0 30px rgba(0,255,136,.3);
    --glow-blue:0 0 30px rgba(0,153,255,.3);
    --transition:.3s cubic-bezier(.4,0,.2,1);
}}
*{{margin:0;padding:0;box-sizing:border-box;}}
html{{scroll-behavior:smooth;}}
body{{
    font-family:'Rajdhani',sans-serif;
    background:var(--dark);color:var(--text);
    line-height:1.6;overflow-x:hidden;min-height:100vh;
}}
/* ── Animated background grid ── */
body::before{{
    content:'';position:fixed;inset:0;z-index:0;pointer-events:none;
    background-image:
        linear-gradient(rgba(0,255,136,.025) 1px,transparent 1px),
        linear-gradient(90deg,rgba(0,255,136,.025) 1px,transparent 1px);
    background-size:60px 60px;
    animation:gridDrift 25s linear infinite;
}}
@keyframes gridDrift{{to{{background-position:60px 60px;}}}}

/* ── Ambient orbs ── */
.orb{{position:fixed;border-radius:50%;pointer-events:none;z-index:0;filter:blur(90px);opacity:.18;animation:orbFloat 18s ease-in-out infinite alternate;}}
.orb-1{{width:500px;height:500px;background:#00ff88;top:-100px;left:-150px;}}
.orb-2{{width:400px;height:400px;background:#0099ff;bottom:-80px;right:-120px;animation-delay:4s;}}
.orb-3{{width:300px;height:300px;background:#a855f7;top:50%;left:50%;transform:translate(-50%,-50%);animation-delay:8s;}}
@keyframes orbFloat{{0%{{transform:scale(1) translate(0,0);}}100%{{transform:scale(1.3) translate(30px,-40px);}}}}

/* ══════════ LAYOUT ══════════ */
main{{position:relative;z-index:2;padding-top:80px;min-height:100vh;}}
.container{{max-width:1320px;margin:0 auto;padding:0 1.5rem;}}

/* ══════════ NAVIGATION ══════════ */
nav{{
    position:fixed;top:0;left:0;width:100%;z-index:9999;
    background:rgba(6,10,22,.8);backdrop-filter:blur(24px);-webkit-backdrop-filter:blur(24px);
    border-bottom:1px solid rgba(0,255,136,.12);
    box-shadow:0 4px 32px rgba(0,0,0,.6);
    transition:var(--transition);
}}
nav .container{{display:flex;justify-content:space-between;align-items:center;padding:1rem 1.5rem;}}
.logo{{
    font-family:'Orbitron',sans-serif;font-size:1.7rem;font-weight:900;
    background:linear-gradient(135deg,var(--primary),var(--secondary));
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
    letter-spacing:3px;text-decoration:none;display:flex;align-items:center;gap:.5rem;
}}
.logo-icon{{font-size:1.4rem;-webkit-text-fill-color:var(--primary);animation:logoSwing 3s ease-in-out infinite;}}
@keyframes logoSwing{{0%,100%{{transform:rotate(-5deg);}}50%{{transform:rotate(5deg);}}}}

.nav-links{{display:flex;gap:.8rem;align-items:center;list-style:none;}}
.nav-links a{{
    color:var(--text-dim);text-decoration:none;font-weight:600;font-size:.95rem;
    padding:.5rem 1rem;border-radius:var(--radius-sm);
    transition:var(--transition);display:flex;align-items:center;gap:.4rem;
}}
.nav-links a:hover{{color:var(--primary);background:rgba(0,255,136,.08);}}
.nav-links a i{{font-size:.85rem;}}
.nav-logout{{color:var(--danger)!important;}}
.nav-logout:hover{{background:rgba(255,51,102,.1)!important;color:var(--danger)!important;}}

.btn-nav{{font-weight:700;font-size:.9rem;padding:.45rem 1.1rem;border-radius:var(--radius-sm);text-decoration:none;display:flex;align-items:center;gap:.35rem;transition:var(--transition);}}
.btn-nav-outline{{border:1.5px solid var(--primary);color:var(--primary);}}
.btn-nav-outline:hover{{background:var(--primary);color:var(--dark);box-shadow:var(--glow-green);}}
.btn-nav-primary{{background:linear-gradient(135deg,var(--primary),var(--secondary));color:var(--dark);box-shadow:0 4px 18px var(--primary-dim);}}
.btn-nav-primary:hover{{transform:translateY(-2px);box-shadow:0 6px 28px var(--primary-dim);}}

/* ══════════ HERO ══════════ */
.hero{{
    text-align:center;padding:10rem 0 5rem;position:relative;overflow:hidden;
}}
.hero-glow{{
    position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);
    width:800px;height:800px;
    background:radial-gradient(circle,rgba(0,255,136,.12) 0%,transparent 70%);
    animation:heroBreath 5s ease-in-out infinite;pointer-events:none;
}}
@keyframes heroBreath{{0%,100%{{transform:translate(-50%,-50%) scale(1);opacity:.5;}}50%{{transform:translate(-50%,-50%) scale(1.15);opacity:.8;}}}}
.hero h1{{
    font-family:'Orbitron',sans-serif;font-size:clamp(2.5rem,6vw,4.8rem);font-weight:900;
    background:linear-gradient(135deg,#fff 0%,var(--primary) 50%,var(--secondary) 100%);
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
    position:relative;z-index:1;margin-bottom:1rem;
    animation:fadeDown .8s ease-out both;
}}
.hero p{{font-size:1.25rem;color:var(--text-dim);position:relative;z-index:1;animation:fadeUp .8s .2s ease-out both;max-width:600px;margin:0 auto 2rem;}}
@keyframes fadeDown{{from{{opacity:0;transform:translateY(-30px);}}to{{opacity:1;transform:translateY(0);}}}}
@keyframes fadeUp{{from{{opacity:0;transform:translateY(20px);}}to{{opacity:1;transform:translateY(0);}}}}

.server-ip-box{{
    display:inline-flex;align-items:center;gap:1rem;
    background:linear-gradient(135deg,rgba(0,255,136,.1),rgba(0,153,255,.1));
    border:1.5px solid rgba(0,255,136,.4);border-radius:var(--radius);
    padding:1.2rem 2.5rem;margin:1.5rem 0;cursor:pointer;
    position:relative;z-index:1;transition:var(--transition);
    box-shadow:0 6px 30px rgba(0,255,136,.15);
    animation:fadeUp .8s .4s ease-out both;
}}
.server-ip-box:hover{{transform:scale(1.04);box-shadow:var(--glow-green);border-color:var(--primary);}}
.server-ip-box .ip-text{{font-family:'Space Grotesk',monospace;font-size:1.6rem;font-weight:700;color:var(--primary);letter-spacing:1px;}}
.server-ip-box .ip-icon{{color:var(--text-dim);font-size:1.1rem;transition:var(--transition);}}
.server-ip-box:hover .ip-icon{{color:var(--primary);transform:scale(1.3);}}

/* ══════════ BUTTONS ══════════ */
.btn{{
    display:inline-flex;align-items:center;justify-content:center;gap:.5rem;
    padding:.9rem 2rem;border-radius:var(--radius-sm);font-weight:700;font-size:1rem;
    text-decoration:none;border:none;cursor:pointer;transition:var(--transition);
    position:relative;overflow:hidden;font-family:'Rajdhani',sans-serif;
}}
.btn::after{{
    content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(255,255,255,.15),transparent);
    opacity:0;transition:var(--transition);
}}
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
.btn-sm{{padding:.5rem 1rem;font-size:.85rem;border-radius:var(--radius-sm);}}

/* ══════════ CARDS / GLASS ══════════ */
.card{{
    background:var(--glass);backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
    border:1px solid rgba(0,255,136,.13);border-radius:var(--radius-lg);
    padding:2rem;box-shadow:var(--shadow);margin-bottom:1.5rem;
    position:relative;overflow:hidden;
}}
.card::before{{
    content:'';position:absolute;top:0;left:0;right:0;height:2px;
    background:linear-gradient(90deg,transparent,var(--primary),var(--secondary),transparent);
    opacity:.5;
}}
.card-header{{padding-bottom:1.2rem;margin-bottom:1.5rem;border-bottom:1px solid rgba(255,255,255,.07);display:flex;align-items:center;gap:.8rem;}}
.card-header h2{{font-family:'Orbitron',sans-serif;font-size:1.35rem;color:var(--primary);font-weight:700;}}
.card-header i{{color:var(--primary);font-size:1.2rem;}}

/* ══════════ STATS GRID ══════════ */
.stats{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:1.2rem;margin:3rem 0;}}
.stat-card{{
    background:var(--glass);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
    border:1px solid rgba(0,255,136,.12);border-radius:var(--radius);
    padding:2rem 1.5rem;text-align:center;transition:var(--transition);
    position:relative;overflow:hidden;
}}
.stat-card::before{{content:'';position:absolute;inset:0;background:linear-gradient(135deg,rgba(0,255,136,.04),rgba(0,153,255,.04));opacity:0;transition:var(--transition);}}
.stat-card:hover{{transform:translateY(-6px);border-color:var(--primary);box-shadow:var(--glow-green);}}
.stat-card:hover::before{{opacity:1;}}
.stat-card i{{font-size:2rem;color:var(--primary);margin-bottom:.6rem;display:block;position:relative;z-index:1;}}
.stat-card h3{{font-family:'Orbitron',sans-serif;font-size:1.8rem;color:var(--primary);margin:.4rem 0;position:relative;z-index:1;}}
.stat-card p{{color:var(--text-dim);font-size:.9rem;font-weight:500;position:relative;z-index:1;}}

/* ══════════ SECTION TITLE ══════════ */
.section-title{{text-align:center;margin:3.5rem 0 2rem;}}
.section-title h2{{
    font-family:'Orbitron',sans-serif;font-size:clamp(1.8rem,4vw,2.8rem);font-weight:900;
    background:linear-gradient(135deg,var(--primary),var(--secondary));
    -webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;
    position:relative;display:inline-block;
}}
.section-title h2::after{{
    content:'';position:absolute;bottom:-10px;left:50%;transform:translateX(-50%);
    width:70px;height:3px;background:linear-gradient(90deg,transparent,var(--primary),transparent);border-radius:2px;
}}

/* ══════════ PACKAGE CARDS ══════════ */
.packages{{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:1.5rem;margin:2rem 0 3rem;}}
.package-card{{
    background:var(--glass);backdrop-filter:blur(14px);-webkit-backdrop-filter:blur(14px);
    border:1.5px solid rgba(255,255,255,.08);border-radius:var(--radius-lg);
    padding:2rem 1.5rem;transition:var(--transition);position:relative;overflow:hidden;
    display:flex;flex-direction:column;
}}
.package-card::before{{
    content:'';position:absolute;top:0;left:0;right:0;height:3px;
    background:linear-gradient(90deg,transparent,var(--pkg-color,var(--primary)),transparent);
}}
.package-card:hover{{transform:translateY(-8px);border-color:var(--pkg-color,var(--primary));box-shadow:0 12px 40px rgba(0,0,0,.4);}}
.pkg-badge{{
    position:absolute;top:12px;right:12px;
    background:linear-gradient(135deg,var(--pkg-color,var(--primary)),rgba(0,0,0,.6));
    color:#fff;font-size:.7rem;font-weight:700;padding:.25rem .6rem;border-radius:20px;
    text-transform:uppercase;letter-spacing:1px;
}}
.package-name{{font-family:'Orbitron',sans-serif;font-size:1.5rem;font-weight:900;color:var(--pkg-color,var(--primary));text-align:center;margin-bottom:.3rem;position:relative;z-index:1;}}
.package-desc{{text-align:center;color:var(--text-dim);font-size:.9rem;margin-bottom:1rem;position:relative;z-index:1;}}
.package-price{{
    font-family:'Orbitron',sans-serif;font-size:2rem;font-weight:900;
    text-align:center;color:var(--primary);margin:1rem 0;position:relative;z-index:1;
}}
.package-price span{{font-size:.85rem;color:var(--text-dim);font-weight:400;font-family:'Rajdhani',sans-serif;}}
.package-features{{list-style:none;margin:1rem 0;flex-grow:1;position:relative;z-index:1;}}
.package-features li{{
    padding:.45rem 0;border-bottom:1px solid rgba(255,255,255,.05);
    display:flex;align-items:center;gap:.6rem;font-size:.9rem;color:var(--text-dim);transition:var(--transition);
}}
.package-features li:hover{{color:var(--text);padding-left:6px;}}
.package-features li i{{color:var(--primary);font-size:.8rem;flex-shrink:0;}}
.package-duration{{
    text-align:center;margin:1rem 0;padding:.5rem;
    background:rgba(0,255,136,.07);border-radius:var(--radius-sm);
    color:var(--primary);font-size:.85rem;font-weight:600;position:relative;z-index:1;
}}

/* ══════════ TABLES ══════════ */
.table-wrap{{overflow-x:auto;border-radius:var(--radius);}}
table{{width:100%;border-collapse:collapse;margin:.5rem 0;}}
table thead{{background:linear-gradient(135deg,rgba(0,255,136,.15),rgba(0,153,255,.15));}}
table thead th{{
    padding:1rem 1.2rem;text-align:left;color:var(--primary);font-weight:700;
    font-size:.85rem;text-transform:uppercase;letter-spacing:.8px;font-family:'Space Grotesk',sans-serif;
    border-bottom:1px solid rgba(0,255,136,.2);white-space:nowrap;
}}
table tbody tr{{transition:var(--transition);border-bottom:1px solid rgba(255,255,255,.04);}}
table tbody tr:hover{{background:rgba(0,255,136,.04);}}
table tbody td{{padding:.9rem 1.2rem;font-size:.92rem;color:var(--text);}}

/* ══════════ BADGES ══════════ */
.badge{{
    display:inline-block;padding:.3rem .85rem;border-radius:20px;
    font-size:.78rem;font-weight:700;text-transform:uppercase;letter-spacing:.8px;
}}
.badge-pending{{background:rgba(255,170,0,.12);color:var(--warning);border:1px solid rgba(255,170,0,.3);}}
.badge-approved,.badge-success{{background:rgba(0,255,136,.12);color:var(--success);border:1px solid rgba(0,255,136,.3);}}
.badge-rejected,.badge-danger{{background:rgba(255,51,102,.12);color:var(--danger);border:1px solid rgba(255,51,102,.3);}}
.badge-open{{background:rgba(0,153,255,.12);color:var(--secondary);border:1px solid rgba(0,153,255,.3);}}
.badge-answered{{background:rgba(168,85,247,.12);color:#c084fc;border:1px solid rgba(168,85,247,.3);}}
.badge-closed{{background:rgba(107,114,154,.12);color:var(--text-dim);border:1px solid rgba(107,114,154,.3);}}

/* ══════════ BALANCE DISPLAY ══════════ */
.balance-hero{{
    background:linear-gradient(135deg,rgba(168,85,247,.25),rgba(255,0,153,.2));
    border:1px solid rgba(168,85,247,.3);border-radius:var(--radius-lg);
    padding:2.5rem;text-align:center;margin:1.5rem 0;position:relative;overflow:hidden;
}}
.balance-hero::before{{
    content:'';position:absolute;top:-60%;right:-30%;width:80%;height:200%;
    background:radial-gradient(circle,rgba(255,255,255,.06) 0%,transparent 70%);
    animation:shimmerMove 4s ease-in-out infinite alternate;
}}
@keyframes shimmerMove{{0%{{transform:translate(0,0);}}100%{{transform:translate(-40px,20px);}}}}
.balance-hero h3{{color:var(--text-dim);font-size:1rem;margin-bottom:.5rem;position:relative;z-index:1;text-transform:uppercase;letter-spacing:1px;}}
.balance-amount{{font-family:'Orbitron',sans-serif;font-size:2.8rem;font-weight:900;color:#fff;position:relative;z-index:1;}}
.balance-amount span{{font-size:1rem;color:var(--text-dim);font-weight:400;font-family:'Rajdhani',sans-serif;}}

/* ══════════ ALERTS ══════════ */
.alert{{padding:1rem 1.2rem;border-radius:var(--radius-sm);margin:1rem 0;display:flex;align-items:flex-start;gap:.8rem;}}
.alert i{{flex-shrink:0;font-size:1.1rem;margin-top:.15rem;}}
.alert-warning{{background:rgba(255,170,0,.08);border:1px solid rgba(255,170,0,.25);color:var(--warning);}}
.alert-info{{background:rgba(0,153,255,.08);border:1px solid rgba(0,153,255,.25);color:var(--secondary);}}
.alert-success{{background:rgba(0,255,136,.08);border:1px solid rgba(0,255,136,.25);color:var(--success);}}

/* ══════════ TABS ══════════ */
.tabs{{display:flex;gap:.6rem;margin:1.5rem 0;flex-wrap:wrap;}}
.tab{{
    padding:.6rem 1.2rem;background:rgba(255,255,255,.04);border:1px solid rgba(255,255,255,.08);
    border-radius:var(--radius-sm);color:var(--text-dim);text-decoration:none;
    font-weight:600;font-size:.88rem;transition:var(--transition);display:flex;align-items:center;gap:.4rem;
}}
.tab:hover{{background:rgba(0,255,136,.08);color:var(--primary);border-color:rgba(0,255,136,.25);}}
.tab.active{{background:linear-gradient(135deg,var(--primary),var(--secondary));color:var(--dark);border-color:transparent;font-weight:700;}}

/* ══════════ FORM ══════════ */
.form-group{{margin-bottom:1.4rem;}}
.form-group label{{display:block;margin-bottom:.5rem;color:var(--text);font-weight:600;font-size:.92rem;}}
.form-group label i{{color:var(--primary);margin-right:.4rem;font-size:.85rem;}}
.form-group input,.form-group textarea,.form-group select{{
    width:100%;padding:.85rem 1rem;background:rgba(255,255,255,.04);
    border:1.5px solid rgba(255,255,255,.1);border-radius:var(--radius-sm);
    color:var(--text);font-size:.95rem;font-family:'Rajdhani',sans-serif;
    transition:var(--transition);
}}
.form-group input:focus,.form-group textarea:focus,.form-group select:focus{{
    outline:none;border-color:var(--primary);background:rgba(0,255,136,.05);box-shadow:var(--glow-green);
}}
.form-group textarea{{resize:vertical;min-height:100px;}}

/* ══════════ FILE UPLOAD ══════════ */
.file-upload{{position:relative;}}
.file-upload input[type=file]{{position:absolute;inset:0;opacity:0;cursor:pointer;z-index:2;}}
.file-upload-label{{
    display:flex;flex-direction:column;align-items:center;gap:.4rem;
    padding:1.5rem;background:rgba(0,255,136,.05);border:2px dashed rgba(0,255,136,.3);
    border-radius:var(--radius-sm);text-align:center;cursor:pointer;transition:var(--transition);
}}
.file-upload-label:hover{{background:rgba(0,255,136,.1);border-color:var(--primary);}}
.file-upload-label i{{font-size:1.6rem;color:var(--primary);}}
.file-upload-label p{{color:var(--text-dim);font-size:.88rem;}}
.image-preview{{max-width:100%;border-radius:var(--radius-sm);border:1px solid rgba(0,255,136,.3);margin-top:.8rem;}}

/* ══════════ NOTIFICATION TOAST ══════════ */
.toast{{
    position:fixed;top:90px;right:1.5rem;z-index:99999;
    background:rgba(14,18,34,.92);backdrop-filter:blur(16px);
    border:1px solid rgba(0,255,136,.25);border-radius:var(--radius);
    padding:1rem 1.4rem;box-shadow:0 8px 36px rgba(0,0,0,.5);
    display:flex;align-items:center;gap:.8rem;max-width:340px;
    animation:toastSlide .35s cubic-bezier(.4,0,.2,1) both;
    color:var(--text);font-size:.92rem;
}}
.toast.hide{{animation:toastSlide .3s cubic-bezier(.4,0,.2,1) reverse both;}}
.toast i{{font-size:1.2rem;flex-shrink:0;}}
.toast.success i{{color:var(--success);}}
.toast.error i{{color:var(--danger);}}
@keyframes toastSlide{{from{{opacity:0;transform:translateX(110%);}}to{{opacity:1;transform:translateX(0);}}}}

/* ══════════ SUPPORT CHAT ══════════ */
.support-list{{display:flex;flex-direction:column;gap:.7rem;}}
.ticket-row{{
    background:rgba(255,255,255,.035);border:1px solid rgba(255,255,255,.07);
    border-radius:var(--radius);padding:1rem 1.2rem;
    display:flex;align-items:center;justify-content:space-between;gap:1rem;
    transition:var(--transition);text-decoration:none;flex-wrap:wrap;
}}
.ticket-row:hover{{background:rgba(0,255,136,.06);border-color:rgba(0,255,136,.2);}}
.ticket-row-left{{display:flex;align-items:center;gap:.9rem;flex-grow:1;}}
.ticket-id{{
    font-family:'Orbitron',sans-serif;font-size:.75rem;color:var(--primary);
    background:rgba(0,255,136,.1);padding:.3rem .7rem;border-radius:6px;font-weight:700;white-space:nowrap;
}}
.ticket-subject{{font-weight:600;color:var(--text);font-size:.95rem;}}
.ticket-meta{{font-size:.78rem;color:var(--text-dim);margin-top:.15rem;}}
.ticket-row-right{{display:flex;align-items:center;gap:.7rem;}}

/* ── New Ticket Form ── */
.new-ticket-wrap{{max-width:720px;margin:0 auto;}}

/* ── Chat Window ── */
.chat-wrap{{display:flex;flex-direction:column;height:100%;}}
.chat-header{{
    display:flex;align-items:center;justify-content:space-between;
    padding:1rem 0;border-bottom:1px solid rgba(255,255,255,.07);margin-bottom:1rem;flex-shrink:0;
}}
.chat-header-left{{display:flex;align-items:center;gap:.8rem;}}
.chat-ticket-id{{font-family:'Orbitron',sans-serif;font-size:.75rem;color:var(--primary);background:rgba(0,255,136,.1);padding:.25rem .6rem;border-radius:6px;}}
.chat-title{{font-weight:700;color:var(--text);font-size:1rem;}}
.chat-online{{display:flex;align-items:center;gap:.35rem;font-size:.78rem;color:var(--success);}}
.chat-online::before{{content:'';display:block;width:7px;height:7px;background:var(--success);border-radius:50%;animation:onlinePulse 2s ease-in-out infinite;}}
@keyframes onlinePulse{{0%,100%{{box-shadow:0 0 0 0 rgba(0,255,136,.5);}}50%{{box-shadow:0 0 0 5px transparent;}}}}

.messages-area{{
    flex-grow:1;overflow-y:auto;padding:.5rem 0;display:flex;flex-direction:column;gap:.7rem;
    min-height:320px;max-height:460px;scroll-behavior:smooth;
}}
.messages-area::-webkit-scrollbar{{width:5px;}}
.messages-area::-webkit-scrollbar-track{{background:transparent;}}
.messages-area::-webkit-scrollbar-thumb{{background:rgba(0,255,136,.2);border-radius:3px;}}

.msg{{display:flex;gap:.7rem;align-items:flex-end;}}
.msg.mine{{flex-direction:row-reverse;}}
.msg-avatar{{
    width:32px;height:32px;border-radius:50%;flex-shrink:0;
    display:flex;align-items:center;justify-content:center;
    font-size:.75rem;font-weight:700;color:#fff;
}}
.msg-avatar.user-av{{background:linear-gradient(135deg,var(--secondary),var(--accent2));}}
.msg-avatar.admin-av{{background:linear-gradient(135deg,var(--primary),var(--secondary));color:var(--dark);}}

.msg-bubble{{
    max-width:72%;padding:.65rem 1rem;border-radius:18px;
    font-size:.92rem;line-height:1.5;position:relative;word-break:break-word;
}}
.msg.mine .msg-bubble{{
    background:linear-gradient(135deg,var(--primary),var(--secondary));
    color:var(--dark);border-bottom-right-radius:4px;
    box-shadow:0 3px 12px rgba(0,255,136,.25);
}}
.msg:not(.mine) .msg-bubble{{
    background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.1);
    color:var(--text);border-bottom-left-radius:4px;
}}
.msg-meta{{font-size:.7rem;color:var(--text-dim);margin-top:.2rem;display:flex;align-items:center;gap:.3rem;}}
.msg.mine .msg-meta{{text-align:right;justify-content:flex-end;}}
.msg-meta .admin-tag{{color:var(--primary);font-weight:700;text-transform:uppercase;font-size:.65rem;letter-spacing:.5px;}}

.chat-input-area{{
    display:flex;gap:.6rem;padding-top:1rem;border-top:1px solid rgba(255,255,255,.07);flex-shrink:0;
}}
.chat-input-area input{{flex-grow:1;}}
.chat-input-area button{{flex-shrink:0;}}

/* typing indicator */
.typing-indicator{{display:flex;align-items:center;gap:.35rem;padding:.5rem 0;color:var(--text-dim);font-size:.82rem;min-height:28px;}}
.typing-dots{{display:flex;gap:3px;}}
.typing-dots span{{display:block;width:6px;height:6px;background:var(--text-dim);border-radius:50%;animation:typeDot .8s ease-in-out infinite;}}
.typing-dots span:nth-child(2){{animation-delay:.15s;}}
.typing-dots span:nth-child(3){{animation-delay:.3s;}}
@keyframes typeDot{{0%,60%,100%{{transform:translateY(0);opacity:.4;}}30%{{transform:translateY(-4px);opacity:1;}}}}

/* ══════════ ADMIN SUPPORT TABS ══════════ */
.admin-support-header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;flex-wrap:wrap;gap:.8rem;}}
.admin-support-filters{{display:flex;gap:.5rem;flex-wrap:wrap;}}

/* ══════════ FOOTER ══════════ */
footer{{
    position:relative;z-index:2;margin-top:4rem;
    background:linear-gradient(180deg,var(--dark) 0%,rgba(6,10,22,.95) 100%);
    border-top:1px solid rgba(0,255,136,.1);padding:3rem 0 1.5rem;
}}
footer::before{{
    content:'';position:absolute;top:0;left:0;right:0;height:2px;
    background:linear-gradient(90deg,transparent,var(--primary),var(--secondary),var(--accent),transparent);
    opacity:.4;
}}
.footer-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:2.5rem;margin-bottom:2.5rem;}}
.footer-col h4{{font-family:'Orbitron',sans-serif;font-size:.95rem;color:var(--primary);margin-bottom:1rem;font-weight:700;}}
.footer-col p,.footer-col li{{color:var(--text-dim);font-size:.88rem;line-height:1.8;}}
.footer-col ul{{list-style:none;}}
.footer-col ul li a{{color:var(--text-dim);text-decoration:none;transition:var(--transition);display:inline-flex;align-items:center;gap:.3rem;}}
.footer-col ul li a:hover{{color:var(--primary);}}
.social-row{{display:flex;gap:.8rem;margin-top:1rem;}}
.social-btn{{
    width:40px;height:40px;border-radius:10px;display:flex;align-items:center;justify-content:center;
    background:rgba(255,255,255,.05);border:1px solid rgba(255,255,255,.1);
    color:var(--text-dim);font-size:1rem;text-decoration:none;transition:var(--transition);
}}
.social-btn:hover{{transform:translateY(-3px);color:#fff;}}
.social-btn.discord:hover{{background:#5865F2;border-color:#5865F2;box-shadow:0 6px 20px rgba(88,101,242,.4);}}
.social-btn.instagram:hover{{background:linear-gradient(135deg,#E1306C,#F77737);border-color:transparent;box-shadow:0 6px 20px rgba(225,48,108,.4);}}
.social-btn.telegram:hover{{background:#0088cc;border-color:#0088cc;box-shadow:0 6px 20px rgba(0,136,204,.4);}}
.social-btn.youtube:hover{{background:#FF0000;border-color:#FF0000;box-shadow:0 6px 20px rgba(255,0,0,.4);}}

.footer-bottom{{text-align:center;padding-top:2rem;border-top:1px solid rgba(255,255,255,.06);color:var(--text-dim);font-size:.82rem;}}

/* ══════════ RESPONSIVE ══════════ */
@media(max-width:768px){{
    .hero{{padding:7rem 0 3rem;}}
    .hero h1{{font-size:2.2rem;}}
    .nav-links{{gap:.3rem;}}
    .nav-links a{{padding:.4rem .6rem;font-size:.82rem;}}
    .nav-links a span{{display:none;}}
    .packages{{grid-template-columns:1fr;}}
    .stats{{grid-template-columns:repeat(2,1fr);}}
    .messages-area{{max-height:320px;}}
    .msg-bubble{{max-width:80%;}}
    table{{font-size:.82rem;}}
    table thead th,table tbody td{{padding:.7rem .8rem;}}
}}
@media(max-width:480px){{
    .stats{{grid-template-columns:1fr 1fr;}}
    .nav-links a i{{font-size:.75rem;}}
}}
</style>
</head>
<body>
<!-- Ambient Orbs -->
<div class="orb orb-1"></div>
<div class="orb orb-2"></div>
<div class="orb orb-3"></div>

<!-- NAV -->
<nav>
<div class="container">
    <a href="/" class="logo"><span class="logo-icon">⚔️</span> EliteMC</a>
    <ul class="nav-links">
        <li><a href="/"><i class="fas fa-home"></i> <span>Asosiy</span></a></li>
        <li><a href="/shop"><i class="fas fa-shopping-cart"></i> <span>Do'kon</span></a></li>
        {nav_user}
    </ul>
</div>
</nav>

<main>{body_content}</main>

<!-- FOOTER -->
<footer>
<div class="container">
    <div class="footer-grid">
        <div class="footer-col">
            <h4>⚔️ EliteMC.uz</h4>
            <p>O'zbekistonning eng yaxshi Minecraft serveri. Ajoyib o'yinchilar jamoasi bilan o'ynashing va yangi do'stlar orttirishingiz mumkin!</p>
            <p style="margin-top:.6rem;"><strong style="color:var(--text);">Server IP:</strong> {settings.get('server_ip','play.elitemc.uz')}</p>
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
            <p>Yangiliklar va aksiyalardan birinchi bo'lib xabardor bo'ling!</p>
            <div class="social-row">
                <a href="{settings.get('discord_link','#')}" class="social-btn discord" target="_blank"><i class="fab fa-discord"></i></a>
                <a href="{settings.get('instagram_link','#')}" class="social-btn instagram" target="_blank"><i class="fab fa-instagram"></i></a>
                <a href="{settings.get('telegram_link','#')}" class="social-btn telegram" target="_blank"><i class="fab fa-telegram"></i></a>
                <a href="{settings.get('youtube_link','#')}" class="social-btn youtube" target="_blank"><i class="fab fa-youtube"></i></a>
            </div>
        </div>
    </div>
    <div class="footer-bottom">
        <p>© 2026 EliteMC.uz — Barcha huquqlar himoyalangan. Made with ❤️ by EliteMC Team</p>
    </div>
</div>
</footer>

<!-- TOAST CONTAINER -->
<div id="toastRoot"></div>

<!-- GLOBAL JS -->
<script>
// ─── Toast system ───
let _toastTimer = null;
function showToast(msg, type='success') {{
    if(_toastTimer) clearTimeout(_toastTimer);
    let el = document.getElementById('toastRoot');
    let icon = type==='success' ? 'fa-check-circle' : 'fa-exclamation-circle';
    el.innerHTML = `<div class="toast ${{type}}"><i class="fas ${{icon}}"></i><span>${{msg}}</span></div>`;
    _toastTimer = setTimeout(()=>{{
        let t = el.querySelector('.toast');
        if(t) {{ t.classList.add('hide'); setTimeout(()=>el.innerHTML='',350); }}
    }}, 3200);
}}

// ─── Copy server IP ───
document.querySelectorAll('.server-ip-box').forEach(el => {{
    el.addEventListener('click', ()=>{{
        navigator.clipboard.writeText('play.elitemc.uz').then(()=>showToast('Server IP nusxalandi! ✅'));
    }});
}});

// ─── Generic AJAX form (login / register) ───
async function ajaxForm(formId, url) {{
    const form = document.getElementById(formId);
    if(!form) return;
    form.addEventListener('submit', async e => {{
        e.preventDefault();
        const data = Object.fromEntries(new FormData(form));
        try {{
            const res = await fetch(url, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify(data)}});
            const j = await res.json();
            showToast(j.message, j.success ? 'success' : 'error');
            if(j.success && j.redirect) setTimeout(()=> window.location.href = j.redirect, 1400);
        }} catch(e) {{ showToast('Xatolik yuz berdi!','error'); }}
    }});
}}
ajaxForm('loginForm','/login');
ajaxForm('registerForm','/register');

// ─── File preview ───
document.querySelectorAll('input[type=file]').forEach(inp => {{
    inp.addEventListener('change', function(e) {{
        const f = e.target.files[0];
        if(f && f.type.startsWith('image/')) {{
            const r = new FileReader();
            r.onload = ev => {{
                const grp = inp.closest('.form-group');
                let prev = grp.querySelector('.image-preview');
                if(prev) prev.remove();
                const img = document.createElement('img');
                img.src = ev.target.result;
                img.className = 'image-preview';
                grp.appendChild(img);
            }};
            r.readAsDataURL(f);
        }}
    }});
}});

// ─── Admin deposit approve/reject ───
async function approveDeposit(id) {{
    const comment = prompt('Izoh (ixtiyoriy):') || '';
    try {{
        const res = await fetch(`/admin/approve_deposit/${{id}}`, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{comment}})}});
        const j = await res.json();
        showToast(j.message, j.success?'success':'error');
        if(j.success) setTimeout(()=>location.reload(),1200);
    }} catch(e){{ showToast('Xatolik!','error'); }}
}}
async function rejectDeposit(id) {{
    const comment = prompt('Rad etish sababi:');
    if(!comment) return;
    try {{
        const res = await fetch(`/admin/reject_deposit/${{id}}`, {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify({{comment}})}});
        const j = await res.json();
        showToast(j.message, j.success?'success':'error');
        if(j.success) setTimeout(()=>location.reload(),1200);
    }} catch(e){{ showToast('Xatolik!','error'); }}
}}

// ─── Buy rank ───
async function buyRank(pkgId) {{
    if(!confirm('Ushbu paketni sotib olishga ishonchingiz komilmi?')) return;
    try {{
        const res = await fetch(`/buy_rank/${{pkgId}}`, {{method:'POST', headers:{{'Content-Type':'application/json'}}}});
        const j = await res.json();
        showToast(j.message, j.success?'success':'error');
        if(j.success) setTimeout(()=>location.reload(),1800);
    }} catch(e){{ showToast('Xatolik!','error'); }}
}}

// ─── Admin settings save ───
async function saveSettings() {{
    const form = document.getElementById('settingsForm');
    const data = Object.fromEntries(new FormData(form));
    try {{
        const res = await fetch('/admin/settings', {{method:'POST', headers:{{'Content-Type':'application/json'}}, body:JSON.stringify(data)}});
        const j = await res.json();
        showToast(j.message, j.success?'success':'error');
    }} catch(e){{ showToast('Xatolik!','error'); }}
}}
</script>
</body>
</html>'''


# ═══════════════════════════════════════════════
# ROUTES — INDEX
# ═══════════════════════════════════════════════

@app.route('/')
def index():
    conn = get_db()
    settings = {r['key']: r['value'] for r in conn.execute('SELECT key,value FROM settings').fetchall()}
    all_news = conn.execute('SELECT * FROM news ORDER BY created_at DESC LIMIT 6').fetchall()
    total_users = conn.execute('SELECT COUNT(*) as c FROM users WHERE is_admin=0').fetchone()['c']
    total_purchases = conn.execute('SELECT COUNT(*) as c FROM purchases').fetchone()['c']
    total_revenue = conn.execute('SELECT COALESCE(SUM(amount),0) as s FROM purchases').fetchone()['s']
    conn.close()

    trailer_html = ''
    if settings.get('show_trailer') == '1':
        trailer_html = f'''
        <div style="margin: 0 auto 2rem; max-width: 800px; border: 2px solid var(--primary); border-radius: 20px; overflow: hidden; box-shadow: var(--glow-green);">
            <iframe width="100%" height="400" src="{settings.get('trailer_url')}" frameborder="0" allowfullscreen></iframe>
        </div>'''

    news_html = "".join([f'<div class="card"><h3>{sanitize(n["title"])}</h3><p style="font-size:0.8rem;opacity:0.6;">{str(n["created_at"])[:16]}</p><p>{sanitize(n["content"][:100])}...</p></div>' for n in all_news])

    content = f'''
    <div class="hero">
        <div class="hero-glow"></div>
        <div class="container">
            {trailer_html}
            <h1 class="glitch-text">EliteMC.uz</h1>
            <div class="server-status-container" style="display:flex; justify-content:center; gap:30px; margin-top:40px;">
    <div class="status-card pulse-green">
        <span class="status-dot"></span>
        <div class="status-info">
            <span class="status-label">ONLINE</span>
            <span class="status-value">{settings.get('online_players', '0')} / 2026</span>
        </div>
    </div>
    <div class="status-card">
        <i class="fas fa-layer-group" style="color:var(--primary);"></i>
        <div class="status-info">
            <span class="status-label">VERSION</span>
            <span class="status-value">{settings.get('server_version', '1.16.5 - 1.20.x')}</span>
        </div>
    </div>
</div>
    <div class="container">
        <div class="stats">
            <div class="stat-card"><i class="fas fa-users"></i><h3>{total_users}</h3><p>Foydalanuvchilar</p></div>
            <div class="stat-card"><i class="fas fa-shopping-bag"></i><h3>{total_purchases}</h3><p>Xaridlar</p></div>
            <div class="stat-card"><i class="fas fa-coins"></i><h3>{total_revenue:,.0f}</h3><p>Jami daromad</p></div>
        </div>
        <div class="section-title"><h2>📰 Yangiliklar</h2></div>
        <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)); gap:1.5rem;">{news_html if news_html else '<p style="text-align:center;grid-column:1/-1;opacity:0.5;">Yangiliklar hozircha yoq</p>'}</div>
    </div>'''
    return render_page(content, logged_in='user_id' in session, is_admin=session.get('is_admin', False))

# ═══════════════════════════════════════════════
# ROUTES — AUTH
# ═══════════════════════════════════════════════

@app.route('/register', methods=['GET','POST'])
def register():
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        username = sanitize(data.get('username',''))
        email = sanitize(data.get('email',''))
        password = hashlib.sha256(data.get('password','').encode()).hexdigest()
        minecraft_nick = sanitize(data.get('minecraft_nick',''))
        try:
            conn = get_db()
            conn.execute('INSERT INTO users (username,email,password,minecraft_nick) VALUES (?,?,?,?)',
                         (username, email, password, minecraft_nick))
            conn.commit(); conn.close()
            return jsonify(success=True, message="Ro'yxatdan muvaffaqiyatli o'tdingiz!", redirect='/login')
        except sqlite3.IntegrityError:
            return jsonify(success=False, message='Bu username yoki email allaqachon mavjud!')

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
            <p style="text-align:center;margin-top:1.2rem;color:var(--text-dim);font-size:.9rem;">
                Akkountingiz bormi? <a href="/login" style="color:var(--primary);text-decoration:none;font-weight:600;">Kirish</a>
            </p>
        </div>
    </div>'''
    return render_page(content, logged_in=False)


@app.route('/login', methods=['GET','POST'])
def login():
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        username = data.get('username','')
        password = hashlib.sha256(data.get('password','').encode()).hexdigest()
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
            <p style="text-align:center;margin-top:1.2rem;color:var(--text-dim);font-size:.9rem;">
                Akkountingiz yo'qmi? <a href="/register" style="color:var(--primary);text-decoration:none;font-weight:600;">Ro'yxatdan O'tish</a>
            </p>
        </div>
    </div>'''
    return render_page(content, logged_in=False)


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


# ═══════════════════════════════════════════════
# ROUTES — SHOP & BUY
# ═══════════════════════════════════════════════

@app.route('/shop')
def shop():
    conn = get_db()
    packages = conn.execute("SELECT * FROM packages WHERE is_active=1").fetchall()
    user_balance = 0
    if 'user_id' in session:
        u = conn.execute('SELECT balance FROM users WHERE id=?', (session['user_id'],)).fetchone()
        if u: user_balance = u['balance']
    conn.close()

    pkgs_html = ''
    for p in packages:
        features = [sanitize(f.strip()) for f in p['features'].split(',')]
        feats_li = ''.join(f'<li><i class="fas fa-check-circle"></i>{f}</li>' for f in features)
        duration_display = p['duration'] if p['duration'] == "UMRBOT" else f"{p['duration']} kun"

        can_buy = 'user_id' in session and user_balance >= p['price']
        if 'user_id' in session:
            btn = f'<button onclick="buyRank({p["id"]})" class="btn btn-primary btn-full">Sotib olish</button>' if can_buy else f'<a href="/balance" class="btn btn-secondary btn-full">Balans yetarli emas</a>'
        else:
            btn = '<a href="/login" class="btn btn-primary btn-full">Kirish kerak</a>'

        pkg_html += f'''
        <div class="card package-card" style="border-top: 4px solid {p['color']};">
            <div class="pkg-badge" style="background:{p['color']}">30 KUNLIK</div>
            <h2 style="color:{p['color']}">{p['name']}</h2>
            <div class="price-tag">{p['price_30']:,} <span>SO'M</span></div>

            <form action="/buy_rank" method="POST">
                <input type="hidden" name="pkg_id" value="{p['id']}">
                <input type="text" name="mc_nick" placeholder="Minecraft Nick kiriting..." required 
                       style="border:1px solid {p['color']}; margin-bottom:10px;">

                <select name="duration" onchange="updatePrice(this, {p['price_30']}, {p['price_90']}, {p['price_forever']})" 
                        style="background:rgba(255,255,255,0.1); color:#fff;">
                    <option value="30">30 Kun - {p['price_30']:,} so'm</option>
                    <option value="90">90 Kun - {p['price_90']:,} so'm</option>
                    <option value="forever">UMRBOT - {p['price_forever']:,} so'm</option>
                </select>

                <button class="btn btn-primary" style="background:{p['color']}; color:#fff; width:100%; margin-top:15px;">
                    <i class="fas fa-shopping-basket"></i> SOTIB OLISH
                </button>
            </form>
        </div>
        '''

    return render_page(
        f'<div class="container" style="padding-top:2rem;"><div class="section-title"><h2>🛒 Do\'kon</h2></div><div class="packages">{pkgs_html}</div></div>',
        logged_in='user_id' in session)

@app.route('/buy_rank/<int:package_id>', methods=['POST'])
@login_required
def buy_rank(package_id):
    conn = get_db()
    pkg = conn.execute('SELECT * FROM packages WHERE id=?', (package_id,)).fetchone()
    user = conn.execute('SELECT balance,minecraft_nick FROM users WHERE id=?', (session['user_id'],)).fetchone()
    if not pkg:
        conn.close(); return jsonify(success=False, message='Paket topilmadi!')
    if not user or user['balance'] < pkg['price']:
        conn.close(); return jsonify(success=False, message="Balansingizda yetarli mablag' yo'q!")

    nick = user['minecraft_nick']
    new_bal = user['balance'] - pkg['price']
    ok, rcon_resp = give_rank_to_player(nick, pkg['name'])
    if ok:
        conn.execute('UPDATE users SET balance=? WHERE id=?', (new_bal, session['user_id']))
        conn.execute('INSERT INTO purchases (user_id,package_id,amount,package_name,minecraft_nick) VALUES (?,?,?,?,?)',
                     (session['user_id'], package_id, pkg['price'], pkg['name'], nick))
        conn.commit(); conn.close()
        return jsonify(success=True, message=f"{pkg['name']} ranki berildi! Serverga qayta kiring.", new_balance=new_bal)
    conn.close()
    return jsonify(success=False, message=f'Rank berishda xatolik: {rcon_resp}')


# ═══════════════════════════════════════════════
# ROUTES — BALANCE
# ═══════════════════════════════════════════════

@app.route('/balance')
@login_required
def balance():
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    deposits = conn.execute('SELECT * FROM balance_deposits WHERE user_id=? ORDER BY created_at DESC', (session['user_id'],)).fetchall()
    settings = {r['key']:r['value'] for r in conn.execute('SELECT key,value FROM settings').fetchall()}
    conn.close()

    rows_html = ''
    for d in deposits:
        sc = 'pending' if d['status']=='pending' else ('approved' if d['status']=='approved' else 'rejected')
        st = '⏳ Kutilmoqda' if d['status']=='pending' else ('✅ Tasdiqlandi' if d['status']=='approved' else '❌ Rad etildi')
        rows_html += f'''<tr>
            <td>#{d['id']}</td>
            <td><strong>{d['amount']:,.0f} so'm</strong></td>
            <td><span class="badge badge-{sc}">{st}</span></td>
            <td>{str(d['created_at'])[:16]}</td>
            <td>{d['admin_comment'] or '—'}</td>
        </tr>'''

    content = f'''
    <div class="container" style="max-width:780px;margin:0 auto;padding-top:2rem;">
        <div class="section-title"><h2>💰 Balans</h2></div>
        <div class="balance-hero">
            <h3>Joriy Balans</h3>
            <div class="balance-amount">{user['balance']:,.0f} <span>so'm</span></div>
        </div>
        <div class="card">
            <div class="card-header"><i class="fas fa-credit-card"></i><h2>Balansga Pul Qo'shish</h2></div>
            <div class="alert alert-warning"><i class="fas fa-exclamation-triangle"></i><div><strong>Diqqat!</strong> Pul o'tkazishdan oldin quyidagi ma'lumotlarni o'qing.</div></div>
            <div class="alert alert-info"><i class="fas fa-credit-card"></i><div>
                <strong>Admin Karta:</strong><br/>
                💳 Raqam: <strong>{settings.get('admin_card_number','')}</strong><br/>
                👤 Eger: <strong>{settings.get('admin_card_name','')}</strong>
            </div></div>
            <form action="/deposit_balance" method="POST" enctype="multipart/form-data">
                <div class="form-group"><label><i class="fas fa-money-bill-wave"></i> Summa (so'm)</label><input type="number" name="amount" required min="1000" placeholder="10000"></div>
                <div class="form-group"><label><i class="fas fa-credit-card"></i> Siz o'tkazgan karta raqami</label><input type="text" name="card_number" required placeholder="8600 **** **** ****"></div>
                <div class="form-group"><label><i class="fas fa-hashtag"></i> Transaksiya ID</label><input type="text" name="transaction_id" required placeholder="TXN12345678"></div>
                <div class="form-group"><label><i class="fas fa-camera"></i> To'lov skrinshoti (ixtiyoriy)</label>
                    <div class="file-upload"><input type="file" name="screenshot" accept="image/*"><div class="file-upload-label"><i class="fas fa-cloud-upload-alt"></i><p>Rasmni bu yerga surting yoki bosing</p></div></div>
                </div>
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
    card_number = sanitize(request.form.get('card_number',''))
    transaction_id = sanitize(request.form.get('transaction_id',''))
    screenshot = None
    if 'screenshot' in request.files:
        f = request.files['screenshot']
        if f and allowed_file(f.filename):
            fname = secure_filename(f"{session['user_id']}_{datetime.datetime.now().timestamp()}_{f.filename}")
            f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
            screenshot = f'/static/uploads/{fname}'
    conn = get_db()
    conn.execute('INSERT INTO balance_deposits (user_id,amount,card_number,transaction_id,screenshot) VALUES (?,?,?,?,?)',
                 (session['user_id'], amount, card_number, transaction_id, screenshot))
    conn.commit(); conn.close()
    return redirect(url_for('balance'))


# ═══════════════════════════════════════════════
# ROUTES — PROFILE
# ═══════════════════════════════════════════════

@app.route('/profile')
@login_required
def profile():
    conn = get_db()
    user = conn.execute('SELECT * FROM users WHERE id=?', (session['user_id'],)).fetchone()
    purchases = conn.execute('SELECT * FROM purchases WHERE user_id=? ORDER BY created_at DESC', (session['user_id'],)).fetchall()
    conn.close()

    pur_html = ''
    if purchases:
        for p in purchases:
            pur_html += f'''<tr>
                <td>#{p['id']}</td>
                <td><strong>{sanitize(p['package_name'])}</strong></td>
                <td>{p['amount']:,.0f} so'm</td>
                <td>{str(p['created_at'])[:16]}</td>
                <td><span class="badge badge-success">✅ {sanitize(p['status'])}</span></td>
            </tr>'''
    else:
        pur_html = '<tr><td colspan="5" style="text-align:center;color:var(--text-dim);padding:1.5rem;">Hali xarid qilmadingiz</td></tr>'

    content = f'''
    <div class="container" style="max-width:860px;margin:0 auto;padding-top:2rem;">
        <div class="section-title"><h2>👤 Profil</h2></div>
        <div class="card">
            <div class="card-header"><i class="fas fa-id-card"></i><h2>Shaxsiy Ma'lumotlar</h2></div>
            <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:1.5rem;">
                <div><p style="color:var(--text-dim);font-size:.82rem;margin-bottom:.25rem;"><i class="fas fa-user"></i> Username</p><h3 style="color:var(--primary);font-size:1.1rem;">{sanitize(user['username'])}</h3></div>
                <div><p style="color:var(--text-dim);font-size:.82rem;margin-bottom:.25rem;"><i class="fas fa-envelope"></i> Email</p><h3 style="color:var(--primary);font-size:1.1rem;">{sanitize(user['email'])}</h3></div>
                <div><p style="color:var(--text-dim);font-size:.82rem;margin-bottom:.25rem;"><i class="fas fa-gamepad"></i> MC Nick</p><h3 style="color:var(--primary);font-size:1.1rem;">{sanitize(user['minecraft_nick'] or '—')}</h3></div>
                <div><p style="color:var(--text-dim);font-size:.82rem;margin-bottom:.25rem;"><i class="fas fa-wallet"></i> Balans</p><h3 style="color:var(--primary);font-size:1.1rem;">{user['balance']:,.0f} so'm</h3></div>
            </div>
        </div>
        <div class="card">
            <div class="card-header"><i class="fas fa-receipt"></i><h2>Xaridlar Tarixi</h2></div>
            <div class="table-wrap"><table>
                <thead><tr><th>#</th><th>Paket</th><th>Summa</th><th>Sana</th><th>Status</th></tr></thead>
                <tbody>{pur_html}</tbody>
            </table></div>
        </div>
    </div>'''
    return render_page(content, logged_in=True, is_admin=session.get('is_admin', False))


# ═══════════════════════════════════════════════
# ROUTES — SUPPORT (Real-Time WebSocket Chat)
# ═══════════════════════════════════════════════

@app.route('/support')
@login_required
def support():
    conn = get_db()
    tickets = conn.execute('SELECT * FROM support_tickets WHERE user_id=? ORDER BY created_at DESC', (session['user_id'],)).fetchall()
    conn.close()

    list_html = ''
    for t in tickets:
        badge_cls = 'badge-open' if t['status']=='open' else ('badge-answered' if t['status']=='answered' else 'badge-closed')
        label = 'Ochiq' if t['status']=='open' else ('Javob berildi' if t['status']=='answered' else 'Yopilgan')
        list_html += f'''
        <a href="/support/{t['id']}" class="ticket-row" style="text-decoration:none;">
            <div class="ticket-row-left">
                <span class="ticket-id">#{t['id']}</span>
                <div><div class="ticket-subject">{sanitize(t['subject'])}</div><div class="ticket-meta"><i class="fas fa-clock"></i> {str(t['created_at'])[:16]}</div></div>
            </div>
            <div class="ticket-row-right">
                <span class="badge {badge_cls}">{label}</span>
                <span class="btn btn-outline btn-sm"><i class="fas fa-eye"></i> Ko'rish</span>
            </div>
        </a>'''

    if not list_html:
        list_html = '<div style="text-align:center;color:var(--text-dim);padding:2.5rem 0;"><i class="fas fa-inbox" style="font-size:2.5rem;margin-bottom:.8rem;display:block;opacity:.4;"></i>Murojaatlar hali yo\'q</div>'

    content = f'''
    <div class="container" style="max-width:780px;margin:0 auto;padding-top:2rem;">
        <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1.5rem;flex-wrap:wrap;gap:.8rem;">
            <div class="section-title" style="margin:0;text-align:left;"><h2>🛠️ Support</h2></div>
            <a href="/support/new" class="btn btn-primary btn-sm"><i class="fas fa-plus"></i> Yangi Murojaat</a>
        </div>
        <div class="card">
            <div class="support-list">{list_html}</div>
        </div>
    </div>'''
    return render_page(content, logged_in=True, is_admin=session.get('is_admin', False))


@app.route('/support/new', methods=['GET','POST'])
@login_required
def new_ticket():
    if request.method == 'POST':
        subject = sanitize(request.form.get('subject',''))
        message = sanitize(request.form.get('message',''))
        conn = get_db()
        conn.execute('INSERT INTO support_tickets (user_id,subject) VALUES (?,?)', (session['user_id'], subject))
        ticket_id = conn.execute('SELECT last_insert_rowid() as id').fetchone()['id']
        conn.execute('INSERT INTO support_messages (ticket_id,user_id,message) VALUES (?,?,?)',
                     (ticket_id, session['user_id'], message))
        conn.commit(); conn.close()
        return redirect(url_for('view_ticket', ticket_id=ticket_id))

    content = '''
    <div class="container new-ticket-wrap" style="padding-top:2rem;">
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


@app.route('/support/<int:ticket_id>', methods=['GET','POST'])
@login_required
def view_ticket(ticket_id):
    conn = get_db()
    # POST — only used as fallback if JS fails; real-time is via WebSocket
    if request.method == 'POST':
        message = sanitize(request.form.get('message',''))
        is_admin = 1 if session.get('is_admin') else 0
        conn.execute('INSERT INTO support_messages (ticket_id,user_id,message,is_admin_reply) VALUES (?,?,?,?)',
                     (ticket_id, session['user_id'], message, is_admin))
        new_status = 'answered' if is_admin else 'open'
        conn.execute('UPDATE support_tickets SET status=? WHERE id=?', (new_status, ticket_id))
        conn.commit()

    ticket = conn.execute('SELECT * FROM support_tickets WHERE id=?', (ticket_id,)).fetchone()
    if not ticket or (ticket['user_id'] != session['user_id'] and not session.get('is_admin')):
        conn.close()
        return redirect(url_for('support'))

    messages = conn.execute(
        'SELECT sm.*, u.username FROM support_messages sm JOIN users u ON sm.user_id=u.id WHERE ticket_id=? ORDER BY sm.created_at ASC',
        (ticket_id,)
    ).fetchall()
    conn.close()

    msgs_html = ''
    for m in messages:
        is_mine = (m['user_id'] == session['user_id'])
        cls = 'msg mine' if is_mine else 'msg'
        av_cls = 'user-av' if is_mine else 'admin-av'
        av_letter = sanitize(m['username'][0].upper()) if m['username'] else '?'
        admin_tag = '<span class="admin-tag"><i class="fas fa-bolt"></i> Admin</span> ' if m['is_admin_reply'] else ''
        msgs_html += f'''
        <div class="{cls}">
            <div class="msg-avatar {av_cls}">{av_letter}</div>
            <div>
                <div class="msg-bubble">{sanitize(m['message'])}</div>
                <div class="msg-meta">{admin_tag}{sanitize(m['username'])} • {str(m['created_at'])[:16]}</div>
            </div>
        </div>'''

    badge_cls = 'badge-open' if ticket['status']=='open' else ('badge-answered' if ticket['status']=='answered' else 'badge-closed')
    label = 'Ochiq' if ticket['status']=='open' else ('Javob berildi' if ticket['status']=='answered' else 'Yopilgan')

    content = f'''
    <div class="container" style="max-width:780px;margin:0 auto;padding-top:2rem;">
        <div class="card" style="display:flex;flex-direction:column;">
            <div class="chat-header">
                <div class="chat-header-left">
                    <a href="/support" class="btn btn-outline btn-sm"><i class="fas fa-arrow-left"></i></a>
                    <span class="chat-ticket-id">#{ticket['id']}</span>
                    <div>
                        <div class="chat-title">{sanitize(ticket['subject'])}</div>
                        <span class="badge {badge_cls}" style="font-size:.7rem;">{label}</span>
                    </div>
                </div>
                <div class="chat-online">Online</div>
            </div>

            <div class="messages-area" id="messagesArea">{msgs_html}</div>
            <div class="typing-indicator" id="typingIndicator" style="display:none;">
                <div class="typing-dots"><span></span><span></span><span></span></div>
                <span id="typingWho">Admin</span> yozmoqda...
            </div>

            <div class="chat-input-area">
                <input type="text" id="chatInput" placeholder="Xabar yozing..." autocomplete="off"/>
                <button class="btn btn-primary btn-sm" id="sendBtn"><i class="fas fa-paper-plane"></i></button>
            </div>
        </div>
    </div>

    <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.7.5/socket.io.min.js"></script>
    <script>
    (function() {{
        const ticketId = {ticket_id};
        const userId = {session['user_id']};
        const isAdmin = {'true' if session.get('is_admin') else 'false'};
        const username = '{sanitize(session.get("username",""))}';

        const area = document.getElementById('messagesArea');
        const input = document.getElementById('chatInput');
        const sendBtn = document.getElementById('sendBtn');
        const typingEl = document.getElementById('typingIndicator');
        const typingWho = document.getElementById('typingWho');

        // auto-scroll bottom
        function scrollBottom() {{ area.scrollTop = area.scrollHeight; }}
        scrollBottom();

        // ── Socket.IO ──
        const io = window.io || (window.socketio ? window.socketio : null);
        let socket = null;
        if(typeof window.io === 'function') {{
            socket = window.io();
        }} else {{
            // fallback: try connecting anyway
            try {{ socket = io(); }} catch(e) {{}}
        }}

        if(socket) {{
            socket.emit('join_ticket', {{ticket_id: ticketId}});

            socket.on('new_message', function(data) {{
                if(data.ticket_id !== ticketId) return;
                if(data.user_id === userId) return; // skip own (already rendered)
                appendMessage(data);
                scrollBottom();
            }});

            socket.on('typing', function(data) {{
                if(data.ticket_id !== ticketId || data.user_id === userId) return;
                typingWho.textContent = data.username;
                typingEl.style.display = 'flex';
                clearTimeout(typingEl._timer);
                typingEl._timer = setTimeout(()=> typingEl.style.display='none', 2500);
            }});

            // emit typing on input
            let typingTimeout = null;
            input.addEventListener('input', function() {{
                if(!typingTimeout) {{
                    socket.emit('typing', {{ticket_id: ticketId, user_id: userId, username: username}});
                    typingTimeout = setTimeout(()=> typingTimeout = null, 1200);
                }}
            }});
        }}

        function appendMessage(data) {{
            const isMine = (data.user_id === userId);
            const cls = isMine ? 'msg mine' : 'msg';
            const avCls = isMine ? 'user-av' : 'admin-av';
            const avLetter = (data.username||'?')[0].toUpperCase();
            const adminTag = data.is_admin ? '<span class="admin-tag"><i class="fas fa-bolt"></i> Admin</span> ' : '';
            const now = new Date().toLocaleString('uz-UZ',{{year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}});
            const div = document.createElement('div');
            div.className = cls;
            div.innerHTML = `
                <div class="msg-avatar ${{avCls}}">${{avLetter}}</div>
                <div>
                    <div class="msg-bubble">${{data.message}}</div>
                    <div class="msg-meta">${{adminTag}}${{data.username}} • ${{now}}</div>
                </div>`;
            area.appendChild(div);
        }}

        async function sendMessage() {{
            const text = input.value.trim();
            if(!text) return;
            input.value = '';

            // Optimistic UI
            const msgObj = {{
                ticket_id: ticketId,
                user_id: userId,
                username: username,
                message: text,
                is_admin: isAdmin
            }};
            appendMessage(msgObj);
            scrollBottom();

            // Emit via socket
            if(socket) {{
                socket.emit('send_message', msgObj);
            }}

            // Also POST to server as persistent store + fallback
            try {{
                await fetch(`/support/${{ticketId}}/send`, {{
                    method:'POST',
                    headers:{{'Content-Type':'application/json'}},
                    body:JSON.stringify({{message: text}})
                }});
            }} catch(e) {{ console.warn('POST fallback failed', e); }}
        }}

        sendBtn.addEventListener('click', sendMessage);
        input.addEventListener('keydown', function(e) {{ if(e.key==='Enter' && !e.shiftKey) {{ e.preventDefault(); sendMessage(); }} }});
    }})();
    </script>'''
    return render_page(content, logged_in=True, is_admin=session.get('is_admin', False))


@app.route('/support/<int:ticket_id>/send', methods=['POST'])
@login_required
def send_support_message(ticket_id):
    """Persist message to DB (called by client after optimistic send)."""
    data = request.get_json(force=True, silent=True) or {}
    message = sanitize(data.get('message',''))
    if not message:
        return jsonify(success=False, message='Xabar bo\'sh!')
    conn = get_db()
    ticket = conn.execute('SELECT * FROM support_tickets WHERE id=?', (ticket_id,)).fetchone()
    if not ticket or (ticket['user_id'] != session['user_id'] and not session.get('is_admin')):
        conn.close()
        return jsonify(success=False, message='Ruxsat yo\'q!')
    is_admin = 1 if session.get('is_admin') else 0
    conn.execute('INSERT INTO support_messages (ticket_id,user_id,message,is_admin_reply) VALUES (?,?,?,?)',
                 (ticket_id, session['user_id'], message, is_admin))
    new_status = 'answered' if is_admin else 'open'
    conn.execute('UPDATE support_tickets SET status=? WHERE id=?', (new_status, ticket_id))
    conn.commit(); conn.close()
    return jsonify(success=True)


# ═══════════════════════════════════════════════
# WEBSOCKET EVENTS
# ═══════════════════════════════════════════════

@socketio.on('join_ticket')
def handle_join(data):
    room = f"ticket_{data.get('ticket_id')}"
    join_room(room)


@socketio.on('disconnect')
def handle_disconnect():
    pass  # rooms auto-cleanup


@socketio.on('send_message')
def handle_send_message(data):
    """Broadcast message to ticket room (real-time relay)."""
    ticket_id = data.get('ticket_id')
    room = f"ticket_{ticket_id}"
    # Broadcast to everyone in room EXCEPT sender
    emit('new_message', data, to=room, include_sender=False)


@socketio.on('typing')
def handle_typing(data):
    ticket_id = data.get('ticket_id')
    room = f"ticket_{ticket_id}"
    emit('typing', data, to=room, include_sender=False)


# ═══════════════════════════════════════════════
# ROUTES — ADMIN
# ═══════════════════════════════════════════════

@app.route('/admin')
@admin_required
def admin_panel():
    conn = get_db()
    pending = conn.execute('''
        SELECT bd.*, u.username as uname, u.minecraft_nick as mc
        FROM balance_deposits bd JOIN users u ON bd.user_id=u.id
        WHERE bd.status='pending' ORDER BY bd.created_at DESC
    ''').fetchall()
    total_users = conn.execute('SELECT COUNT(*) as c FROM users WHERE is_admin=0').fetchone()['c']
    total_deposits = conn.execute("SELECT COUNT(*) as c FROM balance_deposits WHERE status='approved'").fetchone()['c']
    total_purchases = conn.execute('SELECT COUNT(*) as c FROM purchases').fetchone()['c']
    total_revenue = conn.execute('SELECT COALESCE(SUM(amount),0) as s FROM purchases').fetchone()['s']
    open_tickets = conn.execute("SELECT COUNT(*) as c FROM support_tickets WHERE status='open'").fetchone()['c']
    conn.close()

    pending_html = ''
    if pending:
        for d in pending:
            ss_btn = f'<a href="{d["screenshot"]}" target="_blank" class="btn btn-outline btn-sm"><i class="fas fa-image"></i></a>' if d['screenshot'] else ''
            pending_html += f'''<tr>
                <td>#{d['id']}</td>
                <td><strong>{sanitize(d['uname'])}</strong><br/><span style="color:var(--text-dim);font-size:.8rem;">{sanitize(d['mc'])}</span></td>
                <td>{d['amount']:,.0f} so'm</td>
                <td>{sanitize(d['card_number'])}</td>
                <td>{sanitize(d['transaction_id'])}</td>
                <td>{str(d['created_at'])[:16]}</td>
                <td style="display:flex;gap:.4rem;flex-wrap:wrap;">
                    {ss_btn}
                    <button onclick="approveDeposit({d['id']})" class="btn btn-primary btn-sm"><i class="fas fa-check"></i> Tasdiqlash</button>
                    <button onclick="rejectDeposit({d['id']})" class="btn btn-danger btn-sm"><i class="fas fa-times"></i> Rad</button>
                </td>
            </tr>'''
    else:
        pending_html = '<tr><td colspan="7" style="text-align:center;color:var(--text-dim);padding:1.5rem;">Kutilayotgan to\'lovlar yo\'q</td></tr>'

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
            <a href="/admin/deposits?status=all" class="tab"><i class="fas fa-credit-card"></i> To'lovlar</a>
            <a href="/admin/users" class="tab"><i class="fas fa-users"></i> Users</a>
            <a href="/admin/support" class="tab"><i class="fas fa-headset"></i> Support {f'<span class="badge badge-open" style="font-size:.65rem;padding:.15rem .5rem;">{open_tickets}</span>' if open_tickets else ''}</a>
            <a href="/admin/settings" class="tab"><i class="fas fa-cog"></i> Settings</a>
        </div>
        <div class="card">
            <div class="card-header"><i class="fas fa-hourglass-half"></i><h2>Kutilayotgan To'lovlar</h2></div>
            <div class="table-wrap"><table>
                <thead><tr><th>#</th><th>User</th><th>Summa</th><th>Karta</th><th>TXN</th><th>Sana</th><th>Amal</th></tr></thead>
                <tbody>{pending_html}</tbody>
            </table></div>
        </div>
    </div>'''
    return render_page(content, logged_in=True, is_admin=True)


@app.route('/admin/approve_deposit/<int:did>', methods=['POST'])
@admin_required
def approve_deposit(did):
    data = request.get_json(force=True, silent=True) or {}
    comment = sanitize(data.get('comment',''))
    conn = get_db()
    dep = conn.execute('SELECT * FROM balance_deposits WHERE id=?', (did,)).fetchone()
    if dep and dep['status']=='pending':
        conn.execute('UPDATE users SET balance=balance+? WHERE id=?', (dep['amount'], dep['user_id']))
        conn.execute('UPDATE balance_deposits SET status=?,admin_comment=?,processed_at=?,processed_by=? WHERE id=?',
                     ('approved', comment, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), session['user_id'], did))
        conn.commit(); conn.close()
        return jsonify(success=True, message="To'lov tasdiqlandi!")
    conn.close()
    return jsonify(success=False, message='Xatolik!')


@app.route('/admin/reject_deposit/<int:did>', methods=['POST'])
@admin_required
def reject_deposit(did):
    data = request.get_json(force=True, silent=True) or {}
    comment = sanitize(data.get('comment',''))
    conn = get_db()
    dep = conn.execute('SELECT * FROM balance_deposits WHERE id=?', (did,)).fetchone()
    if dep and dep['status']=='pending':
        conn.execute('UPDATE balance_deposits SET status=?,admin_comment=?,processed_at=?,processed_by=? WHERE id=?',
                     ('rejected', comment, datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'), session['user_id'], did))
        conn.commit(); conn.close()
        return jsonify(success=True, message="To'lov rad etildi!")
    conn.close()
    return jsonify(success=False, message='Xatolik!')


@app.route('/admin/deposits')
@admin_required
def admin_deposits():
    sf = request.args.get('status','all')
    conn = get_db()
    q = 'SELECT bd.*, u.username as uname FROM balance_deposits bd JOIN users u ON bd.user_id=u.id'
    params = []
    if sf != 'all':
        q += ' WHERE bd.status=?'; params.append(sf)
    q += ' ORDER BY bd.created_at DESC'
    deposits = conn.execute(q, params).fetchall()
    conn.close()

    rows = ''
    for d in deposits:
        sc = 'pending' if d['status']=='pending' else ('approved' if d['status']=='approved' else 'rejected')
        st = '⏳ Kutilmoqda' if d['status']=='pending' else ('✅ Tasdiqlandi' if d['status']=='approved' else '❌ Rad etildi')
        ss = f'<a href="{d["screenshot"]}" target="_blank" class="btn btn-outline btn-sm"><i class="fas fa-image"></i></a>' if d['screenshot'] else ''
        rows += f'''<tr>
            <td>#{d['id']}</td><td><strong>{sanitize(d['uname'])}</strong></td>
            <td>{d['amount']:,.0f} so'm</td><td>{sanitize(d['card_number'])}</td>
            <td><span class="badge badge-{sc}">{st}</span></td>
            <td>{str(d['created_at'])[:16]}</td><td>{ss}</td>
        </tr>'''

    content = f'''
    <div class="container" style="padding-top:2rem;">
        <div class="section-title"><h2>💳 To'lovlar</h2></div>
        <div class="tabs">
            <a href="/admin" class="tab"><i class="fas fa-tachometer-alt"></i> Dashboard</a>
            <a href="/admin/deposits?status=all" class="tab {'active' if sf=='all' else ''}">Barchasi</a>
            <a href="/admin/deposits?status=pending" class="tab {'active' if sf=='pending' else ''}">⏳ Kutilmoqda</a>
            <a href="/admin/deposits?status=approved" class="tab {'active' if sf=='approved' else ''}">✅ Tasdiqlangan</a>
            <a href="/admin/deposits?status=rejected" class="tab {'active' if sf=='rejected' else ''}">❌ Rad etilgan</a>
        </div>
        <div class="card">
            <div class="table-wrap"><table>
                <thead><tr><th>#</th><th>User</th><th>Summa</th><th>Karta</th><th>Status</th><th>Sana</th><th>Screenshot</th></tr></thead>
                <tbody>{rows or '<tr><td colspan="7" style="text-align:center;color:var(--text-dim);padding:1.5rem;">Malumotlar yoq</td></tr>'}</tbody>
            </table></div>
        </div>
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
        # Har bir foydalanuvchi uchun balansni tahrirlash formasi
        rows += f'''
        <tr>
            <td>#{u['id']}</td>
            <td><strong>{sanitize(u['username'])}</strong></td>
            <td>{u['balance']:,} so'm</td>
            <td>{u['tokens']:,} 💎</td>
            <td>
                <form method="POST" action="/admin/update_balance" style="display:flex; gap:5px; align-items:center;">
                    <input type="hidden" name="user_id" value="{u['id']}">
                    <input type="number" name="new_balance" placeholder="Balans" style="width:100px; padding:5px; margin:0;">
                    <button class="btn btn-primary btn-sm">OK</button>
                    <button type="button" onclick="setZero({u['id']})" class="btn btn-danger btn-sm">0</button>
                </form>
            </td>
        </tr>'''

    content = f'''
    <div class="container" style="padding-top:2rem;">
        <div class="section-title"><h2>👥 Foydalanuvchilar Boshqaruvi</h2></div>
        <div class="card">
            <div class="table-wrap">
                <table>
                    <thead>
                        <tr><th>ID</th><th>Username</th><th>Balans</th><th>Tokenlar</th><th>Amal (Balansni tahrirlash)</th></tr>
                    </thead>
                    <tbody>{rows}</tbody>
                </table>
            </div>
        </div>
    </div>
    <script>
    async function setZero(uid) {{
        if(!confirm('Balansni 0 qilishga ishonchingiz komilmi?')) return;
        const res = await fetch('/admin/update_balance', {{
            method: 'POST',
            headers: {{'Content-Type': 'application/x-www-form-urlencoded'}},
            body: `user_id=${{uid}}&new_balance=0`
        }});
        if(res.ok) location.reload();
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
        conn.commit()
        conn.close()
    return redirect(url_for('admin_users'))


@app.route('/admin/support')
@admin_required
def admin_support_list():
    conn = get_db()
    tickets = conn.execute('''
        SELECT st.*, u.username as uname FROM support_tickets st
        JOIN users u ON st.user_id=u.id
        ORDER BY CASE WHEN st.status='open' THEN 0 WHEN st.status='answered' THEN 1 ELSE 2 END, st.created_at DESC
    ''').fetchall()
    conn.close()

    list_html = ''
    for t in tickets:
        badge_cls = 'badge-open' if t['status']=='open' else ('badge-answered' if t['status']=='answered' else 'badge-closed')
        label = 'Ochiq' if t['status']=='open' else ('Javob berildi' if t['status']=='answered' else 'Yopilgan')
        list_html += f'''
        <a href="/support/{t['id']}" class="ticket-row" style="text-decoration:none;">
            <div class="ticket-row-left">
                <span class="ticket-id">#{t['id']}</span>
                <div>
                    <div class="ticket-subject">{sanitize(t['subject'])}</div>
                    <div class="ticket-meta"><i class="fas fa-user"></i> {sanitize(t['uname'])} • <i class="fas fa-clock"></i> {str(t['created_at'])[:16]}</div>
                </div>
            </div>
            <div class="ticket-row-right">
                <span class="badge {badge_cls}">{label}</span>
                <span class="btn btn-primary btn-sm"><i class="fas fa-reply"></i> Javob</span>
            </div>
        </a>'''

    if not list_html:
        list_html = '<div style="text-align:center;color:var(--text-dim);padding:2.5rem;"><i class="fas fa-check-circle" style="font-size:2rem;color:var(--success);margin-bottom:.6rem;display:block;"></i>Barcha murojaatlar hal qilib tashlangan!</div>'

    content = f'''
    <div class="container" style="max-width:860px;margin:0 auto;padding-top:2rem;">
        <div class="section-title"><h2>⚡ Admin Support</h2></div>
        <div class="tabs">
            <a href="/admin" class="tab"><i class="fas fa-tachometer-alt"></i> Dashboard</a>
            <a href="/admin/support" class="tab active"><i class="fas fa-headset"></i> Support</a>
        </div>
        <div class="card">
            <div class="support-list">{list_html}</div>
        </div>
    </div>'''
    return render_page(content, logged_in=True, is_admin=True)


@app.route('/admin/settings', methods=['GET','POST'])
@admin_required
def admin_settings():
    conn = get_db()
    if request.method == 'POST':
        data = request.get_json(force=True, silent=True) or {}
        for k, v in data.items():
            conn.execute('INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)', (sanitize(k), sanitize(v)))
        conn.commit(); conn.close()
        return jsonify(success=True, message='Sozlamalar saqlandi!')

    settings = {r['key']:r['value'] for r in conn.execute('SELECT key,value FROM settings').fetchall()}
    conn.close()

    def inp(name, typ='text', placeholder=''):
        val = settings.get(name,'')
        return f'<input type="{typ}" name="{name}" value="{sanitize(val)}" form="settingsForm" placeholder="{placeholder}" required>'

    content = f'''
    <div class="container" style="max-width:720px;margin:0 auto;padding-top:2rem;">
        <div class="section-title"><h2>⚙️ Settings</h2></div>
        <div class="tabs">
            <a href="/admin" class="tab"><i class="fas fa-tachometer-alt"></i> Dashboard</a>
            <a href="/admin/settings" class="tab active"><i class="fas fa-cog"></i> Settings</a>
        </div>
        <div class="card">
    <div class="card-header"><i class="fab fa-youtube"></i><h2>Trayler Sozlamalari</h2></div>
    <div class="form-group">
        <label>Trayler ko'rsatilsinmi?</label>
        <select name="show_trailer" form="settingsForm">
            <option value="1" {'selected' if settings.get('show_trailer')=='1' else ''}>Ha</option>
            <option value="0" {'selected' if settings.get('show_trailer')=='0' else ''}>Yo'q</option>
        </select>
    </div>
    <div class="form-group"><label>YouTube Embed Link</label>{inp('trailer_url')}</div>
</div>
        <div class="card">
            <div class="card-header"><i class="fas fa-credit-card"></i><h2>Admin Karta</h2></div>
            <form id="settingsForm">
                <div class="form-group"><label><i class="fas fa-credit-card"></i> Karta Raqami</label>{inp('admin_card_number','text','8600 **** **** ****')}</div>
                <div class="form-group"><label><i class="fas fa-user"></i> Karta Egasi</label>{inp('admin_card_name','text','Ism Familiya')}</div>
            </form>
        </div>
        <div class="card">
            <div class="card-header"><i class="fas fa-globe"></i><h2>Sayt Settings</h2></div>
            <div class="form-group"><label><i class="fas fa-tag"></i> Sayt Nomi</label>{inp('site_name','text','EliteMC.uz')}</div>
            <div class="form-group"><label><i class="fas fa-server"></i> Server IP</label>{inp('server_ip','text','play.elitemc.uz')}</div>
        </div>
        <div class="card">
            <div class="card-header"><i class="fas fa-network-wired"></i><h2>RCON Settings</h2></div>
            <div class="form-group"><label><i class="fas fa-desktop"></i> RCON Host</label>{inp('rcon_host','text','localhost')}</div>
            <div class="form-group"><label><i class="fas fa-plug"></i> RCON Port</label>{inp('rcon_port','number','25575')}</div>
            <div class="form-group"><label><i class="fas fa-key"></i> RCON Parol</label>{inp('rcon_password','password','****')}</div>
        </div>
        <div class="card">
            <div class="card-header"><i class="fas fa-share-alt"></i><h2>Ijtimoiy Tarmoqlar</h2></div>
            <div class="form-group"><label><i class="fab fa-discord"></i> Discord</label>{inp('discord_link','url','https://discord.gg/...')}</div>
            <div class="form-group"><label><i class="fab fa-instagram"></i> Instagram</label>{inp('instagram_link','url','https://instagram.com/...')}</div>
            <div class="form-group"><label><i class="fab fa-telegram"></i> Telegram</label>{inp('telegram_link','url','https://t.me/...')}</div>
            <div class="form-group"><label><i class="fab fa-youtube"></i> YouTube</label>{inp('youtube_link','url','https://youtube.com/@...')}</div>
        </div>
        <button onclick="saveSettings()" class="btn btn-primary btn-full" style="margin-top:.5rem;"><i class="fas fa-save"></i> Saqlash</button>
    </div>'''
    return render_page(content, logged_in=True, is_admin=True)


# ═══════════════════════════════════════════════
# STATIC FILES
# ═══════════════════════════════════════════════

@app.route('/static/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)


@app.route('/api/stats')
def api_stats():
    conn = get_db()
    tu = conn.execute('SELECT COUNT(*) as c FROM users WHERE is_admin=0').fetchone()['c']
    tp = conn.execute('SELECT COUNT(*) as c FROM purchases').fetchone()['c']
    tr = conn.execute('SELECT COALESCE(SUM(amount),0) as s FROM purchases').fetchone()['s']
    conn.close()
    return jsonify(total_users=tu, total_purchases=tp, total_revenue=tr)


# ═══════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════

if __name__ == '__main__':

    init_db()
    port = int(os.environ.get("PORT", 5000))
    
    print("=" * 62)
    print("  🎮  EliteMC.uz — Ultra Premium Donate Platform")
    print("=" * 62)
    print(f"  📍 URL          : http://0.0.0.0:{port}")
    print(f"  👤 Admin        : admin")
    print("=" * 62)
    socketio.run(app, host='0.0.0.0', port=port, debug=False)
