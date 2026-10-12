import pandas as pd
import streamlit as st

from egi import agent, data, state, ui, viz

store = data.get_store(); ss = st.session_state
co = store.cox

ui.page_header('Data per 30 Jun 2026 · 7 kota · 40 kecamatan', 'Peluang pertumbuhan Jabodetabek')

# ------------------------------------------------------------------ hari ini (per RM)
if ss.rm != 'Semua RM':
    pf = agent.candidates(store, ss.rm)
    wn_rm = store.why_now(pf.index, months=1).sort_values('score', ascending=False).drop_duplicates('company_id')
    wn_rm = wn_rm.assign(urut=~wn_rm.event_type.isin(agent.CAUTION)).sort_values(['urut', 'score'], ascending=[True, False])
    fresh = pf[(pf.opportunity_score >= 0.75) & ~pf.contacted & ~pf.index.isin([p['id'] for p in ss.plan])]
    fu = store.followups(ss.rm)
    late = fu[fu.telat_hari > 0]
    with st.container(border=True):
        st.markdown(f"#### Hari ini · {ss.rm}")
        st.caption(f"{len(wn_rm)} alarm bulan ini · {len(fresh)} prioritas belum dihubungi · {len(late)} tindak lanjut terlambat · "
                   f"{len(ss.plan)} di rencana minggu · per {data.SNAPSHOT:%d %b %Y}")
        h1, h2, h3 = st.columns(3)
        with h1:
            st.markdown('**Alarm baru** · risiko dulu')
            for r in wn_rm.head(3).itertuples():
                a, b = st.columns([4, 1.3])
                a.markdown(f"{ui.event_badge(r.event_type)} {ui.esc(store.co.name.get(r.company_id, r.company_id))}<br>"
                           f"<span class='egi-muted'>{r.company_id} · {ui.EVENT_STYLE.get(r.event_type, ('', '', '', ''))[3]}</span>", unsafe_allow_html=True)
                if b.button('Profil', key=f'hi_al_{r.company_id}'):
                    state.focus_company(r.company_id)
            if wn_rm.empty:
                st.caption('Tidak ada alarm bulan ini.')
        with h2:
            st.markdown('**Prioritas belum dihubungi**')
            for cid, r in fresh.head(3).iterrows():
                a, b = st.columns([4, 1.3])
                a.markdown(f"{ui.esc(r['name'])}<br><span class='egi-muted'>{cid} · {r.segment} · skor {ui.fmt(r.opportunity_score * 100, 0)} · {r.recommended_products}</span>",
                           unsafe_allow_html=True)
                if b.button('+ Rencana', key=f'hi_pr_{cid}'):
                    state.add_to_plan(store, cid, 'prioritas belum dihubungi'); st.rerun()
            if fresh.empty:
                st.caption('Semua prioritas sudah dihubungi atau ada di rencana.')
        with h3:
            st.markdown(f'**Tindak lanjut** · {data.FOLLOWUP_DAYS} hari setelah "tertarik"')
            for r in fu.head(3).itertuples():
                a, b = st.columns([4, 1.3])
                when = f"terlambat {r.telat_hari} hari" if r.telat_hari > 0 else f"jatuh tempo {r.jatuh_tempo:%d %b}"
                a.markdown(f"{ui.esc(r.name)}<br><span class='egi-muted'>{r.party_id} · {r.product_id} · kontak {r.contact_date} · "
                           f"<b style='color:{'#9A2416' if r.telat_hari > 0 else ui.INK2}'>{when}</b></span>", unsafe_allow_html=True)
                if b.button('Profil', key=f'hi_fu_{r.party_id}'):
                    state.focus_company(r.party_id)
            if fu.empty:
                st.caption('Tidak ada tindak lanjut tertunda.')
        b1, b2, _ = st.columns([1.2, 1.2, 3])
        if b1.button('Susun rencana minggu di Copilot', use_container_width=True):
            ss.copilot_task = 'plan'; state.go('copilot')
        if b2.button('Tanya Copilot soal hari ini', use_container_width=True):
            ss.copilot_task = 'chat'
            ss.pending_q = 'Apa yang paling penting saya kerjakan hari ini? Pertimbangkan alarm baru, prioritas yang belum dihubungi, dan tindak lanjut yang terlambat.'
            state.go('copilot')

f1, f2, f3, f4, f5 = st.columns([1.2, 1, 1, 1, 1.3])
scope = f1.segmented_control('Cakupan', ['Seluruh bank', 'Portofolio saya'], default='Seluruh bank', disabled=ss.rm == 'Semua RM') or 'Seluruh bank'
kota = f2.selectbox('Kota', ['Semua'] + sorted(co.city.unique()))
ind = f3.selectbox('Industri', ['Semua'] + sorted(co.industry.unique()))
seg = f4.selectbox('Segmen', ['Semua'] + data.SEGS)

c = co.copy()
if scope == 'Portofolio saya' and ss.rm != 'Semua RM':
    c = c[c.rm_id == ss.rm]
if kota != 'Semua': c = c[c.city == kota]
if ind != 'Semua': c = c[c.industry == ind]
if seg != 'Semua': c = c[c.segment == seg]
cl = c[c.is_client]
dist = store.districts(seg=seg)
ws = dist[dist.white_space]
wn = store.why_now(cl.index, months=1)
logd = store.log_all[(store.log_all.track == 'Deepening') & store.log_all.party_id.isin(cl.index)]

k = st.columns(5)
ui.kpi(k[0], 'Perusahaan', ui.fmt(len(c), 0), f"{ui.fmt(len(cl), 0)} nasabah · {ui.fmt(len(c) - len(cl), 0)} prospect")
ui.kpi(k[1], 'Produk aktif per nasabah', f"{ui.fmt(store.n_prod.reindex(cl.index).mean(), 1)} / 8", 'P01 dipegang semua nasabah')
ui.kpi(k[2], 'Omzet belum lewat BNI', f"Rp {ui.fmt(ws.gap_T.sum(), 1)} T", f'di {len(ws)} kecamatan white-space', color='#B4470A')
ui.kpi(k[3], 'Nasabah beralarm bulan ini', ui.fmt(wn.company_id.nunique(), 0),
       ' · '.join(f"{ui.EVENT_STYLE[e][2].lower()} {n}" for e, n in wn.groupby('event_type').company_id.nunique().sort_values(ascending=False).head(3).items()))
ui.kpi(k[4], 'Konversi bila didatangi', ui.fmt(logd.converted.mean() * 100, 0, pct=True) if len(logd) else '—', 'aksi RM Jan–Jun 2026')
st.write('')

m1, m2 = st.columns([1.6, 1])
with m1:
    st.subheader('Peta peluang')
    pts = c[['longitude', 'latitude', 'name', 'segment', 'district', 'is_client']].rename(columns={'longitude': 'lon', 'latitude': 'lat'})
    pts['rgb'] = [viz.CLIENT_RGB if x else viz.PROSPECT_RGB for x in pts.is_client]
    pts['label'] = pts.name + '<br>' + pts.segment.astype(str) + ' · ' + pts.district + ' · ' + pts.is_client.map({True: 'nasabah', False: 'prospect'})
    d = dist.copy(); d['radius'] = 250 + 1800 * (d.gap_T / d.gap_T.max()) ** 0.5
    d['label'] = [f"<b>{i}</b> · skor {s:.0f}<br>{p:.0f} prospect · Rp {g:,.1f} T · penetrasi {pen:.0%}" for i, s, p, g, pen in zip(d.index, d.skor, d.prospect, d.gap_T, d.pen)]
    poly = viz.district_polygons(d, store.shapes, 'gap_T')
    st.pydeck_chart(viz.deck(pts, d, polygons=poly, branches=viz.branch_points(store.branches)))
    st.markdown(viz.scale_legend('Omzet belum lewat BNI', f"Rp {d.gap_T.min():,.1f} T", f"Rp {d.gap_T.max():,.1f} T"), unsafe_allow_html=True)
    st.caption('White-space = penetrasi rendah dan tanpa cabang. Kota Bekasi tanpa poligon OSM, ditampilkan sebagai lingkaran.')
with m2:
    st.subheader('Kecamatan paling potensial')
    t = dist.head(8)[['kota', 'skor', 'prospect', 'gap_T', 'pen']].reset_index(); t['pen'] *= 100
    st.dataframe(t, hide_index=True, use_container_width=True, height=330,
                 column_config={'district': 'Kecamatan', 'kota': 'Kota', 'skor': st.column_config.ProgressColumn('Skor', min_value=0, max_value=100, format='%d'),
                                'prospect': 'Prospect', 'gap_T': st.column_config.NumberColumn('Rp T', format='%.1f'), 'pen': st.column_config.NumberColumn('Penetrasi', format='%.0f%%')})
    pick = st.selectbox('Fokus ke kecamatan', ['—'] + list(dist.index[:15]))
    if pick != '—' and st.button('Buka di Potensi wilayah', use_container_width=True):
        state.focus_district(pick, 'wilayah')

s1, s2 = st.columns(2)
with s1:
    st.subheader('Tiga segmen skala')
    prof = data.read_optional('outputs/08_segmentation/C_segment_profile.csv')
    cols = st.columns(3)
    for col, sname in zip(cols, data.SEGS):
        g = c[c.segment == sname]
        conv = prof.set_index(prof.columns[0]).loc[sname, 'konversi_aksi_RM'] if prof is not None else float('nan')
        ui.kpi(col, sname, ui.fmt(int(g.is_client.sum()), 0), f"nasabah · {int((~g.is_client).sum())} prospect · omzet median Rp {ui.fmt(g.rev_bn.median(), 1)} M · konversi RM {ui.fmt(conv * 100, 0)}%",
               color=ui.SEG_COLOR[sname])
    st.caption('Ranking RM dibuat per segmen: konversi bila didatangi naik dari segmen kecil ke besar.')
with s2:
    st.subheader('Penetrasi produk')
    pen = store.hold[store.hold.company_id.isin(cl.index)].groupby('product_id').company_id.nunique().reindex(sorted(store.hold.product_id.unique())).fillna(0) / max(len(cl), 1) * 100
    pen = pen.sort_values(ascending=False)
    credit = set(store.hold.loc[store.hold.utilization.notna(), 'product_id'])
    st.plotly_chart(viz.hbar([p + (' (kredit)' if p in credit else '') for p in pen.index], pen.values, [f'{v:.0f}%' for v in pen.values], h=290, xmax=115), use_container_width=True)

g1, g2 = st.columns(2)
with g1:
    st.subheader('Celah produk terbesar per kecamatan')
    pr = store.prod[store.prod.company_id.isin(cl.index) & (store.prod.need_score >= 0.5)].join(co[['district', 'city']], on='company_id')
    if len(pr):
        gp = pr.groupby(['district', 'product_id']).size().rename('celah').reset_index().sort_values('celah', ascending=False).drop_duplicates('district').head(8)
        gp['nasabah'] = gp.district.map(cl.groupby('district').size()); gp['pct'] = gp.celah / gp.nasabah * 100
        st.dataframe(gp[['district', 'product_id', 'celah', 'pct']], hide_index=True, use_container_width=True,
                     column_config={'district': 'Kecamatan', 'product_id': 'Produk', 'celah': 'Nasabah celah', 'pct': st.column_config.NumberColumn('% nasabah', format='%.0f%%')})
    st.caption('Celah = produk yang dipegang ≥ 50% peer sesegmen & industri tetapi belum dimiliki. Produk kredit hanya ditawarkan bila risiko bukan High.')
with g2:
    st.subheader('Industri')
    top = store.opp[store.opp.rank_in_segment <= 50].index
    it = c.groupby('industry').agg(perusahaan=('name', 'size'), top50=('name', lambda s: s.index.isin(top).sum())).sort_values('perusahaan', ascending=False).reset_index()
    st.dataframe(it, hide_index=True, use_container_width=True,
                 column_config={'industry': 'Industri', 'perusahaan': st.column_config.ProgressColumn('Perusahaan', min_value=0, max_value=int(it.perusahaan.max()), format='%d'),
                                'top50': st.column_config.ProgressColumn('Masuk Top-50 segmen', min_value=0, max_value=max(int(it.top50.max()), 1), format='%d')})

st.subheader(f'Alarm terbaru · Jun 2026 ({store.alerts_src})')
al = wn.sort_values('score', ascending=False).drop_duplicates('company_id').groupby('event_type').head(2).head(8)
for r in al.itertuples():
    a, b, cbtn = st.columns([3, 5, 1.2])
    a.markdown(f"**{ui.esc(store.co.name.get(r.company_id, r.company_id))}**<br><span class='egi-muted'>{r.company_id} · {co.segment.get(r.company_id)} · {ui.EVENT_STYLE.get(r.event_type, ('', '', '', ''))[3]}</span>", unsafe_allow_html=True)
    b.markdown(ui.event_badge(r.event_type) + f" <span class='egi-muted'>{ui.esc(r.reason)}</span>", unsafe_allow_html=True)
    if cbtn.button('Profil', key=f'al_{r.company_id}_{r.event_type}'):
        state.focus_company(r.company_id)
