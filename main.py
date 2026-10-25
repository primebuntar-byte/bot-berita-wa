import os
import time
import requests
from google import genai

# ==============================
# AMBIL SECRET DARI GITHUB
# ==============================

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


# ==============================
# CEK SECRET
# ==============================

if not GEMINI_KEY:
    raise Exception("GEMINI_API_KEY belum ditemukan")

if not TELEGRAM_BOT_TOKEN:
    raise Exception("TELEGRAM_BOT_TOKEN belum ditemukan")

if not TELEGRAM_CHAT_ID:
    raise Exception("TELEGRAM_CHAT_ID belum ditemukan")


print("Memulai bot berita...")

client = genai.Client(api_key=GEMINI_KEY)


# ==============================
# PROMPT
# ==============================

prompt = """
Tolong rangkum 3 berita terbaru dan penting hari ini
tentang perusahaan yang sedang melakukan akuisisi.

Gunakan bahasa Indonesia yang santai, jelas, dan rapi.

Format:
🔹 Judul berita
🏢 Perusahaan:
📌 Ringkasan:
💰 Nilai transaksi jika tersedia:
📰 Sumber jika tersedia:

Jangan mengarang informasi.
Jika informasi tidak tersedia, katakan tidak tersedia.
"""


# ==============================
# GEMINI DENGAN RETRY
# ==============================

print("Sedang meminta berita ke Gemini...")

max_retries = 4
base_delay = 5

berita = None

for attempt in range(1, max_retries + 1):

    try:

        print(f"Percobaan Gemini {attempt}/{max_retries}...")

        response = client.models.generate_content(
            model="gemini-3.8-flash",
            contents=prompt,
        )

        berita = response.text

        print("Gemini berhasil memberikan berita.")

        break

    except Exception as e:

        print(f"Gemini gagal: {e}")

        if attempt < max_retries:

            delay = base_delay * (2 ** (attempt - 1))

            print(f"Menunggu {delay} detik sebelum mencoba lagi...")

            time.sleep(delay)

        else:

            print("Gemini gagal setelah semua percobaan.")

            raise


# ==============================
# KIRIM KE TELEGRAM
# ==============================

print("Sedang mengirim berita ke Telegram...")

url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

pesan = (
    "🤖 RANGKUMAN BERITA HARIAN\n\n"
    + berita
    + "\n\n_Dikirim otomatis oleh AI_"
)

payload = {
    "chat_id": TELEGRAM_CHAT_ID,
    "text": pesan,
    "parse_mode": "Markdown"
}

res = requests.post(
    url,
    json=payload,
    timeout=30
)

print("Status Telegram:", res.status_code)
print("Respon Telegram:", res.text)


# ==============================
# CEK HASIL TELEGRAM
# ==============================

if not res.ok:

    raise Exception(
        f"Gagal mengirim pesan ke Telegram: {res.text}"
    )

print("✅ Berita berhasil dikirim ke Telegram!")
