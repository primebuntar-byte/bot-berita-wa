import os
import requests
from google import genai

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print("Memulai bot berita...")

if not GEMINI_KEY:
    raise Exception("GEMINI_API_KEY belum ditemukan")

if not TELEGRAM_BOT_TOKEN:
    raise Exception("TELEGRAM_BOT_TOKEN belum ditemukan")

if not TELEGRAM_CHAT_ID:
    raise Exception("TELEGRAM_CHAT_ID belum ditemukan")

client = genai.Client(api_key=GEMINI_KEY)

prompt = """
Cari dan rangkum 3 berita terbaru dan penting hari ini
tentang perusahaan yang sedang melakukan akuisisi.

Gunakan bahasa Indonesia yang santai dan rapi.
Buat dalam bentuk poin-poin dan gunakan emoji.

Jangan mengarang berita.
"""

print("Sedang meminta berita ke Gemini...")

response = client.models.generate_content(
    model="gemini-3.8-flash",
    contents=prompt,
)

berita = response.text

print("Berita berhasil dibuat.")
print("Sedang mengirim ke Telegram...")

url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

payload = {
    "chat_id": TELEGRAM_CHAT_ID,
    "text": f"🤖 RANGKUMAN BERITA HARIAN\n\n{berita}\n\n_Dikirim otomatis oleh AI_",
    "parse_mode": "Markdown"
}

res = requests.post(url, json=payload)

print("Status Telegram:", res.status_code)
print("Respon Telegram:", res.text)

if not res.ok:
    raise Exception("Gagal mengirim pesan ke Telegram")

print("Selesai!")
