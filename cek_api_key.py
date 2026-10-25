"""
Cek apakah API key Gemini-mu benar-benar diterima Google, TANPA LangChain.
Skrip ini tidak pernah mencetak isi key.

Pemakaian (di folder yang sama dengan .env):
    python cek_api_key.py
"""
import json
import os
import sys
import urllib.error
import urllib.request
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent / ".env", override=True, encoding="utf-8-sig")
key = next((os.getenv(n) for n in ("GEMINI", "GEMINI_API_KEY", "GOOGLE_API_KEY") if os.getenv(n)), None)
if not key:
    sys.exit("API key tidak ditemukan di .env")
key = key.strip()

print("== Info key (tanpa isi) ==")
if key.startswith("AIza"):
    print("Format: klasik (AIza...)")
elif key.startswith("AQ."):
    print("Format: baru (AQ....)")
else:
    print("Format: tidak dikenali (bukan AIza... / AQ....). Cek apakah ada spasi, tanda kutip, atau teks lain.")
print(f"Panjang: {len(key)} karakter")

print("\n== Versi library ==")
for pkg in ("google-genai", "langchain-google-genai", "langchain-community", "chromadb"):
    try:
        print(f"{pkg}: {version(pkg)}")
    except PackageNotFoundError:
        print(f"{pkg}: tidak terpasang")

print("\n== Tes 1: REST langsung (header x-goog-api-key) ==")
request = urllib.request.Request(
    "https://generativelanguage.googleapis.com/v1beta/models?pageSize=5",
    headers={"x-goog-api-key": key},
)
try:
    with urllib.request.urlopen(request, timeout=20) as resp:
        names = [m["name"] for m in json.load(resp).get("models", [])]
        print("BERHASIL. Contoh model:", names[:3])
except urllib.error.HTTPError as exc:
    body = exc.read().decode("utf-8", "replace")
    try:
        reason = json.loads(body)["error"]["details"][0]["reason"]
    except Exception:  # noqa: BLE001
        reason = body[:200]
    print(f"GAGAL: HTTP {exc.code} ({reason})")
except Exception as exc:  # noqa: BLE001
    print("Tidak bisa terhubung ke Google:", exc)

print("\n== Tes 2: SDK google-genai ==")
try:
    from google import genai

    client = genai.Client(api_key=key)
    names = []
    for model in client.models.list():
        names.append(model.name)
        if len(names) == 3:
            break
    print("BERHASIL. Contoh model:", names)
except Exception as exc:  # noqa: BLE001
    print("GAGAL:", type(exc).__name__, str(exc)[:200])