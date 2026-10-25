
import os
import json
import time
import random
import hashlib
import html
import re
import xml.etree.ElementTree as ET

from pathlib import Path
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote

import requests
from google import genai

# =====================================
# KONFIGURASI
# =====================================

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

RIWAYAT_FILE = Path("berita_terkirim.json")
JUMLAH_BERITA = 5
MAKS_UMUR_BERITA_HARI = 7

MODELS = [
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
]

if not GEMINI_KEY:
    raise RuntimeError("Secret GEMINI_API_KEY belum diatur.")

if not TELEGRAM_BOT_TOKEN:
    raise RuntimeError("Secret TELEGRAM_BOT_TOKEN belum diatur.")

if not TELEGRAM_CHAT_ID:
    raise RuntimeError("Secret TELEGRAM_CHAT_ID belum diatur.")

client = genai.Client(api_key=GEMINI_KEY)

# =====================================
# KATA KUNCI AKSI KORPORASI
# =====================================

KATA_KUNCI = [
    "akuisisi",
    "pengambilalihan",
    "merger",
    "penggabungan usaha",
    "private placement",
    "PMTHMETD",
    "right issue",
    "rights issue",
    "HMETD",
    "penambahan modal dengan hak memesan efek terlebih dahulu",
]

# =====================================
# RIWAYAT BERITA
# =====================================

def baca_riwayat():
    if not RIWAYAT_FILE.exists():
        return set()

    try:
        data = json.loads(
            RIWAYAT_FILE.read_text(encoding="utf-8")
        )
        return set(data.get("urls", []))

    except (json.JSONDecodeError, OSError) as e:
        raise RuntimeError(
            f"Riwayat berita gagal dibaca: {e}"
        ) from e


def simpan_riwayat(urls):
    data = {
        "urls": sorted(urls),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    RIWAYAT_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


# =====================================
# MENGAMBIL BERITA GOOGLE NEWS RSS
# =====================================

def ambil_berita():
    query = (
        '("akuisisi" OR "pengambilalihan" OR "merger" OR '
        '"penggabungan usaha" OR "private placement" OR '
        '"PMTHMETD" OR "right issue" OR "rights issue" OR '
        '"HMETD") '
        '(saham OR emiten OR perusahaan OR BEI OR IDX)'
    )

    rss_url = (
        "https://news.google.com/rss/search?q="
        + quote(query)
        + "&hl=id&gl=ID&ceid=ID:id"
    )

    response = requests.get(
        rss_url,
        timeout=30,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()

    root = ET.fromstring(response.content)
    sekarang = datetime.now(timezone.utc)
    berita = []
    url_ditemukan = set()

    for item in root.findall("./channel/item"):
        judul = html.unescape(
            item.findtext("title", "")
        ).strip()

        url = item.findtext("link", "").strip()
        sumber = item.findtext("source", "").strip()
        tanggal = item.findtext("pubDate", "").strip()

        deskripsi = html.unescape(
            re.sub(
                r"<[^>]+>",
                " ",
                item.findtext("description", ""),
            )
        ).strip()

        if not judul or not url:
            continue

        if url in url_ditemukan:
            continue

        url_ditemukan.add(url)

        try:
            waktu = parsedate_to_datetime(tanggal)

            if waktu.tzinfo is None:
                waktu = waktu.replace(tzinfo=timezone.utc)

            waktu = waktu.astimezone(timezone.utc)
            umur_hari = (
                sekarang - waktu
            ).total_seconds() / 86400

            if umur_hari < -1 or umur_hari > MAKS_UMUR_BERITA_HARI:
                continue

            tanggal_tampil = waktu.strftime("%d-%m-%Y")

        except (ValueError, TypeError, OverflowError):
            tanggal_tampil = tanggal

        berita.append({
            "id": hashlib.sha256(
                url.encode("utf-8")
            ).hexdigest(),
            "title": judul,
            "url": url,
            "source": sumber,
            "published": tanggal_tampil,
            "description": deskripsi[:1500],
        })

    berita.sort(
        key=lambda x: x["published"],
        reverse=True,
    )

    print(f"Jumlah berita dari RSS: {len(berita)}")
    return berita


# =====================================
# MENYARING DAN MERANGKUM DENGAN GEMINI
# =====================================

def rangkum_berita(berita):
    data_berita = json.dumps(
        berita,
        ensure_ascii=False,
        indent=2,
    )

    prompt = f"""
Kamu adalah analis aksi korporasi saham Indonesia.

TUGAS:
Pilih berita yang benar-benar membahas salah satu dari
empat kategori berikut saja:

1. AKUISISI
   Pembelian atau pengambilalihan perusahaan, saham,
   atau aset perusahaan.

2. MERGER
   Penggabungan dua atau lebih perusahaan.

3. PRIVATE PLACEMENT
   Penerbitan saham baru tanpa HMETD, termasuk PMTHMETD.

4. RIGHT ISSUE
   Penerbitan saham baru dengan HMETD.

ATURAN WAJIB:
- Jangan memasukkan berita di luar empat kategori tersebut.
- Jangan memasukkan dividen, buyback, pergantian direksi,
  laporan keuangan, atau berita saham umum.
- Prioritaskan perusahaan publik Indonesia dan emiten BEI.
- Jangan mengarang fakta, tanggal, kode saham, nilai transaksi,
  status transaksi, sumber, atau tautan.
- Gunakan hanya informasi dari data berita yang diberikan.
- Bedakan rumor, rencana, persetujuan, dan transaksi selesai.
- Jika hanya rumor, beri label BELUM TERKONFIRMASI.
- Jangan mengklaim berita telah dikonfirmasi IDX jika datanya
  tidak menunjukkan bukti pengumuman resmi.
- Maksimal {JUMLAH_BERITA} berita.
- Jangan mengulang berita yang sama dengan judul berbeda.
- Pertahankan tautan asli yang diberikan.

FORMAT SETIAP BERITA:

📌 [KATEGORI AKSI KORPORASI]
🏢 Emiten/perusahaan:
📰 Judul:
📝 Ringkasan:
💰 Nilai transaksi: (jika tersedia)
📅 Tanggal:
🔎 Status: (rumor/rencana/disetujui/selesai/tidak diketahui)
🗞️ Sumber:
🔗 Tautan:

Pisahkan setiap berita dengan garis pemisah.

Jika tidak ada berita yang memenuhi kriteria, balas tepat:
TIDAK_ADA_BERITA_RELEVAN

DATA BERITA:
{data_berita}
"""

    for model in MODELS:
        for percobaan in range(1, 3):
            try:
                print(
                    f"Mencoba model {model}, "
                    f"percobaan {percobaan}/2"
                )

                hasil = client.models.generate_content(
                    model=model,
                    contents=prompt,
                )

                teks = hasil.text

                if teks and teks.strip():
                    print(f"Berhasil menggunakan {model}")
                    return teks.strip()

                break

            except Exception as e:
                print(
                    f"Model {model} gagal: "
                    f"{type(e).__name__}: {e}"
                )

                if percobaan < 2:
                    jeda = (
                        5 * (2 ** (percobaan - 1))
                        + random.uniform(0, 2)
                    )
                    print(f"Mencoba lagi dalam {jeda:.1f} detik")
                    time.sleep(jeda)

    raise RuntimeError(
        "Semua model Gemini gagal. Tidak ada berita dikirim."
    )


# =====================================
# KIRIM PESAN KE TELEGRAM
# =====================================

def kirim_telegram(pesan):
    url = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    potongan = []

    while len(pesan) > 3800:
        posisi = pesan.rfind("\n", 0, 3800)

        if posisi < 500:
            posisi = 3800

        potongan.append(pesan[:posisi])
        pesan = pesan[posisi:].lstrip()

    if pesan:
        potongan.append(pesan)

    for nomor, bagian in enumerate(potongan, start=1):
        response = requests.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": bagian,
                "disable_web_page_preview": True,
            },
            timeout=30,
        )

        response.raise_for_status()
        hasil = response.json()

        if not hasil.get("ok"):
            raise RuntimeError(
                f"Telegram menolak pesan: {hasil}"
            )

        print(
            f"Pesan Telegram {nomor}/{len(potongan)} terkirim."
        )


# =====================================
# PROSES UTAMA
# =====================================

def main():
    print("====================================")
    print("BOT PEMANTAU AKSI KORPORASI")
    print("Akuisisi | Merger | Private Placement | Right Issue")
    print("====================================")

    riwayat = baca_riwayat()
    semua_berita = ambil_berita()

    if not semua_berita:
        print("Tidak ada berita dari RSS.")
        return

    baru = [
        berita for berita in semua_berita
        if berita["url"] not in riwayat
    ]

    if not baru:
        print("Tidak ada berita baru. Tidak mengirim pesan.")
        return

    # Batasi jumlah artikel yang dikirim ke Gemini.
    calon = baru[:20]

    print(
        f"Ada {len(baru)} URL berita baru; "
        f"{len(calon)} akan disaring."
    )

    rangkuman = rangkum_berita(calon)

    if "TIDAK_ADA_BERITA_RELEVAN" in rangkuman:
        print("Tidak ada berita relevan dari empat kategori.")
        return

    pesan = (
        "📊 PEMANTAU AKSI KORPORASI SAHAM INDONESIA\n\n"
        "Kategori: Akuisisi | Merger | Private Placement | Right Issue\n"
        f"Waktu pemeriksaan: "
        f"{datetime.now(timezone.utc).strftime('%d-%m-%Y %H:%M UTC')}\n\n"
        f"{rangkuman}\n\n"
        "⚠️ Sumber awal: Google News RSS. "
        "Periksa keterbukaan informasi resmi IDX/BEI dan "
        "pengumuman emiten sebelum mengambil keputusan investasi."
    )

    kirim_telegram(pesan)

    # Simpan URL yang diperiksa setelah pengiriman berhasil,
    # agar artikel yang sama tidak diproses berulang kali.
    riwayat.update(
        berita["url"] for berita in calon
    )
    simpan_riwayat(riwayat)

    print("Riwayat berita berhasil diperbarui.")
    print("Bot selesai dijalankan.")


if __name__ == "__main__":
    main()
