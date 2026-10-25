"""
Tes untuk chunking_per_pasal.py. Tidak memakai API, jaringan, maupun file PDF
(pembacaan PDF diganti teks buatan lewat mock), jadi cepat dan gratis.

Jalankan salah satu:
    python -m unittest discover -s tests -v
    pytest -v
"""
import contextlib
import io
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import chunking_per_pasal as cp  # noqa: E402


def numbers(parsed):
    return [p["pasal_no"] for p in parsed]


def body_of(parsed, no):
    return next(p for p in parsed if p["pasal_no"] == no)["body"]


def simple_uu(count=5):
    """UU buatan: BAB I (Pasal 1..count) dengan isi satu baris per Pasal."""
    lines = ["BAB I", "KETENTUAN UMUM"]
    for n in range(1, count + 1):
        lines += [f"Pasal {n}", f"Isi pasal {n}."]
    return "\n".join(lines)


class CleanTextTests(unittest.TestCase):
    def test_removes_page_numbers_headers_and_footers(self):
        raw = "\n".join(["Isi sebelum.", "- 12 -", "PRESIDEN", "REPUBLIK INDONESIA", "BLIK INDONES",
                         "SK No 155350A", "Isi sesudah."])
        cleaned = cp.clean_text(raw)
        self.assertEqual(cleaned, "Isi sebelum.\nIsi sesudah.")

    def test_removes_dotted_page_artifacts_but_keeps_real_headings(self):
        raw = "\n".join(["Pasal 25...", "Pasal 7. . .", "Pasal 71 ...", "Pasal 25", "Isi."])
        cleaned = cp.clean_text(raw)
        self.assertEqual(cleaned, "Pasal 25\nIsi.")

    def test_fixes_ocr_ayat_one(self):
        self.assertIn("ayat (1)", cp.clean_text("sebagaimana dimaksud pada ayat (l) dan ayat (2)"))


class ParsePasalTests(unittest.TestCase):
    def test_numbers_bab_and_bodies(self):
        text = "\n".join(["BAB I", "KETENTUAN UMUM", "Pasal 1", "Isi satu.", "Pasal 2", "Isi dua.",
                          "BAB II", "HAK SUBJEK", "Pasal 3", "Isi tiga."])
        parsed = cp.parse_pasal(text)
        self.assertEqual(numbers(parsed), ["1", "2", "3"])
        self.assertEqual([p["bab"] for p in parsed], ["BAB I KETENTUAN UMUM"] * 2 + ["BAB II HAK SUBJEK"])
        self.assertEqual(body_of(parsed, "2"), "Isi dua.")

    def test_bab_title_is_not_part_of_previous_body(self):
        parsed = cp.parse_pasal(simple_uu(2) + "\nBAB II\nHAK SUBJEK\nPasal 3\nIsi tiga.")
        self.assertNotIn("HAK SUBJEK", body_of(parsed, "2"))

    def test_inline_reference_is_not_a_heading(self):
        text = "\n".join(["Pasal 1", "Aturan ini dikecualikan sebagaimana dimaksud dalam",
                          "Pasal 5 ayat (1) dan ayat (2) berlaku untuk semua.", "Pasal 2", "Isi dua."])
        self.assertEqual(numbers(cp.parse_pasal(text)), ["1", "2"])

    def test_suffix_letter_heading_is_kept(self):
        text = "\n".join(["Pasal 3", "Isi 3.", "Pasal 3A", "Isi 3A.", "Pasal 4", "Isi 4."])
        self.assertEqual(numbers(cp.parse_pasal(text)), ["3", "3A", "4"])

    def test_empty_text_has_no_pasal(self):
        self.assertEqual(cp.parse_pasal("tidak ada judul pasal di sini"), [])


class OcrRecoveryTests(unittest.TestCase):
    """Kasus nyata dari PDF UU PDP hasil scan."""

    def make(self, corrupted):
        """Pasal 1..73; nomor tertentu diganti judul hasil salah baca OCR."""
        lines = ["BAB I", "KETENTUAN UMUM"]
        for n in range(1, 74):
            lines += [corrupted.get(n, f"Pasal {n}"), f"Isi pasal {n}."]
        return "\n".join(lines)

    def test_recovers_misread_headings(self):
        text = self.make({22: "Pasa722", 27: "Pasal2T", 72: "Pasal T2"})
        parsed = cp.parse_pasal(text)
        self.assertEqual(numbers(parsed), [str(n) for n in range(1, 74)])

    def test_recovers_j_variant(self):
        parsed = cp.parse_pasal(self.make({22: "PasaJ22"}))
        self.assertIn("22", numbers(parsed))

    def test_letter_o_instead_of_zero_becomes_70(self):
        parsed = cp.parse_pasal(self.make({70: "Pasal 7O"}))
        self.assertEqual(numbers(parsed), [str(n) for n in range(1, 74)])
        self.assertNotIn("7O", numbers(parsed))
        self.assertEqual(body_of(parsed, "70"), "Isi pasal 70.")

    def test_roman_i_at_start_is_pasal_one(self):
        text = "\n".join(["BAB I", "KETENTUAN", "Pasal I", "Isi satu.", "Pasal 2", "Isi dua."])
        self.assertEqual(numbers(cp.parse_pasal(text)), ["1", "2"])

    def test_non_sequential_guess_is_rejected(self):
        text = simple_uu(5) + "\nPasa17\nbaris sisa yang bukan judul"
        parsed = cp.parse_pasal(text)
        self.assertEqual(numbers(parsed), ["1", "2", "3", "4", "5"])
        self.assertIn("Pasa17", body_of(parsed, "5"))

    def test_corrupted_heading_does_not_leak_into_previous_body(self):
        parsed = cp.parse_pasal(self.make({27: "Pasal2T"}))
        self.assertNotIn("Isi pasal 27", body_of(parsed, "26"))
        self.assertEqual(body_of(parsed, "27"), "Isi pasal 27.")


class SectionSplitTests(unittest.TestCase):
    def test_split_batang_tubuh_and_penjelasan(self):
        body, expl = cp.split_batang_tubuh_penjelasan("Pasal 1\nIsi.\nPENJELASAN\nATAS UU\nPasal 1\nCukup jelas.")
        self.assertIn("Isi.", body)
        self.assertNotIn("PENJELASAN", body)
        self.assertTrue(expl.startswith("PENJELASAN"))

    def test_no_penjelasan(self):
        body, expl = cp.split_batang_tubuh_penjelasan("Pasal 1\nIsi.")
        self.assertEqual((body, expl), ("Pasal 1\nIsi.", ""))

    def test_split_by_ayat(self):
        segments = cp.split_by_ayat("(1) Ayat satu.\n(2) Ayat dua.\n(3) Ayat tiga.")
        self.assertEqual([n for n, _ in segments], ["1", "2", "3"])
        self.assertTrue(segments[1][1].startswith("(2)"))

    def test_split_by_ayat_without_ayat(self):
        self.assertEqual(cp.split_by_ayat("Tanpa ayat."), [(None, "Tanpa ayat.")])

    def test_pack_ayat_groups_small_ayat(self):
        packed = cp.pack_ayat([("1", "(1) a"), ("2", "(2) b"), ("3", "(3) c")], max_chars=200)
        self.assertEqual(len(packed), 1)
        self.assertEqual(packed[0][0], "ayat (1)-(3)")

    def test_pack_ayat_splits_when_full(self):
        segments = [(str(i), f"({i}) " + "x" * 40) for i in range(1, 5)]
        packed = cp.pack_ayat(segments, max_chars=100)
        self.assertGreater(len(packed), 1)
        self.assertTrue(all(len(text) <= 100 for _, text in packed))

    def test_pack_ayat_splits_one_overlong_ayat(self):
        packed = cp.pack_ayat([("1", "(1) " + "kalimat panjang. " * 30)], max_chars=100)
        self.assertGreater(len(packed), 1)
        self.assertTrue(all(label.startswith("ayat (1) bagian") for label, _ in packed))


class ChunkTextTests(unittest.TestCase):
    def test_short_text_is_single_chunk(self):
        self.assertEqual(cp.chunk_text("Teks pendek.", chunk_size=100), ["Teks pendek."])

    def test_long_text_terminates_and_respects_size(self):
        text = " ".join(f"Kalimat nomor {i}." for i in range(200))
        chunks = cp.chunk_text(text, chunk_size=120, overlap=30)
        self.assertGreater(len(chunks), 5)
        self.assertTrue(all(0 < len(c) <= 120 for c in chunks))

    def test_chunks_overlap_and_cover_everything(self):
        text = " ".join(f"kata{i}" for i in range(300))
        chunks = cp.chunk_text(text, chunk_size=100, overlap=30)
        for a, b in zip(chunks, chunks[1:]):
            self.assertTrue(set(a.split()[-3:]) & set(b.split()), "chunk berurutan harus berbagi kata")
        joined = " ".join(chunks)
        for i in (0, 150, 299):
            self.assertIn(f"kata{i}", joined)


class EndToEndTests(unittest.TestCase):
    LONG_PASAL = "\n".join(["Pasal 3"] + [f"({i}) " + "Ketentuan penting nomor %d berlaku bagi setiap orang. " % i * 6
                                          for i in range(1, 5)])

    def doc(self):
        return "\n".join([
            "BAB I", "KETENTUAN UMUM",
            "Pasal 1", "Dalam Undang-Undang ini yang dimaksud dengan data adalah keterangan.",
            "Pasal 2", "(1) Berlaku untuk setiap orang.", "(2) Pengecualian diatur terpisah.",
            "BAB II", "HAK SUBJEK",
            self.LONG_PASAL,
            "PENJELASAN", "ATAS UNDANG-UNDANG CONTOH", "I. UMUM", "Penjelasan umum.",
            "Pasal 1", "Cukup jelas.",
            "Pasal 3", "Yang dimaksud dengan informasi adalah penjelasan tujuan, dasar hukum, dan jangka waktu.",
        ])

    def chunks(self, **kwargs):
        with mock.patch.object(cp, "extract_full_text", return_value=self.doc()):
            return cp.chunk_undang_undang("x.pdf", "UU Contoh 1/2026", max_chars=300, **kwargs)

    def test_metadata_and_header(self):
        c = self.chunks()[0]
        self.assertEqual({"id", "text", "source", "location", "bab", "pasal", "bagian"}, set(c))
        self.assertEqual((c["source"], c["location"], c["pasal"], c["bagian"]),
                         ("UU Contoh 1/2026", "Pasal 1", "1", "Batang Tubuh"))
        self.assertTrue(c["text"].startswith("[UU Contoh 1/2026 | BAB I KETENTUAN UMUM | Pasal 1]\n"))

    def test_ids_are_sequential(self):
        self.assertEqual([c["id"] for c in self.chunks()], list(range(len(self.chunks()))))

    def test_long_pasal_is_split_by_ayat_and_stays_under_limit(self):
        pasal3 = [c for c in self.chunks() if c["pasal"] == "3" and c["bagian"] == "Batang Tubuh"]
        self.assertGreater(len(pasal3), 1)
        self.assertTrue(all("ayat" in c["location"] for c in pasal3))
        self.assertTrue(all(len(c["text"]) < 300 + 120 for c in pasal3))     # batas + header konteks

    def test_penjelasan_skips_cukup_jelas_and_keeps_real_explanations(self):
        penjelasan = [c for c in self.chunks() if c["bagian"] == "Penjelasan"]
        self.assertEqual([c["location"] for c in penjelasan], ["Pasal 3 (Penjelasan)"])
        self.assertNotIn("Cukup jelas", penjelasan[0]["text"])

    def test_penjelasan_can_be_excluded(self):
        self.assertTrue(all(c["bagian"] == "Batang Tubuh" for c in self.chunks(include_penjelasan=False)))

    def test_build_legal_chunks_keeps_ids_unique_across_documents(self):
        with mock.patch.object(cp, "extract_full_text", return_value=self.doc()):
            chunks = cp.build_legal_chunks({"UU A": "a.pdf", "UU B": "b.pdf"}, max_chars=300)
        ids = [c["id"] for c in chunks]
        self.assertEqual(ids, list(range(len(ids))))
        self.assertEqual({c["source"] for c in chunks}, {"UU A", "UU B"})


class CheckSequenceTests(unittest.TestCase):
    def run_check(self, text):
        buffer = io.StringIO()
        with mock.patch.object(cp, "extract_full_text", return_value=text), contextlib.redirect_stdout(buffer):
            cp.check_pasal_sequence("x.pdf", "UU Uji")
        return buffer.getvalue()

    def test_complete(self):
        out = self.run_check(simple_uu(5))
        self.assertIn("terdeteksi 5 Pasal", out)
        self.assertIn("Lengkap.", out)

    def test_reports_missing_numbers(self):
        text = simple_uu(5).replace("Pasal 4\nIsi pasal 4.\n", "")
        self.assertIn("Nomor yang hilang: [4]", self.run_check(text))

    def test_no_pasal_at_all(self):
        self.assertIn("TIDAK ADA Pasal terdeteksi", self.run_check("teks tanpa judul pasal"))

    def test_misread_heading_no_longer_reported_missing(self):
        text = simple_uu(30).replace("Pasal 22\n", "Pasa722\n")
        self.assertIn("Lengkap.", self.run_check(text))


if __name__ == "__main__":
    unittest.main()
