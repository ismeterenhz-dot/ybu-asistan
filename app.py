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

    # Eski veritabanlarını bozmamak için dinamik sütun ekleme
    new_patient_cols = {"er_admission_date": "DATE", "icu_admission_date": "DATE", "pre_diagnosis": "TEXT", "ekg": "TEXT"}
    new_eval_cols = {"mayi": "TEXT", "sedasyon": "TEXT", "inotrop": "TEXT", "anti_odem": "TEXT", "antinobet": "TEXT", "antitrombotik": "TEXT", "beslenme": "TEXT", "kan_gazi": "TEXT", "yara_durumu": "TEXT", "norogoruntuleme": "TEXT", "diger_goruntuleme": "TEXT", "konsultasyonlar": "TEXT", "hasta_yakini": "TEXT"}
    
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
        st.sidebar.markdown(f"**Özgeçmiş:** {current_patient.get('history_og', '-')}")
        st.sidebar.markdown(f"**Kullandığı İlaçlar:** {current_patient.get('meds_ki', '-')}")
        st.sidebar.markdown(f"**EKG:** {current_patient.get('ekg', '-')}")
        st.sidebar.markdown("---")

        # --- SEKMELER ---
        tabs = st.tabs(["🩺 1. Gözlem & Lab Girişi", "🧠 2. YZ Asistanı (Vaka Tartışması)", "📅 3. Gelecek Planları", "🗂️ 4. Dosya & Arşiv"])

        # TAB 1: GÖZLEM & LAB GİRİŞİ
        with tabs[0]:
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
                    norogoruntuleme = st.text_input("Nörogörüntülemeler")
                    diger_goruntuleme = st.text_input("Diğer Görüntülemeler")
                
                konsultasyonlar = st.text_area("Konsültasyonlar", height=80)
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

            # LAB / GÖRÜNTÜLEME RAPOR YÜKLEME (1. SEKMEYE TAŞINDI)
            st.markdown("---")
            st.subheader("🔬 Lab & Görüntüleme Raporu Yükleme")
            lab_image = st.file_uploader("Lab sonucu veya görüntüleme raporu yükleyin (YZ otomatik okuyup bugünkü nota ekler)", type=["png", "jpg", "jpeg"])
            if lab_image:
                if st.button("YZ ile Oku ve Günlük Nota Ekle"):
                    latest_eval = fetch_data("SELECT id, daily_note FROM daily_evals WHERE patient_id=? ORDER BY eval_date DESC LIMIT 1", [int(current_patient['id'])])
                    if not latest_eval.empty:
                        with st.spinner("Rapor analiz ediliyor..."):
                            img = Image.open(lab_image)
                            model = genai.GenerativeModel('gemini-1.5-flash')
                            response = model.generate_content(["Bu tıbbi raporu/sonucu analiz et, anormallikleri ve klinik önemini kısaca çıkar.", img])
                            
                            eval_id = latest_eval.iloc[0]['id']
                            old_note = latest_eval.iloc[0]['daily_note'] or ""
                            new_note = old_note + f"\n\n[YZ Rapor Analizi]: {response.text}"
                            execute_query("UPDATE daily_evals SET daily_note=? WHERE id=?", [new_note, int(eval_id)])
                            st.success("✅ Rapor okundu ve bugünkü ekstra gözlem notuna başarıyla eklendi!")
                    else:
                        st.warning("Raporu ekleyebilmek için lütfen önce yukarıdan bugünün gözlem formunu kaydedin.")

            # YZ OTOMATİK EPİKRİZ ALANI
            st.markdown("---")
            st.subheader("🤖 YZ Otomatik Epikriz / Günlük Özet Çıkarıcı")
            st.info("Formu kaydedip varsa laboratuvarı ekledikten sonra, vizit veya dosya için günlük profesyonel özetinizi buradan alabilirsiniz.")
            
            if st.button("📝 Son Gözleme Göre Epikriz Notu Yaz", type="primary"):
                latest_eval = fetch_data("SELECT * FROM daily_evals WHERE patient_id=? ORDER BY eval_date DESC LIMIT 1", [int(current_patient['id'])])
                if not latest_eval.empty:
                    with st.spinner("YZ, hastanın tıbbi verilerini derliyor..."):
                        try:
                            e_data = latest_eval.iloc[0]
                            model = genai.GenerativeModel('gemini-1.5-flash')
                            epicrisis_prompt = f"""
                            Sen bir yoğun bakım nöroloji uzmanısın. Aşağıdaki güncel klinik verileri kullanarak, resmi dosyaya konulabilecek veya vizitte okunabilecek derli toplu, profesyonel bir GÜNLÜK EPİKRİZ (Progress Note) hazırla.
                            
                            KİMLİK/TANI: {current_patient['age']} yaş, {current_patient.get('gender', '')}.
                            Ön Tanı: {patient_diag}
                            Özgeçmiş: {current_patient.get('history_og', '-')}
                            Yatış Tarihleri: Acil: {current_patient.get('er_admission_date', '-')} / YBÜ: {current_patient.get('icu_admission_date', '-')}
                            EKG: {current_patient.get('ekg', '-')}
                            
                            BUGÜNKÜ GÖZLEM ({e_data['eval_date']}):
                            NM: {e_data.get('nm_today', '-')}
                            Solunum: {e_data.get('intubation_status', '-')} | Sedasyon: {e_data.get('sedasyon', '-')}
                            İnotrop: {e_data.get('inotrop', '-')} | Anti-Ödem: {e_data.get('anti_odem', '-')}
                            Antinöbet: {e_data.get('antinobet', '-')} | Antitrombotik: {e_data.get('antitrombotik', '-')}
                            Antibiyotik: {e_data.get('antibiotics', '-')} | Mayi: {e_data.get('mayi', '-')}
                            Beslenme: {e_data.get('beslenme', '-')} | Kan Gazı: {e_data.get('kan_gazi', '-')}
                            Yara: {e_data.get('yara_durumu', '-')}
                            Nörogörüntüleme: {e_data.get('norogoruntuleme', '-')}
                            Konsültasyon: {e_data.get('konsultasyonlar', '-')}
                            Ek Not & YZ Lab Analizleri: {e_data.get('daily_note', '-')}
                            """
                            response = model.generate_content(epicrisis_prompt)
                            st.success("✅ Günlük Epikriz / Özet Hazır")
                            st.markdown(response.text)
                        except Exception as e:
                            st.error(f"Hata: {e}")
                else:
                    st.warning("Bu hastaya ait henüz bir gözlem kaydı bulunmuyor.")

            # HASTA YAKINI BİLGİLENDİRME (EPİKRİZİN ALTINA TAŞINDI)
            st.markdown("---")
            st.subheader("👥 Hasta Yakını Bilgilendirme")
            latest_eval_hy = fetch_data("SELECT id, hasta_yakini FROM daily_evals WHERE patient_id=? ORDER BY eval_date DESC LIMIT 1", [int(current_patient['id'])])
            
            if not latest_eval_hy.empty:
                eval_id = latest_eval_hy.iloc[0]['id']
                current_hy = latest_eval_hy.iloc[0]['hasta_yakini']
                with st.form("hy_form"):
                    hy_text = st.text_area("Hasta Yakını Bilgilendirme Özeti (Görüşme sonrası doldurabilirsiniz)", value=current_hy if current_hy else "", height=100)
                    if st.form_submit_button("Bilgilendirmeyi Bugüne Kaydet"):
                        execute_query("UPDATE daily_evals SET hasta_yakini=? WHERE id=?", [hy_text, int(eval_id)])
                        st.success("✅ Hasta yakını bilgilendirmesi bugünkü kayda eklendi!")
                        st.rerun()
            else:
                st.info("Bilgilendirme notu girmek için önce bugünün gözlem formunu kaydedin.")

        # TAB 2: YZ ASİSTANI (THREAD/SOHBET HALİ)
        with tabs[1]:
            st.subheader("🧠 Klinik YZ Asistanı (Birebir Vaka Tartışması)")
            st.markdown("Burada hastanın durumunu, tedavi alternatiflerini ve komplikasyonları YZ meslektaşınızla tartışabilirsiniz. Tüm konuşmalar hasta dosyasına kaydedilir.")
            
            # Konuşma geçmişini çek
            messages = fetch_data("SELECT role, content FROM ai_chats WHERE patient_id=? ORDER BY timestamp ASC", [int(current_patient['id'])])
            
            # Geçmiş mesajları ekrana bas
            for _, msg in messages.iterrows():
                with st.chat_message(msg['role']):
                    st.markdown(msg['content'])
                    
            # Yeni mesaj girdisi
            if user_prompt := st.chat_input("Vaka ile ilgili ne danışmak istersiniz?"):
                # Kullanıcı mesajını ekrana bas ve kaydet
                with st.chat_message("user"):
                    st.markdown(user_prompt)
                execute_query("INSERT INTO ai_chats (patient_id, role, content) VALUES (?, ?, ?)", [int(current_patient['id']), "user", user_prompt])
                
                # YZ Sistem Context'ini oluştur
                history_text = "\n".join([f"{r['role']}: {r['content']}" for _, r in messages.iterrows()])
                system_prompt = f"""
                Sen bir Yoğun Bakım Nöroloji doktorunun kıdemli asistanısın. Vakayı seninle birebir tartışıyor.
                Hasta: {current_patient['age']} yaş, {current_patient.get('gender', '')}. Ön Tanı: {patient_diag}.
                Geçmiş Konuşmalar:
                {history_text}
                
                Doktorun Sorusu/Mesajı: {user_prompt}
                
                Lütfen klinik pratik, literatür veya YBÜ tecrübelerine dayanarak doktora bilimsel, tartışmaya açık ve yönlendirici bir yanıt ver.
                """
                
                with st.spinner("YZ Asistanı yanıtlıyor..."):
                    try:
                        model = genai.GenerativeModel('gemini-1.5-flash')
                        response = model.generate_content(system_prompt)
                        # Asistan mesajını ekrana bas ve kaydet
                        with st.chat_message("assistant"):
                            st.markdown(response.text)
                        execute_query("INSERT INTO ai_chats (patient_id, role, content) VALUES (?, ?, ?)", [int(current_patient['id']), "assistant", response.text])
                        st.rerun()
                    except Exception as e:
                        st.error(f"Bağlantı hatası: {e}")

        # TAB 3: GELECEK PLANLARI
        with tabs[2]:
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

        # TAB 4: DOSYA & ARŞİV (HASTA ÇIKIŞI BURAYA ALINDI)
        with tabs[3]:
            st.subheader("🗂️ Dosya Dökümü ve Geçmiş Gözlemler")
            all_evals = fetch_data("SELECT * FROM daily_evals WHERE patient_id=? ORDER BY eval_date DESC", [int(current_patient['id'])])
            
            for idx, row in all_evals.iterrows():
                with st.expander(f"🗓️ {row['eval_date']} Gözlemi"):
                    st.markdown(f"**NM:** {row['nm_today']}\n\n**Solunum:** {row['intubation_status']} | **Antibiyotik:** {row['antibiotics']}\n\n**Genel Not & Rapor Analizleri:** {row['daily_note']}\n\n**Hasta Yakını Bilgilendirme:** {row['hasta_yakini']}")
            
            # HASTA ÇIKIŞI İŞLEMLERİ (Sadece Bu Sekmenin Altında)
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
                
                p_diag = st.text_area("Ön Tanı(lar) (Alt alta girebilirsiniz)")
                p_og = st.text_area("Özgeçmiş (ÖG)")
                p_ki = st.text_area("Kullandığı İlaçlar (Kİ)")
                p_ekg = st.text_area("EKG Bilgisi")
                
                if st.form_submit_button("Hastayı Yatağa Al") and p_name:
                    execute_query("INSERT INTO patients (bed_no, name, age, gender, er_admission_date, icu_admission_date, pre_diagnosis, history_og, meds_ki, ekg) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                                  [selected_bed, p_name, int(p_age), p_gender, str(p_er_date), str(p_icu_date), p_diag, p_og, p_ki, p_ekg])
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
