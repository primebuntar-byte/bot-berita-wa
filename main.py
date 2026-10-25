
import os
import time
import random
import requests
from google import genai
from google.genai import errors

# =========================
# 1. KONFIGURASI
# =========================

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not GEMINI_KEY:
    raise RuntimeError("Secret GEMINI_API_KEY belum diatur.")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Secret TELEGRAM_BOT_TOKEN belum diatur.")

if not TELEGRAM_CHAT_ID:
    raise RuntimeError("Secret TELEGRAM_CHAT_ID belum diatur.")

client = genai.Client(api_key=GEMINI_KEY)

# Model dicoba secara berurutan.
# Model berikutnya dicoba jika model sebelumnya gagal.
MODELS = [
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
]

PROMPT = """
Buat rangkuman 3 berita terbaru tentang perusahaan
yang melakukan atau mengumumkan akuisisi, khususnya
perusahaan publik Indonesia dan emiten BEI.

Gunakan bahasa Indonesia yang jelas dan ringkas.

Untuk setiap berita, tuliskan:
- Judul
- Perusahaan yang terlibat
- Ringkasan kejadian
- Nilai transaksi jika tersedia
- Tanggal berita
- Tautan sumber jika tersedia

Jangan mengarang fakta, tanggal, nilai transaksi,
atau tautan. Jika tidak dapat memastikan adanya
berita aktual, katakan dengan jujur bahwa berita
belum dapat diverifikasi.

PENTING:
Pembuatan rangkuman ini saja tidak membuktikan
bahwa kamu telah mencari internet. Jangan mengklaim
berita sebagai berita terbaru jika tidak dapat
memastikan sumber dan tanggalnya.
"""

# =========================
# 2. MINTA HASIL KE GEMINI
# =========================

def buat_berita():
    for model in MODELS:
        print(f"\nMencoba model: {model}")

        # Maksimal 2 percobaan untuk setiap model.
        for attempt in range(1, 3):
            try:
                print(
                    f"Percobaan {attempt}/2 "
                    f"untuk {model}"
                )

                response = client.models.generate_content(
                    model=model,
                    contents=PROMPT,
                )

                text = response.text

                if not text or not text.strip():
                    print("Model menghasilkan teks kosong.")
                    break

                print(f"Berhasil menggunakan {model}")
                return text.strip()

            except Exception as e:
                print(
                    f"Gagal dengan {model}: "
                    f"{type(e).__name__}: {e}"
                )

                # Jangan mengulang error yang biasanya
                # membutuhkan perubahan konfigurasi.
                if isinstance(e, errors.APIError):
                    status = getattr(e, "code", None)

                    if status not in (408, 429, 500, 502, 503, 504):
                        print(
                            "Error bukan gangguan sementara. "
                            "Pindah ke model berikutnya."
                        )
                        break

                if attempt < 2:
                    delay = 5 * (2 ** (attempt - 1))
                    delay += random.uniform(0, 2)

                    print(f"Tunggu {delay:.1f} detik...")
                    time.sleep(delay)

    raise RuntimeError(
        "Semua model gagal. Berita tidak dikirim."
    )


# =========================
# 3. KIRIM KE TELEGRAM
# =========================

def kirim_telegram(berita):
    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    pesan = (
        "🤖 RANGKUMAN BERITA AKUISISI\n\n"
        f"{berita}\n\n"
        "Dikirim otomatis oleh Bot Berita Harian."
    )

    # Telegram membatasi pesan teks sekitar 4096 karakter.
    # Bagi pesan panjang menjadi beberapa bagian.
    bagian = [
        pesan[i:i + 4000]
        for i in range(0, len(pesan), 4000)
    ]

    for nomor, teks in enumerate(bagian, start=1):
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": teks,
        }

        try:
            response = requests.post(
                url,
                json=payload,
                timeout=30,
            )
            response.raise_for_status()

            data = response.json()

            if not data.get("ok"):
                raise RuntimeError(
                    f"Telegram menolak pesan: {data}"
                )

            print(
                f"Pesan {nomor}/{len(bagian)} "
                "berhasil dikirim."
            )

        except requests.RequestException as e:
            raise RuntimeError(
                f"Gagal menghubungi Telegram: {e}"
            ) from e


# =========================
# 4. JALANKAN BOT
# =========================

def main():
    print("Memulai Bot Berita Harian...")

    berita = buat_berita()

    print("\nBerita berhasil dibuat.")
    print("Mengirim ke group Telegram...")

    kirim_telegram(berita)

    print("\nSelesai! Bot berhasil mengirim pesan.")


if __name__ == "__main__":
    main()
    
