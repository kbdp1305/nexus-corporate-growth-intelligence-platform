import pandas as pd
import streamlit as st

from egi import agent, data, state, ui, viz

store = data.get_store(); ss = st.session_state

PLAYBOOK = {
    'S1 Kecil': 'Kanal murah dulu: telepon / email, paket produk standar (P01 + payroll). Kunjungan hanya untuk skor ≥ 0,85 atau ada alarm ekspansi.',
    'S2 Menengah': 'Campuran: kunjungan untuk Top-20, telepon untuk sisanya. Fokus celah produk yang sudah dipegang peer sesegmen.',
    'S3 Besar': 'Kunjungan tatap muka dan solusi ekosistem (supply-chain financing, cash management). Libatkan analis untuk produk kredit.',
}
COMP = {'pct_dompet_belum_digarap': 'Dompet belum digarap', 'pct_ekosistem': 'Ekosistem', 'pct_kebutuhan_modal': 'Kebutuhan modal',
        'pct_celah_produk': 'Celah produk', 'pct_erosi_wallet': 'Erosi wallet'}

ui.page_header(f'{ss.rm} · peringkat dibuat per segmen', 'Daftar prioritas')
pf = agent.candidates(store, ss.rm, [p['id'] for p in ss.plan])
if pf.empty:
    st.info('RM ini belum punya nasabah dengan skor peluang.'); st.stop()

f1, f2, f3, f4 = st.columns([2, 1.2, 1, 1])
kec = f1.multiselect('Kecamatan', sorted(pf.district.unique()), default=[ss.focus_district] if ss.focus_district in set(pf.district) else [])
prods = sorted({p.strip() for s in pf.recommended_products.dropna() for p in str(s).split(',') if p.strip()})
prod = f2.selectbox('Produk disarankan', ['Semua'] + prods)
only_wn = f3.toggle('Hanya Why Now')
hide_c = f4.toggle('Sembunyikan yang sudah dihubungi')
v = pf.copy()
if kec: v = v[v.district.isin(kec)]
if prod != 'Semua': v = v[v.recommended_products.fillna('').str.contains(prod)]
if only_wn: v = v[v.why_up]
if hide_c: v = v[~v.contacted]

k = st.columns(4)
ui.kpi(k[0], 'Nasabah di portofolio', ui.fmt(len(pf), 0), ' · '.join(f"{s.split()[0]} {int((pf.segment == s).sum())}" for s in data.SEGS))
ui.kpi(k[1], 'Skor peluang ≥ 0,75', ui.fmt(int((pf.opportunity_score >= .75).sum()), 0), f"{int(((pf.opportunity_score >= .75) & ~pf.contacted).sum())} belum pernah dihubungi", color=ui.ORANGE)
ui.kpi(k[2], 'Why Now (3 bulan)', ui.fmt(int(pf.why_up.sum()), 0), 'ekspansi / erosi wallet')
ui.kpi(k[3], 'Nilai harapan Top-10', f"Rp {ui.fmt(pf.nlargest(10, 'opportunity_score').ev_idr_mn.sum() / 1000, 1)} M", 'EV = P × deal × (margin − PD×LGD) − biaya')
st.write('')

tabs = st.tabs([f"{s} · {int((v.segment == s).sum())}" for s in data.SEGS])
for tab, sname in zip(tabs, data.SEGS):
    with tab:
        st.markdown(f"<div class='egi-card' style='border-left:4px solid {ui.SEG_COLOR[sname]}'><b>Playbook {sname}.</b> {PLAYBOOK[sname]}</div>", unsafe_allow_html=True)
        g = v[v.segment == sname].copy()
        if g.empty:
            st.caption('Tidak ada nasabah yang cocok dengan filter.'); continue
        g['status'] = g.caution.map({True: '⚠ alarm risiko', False: ''}) + g.why_up.map({True: ' ↑ Why Now', False: ''}) + g.contacted.map({True: '', False: ' · baru'})
        t = g[['name', 'district', 'opportunity_score', 'rank_in_segment', 'risk_class', 'status', 'recommended_products', 'p_convert', 'ev_idr_mn']].reset_index()
        ev = st.dataframe(t, hide_index=True, use_container_width=True, height=min(38 + 35 * len(t), 460), on_select='rerun', selection_mode='single-row', key=f'tbl_{sname}',
                          column_config={'company_id': 'ID', 'name': 'Perusahaan', 'district': 'Kecamatan',
                                         'opportunity_score': st.column_config.ProgressColumn('Skor peluang', min_value=0, max_value=1, format='%.2f'),
                                         'rank_in_segment': st.column_config.NumberColumn('Peringkat', format='%d'), 'risk_class': 'Risiko', 'status': 'Status',
                                         'recommended_products': 'Produk disarankan', 'p_convert': st.column_config.NumberColumn('P(konversi)', format='%.2f'),
                                         'ev_idr_mn': st.column_config.NumberColumn('EV (Rp juta)', format='%.0f')})
        rows = ev.selection.rows if ev and hasattr(ev, 'selection') else []
        cid = t.company_id.iloc[rows[0]] if rows else t.company_id.iloc[0]
        r = g.loc[cid]
        st.markdown(f"#### {ui.esc(r['name'])} <span class='egi-muted'>{cid} · {ui.esc(r.district)}</span>", unsafe_allow_html=True)
        a, b = st.columns([1.1, 1])
        with a:
            st.markdown(ui.risk_badge(r.risk_class) + ''.join(ui.event_badge(e.strip()) for e in str(r.alarm).split(',') if e.strip()), unsafe_allow_html=True)
            ui.ai_box('Kenapa nasabah ini', str(r.reason), source='komponen skor peluang NB08 + aturan risiko')
            state.company_actions(store, cid, f'pr_{sname}')
        with b:
            comps = {lab: float(r[c]) * 100 for c, lab in COMP.items() if c in r.index and pd.notna(r[c])}
            st.plotly_chart(viz.hbar(list(comps), list(comps.values()), [f'{x:.0f}' for x in comps.values()], h=210, xmax=115,
                                     title='Komponen (persentil di segmen)'), use_container_width=True, key=f'cmp_{sname}_{cid}')
st.caption('Skor = persentil gabungan komponen di dalam segmen + bonus Why Now; risiko High → produk kredit ditunda, Medium → kredit × 0,5. '
           'Pilih baris untuk melihat alasannya.')
