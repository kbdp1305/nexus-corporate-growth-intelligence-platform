import pandas as pd
import streamlit as st

from egi import data, state, ui, viz

store = data.get_store(); ss = st.session_state

ui.page_header('Skor potensi per kecamatan dari lat/lon perusahaan · bobot bisa diatur', 'Potensi wilayah')

with st.expander('Bobot skor wilayah', expanded=False):
    x = st.columns(5)
    w = {'gap': x[0].slider('Omzet belum lewat BNI', 0, 5, data.DEFAULT_W['gap']), 'prospect': x[1].slider('Jumlah prospect', 0, 5, data.DEFAULT_W['prospect']),
         'low_pen': x[2].slider('Penetrasi rendah', 0, 5, data.DEFAULT_W['low_pen']), 'poi': x[3].slider('Kepadatan POI', 0, 5, data.DEFAULT_W['poi']),
         'eksp': x[4].slider('Alarm ekspansi', 0, 5, data.DEFAULT_W['eksp'])}
    st.caption(f'White-space = penetrasi < {data.WS_PEN:.0%} dan tidak ada cabang di kecamatan itu. Skor = rata-rata tertimbang persentil (0–100).')
f1, f2 = st.columns([1, 3])
seg = f1.selectbox('Segmen', ['Semua'] + data.SEGS)
dist = store.districts(w, seg)
focus = ss.focus_district if ss.focus_district in dist.index else dist.index[0]

m1, m2 = st.columns([1.6, 1])
with m1:
    c = store.cox if seg == 'Semua' else store.cox[store.cox.segment == seg]
    pts = c[['longitude', 'latitude', 'name', 'segment', 'district', 'is_client', 'rm_id']].rename(columns={'longitude': 'lon', 'latitude': 'lat'}).copy()
    pts['rgb'] = [viz.MINE_RGB if (cl and r == ss.rm) else viz.CLIENT_RGB if cl else viz.PROSPECT_RGB for cl, r in zip(pts.is_client, pts.rm_id)]
    pts['label'] = pts.name + '<br>' + pts.segment.astype(str) + ' · ' + pts.district + ' · ' + pts.is_client.map({True: 'nasabah', False: 'prospect'})
    d = dist.copy(); d['radius'] = 250 + 1800 * (d.skor / 100) ** 1.5
    d['fill'] = [[210, 87, 15, 60] if i == focus else [210, 87, 15, 35] if ws else [30, 58, 110, 25] for i, ws in zip(d.index, d.white_space)]
    d['line'] = [[15, 30, 58, 255] if i == focus else [210, 87, 15, 220] if ws else [30, 58, 110, 120] for i, ws in zip(d.index, d.white_space)]
    d['label'] = [f"<b>{i}</b> · skor {s:.0f}<br>{p:.0f} prospect · Rp {g:,.1f} T · penetrasi {pen:.0%}" + (' · white-space' if ws else '')
                  for i, s, p, g, pen, ws in zip(d.index, d.skor, d.prospect, d.gap_T, d.pen, d.white_space)]
    st.pydeck_chart(viz.deck(pts, d, focus=focus if ss.focus_district else None))
    st.caption('Navy tua = nasabah Anda · biru muda = nasabah RM lain · oranye = prospect. Lingkaran = skor kecamatan; oranye = white-space.')
with m2:
    t = dist[['kota', 'skor', 'prospect', 'pen', 'gap_T', 'white_space']].reset_index(); t['pen'] *= 100
    ev = st.dataframe(t, hide_index=True, use_container_width=True, height=470, on_select='rerun', selection_mode='single-row', key='dist_tbl',
                      column_config={'district': 'Kecamatan', 'kota': 'Kota', 'skor': st.column_config.ProgressColumn('Skor', min_value=0, max_value=100, format='%d'),
                                     'prospect': 'Prospect', 'pen': st.column_config.NumberColumn('Penetrasi', format='%.0f%%'),
                                     'gap_T': st.column_config.NumberColumn('Rp T', format='%.1f'), 'white_space': 'White-space'})
    rows = ev.selection.rows if ev and hasattr(ev, 'selection') else []
    if rows and t.district.iloc[rows[0]] != ss.focus_district:
        state.focus_district(t.district.iloc[rows[0]]); st.rerun()

# ------------------------------------------------------------------ drill-down
r = dist.loc[focus]
st.subheader(f'{focus}, {r.kota}')
k = st.columns(5)
ui.kpi(k[0], 'Skor wilayah', ui.fmt(r.skor, 0), f"peringkat {list(dist.index).index(focus) + 1} dari {len(dist)}", color=ui.ORANGE)
ui.kpi(k[1], 'Perusahaan', ui.fmt(r.n, 0), f"{int(r.nasabah)} nasabah · {int(r.prospect)} prospect")
ui.kpi(k[2], 'Penetrasi', ui.fmt(r.pen * 100, 0, pct=True), 'white-space' if r.white_space else '')
ui.kpi(k[3], 'Omzet belum lewat BNI', f"Rp {ui.fmt(r.gap_T, 1)} T", f"{int(r.besar)} perusahaan S3")
ui.kpi(k[4], 'Cabang', 'ada' if r.cabang else 'tidak ada', f"jarak rata-rata {ui.fmt(r.jarak, 1)} km")
st.write('')
kanal = ('Tidak ada cabang dan jarak > 5 km: kumpulkan kunjungan dalam satu hari (cluster visit) dan pakai telepon untuk S1.' if not r.cabang and r.jarak > 5 else
         'Tidak ada cabang: jadwalkan hari kunjungan khusus kecamatan ini; pertimbangkan kas keliling/agen untuk payroll.' if not r.cabang else
         'Ada cabang: libatkan tim cabang untuk walk-in dan event komunitas usaha; RM fokus ke S2/S3.')
ui.ai_box('Saran kanal', kanal, 'aturan kanal berdasarkan cabang & jarak (bukan LLM)')

cc = store.cox[store.cox.district == focus]
a, b = st.columns(2)
with a:
    st.markdown('**Prospect teratas di kecamatan ini** (skor akuisisi)')
    p = store.acq[store.acq.index.isin(cc.index)].join(cc[['name']]).sort_values('acquisition_score', ascending=False).head(8)
    for pid, x in p.iterrows():
        y1, y2, y3 = st.columns([3, 1, 1])
        y1.markdown(f"{ui.esc(x['name'])}<br><span class='egi-muted'>{pid} · {x.segment} · risiko {x.risk_class} · skor {x.acquisition_score:.2f}</span>", unsafe_allow_html=True)
        if y2.button('Profil', key=f'wp_{pid}'): state.focus_company(pid)
        if y3.button('+ Rencana', key=f'wr_{pid}'): state.add_to_plan(store, pid)
with b:
    st.markdown('**Nasabah dengan peluang tertinggi**')
    o = store.opp[store.opp.index.isin(cc.index)].join(cc[['name', 'rm_id']]).sort_values('opportunity_score', ascending=False).head(8)
    for cid, x in o.iterrows():
        y1, y2, y3 = st.columns([3, 1, 1])
        y1.markdown(f"{ui.esc(x['name'])}{' ★' if x.rm_id == ss.rm else ''}<br><span class='egi-muted'>{cid} · {x.segment} · {x.rm_id} · skor {x.opportunity_score:.2f}</span>", unsafe_allow_html=True)
        if y2.button('Profil', key=f'wo_{cid}'): state.focus_company(cid)
        if y3.button('+ Rencana', key=f'wq_{cid}'): state.add_to_plan(store, cid)
    rms = cc[cc.is_client].rm_id.value_counts().head(5)
    st.caption('RM aktif di sini: ' + ', '.join(f'{i} ({n})' for i, n in rms.items()) + ' · ★ = nasabah Anda')

if st.button(f'Lihat daftar prioritas saya di {focus}', use_container_width=True):
    state.focus_district(focus, 'prioritas')
