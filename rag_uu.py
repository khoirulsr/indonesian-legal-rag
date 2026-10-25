"""
Asisten RAG untuk Undang-Undang Indonesia (UU PDP dan UU Perlindungan Konsumen).

Alur:
    PDF -> chunk per Pasal -> embedding (Gemini) -> Chroma (disimpan di disk)
        -> retrieval top-k -> prompt -> Gemini -> jawaban + sitasi Pasal

Pemakaian:
    python rag_uu.py                          # mode tanya-jawab interaktif
    python rag_uu.py -q "Apa hak subjek data pribadi?"
    python rag_uu.py --rebuild                # bangun ulang indeks (PDF atau chunker berubah)

Catatan: output ini informasi dari teks peraturan, bukan nasihat hukum.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from langchain_community.vectorstores import Chroma
from langchain_core.documents import Document
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from chunking_per_pasal import build_legal_chunks
from prompts import DISCLAIMER, PROMPT_TEMPLATE

logger = logging.getLogger("rag_uu")

BASE_DIR = Path(__file__).resolve().parent

PROMPT = ChatPromptTemplate.from_template(PROMPT_TEMPLATE)


# ---------------------------------------------------------------------
# Konfigurasi
# ---------------------------------------------------------------------
@dataclass(frozen=True)
class Settings:
    docs_dir: Path = BASE_DIR / "data" / "raw"
    persist_dir: Path = BASE_DIR / "chroma_db"
    collection: str = "uu_indonesia"
    # nama tampil (dipakai di sitasi) -> nama file PDF di docs_dir
    documents: dict[str, str] = field(default_factory=lambda: {
        "UU 27/2022 (PDP)": "uu_27_2022_pdp.pdf",
        "UU 8/1999 (Perlindungan Konsumen)": "uu_8_1999_perlindungan_konsumen.pdf",
    })
    embed_model: str = "gemini-embedding-2"
    chat_model: str = "gemini-3.6-flash"
    top_k: int = 6
    max_chunk_chars: int = 1200
    embed_batch_size: int = 20
    embed_per_minute: int = 80        # batas gratis 100/menit; sisakan ruang aman

    @classmethod
    def from_env(cls) -> "Settings":
        """Baca .env lalu izinkan nama model diganti lewat variabel lingkungan."""
        load_dotenv(BASE_DIR / ".env", override=True, encoding="utf-8-sig")  # sig: tahan BOM Notepad
        return cls(
            embed_model=os.getenv("GEMINI_EMBED_MODEL", cls.embed_model),
            chat_model=os.getenv("GEMINI_CHAT_MODEL", cls.chat_model),
        )


API_KEY_VARS = ("GEMINI", "GEMINI_API_KEY", "GOOGLE_API_KEY")


def _env_diagnosis() -> str:
    """Jelaskan kenapa API key tidak ditemukan (hanya nama variabel, tidak pernah nilainya)."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        similar = sorted(p.name for p in BASE_DIR.glob(".env*"))
        hint = f"File .env TIDAK ditemukan di folder {BASE_DIR}."
        if similar:
            hint += (f" File mirip yang ada di sana: {similar}. "
                     "Namanya harus persis '.env' (tanpa .txt atau .example).")
        else:
            hint += " Taruh .env di folder yang sama dengan rag_uu.py."
        return hint
    names = list(dotenv_values(env_path, encoding="utf-8-sig").keys())
    return (f"File .env ditemukan di {env_path}, tetapi tidak berisi salah satu variabel {API_KEY_VARS}. "
            f"Variabel yang terbaca: {names or 'tidak ada (file kosong atau formatnya salah)'}.")


def get_api_key() -> str:
    for name in API_KEY_VARS:
        key = os.getenv(name)
        if key and key.strip():
            return key.strip()
    sys.exit(f"API key tidak ditemukan. {_env_diagnosis()}\n"
             "Isi satu baris di .env, contoh:  GEMINI=api_key_kamu  (tanpa spasi dan tanpa tanda kutip).")


# ---------------------------------------------------------------------
# Indexing: PDF -> chunk -> vector store
# ---------------------------------------------------------------------
def build_documents(settings: Settings) -> list[Document]:
    """Baca PDF, pecah per Pasal, lalu ubah ke Document LangChain beserta metadata."""
    files: dict[str, str] = {}
    for name, filename in settings.documents.items():
        path = settings.docs_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"PDF tidak ditemukan: {path}")
        files[name] = str(path)

    chunks = build_legal_chunks(files, max_chars=settings.max_chunk_chars)
    docs = [
        Document(
            page_content=c["text"],
            metadata={k: c[k] for k in ("source", "location", "bab", "pasal", "bagian")},
        )
        for c in chunks
    ]
    logger.info("%d chunk dari %d dokumen", len(docs), len(files))
    return docs


INDEX_MARKER = "index_complete.json"   # ditulis HANYA setelah semua chunk berhasil di-embed


def _add_with_retry(store: Chroma, docs: list[Document], ids: list[str], max_retries: int = 5) -> None:
    """Tambahkan satu batch; jika kena limit kuota (429), tunggu lalu ulangi."""
    for attempt in range(1, max_retries + 1):
        try:
            store.add_documents(docs, ids=ids)
            return
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            is_quota = "429" in msg or "RESOURCE_EXHAUSTED" in msg
            if not is_quota or attempt == max_retries:
                raise
            hint = re.search(r"retry in ([\d.]+)s", msg)
            wait = (float(hint.group(1)) if hint else 60.0) + 5
            logger.warning("Kuota embedding habis (429). Menunggu %.0f detik, lalu coba lagi (%d/%d)...",
                           wait, attempt, max_retries)
            time.sleep(wait)


def get_vectorstore(settings: Settings, embeddings, rebuild: bool = False) -> Chroma:
    """Muat indeks dari disk. Jika belum lengkap, lanjutkan dari chunk yang tersisa."""
    persist = settings.persist_dir
    if rebuild and persist.exists():
        shutil.rmtree(persist)

    store = Chroma(
        collection_name=settings.collection,
        embedding_function=embeddings,
        persist_directory=str(persist),
    )
    if (persist / INDEX_MARKER).exists():
        logger.info("Memakai indeks yang sudah ada di %s", persist)
        return store

    docs = build_documents(settings)
    ids = [f"chunk-{i:05d}" for i in range(len(docs))]       # ID tetap -> bisa dilanjutkan
    done = set(store.get()["ids"])
    if any(not i.startswith("chunk-") for i in done):
        sys.exit("Ditemukan indeks lama yang tidak lengkap. Jalankan: python rag_uu.py --rebuild")

    pending = [(d, i) for d, i in zip(docs, ids) if i not in done]
    if done:
        logger.info("Melanjutkan indeks: %d chunk sudah ada, %d tersisa.", len(done), len(pending))
    delay = settings.embed_batch_size / settings.embed_per_minute * 60
    logger.info("Membangun indeks: %d chunk, sekitar %.1f menit (dibatasi kuota gratis).",
                len(pending), len(pending) * 60 / settings.embed_per_minute / 60)

    size = settings.embed_batch_size
    for start in range(0, len(pending), size):
        batch = pending[start:start + size]
        _add_with_retry(store, [d for d, _ in batch], [i for _, i in batch])
        logger.info("  %d/%d chunk selesai", len(done) + start + len(batch), len(docs))
        if start + size < len(pending):
            time.sleep(delay)

    persist.mkdir(parents=True, exist_ok=True)
    (persist / INDEX_MARKER).write_text(json.dumps({"chunks": len(docs)}), encoding="utf-8")
    return store


# ---------------------------------------------------------------------
# Retrieval + generation
# ---------------------------------------------------------------------
@dataclass
class RagResult:
    question: str
    answer: str
    sources: list[Document]


class RagAssistant:
    def __init__(self, settings: Settings, api_key: str, rebuild: bool = False) -> None:
        self.settings = settings
        embeddings = GoogleGenerativeAIEmbeddings(model=settings.embed_model, google_api_key=api_key)
        self.store = get_vectorstore(settings, embeddings, rebuild=rebuild)
        self.retriever = self.store.as_retriever(search_kwargs={"k": settings.top_k})
        llm = ChatGoogleGenerativeAI(model=settings.chat_model, api_key=api_key)
        self.chain = PROMPT | llm | StrOutputParser()

    def ask(self, question: str) -> RagResult:
        docs = self.retriever.invoke(question)
        context = "\n\n".join(d.page_content for d in docs)
        answer = self.chain.invoke({"context": context, "question": question})
        return RagResult(question=question, answer=answer.strip(), sources=docs)


def format_sources(docs: list[Document]) -> str:
    """Daftar sumber unik, urut sesuai peringkat retrieval."""
    seen, lines = set(), []
    for d in docs:
        key = (d.metadata["source"], d.metadata["location"])
        if key not in seen:
            seen.add(key)
            lines.append(f"  - {key[0]}, {key[1]}")
    return "\n".join(lines)


def print_result(result: RagResult) -> None:
    print(f"\nJawaban:\n{result.answer}")
    print(f"\nSumber yang diambil:\n{format_sources(result.sources)}")
    print(f"\n{DISCLAIMER}")


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------
def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Asisten RAG untuk UU PDP dan UU Perlindungan Konsumen.")
    p.add_argument("-q", "--question", help="Ajukan satu pertanyaan lalu keluar.")
    p.add_argument("--rebuild", action="store_true", help="Bangun ulang indeks dari PDF.")
    p.add_argument("-v", "--verbose", action="store_true", help="Tampilkan log detail.")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s: %(message)s")
    logger.setLevel(logging.INFO)                      # progres indeks selalu ditampilkan

    settings = Settings.from_env()
    assistant = RagAssistant(settings, get_api_key(), rebuild=args.rebuild)

    if args.question:
        print_result(assistant.ask(args.question))
        return 0

    print("Asisten UU siap. Ketik 'keluar' untuk berhenti.")
    while True:
        try:
            question = input("\nTanyakan pertanyaan: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if question.lower() in {"keluar", "exit", "quit"}:
            break
        if not question:
            continue
        try:
            print_result(assistant.ask(question))
        except Exception as exc:  # noqa: BLE001 - tampilkan error ramah, jangan crash
            logger.error("Gagal memproses pertanyaan: %s", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
