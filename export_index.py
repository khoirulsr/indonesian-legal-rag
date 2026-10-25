"""
Ekspor indeks Chroma lokal menjadi file biasa (numpy + JSON) untuk deployment.

Tidak memanggil API apa pun, jadi tidak memakai kuota. Hasilnya di folder index/:
    vectors.npy   vektor embedding yang sudah dinormalisasi (cosine = dot product)
    chunks.json   teks dan metadata tiap chunk (UU, BAB, Pasal, ...)
    meta.json     nama model embedding (aplikasi web harus memakai model yang SAMA)

Pemakaian:
    python export_index.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from rag_uu import INDEX_MARKER, Settings

OUT_DIR = Path(__file__).resolve().parent / "index"


def main() -> int:
    import chromadb

    settings = Settings.from_env()
    marker = settings.persist_dir / INDEX_MARKER
    if not marker.exists():
        sys.exit("Indeks lokal belum lengkap. Jalankan dulu: python rag_uu.py --rebuild")

    client = chromadb.PersistentClient(path=str(settings.persist_dir))
    data = client.get_collection(settings.collection).get(include=["embeddings", "documents", "metadatas"])

    ids = data["ids"]
    order = sorted(range(len(ids)), key=lambda i: ids[i])          # urut sesuai ID chunk-00000, ...
    vectors = np.asarray(data["embeddings"], dtype="float32")[order]
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vectors = vectors / norms
    chunks = [{"id": ids[i], "text": data["documents"][i], **data["metadatas"][i]} for i in order]

    expected = json.loads(marker.read_text(encoding="utf-8")).get("chunks")
    if expected is not None and expected != len(chunks):
        print(f"PERINGATAN: penanda indeks mencatat {expected} chunk, tetapi yang terbaca {len(chunks)}.")

    OUT_DIR.mkdir(exist_ok=True)
    np.save(OUT_DIR / "vectors.npy", vectors)
    (OUT_DIR / "chunks.json").write_text(json.dumps(chunks, ensure_ascii=False), encoding="utf-8")
    (OUT_DIR / "meta.json").write_text(
        json.dumps({"embed_model": settings.embed_model, "chunks": len(chunks), "dim": int(vectors.shape[1])}),
        encoding="utf-8",
    )

    size_mb = sum(p.stat().st_size for p in OUT_DIR.iterdir()) / 1e6
    print(f"Selesai: {len(chunks)} chunk, dimensi {vectors.shape[1]}, total {size_mb:.1f} MB -> {OUT_DIR}")
    print("Folder index/ inilah yang harus ikut di-commit ke GitHub.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
