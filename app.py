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
        '''CREATE TABLE IF NOT EXISTS future_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER, plan_date DATE, description TEXT, is_completed INTEGER DEFAULT 0)''',
        '''CREATE TABLE IF NOT EXISTS ai_chats (id INTEGER PRIMARY KEY AUTOINCREMENT, patient_id INTEGER, role TEXT, content TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)'''
    ]
    for q in queries:
        execute_query(q)

    # Yeni eklenen sütunlar (Anamnez ve diğerleri)
    new_patient_cols = {
        "er_admission_date": "DATE", "icu_admission_date": "DATE", "pre_diagnosis": "TEXT", "ekg": "TEXT",
        "chief_complaint": "TEXT", "anamnesis": "TEXT", "initial_nm": "TEXT", "initial_labs": "TEXT", "initial_neuroimaging": "TEXT"
    }
    new_eval_cols = {
        "mayi": "TEXT", "sedasyon": "TEXT", "inotrop": "TEXT", "anti_odem": "TEXT", "antinobet": "TEXT", 
        "antitrombotik": "TEXT", "beslenme": "TEXT", "kan_gazi": "TEXT", "yara_durumu": "TEXT", 
        "norogoruntuleme": "TEXT", "diger_goruntuleme": "TEXT", "konsultasyonlar": "TEXT", "hasta_yakini": "TEXT"
    }
    
    for col, d_type in new_patient_cols.items():
        try: execute_query(f"ALTER TABLE patients ADD COLUMN {col} {d_type}")
        except: pass
        
    for col, d_type in new_eval_cols.items():
        try: execute_query(f"ALTER TABLE daily_evals ADD COLUMN {col} {d_type}")
        except: pass

init_db()

# --- ARAYÜZ KURULUMU ---
st.set_page_config(page_title="YBÜ Dijital Asistan", layout="wide", page_icon="🏥")
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
        patient_diag = current_patient.get('pre_diagnosis') if current_patient.get('pre_diagnosis') else current_patient.get('diagnosis', 'Girilemedi')
        
        # --- SOL MENÜ HASTA KARTI ---
        st.sidebar.markdown("---")
        st.sidebar.markdown(f"### 🛏️ {current_patient['bed_no']}")
        st.sidebar.markdown(f"**{current_patient['name']}** ({current_patient['age']} Y, {current_patient.get('gender', '')})")
        st.sidebar.markdown(f"**Acil/Yatış Tarihi:** {current_patient.get('er_admission_date', '-')}")
        st.sidebar.markdown(f"**YBÜ Geliş Tarihi:** {current_patient.get('icu_admission_date', '-')}")
        st.sidebar.markdown(f"**Ön Tanı:** {patient_diag}")
        st.sidebar.markdown("---")

        # --- SEKMELER (5 ADET) ---
        tabs = st.tabs([
            "🏥 1. İlk Başvuru & Anamnez", 
            "🩺 2. Günlük Gözlem & Lab", 
            "🧠 3. YZ Asistanı (Vaka)", 
            "📅 4. Gelecek Planları", 
            "🗂️ 5. Dosya & Arşiv"
        ])

        # TAB 1: İLK BAŞVURU & ANAMNEZ
        with tabs[0]:
            st.subheader("🏥 İlk Başvuru, Anamnez ve Temel Bulgular")
            st.info("Hastanın acil veya servise ilk gelişindeki hikayesini ve temel bulgularını buradan girebilir veya güncelleyebilirsiniz.")
            with st.form("anamnez_form"):
                sikayet = st.text_input("Acile Geliş Şikayeti", value=current_patient.get('chief_complaint', '') or "")
                hikaye = st.text_area("Anamnez / Neler Olmuş? (Hikaye)", value=current_patient.get('anamnesis', '') or "", height=100)
                ozgecmis = st.text_area("Özgeçmiş (ÖG) & Kullandığı İlaçlar", value=current_patient.get('history_og', '') or "", height=80)
                
                st.markdown("##### İlk Klinik Durum (Yatış Anı)")
                c1, c2 = st.columns(2)
                with c1:
                    ilk_nm = st.text_area("İlk Nörolojik Muayene", value=current_patient.get('initial_nm', '') or "", height=100)
                    ilk_lab = st.text_area("İlk Laboratuvar Bulguları", value=current_patient.get('initial_labs', '') or "", height=100)
                with c2:
                    ilk_noro = st.text_area("İlk Nörogörüntülemeler", value=current_patient.get('initial_neuroimaging', '') or "", height=100)
                    ekg = st.text_area("EKG", value=current_patient.get('ekg', '') or "", height=100)
                
                if st.form_submit_button("💾 İlk Başvuru Bilgilerini Kaydet / Güncelle"):
                    q = """UPDATE patients SET chief_complaint=?, anamnesis=?, history_og=?, initial_nm=?, initial_labs=?, initial_neuroimaging=?, ekg=? WHERE id=?"""
                    execute_query(q, [sikayet, hikaye, ozgecmis, ilk_nm, ilk_lab, ilk_noro, ekg, int(current_patient['id'])])
                    st.success("✅ Başvuru anamnezi başarıyla güncellendi.")
                    st.rerun()

        # TAB 2: GÜNLÜK GÖZLEM & LAB GİRİŞİ
        with tabs[1]:
            st.subheader("📝 Günlük Gözlem, Bakım ve Tedavi Formu")
            with st.form("daily_form"):
                e_date = st.date_input("Değerlendirme Tarihi", date.today())
                nm_today = st.text_area("Güncel Nörolojik Muayene (NM)", height=80)
                
                st.markdown("##### 🎛️ Sistem Sorgulaması")
                c1, c2, c3 = st.columns(3)
                with c1:
                    mayi = st.text_input("Mayi")
                    entubasyon = st.text_input("Entübasyon / Solunum")
                    sedasyon = st.text_input("Sedasyon")
                    inotrop = st.text_input("İnotrop")
                with c2:
                    anti_odem = st.text_input("Anti-Ödem")
                    antinobet = st.text_input("Antinöbet")
                    antitrombotik = st.text_input("Antitrombotik")
                    antibiyotik = st.text_input("Antibiyotikler")
                with c3:
                    beslenme = st.text_input("Beslenme")
                    kan_gazi = st.text_input("Kan Gazı")
                    yara_durumu = st.text_input("Yara Durumu")
                    diger_goruntuleme = st.text_input("Diğer Görüntülemeler")
                
                # Uzun metin girişleri için orta-büyük genişlikte çift kolon
                c_noro, c_kons = st.columns(2)
                with c_noro:
                    norogoruntuleme = st.text_area("Nörogörüntülemeler", height=120)
                with c_kons:
                    konsultasyonlar = st.text_area("Konsültasyonlar", height=120)
                
                note = st.text_area("Ekstra Gözlem / Sisteme Düşülecek Not", height=80)
                
                if st.form_submit_button("🩺 Bugünü Kaydet (Veritabanına İşle)"):
                    query = """INSERT INTO daily_evals 
                               (patient_id, eval_date, nm_today, intubation_status, antibiotics, daily_note, 
                                mayi, sedasyon, inotrop, anti_odem, antinobet, antitrombotik, beslenme, kan_gazi, 
                                yara_durumu, norogoruntuleme, diger_goruntuleme, konsultasyonlar) 
                               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"""
                    params = [int(current_patient['id']), str(e_date), nm_today, entubasyon, antibiyotik, note,
                              mayi, sedasyon, inotrop, anti_odem, antinobet, antitrombotik, beslenme, kan_gazi, 
                              yara_durumu, norogoruntuleme, diger_goruntuleme, konsultasyonlar]
                    execute_query(query, params)
                    st.success("✅ Gözlem Kaydı Başarıyla Alındı.")
                    st.rerun()

            # LAB RAPOR YÜKLEME
            st.markdown("---")
            st.subheader("🔬 Lab Raporu Yükleme")
            lab_image = st.file_uploader("Lab sonucu yükleyin (YZ otomatik okuyup bugünkü nota ekler)", type=["png", "jpg", "jpeg"])
            if lab_image:
                if st.button("YZ ile Oku ve Günlük Nota Ekle"):
                    latest_eval = fetch_data("SELECT id, daily_note FROM daily_evals WHERE patient_id=? ORDER BY eval_date DESC LIMIT 1", [int(current_patient['id'])])
                    if not latest_eval.empty:
                        with st.spinner("Rapor analiz ediliyor..."):
                            img = Image.open(lab_image)
                            model = genai.GenerativeModel('gemini-1.5-flash')
                            response = model.generate_content(["Bu laboratuvar raporunu analiz et, anormallikleri ve klinik önemini kısaca çıkar.", img])
                            
                            eval_id = latest_eval.iloc[0]['id']
                            old_note = latest_eval.iloc[0]['daily_note'] or ""
                            new_note = old_note + f"\n\n[YZ Lab Analizi]: {response.text}"
                            execute_query("UPDATE daily_evals SET daily_note=? WHERE id=?", [new_note, int(eval_id)])
                            st.success("✅ Rapor okundu ve bugünkü ekstra gözlem notuna başarıyla eklendi!")
                    else:
                        st.warning("Raporu ekleyebilmek için lütfen önce yukarıdan bugünün gözlem formunu kaydedin.")

            # HASTA YAKINI BİLGİLENDİRME
            st.markdown("---")
            st.subheader("👥 Hasta Yakını Bilgilendirme")
            latest_eval_hy = fetch_data("SELECT id, hasta_yakini FROM daily_evals WHERE patient_id=? ORDER BY eval_date DESC LIMIT 1", [int(current_patient['id'])])
            
            if not latest_eval_hy.empty:
                eval_id = latest_eval_hy.iloc[0]['id']
                current_hy = latest_eval_hy.iloc[0]['hasta_yakini']
                with st.form("hy_form"):
                    hy_text = st.text_area("Hasta Yakını Bilgilendirme Özeti", value=current_hy if current_hy else "", height=100)
                    if st.form_submit_button("Bilgilendirmeyi Bugüne Kaydet"):
                        execute_query("UPDATE daily_evals SET hasta_yakini=? WHERE id=?", [hy_text, int(eval_id)])
                        st.success("✅ Hasta yakını bilgilendirmesi bugünkü kayda eklendi!")
                        st.rerun()
            else:
                st.info("Bilgilendirme notu girmek için önce bugünün gözlem formunu kaydedin.")

        # TAB 3: YZ ASİSTANI (THREAD/SOHBET HALİ)
        with tabs[2]:
            st.subheader("🧠 Klinik YZ Asistanı (Birebir Vaka Tartışması)")
            
            messages = fetch_data("SELECT role, content FROM ai_chats WHERE patient_id=? ORDER BY timestamp ASC", [int(current_patient['id'])])
            
            for _, msg in messages.iterrows():
                with st.chat_message(msg['role']):
                    st.markdown(msg['content'])
                    
            if user_prompt := st.chat_input("Vaka ile ilgili ne danışmak istersiniz?"):
                with st.chat_message("user"):
                    st.markdown(user_prompt)
                execute_query("INSERT INTO ai_chats (patient_id, role, content) VALUES (?, ?, ?)", [int(current_patient['id']), "user", user_prompt])
                
                history_text = "\n".join([f"{r['role']}: {r['content']}" for _, r in messages.iterrows()])
                system_prompt = f"""
                Sen bir Yoğun Bakım Nöroloji doktorunun kıdemli asistanısın. Vakayı seninle tartışıyor.
                Hasta: {current_patient['age']} yaş, {current_patient.get('gender', '')}.
                Şikayet: {current_patient.get('chief_complaint', '-')}
                Hikaye: {current_patient.get('anamnesis', '-')}
                İlk Bulgular: {current_patient.get('initial_nm', '-')}
                Ön Tanı: {patient_diag}.
                
                Geçmiş Konuşmalar:
                {history_text}
                
                Doktorun Sorusu: {user_prompt}
                
                Lütfen klinik pratik ve literatüre dayanarak bilimsel, yönlendirici bir yanıt ver.
                """
                
                with st.spinner("YZ Asistanı yanıtlıyor..."):
                    try:
                        model = genai.GenerativeModel('gemini-1.5-flash')
                        response = model.generate_content(system_prompt)
                        with st.chat_message("assistant"):
                            st.markdown(response.text)
                        execute_query("INSERT INTO ai_chats (patient_id, role, content) VALUES (?, ?, ?)", [int(current_patient['id']), "assistant", response.text])
                        st.rerun()
                    except Exception as e:
                        st.error(f"Bağlantı hatası: {e}")

        # TAB 4: GELECEK PLANLARI
        with tabs[3]:
            st.subheader("📅 Planlanan İşlemler ve Tetkikler")
            with st.form("plan_form"):
                c1, c2 = st.columns([1, 3])
                p_date = c1.date_input("Planlanan Tarih", date.today() + timedelta(days=1))
                p_desc = c2.text_input("İşlem / Konsültasyon / Aksiyon Detayı")
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

        # TAB 5: DOSYA & ARŞİV
        with tabs[4]:
            st.subheader("🗂️ Dosya Dökümü ve Geçmiş Bilgiler")
            
            # 1. BÖLÜM: TEMEL HASTA BİLGİLERİ (ESKİ BİLGİLERE ULAŞIM)
            with st.expander("📌 İLK BAŞVURU VE ANAMNEZ (Hastanın Geçmişi)", expanded=True):
                st.markdown(f"**Geliş Şikayeti:** {current_patient.get('chief_complaint', '-')}")
                st.markdown(f"**Hikaye / Ne Olmuş?:** {current_patient.get('anamnesis', '-')}")
                st.markdown(f"**Özgeçmiş:** {current_patient.get('history_og', '-')}")
                st.markdown(f"**İlk Nörolojik Muayene:** {current_patient.get('initial_nm', '-')}")
                st.markdown(f"**İlk Nörogörüntüleme:** {current_patient.get('initial_neuroimaging', '-')}")
            
            st.markdown("### 🗓️ Geçmiş Günlük Gözlemler")
            all_evals = fetch_data("SELECT * FROM daily_evals WHERE patient_id=? ORDER BY eval_date DESC", [int(current_patient['id'])])
            
            if not all_evals.empty:
                for idx, row in all_evals.iterrows():
                    with st.expander(f"▶️ {row['eval_date']} Tarihli Gözlem Dosyası"):
                        c_sol, c_sag = st.columns(2)
                        with c_sol:
                            st.markdown(f"**Nörolojik Muayene:** {row['nm_today']}")
                            st.markdown(f"**Solunum:** {row['intubation_status']} | **Sedasyon:** {row['sedasyon']}")
                            st.markdown(f"**Beslenme:** {row['beslenme']} | **Mayi:** {row['mayi']}")
                        with c_sag:
                            st.markdown(f"**Nörogörüntüleme:** {row['norogoruntuleme']}")
                            st.markdown(f"**Konsültasyonlar:** {row['konsultasyonlar']}")
                            st.markdown(f"**Antibiyotik:** {row['antibiotics']}")
                        
                        st.markdown(f"**Genel Not & Lab Analizleri:** {row['daily_note']}")
                        st.markdown(f"**Hasta Yakını Bilgilendirme:** {row['hasta_yakini']}")
            else:
                st.info("Bu hastaya ait henüz geçmiş bir günlük gözlem kaydı bulunmuyor.")
            
            # HASTA ÇIKIŞI İŞLEMLERİ
            st.markdown("---")
            st.subheader("🚪 Hasta Çıkışı / Arşivleme")
            col1, col2 = st.columns(2)
            with col1:
                cikis_turu = st.selectbox("Çıkış Türü", ["Taburcu", "Ex", "Başka Servise Devir", "Palyatif"])
            with col2:
                cikis_tarihi = st.date_input("Çıkış Tarihi")

            if st.button("Hastayı Arşivle ve Yatağı Boşalt", type="primary", use_container_width=True):
                try:
                    execute_query(f"UPDATE patients SET status = '{cikis_turu}', discharge_date = '{cikis_tarihi}', bed_no = NULL WHERE id = {current_patient['id']}")
                    st.success(f"Hasta başarıyla {cikis_turu} edildi ve arşive taşındı.")
                    st.rerun() 
                except Exception as e:
                    st.error(f"Bir hata oluştu: {e}")

    # --- BOŞ YATAK / YENİ HASTA GİRİŞİ ---
    else:
        st.sidebar.info("Bu yatak şu an BOŞ.")
        with st.sidebar.expander("➕ Yeni Hasta Kabulü"):
            with st.form("new_patient_form"):
                p_name = st.text_input("Ad Soyad")
                p_age = st.number_input("Yaş", 18, 120, 60)
                p_gender = st.selectbox("Cinsiyet", ["Kadın", "Erkek"])
                
                c1, c2 = st.columns(2)
                p_er_date = c1.date_input("Acil/Yatış Tarihi", date.today())
                p_icu_date = c2.date_input("YBÜ Geliş Tarihi", date.today())
                
                p_diag = st.text_area("Ön Tanı(lar)")
                st.caption("Detaylı şikayet ve anamnezi hastayı yatağa aldıktan sonra 1. Sekmeden girebilirsiniz.")
                
                if st.form_submit_button("Hastayı Yatağa Al") and p_name:
                    execute_query("INSERT INTO patients (bed_no, name, age, gender, er_admission_date, icu_admission_date, pre_diagnosis) VALUES (?, ?, ?, ?, ?, ?, ?)", 
                                  [selected_bed, p_name, int(p_age), p_gender, str(p_er_date), str(p_icu_date), p_diag])
                    st.rerun()

# --- TABURCU/EX ARŞİVİ ---
elif view_mode == "Taburcu/Ex Arşivi":
    st.header("🗄️ Geçmiş Hasta Arşivi")
    arsiv_hastalar = fetch_data("""
        SELECT id, name as İsim, age as Yaş, pre_diagnosis as 'Ön Tanı', 
               status as Durum, er_admission_date as 'Acil Yatış', discharge_date as 'Çıkış Tarihi' 
        FROM patients WHERE status != 'Aktif' ORDER BY discharge_date DESC
    """)
    if not arsiv_hastalar.empty:
        st.dataframe(arsiv_hastalar.drop(columns=["id"]), hide_index=True, use_container_width=True)
    else:
        st.info("Arşivde henüz hasta bulunmamaktadır.")
