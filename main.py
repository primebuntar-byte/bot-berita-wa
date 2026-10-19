import os
import requests
from google import genai

# Ambil Secret dari GitHub Environment Variables
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

print("Sedang memproses berita dari AI...")
client = genai.Client(api_key=GEMINI_KEY)

# Prompt berita akuisisi perusahaan
prompt = (
    "Tolong rangkumkan 3 berita terbaru dan penting hari ini tentang Perusahaan yang sedang melakukan akuisisi. "
    "Gunakan bahasa Indonesia yang santai dan rapi dengan poin-poin serta emoji agar menarik dibaca di Telegram."
)

response = client.models.generate_content(
    model="gemini-3.8-flash",
    contents=prompt,
)
berita = response.text

print("Sedang mengirim ke Telegram...")

# Endpoint API Bot Telegram
url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

# Format pesan yang dikirim
payload = {
    "chat_id": TELEGRAM_CHAT_ID,
    "text": f"🤖 *RANGKUMAN BERITA HARIAN*\n\n{berita}\n\n_Dikirim otomatis oleh AI_",
    "parse_mode": "Markdown",
}

# Kirim pesan ke grup Telegram
res = requests.post(url, json=payload)

print("Respon Telegram:", res.text)
print("Selesai!")
