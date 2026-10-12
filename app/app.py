"""BNI Ecosystem & Growth Intelligence — dashboard RM (Streamlit).

Jalankan dari folder proyek:
    uv run streamlit run app/app.py
"""
import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from egi import auth, data, state, ui  # noqa: E402

st.set_page_config(page_title='Growth Intelligence · RM', page_icon='📈', layout='wide', initial_sidebar_state='expanded')
ui.apply_theme()

miss = data.missing_files()
if miss:
    st.error('Output notebook belum lengkap. Jalankan NB01–NB08 dulu. Berkas yang belum ada:\n\n' + '\n'.join(f'- `{m}`' for m in miss))
    st.stop()

store = data.get_store()
rms = state.init(store)

if not auth.current():          # belum masuk: hanya halaman login yang terdaftar
    st.navigation([st.Page(lambda: auth.login_page(rms), title='Masuk', url_path='masuk')], position='hidden').run()
    st.stop()

if auth.current()['role'] == 'divisi':     # akun divisi: hanya kotak masuk koordinasi
    pages = {'Divisi': [st.Page('pages/11_koordinasi.py', title='Koordinasi divisi', default=True)]}
else:
    pages = {
        'Ruang kerja RM': [
            st.Page('pages/1_overview.py', title='Overview', default=True),
            st.Page('pages/2_prioritas.py', title='Daftar prioritas'),
            st.Page('pages/3_profil.py', title='Profil 360°'),
            st.Page('pages/4_wilayah.py', title='Potensi wilayah'),
            st.Page('pages/5_prospect.py', title='Prospect lewat jaringan'),
            st.Page('pages/6_copilot.py', title='RM Copilot'),
            st.Page('pages/9_kalender.py', title='Kalender kunjungan'),
            st.Page('pages/7_kinerja.py', title='Kinerja saya'),
        ],
        'Kunjungan & koordinasi': [
            st.Page('pages/10_tindak_lanjut.py', title='Tindak lanjut kunjungan'),
            st.Page('pages/11_koordinasi.py', title='Koordinasi divisi'),
        ],
        'Tentang': [st.Page('pages/8_metodologi.py', title='Data & metodologi')],
    }
nav = st.navigation(pages)
state.sidebar(store, rms)
nav.run()
