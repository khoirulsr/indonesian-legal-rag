"""
Chunking per PASAL untuk PDF undang-undang Indonesia.

Output berformat sama dengan notebook RAG sebelumnya:
    {"id", "text", "source", "location", ...metadata tambahan}
jadi bisa langsung dipakai di langkah embedding, vector store, dan retrieval.

Cara pakai (di Colab):
    chunks = build_legal_chunks({
        "UU 27/2022 (PDP)": "docs/uu_27_2022_pdp.pdf",
        "UU 28/2014 (Hak Cipta)": "docs/uu_28_2014.pdf",
    })
"""
import re
from pypdf import PdfReader

# ---------------------------------------------------------------------
# 1. BACA DAN BERSIHKAN TEKS
# ---------------------------------------------------------------------
# Baris "sampah" yang sering muncul di PDF peraturan. SESUAIKAN dengan PDF-mu:
# cetak 3000 karakter pertama hasil ekstraksi, lalu tambahkan pola yang mengganggu.
NOISE_PATTERNS = [
    r"^\s*-\s*\d+\s*-\s*$",                 # nomor halaman, contoh: "- 12 -"
    r"^\s*PRESIDEN\s*$",                    # kop halaman
    r"^\s*REPUBLIK\s+INDONESIA\s*$",
    r"^\s*PRESIDEN\s+REPUBLIK\s+INDONESIA\s*$",
    r"^\s*\w*BLIK\s+INDONE\w*\s*$",           # kop yang terbaca rusak: "BLIK INDONES"
    r"^\s*SK\s+No\s*\d+.*$",                # footer "SK No 123456 A"
    r"^\s*Pasal\s+\d+[A-Z]?\s*(\.\s*){2,}$",   # artefak "Pasal 25..." atau "Pasal 7. . ."
]
NOISE_RE = re.compile("|".join(NOISE_PATTERNS))


def extract_full_text(path):
    """Gabungkan SEMUA halaman jadi satu teks, karena satu Pasal bisa lintas halaman."""
    reader = PdfReader(path)
    return "\n".join((page.extract_text() or "") for page in reader.pages)


def clean_text(text):
    lines = [ln.rstrip() for ln in text.splitlines()]
    lines = [ln for ln in lines if not NOISE_RE.match(ln)]
    text = "\n".join(lines).replace("(l)", "(1)")      # salah baca OCR yang umum
    return re.sub(r"\n{3,}", "\n\n", text).strip()


# ---------------------------------------------------------------------
# 2. CARI PENANDA: BAB dan Pasal
# ---------------------------------------------------------------------
# "Pasal 12" atau "Pasal 12A" yang berdiri SENDIRI di satu baris = judul Pasal.
# Kalimat seperti "sebagaimana dimaksud dalam Pasal 5 ayat (1)" TIDAK ikut
# karena ada teks lain di barisnya.
MARKER_RE = re.compile(
    r"^(?P<bab>BAB[ \t]+(?P<bab_no>[IVXLC]+)[ \t]*\n(?P<bab_title>[^\n]+))[ \t]*$"
    r"|^(?P<pasal>Pasal[ \t]+(?P<pasal_no>\d+[A-Z]?))[ \t]*$",
    re.MULTILINE,
)

# Awal ayat: "(1) ", "(2) ", dst. di awal baris
AYAT_RE = re.compile(r"^\((\d+[a-z]?)\)[ \t]", re.MULTILINE)


def split_batang_tubuh_penjelasan(text):
    """Pisahkan batang tubuh dari PENJELASAN (di bagian ini, Pasal diulang
    dan kebanyakan hanya berisi 'Cukup jelas.')."""
    m = re.search(r"^PENJELASAN[ \t]*$", text, re.MULTILINE)
    return (text[:m.start()], text[m.start():]) if m else (text, "")


# Salah baca OCR yang umum pada angka: O/o -> 0, I/l -> 1, T -> 7, dst.
OCR_DIGITS = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "T": "7", "S": "5", "B": "8", "Z": "2"})

# Judul Pasal "longgar", toleran OCR: "Pasa722", "PasaJ22", "Pasal2T", "Pasal T2", "Pasal I"
LOOSE_PASAL_RE = re.compile(r"^Pasa[lI1J7|][ \t]*(?P<no>[0-9OoIlTSBZ]{1,3})[ \t]*$", re.MULTILINE)


def _find_markers(text):
    """Gabungkan penanda ketat (BAB, Pasal) dan penanda longgar (Pasal salah baca OCR).
    Return list (start, end, kind, value, strict) terurut berdasarkan posisi."""
    found, strict_spans = [], []
    for m in MARKER_RE.finditer(text):
        if m.group("bab"):
            found.append((m.start(), m.end(), "bab",
                          f"BAB {m.group('bab_no')} {m.group('bab_title').strip()}", True))
        else:
            found.append((m.start(), m.end(), "pasal", m.group("pasal_no"), True))
        strict_spans.append((m.start(), m.end()))
    for m in LOOSE_PASAL_RE.finditer(text):
        if any(s <= m.start() < e for s, e in strict_spans):
            continue                                         # sudah dikenali sebagai penanda ketat
        number = m.group("no").translate(OCR_DIGITS)
        if number.isdigit():
            found.append((m.start(), m.end(), "pasal", number, False))
    return sorted(found, key=lambda x: x[0])


def parse_pasal(text):
    """Kembalikan list dict: {pasal_no, bab, body} sesuai urutan di dokumen.

    Penanda longgar (tebakan OCR) hanya diterima jika nomornya tepat melanjutkan
    urutan Pasal sebelumnya (mis. setelah Pasal 21 harus 22). Ini mencegah
    kalimat acuan seperti "... dalam Pasal 5" salah dianggap judul.
    """
    accepted, last_no = [], 0
    for start, end, kind, value, strict in _find_markers(text):
        if kind == "bab":
            accepted.append((start, end, kind, value))
            continue
        # "7O" (huruf O) yang tepat melanjutkan urutan setelah Pasal 69 adalah "70",
        # bukan "Pasal 7" dengan akhiran huruf O.
        fixed = value.translate(OCR_DIGITS)
        if not value.isdigit() and fixed.isdigit() and int(fixed) == last_no + 1:
            value = fixed
        number = int(re.match(r"\d+", value).group())
        if strict or number == last_no + 1:
            accepted.append((start, end, kind, value))
            last_no = number

    results, current_bab = [], "-"
    for i, (start, end, kind, value) in enumerate(accepted):
        if kind == "bab":
            current_bab = value
            continue
        next_start = accepted[i + 1][0] if i + 1 < len(accepted) else len(text)
        results.append({"pasal_no": value, "bab": current_bab, "body": text[end:next_start].strip()})
    return results


# ---------------------------------------------------------------------
# 3. PASAL PANJANG -> PECAH PER AYAT (cadangan: sliding window)
# ---------------------------------------------------------------------
def chunk_text(text, chunk_size=1200, overlap=150):
    """Sliding window biasa, dipakai hanya jika satu ayat/Pasal masih terlalu panjang."""
    text = re.sub(r"[ \t]+", " ", text).strip()
    chunks, start = [], 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            cut = max(text.rfind(sep, start, end) for sep in (". ", "; ", "\n"))
            if cut > start + chunk_size * 0.5:
                end = cut + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(end - overlap, start + 1)
        nxt = text.find(" ", start, end)
        if nxt != -1:
            start = nxt + 1
    return chunks


def split_by_ayat(body):
    """Return list (nomor_ayat, teks). Jika tidak ada ayat: [(None, body)]."""
    matches = list(AYAT_RE.finditer(body))
    if not matches:
        return [(None, body)]
    segments = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        segments.append((m.group(1), body[m.start():end].strip()))
    return segments


def pack_ayat(segments, max_chars):
    """Gabungkan ayat berurutan sampai mendekati max_chars.
    Return list (label_ayat, teks)."""
    packed, buf, nums = [], [], []

    def flush():
        if buf:
            label = f"ayat ({nums[0]})" if len(nums) == 1 else f"ayat ({nums[0]})-({nums[-1]})"
            packed.append((label, "\n".join(buf)))
            buf.clear(); nums.clear()

    for num, text in segments:
        if len(text) > max_chars:                            # satu ayat saja sudah kepanjangan
            flush()
            for j, part in enumerate(chunk_text(text, max_chars), 1):
                packed.append((f"ayat ({num}) bagian {j}", part))
            continue
        if buf and len("\n".join(buf)) + len(text) > max_chars:
            flush()
        buf.append(text); nums.append(num)
    flush()
    return packed


# ---------------------------------------------------------------------
# 4. RAKIT CHUNK
# ---------------------------------------------------------------------
def chunk_undang_undang(path, uu_name, max_chars=1200, include_penjelasan=True, start_id=0):
    text = clean_text(extract_full_text(path))
    batang_tubuh, penjelasan = split_batang_tubuh_penjelasan(text)

    parts = [("Batang Tubuh", batang_tubuh)]
    if include_penjelasan and penjelasan:
        parts.append(("Penjelasan", penjelasan))

    chunks = []
    for bagian, part_text in parts:
        for p in parse_pasal(part_text):
            body = p["body"]
            if bagian == "Penjelasan" and len(body) < 40:    # lewati "Cukup jelas."
                continue
            if not body:
                continue

            if len(body) <= max_chars:
                pieces = [("", body)]
            elif split_by_ayat(body)[0][0] is not None:
                pieces = pack_ayat(split_by_ayat(body), max_chars)
            else:                                            # Pasal panjang tanpa ayat (mis. definisi)
                pieces = [(f"bagian {j}", t) for j, t in enumerate(chunk_text(body, max_chars), 1)]

            for sub_label, piece in pieces:
                location = f"Pasal {p['pasal_no']}" + (f" {sub_label}" if sub_label else "")
                if bagian == "Penjelasan":
                    location += " (Penjelasan)"
                # Awalan konteks ikut di-embed: bantu retrieval menemukan Pasal yang tepat
                header = " | ".join(x for x in (uu_name, p["bab"] if p["bab"] != "-" else "", location) if x)
                chunks.append({
                    "id": start_id + len(chunks),
                    "text": f"[{header}]\n{piece}",
                    "source": uu_name,
                    "location": location,
                    "bab": p["bab"],
                    "pasal": p["pasal_no"],
                    "bagian": bagian,
                })
    return chunks


def build_legal_chunks(files, **kwargs):
    """files: dict {nama_uu: path_pdf}. Return gabungan chunk dengan id berurutan."""
    all_chunks = []
    for name, path in files.items():
        all_chunks += chunk_undang_undang(path, name, start_id=len(all_chunks), **kwargs)
    return all_chunks


# ---------------------------------------------------------------------
# 5. VALIDASI: apakah ada Pasal yang terlewat?
# ---------------------------------------------------------------------
def check_pasal_sequence(path, uu_name=""):
    """Bandingkan nomor Pasal hasil parsing dengan urutan 1..N. Jika ada yang bolong,
    biasanya format PDF-nya aneh (cek pola MARKER_RE)."""
    text = clean_text(extract_full_text(path))
    batang_tubuh, _ = split_batang_tubuh_penjelasan(text)
    nums = sorted({int(re.match(r"\d+", p["pasal_no"]).group()) for p in parse_pasal(batang_tubuh)})
    if not nums:
        print(f"{uu_name}: TIDAK ADA Pasal terdeteksi. Cek hasil ekstraksi teks PDF-nya.")
        return
    missing = [n for n in range(1, nums[-1] + 1) if n not in nums]
    print(f"{uu_name}: terdeteksi {len(nums)} Pasal (nomor terbesar {nums[-1]}).",
          "Lengkap." if not missing else f"Nomor yang hilang: {missing}")