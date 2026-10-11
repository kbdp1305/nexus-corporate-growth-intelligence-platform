import streamlit as st

from egi import data, ui

ui.page_header('Bagaimana angka di dashboard ini dibuat', 'Data & metodologi')
st.markdown("<div class='egi-warn'>Semua data sintetis (v8). Angka menggambarkan cara kerja sistem, bukan kondisi nasabah sebenarnya.</div>", unsafe_allow_html=True)
st.write('')


def table(rel, caption=None, pct=(), **kw):
    df = data.read_optional(rel)
    if df is None:
        st.caption(f'`{rel}` belum ada.'); return None
    df = df.rename(columns={'Unnamed: 0': ''})
    for c in pct:
        if c in df: df[c] = df[c] * 100
    cfg = {c: st.column_config.NumberColumn(format='%.0f%%') for c in pct} | {c: st.column_config.NumberColumn(format='%.3f') for c in df.select_dtypes('float').columns if c not in pct}
    st.dataframe(df, hide_index=True, use_container_width=True, column_config=cfg, **kw)
    if caption: st.caption(caption)
    return df


t = st.tabs(['Alur', 'Model risiko', 'Alarm anomali', 'Segmentasi & skor peluang', 'Asumsi EV', 'Kendali & batasan'])
with t[0]:
    st.markdown("""
| Notebook | Isi | Dipakai di dashboard |
|---|---|---|
| NB01 | Pembuatan data sintetis v8 (perusahaan, keuangan, relasi, transaksi, produk, log aksi RM) | semua halaman |
| NB02–03 | EDA dan rekayasa fitur (rasio, arus kas bulanan, jaringan) | Profil · Keuangan, Anomali |
| NB04–06 | Model risiko 3 kelas (XGBoost + conformal), alarm anomali berbasis aturan, evaluasi di data test terkunci | badge risiko, alasan SHAP, alarm |
| NB07 | Post-evaluasi: audit label, aturan alarm v2 (shadow) | alarm yang ditampilkan |
| NB08 | Segmentasi skala (K-means k=3), Opportunity Score per segmen, P(konversi), nilai harapan (EV) | Daftar prioritas, Overview, Copilot |
| Dashboard | Hanya membaca output; menulis catatan kunjungan, rencana yang disetujui, dan log audit ke `outputs/app/` | — |
""")
with t[1]:
    st.markdown('**Metrik di data test** (baris pertama = champion yang dipakai)')
    table('outputs/06_evaluation/test_metrics.csv')
    a, b = st.columns(2)
    with a:
        st.markdown('**Cakupan conformal**')
        table('outputs/06_evaluation/conformal_test.csv', 'Target cakupan 90%: himpunan prediksi memuat kelas sebenarnya.', pct=('cakupan', 'lo95', 'hi95'))
    with b:
        st.markdown('**Per segmen**')
        table('outputs/08_segmentation/D_risk_by_segment_test.csv', pct=('recall_High', 'cakupan_conformal', 'pct_otomatis'))
    st.markdown('**Fitur paling berpengaruh (SHAP, kelas High)**')
    table('outputs/06_evaluation/shap_global.csv', height=260)
with t[2]:
    table('outputs/07_postevaluation/F_anomaly_v1_vs_v2.csv', 'Dashboard memakai v2 (shadow NB07) bila tersedia; resmi tetap v1 sampai disetujui.')
with t[3]:
    st.markdown('**Pemilihan k** — aturan: Jaccard stabilitas ≥ 0,85, lalu Cramér V tertinggi terhadap konversi aksi RM')
    table('outputs/08_segmentation/C_k_selection.csv')
    st.markdown('**Profil segmen**')
    table('outputs/08_segmentation/C_segment_profile.csv', pct=('konversi_aksi_RM',))
    st.markdown('**Validasi di outcome Jul–Sep (dibuka satu kali)**')
    table('outputs/08_segmentation/H_validation_company_level.csv', 'Lift = presisi Top-50 / adopsi dasar. Lift skor resmi moderat; di beberapa segmen ranking sederhana setara.',
          pct=('adopsi_dasar', 'presisi_top', 'produk_tepat'))
with t[4]:
    table('outputs/scores/assumptions_opportunity.csv', 'EV = P(konversi) × ukuran deal × (margin − PD × LGD) × horizon − biaya kontak.')
    table('outputs/08_segmentation/I_sensitivity_assumptions.csv')
with t[5]:
    st.markdown("""
**Kendali**
- LLM tidak menghitung. Semua angka berasal dari paket fakta; narasi divalidasi dengan pencocokan angka, bagian yang memuat angka asing diganti teks template.
- Copilot tidak memutuskan kredit. Risiko High → produk kredit ditunda; alarm distress → diteruskan ke analis.
- Setiap tindakan tulis (catatan kunjungan, rencana, pesan) menunggu persetujuan RM dan dicatat di `outputs/app/audit_log.jsonl`. Pesan tidak dikirim otomatis.
- RM hanya melihat fakta lengkap nasabah di portofolionya lewat alat agen.

**Batasan**
- Data sintetis; hubungan antarvariabel dirancang, sehingga performa di data nyata perlu diuji ulang.
- Lift Opportunity Score di validasi moderat; gunakan sebagai urutan kerja, bukan target.
- Asumsi EV (margin, LGD, biaya) adalah asumsi kerja, bukan angka resmi bank.
- Catatan dari dashboard belum memengaruhi skor sampai notebook dijalankan ulang.
""")
