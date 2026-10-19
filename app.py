import hashlib
import hmac
import html
import json
import os
import re
import secrets
import threading
import time
import urllib.parse
import urllib.request
from datetime import date

import streamlit as st
import yt_dlp
from google import genai
from google.genai import types

# ====================== CONFIG ======================
VERSION = "v9"
LINK = "https://buy.stripe.com/aFa7sN3E96m71RL9nQ5Ne02"
MODEL = "gemini-flash-latest"  # pointe toujours vers le dernier Flash stable
FREE_LIMIT = 5  # analyses gratuites par appareil/rÃ©seau
FREE_TTL = 30 * 24 * 3600  # le compteur gratuit se remet Ã  zÃ©ro aprÃ¨s 30 jours
PREMIUM_DAILY_LIMIT = 30  # analyses premium par jour (protÃ¨ge ton quota Gemini)
MAX_VIDEO_SECONDS = 20 * 60  # au-delÃ , on analyse seulement le titre
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sans 0/O/1/I pour Ã©viter les erreurs

st.set_page_config(page_title="VIRAL OS", page_icon="ðŸš€", layout="centered")


def get_secret(name):
    """Lit un secret Streamlit, ou une variable d'environnement en secours."""
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.getenv(name)


GEMINI_API_KEY = get_secret("GEMINI_API_KEY")
ADMIN_PASSWORD = get_secret("ADMIN_PASSWORD")
UPSTASH_URL = get_secret("UPSTASH_REDIS_REST_URL")
UPSTASH_TOKEN = get_secret("UPSTASH_REDIS_REST_TOKEN")
ID_SALT = get_secret("ID_SALT") or "viral-os"

if not GEMINI_API_KEY:
    st.error("ClÃ© GEMINI_API_KEY manquante. Ajoute-la dans Manage app â†’ Settings â†’ Secrets.")
    st.stop()


# ====================== STOCKAGE (codes, compteurs) ======================
class RedisStore:
    """Stockage permanent via Upstash Redis (gratuit), appelÃ© en HTTPS."""

    persistent = True

    def __init__(self, url, token):
        self.url = url.rstrip("/")
        self.token = token

    def _cmd(self, *args):
        req = urllib.request.Request(
            self.url,
            data=json.dumps([str(a) for a in args]).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as r:
            out = json.loads(r.read().decode("utf-8"))
        if out.get("error"):
            raise RuntimeError(out["error"])
        return out.get("result")

    def add_codes(self, codes):
        self._cmd("SADD", "viral:codes", *codes)

    def redeem(self, code):
        # SREM est atomique : un seul visiteur peut obtenir 1, mÃªme si deux essaient en mÃªme temps
        return self._cmd("SREM", "viral:codes", code) == 1

    def members(self):
        return sorted(self._cmd("SMEMBERS", "viral:codes") or [])

    def count_codes(self):
        return int(self._cmd("SCARD", "viral:codes") or 0)

    def add_token(self, token):
        self._cmd("SADD", "viral:tokens", token)

    def has_token(self, token):
        return self._cmd("SISMEMBER", "viral:tokens", token) == 1

    def bump(self, key, ttl):
        n = int(self._cmd("INCR", "viral:" + key))
        if n == 1:
            self._cmd("EXPIRE", "viral:" + key, ttl)
        return n

    def get(self, key):
        return int(self._cmd("GET", "viral:" + key) or 0)


class FileStore:
    """Stockage local dans un fichier : pratique en test, mais pas permanent sur Streamlit Cloud."""

    persistent = False
    _lock = threading.Lock()

    def __init__(self, path):
        self.path = path

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                d = json.load(f)
        except Exception:
            d = {}
        d.setdefault("codes", [])
        d.setdefault("tokens", [])
        d.setdefault("counters", {})
        return d

    def _save(self, d):
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f)
        os.replace(tmp, self.path)

    def _update(self, fn):
        with self._lock:
            d = self._load()
            result = fn(d)
            self._save(d)
            return result

    def add_codes(self, codes):
        def f(d):
            d["codes"] = sorted(set(d["codes"]) | set(codes))
        self._update(f)

    def redeem(self, code):
        def f(d):
            if code in d["codes"]:
                d["codes"].remove(code)
                return True
            return False
        return self._update(f)

    def members(self):
        with self._lock:
            return sorted(self._load()["codes"])

    def count_codes(self):
        return len(self.members())

    def add_token(self, token):
        def f(d):
            if token not in d["tokens"]:
                d["tokens"].append(token)
        self._update(f)

    def has_token(self, token):
        with self._lock:
            return token in self._load()["tokens"]

    def bump(self, key, ttl):
        def f(d):
            now = time.time()
            c = d["counters"].get(key)
            if not c or c[1] < now:
                c = [0, now + ttl]
            c[0] += 1
            d["counters"][key] = c
            return c[0]
        return self._update(f)

    def get(self, key):
        with self._lock:
            c = self._load()["counters"].get(key)
        if not c or c[1] < time.time():
            return 0
        return int(c[0])


@st.cache_resource
def get_store(url, token):
    if url and token:
        return RedisStore(url, token)
    here = os.path.dirname(os.path.abspath(__file__))
    return FileStore(os.path.join(here, ".viral_os_store.json"))


store = get_store(UPSTASH_URL, UPSTASH_TOKEN)


def safe(fn, default=None):
    try:
        return fn()
    except Exception as e:
        print(f"[viral-os] erreur de stockage : {e!r}")
        return default


# ====================== SESSION ======================
st.session_state.setdefault("count", 0)
st.session_state.setdefault("is_premium", False)
st.session_state.setdefault("token", None)
st.session_state.setdefault("history", [])
st.session_state.setdefault("last", None)
st.session_state.setdefault("admin_ok", False)
st.session_state.setdefault("sid", secrets.token_hex(8))

# Retrouve l'accÃ¨s premium aprÃ¨s un rafraÃ®chissement grÃ¢ce au lien ?k=...
if not st.session_state.is_premium:
    try:
        k = st.query_params.get("k")
    except Exception:
        k = None
    if k and safe(lambda: store.has_token(k), False):
        st.session_state.is_premium = True
        st.session_state.token = k


# ====================== OUTILS ======================
def render(markup):
    """Affiche du HTML sans lignes vides ni indentation (sinon Streamlit casse le rendu)."""
    cleaned = "\n".join(line.strip() for line in markup.splitlines() if line.strip())
    st.markdown(cleaned, unsafe_allow_html=True)


def esc(value):
    """Ã‰chappe le texte venant de YouTube ou de Gemini avant de l'afficher en HTML."""
    text = html.escape(str(value))
    text = text.replace("$", "&#36;")  # Ã©vite que Streamlit lise $...$ comme des maths
    return text.replace("\r\n", "\n").replace("\n", "<br>")


def clamp(value, default):
    try:
        return max(0, min(100, int(float(value))))
    except (TypeError, ValueError):
        return default


def n_items(value, defaults, n):
    items = [str(v) for v in value if str(v).strip()] if isinstance(value, list) else []
    return (items + defaults)[:n]


def normalize_code(code):
    return re.sub(r"[^A-Z0-9]", "", (code or "").upper())


def generate_codes(n):
    codes = set()
    while len(codes) < n:
        codes.add("VOS" + "".join(secrets.choice(CODE_ALPHABET) for _ in range(8)))
    return sorted(codes)


def pretty_code(code):
    return f"{code[:3]}-{code[3:7]}-{code[7:]}"


def is_youtube_url(u):
    try:
        host = (urllib.parse.urlparse(u).hostname or "").lower()
    except ValueError:
        return False
    return host in ("youtu.be", "youtube.com") or host.endswith(".youtube.com")


def extract_video_id(u):
    try:
        p = urllib.parse.urlparse(u)
    except ValueError:
        return None
    host = (p.hostname or "").lower()
    vid = ""
    if host == "youtu.be":
        vid = p.path.strip("/").split("/")[0]
    else:
        qs = urllib.parse.parse_qs(p.query)
        if "v" in qs:
            vid = qs["v"][0]
        else:
            m = re.match(r"^/(?:shorts|embed|live|v)/([^/?#]+)", p.path)
            vid = m.group(1) if m else ""
    return vid if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid) else None


def client_id():
    """Identifiant anonyme (IP hachÃ©e) pour limiter les abus. None en local."""
    try:
        h = st.context.headers
        ip = (h.get("X-Forwarded-For") or h.get("X-Real-Ip") or "").split(",")[0].strip()
    except Exception:
        ip = ""
    if not ip:
        return None
    return hashlib.sha256((ID_SALT + ip).encode()).hexdigest()[:20]


def ident():
    return client_id() or st.session_state.sid


def too_many_fails(kind):
    return (safe(lambda: store.get(f"fail:{kind}:{ident()}"), 0) or 0) >= 8


def register_fail(kind):
    safe(lambda: store.bump(f"fail:{kind}:{ident()}", 3600))


def free_used():
    cid = client_id()
    if cid:
        n = safe(lambda: store.get(f"free:{cid}"), None)
        if n is not None:
            return max(n, st.session_state.count)
    return st.session_state.count


def register_free_use():
    st.session_state.count += 1
    cid = client_id()
    if cid:
        safe(lambda: store.bump(f"free:{cid}", FREE_TTL))


def premium_key():
    return f"pday:{st.session_state.token or ident()}:{date.today().isoformat()}"


def premium_used_today():
    return safe(lambda: store.get(premium_key()), 0) or 0


def register_premium_use():
    safe(lambda: store.bump(premium_key(), 86400))


def redeem_code(raw):
    if too_many_fails("code"):
        st.error("Trop d'essais. RÃ©essaie dans une heure.")
        return
    code = normalize_code(raw)
    if len(code) != 11:
        register_fail("code")
        st.error("Code invalide. Il ressemble Ã  VOS-XXXX-XXXX.")
        return
    try:
        ok = store.redeem(code)
    except Exception as e:
        print(f"[viral-os] erreur de stockage (activation) : {e!r}")
        st.error("Service momentanÃ©ment indisponible, rÃ©essaie dans un instant. Ton code n'a pas Ã©tÃ© utilisÃ©.")
        return
    if not ok:
        register_fail("code")
        st.error("Code invalide ou dÃ©jÃ  utilisÃ©.")
        return
    token = secrets.token_urlsafe(16)
    if safe(lambda: store.add_token(token) or True, False):
        st.session_state.token = token
        try:
            st.query_params["k"] = token
        except Exception:
            pass
    st.session_state.is_premium = True
    st.rerun()


def get_video_info(vid, link):
    """yt-dlp d'abord. Si YouTube bloque le serveur, on se rabat sur oEmbed (sans vues ni durÃ©e)."""
    thumb_default = f"https://img.youtube.com/vi/{vid}/hqdefault.jpg"
    try:
        opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(link, download=False)
        return {
            "title": info.get("title") or "Sans titre",
            "uploader": info.get("uploader") or "Inconnu",
            "views": info.get("view_count") or 0,
            "thumb": info.get("thumbnail") or thumb_default,
            "duration": info.get("duration"),
            "minimal": False,
        }
    except Exception as e:
        print(f"[viral-os] yt-dlp a Ã©chouÃ©, passage Ã  oEmbed : {e!r}")
    try:
        oembed = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(link, safe="")
        with urllib.request.urlopen(oembed, timeout=10) as r:
            d = json.loads(r.read().decode("utf-8"))
        return {
            "title": d.get("title") or "Sans titre",
            "uploader": d.get("author_name") or "Inconnu",
            "views": 0,
            "thumb": d.get("thumbnail_url") or thumb_default,
            "duration": None,
            "minimal": False,
        }
    except Exception as e:
        print(f"[viral-os] oEmbed a Ã©chouÃ© aussi : {e!r}")
    return {
        "title": "VidÃ©o YouTube",
        "uploader": "Inconnu",
        "views": 0,
        "thumb": thumb_default,
        "duration": None,
        "minimal": True,
    }


def parse_json(raw):
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = raw.strip("`")
        if raw.lower().startswith("json"):
            raw = raw[4:]
    data = json.loads(raw)
    if isinstance(data, list) and data:
        data = data[0]
    if not isinstance(data, dict):
        raise ValueError("RÃ©ponse Gemini inattendue")
    return data


def build_prompt(video, link, use_video):
    if use_video:
        intro = (
            "Tu es un coach expert en croissance YouTube et TikTok. Regarde rÃ©ellement cette vidÃ©o "
            "(image et son) et analyse-la : le hook des 3 premiÃ¨res secondes, le rythme, la rÃ©tention, "
            "la fin et l'appel Ã  l'action."
        )
    else:
        intro = (
            "Tu es un coach expert en croissance YouTube et TikTok. Tu n'as accÃ¨s qu'au titre, "
            "Ã  la chaÃ®ne et au nombre de vues, pas Ã  la vidÃ©o : estime au mieux Ã  partir de Ã§a."
        )
    views = f"{video['views']:,}".replace(",", " ") if video["views"] else "inconnu"
    return f"""{intro}

Titre : {video['title']}
ChaÃ®ne : {video['uploader']}
Vues : {views}
URL : {link}

RÃ©ponds en franÃ§ais, UNIQUEMENT avec un JSON valide contenant exactement ces clÃ©s :
{{
  "resume": "de quoi parle la vidÃ©o, en 1 ou 2 phrases",
  "hook_score": nombre entre 0 et 100,
  "retention_score": nombre entre 0 et 100,
  "cta_score": nombre entre 0 et 100,
  "overall_score": nombre entre 0 et 100,
  "strengths": ["force 1", "force 2"],
  "weaknesses": ["faiblesse 1", "faiblesse 2"],
  "hooks_alternatifs": ["accroche 1", "accroche 2", "accroche 3"],
  "script_0_60": "script complet seconde par seconde de 0 Ã  60 secondes d'une version amÃ©liorÃ©e, prÃªt Ã  lire",
  "montage": "instructions de montage courtes et claires, avec des mots simples",
  "title_suggestion": "titre optimisÃ©",
  "hashtags": "#tag1 #tag2 #tag3 #tag4",
  "plan_action": ["action 1", "action 2", "action 3"]
}}
Les accroches alternatives sont des phrases Ã  dire dans les 3 premiÃ¨res secondes.
Le plan d'action contient 3 actions concrÃ¨tes Ã  faire avant de publier ou republier.
Sois ultra concret, direct et utile.
"""


def make_config(use_video):
    kwargs = {"response_mime_type": "application/json"}
    if use_video:
        try:
            # rÃ©solution basse = beaucoup moins cher pour analyser une vidÃ©o
            return types.GenerateContentConfig(
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_LOW, **kwargs
            )
        except Exception:
            pass
    return types.GenerateContentConfig(**kwargs)


def ask_gemini(video, link, use_video):
    parts = []
    if use_video:
        parts.append(types.Part(file_data=types.FileData(file_uri=link)))
    parts.append(types.Part(text=build_prompt(video, link, use_video)))
    response = client.models.generate_content(
        model=MODEL,
        contents=[types.Content(role="user", parts=parts)],
        config=make_config(use_video),
    )
    return parse_json(response.text)


@st.cache_resource
def get_client(key):
    return genai.Client(api_key=key)


client = get_client(GEMINI_API_KEY)


def plan_text(video, data):
    score = clamp(data.get("overall_score"), 80)
    hooks = n_items(data.get("hooks_alternatifs"), [], 3)
    actions = n_items(data.get("plan_action"), [], 3)
    lines = [
        "VIRAL OS - TON PLAN POUR PERCER",
        "",
        f"VidÃ©o : {video['title']} ({video['uploader']})",
        f"Score viral : {score}/100",
        "",
        "TITRE Ã€ METTRE :",
        str(data.get("title_suggestion") or video["title"]),
        "",
        "HASHTAGS :",
        str(data.get("hashtags") or ""),
        "",
        "ACCROCHES ALTERNATIVES :",
        *[f"{i}. {h}" for i, h in enumerate(hooks, 1)],
        "",
        "SCRIPT (0 Ã  60 secondes) :",
        str(data.get("script_0_60") or ""),
        "",
        "MONTAGE :",
        str(data.get("montage") or ""),
        "",
        "PLAN D'ACTION :",
        *[f"{i}. {a}" for i, a in enumerate(actions, 1)],
    ]
    return "\n".join(lines)


# ====================== STYLE ======================
render("""
<style>
.stApp {
    background: radial-gradient(circle at 20% 20%, #c4b5fd 0%, transparent 40%),
                radial-gradient(circle at 80% 10%, #93c5fd 0%, transparent 40%),
                radial-gradient(circle at 50% 90%, #f9a8d4 0%, transparent 40%),
                #f8f7ff !important;
}
.card {
    background: white;
    border-radius: 22px;
    padding: 20px;
    box-shadow: 0 10px 30px rgba(0,0,0,0.06);
    border: 1px solid rgba(0,0,0,0.05);
    margin-bottom: 16px;
}
.hero {
    background: linear-gradient(135deg, #111 0%, #333 100%);
    border-radius: 24px;
    padding: 26px;
    color: white;
    margin-bottom: 20px;
}
.stTextInput input {
    border-radius: 100px !important;
    height: 54px !important;
}
</style>
""")

# ====================== HERO ======================
render(f"""
<div class="hero">
<div style="display:flex; justify-content:space-between;">
<span style="background: rgba(255,255,255,0.15); padding:5px 12px; border-radius:100px; font-size:11px;">âœ¨ INSPIRÃ‰ DE BLOW UP</span>
<span style="opacity:0.5; font-size:11px;">VIRAL OS {VERSION}</span>
</div>
<h1 style="margin:14px 0 4px 0; font-size:32px;">VIRAL OS ðŸš€</h1>
<p style="opacity:0.7; margin:0; font-size:14px;">Colle un lien. On te dit tout ce que tu dois refaire pour percer.</p>
</div>
""")

url = st.text_input("Lien YouTube", placeholder="ðŸ”— Colle ton lien YouTube ici...", label_visibility="collapsed")


# ====================== AFFICHAGE ======================
def unlock_card():
    render(f"""
<div class="card" style="text-align:center; border: 2px dashed #d6c7ff;">
<div style="font-size:40px;">ðŸ”’</div>
<p style="font-weight:800; color:#111; margin:8px 0 4px 0;">SCRIPT COMPLET + MONTAGE + TITRE + 3 ACCROCHES + PLAN D'ACTION</p>
<p style="color:#888; font-size:12px; margin:0 0 12px 0;">60 secondes mot pour mot, bloquÃ© en premium</p>
<a href="{LINK}" target="_blank" rel="noopener" style="text-decoration:none;">
<div style="background:black; color:white; padding:14px; border-radius:100px; font-weight:800;">
ðŸ”“ DÃ‰BLOQUER POUR 9,99â‚¬
</div>
</a>
<p style="color:#aaa; font-size:11px; margin-top:8px;">Tu reÃ§ois un code, tu l'entres dans la barre latÃ©rale. Comme Blow Up mais sans abonnement</p>
</div>
""")


def show_results(video, data, watched):
    score = clamp(data.get("overall_score"), 80)
    hook = clamp(data.get("hook_score"), 85)
    retention = clamp(data.get("retention_score"), 75)
    cta = clamp(data.get("cta_score"), 50)
    strengths = n_items(data.get("strengths"), ["DÃ©but accrocheur", "Sujet porteur"], 2)
    weaknesses = n_items(data.get("weaknesses"), ["RÃ©tention moyenne", "Pas de CTA clair"], 2)
    hooks = n_items(data.get("hooks_alternatifs"), [], 3)
    actions = n_items(data.get("plan_action"), [], 3)
    resume = data.get("resume") or ""
    script = data.get("script_0_60") or "Script non gÃ©nÃ©rÃ©"
    montage = data.get("montage") or "Montage non gÃ©nÃ©rÃ©"
    title_sugg = data.get("title_suggestion") or video["title"]
    hashtags = data.get("hashtags") or "#viral #youtube"

    views = video["views"]
    views_badge = ""
    if views:
        views_txt = f"{views:,}".replace(",", " ")
        views_badge = (
            '<span style="background:#ede9fe; color:#6d28d9; padding:4px 10px; border-radius:100px; '
            f'font-size:11px; font-weight:700;">ðŸ”¥ {views_txt} VUES</span>'
        )
    viral_badge = ""
    if views >= 100_000:
        viral_badge = (
            '<span style="background:#dcfce7; color:#15803d; padding:4px 10px; border-radius:100px; '
            'font-size:11px; font-weight:700;">VIRAL</span>'
        )
    mode_txt = "ðŸŽ¥ VidÃ©o analysÃ©e" if watched else "ðŸ“ Analyse du titre"
    mode_badge = (
        '<span style="background:#f3f4f6; color:#374151; padding:4px 10px; border-radius:100px; '
        f'font-size:11px; font-weight:700;">{mode_txt}</span>'
    )
    thumb_html = f'<img src="{esc(video["thumb"])}" style="width:100%;">' if video["thumb"] else ""
    resume_html = (
        f'<p style="color:#444; font-size:13px; margin:10px 0 0 0; line-height:1.5;">{esc(resume)}</p>'
        if resume else ""
    )

    render(f"""
<div class="card" style="padding:0; overflow:hidden;">
{thumb_html}
<div style="padding:16px;">
<div style="display:flex; gap:8px; align-items:center; flex-wrap:wrap;">
{views_badge}
{viral_badge}
{mode_badge}
</div>
<h3 style="margin:10px 0 0 0; color:#111; font-size:17px;">{esc(video['title'])}</h3>
<p style="color:#888; font-size:12px; margin:4px 0 0 0;">Par {esc(video['uploader'])}</p>
{resume_html}
</div>
</div>
""")

    c1, c2 = st.columns(2)
    with c1:
        render(f"""
<div class="card" style="text-align:center;">
<div style="width:70px; height:70px; border-radius:100px; background: conic-gradient(#8b5cf6 0% {score}%, #eee {score}% 100%); margin:0 auto; display:flex; align-items:center; justify-content:center;">
<div style="width:54px; height:54px; background:white; border-radius:100px; display:flex; align-items:center; justify-content:center; font-weight:900; color:#111;">{score}</div>
</div>
<p style="font-weight:800; margin:8px 0 0 0; color:#111;">Score Viral</p>
<p style="font-size:11px; color:#888; margin:0;">sur 100</p>
</div>
""")

    with c2:
        render(f"""
<div class="card">
<p style="font-size:11px; font-weight:800; color:#999; letter-spacing:1px; margin:0 0 10px 0;">PERFORMANCE</p>
<div style="margin-bottom:8px;">
<span style="font-size:12px; color:#111;">Hook 0-3s</span>
<div style="background:#eee; height:6px; border-radius:10px; margin-top:4px;">
<div style="background:#8b5cf6; width:{hook}%; height:6px; border-radius:10px;"></div>
</div>
</div>
<div style="margin-bottom:8px;">
<span style="font-size:12px; color:#111;">RÃ©tention</span>
<div style="background:#eee; height:6px; border-radius:10px; margin-top:4px;">
<div style="background:#22c55e; width:{retention}%; height:6px; border-radius:10px;"></div>
</div>
</div>
<div>
<span style="font-size:12px; color:#111;">Fin / CTA</span>
<div style="background:#eee; height:6px; border-radius:10px; margin-top:4px;">
<div style="background:#f59e0b; width:{cta}%; height:6px; border-radius:10px;"></div>
</div>
</div>
</div>
""")

    render(f"""
<div class="card">
<p style="font-size:11px; font-weight:800; color:#999; letter-spacing:1px; margin:0 0 12px 0;">CE QUE GEMINI A DÃ‰TECTÃ‰</p>
<div style="display:flex; gap:16px;">
<div style="flex:1;">
<p style="color:#16a34a; font-weight:800; font-size:13px; margin:0 0 6px 0;">âœ… FORCES</p>
<p style="color:#111; font-size:13px; margin:3px 0;">â€¢ {esc(strengths[0])}</p>
<p style="color:#111; font-size:13px; margin:3px 0;">â€¢ {esc(strengths[1])}</p>
</div>
<div style="flex:1;">
<p style="color:#dc2626; font-weight:800; font-size:13px; margin:0 0 6px 0;">âš ï¸ FAIBLESSES</p>
<p style="color:#111; font-size:13px; margin:3px 0;">â€¢ {esc(weaknesses[0])}</p>
<p style="color:#111; font-size:13px; margin:3px 0;">â€¢ {esc(weaknesses[1])}</p>
</div>
</div>
</div>
""")

    if not st.session_state.is_premium:
        unlock_card()
        return

    target = max(score, min(97, score + 12))
    hooks_html = "<br>".join(f"<b>{i}.</b> {esc(h)}" for i, h in enumerate(hooks, 1)) or "â€”"
    actions_html = "<br>".join(f"<b>{i}.</b> {esc(a)}" for i, a in enumerate(actions, 1)) or "â€”"
    render(f"""
<div class="card" style="border: 2px solid #8b5cf6;">
<div style="display:flex; align-items:center; gap:10px; margin-bottom:18px;">
<div style="background: linear-gradient(135deg, #8b5cf6, #60a5fa); width:32px; height:32px; border-radius:100px; display:flex; align-items:center; justify-content:center;">ðŸš€</div>
<p style="font-weight:900; color:#111; margin:0; font-size:17px;">TON PLAN POUR PERCER</p>
<span style="margin-left:auto; background:#22c55e; color:white; padding:4px 12px; border-radius:100px; font-size:12px; font-weight:800;">PREMIUM</span>
</div>
<div style="background:#fff7ed; border-radius:16px; padding:18px; margin-bottom:16px;">
<p style="color:#c2410c; font-weight:800; font-size:14px; margin:0 0 12px 0;">âš¡ 3 ACCROCHES POUR LES 3 PREMIÃˆRES SECONDES</p>
<p style="color:#111; font-size:15px; line-height:1.65; margin:0;">{hooks_html}</p>
</div>
<div style="background:#f5f3ff; border-radius:16px; padding:18px; margin-bottom:16px;">
<p style="color:#6d28d9; font-weight:800; font-size:14px; margin:0 0 12px 0;">ðŸ“ SCRIPT Ã€ DIRE (0 Ã  60 secondes)</p>
<p style="color:#111; font-size:15px; line-height:1.65; margin:0;">{esc(script)}</p>
</div>
<div style="background:#eff6ff; border-radius:16px; padding:18px; margin-bottom:16px;">
<p style="color:#1d4ed8; font-weight:800; font-size:14px; margin:0 0 10px 0;">ðŸŽ¬ COMMENT MONTER LA VIDÃ‰O</p>
<p style="color:#111; font-size:15px; margin:0; line-height:1.6;">{esc(montage)}</p>
</div>
<div style="background:#f0fdf4; border-radius:16px; padding:18px; margin-bottom:16px;">
<p style="color:#15803d; font-weight:800; font-size:14px; margin:0 0 12px 0;">ðŸ“Œ TITRE ET HASHTAGS</p>
<p style="color:#111; font-size:15px; margin:0 0 8px 0;">
<b>Titre Ã  mettre :</b><br>
{esc(title_sugg)}
</p>
<p style="color:#111; font-size:15px; margin:12px 0 0 0;">
<b>Hashtags Ã  mettre :</b><br>
{esc(hashtags)}
</p>
</div>
<div style="background:#fef2f2; border-radius:16px; padding:18px; margin-bottom:16px;">
<p style="color:#b91c1c; font-weight:800; font-size:14px; margin:0 0 12px 0;">âœ… PLAN D'ACTION AVANT DE PUBLIER</p>
<p style="color:#111; font-size:15px; line-height:1.65; margin:0;">{actions_html}</p>
</div>
<div style="background:black; border-radius:14px; padding:16px; text-align:center;">
<p style="color:white; margin:0; font-weight:800; font-size:16px;">
Score actuel : {score}% â†’ Possible dâ€™atteindre {target}%
</p>
</div>
</div>
""")
    st.download_button(
        "â¬‡ï¸ TÃ©lÃ©charger mon plan (.txt)",
        data=plan_text(video, data),
        file_name="viral-os-plan.txt",
        mime="text/plain",
        use_container_width=True,
    )


# ====================== ANALYSE ======================
def analyze(raw_url):
    link = raw_url.strip()
    if not link.startswith(("http://", "https://")):
        link = "https://" + link

    if not is_youtube_url(link):
        st.warning("Colle un lien YouTube valide (youtube.com ou youtu.be).")
        return
    vid = extract_video_id(link)
    if not vid:
        st.warning("Colle le lien d'une vidÃ©o (pas d'une chaÃ®ne ou d'une playlist).")
        return
    link = f"https://www.youtube.com/watch?v={vid}"

    premium = st.session_state.is_premium
    if not premium and free_used() >= FREE_LIMIT:
        st.warning(f"Tu as utilisÃ© tes {FREE_LIMIT} analyses gratuites.")
        unlock_card()
        return
    if premium and premium_used_today() >= PREMIUM_DAILY_LIMIT:
        st.warning(f"Tu as atteint la limite de {PREMIUM_DAILY_LIMIT} analyses aujourd'hui. Reviens demain ðŸ™‚")
        return

    with st.spinner("Analyse en cours avec Gemini..."):
        video = get_video_info(vid, link)
        data = None
        watched = False

        duration = video.get("duration")
        if duration is None or duration <= MAX_VIDEO_SECONDS:
            try:
                data = ask_gemini(video, link, True)
                watched = True
            except Exception as e:
                print(f"[viral-os] analyse vidÃ©o impossible, repli sur le titre : {e!r}")

        if data is None and not video["minimal"]:
            try:
                data = ask_gemini(video, link, False)
            except Exception as e:
                print(f"[viral-os] erreur d'analyse : {e!r}")

    if data is None:
        st.error("Impossible d'analyser cette vidÃ©o pour le moment. RÃ©essaie dans un instant ou essaie un autre lien.")
        return

    if premium:
        register_premium_use()
    else:
        register_free_use()

    st.session_state.last = {"video": video, "data": data, "watched": watched}
    st.session_state.history.append(
        {"title": video["title"], "score": clamp(data.get("overall_score"), 80)}
    )


if st.button("Analyser ma vidÃ©o â†’", use_container_width=True, type="primary"):
    if not url.strip():
        st.warning("Colle un lien d'abord")
    else:
        analyze(url)

if st.session_state.last:
    show_results(**st.session_state.last)

# ====================== SIDEBAR ======================
with st.sidebar:
    if st.session_state.is_premium:
        st.write("**Premium actif âœ…**")
        st.caption(f"{premium_used_today()}/{PREMIUM_DAILY_LIMIT} analyses aujourd'hui")
        if st.session_state.token:
            st.caption("Mets cette page en favori : le lien garde ton accÃ¨s premium.")
    else:
        st.write(f"**{min(free_used(), FREE_LIMIT)}/{FREE_LIMIT} gratuites**")
        code_in = st.text_input("Code", placeholder="VOS-XXXX-XXXX", max_chars=24, key="code_input")
        if st.button("Activer"):
            redeem_code(code_in)

    if st.session_state.history:
        st.divider()
        st.caption("DerniÃ¨res analyses")
        for item in reversed(st.session_state.history[-5:]):
            st.caption(f"{item['score']}/100 Â· {item['title'][:40]}".replace("$", "\\$"))

    # Panneau admin : visible seulement avec ?admin=1 dans l'adresse
    try:
        show_admin = bool(st.query_params.get("admin"))
    except Exception:
        show_admin = False
    if show_admin:
        st.divider()
        with st.expander("ðŸ”§ Admin"):
            if not ADMIN_PASSWORD:
                st.caption("Ajoute ADMIN_PASSWORD dans les Secrets pour activer ce panneau.")
            elif not st.session_state.admin_ok:
                pwd = st.text_input("Mot de passe admin", type="password", key="admin_pwd")
                if st.button("Connexion"):
                    if too_many_fails("admin"):
                        st.error("Trop d'essais. RÃ©essaie dans une heure.")
                    elif hmac.compare_digest(pwd.encode(), ADMIN_PASSWORD.encode()):
                        st.session_state.admin_ok = True
                        st.rerun()
                    else:
                        register_fail("admin")
                        st.error("Mot de passe incorrect")
            else:
                if not store.persistent:
                    st.warning(
                        "Stockage local : les codes peuvent se rÃ©initialiser quand l'app redÃ©marre. "
                        "Configure Upstash pour un stockage permanent."
                    )
                remaining = safe(store.count_codes, None)
                st.write(f"**{remaining if remaining is not None else '?'} codes restants**")
                n_new = st.number_input("Combien de codes crÃ©er ?", min_value=1, max_value=50, value=10, step=1)
                if st.button("GÃ©nÃ©rer des codes"):
                    new_codes = generate_codes(int(n_new))
                    if safe(lambda: store.add_codes(new_codes) or True, False):
                        st.session_state.new_codes = [pretty_code(c) for c in new_codes]
                    else:
                        st.error("Impossible d'enregistrer les codes (stockage indisponible).")
                new_codes = st.session_state.get("new_codes")
                if new_codes:
                    st.caption("Nouveaux codes (copie-les maintenant) :")
                    st.code("\n".join(new_codes), language=None)
                    st.download_button("TÃ©lÃ©charger la liste", "\n".join(new_codes), file_name="codes-viral-os.txt")
                if st.button("Voir tous les codes restants"):
                    left = safe(store.members, [])
                    st.code("\n".join(pretty_code(c) for c in left) or "(aucun)", language=None)
                if st.button("Se dÃ©connecter"):
                    st.session_state.admin_ok = False
                    st.session_state.new_codes = None
                    st.rerun()
