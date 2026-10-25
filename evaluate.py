"""
Evaluasi RETRIEVAL: apakah Pasal yang benar muncul di k hasil teratas?

Tidak memanggil LLM (hanya embedding pertanyaan), jadi cepat dan hemat kuota.

Format eval_set.json (isi sendiri setelah membaca UU-nya):
    [
      {"question": "...", "source": "UU 27/2022 (PDP)", "pasal": "20"},
      ...
    ]
"source" harus sama dengan nama di Settings.documents. Entri yang pasal-nya masih
berawalan "ISI" dilewati.

Pemakaian:
    python evaluate.py --eval-set eval_set.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rag_uu import RagAssistant, Settings, get_api_key

KS = (1, 3, 5)

'''
def rank_of_expected(docs, item) -> int | None:
    """Peringkat (mulai 1) chunk Batang Tubuh yang cocok dengan Pasal yang diharapkan."""
    for rank, d in enumerate(docs, start=1):
        meta = d.metadata
        if (meta["source"] == item["source"]
                and meta["pasal"] == str(item["pasal"])
                and meta["bagian"] == "Batang Tubuh"):
            return rank
    return None
'''

def rank_of_expected(docs, item) -> int | None:
    """Peringkat (mulai 1) chunk Batang Tubuh yang cocok dengan Pasal yang diharapkan."""
    # Pastikan format pasal dari database RAG diubah menjadi string
    expected_pasal = item["pasal"]

    for rank, d in enumerate(docs, start=1):
        meta = d.metadata
        
        # Cek kesesuaian source dan bagian dokumen terlebih dahulu
        if meta["source"] == item["source"] and meta["bagian"] == "Batang Tubuh":
            
            # KONDISI A: Jika di JSON diisi dengan LIST/ARRAY banyak pasal
            if isinstance(expected_pasal, list):
                # Ubah isi list menjadi string untuk keamanan perbandingan
                if str(meta["pasal"]) in [str(p) for p in expected_pasal]:
                    return rank
                    
            # KONDISI B: Jika di JSON diisi dengan STRING TUNGGAL biasa
            else:
                if str(meta["pasal"]) == str(expected_pasal):
                    return rank
    return None
def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Evaluasi retrieval Hit@k dan MRR.")
    p.add_argument("--eval-set", default="eval_set.json", type=Path)
    args = p.parse_args(argv)

    items = [x for x in json.loads(args.eval_set.read_text(encoding="utf-8"))
             if not str(x["pasal"]).upper().startswith("ISI")]
    if not items:
        sys.exit("Belum ada pertanyaan yang pasal-nya terisi di eval set.")

    assistant = RagAssistant(Settings.from_env(), get_api_key())
    ranks = []
    for item in items:
        docs = assistant.store.similarity_search(item["question"], k=max(KS))
        ranks.append(rank_of_expected(docs, item))

    print(f"Jumlah pertanyaan: {len(items)}")
    for k in KS:
        hits = sum(1 for r in ranks if r is not None and r <= k)
        print(f"Hit@{k}: {hits / len(items):.0%} ({hits}/{len(items)})")
    mrr = sum(1 / r for r in ranks if r) / len(items)
    print(f"MRR   : {mrr:.3f}")

    misses = [(it, r) for it, r in zip(items, ranks) if r is None]
    if misses:
        print(f"\nTidak ditemukan di top-{max(KS)}:")
        for it, _ in misses:
            print(f"  - {it['question']}  (harapan: {it['source']}, Pasal {it['pasal']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
