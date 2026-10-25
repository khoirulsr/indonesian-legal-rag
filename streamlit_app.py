from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import deque
from pathlib import Path

import numpy as np
import streamlit as st
from dotenv import load_dotenv
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from prompts import DISCLAIMER, PROMPT_TEMPLATE
from ui_style import inject_css, notice_html, source_card_html

# 1. Konfigurasi halaman utama (harus menjadi perintah Streamlit yang pertama)
st.set_page_config(
    page_title="Asisten Hukum RAG - UU PDP & Perlindungan Konsumen",
    page_icon="⚖️",
    layout="centered",
)

# 2. Gaya tampilan: seluruh CSS ada di ui_style.py (tema terang + teks gelap yang konsisten)
inject_css()

logger = logging.getLogger("streamlit_app")
BASE_DIR = Path(__file__).resolve().parent
INDEX_DIR = BASE_DIR / "index"
load_dotenv(BASE_DIR / ".env", encoding="utf-8-sig")

API_KEY_VARS = ("GEMINI", "GEMINI_API_KEY", "GOOGLE_API_KEY")
DEFAULT_CHAT_MODEL = "gemini-3.6-flash"
TOP_K = 6
MAX_QUESTION_CHARS = 300
MIN_SECONDS_BETWEEN_QUESTIONS = 5
MAX_QUESTIONS_PER_SESSION = 20
GLOBAL_MAX_PER_MINUTE = 10
CACHE_MAX_ENTRIES = 200
SOURCE_PREVIEW_CHARS = 700

EXAMPLES = [
    "Apa saja hak subjek data pribadi?",
    "Apa kewajiban pelaku usaha menurut UU Perlindungan Konsumen?",
    "Apa yang harus dilakukan pengendali data jika terjadi kegagalan pelindungan data pribadi?",
]

# DISCLAIMER berawalan "Catatan: ...". Awalan dibuang karena sudah ada label "PENTING" / "Catatan Sistem".
_body = DISCLAIMER.split(": ", 1)[-1]
DISCLAIMER_TEXT = _body[0].upper() + _body[1:]


def read_setting(names) -> str | None:
    for name in names:
        try:
            value = st.secrets.get(name)
        except Exception:  # noqa: BLE001 - tidak ada secrets.toml saat uji lokal
            value = None
        value = value or os.getenv(name)
        if value:
            return str(value).strip()
    return None


@st.cache_resource(show_spinner="Menyelaraskan data dan indeks hukum...")
def load_index():
    vectors = np.load(INDEX_DIR / "vectors.npy")
    chunks = json.loads((INDEX_DIR / "chunks.json").read_text(encoding="utf-8"))
    meta = json.loads((INDEX_DIR / "meta.json").read_text(encoding="utf-8"))
    return vectors, chunks, meta


@st.cache_resource
def load_models(api_key: str, embed_model: str, chat_model: str):
    embeddings = GoogleGenerativeAIEmbeddings(model=embed_model, google_api_key=api_key)
    llm = ChatGoogleGenerativeAI(model=chat_model, api_key=api_key)
    chain = ChatPromptTemplate.from_template(PROMPT_TEMPLATE) | llm | StrOutputParser()
    return embeddings, chain


class RateLimiter:
    def __init__(self, max_calls: int, period: float = 60.0) -> None:
        self.max_calls, self.period = max_calls, period
        self.calls: deque[float] = deque()
        self.lock = threading.Lock()

    def allow(self) -> bool:
        now = time.time()
        with self.lock:
            while self.calls and now - self.calls[0] > self.period:
                self.calls.popleft()
            if len(self.calls) >= self.max_calls:
                return False
            self.calls.append(now)
            return True


@st.cache_resource
def get_global_limiter() -> RateLimiter:
    return RateLimiter(GLOBAL_MAX_PER_MINUTE)


@st.cache_resource
def get_answer_cache() -> dict:
    return {}


def retrieve(question: str, embeddings, vectors: np.ndarray, chunks: list[dict], k: int = TOP_K) -> list[dict]:
    query = np.asarray(embeddings.embed_query(question), dtype="float32")
    norm = np.linalg.norm(query)
    if norm:
        query = query / norm
    scores = vectors @ query
    top = np.argsort(-scores)[:k]
    return [{**chunks[i], "score": float(scores[i])} for i in top]


def answer_question(question: str, embeddings, chain, vectors, chunks) -> dict:
    hits = retrieve(question, embeddings, vectors, chunks)
    context = "\n\n".join(h["text"] for h in hits)
    answer = chain.invoke({"context": context, "question": question})
    return {"answer": answer.strip(), "sources": hits}


def friendly_error(exc: Exception) -> str:
    msg = str(exc)
    logger.exception("Gagal memproses pertanyaan")
    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        return "Kuota penelusuran gratis sedang penuh. Harap tunggu satu menit lalu segarkan halaman."
    if "401" in msg or "UNAUTHENTICATED" in msg or "API key" in msg:
        return "Sistem mendeteksi kesalahan konfigurasi enkripsi API di server utama. Silakan laporkan masalah ini."
    return "Terjadi kendala interkoneksi saat membaca berkas undang-undang. Mohon coba sesaat lagi."


def render_sources(sources: list[dict]) -> None:
    with st.expander("🔍 Lihat Referensi & Dokumen Hukum Terkait"):
        st.caption("Rujukan pasal asli yang digunakan model AI untuk menyusun jawaban:")
        for s in sources:
            st.markdown(source_card_html(s, max_chars=SOURCE_PREVIEW_CHARS), unsafe_allow_html=True)


def render_sidebar(chunks: list[dict]) -> None:
    with st.sidebar:
        st.markdown("## ⚖️ Legal RAG Pro")
        st.caption("Context Intelligence System")

        st.subheader("Cakupan Dokumen")
        for name in sorted({c["source"] for c in chunks}):
            st.markdown(f"💼 {name}")

        st.divider()
        st.subheader("💡 Topik Rujukan Cepat")
        for i, example in enumerate(EXAMPLES):
            if st.button(example, key=f"example_{i}"):    # lebar penuh diatur lewat CSS di ui_style.py
                st.session_state["pending_question"] = example

        st.divider()
        st.markdown(
            f"<div class='custom-disclaimer'><b>PENTING:</b><br>{DISCLAIMER_TEXT}</div>",
            unsafe_allow_html=True,
        )


def check_limits(question: str) -> str | None:
    if len(question) > MAX_QUESTION_CHARS:
        return f"Pertanyaan melampaui batas instan (maksimal {MAX_QUESTION_CHARS} karakter)."
    if st.session_state["question_count"] >= MAX_QUESTIONS_PER_SESSION:
        return "Anda telah mencapai batas maksimum interaksi pada sesi ini demi keamanan server."
    if time.time() - st.session_state["last_question_at"] < MIN_SECONDS_BETWEEN_QUESTIONS:
        return f"Mohon berikan jeda waktu {MIN_SECONDS_BETWEEN_QUESTIONS} detik sebelum mengirimkan analisis."
    if not get_global_limiter().allow():
        return "Lalu lintas data ke server sedang padat. Silakan kirim ulang pertanyaan dalam 30-60 detik."
    return None


def main() -> None:
    st.markdown(
        '<div class="header-container"><h1>⚖️ Asisten Regulasi &amp; Hukum Indonesia</h1>'
        "<p>Pencarian pintar berbasis semantik untuk UU Pelindungan Data Pribadi (PDP) dan UU Perlindungan Konsumen.</p></div>",
        unsafe_allow_html=True,
    )

    if not (INDEX_DIR / "vectors.npy").exists():
        st.error("Gagal memuat arsitektur database. Berkas indeks biner 'vectors.npy' tidak terdeteksi.")
        st.stop()

    api_key = read_setting(API_KEY_VARS)
    if not api_key:
        st.error("Kredensial API tidak ditemukan. Isi GEMINI di Settings > Secrets (Streamlit Cloud) atau di file .env.")
        st.stop()

    vectors, chunks, meta = load_index()
    chat_model = read_setting(("GEMINI_CHAT_MODEL",)) or DEFAULT_CHAT_MODEL
    embeddings, chain = load_models(api_key, meta["embed_model"], chat_model)

    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("question_count", 0)
    st.session_state.setdefault("last_question_at", 0.0)
    render_sidebar(chunks)

    for message in st.session_state["messages"]:
        with st.chat_message(message["role"]):
            if message.get("is_error"):
                st.markdown(notice_html(message["content"]), unsafe_allow_html=True)
            else:
                st.markdown(message["content"])
            if message.get("sources"):
                render_sources(message["sources"])

    question = st.chat_input("Tulis pertanyaan Anda di sini...")
    question = question or st.session_state.pop("pending_question", None)

    if not question:
        return
    question = question.strip()

    st.session_state["messages"].append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.markdown(question)

    cache, cache_key = get_answer_cache(), " ".join(question.lower().split())
    result, error = cache.get(cache_key), None

    if result is None:
        error = check_limits(question)
        if error is None:
            st.session_state["question_count"] += 1
            st.session_state["last_question_at"] = time.time()
            try:
                with st.spinner("Sedang menelusuri pasal dan merangkum asas hukum untuk Anda..."):
                    result = answer_question(question, embeddings, chain, vectors, chunks)
                if len(cache) >= CACHE_MAX_ENTRIES:
                    cache.pop(next(iter(cache)))
                cache[cache_key] = result
            except Exception as exc:  # noqa: BLE001
                error = friendly_error(exc)

    with st.chat_message("assistant"):
        if error:
            st.markdown(notice_html(error), unsafe_allow_html=True)
            st.session_state["messages"].append({"role": "assistant", "content": error, "is_error": True})
        else:
            st.markdown(result["answer"])
            render_sources(result["sources"])
            st.markdown(
                f"<div class='custom-disclaimer'><b>Catatan Sistem:</b> {DISCLAIMER_TEXT}</div>",
                unsafe_allow_html=True,
            )
            st.session_state["messages"].append(
                {"role": "assistant", "content": result["answer"], "sources": result["sources"]}
            )


if __name__ == "__main__":
    main()