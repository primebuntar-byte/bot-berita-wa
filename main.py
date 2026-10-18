import os
import requests
from google import genai

GEMINI_KEY = os.getenv("GEMINI_API_KEY")
FONNTE_TOKEN = os.getenv("FONNTE_TOKEN")
GROUP_ID = os.getenv("WA_GROUP_ID")

def cari_dan_rangkum_berita():
    client = genai.Client(api_key=GEMINI_KEY)
    
    prompt = (
        "Tolong rangkumkan 3 berita terbaru dan penting hari ini tentang perkembangan teknologi atau keuangan secara singkat. "
        "Gunakan bahasa Indonesia yang santai dan rapi dengan poin-poin serta emoji agar menarik dibaca di WhatsApp."
    )
    
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
    )
    return response.text

def kirim_ke_grup_wa(pesan):
    url = "https://api.fonnte.com/send"
    headers = {
        "Authorization": FONNTE_TOKEN
    }
    data = {
        "target": GROUP_ID,
        "message": pesan
    }
    
    res = requests.post(url, headers=headers, data=data)
    print("Respon Fonnte:", res.text)

if name == "main":
    print("Sedang memproses berita dari AI...")
    berita = cari_dan_rangkum_berita()
    
    pesan_final = f"🤖 *RANGKUMAN BERITA HARIAN*\n\n{berita}\n\n_Dikirim otomatis oleh AI_"
    
    print("Sedang mengirim ke WhatsApp...")
    kirim_ke_grup_wa(pesan_final)
    print("Selesai!")
