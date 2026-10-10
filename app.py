import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import date, datetime, timedelta
import google.generativeai as genai
from PIL import Image
import libsql_client
import json
import pypdf

# --- YAPAY ZEKA MODEL AYARI ---
MODEL_NAME = "gemini-3.8-flash"

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

def safe_str(val):
    if val is None or pd.isna(val):
        return ""
    return str(val)

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
        execute_query(q, [])

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
        try: execute_query(f"ALTER TABLE patients ADD COLUMN {col} {d_type}", [])
        except: pass
        
    for col, d_type in new_eval_cols.items():
        try: execute_query(f"ALTER TABLE daily_evals ADD COLUMN {col} {d_type}", [])
        except: pass

init_db()

# --- ARAYÜZ KURULUMU ---
st.set_page_config(page_title="YBÜ Dijital Asistan", layout="wide", page_icon="🏥")
st.markdown("<h1 style='text-align: center; color: #117A65;'>🏥 Nöroloji YBÜ Dijital Dosya & YZ Asistanı</h1>", unsafe_allow_html=True)

st.sidebar.header("📌 Servis Durumu")
view_mode = st.sidebar.radio("Görünüm:", ["Aktif Yatan Hastalar", "Taburcu/Ex Arşivi"])

if view_mode == "Aktif Yatan Hastalar":
    active_patients = fetch_data("SELECT * FROM patients WHERE status = 'Aktif' ORDER BY bed_no", [])
    bed_list = [f"Yatak {i}" for i in range(1, 10)]
    selected_bed = st.sidebar.selectbox("Yatak Seçiniz:", bed_list)
    
    current_patient = None
    if not active_patients.empty:
        match = active_patients[active_patients['bed_no'] == selected_bed]
        if not match.empty: current_patient = match.iloc[0]

    if current_patient is not None:
        patient_diag = current_patient.get('pre_diagnosis') if current_patient.get('pre_diagnosis') else current_patient.get('diagnosis', '')
        
        # --- SOL MENÜ HASTA KARTI ---
        st.sidebar.markdown("---")
        st.sidebar.markdown(f"### 🛏️ {current_patient['bed_no']}")
        st.sidebar.markdown(f"**{safe_str(current_patient['name'])}** ({safe_str(current_patient['age'])} Y, {safe_str(current_patient.get('gender', ''))})")
        st.sidebar.markdown(f"**Acil/Yatış Tarihi:** {safe_str(current_patient.get('er_admission_date', '-'))}")
        st.sidebar.markdown(f"**YBÜ Geliş Tarihi:** {safe_str(current_patient.get('icu_admission_date', '-'))}")
        st.sidebar.markdown(f"**Ön Tanı:** {safe_str(patient_diag)}")
        st.sidebar.markdown(f"**EKG:** {safe_str(current_patient.get('ekg', '-'))}")
        st.sidebar.markdown(f"**Kullandığı İlaçlar:** {safe_str(current_patient.get('meds_ki', '-'))}")
        st.sidebar.markdown("---")

        # Sol menüden hasta bilgilerini düzenleme paneli
        with st.sidebar.expander("✏️ Hasta Bilgilerini Düzenle"):
            with st.form("edit_patient_sidebar_form"):
                ed_name = st.text_input("Ad Soyad", value=safe_str(current_patient.get('name')))
                ed_age = st.number_input("Yaş", 1, 120, int(current_patient['age']) if pd.notna(current_patient.get('age')) else 60)
                ed_gender = st.selectbox("Cinsiyet", ["Kadın", "Erkek"], index=0 if current_patient.get('gender') == "Kadın" else 1)
                
                try:
                    def_er_date = datetime.strptime(str(current_patient.get('er_admission_date')), "%Y-%m-%d").date()
                except:
                    def_er_date = date.today()
                
                try:
                    def_icu_date = datetime.strptime(str(current_patient.get('icu_admission_date')), "%Y-%m-%d").date()
                except:
                    def_icu_date = date.today()

                ed_er_date = st.date_input("Acil/Yatış Tarihi", def_er_date)
                ed_icu_date = st.date_input("YBÜ Geliş Tarihi", def_icu_date)
                ed_diag = st.text_area("Ön Tanı", value=safe_str(patient_diag))
                ed_ekg = st.text_area("EKG", value=safe_str(current_patient.get('ekg')))
                ed_meds = st.text_area("Kullandığı İlaçlar", value=safe_str(current_patient.get('meds_ki')))
                
                if st.form_submit_button("💾 Bilgileri Güncelle"):
                    execute_query(
                        "UPDATE patients SET name=?, age=?, gender=?, er_admission_date=?, icu_admission_date=?, pre_diagnosis=?, ekg=?, meds_ki=? WHERE id=?",
                        [ed_name, int(ed_age), ed_gender, str(ed_er_date), str(ed_icu_date), ed_diag, ed_ekg, ed_meds, int(current_patient['id'])]
                    )
                    st.success("✅ Hasta bilgileri güncellendi!")
                    st.rerun()

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
            st.info("Hastanın acil veya servise ilk gelişindeki hikayesini elle girebilir ya da aşağıdan PDF epikriz yükleyerek YZ ile otomatik doldurabilirsiniz.")
            
            # --- PDF İLE OTOMATİK DOLDURMA ---
            st.markdown("##### 📄 PDF Epikriz Yükle & YZ Otomatik Doldur")
            uploaded_pdf = st.file_uploader("Hasta epikriz PDF dosyasını seçin", type=["pdf"], key="epicrisis_pdf_upload")
            if uploaded_pdf is not None:
                if st.button("🤖 PDF'i Analiz Et ve İlk Başvuru Bilgilerini Otomatik Doldur"):
                    with st.spinner("PDF okunuyor ve YZ tarafından titizlikle analiz ediliyor..."):
                        try:
                            reader = pypdf.PdfReader(uploaded_pdf)
                            pdf_text = ""
                            for page in reader.pages:
                                pdf_text += page.extract_text() + "\n"
                            
                            model = genai.GenerativeModel(MODEL_NAME)
                            json_prompt = f"""
                            Sen kıdemli bir nöroloji uzmanısın. Aşağıdaki epikriz metnini dikkatlice oku, verileri çapraz kontrol et ve şu anahtarlara sahip geçerli bir JSON objesi döndür (başka hiçbir açıklama yazma, sadece saf JSON):
                            {{
                              "chief_complaint": "Acile geliş şikayeti",
                              "anamnesis": "Anamnez ve öykü detayları",
                              "history_og": "Özgeçmiş bilgileri",
                              "meds_ki": "Kullandığı ilaçlar",
                              "initial_nm": "İlk nörolojik muayene bulguları",
                              "initial_labs": "İlk laboratuvar bulguları",
                              "initial_neuroimaging": "İlk nörogörüntüleme bulguları",
                              "ekg": "EKG bulguları",
                              "pre_diagnosis": "Ön tanılar"
                            }}

                            PDF Metni:
                            {pdf_text}
                            """
                            response = model.generate_content(json_prompt)
                            cleaned_json = response.text.strip().replace("```json", "").replace("```", "").strip()
                            data_dict = json.loads(cleaned_json)
                            
                            execute_query(
                                """UPDATE patients SET chief_complaint=?, anamnesis=?, history_og=?, meds_ki=?, 
                                   initial_nm=?, initial_labs=?, initial_neuroimaging=?, ekg=?, pre_diagnosis=? WHERE id=?""",
                                [
                                    data_dict.get("chief_complaint", ""),
                                    data_dict.get("anamnesis", ""),
                                    data_dict.get("history_og", ""),
                                    data_dict.get("meds_ki", ""),
                                    data_dict.get("initial_nm", ""),
                                    data_dict.get("initial_labs", ""),
                                    data_dict.get("initial_neuroimaging", ""),
                                    data_dict.get("ekg", ""),
                                    data_dict.get("pre_diagnosis", ""),
                                    int(current_patient['id'])
                                ]
                            )
                            st.success("✅ PDF başarıyla analiz edildi ve ilk başvuru bilgileri otomatik olarak dolduruldu!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"PDF işlenirken veya YZ yanıtı çözümlenirken hata oluştu: {e}")

            st.markdown("---")
            with st.form("anamnez_form"):
                sikayet = st.text_input("Acile Geliş Şikayeti", value=safe_str(current_patient.get('chief_complaint')))
                hikaye = st.text_area("Anamnez / Neler Olmuş? (Hikaye)", value=safe_str(current_patient.get('anamnesis')), height=100)
                
                c_og, c_ki = st.columns(2)
                with c_og:
                    ozgecmis = st.text_area("Özgeçmiş (ÖG)", value=safe_str(current_patient.get('history_og')), height=80)
                with c_ki:
                    ilaclar = st.text_area("Kullandığı İlaçlar (Kİ)", value=safe_str(current_patient.get('meds_ki')), height=80)
                
                st.markdown("##### İlk Klinik Durum (Yatış Anı)")
                c1, c2 = st.columns(2)
                with c1:
                    ilk_nm = st.text_area("İlk Nörolojik Muayene", value=safe_str(current_patient.get('initial_nm')), height=100)
                    ilk_lab = st.text_area("İlk Laboratuvar Bulguları", value=safe_str(current_patient.get('initial_labs')), height=100)
                with c2:
                    ilk_noro = st.text_area("İlk Nörogörüntülemeler", value=safe_str(current_patient.get('initial_neuroimaging')), height=100)
                    ekg = st.text_area("EKG", value=safe_str(current_patient.get('ekg')), height=100)
                
                if st.form_submit_button("💾 İlk Başvuru Bilgilerini Kaydet / Güncelle"):
                    q = """UPDATE patients SET chief_complaint=?, anamnesis=?, history_og=?, meds_ki=?, initial_nm=?, initial_labs=?, initial_neuroimaging=?, ekg=? WHERE id=?"""
                    execute_query(q, [sikayet, hikaye, ozgecmis, ilaclar, ilk_nm, ilk_lab, ilk_noro, ekg, int(current_patient['id'])])
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
                
                st.markdown("##### 🧠 Görüntüleme & Konsültasyon Notları")
                norogoruntuleme = st.text_area("Nörogörüntülemeler", height=120)
                konsultasyonlar = st.text_area("Konsültasyonlar", height=250)
                
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

            # ÇOKLU LAB RAPOR YÜKLEME
            st.markdown("---")
            st.subheader("🔬 Lab Raporu Yükleme")
            lab_images = st.file_uploader("Lab sonuçlarını yükleyin (Aynı anda birden fazla fotoğraf seçebilirsiniz)", type=["png", "jpg", "jpeg"], accept_multiple_files=True)
            if lab_images:
                if st.button("YZ ile Oku ve Günlük Nota Ekle"):
                    latest_eval = fetch_data("SELECT id, daily_note FROM daily_evals WHERE patient_id=? ORDER BY eval_date DESC LIMIT 1", [int(current_patient['id'])])
                    if not latest_eval.empty:
                        with st.spinner(f"{len(lab_images)} adet rapor sırayla analiz ediliyor, lütfen bekleyin..."):
                            model = genai.GenerativeModel(MODEL_NAME)
                            all_responses = []
                            
                            for i, lab_image in enumerate(lab_images):
                                img = Image.open(lab_image)
                                response = model.generate_content(["Bu laboratuvar raporunu analiz et, anormallikleri ve klinik önemini kısaca çıkar.", img])
                                all_responses.append(f"--- Eklenen Rapor {i+1} ---\n{response.text}")
                            
                            combined_analysis = "\n\n".join(all_responses)
                            eval_id = latest_eval.iloc[0]['id']
                            old_note = safe_str(latest_eval.iloc[0]['daily_note'])
                            new_note = old_note + f"\n\n[YZ Çoklu Lab Analizi]:\n{combined_analysis}"
                            
                            execute_query("UPDATE daily_evals SET daily_note=? WHERE id=?", [new_note, int(eval_id)])
                            st.success(f"✅ Toplam {len(lab_images)} rapor okundu ve bugünkü ekstra gözlem notuna başarıyla eklendi!")
                    else:
                        st.warning("Raporu ekleyebilmek için lütfen önce yukarıdan bugünün gözlem formunu kaydedin.")

            # YZ OTOMATİK EPİKRİZ ALANI
            st.markdown("---")
            st.subheader("🤖 YZ Otomatik Epikriz / Günlük Özet Çıkarıcı")
            st.info("Formu kaydedip varsa laboratuvarı ekledikten sonra, vizit veya dosya için günlük profesyonel özetinizi buradan alabilirsiniz.")
            
            if st.button("📝 Son Gözleme Göre Epikriz Notu Yaz"):
                latest_eval = fetch_data("SELECT * FROM daily_evals WHERE patient_id=? ORDER BY eval_date DESC LIMIT 1", [int(current_patient['id'])])
                if not latest_eval.empty:
                    with st.spinner("YZ, hastanın tıbbi verilerini derliyor..."):
                        try:
                            e_data = latest_eval.iloc[0]
                            model = genai.GenerativeModel(MODEL_NAME)
                            epicrisis_prompt = f"""
                            Sen bir yoğun bakım nöroloji uzmanısın. Aşağıdaki güncel klinik verileri kullanarak, resmi dosyaya konulabilecek veya vizitte okunabilecek derli toplu, profesyonel bir GÜNLÜK EPİKRİZ (Progress Note) hazırla.
                            
                            KİMLİK/TANI: {current_patient['age']} yaş, {safe_str(current_patient.get('gender', ''))}.
                            Ön Tanı: {patient_diag}
                            Özgeçmiş: {safe_str(current_patient.get('history_og', '-'))}
                            Kullandığı İlaçlar: {safe_str(current_patient.get('meds_ki', '-'))}
                            Yatış Tarihleri: Acil: {safe_str(current_patient.get('er_admission_date', '-'))} / YBÜ: {safe_str(current_patient.get('icu_admission_date', '-'))}
                            EKG: {safe_str(current_patient.get('ekg', '-'))}
                            
                            BUGÜNKÜ GÖZLEM ({e_data['eval_date']}):
                            NM: {safe_str(e_data.get('nm_today', '-'))}
                            Solunum: {safe_str(e_data.get('intubation_status', '-'))} | Sedasyon: {safe_str(e_data.get('sedasyon', '-'))}
                            İnotrop: {safe_str(e_data.get('inotrop', '-'))} | Anti-Ödem: {safe_str(e_data.get('anti_odem', '-'))}
                            Antinöbet: {safe_str(e_data.get('antinobet', '-'))} | Antitrombotik: {safe_str(e_data.get('antitrombotik', '-'))}
                            Antibiyotik: {safe_str(e_data.get('antibiotics', '-'))} | Mayi: {safe_str(e_data.get('mayi', '-'))}
                            Beslenme: {safe_str(e_data.get('beslenme', '-'))} | Kan Gazı: {safe_str(e_data.get('kan_gazi', '-'))}
                            Yara: {safe_str(e_data.get('yara_durumu', '-'))}
                            Nörogörüntüleme: {safe_str(e_data.get('norogoruntuleme', '-'))}
                            Diğer Görüntüleme: {safe_str(e_data.get('diger_goruntuleme', '-'))}
                            Konsültasyon: {safe_str(e_data.get('konsultasyonlar', '-'))}
                            Ek Not & YZ Lab Analizleri: {safe_str(e_data.get('daily_note', '-'))}
                            """
                            response = model.generate_content(epicrisis_prompt)
                            st.success("✅ Günlük Epikriz / Özet Hazır")
                            st.markdown(response.text)
                        except Exception as e:
                            st.error(f"Hata: {e}")
                else:
                    st.warning("Bu hastaya ait henüz bir gözlem kaydı bulunmuyor.")

            # HASTA YAKINI BİLGİLENDİRME
            st.markdown("---")
            st.subheader("👥 Hasta Yakını Bilgilendirme")
            latest_eval_hy = fetch_data("SELECT id, hasta_yakini FROM daily_evals WHERE patient_id=? ORDER BY eval_date DESC LIMIT 1", [int(current_patient['id'])])
            
            if not latest_eval_hy.empty:
                eval_id = latest_eval_hy.iloc[0]['id']
                current_hy = latest_eval_hy.iloc[0]['hasta_yakini']
                with st.form("hy_form"):
                    hy_text = st.text_area("Hasta Yakını Bilgilendirme Özeti", value=safe_str(current_hy), height=100)
                    if st.form_submit_button("💾 Bilgilendirmeyi Bugüne Kaydet"):
                        execute_query("UPDATE daily_evals SET hasta_yakini=? WHERE id=?", [hy_text, int(eval_id)], [])
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
                execute_query("INSERT INTO ai_chats (patient_id, role, content) VALUES (?, ?, ?)", [int(current_patient['id']), "user", user_prompt], [])
                
                history_text = "\n".join([f"{r['role']}: {r['content']}" for _, r in messages.iterrows()])
                system_prompt = f"""
                Sen bir Yoğun Bakım Nöroloji doktorunun kıdemli asistanısın. Vakayı seninle tartışıyor.
                Hasta: {current_patient['age']} yaş, {safe_str(current_patient.get('gender', ''))}.
                Şikayet: {safe_str(current_patient.get('chief_complaint', '-'))}
                Hikaye: {safe_str(current_patient.get('anamnesis', '-'))}
                İlk Bulgular: {safe_str(current_patient.get('initial_nm', '-'))}
                Ön Tanı: {patient_diag}.
                
                Geçmiş Konuşmalar:
                {history_text}
                
                Doktorun Sorusu: {user_prompt}
                
                Lütfen klinik pratik ve literatüre dayanarak bilimsel, yönlendirici bir yanıt ver.
                """
                
                with st.spinner("YZ Asistanı yanıtlıyor..."):
                    try:
                        model = genai.GenerativeModel(MODEL_NAME)
                        response = model.generate_content(system_prompt)
                        with st.chat_message("assistant"):
                            st.markdown(response.text)
                        execute_query("INSERT INTO ai_chats (patient_id, role, content) VALUES (?, ?, ?)", [int(current_patient['id']), "assistant", response.text], [])
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
                if st.form_submit_button("➕ Planı Ekle") and p_desc:
                    execute_query("INSERT INTO future_plans (patient_id, plan_date, description) VALUES (?, ?, ?)", [int(current_patient['id']), str(p_date), p_desc], [])
                    st.rerun()
                    
            plans = fetch_data("SELECT * FROM future_plans WHERE patient_id=? ORDER BY is_completed ASC, plan_date ASC", [int(current_patient['id'])], [])
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
                            execute_query("UPDATE future_plans SET is_completed=1 WHERE id=?", [int(row['id'])], [])
                            st.rerun()
                        
                        if delta < 0: col_t.error(f"GECİKTİ! [{row['plan_date']}] - {row['description']}")
                        elif delta <= 3: col_t.warning(f"YAKLAŞIYOR! [{row['plan_date']}] - {row['description']}")
                        else: col_t.info(f"PLANLI [{row['plan_date']}] - {row['description']}")

        # TAB 5: DOSYA & ARŞİV
        with tabs[4]:
            st.subheader("🗂️ Dosya Dökümü ve Geçmiş Bilgiler")
            
            with st.expander("📌 İLK BAŞVURU VE ANAMNEZ (Hastanın Geçmişi)", expanded=True):
                st.markdown(f"**Geliş Şikayeti:** {safe_str(current_patient.get('chief_complaint', '-'))}")
                st.markdown(f"**Hikaye / Ne Olmuş?:** {safe_str(current_patient.get('anamnesis', '-'))}")
                st.markdown(f"**Özgeçmiş:** {safe_str(current_patient.get('history_og', '-'))}")
                st.markdown(f"**Kullandığı İlaçlar:** {safe_str(current_patient.get('meds_ki', '-'))}")
                st.markdown(f"**İlk Nörolojik Muayene:** {safe_str(current_patient.get('initial_nm', '-'))}")
                st.markdown(f"**İlk Nörogörüntüleme:** {safe_str(current_patient.get('initial_neuroimaging', '-'))}")
            
            st.markdown("### 🗓️ Geçmiş Günlük Gözlemler")
            all_evals = fetch_data("SELECT * FROM daily_evals WHERE patient_id=? ORDER BY eval_date DESC", [int(current_patient['id'])], [])
            
            if not all_evals.empty:
                for idx, row in all_evals.iterrows():
                    with st.expander(f"▶️ {safe_str(row['eval_date'])} Tarihli Gözlem Dosyası"):
                        c_sol, c_sag = st.columns(2)
                        with c_sol:
                            st.markdown(f"**Nörolojik Muayene:** {safe_str(row['nm_today'])}")
                            st.markdown(f"**Solunum:** {safe_str(row['intubation_status'])} | **Sedasyon:** {safe_str(row['sedasyon'])}")
                            st.markdown(f"**Beslenme:** {safe_str(row['beslenme'])} | **Mayi:** {safe_str(row['mayi'])}")
                        with c_sag:
                            st.markdown(f"**Nörogörüntüleme:** {safe_str(row['norogoruntuleme'])}")
                            st.markdown(f"**Konsültasyonlar:** {safe_str(row['konsultasyonlar'])}")
                            st.markdown(f"**Antibiyotik:** {safe_str(row['antibiotics'])}")
                        
                        st.markdown(f"**Genel Not & Lab Analizleri:** {safe_str(row['daily_note'])}")
                        st.markdown(f"**Hasta Yakını Bilgilendirme:** {safe_str(row['hasta_yakini'])}")
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

            if st.button("Hastayı Arşivle ve Yatağı Boşalt"):
                try:
                    execute_query(f"UPDATE patients SET status = ?, discharge_date = ?, bed_no = NULL WHERE id = ?", [cikis_turu, str(cikis_tarihi), int(current_patient['id'])])
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
                
                if st.form_submit_button("📥 Hastayı Yatağa Al") and p_name:
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
    """, [])
    if not arsiv_hastalar.empty:
        st.dataframe(arsiv_hastalar.drop(columns=["id"]), hide_index=True, use_container_width=True)
    else:
        st.info("Arşivde henüz hasta bulunmamaktadır.")
