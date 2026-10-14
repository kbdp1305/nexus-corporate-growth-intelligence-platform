import pandas as pd
import streamlit as st

from egi import auth, data, state, tindak as T, ui

store = data.get_store(); ss = st.session_state
user = auth.current()
is_div = user['role'] == 'divisi'
ui.page_header(f"{user['nama'] if is_div else ss.rm} · tiket hasil kunjungan & pendampingan kunjungan", 'Koordinasi divisi')
st.caption('RM dapat membalas atau membatalkan permintaan. Divisi penerima memproses dan menyelesaikan tiket; '
           'supervisor dapat memproses sebagai pengawas. Tiket kegiatan yang selesai memperbarui progres terkait.')

df = T.visible_requests(user)
df = df[df.jenis != 'Pengajuan kunjungan']
if user['role'] == 'supervisor' and ss.rm != 'Semua RM':
    df = df[df.rm_id == ss.rm]

k = st.columns(len(T.ST_TIKET))
for col, s in zip(k, T.ST_TIKET):
    ui.kpi(col, s, str(int((df.status == s).sum())), 'tiket')
st.write('')

f1, f2, f3 = st.columns([1.4, 1.2, 1.4])
stat = f1.multiselect('Status', T.ST_TIKET, default=['Baru', 'Diproses', 'Dikonfirmasi'])
jenis = f2.multiselect('Jenis', ['Koordinasi hasil kunjungan', 'Koordinasi kegiatan', 'Pendampingan kunjungan', 'Undangan rapat dadakan', T.ESKALASI])
divf = [] if is_div else f3.multiselect('Divisi', list(T.DIVISI), format_func=lambda d: T.DIVISI[d])
v = df[df.status.isin(stat or T.ST_TIKET)]
if jenis:
    v = v[v.jenis.isin(jenis)]
if divf:
    v = v[v.divisi.isin(divf)]
order = {'Mendesak': 0, 'Tinggi': 1, 'Normal': 2}
v = v.assign(_p=v.prioritas.map(order).fillna(3)).sort_values(['_p', 'tenggat', 'dibuat_pada'])

if v.empty:
    st.info('Tidak ada tiket dengan filter ini.' + ('' if is_div else ' Tiket dibuat dari Tindak lanjut kunjungan (feedback) atau saat pengajuan kunjungan disetujui.'))

PRIO = {'Mendesak': ('#FADFDB', '#9A2416'), 'Tinggi': ('#FBEFD6', '#7A4E00'), 'Normal': ('#EEF0F3', '#374151')}
STC = {'Baru': ('#EEF2F9', ui.NAVY2), 'Diproses': ('#FBEFD6', '#7A4E00'), 'Selesai': ('#E4F1EA', '#17613F'), 'Ditolak': ('#FADFDB', '#9A2416')}
STC.update({'Dikonfirmasi': ('#DBEAFE', '#1D4ED8'), 'Dibatalkan': ('#EEF0F3', '#6B7280')})
for r in v.head(40).to_dict('records'):
    cid = r['company_id']; nama = store.co.name.get(cid, cid)
    telat = r['tenggat'] and r['status'] in ('Baru', 'Diproses', 'Dikonfirmasi') and r['tenggat'] < str(pd.Timestamp.today().date())
    head = f"{r['status']} · {r['prioritas']} · {T.DIVISI.get(r['divisi'], r['divisi'])} · {r['judul']} · {r['rm_id']}" + (' · LEWAT TENGGAT' if telat else '')
    with st.expander(head, expanded=is_div and r['status'] == 'Baru'):
        a, b = st.columns([1.5, 1])
        with a:
            if r['jenis'] in ('Pendampingan kunjungan', 'Undangan rapat dadakan'):
                st.caption('Pendampingan baru dianggap tersedia setelah divisi memilih Dikonfirmasi. Perubahan waktu membutuhkan konfirmasi ulang.')
            st.markdown(ui.badge(r['status'], *STC.get(r['status'], STC['Baru'])) + ui.badge(r['prioritas'], *PRIO.get(r['prioritas'], PRIO['Normal']))
                        + ui.badge(r['jenis'], '#EEF0F3', '#374151') + (ui.badge('lewat tenggat', '#FADFDB', '#9A2416') if telat else '')
                        + f"<br><span class='egi-muted'>Tenggat {r['tenggat'] or '—'} · dibuat {r['dibuat_pada'][:16].replace('T', ' ')} oleh {ui.esc(r['dibuat_oleh'])}</span>",
                        unsafe_allow_html=True)
            st.markdown(ui.esc(r['isi']).replace('\n', '<br>'), unsafe_allow_html=True)
        with b:
            if cid in store.cox.index:
                c = store.cox.loc[cid]
                held = ', '.join(sorted(store.hold[store.hold.company_id == cid].product_id.unique())) or '—'
                st.markdown(f"**{ui.esc(nama)}** · {cid}<br>" + ui.badge(c.segment or '—', ui.SEG_COLOR.get(c.segment, '#999'), '#fff') + ui.risk_badge(c.pred_class)
                            + f"<br><span class='egi-muted'>{ui.esc(c.industry)} · Kec. {ui.esc(c.district)}<br>{'Nasabah' if c.is_client else 'Prospect'} · produk: {held}</span>",
                            unsafe_allow_html=True)
                if not is_div and st.button('Profil 360°', key=f"pf_{r['id']}"):
                    state.focus_company(cid)
        st.markdown('**Percakapan**')
        for e in T.thread(r):
            st.markdown(f"<span class='egi-muted'>{e['waktu'][:16].replace('T', ' ')} · {ui.esc(e['oleh'])}"
                        + (f" · <b>{ui.esc(e['status'])}</b>" if e.get('status') else '') + f"</span><br>{ui.esc(e['pesan'])}", unsafe_allow_html=True)
        boleh = (is_div and r['divisi'] == user['rm_id']) or user['role'] == 'supervisor' or (user['role'] == 'rm' and r['rm_id'] == user['rm_id'])
        if boleh:
            with st.form(f"rp_{r['id']}", clear_on_submit=True):
                pesan = st.text_area('Balasan', height=70, placeholder='Mis. Simulasi limit sudah dikirim ke email RM; mohon lengkapi laporan keuangan 2025.'
                                     if is_div else 'Mis. Dokumen sudah saya minta ke nasabah.')
                pilihan = ['(tetap)'] + T.ticket_status_options(r, user)
                st_baru = st.selectbox('Ubah status', pilihan, index=pilihan.index('Diproses') if is_div and r['status'] == 'Baru' and 'Diproses' in pilihan else 0)
                if st.form_submit_button('Kirim', type='primary'):
                    if not pesan.strip() and st_baru == '(tetap)':
                        st.error('Tulis balasan atau ubah status.')
                    else:
                        try:
                            T.reply(r['id'], user['username'], pesan.strip() or f'Status → {st_baru}', None if st_baru == '(tetap)' else st_baru)
                            data.audit('balas_tiket', user=user['username'], id=r['id'], status=st_baru)
                            st.rerun()
                        except (ValueError, OSError) as error:
                            st.error(str(error))
if len(v) > 40:
    st.caption(f'Menampilkan 40 dari {len(v)} tiket; persempit dengan filter.')
