import streamlit as st
import yt_dlp
import json
import os
import random
from google import genai

# ====================== CONFIG ======================
LINK = "https://buy.stripe.com/aFa7sN3E96m71RL9nQ5Ne02"
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

client = genai.Client(api_key=GEMINI_API_KEY)

st.set_page_config(page_title="VIRAL OS", page_icon="🚀", layout="centered")

if "count" not in st.session_state:
    st.session_state.count = 0
    st.session_state.is_premium = False
    st.session_state.history = []

# ====================== STYLE ======================
st.markdown("""
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
""", unsafe_allow_html=True)

# ====================== HERO ======================
st.markdown("""
<div class="hero">
    <div style="display:flex; justify-content:space-between;">
        <span style="background: rgba(255,255,255,0.15); padding:5px 12px; border-radius:100px; font-size:11px;">✨ INSPIRÉ DE BLOW UP</span>
        <span style="opacity:0.5; font-size:11px;">VIRAL OS v8</span>
    </div>
    <h1 style="margin:14px 0 4px 0; font-size:32px;">VIRAL OS 🚀</h1>
    <p style="opacity:0.7; margin:0; font-size:14px;">Colle un lien. On te dit tout ce que tu dois refaire pour percer.</p>
</div>
""", unsafe_allow_html=True)

url = st.text_input("", placeholder="🔗 Colle ton lien YouTube ici...")

# ====================== ANALYSE ======================
if st.button("Analyser ma vidéo →", use_container_width=True, type="primary"):
    if not url:
        st.warning("Colle un lien d'abord")
        st.stop()

    with st.spinner("Analyse en cours avec Gemini..."):
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(url, download=False)

            if not st.session_state.is_premium:
                st.session_state.count += 1

            views = info.get('view_count', 0) or 0
            title = info.get('title', 'Sans titre')
            uploader = info.get('uploader', 'Inconnu')
            thumb = info.get('thumbnail', '')

            prompt = f"""
Tu es un coach expert en croissance YouTube et TikTok.
Analyse cette vidéo :

Titre : {title}
Chaîne : {uploader}
Vues : {views}
URL : {url}

Réponds UNIQUEMENT avec un JSON valide (pas de markdown, pas de ```json) contenant exactement ces clés :
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
                model="gemini-3.8-flash",
                contents=prompt
            )

            raw = response.text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            data = json.loads(raw)

            score = data.get("overall_score", random.randint(80, 92))
            hook = data.get("hook_score", 85)
            retention = data.get("retention_score", 75)
            cta = data.get("cta_score", 50)
            strengths = data.get("strengths", ["Début accrocheur", "Sujet porteur"])
            weaknesses = data.get("weaknesses", ["Rétention moyenne", "Pas de CTA clair"])
            script = data.get("script_0_60", "Script non généré")
            montage = data.get("montage", "Montage non généré")
            title_sugg = data.get("title_suggestion", title)
            hashtags = data.get("hashtags", "#viral #youtube")

            # ====================== AFFICHAGE ======================
            st.markdown(f"""
            <div class="card" style="padding:0; overflow:hidden;">
                <img src="{thumb}" style="width:100%;">
                <div style="padding:16px;">
                    <div style="display:flex; gap:8px; align-items:center;">
                        <span style="background:#ede9fe; color:#6d28d9; padding:4px 10px; border-radius:100px; font-size:11px; font-weight:700;">🔥 {views:,} VUES</span>
                        <span style="background:#dcfce7; color:#15803d; padding:4px 10px; border-radius:100px; font-size:11px; font-weight:700;">VIRAL</span>
                    </div>
                    <h3 style="margin:10px 0 0 0; color:#111; font-size:17px;">{title}</h3>
                    <p style="color:#888; font-size:12px; margin:4px 0 0 0;">Par {uploader}</p>
                </div>
            </div>
            """, unsafe_allow_html=True)

            c1, c2 = st.columns(2)
            with c1:
                st.markdown(f"""
                <div class="card" style="text-align:center;">
                    <div style="width:70px; height:70px; border-radius:100px; background: conic-gradient(#8b5cf6 0% {score}%, #eee {score}% 100%); margin:0 auto; display:flex; align-items:center; justify-content:center;">
                        <div style="width:54px; height:54px; background:white; border-radius:100px; display:flex; align-items:center; justify-content:center; font-weight:900;">{score}</div>
                    </div>
                    <p style="font-weight:800; margin:8px 0 0 0; color:#111;">Score Viral</p>
                    <p style="font-size:11px; color:#888; margin:0;">sur 100</p>
                </div>
                """, unsafe_allow_html=True)

            with c2:
                st.markdown(f"""
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
                """, unsafe_allow_html=True)

            st.markdown(f"""
            <div class="card">
                <p style="font-size:11px; font-weight:800; color:#999; letter-spacing:1px; margin:0 0 12px 0;">CE QUE GEMINI A DÉTECTÉ</p>
                <div style="display:flex; gap:16px;">
                    <div style="flex:1;">
                        <p style="color:#16a34a; font-weight:800; font-size:13px; margin:0 0 6px 0;">✅ FORCES</p>
                        <p style="color:#111; font-size:13px; margin:3px 0;">• {strengths[0]}</p>
                        <p style="color:#111; font-size:13px; margin:3px 0;">• {strengths[1]}</p>
                    </div>
                    <div style="flex:1;">
                        <p style="color:#dc2626; font-weight:800; font-size:13px; margin:0 0 6px 0;">⚠️ FAIBLESSES</p>
                        <p style="color:#111; font-size:13px; margin:3px 0;">• {weaknesses[0]}</p>
                        <p style="color:#111; font-size:13px; margin:3px 0;">• {weaknesses[1]}</p>
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # ====================== PREMIUM (VERSION SIMPLIFIÉE) ======================
            if st.session_state.is_premium:
                st.markdown(f"""
                <div class="card" style="border: 2px solid #8b5cf6;">
                    <div style="display:flex; align-items:center; gap:10px; margin-bottom:18px;">
                        <div style="background: linear-gradient(135deg, #8b5cf6, #60a5fa); width:32px; height:32px; border-radius:100px; display:flex; align-items:center; justify-content:center;">🚀</div>
                        <p style="font-weight:900; color:#111; margin:0; font-size:17px;">TON PLAN POUR PERCER</p>
                        <span style="margin-left:auto; background:#22c55e; color:white; padding:4px 12px; border-radius:100px; font-size:12px; font-weight:800;">PREMIUM</span>
                    </div>

                    <!-- SCRIPT -->
                    <div style="background:#f5f3ff; border-radius:16px; padding:18px; margin-bottom:16px;">
                        <p style="color:#6d28d9; font-weight:800; font-size:14px; margin:0 0 12px 0;">📝 SCRIPT À DIRE (0 à 60 secondes)</p>
                        <p style="color:#111; font-size:15px; line-height:1.65; margin:0; white-space:pre-wrap;">{script}</p>
                    </div>

                    <!-- MONTAGE -->
                    <div style="background:#eff6ff; border-radius:16px; padding:18px; margin-bottom:16px;">
                        <p style="color:#1d4ed8; font-weight:800; font-size:14px; margin:0 0 10px 0;">🎬 COMMENT MONTER LA VIDÉO</p>
                        <p style="color:#111; font-size:15px; margin:0; line-height:1.6;">{montage}</p>
                    </div>

                    <!-- TITRE + HASHTAGS -->
                    <div style="background:#f0fdf4; border-radius:16px; padding:18px; margin-bottom:16px;">
                        <p style="color:#15803d; font-weight:800; font-size:14px; margin:0 0 12px 0;">📌 TITRE ET HASHTAGS</p>
                        
                        <p style="color:#111; font-size:15px; margin:0 0 8px 0;">
                            <b>Titre à mettre :</b><br>
                            {title_sugg}
                        </p>
                        
                        <p style="color:#111; font-size:15px; margin:12px 0 0 0;">
                            <b>Hashtags à mettre :</b><br>
                            {hashtags}
                        </p>
                    </div>

                    <!-- SCORE -->
                    <div style="background:black; border-radius:14px; padding:16px; text-align:center;">
                        <p style="color:white; margin:0; font-weight:800; font-size:16px;">
                            Score actuel : {score}% → Possible d’atteindre {min(97, score + 12)}%
                        </p>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            else:
                st.markdown(f"""
                <div class="card" style="text-align:center; border: 2px dashed #d6c7ff;">
                    <div style="font-size:40px;">🔒</div>
                    <p style="font-weight:800; color:#111; margin:8px 0 4px 0;">TON SCRIPT COMPLET + MONTAGE + TITRE</p>
                    <p style="color:#888; font-size:12px; margin:0 0 12px 0;">60 secondes mot pour mot, bloqué en premium</p>
                    <a href="{LINK}" target="_blank" style="text-decoration:none;">
                        <div style="background:black; color:white; padding:14px; border-radius:100px; font-weight:800;">
                            🔓 DÉBLOQUER POUR 9,99€
                        </div>
                    </a>
                    <p style="color:#aaa; font-size:11px; margin-top:8px;">Comme Blow Up mais sans abonnement</p>
                </div>
                """, unsafe_allow_html=True)

        except Exception as e:
            st.error(f"Erreur : {e}")

# ====================== SIDEBAR ======================
with st.sidebar:
    st.write(f"**{st.session_state.count}/5 gratuites**")
    code = st.text_input("Code", placeholder="PREMIUM2026")
    if st.button("Activer"):
        if code == "PREMIUM2026":
            st.session_state.is_premium = True
            st.rerun()