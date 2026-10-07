import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date, datetime, timedelta
import google.generativeai as genai
from PIL import Image
import libsql_client

# --- GÜVENLİ BAĞLANTILAR (SECRETS) ---
genai.configure(api_key=st.secrets["GEMINI_API_KEY"])

def get_client():
    return libsql_client.create_client_sync(
        url=st.secrets["TURSO_DATABASE_URL"],
        auth_token=st.secrets["TURSO_AUTH_TOKEN"]
    )

def execute_query(sql, params=[]):
    with get_client() as client:
        client.execute(sql, params)

def fetch_data(sql, params=[]):
    with get_client() as client:
        result = client.execute(sql, params)
        if result.rows:
            return pd.DataFrame([tuple(row) for row in result.rows], columns=result.columns)
        return pd.DataFrame(columns=result.columns)

# --- VERİTABANI KURULUMU ---
def init_db():
    queries = [
        '''CREATE TABLE IF NOT EXISTS patients (id INTEGER PRIMARY KEY AUTOINCREMENT, bed_no TEXT, status TEXT DEFAULT 'Aktif', name TEXT, age INTEGER, gender TEXT, admission_date DATE, discharge_date DATE, diagnosis TEXT, history_og TEXT, meds_ki TEXT, relatives_contact TEXT, relative_tc TEXT)''',
        '''CREATE TABLE IF NOT EXISTS daily_evals (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER, eval_date DATE, nm_today TEXT, intubation_status TEXT, antibiotics TEXT, daily_note TEXT)''',
        '''CREATE TABLE IF NOT EXISTS labs (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER, lab_date DATE, crp REAL, wbc REAL, hgb REAL, ure REAL, krea REAL, ck REAL, lab_text TEXT)''',
        '''CREATE TABLE IF NOT EXISTS future_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER, plan_date DATE, description TEXT, is_completed INTEGER DEFAULT 0)'''
    ]
    for q in queries:
        execute_query(q)

init_db()

# --- ARAYÜZ VE UYGULAMA ---
st.set_page_config(page_title="YBÜ Yapay Zeka Asistanlı", layout="wide", page_icon="🏥")
st.markdown("<h1 style='text-align: center; color: #117A65;'>🏥 Nöroloji YBÜ Dijital Dosya & YZ Asistanı</h1>", unsafe_allow_html=True)

st.sidebar.header("📌 Servis Durumu")
view_mode = st.sidebar.radio("Görünüm:", ["Aktif Yatan Hastalar", "Taburcu/Ex Arşivi"])

if view_mode == "Aktif Yatan Hastalar":
    active_patients = fetch_data("SELECT * FROM patients WHERE status = 'Aktif' ORDER BY bed_no")
    bed_list = [f"Yatak {i}" for i in range(1, 10)]
    selected_bed = st.sidebar.selectbox("Yatak Seçiniz:", bed_list)
    
    current_patient = None
    if not active_patients.empty:
        match = active_patients[active_patients['bed_no'] == selected_bed]
        if not match.empty: current_patient = match.iloc[0]

    if current_patient is not None:
       st.markdown("---")
st.subheader("🚪 Hasta Çıkışı / Arşivleme")

col1, col2 = st.columns(2)
with col1:
    cikis_turu = st.selectbox("Çıkış Türü", ["Taburcu", "Ex", "Başka Servise Devir", "Palyatif"])
with col2:
    cikis_tarihi = st.date_input("Çıkış Tarihi")

if st.button("Hastayı Arşivle ve Yatağı Boşalt", type="primary", use_container_width=True):
    try:
        # Sizin yazdığınız execute_query fonksiyonunu kullanıyoruz
        query = f"""
            UPDATE patients 
            SET status = '{cikis_turu}', discharge_date = '{cikis_tarihi}', bed_no = NULL 
            WHERE id = {current_patient['id']}
        """
        execute_query(query)
        st.success(f"Hasta başarıyla {cikis_turu} edildi ve arşive taşındı.")
        st.rerun() 
    except Exception as e:
        st.error(f"Bir hata oluştu: {e}")
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
                    execute_query("INSERT INTO patients (bed_no, name, age, gender, admission_date, diagnosis, history_og, meds_ki) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", 
                                  [selected_bed, p_name, int(p_age), p_gender, str(p_adm_date), p_diag, p_og, p_ki])
                    st.rerun()
else:
    st.sidebar.warning("🗄️ Arşiv Modu")
    archived = fetch_data("SELECT * FROM patients WHERE status != 'Aktif' ORDER BY discharge_date DESC")
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

tabs = st.tabs(["🤖 YZ Asistanı & Konsültasyon", "📅 Gelecek Planları", "🩺 Gözlem & Lab Girişi", "🗂️ Dosya & Arşiv"])

# 1. YAPAY ZEKA ASİSTANI
with tabs[0]:
    st.subheader("🧠 Klinik Yapay Zeka Asistanı")
    st.markdown("Laboratuvar kağıdını yükleyin veya verileri yazın, asistan klinik tabloyu yorumlayıp nörolojik durumla bağdaştırsın.")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        lab_image = st.file_uploader("📸 Lab Sonucu Yükle (Opsiyonel)", type=["png", "jpg", "jpeg"])
        lab_text_input = st.text_area("📝 Veya Önemli Notları Yazın:", height=100)
        
    with col2:
        if st.button("🔮 Asistana Danış (Analiz Et)", use_container_width=True):
            with st.spinner("Asistan verileri yorumluyor..."):
                try:
                    # Model ismini güncel 2.5 sürümüyle değiştirdik
                    model = genai.GenerativeModel('gemini-3.8-flash')
                    prompt = f"""
                    Sen uzman bir yoğun bakım nöroloji doktoru asistanısın. 
                    Hasta: {current_patient['age']} yaş, {current_patient.get('gender', '')}. Tanı: {current_patient['diagnosis']}.
                    Özgeçmiş: {current_patient.get('history_og', 'Yok')}.
                    
                    Görevin:
                    1. Verilerdeki kırmızı bayrakları (anormallikleri) saptamak.
                    2. Bu değerleri nörolojik tanıyla klinik olarak ilişkilendirmek.
                    3. Aksiyon planı veya Konsültasyon önerisi vermek.
                    
                    Ek Veri: {lab_text_input}
                    """
                    if lab_image is not None:
                        img = Image.open(lab_image)
                        response = model.generate_content([prompt, img])
                    else:
                        response = model.generate_content(prompt)
                        
                    st.success("✅ Yorumlama Tamamlandı")
                    st.write(response.text)
                except Exception as e:
                    st.error(f"Bir hata oluştu: {e}")

# 2. GELECEK PLANLARI
with tabs[1]:
    st.subheader("📅 Yaklaşan İşler")
    with st.form("plan_form"):
        c1, c2 = st.columns([1, 3])
        p_date = c1.date_input("Tarih", date.today() + timedelta(days=2))
        p_desc = c2.text_input("Aksiyon Detayı")
        if st.form_submit_button("Planı Ekle") and p_desc:
            execute_query("INSERT INTO future_plans (patient_id, plan_date, description) VALUES (?, ?, ?)", [int(current_patient['id']), str(p_date), p_desc])
            st.rerun()
            
    plans = fetch_data("SELECT * FROM future_plans WHERE patient_id=? ORDER BY is_completed ASC, plan_date ASC", [int(current_patient['id'])])
    if not plans.empty:
        for idx, row in plans.iterrows():
            plan_date = datetime.strptime(row['plan_date'], "%Y-%m-%d").date()
            delta = (plan_date - date.today()).days
            
            if row['is_completed']:
                st.markdown(f"~~[{row['plan_date']}] {row['description']}~~ ✅")
            else:
                col_c, col_t = st.columns([0.05, 0.95])
                check = col_c.checkbox("", key=f"p_{row['id']}")
                if check:
                    execute_query("UPDATE future_plans SET is_completed=1 WHERE id=?", [int(row['id'])])
                    st.rerun()
                
                if delta < 0: col_t.error(f"GECİKTİ! [{row['plan_date']}] - {row['description']}")
                elif delta <= 3: col_t.warning(f"YAKLAŞIYOR! [{row['plan_date']}] - {row['description']}")
                else: col_t.info(f"PLANLI [{row['plan_date']}] - {row['description']}")

# 3. GÜNLÜK DEĞERLENDİRME
with tabs[2]:
    with st.form("daily_form"):
        e_date = st.date_input("Tarih", date.today())
        nm_today = st.text_area("Güncel NM")
        c1, c2 = st.columns(2)
        intub = c1.text_input("Solunum/Entübasyon")
        anti = c2.text_input("Antibiyotikler")
        st.markdown("#### Hızlı Lab Trendi Girişi")
        l1, l2, l3, l4 = st.columns(4)
        crp = l1.number_input("CRP", value=0.0)
        wbc = l2.number_input("WBC", value=0.0)
        krea = l3.number_input("Kreatinin", value=0.0)
        ck = l4.number_input("CK", value=0.0)
        note = st.text_area("Devir Notu")
        
        if st.form_submit_button("Bugünü Kaydet"):
            execute_query("INSERT INTO daily_evals (patient_id, eval_date, nm_today, intubation_status, antibiotics, daily_note) VALUES (?, ?, ?, ?, ?, ?)", 
                          [int(current_patient['id']), str(e_date), nm_today, intub, anti, note])
            if crp>0 or wbc>0 or krea>0 or ck>0:
                execute_query("INSERT INTO labs (patient_id, lab_date, crp, wbc, krea, ck) VALUES (?, ?, ?, ?, ?, ?)", 
                              [int(current_patient['id']), str(e_date), float(crp), float(wbc), float(krea), float(ck)])
            st.success("Kayıt Başarılı.")
            st.rerun()

# 4. DOSYA & ARŞİV
with tabs[3]:
    st.subheader("🗂️ Dosya Dökümü")
    all_evals = fetch_data("SELECT * FROM daily_evals WHERE patient_id=? ORDER BY eval_date DESC", [int(current_patient['id'])])
    all_labs = fetch_data("SELECT * FROM labs WHERE patient_id=? ORDER BY lab_date ASC", [int(current_patient['id'])])
    
    if not all_labs.empty and len(all_labs) > 1:
        st.plotly_chart(px.line(all_labs, x="lab_date", y="crp", title="CRP Seyri", markers=True), use_container_width=True)
        
    for idx, row in all_evals.iterrows():
        with st.expander(f"🗓️ {row['eval_date']}"):
            st.markdown(f"**NM:** {row['nm_today']}\n\n**Not:** {row['daily_note']}")
st.markdown("---")
st.subheader("🚪 Hasta Çıkışı / Arşivleme")

col1, col2 = st.columns(2)
with col1:
    cikis_turu = st.selectbox("Çıkış Türü", ["Taburcu", "Ex", "Başka Servise Devir", "Palyatif"])
with col2:
    cikis_tarihi = st.date_input("Çıkış Tarihi")

if st.button("Hastayı Arşivle ve Yatağı Boşalt", type="primary", use_container_width=True):
    try:
        # Durumu güncelle, çıkış tarihini yaz ve yatağı (bed_no) boşa çıkar
        cur.execute('''
            UPDATE patients 
            SET status = ?, discharge_date = ?, bed_no = NULL 
            WHERE id = ?
        ''', (cikis_turu, cikis_tarihi, current_patient['id']))
        conn.commit()
        st.success(f"Hasta başarıyla {cikis_turu} edildi ve arşive taşındı.")
        st.rerun() # Sayfayı yenile ve yatağı boş göster
    except Exception as e:
        st.error(f"Veritabanı hatası: {e}")
        st.header("🗄️ Geçmiş Hasta Arşivi")
# Sadece durumu 'Aktif' OLMAYAN hastaları getir
cur.execute('''
    SELECT id, name, age, diagnosis, status, admission_date, discharge_date 
    FROM patients 
    WHERE status != 'Aktif' 
    ORDER BY discharge_date DESC
''')
arsiv_hastalar = cur.fetchall()

if arsiv_hastalar:
    import pandas as pd
    # Verileri tabloya dönüştür
    df = pd.DataFrame(arsiv_hastalar, columns=["ID", "İsim", "Yaş", "Tanı", "Çıkış Türü", "Yatış Tarihi", "Çıkış Tarihi"])
    # ID sütununu gizleyerek temiz bir görünüm sun
    st.dataframe(df.drop(columns=["ID"]), hide_index=True, use_container_width=True)
else:
    st.info("Arşivde henüz hasta bulunmamaktadır.")

elif view_mode == "Taburcu/Ex Arşivi":
    st.header("🗄️ Geçmiş Hasta Arşivi")
    
    arsiv_hastalar = fetch_data("""
        SELECT id, name as İsim, age as Yaş, diagnosis as Tanı, 
               status as Durum, admission_date as 'Yatış Tarihi', discharge_date as 'Çıkış Tarihi' 
        FROM patients 
        WHERE status != 'Aktif' 
        ORDER BY discharge_date DESC
    """)
    
    if not arsiv_hastalar.empty:
        st.dataframe(arsiv_hastalar.drop(columns=["id"]), hide_index=True, use_container_width=True)
    else:
        st.info("Arşivde henüz kayıtlı hasta bulunmamaktadır.")
