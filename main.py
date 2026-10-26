
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
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urlsplit, urlunsplit

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
    "akuisisi",
    "merger",
    "private placement",
    "right issue",
}

for nama, nilai in [
    ("GEMINI_API_KEY", GEMINI_KEY),
    ("TELEGRAM_BOT_TOKEN", TELEGRAM_BOT_TOKEN),
    ("TELEGRAM_CHAT_ID", TELEGRAM_CHAT_ID),
]:
    if not nilai:
        raise RuntimeError(
            f"Secret {nama} belum diatur."
        )

client = genai.Client(api_key=GEMINI_KEY)

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0"
})


# =====================================
# UTILITAS
# =====================================

def waktu_sekarang():
    return datetime.now(timezone.utc).astimezone(
        ZONA_WAKTU
    )


def normalisasi_teks(teks):
    teks = (teks or "").lower()
    teks = re.sub(r"[^a-z0-9]+", " ", teks)
    return " ".join(teks.split())


def normalisasi_url(url):
    """Hilangkan parameter pelacakan yang umum."""
    try:
        bagian = urlsplit(url.strip())
        host = bagian.netloc.lower()
        path = bagian.path.rstrip("/")

        if not host or not bagian.scheme.startswith("http"):
            return url.strip()

        return urlunsplit((
            "https",
            host,
            path,
            "",
            "",
        ))

    except Exception:
        return url.strip()


def hash_teks(teks):
    return hashlib.sha256(
        teks.encode("utf-8")
    ).hexdigest()


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
            RIWAYAT_FILE.read_text(
                encoding="utf-8"
            )
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
    # Batasi ukuran riwayat.
    riwayat["urls"] = list(
        dict.fromkeys(riwayat["urls"])
    )[-5000:]

    riwayat["events"] = list(
        dict.fromkeys(riwayat["events"])
    )[-3000:]

    riwayat["updated_at"] = (
        waktu_sekarang().isoformat()
    )

    RIWAYAT_FILE.write_text(
        json.dumps(
            riwayat,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


# =====================================
# GOOGLE NEWS RSS
# HANYA PUBLIKASI HARI INI WIB
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

    response = SESSION.get(
        rss_url,
        timeout=30,
    )
    response.raise_for_status()

    root = ET.fromstring(response.content)
    tanggal_hari_ini = waktu_sekarang().date()

    berita = []
    url_ditemukan = set()

    for item in root.findall("./channel/item"):
        judul = html.unescape(
            item.findtext("title", "")
        ).strip()

        url = item.findtext("link", "").strip()
        sumber = item.findtext("source", "").strip()
        tanggal = item.findtext("pubDate", "").strip()

        deskripsi_html = item.findtext(
            "description", ""
        )

        deskripsi = html.unescape(
            re.sub(r"<[^>]+>", " ", deskripsi_html)
        ).strip()

        if not judul or not url or not tanggal:
            continue

        url_normal = normalisasi_url(url)

        if url_normal in url_ditemukan:
            continue

        url_ditemukan.add(url_normal)

        # Tolak tanggal yang tidak dapat dibaca.
        try:
            waktu_terbit = parsedate_to_datetime(
                tanggal
            )

            if waktu_terbit.tzinfo is None:
                waktu_terbit = waktu_terbit.replace(
                    tzinfo=timezone.utc
                )

            waktu_lokal = waktu_terbit.astimezone(
                ZONA_WAKTU
            )

        except (ValueError, TypeError, OverflowError):
            continue

        # Hanya berita yang terbit hari ini WIB.
        if waktu_lokal.date() != tanggal_hari_ini:
            continue

        berita.append({
            "title": judul,
            "url": url,
            "url_normal": url_normal,
            "source": sumber,
            "published": waktu_lokal.strftime(
                "%d-%m-%Y %H:%M WIB"
            ),
            "description": deskripsi[:1200],
        })

    berita.sort(
        key=lambda x: datetime.strptime(
            x["published"],
            "%d-%m-%Y %H:%M WIB",
        ),
        reverse=True,
    )

    print(
        f"Berita terbit hari ini "
        f"({tanggal_hari_ini} WIB): {len(berita)}"
    )

    return berita


# =====================================
# AI: PILIH, VERIFIKASI, DAN RINGKAS
# =====================================

def rangkum_berita(berita):
    data = json.dumps(
        berita,
        ensure_ascii=False,
        indent=2,
    )

    prompt = f"""
Kamu adalah analis berita aksi korporasi saham Indonesia.

Pilih hanya berita yang benar-benar membahas:
1. Akuisisi
2. Merger
3. Private Placement
4. Right Issue

DATA SUMBER:
{data}

ATURAN:
- Gunakan hanya fakta dari data sumber.
- Jangan mengarang nama perusahaan, kode saham,
  nilai transaksi, tanggal, status, atau tautan.
- Prioritaskan perusahaan Indonesia.
- Abaikan dividen, buyback, laporan keuangan,
  dan berita saham umum.
- Deskripsi maksimal satu kalimat.
- Bedakan rencana, rumor, persetujuan,
  dan transaksi yang sudah selesai.
- Rumor harus berstatus "Belum terkonfirmasi".
- Jangan mengklaim berita sudah dikonfirmasi IDX
  tanpa bukti.
- Gunakan URL asli dari data.
- Maksimal {JUMLAH_BERITA} peristiwa.
- event_key harus stabil dan spesifik untuk peristiwa.
- Jangan masukkan kata yang berubah hanya karena judul berbeda.
- Perkembangan material baru boleh dikirim kembali.
- Jika tidak ada berita relevan, articles harus [].

Kembalikan JSON saja dengan format:
{{
  "articles": [
    {{
      "company": "Nama perusahaan sesuai sumber",
      "category": "Private Placement",
      "description": "Ringkasan satu kalimat.",
      "date": "26-10-2026",
      "status": "Rencana",
      "source": "Nama sumber",
      "url": "URL asli dari data",
      "event_key": "PERUSAHAAN|kategori|peristiwa spesifik",
      "material_update": false
    }}
  ]
}}

category harus salah satu dari:
Akuisisi, Merger, Private Placement, Right Issue.

material_update hanya true jika sumber secara jelas menunjukkan
perkembangan baru yang material, bukan sekadar judul berbeda.
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

                teks = hasil.text

                if not teks:
                    continue

                data_hasil = json.loads(teks)
                artikel_ai = data_hasil.get(
                    "articles", []
                )

                if not isinstance(artikel_ai, list):
                    raise ValueError(
                        "Format articles tidak valid."
                    )

                sumber_valid = {
                    normalisasi_url(b["url"]): b
                    for b in berita
                }

                artikel_valid = []

                for artikel in artikel_ai:
                    if not isinstance(artikel, dict):
                        continue

                    url = artikel.get("url", "")
                    url_normal = normalisasi_url(url)
                    sumber = sumber_valid.get(url_normal)

                    # Tolak URL yang tidak ada dalam sumber.
                    if not sumber:
                        continue

                    kategori = normalisasi_teks(
                        artikel.get("category", "")
                    )

                    if kategori not in KATEGORI_VALID:
                        continue

                    perusahaan = str(
                        artikel.get("company", "")
                    ).strip()

                    deskripsi = str(
                        artikel.get("description", "")
                    ).strip()

                    event_key = str(
                        artikel.get("event_key", "")
                    ).strip()

                    if (
                        not perusahaan
                        or not deskripsi
                        or not event_key
                    ):
                        continue

                    artikel["url"] = sumber["url"]
                    artikel["source"] = (
                        sumber["source"]
                    )
                    artikel["published"] = (
                        sumber["published"]
                    )

                    artikel["category"] = {
                        "akuisisi": "Akuisisi",
                        "merger": "Merger",
                        "private placement": "Private Placement",
                        "right issue": "Right Issue",
                    }[kategori]

                    artikel["company"] = perusahaan
                    artikel["description"] = deskripsi

                    artikel["status"] = str(
                        artikel.get(
                            "status",
                            "Tidak diketahui",
                        )
                    ).strip()

                    artikel["event_key"] = (
                        normalisasi_teks(event_key)
                    )

                    artikel["material_update"] = (
                        artikel.get("material_update")
                        is True
                    )

                    artikel_valid.append(artikel)

                print(f"Gemini berhasil: {model}")
                return artikel_valid

            except Exception as e:
                print(
                    f"{model} gagal: "
                    f"{type(e).__name__}: {e}"
                )

                if percobaan == 0:
                    time.sleep(
                        3 + random.uniform(0, 2)
                    )

    raise RuntimeError(
        "Semua model Gemini gagal. "
        "Riwayat tidak akan diubah."
    )


# =====================================
# FORMAT PESAN TELEGRAM
# =====================================

def format_pesan(artikel):
    tanggal_hari_ini = (
        waktu_sekarang().strftime("%d-%m-%Y")
    )

    baris = [
        "📊 <b>INFO BERITA TERBARU A1</b>",
        f"📅 {tanggal_hari_ini} WIB",
        "",
    ]

    for nomor, item in enumerate(artikel, start=1):
        perusahaan = html.escape(
            item["company"]
        )
        kategori = html.escape(
            item["category"]
        )
        deskripsi = html.escape(
            item["description"]
        )
        status = html.escape(
            item["status"]
        )
        tanggal = html.escape(
            item["published"]
        )
        sumber = html.escape(
            item["source"] or "Tidak diketahui"
        )
        url = html.escape(
            item["url"],
            quote=True,
        )

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
# KIRIM PESAN KE TELEGRAM
# =====================================

def kirim_telegram(pesan):
    url = (
        "https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    # Telegram membatasi panjang pesan.
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


# =====================================
# PESAN JIKA TIDAK ADA BERITA BARU
# =====================================

def kirim_tidak_ada_berita():
    tanggal = waktu_sekarang().strftime(
        "%d-%m-%Y"
    )

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

    # Jangan proses ulang URL yang pernah diperiksa.
    urls_lama = set(riwayat["urls"])

    calon = [
        b for b in berita
        if b["url_normal"] not in urls_lama
    ][:MAKS_ARTIKEL_AI]

    print(
        f"Artikel baru untuk diperiksa AI: {len(calon)}"
    )

    if not calon:
        kirim_tidak_ada_berita()
        return

    # Jika semua model AI gagal, program berhenti.
    # Riwayat tidak akan diubah sehingga bisa dicoba lagi.
    artikel_ai = rangkum_berita(calon)

    events_lama = set(riwayat["events"])
    artikel_baru = []

    for item in artikel_ai:
        event_key = item["event_key"]

        if event_key in events_lama:
            # Kirim ulang hanya jika ada perkembangan
            # material yang dinyatakan oleh AI.
            if not item["material_update"]:
                continue

        artikel_baru.append(item)

    artikel_baru = artikel_baru[:JUMLAH_BERITA]

    if artikel_baru:
        # Riwayat diperbarui setelah pengiriman berhasil.
        kirim_telegram(
            format_pesan(artikel_baru)
        )

        for item in artikel_baru:
            riwayat["events"].append(
                item["event_key"]
            )

    else:
        kirim_tidak_ada_berita()

    # Tandai URL yang sudah diperiksa.
    riwayat["urls"].extend(
        b["url_normal"] for b in calon
    )

    simpan_riwayat(riwayat)

    print("Riwayat berhasil diperbarui.")
    print("Bot selesai.")


if __name__ == "__main__":
    main()
