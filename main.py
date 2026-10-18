import os
import requests
import google.generativeai as genai

# Ambil kunci rahasia dari Secrets GitHub
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
FONNTE_TOKEN = os.getenv("FONNTE_TOKEN")
GROUP_ID = os.getenv("WA_GROUP_ID")

def cari_dan_rangkum_berita():
    # Konfigurasi Gemini
    genai.configure(api_key=GEMINI_KEY)
    
    # Menggunakan model gemini-1.5-flash
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = (
        "Tolong rangkumkan 3 berita terbaru dan penting hari ini tentang perkembangan teknologi atau keuangan secara singkat. "
        "Gunakan bahasa Indonesia yang santai dan rapi dengan poin-poin serta emoji agar menarik dibaca di WhatsApp."
    )
    
    response = model.generate_content(prompt)
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
