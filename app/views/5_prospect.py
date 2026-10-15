import streamlit as st

from egi import data, llm, state, ui

store = data.get_store(); ss = st.session_state

ui.page_header(f'{ss.rm} · prospect yang sudah bertransaksi dengan nasabah Anda', 'Prospect lewat jaringan')
pr = store.prospects_for(ss.rm)
if pr.empty:
    st.info('Belum ada prospect yang terhubung ke nasabah RM ini.'); st.stop()

f1, f2 = st.columns(2)
no_high = f1.toggle('Sembunyikan risiko High', value=True)
ws_only = f2.toggle('Hanya kecamatan white-space')
v = pr.copy()
if no_high: v = v[v.risk_class != 'High']
if ws_only: v = v[v.white_space]

k = st.columns(4)
ui.kpi(k[0], 'Prospect terhubung', ui.fmt(len(pr), 0), f"{int((pr.risk_class == 'High').sum())} berisiko High")
ui.kpi(k[1], 'Nilai transaksi dengan nasabah Anda', f"Rp {ui.fmt(pr.nilai_M.sum(), 0)} M/thn", 'jumlah nilai relasi aktif')
ui.kpi(k[2], 'Di kecamatan white-space', ui.fmt(int(pr.white_space.sum()), 0), 'tanpa cabang, penetrasi rendah', color=ui.ORANGE)
ui.kpi(k[3], 'Lewat > 1 nasabah', ui.fmt(int((pr.lewat.str.len() > 1).sum()), 0), 'jalan masuk lebih dari satu')
st.write('')

if v.empty:
    st.caption('Tidak ada prospect yang cocok dengan filter.'); st.stop()
t = v[['name', 'segment', 'district', 'lewat_nama', 'nilai_M', 'acquisition_score', 'risk_class', 'white_space']].reset_index().rename(columns={'other': 'company_id'})
idcol = t.columns[0]
ev = st.dataframe(t, hide_index=True, use_container_width=True, height=min(38 + 35 * len(t), 420), on_select='rerun', selection_mode='single-row', key='pros_tbl',
                  column_config={idcol: 'ID', 'name': 'Prospect', 'segment': 'Segmen', 'district': 'Kecamatan', 'lewat_nama': 'Lewat nasabah Anda',
                                 'nilai_M': st.column_config.NumberColumn('Nilai (Rp M/thn)', format='%.1f'),
                                 'acquisition_score': st.column_config.ProgressColumn('Skor akuisisi', min_value=0, max_value=1, format='%.2f'),
                                 'risk_class': 'Risiko', 'white_space': 'White-space'})
rows = ev.selection.rows if ev and hasattr(ev, 'selection') else []
pref = ss.get('prospect_focus')
pid = t[idcol].iloc[rows[0]] if rows else (pref if pref in set(t[idcol]) else t[idcol].iloc[0])
x = v.loc[pid]

st.subheader(x['name'])
st.markdown(ui.badge(x.segment, ui.SEG_COLOR.get(x.segment, '#999'), '#fff') + ui.risk_badge(x.risk_class)
            + (ui.badge('white-space', '#FDEBDD', '#9A3412') if x.white_space else '') + f" <span class='egi-muted'>{pid} · {ui.esc(x.industry)} · {ui.esc(x.district)}</span>", unsafe_allow_html=True)
a, b = st.columns([1.3, 1])
with a:
    paths = store.intro_paths(pid, ss.rm)
    st.markdown('**Jalur kenalan** (nasabah BNI yang bertransaksi dengan prospect ini)')
    st.dataframe(paths[['name', 'rm_id', 'jenis', 'arah', 'nilai_M', 'milik_saya']], hide_index=True, use_container_width=True,
                 column_config={'name': 'Nasabah', 'rm_id': 'RM', 'jenis': 'Relasi', 'arah': 'Arah', 'nilai_M': st.column_config.NumberColumn('Rp M/thn', format='%.1f'),
                                'milik_saya': 'Nasabah saya'})
    own = paths[paths.milik_saya]
    best = paths.iloc[0] if len(paths) else None
    if best is not None:
        txt = (f"Jalur terbaik lewat nasabah Anda sendiri, {best['name']} (Rp {ui.fmt(best.nilai_M, 1)} M/thn, {best.jenis})." if best.milik_saya else
               f"Jalur terkuat lewat {best['name']} milik {best.rm_id}; koordinasikan dengan RM tersebut.")
        if len(own) and not best.milik_saya:
            txt += f" Alternatif sendiri: {own.iloc[0]['name']}."
        ui.ai_box('Jalan masuk', txt, 'relationships.csv · aturan: utamakan nasabah sendiri, lalu nilai relasi terbesar')
with b:
    if best is not None and st.button('Draf pesan permintaan perkenalan', use_container_width=True):
        msg, m = llm.draft_message('intro', {'perantara': best['name'], 'prospect': x['name']})
        ss['intro_msg'] = (pid, msg, m)
    im = ss.get('intro_msg')
    if im and im[0] == pid:
        txt = st.text_area(f'Draf ({im[2]}) — edit sebelum dikirim', im[1], height=140)
        if st.button('Setujui draf', type='primary'):
            data.audit('setujui_pesan_intro', prospect=pid, perantara=best['name'] if best is not None else None, rm=ss.rm, isi=txt)
            st.success('Draf disetujui dan dicatat di log audit. Kirim lewat WhatsApp Anda sendiri.')
    state.company_actions(store, pid, 'pros', sumber='Prospect lewat jaringan')
