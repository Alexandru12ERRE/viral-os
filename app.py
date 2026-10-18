import hmac
import html
import json
import os
import urllib.parse
import urllib.request

import streamlit as st
import yt_dlp
from google import genai
from google.genai import types

# ====================== CONFIG ======================
LINK = "https://buy.stripe.com/aFa7sN3E96m71RL9nQ5Ne02"
MODEL = "gemini-flash-latest"  # pointe toujours vers le dernier Flash stable
FREE_LIMIT = 5

st.set_page_config(page_title="VIRAL OS", page_icon="🚀", layout="centered")


def get_secret(name):
    """Lit un secret Streamlit, ou une variable d'environnement en secours."""
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.getenv(name)


GEMINI_API_KEY = get_secret("GEMINI_API_KEY")
PREMIUM_CODE = get_secret("PREMIUM_CODE")

if not GEMINI_API_KEY:
    st.error("Clé GEMINI_API_KEY manquante. Ajoute-la dans Manage app → Settings → Secrets.")
    st.stop()


@st.cache_resource
def get_client(key):
    return genai.Client(api_key=key)


client = get_client(GEMINI_API_KEY)

st.session_state.setdefault("count", 0)
st.session_state.setdefault("is_premium", False)


# ====================== OUTILS ======================
def render(markup):
    """Affiche du HTML sans lignes vides ni indentation (sinon Streamlit casse le rendu)."""
    cleaned = "\n".join(line.strip() for line in markup.splitlines() if line.strip())
    st.markdown(cleaned, unsafe_allow_html=True)


def esc(value):
    """Échappe le texte venant de YouTube ou de Gemini avant de l'afficher en HTML."""
    text = html.escape(str(value))
    text = text.replace("$", "&#36;")  # évite que Streamlit lise $...$ comme des maths
    return text.replace("\r\n", "\n").replace("\n", "<br>")


def clamp(value, default):
    try:
        return max(0, min(100, int(float(value))))
    except (TypeError, ValueError):
        return default


def two_items(value, defaults):
    items = [str(v) for v in value if str(v).strip()] if isinstance(value, list) else []
    return (items + defaults)[:2]


def code_ok(code):
    if not PREMIUM_CODE or not code:
        return False
    return hmac.compare_digest(code.strip().encode(), PREMIUM_CODE.strip().encode())


def is_youtube_url(u):
    try:
        host = (urllib.parse.urlparse(u).hostname or "").lower()
    except ValueError:
        return False
    return host in ("youtu.be", "youtube.com") or host.endswith(".youtube.com")


def get_video_info(url):
    """yt-dlp d'abord. Si YouTube bloque le serveur, on se rabat sur oEmbed (sans les vues)."""
    try:
        opts = {"quiet": True, "no_warnings": True, "noplaylist": True, "skip_download": True}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
        return {
            "title": info.get("title") or "Sans titre",
            "uploader": info.get("uploader") or "Inconnu",
            "views": info.get("view_count") or 0,
            "thumb": info.get("thumbnail") or "",
        }
    except Exception as e:
        print(f"[viral-os] yt-dlp a échoué, passage à oEmbed : {e!r}")

    oembed = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(url, safe="")
    with urllib.request.urlopen(oembed, timeout=10) as r:
        d = json.loads(r.read().decode("utf-8"))
    return {
        "title": d.get("title") or "Sans titre",
        "uploader": d.get("author_name") or "Inconnu",
        "views": 0,
        "thumb": d.get("thumbnail_url") or "",
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
        raise ValueError("Réponse Gemini inattendue")
    return data


def ask_gemini(video, url):
    prompt = f"""
Tu es un coach expert en croissance YouTube et TikTok.
Analyse cette vidéo. Tu n'as accès qu'au titre, à la chaîne et au nombre de vues : estime au mieux à partir de ça.

Titre : {video['title']}
Chaîne : {video['uploader']}
Vues : {video['views'] or 'inconnu'}
URL : {url}

Réponds en français, UNIQUEMENT avec un JSON valide contenant exactement ces clés :
{{
  "hook_score": nombre entre 0 et 100,
  "retention_score": nombre entre 0 et 100,
  "cta_score": nombre entre 0 et 100,
  "overall_score": nombre entre 0 et 100,
  "strengths": ["force 1", "force 2"],
  "weaknesses": ["faiblesse 1", "faiblesse 2"],
  "script_0_60": "script complet seconde par seconde de 0 à 60 secondes, prêt à lire",
  "montage": "instructions de montage courtes et claires, avec des mots simples",
  "title_suggestion": "titre optimisé",
  "hashtags": "#tag1 #tag2 #tag3 #tag4"
}}
Sois ultra concret, direct et utile.
"""
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return parse_json(response.text)


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
render("""
<div class="hero">
<div style="display:flex; justify-content:space-between;">
<span style="background: rgba(255,255,255,0.15); padding:5px 12px; border-radius:100px; font-size:11px;">✨ INSPIRÉ DE BLOW UP</span>
<span style="opacity:0.5; font-size:11px;">VIRAL OS v8</span>
</div>
<h1 style="margin:14px 0 4px 0; font-size:32px;">VIRAL OS 🚀</h1>
<p style="opacity:0.7; margin:0; font-size:14px;">Colle un lien. On te dit tout ce que tu dois refaire pour percer.</p>
</div>
""")

url = st.text_input("Lien YouTube", placeholder="🔗 Colle ton lien YouTube ici...", label_visibility="collapsed")


# ====================== AFFICHAGE ======================
def unlock_card():
    render(f"""
<div class="card" style="text-align:center; border: 2px dashed #d6c7ff;">
<div style="font-size:40px;">🔒</div>
<p style="font-weight:800; color:#111; margin:8px 0 4px 0;">TON SCRIPT COMPLET + MONTAGE + TITRE</p>
<p style="color:#888; font-size:12px; margin:0 0 12px 0;">60 secondes mot pour mot, bloqué en premium</p>
<a href="{LINK}" target="_blank" rel="noopener" style="text-decoration:none;">
<div style="background:black; color:white; padding:14px; border-radius:100px; font-weight:800;">
🔓 DÉBLOQUER POUR 9,99€
</div>
</a>
<p style="color:#aaa; font-size:11px; margin-top:8px;">Comme Blow Up mais sans abonnement</p>
</div>
""")


def show_results(video, data):
    score = clamp(data.get("overall_score"), 80)
    hook = clamp(data.get("hook_score"), 85)
    retention = clamp(data.get("retention_score"), 75)
    cta = clamp(data.get("cta_score"), 50)
    strengths = two_items(data.get("strengths"), ["Début accrocheur", "Sujet porteur"])
    weaknesses = two_items(data.get("weaknesses"), ["Rétention moyenne", "Pas de CTA clair"])
    script = data.get("script_0_60") or "Script non généré"
    montage = data.get("montage") or "Montage non généré"
    title_sugg = data.get("title_suggestion") or video["title"]
    hashtags = data.get("hashtags") or "#viral #youtube"

    views = video["views"]
    views_badge = ""
    if views:
        views_txt = f"{views:,}".replace(",", " ")
        views_badge = (
            '<span style="background:#ede9fe; color:#6d28d9; padding:4px 10px; border-radius:100px; '
            f'font-size:11px; font-weight:700;">🔥 {views_txt} VUES</span>'
        )
    viral_badge = ""
    if views >= 100_000:
        viral_badge = (
            '<span style="background:#dcfce7; color:#15803d; padding:4px 10px; border-radius:100px; '
            'font-size:11px; font-weight:700;">VIRAL</span>'
        )
    thumb_html = f'<img src="{esc(video["thumb"])}" style="width:100%;">' if video["thumb"] else ""

    render(f"""
<div class="card" style="padding:0; overflow:hidden;">
{thumb_html}
<div style="padding:16px;">
<div style="display:flex; gap:8px; align-items:center;">
{views_badge}
{viral_badge}
</div>
<h3 style="margin:10px 0 0 0; color:#111; font-size:17px;">{esc(video['title'])}</h3>
<p style="color:#888; font-size:12px; margin:4px 0 0 0;">Par {esc(video['uploader'])}</p>
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
<span style="font-size:12px; color:#111;">Rétention</span>
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
<p style="font-size:11px; font-weight:800; color:#999; letter-spacing:1px; margin:0 0 12px 0;">CE QUE GEMINI A DÉTECTÉ</p>
<div style="display:flex; gap:16px;">
<div style="flex:1;">
<p style="color:#16a34a; font-weight:800; font-size:13px; margin:0 0 6px 0;">✅ FORCES</p>
<p style="color:#111; font-size:13px; margin:3px 0;">• {esc(strengths[0])}</p>
<p style="color:#111; font-size:13px; margin:3px 0;">• {esc(strengths[1])}</p>
</div>
<div style="flex:1;">
<p style="color:#dc2626; font-weight:800; font-size:13px; margin:0 0 6px 0;">⚠️ FAIBLESSES</p>
<p style="color:#111; font-size:13px; margin:3px 0;">• {esc(weaknesses[0])}</p>
<p style="color:#111; font-size:13px; margin:3px 0;">• {esc(weaknesses[1])}</p>
</div>
</div>
</div>
""")

    if st.session_state.is_premium:
        target = max(score, min(97, score + 12))
        render(f"""
<div class="card" style="border: 2px solid #8b5cf6;">
<div style="display:flex; align-items:center; gap:10px; margin-bottom:18px;">
<div style="background: linear-gradient(135deg, #8b5cf6, #60a5fa); width:32px; height:32px; border-radius:100px; display:flex; align-items:center; justify-content:center;">🚀</div>
<p style="font-weight:900; color:#111; margin:0; font-size:17px;">TON PLAN POUR PERCER</p>
<span style="margin-left:auto; background:#22c55e; color:white; padding:4px 12px; border-radius:100px; font-size:12px; font-weight:800;">PREMIUM</span>
</div>
<div style="background:#f5f3ff; border-radius:16px; padding:18px; margin-bottom:16px;">
<p style="color:#6d28d9; font-weight:800; font-size:14px; margin:0 0 12px 0;">📝 SCRIPT À DIRE (0 à 60 secondes)</p>
<p style="color:#111; font-size:15px; line-height:1.65; margin:0;">{esc(script)}</p>
</div>
<div style="background:#eff6ff; border-radius:16px; padding:18px; margin-bottom:16px;">
<p style="color:#1d4ed8; font-weight:800; font-size:14px; margin:0 0 10px 0;">🎬 COMMENT MONTER LA VIDÉO</p>
<p style="color:#111; font-size:15px; margin:0; line-height:1.6;">{esc(montage)}</p>
</div>
<div style="background:#f0fdf4; border-radius:16px; padding:18px; margin-bottom:16px;">
<p style="color:#15803d; font-weight:800; font-size:14px; margin:0 0 12px 0;">📌 TITRE ET HASHTAGS</p>
<p style="color:#111; font-size:15px; margin:0 0 8px 0;">
<b>Titre à mettre :</b><br>
{esc(title_sugg)}
</p>
<p style="color:#111; font-size:15px; margin:12px 0 0 0;">
<b>Hashtags à mettre :</b><br>
{esc(hashtags)}
</p>
</div>
<div style="background:black; border-radius:14px; padding:16px; text-align:center;">
<p style="color:white; margin:0; font-weight:800; font-size:16px;">
Score actuel : {score}% → Possible d’atteindre {target}%
</p>
</div>
</div>
""")
    else:
        unlock_card()


# ====================== ANALYSE ======================
def analyze(raw_url):
    link = raw_url.strip()
    if not link.startswith(("http://", "https://")):
        link = "https://" + link

    if not is_youtube_url(link):
        st.warning("Colle un lien YouTube valide (youtube.com ou youtu.be).")
        return

    if not st.session_state.is_premium and st.session_state.count >= FREE_LIMIT:
        st.warning(f"Tu as utilisé tes {FREE_LIMIT} analyses gratuites.")
        unlock_card()
        return

    with st.spinner("Analyse en cours avec Gemini..."):
        try:
            video = get_video_info(link)
            data = ask_gemini(video, link)
        except Exception as e:
            print(f"[viral-os] erreur d'analyse : {e!r}")
            st.error("Impossible d'analyser cette vidéo pour le moment. Réessaie dans un instant ou essaie un autre lien.")
            return

    if not st.session_state.is_premium:
        st.session_state.count += 1

    show_results(video, data)


if st.button("Analyser ma vidéo →", use_container_width=True, type="primary"):
    if not url.strip():
        st.warning("Colle un lien d'abord")
    else:
        analyze(url)

# ====================== SIDEBAR ======================
with st.sidebar:
    if st.session_state.is_premium:
        st.write("**Premium actif ✅**")
    else:
        st.write(f"**{min(st.session_state.count, FREE_LIMIT)}/{FREE_LIMIT} gratuites**")
        code = st.text_input("Code", placeholder="Ton code premium", type="password")
        if st.button("Activer"):
            if code_ok(code):
                st.session_state.is_premium = True
                st.rerun()
            else:
                st.error("Code invalide")
