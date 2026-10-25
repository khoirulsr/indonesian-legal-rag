from __future__ import annotations

import html

import streamlit as st

CSS = """
<style>
/* ===== Dasar: paksa mode terang, teks selalu gelap ===== */
:root { color-scheme: light; }
.stApp, [data-testid="stAppViewContainer"] { background-color: #F8FAFC; color: #0F172A; }
[data-testid="stHeader"] { background-color: #F8FAFC !important; border-bottom: 1px solid #E2E8F0; }
[data-testid="stHeader"], [data-testid="stHeader"] *, [data-testid="stToolbar"] * { color: #0F172A !important; }
.block-container { max-width: 880px; padding-top: 2rem; padding-bottom: 6rem; }
footer { visibility: hidden; }

/* ===== Header ===== */
.header-container {
    background: #FFFFFF; border: 1px solid #E2E8F0; border-top: 4px solid #2563EB;
    border-radius: 16px; padding: 1.5rem 1.75rem; margin-bottom: 1.5rem;
    box-shadow: 0 4px 12px rgba(15, 23, 42, 0.06);
}
.header-container h1 { color: #0F172A !important; font-size: 1.7rem; margin: 0 0 0.35rem 0; padding: 0; }
.header-container p  { color: #475569 !important; margin: 0; font-size: 0.97rem; }

/* ===== Bubble chat: asisten = putih, pengguna = biru muda, teks selalu gelap ===== */
[data-testid="stChatMessage"] {
    background-color: #FFFFFF !important; border: 1px solid #E2E8F0 !important;
    border-radius: 14px !important; padding: 1rem 1.25rem !important; margin-bottom: 0.9rem;
    box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06);
}
[data-testid="stChatMessage"]:has([data-testid="stChatMessageAvatarUser"]),
[data-testid="stChatMessage"]:has([data-testid="chatAvatarIcon-user"]) {
    background-color: #EAF2FF !important; border-color: #BFD6FF !important;
}
[data-testid="stChatMessage"],
[data-testid="stChatMessage"] p, [data-testid="stChatMessage"] li,
[data-testid="stChatMessage"] span, [data-testid="stChatMessage"] strong,
[data-testid="stChatMessage"] em, [data-testid="stChatMessage"] h1, [data-testid="stChatMessage"] h2,
[data-testid="stChatMessage"] h3, [data-testid="stChatMessage"] h4 { color: #0F172A !important; }
[data-testid="stChatMessage"] p { line-height: 1.65; }
[data-testid="stChatMessage"] code { background-color: #E2E8F0 !important; color: #0F172A !important; }
[data-testid="stChatMessage"] [data-testid="stCaptionContainer"],
[data-testid="stChatMessage"] [data-testid="stCaptionContainer"] * { color: #64748B !important; }

/* ===== Expander "Sumber yang dipakai" ===== */
[data-testid="stExpander"] {
    background-color: #FFFFFF !important; border: 1px solid #E2E8F0 !important; border-radius: 12px !important;
}
[data-testid="stExpander"] details, [data-testid="stExpander"] summary { background-color: #FFFFFF !important; }
[data-testid="stExpander"] summary, [data-testid="stExpander"] summary * { color: #0F172A !important; font-weight: 600; }
[data-testid="stExpander"] p, [data-testid="stExpander"] li, [data-testid="stExpander"] span { color: #0F172A; }

/* ===== Kartu teks Pasal ===== */
.pasal-card {
    background-color: #F1F5F9; border-left: 5px solid #2563EB;
    padding: 0.8rem 1rem; border-radius: 0 10px 10px 0; margin: 0.5rem 0;
}
.pasal-card .pasal-title { color: #1E3A8A; font-weight: 700; font-size: 0.93rem; margin-bottom: 0.3rem; }
.pasal-card .score {
    background: #DBEAFE; color: #1E40AF; border-radius: 999px; padding: 1px 9px;
    font-size: 0.74rem; font-weight: 600; margin-left: 0.4rem; white-space: nowrap;
}
.pasal-card .pasal-text { color: #334155; font-size: 0.87rem; line-height: 1.55; }

/* ===== Disclaimer ===== */
.custom-disclaimer {
    background-color: #FFF1F2; border: 1px solid #FFE4E6; border-left: 4px solid #F43F5E;
    padding: 0.9rem 1rem; border-radius: 8px; color: #9F1239 !important; font-size: 0.85rem; margin-top: 0.9rem;
}
.custom-disclaimer * { color: #9F1239 !important; }

/* ===== Kotak input chat: SEMUA lapisan dalam dipaksa terang (wadah bawaan bisa gelap di tema gelap) ===== */
[data-testid="stBottom"], [data-testid="stBottom"] > div, [data-testid="stBottomBlockContainer"] {
    background-color: #F8FAFC !important;
}
[data-testid="stChatInput"] {
    background-color: #FFFFFF !important; border: 1px solid #CBD5E1 !important; border-radius: 14px !important;
    box-shadow: 0 2px 8px rgba(15, 23, 42, 0.06);
}
[data-testid="stChatInput"] div { background-color: #FFFFFF !important; border-color: transparent !important; box-shadow: none !important; }
[data-testid="stChatInput"]:focus-within { border-color: #2563EB !important; box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15); }
[data-testid="stChatInput"] textarea { color: #0F172A !important; background-color: #FFFFFF !important; }
[data-testid="stChatInput"] textarea::placeholder { color: #94A3B8 !important; }
[data-testid="stChatInput"] button { background-color: #2563EB !important; border-radius: 10px !important; }
[data-testid="stChatInput"] button svg { fill: #FFFFFF !important; color: #FFFFFF !important; }
[data-testid="stChatInput"] button:disabled { background-color: #CBD5E1 !important; opacity: 1; }

/* ===== Pemberitahuan (kuota habis, error): kartu sendiri, tidak bergantung pada tema Streamlit ===== */
.notice-card {
    background-color: #FFFBEB; border: 1px solid #FDE68A; border-left: 4px solid #F59E0B;
    border-radius: 10px; padding: 0.85rem 1rem; color: #78350F !important; font-size: 0.95rem; line-height: 1.55;
}
.notice-card * { color: #78350F !important; }
/* cadangan jika masih ada st.warning / st.error / st.info bawaan */
[data-testid="stAlert"] p, [data-testid="stAlert"] span, [data-testid="stAlert"] li { color: #0F172A !important; }

/* ===== Sidebar gelap ===== */
[data-testid="stSidebar"] { background-color: #0F172A !important; }
[data-testid="stSidebar"] h1, [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3,
[data-testid="stSidebar"] p, [data-testid="stSidebar"] li, [data-testid="stSidebar"] span,
[data-testid="stSidebar"] strong, [data-testid="stSidebar"] label { color: #F8FAFC !important; }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"],
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] * { color: #CBD5E1 !important; }
[data-testid="stSidebar"] hr { border-color: #334155 !important; }
[data-testid="stSidebar"] .stButton, [data-testid="stSidebar"] [data-testid="stButton"],
[data-testid="stSidebar"] [data-testid="stElementContainer"]:has(.stButton),
[data-testid="stSidebar"] [data-testid="stElementContainer"]:has([data-testid="stButton"]) { width: 100% !important; }
[data-testid="stSidebar"] .stButton > button, [data-testid="stSidebar"] [data-testid="stButton"] > button,
[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] {
    background-color: #1E293B !important; color: #F8FAFC !important; border: 1px solid #334155 !important;
    border-radius: 10px !important; width: 100% !important; height: auto; padding: 0.6rem 0.8rem;
    text-align: left; white-space: normal; line-height: 1.4; transition: all 0.2s ease;
}
[data-testid="stSidebar"] .stButton > button p, [data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"] p { color: #F8FAFC !important; text-align: left; }
[data-testid="stSidebar"] .stButton > button:hover, [data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"]:hover { background-color: #1D4ED8 !important; border-color: #3B82F6 !important; }
</style>
"""


def inject_css() -> None:
    """Pasang CSS ke halaman. Panggil sekali di awal, setelah st.set_page_config()."""
    st.markdown(CSS, unsafe_allow_html=True)


def source_card_html(source: dict, max_chars: int = 400) -> str:
    """HTML satu kartu sumber (Pasal). Teks di-escape supaya karakter < > & dari PDF tidak merusak tampilan.
    Sengaja satu baris tanpa indentasi: Markdown menganggap baris berindentasi 4 spasi sebagai blok kode."""
    text = source["text"]
    snippet = html.escape(text[:max_chars]) + ("..." if len(text) > max_chars else "")
    snippet = snippet.replace("\n", "<br>")
    title = html.escape(f"{source['source']}, {source['location']}")
    return (f'<div class="pasal-card"><div class="pasal-title">{title}'
            f'<span class="score">skor {source["score"]:.2f}</span></div>'
            f'<div class="pasal-text">{snippet}</div></div>')


def notice_html(message: str) -> str:
    """HTML kartu pemberitahuan ramah (mis. kuota habis). Pakai: st.markdown(notice_html(pesan), unsafe_allow_html=True)."""
    return f'<div class="notice-card">{html.escape(message)}</div>'