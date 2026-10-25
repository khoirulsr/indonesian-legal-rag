# ⚖️ Indonesian Legal RAG

Asisten tanya-jawab yang menjawab **hanya dari teks undang-undang**, lengkap dengan sitasi Pasal. Dokumen yang dipakai: **UU No. 27/2022 (Pelindungan Data Pribadi)** dan **UU No. 8/1999 (Perlindungan Konsumen)**.

🔗 **Demo:** `ISI_LINK_STREAMLIT`

[Demo](docs/demo.png)

> ⚠️ Proyek edukasi. Jawabannya informasi dari teks peraturan, **bukan nasihat hukum**.

---

## ✨ Fitur

- **Chunking per Pasal**: satu potongan = satu Pasal (atau ayat), bukan potongan karakter acak, sehingga sitasinya presisi.
- **Sitasi di setiap jawaban**: format (nama UU, Pasal N) beserta daftar sumber yang diambil.
- **Menolak menjawab di luar dokumen**: prompt mewajibkan jawaban hanya dari konteks.
- **Parser tahan salah baca OCR**: judul seperti `Pasa722` atau `Pasal 7O` tetap dikenali, divalidasi dengan urutan nomor Pasal.
- **Indeks tersimpan**: embedding dihitung sekali, lalu dipakai ulang. Pembangunan indeks otomatis mengikuti batas kuota API gratis dan bisa dilanjutkan jika terputus.
- **Aplikasi web (Streamlit)** dengan pembatasan pemakaian dan cache jawaban untuk melindungi kuota.

## 🧠 Cara kerja

```
PDF ─► chunk per Pasal ─► embedding (Gemini) ─► vector store
                                                     │
Pertanyaan ─► embedding ─► top-k chunk ─► prompt ─► Gemini ─► jawaban + sumber
```

| Tahap | Implementasi |
|---|---|
| Baca PDF | `pypdf`, seluruh halaman digabung (Pasal bisa lintas halaman) |
| Chunking | `chunking_per_pasal.py`: regex judul Pasal/BAB, pecah per ayat jika panjang |
| Embedding | Gemini (`GoogleGenerativeAIEmbeddings`) |
| Vector store | Chroma (lokal, untuk membangun indeks); numpy (aplikasi web) |
| Generation | Gemini via LangChain, prompt di `prompts.py` |

## 📚 Dokumen sumber

| Dokumen | Sumber | Diakses |
|---|---|---|
| UU No. 27 Tahun 2022 tentang Pelindungan Data Pribadi | https://peraturan.bpk.go.id/Details/229798 | 23 Oktober 2026 |
| UU No. 8 Tahun 1999 tentang Perlindungan Konsumen | https://peraturan.bpk.go.id/Details/45288 | 23 Oktober 2026 |

Peraturan perundang-undangan tidak dilindungi hak cipta di Indonesia (Pasal 42 UU No. 28/2014 tentang Hak Cipta).

## 🗂️ Struktur repo

```
.
├── data/raw/              # PDF undang-undang
├── index/                 # indeks siap pakai untuk aplikasi web (hasil export_index.py)
├── rag_uu.py              # CLI: bangun indeks dan tanya-jawab
├── chunking_per_pasal.py  # parser dan chunker per Pasal
├── prompts.py             # prompt bersama (CLI dan web)
├── export_index.py        # ekspor indeks Chroma -> numpy + JSON
├── streamlit_app.py       # aplikasi web
├── evaluate.py            # evaluasi retrieval (Hit@k, MRR)
├── tests/                 # tes unit untuk parser dan chunker
├── diagnose_pasal.py      # alat bantu debugging parsing Pasal
├── cek_api_key.py         # alat bantu cek API key
├── requirements.txt       # dependensi aplikasi web
└── requirements-build.txt # dependensi untuk membangun indeks secara lokal
```

## 🚀 Menjalankan secara lokal

```bash
git clone https://github.com/khoirulsr/indonesian-legal-rag.git
cd indonesian-legal-rag
python -m venv venv && venv\Scripts\activate      # Windows
pip install -r requirements-build.txt
```

1. Buat API key di [Google AI Studio](https://aistudio.google.com/apikey), lalu salin `.env.example` menjadi `.env` dan isi `GEMINI=...`.
2. Taruh PDF di `data/raw/` dengan nama `uu_27_2022_pdp.pdf` dan `uu_8_1999_perlindungan_konsumen.pdf`.
3. Cek parsing Pasal, lalu bangun indeks:
   ```bash
   python -c "from chunking_per_pasal import check_pasal_sequence as c; c('data/raw/uu_27_2022_pdp.pdf', 'PDP')"
   python rag_uu.py --rebuild
   ```
4. Tanya lewat terminal:
   ```bash
   python rag_uu.py -q "Apa hak subjek data pribadi?"
   ```
5. Jalankan aplikasi web:
   ```bash
   python export_index.py
   streamlit run streamlit_app.py
   ```

## ✅ Tes

Tes unit untuk parser dan chunker (34 tes, tanpa API dan tanpa file PDF, jadi berjalan dalam hitungan detik dan tidak memakai kuota):

```bash
python -m unittest discover -s tests -v
```

Mencakup pembersihan teks, deteksi BAB dan Pasal, pemulihan judul yang salah baca OCR (dengan validasi urutan), pemecahan per ayat, penanganan Penjelasan, dan konsistensi ID chunk.

## 📊 Evaluasi

Evaluasi retrieval (tanpa LLM): apakah Pasal yang benar muncul di k hasil teratas? Dijalankan dengan `python evaluate.py --eval-set eval_set.json` pada **16** pertanyaan yang kuncinya ditulis manual dari teks UU.

| Metrik | Nilai |
|---|---|
| Hit@1 | 62% (10/16) |
| Hit@3 | 75% (12/16) |
| Hit@5 | 81% (13/16) |
| MRR | 0.703 |

## ⚠️ Keterbatasan

- Bukan nasihat hukum, hanya membaca teks peraturan.
- **Putusan Mahkamah Konstitusi yang mengubah makna pasal belum dimuat.** Contoh: Pasal 53 ayat (1) huruf b UU PDP dan Pasal 31 UU Perlindungan Konsumen.
- PDF UU PDP yang dipakai adalah hasil scan dengan lapisan OCR, sehingga teksnya berisik (misalnya `2O` untuk `20`). Parser mengoreksi judul Pasal, tetapi isi pasal bisa mengandung salah baca.
- Evaluasi memakai set pertanyaan kecil dan hanya mengukur retrieval, bukan kualitas jawaban akhir.
- Versi web berbagi kuota API gratis milik pemilik repo, sehingga bisa menampilkan pesan "kuota penuh".

## 🛠️ Tech stack

Python · LangChain · Google Gemini · Chroma · NumPy · Streamlit · pypdf

## 📄 Lisensi

Kode: MIT (lihat `LICENSE`). Teks undang-undang: domain publik.

## 👤 Author

Khoirul Salman Riyadi · [LinkedIn](https://linkedin.com/in/khoirul-salman-riyadi) · [GitHub](https://github.com/khoirulsr)
