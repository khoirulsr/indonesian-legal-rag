"""
Bantu cari tahu kenapa suatu Pasal tidak terdeteksi parser.

Contoh:
    python diagnose_pasal.py data/raw/uu_27_2022_pdp.pdf 22 27 70 72

Skrip menampilkan:
  1. Baris-baris di PDF yang menyebut nomor itu dekat kata "Pasal" (beserta baris
     sebelum dan sesudahnya). repr() dipakai supaya karakter aneh/tersembunyi terlihat.
  2. Baris yang MIRIP judul Pasal tetapi ditolak parser (biasanya salah baca OCR).
"""
import re
import sys

from chunking_per_pasal import extract_full_text

STRICT = re.compile(r"^Pasal[ \t]+\d+[A-Z]?[ \t]*$")
LOOKALIKE = re.compile(r"(?i)^\s*pa\S{0,3}\s*[\dOolI]")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 1
    path, wanted = sys.argv[1], sys.argv[2:]
    lines = extract_full_text(path).splitlines()

    for num in wanted:
        digits = r"\s?".join(re.escape(ch) for ch in num)       # "22" juga cocok dengan "2 2"
        pattern = re.compile(rf"(?i)pa\S{{0,3}}\s*{digits}(?!\d)")
        hits = [i for i, ln in enumerate(lines) if pattern.search(ln)]
        print(f"\n===== Pasal {num}: {len(hits)} baris cocok =====")
        for i in hits[:6]:
            tag = "JUDUL VALID" if STRICT.match(lines[i].strip()) else "tidak valid sbg judul"
            print(f"--- baris {i} [{tag}]")
            for j in range(max(0, i - 1), min(len(lines), i + 2)):
                print(f"   {'>' if j == i else ' '} {lines[j]!r}")

    print("\n===== Baris mirip judul Pasal tapi DITOLAK parser =====")
    rejected = [(i, ln) for i, ln in enumerate(lines)
                if LOOKALIKE.match(ln) and not STRICT.match(ln.strip())]
    for i, ln in rejected[:40]:
        print(f"  baris {i}: {ln!r}")
    if not rejected:
        print("  (tidak ada)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
