import os
import json
import datetime
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import google.generativeai as genai
from telegram import Update
from telegram.ext import ApplicationBuilder, MessageHandler, filters, ContextTypes

# 1. Google Sheets Bağlantısı
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds = ServiceAccountCredentials.from_json_keyfile_name("credentials.json", scope)
client = gspread.authorize(creds)
spreadsheet = client.open("Fitness Tracking")

ws_program = spreadsheet.worksheet("Program Yapısı")
ws_logs = spreadsheet.worksheet("Antrenman Kayıtları")

# 2. Gemini AI Bağlantısı
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

# Kullanıcı Oturum Takibi (O anki antrenman durumunu tutar)
user_sessions = {}

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    user_text = update.message.text.strip()
    
    if user_id not in user_sessions:
        user_sessions[user_id] = {"current_day": None, "current_exercise_idx": 0, "current_set": 1}
    
    session = user_sessions[user_id]
    
    # Program ve Geçmiş Kayıtları Oku
    try:
        program_rows = ws_program.get_all_records()
        log_rows = ws_logs.get_all_records()
    except Exception as e:
        await update.message.reply_text("⚠️ Google Sheets verileri okunamadı. Lütfen tablo isimlerini kontrol edin.")
        return

    # Gemini Prompt Hazırlama
    prompt = f"""
    Sen profesyonel, samimi ve motive edici bir akıllı fitness koçusun.
    Kullanıcı Durumu: {json.dumps(session)}
    Kullanıcının Mesajı: "{user_text}"
    Mevcut Antrenman Programı Yapısı: {json.dumps(program_rows)}
    Kullanıcının Son Antrenman Geçmiş Kayıtları: {json.dumps(log_rows[-15:] if log_rows else [])}
    Günün Tarihi ve Saati: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}
    
    GÖREVİN VE DAVRANIŞ KURALLARIN:
    1. Kullanıcı "Bugün ne yapıyoruz?", "Hangi gündeyiz?" veya belirli bir gün (Push, Pull, Legs vb.) sorduğunda programdan o günün İLK HAREKETİNİ ve son geçmiş antrenmandaki referans ağırlık/tekrarını söyleyerek motive et.
    2. Kullanıcı set sonucunu veriyorsa (örneğin "20 kg ile 10 tekrar yaptım", "25 bastım 8 çıktı", "ilk set bitti 80kg 8 tekrar"):
       - Kullanıcıyı tebrik et/motive et.
       - Bir sonraki seti veya sıradaki hareketi hatırlat.
       - Veriyi kaydedebilmem için yanıtının EN SONUNA tam olarak şu formatta gizli JSON bloğu ekle:
         DATA_INSERT: {{"gun": "...", "hareket": "...", "set": 1, "kilo": 20, "tekrar": 10}}
    """
    
    try:
        response = model.generate_content(prompt)
        reply_text = response.text
        
        # Eğer yanıtta veri kaydetme bloğu varsa
        if "DATA_INSERT:" in reply_text:
            parts = reply_text.split("DATA_INSERT:")
            raw_json = parts[1].strip()
            
            try:
                data = json.loads(raw_json)
                now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
                
                # Google Sheets'e Kaydet: Tarih | Gün | Hareket Adı | Set No | Ağırlık (KG) | Tekrar | Not
                ws_logs.append_row([
                    now_str, 
                    data.get("gun", session.get("current_day", "Antrenman")), 
                    data.get("hareket", "Hareket"), 
                    data.get("set", session["current_set"]), 
                    data.get("kilo", 0), 
                    data.get("tekrar", 0), 
                    "Sohbet Kaydı"
                ])
                
                session["current_set"] += 1
            except Exception as parse_err:
                print(f"JSON Parse/Insert Hatası: {parse_err}")
            
            # Kullanıcıya sadece temiz koçluk mesajını göster
            reply_text = parts[0].strip()

        await update.message.reply_text(reply_text)
        
    except Exception as ai_err:
        print(f"AI İşleme Hatası: {ai_err}")
        await update.message.reply_text("Bir hata oluştu, lütfen tekrar deneyin.")

if __name__ == '__main__':
    BOT_TOKEN = os.environ.get("BOT_TOKEN")
    if not BOT_TOKEN:
        print("HATA: BOT_TOKEN çevre değişkeni bulunamadı!")
    else:
        app = ApplicationBuilder().token(BOT_TOKEN).build()
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        print("🚀 Akıllı Fitness Botu Başarıyla Çalıştırıldı...")
        app.run_polling()