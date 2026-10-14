import hashlib

import pandas as pd
import streamlit as st

from egi import auth, data, profile_workspace as PW, region_hover, regions, state, ui, viz
from egi import kalender as K

store = data.get_store()
ss = st.session_state
user = auth.current()
if not user or user['role'] not in ('rm', 'supervisor'):
    st.stop()
supervisor = user['role'] == 'supervisor'
if not supervisor:
    ss.rm = user['rm_id']

ui.page_header(f'Penetrasi BNI per kecamatan · Data per {data.SNAPSHOT:%d/%m/%Y}', 'Potensi Wilayah')
st.caption('Penetrasi = perusahaan nasabah BNI ÷ seluruh perusahaan dalam dataset pada wilayah dan filter yang dipilih. '
           'Angka ini menggambarkan cakupan dataset, bukan keseluruhan pasar korporasi.')
f1, f2, f3 = st.columns(3)
city = f1.selectbox('Kota', ['Semua'] + sorted(store.cox.city.dropna().unique()), key='region_city')
segment = f2.selectbox('Segmen Nasabah (titik & detail)', ['Semua'] + data.SEGS, key='region_segment')
industry = f3.selectbox('Industri', ['Semua'] + sorted(store.cox.industry.dropna().unique()), key='region_industry')
companies = store.cox.copy()
if city != 'Semua': companies = companies[companies.city == city]
if industry != 'Semua': companies = companies[companies.industry == industry]
stats = regions.aggregate(store, companies)
if city != 'Semua': stats = stats[stats.kota == city]
allowed = PW.accessible_ids(store, user)
relevant = companies[companies.index.isin(allowed)]
relevant = relevant[relevant.is_client | (relevant.customer_type == 'Prospect')]
if segment != 'Semua':
    relevant = relevant[(relevant.customer_type == 'Prospect') | (relevant.segment == segment)]
st.caption('Segmen hanya memfilter nasabah pada titik dan detail. Prospect tetap ditampilkan lintas segmen; penetrasi wilayah mengikuti kota dan industri.')
st.caption('Warna wilayah: agregat BNI sesuai filter. Detail perusahaan: ' + ('seluruh bank (supervisor).' if supervisor else 'portofolio Anda dan prospect jaringan.'))

a, b, c = st.columns(3)
show_clients = a.checkbox('Nasabah BNI' if supervisor else 'Nasabah Saya', value=True, key='region_clients')
show_prospects = b.checkbox('Prospect' if supervisor else 'Prospect Jaringan', value=True, key='region_prospects')
show_branches = c.checkbox('Cabang BNI', value=True, key='region_branches')
highlight = st.selectbox('Sorot Perusahaan di Peta', ['Semua', 'Potensial atau Ada Temuan', 'Sangat Potensial',
                                                    'Sinyal Risiko', 'Momentum Peluang', 'Dengan Temuan'], key='region_highlight')
st.caption('★ Sangat potensial (skor ≥75) · ! merah: distress/pembeli keluar/efek berantai · ↑ hijau: ekspansi/erosi wallet · • ungu: temuan lain. '
           'Sinyal berasal dari 3 bulan data terakhir; simbol dapat muncul bersamaan. Filter sorotan hanya mengubah titik pada peta.')
points = relevant[((relevant.is_client) & show_clients) | ((~relevant.is_client) & show_prospects)]
signature = hashlib.sha1(f'{city}|{segment}|{industry}|{user["role"]}|{ss.rm}'.encode()).hexdigest()[:10]
map_key = f'region_map_{signature}'
pick_key = f'region_pick_{signature}'
options = ['Pilih wilayah'] + list(stats.index)
if ss.get(pick_key) not in options:
    ss[pick_key] = ss.focus_district if ss.focus_district in stats.index else options[0]

focus = ss.get(pick_key)
if focus not in stats.index:
    focus = None
map_col, detail = st.columns([1.85, 1])
with map_col:
    st.markdown('#### Penetrasi BNI per Kecamatan')
    st.caption('Semakin gelap, semakin rendah penetrasi. Klik wilayah untuk melihat peluang. Hover titik perusahaan untuk ringkasan dan tombol Selengkapnya.')
    branches = store.branches if show_branches else None
    event = region_hover.render(region_hover.payload(store, stats, points, branches, K.claims(), focus, highlight), key=map_key)
    if event and event.get('nonce') != ss.get('region_handled_event'):
        ss.region_handled_event = event.get('nonce')
        if event.get('action') == 'company' and event.get('company_id') in points.index:
            state.focus_company(event['company_id'])
        elif event.get('action') == 'district' and event.get('district') in stats.index:
            ss[pick_key] = event['district']
            ss.focus_district = event['district']
            st.rerun()
    gradient = ', '.join(viz.SEQ_RAMP)
    st.markdown(f"<div style='font-size:12px'>100% <span style='display:inline-block;width:180px;height:12px;"
                f"background:linear-gradient(90deg,{gradient});border-radius:6px'></span> 0% · "
                "<span style='display:inline-block;width:12px;height:12px;background:#BEC3CB'></span> Tanpa data</div>", unsafe_allow_html=True)
    st.caption('Skala warna tetap 0–100%, termasuk saat filter berubah. Cabang ditandai lingkaran putih; '
               'nasabah biru, prospect oranye. Kecamatan tanpa batas poligon, termasuk Kota Bekasi, ditampilkan sebagai lingkaran berwarna.')
    st.caption('? Sangat Potensial: skor peluang atau akuisisi ?75/100. Skor merupakan indikator model, bukan jaminan konversi.')
    with st.expander('Daftar penetrasi wilayah', expanded=False):
        table = stats[['kota', 'perusahaan', 'nasabah', 'prospect', 'penetrasi']].reset_index()
        table['penetrasi'] *= 100
        st.dataframe(table, hide_index=True, use_container_width=True,
                     column_config={'district': 'Kecamatan', 'kota': 'Kota', 'perusahaan': 'Perusahaan dalam data',
                                    'nasabah': 'Nasabah BNI', 'prospect': 'Prospect dalam data',
                                    'penetrasi': st.column_config.NumberColumn('Penetrasi BNI', format='%.0f%%')})

with detail, st.container(border=True):
    selected = st.selectbox('Pilih wilayah untuk melihat peluang', options, key=pick_key)
    focus = selected if selected in stats.index else None
    if focus is None:
        st.info('Pilih wilayah pada peta atau daftar pilihan untuk melihat peluang yang bisa ditindaklanjuti.')
    else:
        ss.focus_district = focus
        row = stats.loc[focus]
        local = relevant[relevant.district == focus]
        prospects = local[local.customer_type == 'Prospect']
        customers = local[local.is_client]
        st.markdown(f'#### {ui.esc(focus)}', unsafe_allow_html=True)
        st.caption(row.kota)
        a, b = st.columns(2)
        a.metric('Penetrasi BNI', ui.fmt(row.penetrasi * 100, 0, pct=True))
        b.metric('Perusahaan dalam data', int(row.perusahaan))
        st.caption(f'{row.nasabah} nasabah BNI · {row.prospect} prospect dalam dataset')
        if row.perusahaan == 0:
            st.info('Tidak ada data perusahaan untuk filter ini. Penetrasi belum dapat dihitung.')
        else:
            if row.penetrasi < data.WS_PEN:
                st.markdown(ui.badge(f'Penetrasi rendah (<{data.WS_PEN:.0%})', '#FBEFD6', '#7A4E00'), unsafe_allow_html=True)
            st.caption(f"Dukungan cabang: {'tersedia' if row.cabang else 'belum tersedia'} · jarak rata-rata perusahaan ke cabang {ui.fmt(row.jarak, 1)} km")
        st.markdown('#### Peluang yang Bisa Saya Tindaklanjuti' if not supervisor else '#### Peluang Perusahaan di Wilayah Ini')
        st.caption(f'{len(customers)} nasabah relevan · {len(prospects)} prospect relevan sesuai filter')
        if local.empty:
            st.info('Belum ada nasabah atau prospect dalam cakupan akun Anda di wilayah ini. Penetrasi rendah belum tentu berarti peluang yang dapat langsung dikerjakan.')
        else:
            st.write(f'Wilayah ini memiliki {len(prospects)} prospect relevan dan {len(customers)} nasabah dalam cakupan Anda. '
                     'Konfirmasi kebutuhan dan jalur masuk sebelum merencanakan kunjungan.')
        claims = K.claims()
        for title, scores, subset, score_col in [
            ('Prospect Relevan', store.acq, prospects, 'acquisition_score'),
            ('Nasabah Berpeluang', store.opp, customers, 'opportunity_score')]:
            st.markdown(f'**{title}**')
            ranked = scores[scores.index.isin(subset.index)].sort_values(score_col, ascending=False).head(4)
            if ranked.empty:
                st.caption('Belum ada perusahaan dengan skor untuk cakupan ini.')
            for cid, score in ranked.iterrows():
                company = subset.loc[cid]
                st.markdown(f"**{ui.esc(company['name'])}**", unsafe_allow_html=True)
                st.caption(f'{cid} · {company.segment} · skor prioritas {ui.fmt(score[score_col] * 100, 1)}/100')
                st.markdown(ui.risk_badge(score.risk_class), unsafe_allow_html=True)
                owner = claims.get(cid, '') if not company.is_client else company.rm_id
                locked = bool(not supervisor and owner and owner != user['rm_id'])
                if locked:
                    st.caption(f'Dipegang {owner}; koordinasikan dengan RM tersebut sebelum menjadwalkan.')
                if not company.is_client:
                    paths = store.intro_paths(cid, ss.rm if not supervisor else '')
                    if not paths.empty:
                        path = paths.iloc[0]
                        st.caption(f"Jalur masuk: {path['name']} · RM {path.rm_id}")
                a, b = st.columns(2)
                if a.button('Profil', key=f'region_profile_{cid}', use_container_width=True): state.focus_company(cid)
                if b.button('Jadwalkan', key=f'region_schedule_{cid}', disabled=locked, use_container_width=True):
                    state.schedule_visit(store, cid, sumber=f'Potensi Wilayah · {focus}')
        if st.button('Lihat Daftar Prioritas di Wilayah Ini', key='region_priority', use_container_width=True):
            state.focus_district(focus, 'prioritas')
