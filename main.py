
import os
import json
import time
import random
import re
import html
import hashlib
import xml.etree.ElementTree as ET

from pathlib import Path
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlsplit, urlunsplit
from difflib import SequenceMatcher
from collections import defaultdict

import requests
from google import genai


# =====================================
# KONFIGURASI
# =====================================

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

RIWAYAT_FILE = Path("berita_terkirim.json")
ZONA_WAKTU = ZoneInfo("Asia/Jakarta")

JUMLAH_BERITA = 5
MAKS_ARTIKEL_AI = 30

MODELS = [
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.5-flash-lite",
    "gemini-2.5-flash",
]

KATEGORI_VALID = {
    "akuisisi": "Akuisisi",
    "merger": "Merger",
    "private placement": "Private Placement",
    "right issue": "Right Issue",
}

for nama, nilai in [
    ("GEMINI_API_KEY", GEMINI_KEY),
    ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
    ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
]:
    if not nilai:
        raise RuntimeError(f"Secret {nama} belum diatur.")

client = genai.Client(api_key=GEMINI_KEY)
SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "Mozilla/5.0"})


# =====================================
# UTILITAS
# =====================================

def waktu_sekarang():
    return datetime.now(timezone.utc).astimezone(ZONA_WAKTU)


def normalisasi_teks(teks):
    teks = (teks or "").lower()
    teks = re.sub(r"[^a-z0-9]+", " ", teks)
    return " ".join(teks.split())


def normalisasi_url(url):
    try:
        bagian = urlsplit(url.strip())
        host = bagian.netloc.lower()
        path = bagian.path.rstrip("/")

        if not host or not bagian.scheme.startswith("http"):
            return url.strip()

        return urlunsplit(("https", host, path, "", ""))
    except Exception:
        return url.strip()


def hash_teks(teks):
    return hashlib.sha256(
        teks.encode("utf-8")
    ).hexdigest()


def angka_penting(teks):
    """Ambil angka yang mungkin membedakan satu transaksi."""
    return set(
        re.findall(
            r"\b\d+(?:[.,]\d+)?\s*"
            r"(?:miliar|triliun|juta|lembar|saham|persen|%)?\b",
            normalisasi_teks(teks),
        )
    )


def kemiripan(teks_a, teks_b):
    a = normalisasi_teks(teks_a)
    b = normalisasi_teks(teks_b)

    if not a or not b:
        return 0.0

    return SequenceMatcher(None, a, b).ratio()


# =====================================
# RIWAYAT PERSISTEN
# =====================================

def baca_riwayat():
    if not RIWAYAT_FILE.exists():
        return {
            "urls": [],
            "events": [],
            "updated_at": None,
        }

    try:
        data = json.loads(
            RIWAYAT_FILE.read_text(encoding="utf-8")
        )

        return {
            "urls": data.get("urls", []),
            "events": data.get("events", []),
            "updated_at": data.get("updated_at"),
        }
    except (json.JSONDecodeError, OSError) as e:
        raise RuntimeError(
            f"Riwayat gagal dibaca: {e}"
        ) from e


def simpan_riwayat(riwayat):
    riwayat["urls"] = list(
        dict.fromkeys(riwayat["urls"])
    )[-5000:]

    riwayat["events"] = list(
        dict.fromkeys(riwayat["events"])
    )[-3000:]

    riwayat["updated_at"] = waktu_sekarang().isoformat()

    RIWAYAT_FILE.write_text(
        json.dumps(
            riwayat,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# =====================================
# AMBIL BERITA GOOGLE NEWS RSS
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

    response = SESSION.get(rss_url, timeout=30)
    response.raise_for_status()

    root = ET.fromstring(response.content)
    hari_ini = waktu_sekarang().date()

    berita = []
    url_ditemukan = set()

    for item in root.findall("./channel/item"):
        judul = html.unescape(
            item.findtext("title", "")
        ).strip()

        url = item.findtext("link", "").strip()
        sumber = item.findtext("source", "").strip()
        tanggal = item.findtext("pubDate", "").strip()

        deskripsi_html = item.findtext("description", "")
        deskripsi = html.unescape(
            re.sub(r"<[^>]+>", " ", deskripsi_html)
        ).strip()

        if not judul or not url or not tanggal:
            continue

        url_normal = normalisasi_url(url)

        if url_normal in url_ditemukan:
            continue

        try:
            waktu_terbit = parsedate_to_datetime(tanggal)

            if waktu_terbit.tzinfo is None:
                waktu_terbit = waktu_terbit.replace(
                    tzinfo=timezone.utc
                )

            waktu_lokal = waktu_terbit.astimezone(ZONA_WAKTU)
        except (ValueError, TypeError, OverflowError):
            continue

        if waktu_lokal.date() != hari_ini:
            continue

        url_ditemukan.add(url_normal)

        berita.append({
            "title": judul,
            "url": url,
            "url_normal": url_normal,
            "source": sumber or "Tidak diketahui",
            "published": waktu_lokal.strftime(
                "%d-%m-%Y %H:%M WIB"
            ),
            "description": deskripsi[:1200],
        })

    berita.sort(
        key=lambda x: datetime.strptime(
            x["published"], "%d-%m-%Y %H:%M WIB"
        ),
        reverse=True,
    )

    print(f"Berita terbit hari ini WIB: {len(berita)}")
    return berita


# =====================================
# DEDUPLIKASI LOKAL SEBELUM AI
# =====================================

def gabungkan_berita_serupa(berita):
    """
    Menggabungkan artikel yang judulnya sangat mirip.
    Perbedaan angka transaksi membuat artikel tidak otomatis
    digabung jika angka pentingnya bertentangan.
    """
    kelompok = []

    for item in berita:
        gabung_ke = None

        teks_item = (
            item["title"] + " " + item["description"]
        )

        for grup in kelompok:
            wakil = grup[0]
            teks_wakil = (
                wakil["title"] + " " + wakil["description"]
            )

            skor_judul = kemiripan(
                item["title"], wakil["title"]
            )

            skor_total = kemiripan(
                teks_item, teks_wakil
            )

            angka_a = angka_penting(item["title"])
            angka_b = angka_penting(wakil["title"])

            angka_bertentangan = (
                angka_a and angka_b and angka_a != angka_b
            )

            if angka_bertentangan:
                continue

            if skor_judul >= 0.78 or skor_total >= 0.84:
                gabung_ke = grup
                break

        if gabung_ke is None:
            kelompok.append([item])
        else:
            gabung_ke.append(item)

    hasil = []

    for grup in kelompok:
        # Utamakan artikel dengan deskripsi yang lebih lengkap.
        grup.sort(
            key=lambda x: (
                len(x["description"]),
                len(x["title"]),
            ),
            reverse=True,
        )

        utama = dict(grup[0])

        # Simpan seluruh sumber untuk membantu AI membandingkan
        # berita, tetapi pilih satu URL utama untuk Telegram.
        utama["related_sources"] = [
            {
                "title": x["title"],
                "url": x["url"],
                "source": x["source"],
                "published": x["published"],
                "description": x["description"],
            }
            for x in grup
        ]

        hasil.append(utama)

    print(
        f"Setelah deduplikasi lokal: {len(hasil)} "
        f"dari {len(berita)} artikel"
    )

    return hasil


# =====================================
# AI: KLASIFIKASI DAN DEDUPLIKASI EVENT
# =====================================

def rangkum_berita(berita):
    data = json.dumps(
        berita,
        ensure_ascii=False,
        indent=2,
    )

    prompt = f"""
Kamu adalah analis aksi korporasi saham Indonesia.

DATA ARTIKEL:
{data}

TUGAS:
Pilih hanya peristiwa yang benar-benar membahas:
1. Akuisisi
2. Merger
3. Private Placement
4. Right Issue

ATURAN PENTING:
- Beberapa artikel bisa membahas peristiwa yang SAMA.
- Gabungkan berita lintas media jika emiten, transaksi, dan
  substansi peristiwanya sama.
- Satu peristiwa hanya boleh muncul satu kali dalam output.
- Jangan menganggap artikel sebagai peristiwa berbeda hanya
  karena sumber atau judulnya berbeda.
- Bedakan transaksi yang berbeda pada emiten yang sama.
- Jangan gabungkan rencana transaksi dengan realisasi transaksi
  sebagai perkembangan yang sama tanpa memeriksa konteksnya.
- Jangan mengarang kode saham, nama perusahaan, angka,
  tanggal, status, atau tautan.
- Gunakan hanya informasi dari artikel yang tersedia.
- Prioritaskan perusahaan Indonesia.
- Abaikan dividen, buyback, laporan keuangan, dan berita umum.
- Rumor harus berstatus "Belum terkonfirmasi".
- Ringkasan maksimal satu kalimat.
- Gunakan URL yang benar-benar ada di data.
- Maksimal {JUMLAH_BERITA} peristiwa.
- event_key harus konsisten untuk peristiwa yang sama
  meskipun sumbernya berbeda.
- event_key harus memuat perusahaan, kategori, dan identitas
  transaksi yang dapat diketahui dari sumber.
- Jangan menggunakan URL atau nama media sebagai event_key.
- material_update hanya true jika ada perkembangan material
  yang jelas dibandingkan peristiwa yang sudah pernah dikirim.
- Jika tidak ada berita relevan, kembalikan articles kosong.

Kembalikan JSON saja:
{{
  "articles": [
    {{
      "company": "Nama perusahaan dan kode jika tersedia",
      "category": "Private Placement",
      "description": "Ringkasan satu kalimat",
      "status": "Rencana",
      "source": "Nama sumber utama",
      "url": "URL dari data",
      "event_key": "perusahaan|kategori|identitas transaksi",
      "material_update": false
    }}
  ]
}}

Kategori yang diperbolehkan:
Akuisisi, Merger, Private Placement, Right Issue.
"""

    for model in MODELS:
        for percobaan in range(2):
            try:
                print(f"Mencoba Gemini: {model}")

                hasil = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config={
                        "response_mime_type": "application/json"
                    },
                )

                if not hasil.text:
                    continue

                data_hasil = json.loads(hasil.text)
                artikel_ai = data_hasil.get("articles", [])

                if not isinstance(artikel_ai, list):
                    raise ValueError("Format articles tidak valid")

                sumber_valid = {}

                for b in berita:
                    for sumber in b.get(
                        "related_sources",
                        [{
                            "url": b["url"],
                            "source": b["source"],
                            "published": b["published"],
                        }],
                    ):
                        sumber_valid[
                            normalisasi_url(sumber["url"])
                        ] = sumber

                artikel_valid = []
                event_dalam_batch = set()

                for artikel in artikel_ai:
                    if not isinstance(artikel, dict):
                        continue

                    url = artikel.get("url", "")
                    sumber = sumber_valid.get(
                        normalisasi_url(url)
                    )

                    if not sumber:
                        continue

                    kategori_raw = normalisasi_teks(
                        artikel.get("category", "")
                    )

                    if kategori_raw not in KATEGORI_VALID:
                        continue

                    perusahaan = str(
                        artikel.get("company", "")
                    ).strip()

                    deskripsi = str(
                        artikel.get("description", "")
                    ).strip()

                    event_key = normalisasi_teks(
                        artikel.get("event_key", "")
                    )

                    if not perusahaan or not deskripsi or not event_key:
                        continue

                    # Deduplikasi berdasarkan event_key dalam satu batch.
                    if event_key in event_dalam_batch:
                        continue

                    event_dalam_batch.add(event_key)

                    artikel_valid.append({
                        "company": perusahaan,
                        "category": KATEGORI_VALID[kategori_raw],
                        "description": deskripsi,
                        "status": str(
                            artikel.get(
                                "status",
                                "Tidak diketahui",
                            )
                        ).strip(),
                        "source": sumber.get(
                            "source",
                            artikel.get("source", "Tidak diketahui"),
                        ),
                        "url": sumber["url"],
                        "published": sumber.get(
                            "published",
                            waktu_sekarang().strftime(
                                "%d-%m-%Y %H:%M WIB"
                            ),
                        ),
                        "event_key": event_key,
                        "material_update": (
                            artikel.get("material_update") is True
                        ),
                    })

                print(f"Gemini berhasil: {model}")
                return artikel_valid

            except Exception as e:
                print(
                    f"{model} gagal: "
                    f"{type(e).__name__}: {e}"
                )

                if percobaan == 0:
                    time.sleep(3 + random.uniform(0, 2))

    raise RuntimeError(
        "Semua model Gemini gagal. Riwayat tidak diubah."
    )


# =====================================
# DEDUPLIKASI AKHIR SEBELUM TELEGRAM
# =====================================

def deduplikasi_event(artikel):
    hasil = []
    kunci_ditemukan = set()

    for item in artikel:
        kunci = item["event_key"]

        if kunci in kunci_ditemukan:
            print(f"Duplikat event dilewati: {kunci}")
            continue

        kunci_ditemukan.add(kunci)
        hasil.append(item)

    return hasil


# =====================================
# FORMAT PESAN TELEGRAM
# =====================================

def format_pesan(artikel):
    tanggal_hari_ini = waktu_sekarang().strftime(
        "%d-%m-%Y"
    )

    baris = [
        "📊 <b>INFO BERITA TERBARU A1</b>",
        f"📅 {tanggal_hari_ini} WIB",
        "",
    ]

    for nomor, item in enumerate(artikel, start=1):
        perusahaan = html.escape(item["company"])
        kategori = html.escape(item["category"])
        deskripsi = html.escape(item["description"])
        status = html.escape(item["status"])
        tanggal = html.escape(item["published"])
        sumber = html.escape(
            item["source"] or "Tidak diketahui"
        )
        url = html.escape(item["url"], quote=True)

        baris.extend([
            f"<b>{nomor}. {perusahaan}</b>",
            "",
            "<b>Corporate Action:</b>",
            f"         {kategori}",
            "",
            "<b>Deskripsi:</b>",
            f"         {deskripsi}",
            "",
            f"<b>Status:</b> {status}",
            f"<b>Tanggal:</b> {tanggal}",
            "",
            f'🔗 <a href="{url}">Baca berita</a>',
            "",
            f"<b>Sumber:</b> {sumber}",
            "",
            "━━━━━━━━━━━━━━━━━━",
            "",
        ])

    baris.append(
        "⚠️ Periksa keterbukaan informasi resmi IDX/BEI "
        "sebelum mengambil keputusan investasi."
    )

    return "\n".join(baris)


# =====================================
# KIRIM KE TELEGRAM
# =====================================

def kirim_telegram(pesan):
    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    if len(pesan) > 3800:
        raise RuntimeError(
            "Pesan terlalu panjang. Kurangi jumlah berita."
        )

    response = SESSION.post(
        url,
        json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": pesan,
            "parse_mode": "HTML",
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

    print("Pesan Telegram berhasil dikirim.")


def kirim_tidak_ada_berita():
    tanggal = waktu_sekarang().strftime("%d-%m-%Y")

    pesan = (
        "📊 <b>INFO BERITA TERBARU A1</b>\n"
        f"📅 {tanggal} WIB\n\n"
        "Tidak ada berita aksi korporasi baru "
        "yang relevan hari ini."
    )

    kirim_telegram(pesan)


# =====================================
# PROSES UTAMA
# =====================================

def main():
    print("=" * 40)
    print("BOT PEMANTAU AKSI KORPORASI")
    print("Zona waktu: Asia/Jakarta")
    print("=" * 40)

    riwayat = baca_riwayat()
    berita = ambil_berita()

    urls_lama = set(riwayat["urls"])

    calon = [
        b for b in berita
        if b["url_normal"] not in urls_lama
    ]

    if not calon:
        print("Tidak ada URL baru untuk diperiksa.")
        kirim_tidak_ada_berita()
        return

    # Gabungkan artikel yang sangat mirip sebelum AI.
    calon = gabungkan_berita_serupa(calon)

    # Batasi beban AI.
    calon = calon[:MAKS_ARTIKEL_AI]

    print(
        f"Artikel unik untuk diperiksa AI: {len(calon)}"
    )

    artikel_ai = rangkum_berita(calon)

    # Hapus duplikat dari hasil AI.
    artikel_ai = deduplikasi_event(artikel_ai)

    events_lama = set(riwayat["events"])
    artikel_baru = []

    for item in artikel_ai:
        event_key = item["event_key"]

        if event_key in events_lama:
            if not item["material_update"]:
                print(
                    f"Event lama dilewati: {event_key}"
                )
                continue

        artikel_baru.append(item)

    artikel_baru = deduplikasi_event(
        artikel_baru
    )[:JUMLAH_BERITA]

    if artikel_baru:
        kirim_telegram(
            format_pesan(artikel_baru)
        )

        for item in artikel_baru:
            riwayat["events"].append(
                item["event_key"]
            )
    else:
        kirim_tidak_ada_berita()

    # Tandai semua artikel dalam batch sebagai sudah diperiksa.
    # Simpan hanya setelah pengiriman berhasil.
    for item in berita:
        if item["url_normal"] not in urls_lama:
            riwayat["urls"].append(
                item["url_normal"]
            )

    simpan_riwayat(riwayat)

    print("Riwayat berhasil diperbarui.")
    print("Bot selesai.")


if __name__ == "__main__":
    main()
