import streamlit as st
import sqlite3
import pandas as pd
import plotly.express as px
from datetime import date, datetime, timedelta
import os
import google.generativeai as genai
from PIL import Image

# ==========================================
# ⚙️ AYARLAR: DRIVE YOLU VE YAPAY ZEKA API
# ==========================================

# 1. Google Drive Klasör Yolunuz (Kendi bilgisayarınıza göre düzenleyin)
# Örnek Windows: r"C:\Users\Adiniz\Google Drive\YBÜ_Veritabani\klinik_yogun_bakim_v3.db"
# Örnek Mac: "/Users/Adiniz/Google Drive/YBÜ_Veritabani/klinik_yogun_bakim_v3.db"
# Şimdilik aynı klasöre kurması için varsayılan bırakıyorum, bunu kendi Drive yolunuzla değiştirin:
DB_PATH = "klinik_yogun_bakim_v3.db" 

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS patients (id INTEGER PRIMARY KEY AUTOINCREMENT, bed_no TEXT, status TEXT DEFAULT 'Aktif', name TEXT, age INTEGER, gender TEXT, admission_date DATE, discharge_date DATE, diagnosis TEXT, history_og TEXT, meds_ki TEXT, relatives_contact TEXT, relative_tc TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS daily_evals (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER, eval_date DATE, nm_today TEXT, intubation_status TEXT, antibiotics TEXT, daily_note TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS labs (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER, lab_date DATE, crp REAL, wbc REAL, hgb REAL, ure REAL, krea REAL, ck REAL, lab_text TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS future_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER, plan_date DATE, description TEXT, is_completed INTEGER DEFAULT 0)''')
    conn.commit()
    conn.close()

init_db()
def get_db(): return sqlite3.connect(DB_PATH)

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="YBÜ Yapay Zeka Asistanlı", layout="wide", page_icon="🏥")
st.markdown("<h1 style='text-align: center; color: #117A65;'>🏥 Nöroloji YBÜ Dijital Dosya & YZ Asistanı</h1>", unsafe_allow_html=True)

# --- YAN MENÜ: AYARLAR VE HASTA SEÇİMİ ---
with st.sidebar.expander("⚙️ Sistem Ayarları (Drive & API)"):
    st.info(f"Veritabanı Yolu: \n`{DB_PATH}`")
    api_key_input = st.text_input("Gemini API Key (Yapay Zeka için)", type="password")
    if api_key_input:
        genai.configure(api_key=api_key_input)
        st.success("YZ Asistanı Aktif!")

st.sidebar.header("📌 Servis Durumu")
view_mode = st.sidebar.radio("Görünüm:", ["Aktif Yatan Hastalar", "Taburcu/Ex Arşivi"])

if view_mode == "Aktif Yatan Hastalar":
    conn = get_db()
    active_patients = pd.read_sql_query("SELECT * FROM patients WHERE status = 'Aktif' ORDER BY bed_no", conn)
    conn.close()
    
    bed_list = [f"Yatak {i}" for i in range(1, 10)]
    selected_bed = st.sidebar.selectbox("Yatak Seçiniz:", bed_list)
    
    current_patient = None
    if not active_patients.empty:
        match = active_patients[active_patients['bed_no'] == selected_bed]
        if not match.empty: current_patient = match.iloc[0]

    if current_patient is not None:
        st.sidebar.success(f"**Yatan Hasta:** {current_patient['name']} ({current_patient['age']} Y)")
        with st.sidebar.expander("⚠️ Hastayı Taburcu/Ex Et"):
            out_status = st.selectbox("Çıkış Durumu", ["Taburcu", "Ex"])
            if st.button("Onayla ve Arşivle"):
                conn = get_db()
                conn.cursor().execute("UPDATE patients SET status=?, bed_no='-', discharge_date=? WHERE id=?", (out_status, str(date.today()), current_patient['id']))
                conn.commit()
                conn.close()
                st.rerun()
    else:
        st.sidebar.info("Bu yatak şu an BOŞ.")
        with st.sidebar.expander("➕ Yeni Hasta Kabulü"):
            with st.form("new_patient_form"):
                p_name = st.text_input("Ad Soyad")
                p_age = st.number_input("Yaş", 18, 120, 60)
                p_gender = st.selectbox("Cinsiyet", ["Kadın", "Erkek"])
                p_adm_date = st.date_input("Yatış Tarihi", date.today())
                p_diag = st.text_input("Tanı")
                p_og = st.text_area("Özgeçmiş (ÖG)")
                p_ki = st.text_area("Kullandığı İlaçlar (Kİ)")
                if st.form_submit_button("Hastayı Yatır") and p_name:
                    conn = get_db()
                    conn.cursor().execute("INSERT INTO patients (bed_no, name, age, gender, admission_date, diagnosis, history_og, meds_ki) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (selected_bed, p_name, p_age, p_gender, str(p_adm_date), p_diag, p_og, p_ki))
                    conn.commit()
                    conn.close()
                    st.rerun()
else:
    st.sidebar.warning("🗄️ Arşiv Modu")
    conn = get_db()
    archived = pd.read_sql_query("SELECT * FROM patients WHERE status != 'Aktif' ORDER BY discharge_date DESC", conn)
    conn.close()
    if not archived.empty:
        opts = archived['name'] + " (" + archived['status'] + ")"
        sel = st.sidebar.selectbox("Hastalar:", opts)
        current_patient = archived.iloc[opts.tolist().index(sel)]
    else:
        st.sidebar.info("Arşiv boş.")
        current_patient = None

if current_patient is None: st.stop()

# --- HASTA BİLGİ KARTI ---
st.markdown(f"### 🛏️ {current_patient['bed_no']} | {current_patient['name']} | Yaş: {current_patient['age']} | Tanı: {current_patient['diagnosis']}")
st.markdown("---")

tabs = st.tabs(["🤖 Yapay Zeka Asistanı & Konsültasyon", "📅 Gelecek Planları", "🩺 Değerlendirme & Lab Girişi", "🗂️ Dosya & Arşiv"])

# 1. YAPAY ZEKA ASİSTANI
with tabs[0]:
    st.subheader("🧠 Klinik Yapay Zeka Asistanı")
    st.markdown("Hastanın verilerini veya laboratuvar ekran görüntüsünü yükleyin, asistan klinik tabloyu yorumlasın ve konsültasyon/tedavi önerilerinde bulunsun.")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        lab_image = st.file_uploader("📸 Laboratuvar Ekran Görüntüsü Yükle (Opsiyonel)", type=["png", "jpg", "jpeg"])
        lab_text_input = st.text_area("📝 Veya Önemli Lab/Klinik Notları Buraya Yazın:", height=100, placeholder="Örn: CRP 120'den 250'ye çıktı, lökosit 18 bin, idrar çıkışı azaldı...")
        
    with col2:
        if st.button("🔮 Asistana Danış (Analiz Et)", use_container_width=True):
            if not api_key_input:
                st.error("Lütfen sol menüden Gemini API Key giriniz.")
            else:
                with st.spinner("Asistan verileri yorumluyor, anormallikleri tespit edip konsültasyon önerileri hazırlıyor..."):
                    try:
                        # Yapay Zekaya Gönderilecek İçerik (Prompt)
                        model = genai.GenerativeModel('gemini-1.5-flash')
                        
                        prompt = f"""
                        Sen uzman bir yoğun bakım nöroloji doktoru asistanısın. 
                        Hasta Bilgisi: {current_patient['age']} yaşında {current_patient.get('gender', 'belirtilmemiş')}, Ana Tanı: {current_patient['diagnosis']}.
                        Özgeçmiş: {current_patient.get('history_og', 'Yok')}.
                        
                        Aşağıdaki güncel laboratuvar verilerini/notları veya resmi incele. 
                        1. Kırmızı bayrakları (anormal değerleri) belirle.
                        2. Hastanın nörolojik tanısı ve yaşıyla bu anormallikleri ilişkilendir.
                        3. Mevcut klinik tabloya göre EKSİKLİKLERİ veya alınması gereken aksiyonları söyle (Örn: hidrasyon, antibiyotik revizyonu).
                        4. Gerekli görüyorsan spesifik KONSÜLTASYON önerilerinde bulun ve gerekçesini kısa ve net belirt.
                        
                        Ek veri/Not: {lab_text_input}
                        """
                        
                        # Eğer görsel yüklendiyse model ile birlikte gönder
                        if lab_image is not None:
                            img = Image.open(lab_image)
                            response = model.generate_content([prompt, img])
                        else:
                            response = model.generate_content(prompt)
                            
                        st.success("✅ Asistan Yorumu Tamamlandı")
                        st.markdown("### 📋 Asistanın Klinik Değerlendirmesi:")
                        st.write(response.text)
                        
                    except Exception as e:
                        st.error(f"Bir hata oluştu: {e}")

# 2. GELECEK PLANLARI
with tabs[1]:
    st.subheader("📅 Yaklaşan İşler ve Planlar")
    with st.form("plan_form"):
        c1, c2 = st.columns([1, 3])
        p_date = c1.date_input("Tarih", date.today() + timedelta(days=2))
        p_desc = c2.text_input("Aksiyon (Örn: Trakeostomi planı, Anestezi konsu)")
        if st.form_submit_button("Planı Ekle") and p_desc:
            conn = get_db()
            conn.cursor().execute("INSERT INTO future_plans (patient_id, plan_date, description) VALUES (?, ?, ?)", (current_patient['id'], str(p_date), p_desc))
            conn.commit()
            conn.close()
            st.rerun()
            
    conn = get_db()
    plans = pd.read_sql_query("SELECT * FROM future_plans WHERE patient_id=? ORDER BY is_completed ASC, plan_date ASC", conn, params=(current_patient['id'],))
    conn.close()
    
    if not plans.empty:
        for idx, row in plans.iterrows():
            plan_date = datetime.strptime(row['plan_date'], "%Y-%m-%d").date()
            delta = (plan_date - date.today()).days
            
            # Renklendirme mantığı
            if row['is_completed']:
                st.markdown(f"~~[{row['plan_date']}] {row['description']}~~ ✅")
            else:
                col_c, col_t = st.columns([0.05, 0.95])
                check = col_c.checkbox("", key=f"p_{row['id']}")
                if check:
                    conn = get_db()
                    conn.cursor().execute("UPDATE future_plans SET is_completed=1 WHERE id=?", (row['id'],))
                    conn.commit()
                    conn.close()
                    st.rerun()
                
                if delta < 0:
                    col_t.error(f"GECİKTİ! [{row['plan_date']}] - {row['description']}")
                elif delta <= 3:
                    col_t.warning(f"YAKLAŞIYOR! ({delta} gün kaldı) [{row['plan_date']}] - {row['description']}")
                else:
                    col_t.info(f"PLANLI [{row['plan_date']}] - {row['description']}")

# 3. GÜNLÜK DEĞERLENDİRME & LAB GİRİŞİ
with tabs[2]:
    with st.form("daily_form"):
        e_date = st.date_input("Tarih", date.today())
        nm_today = st.text_area("Nörolojik Muayene")
        c1, c2 = st.columns(2)
        intub = c1.text_input("Solunum/Entübasyon")
        anti = c2.text_input("Antibiyotikler")
        st.markdown("#### Hızlı Lab Girişi (Trend İçin Önemli Olanlar)")
        l1, l2, l3, l4 = st.columns(4)
        crp = l1.number_input("CRP", value=0.0)
        wbc = l2.number_input("WBC", value=0.0)
        krea = l3.number_input("Kreatinin", value=0.0)
        ck = l4.number_input("CK", value=0.0)
        note = st.text_area("Devir Notu")
        
        if st.form_submit_button("Bugünü Kaydet"):
            conn = get_db()
            conn.cursor().execute("INSERT INTO daily_evals (patient_id, eval_date, nm_today, intubation_status, antibiotics, daily_note) VALUES (?, ?, ?, ?, ?, ?)", (current_patient['id'], str(e_date), nm_today, intub, anti, note))
            if crp>0 or wbc>0 or krea>0 or ck>0:
                conn.cursor().execute("INSERT INTO labs (patient_id, lab_date, crp, wbc, krea, ck) VALUES (?, ?, ?, ?, ?, ?)", (current_patient['id'], str(e_date), crp, wbc, krea, ck))
            conn.commit()
            conn.close()
            st.success("Kayıt Başarılı.")
            st.rerun()

# 4. DOSYA & ARŞİV
with tabs[3]:
    st.subheader("🗂️ Geçmiş ve Grafikler")
    conn = get_db()
    all_evals = pd.read_sql_query("SELECT * FROM daily_evals WHERE patient_id=? ORDER BY eval_date DESC", conn, params=(current_patient['id'],))
    all_labs = pd.read_sql_query("SELECT * FROM labs WHERE patient_id=? ORDER BY lab_date ASC", conn, params=(current_patient['id'],))
    conn.close()
    
    if not all_labs.empty and len(all_labs) > 1:
        st.plotly_chart(px.line(all_labs, x="lab_date", y="crp", title="CRP Seyri", markers=True), use_container_width=True)
        
    for idx, row in all_evals.iterrows():
        with st.expander(f"🗓️ {row['eval_date']}"):
            st.markdown(f"**NM:** {row['nm_today']}\n\n**Not:** {row['daily_note']}")
