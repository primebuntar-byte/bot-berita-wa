import os
import requests
import google.generativeai as genai

# 1. Ambil Kunci Rahasia dari Environment GitHub
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
FONNTE_TOKEN = os.getenv("FONNTE_TOKEN")
GROUP_ID = os.getenv("WA_GROUP_ID")

def cari_dan_rangkum_berita():
    # Setup Gemini AI
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    # Prompt / Instruksi untuk AI (Bisa Anda ubah topik beritanya nanti)
    prompt = (
        "Tolong carikan dan rangkumkan 3 berita terbaru, penting, dan menarik hari ini "
        "mengenai perkembangan teknologi dan pasar keuangan secara singkat, padat, dan jelas. "
        "Format hasilnya menggunakan poin-poin rapi dengan emoji agar enak dibaca di WhatsApp."
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
    try:
        print("Sedang mencari dan merangkum berita via AI...")
        isi_berita = cari_dan_rangkum_berita()
        
        pesan_final = f"🤖 *RANGKUMAN BERITA HARIAN*\n\n{isi_berita}\n\n_Dikirim otomatis oleh AI Bot_"
        
        print("Sedang mengirim ke grup WhatsApp...")
        kirim_ke_grup_wa(pesan_final)
        print("Selesai!")
    except Exception as e:
        print("Terjadi kesalahan:", e)
