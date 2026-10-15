import pandas as pd
import plotly.express as px
import streamlit as st

from egi import agent, auth, data, state, tindak, ui, viz
from egi import kalender as K

store = data.get_store()
ss = st.session_state
user = auth.current()
if not user or user['role'] not in ('rm', 'supervisor'):
    st.stop()
supervisor = user['role'] == 'supervisor'
today = pd.Timestamp.now(tz='Asia/Bangkok').tz_localize(None).normalize()
now = pd.Timestamp.now(tz='Asia/Bangkok').tz_localize(None)
week_start = today - pd.Timedelta(days=today.weekday())
week_end = week_start + pd.Timedelta(days=7)
period = f'{state.BULAN[data.SNAPSHOT.month - 1]} {data.SNAPSHOT.year}'
ui.page_header(f'Data peluang & temuan: {period} · Agenda operasional: {today:%d/%m/%Y}', 'Insight Perusahaan')

# Use the authenticated account, not a saved widget value, for RM scope.
if supervisor:
    scope = st.segmented_control('Cakupan', ['Portofolio RM', 'Seluruh bank'],
                                 default='Seluruh bank' if ss.rm == 'Semua RM' else 'Portofolio RM', key='ov_scope')
    if scope == 'Portofolio RM':
        rms = sorted(store.co.rm_id.dropna().unique())
        rm = st.selectbox('Portofolio RM', rms, index=rms.index(ss.rm) if ss.rm in rms else 0, key='ov_rm')
    else:
        rm = 'Semua RM' if scope == 'Seluruh bank' else ss.rm
else:
    rm = user['rm_id']
ss.rm = rm
st.caption(f"{'Seluruh bank' if rm == 'Semua RM' else 'Portofolio ' + rm} · Temuan dan potensi: {period} · Progress: tanggal operasional")

base = store.cox if rm == 'Semua RM' else store.cox[store.cox.rm_id == rm]
f1, f2, f3 = st.columns(3)
city = f1.selectbox('Kota', ['Semua'] + sorted(base.city.dropna().unique()), key='ov_city')
industry = f2.selectbox('Industri', ['Semua'] + sorted(base.industry.dropna().unique()), key='ov_industry')
segment = f3.selectbox('Segmen Nasabah', ['Semua'] + data.SEGS, key='ov_segment')
co = base.copy()
if city != 'Semua': co = co[co.city == city]
if industry != 'Semua': co = co[co.industry == industry]
if segment != 'Semua': co = co[(co.customer_type == 'Prospect') | (co.segment == segment)]
ids = co.index
pf = agent.candidates(store, rm)
pf = pf[pf.index.isin(ids)]
alarms = store.why_now(ids, months=1)
alarms = alarms[alarms.ym == data.REF_MONTH].sort_values('score', ascending=False)
fresh = pf[(pf.opportunity_score >= 0.75) & ~pf.contacted & ~pf.index.isin(K.scheduled_ids(rm, now=now.to_pydatetime()))]
fu = store.followups(rm)
fu = fu[fu.party_id.isin(ids)].copy()
fu['telat_hari'] = (today - fu.jatuh_tempo.dt.normalize()).dt.days
due = fu[fu.jatuh_tempo < today + pd.Timedelta(days=8)]
keg = tindak.kegiatan_for(rm).copy()
keg = keg[keg.company_id.isin(ids)]
if not keg.empty:
    keg['sisa_hari'] = (pd.to_datetime(keg.tenggat, errors='coerce').dt.normalize() - today).dt.days
    keg['status_tampil'] = 'berjalan'
    keg.loc[keg.sisa_hari < 0, 'status_tampil'] = 'terlambat'
    keg.loc[keg.status == 'Selesai', 'status_tampil'] = 'selesai'
    keg.loc[keg.status == 'Dibatalkan', 'status_tampil'] = 'batal'
agenda = K.active(rm)
agenda = agenda[(agenda._m >= week_start) & (agenda._m < week_end)
                & (agenda.status == 'Terjadwal') & agenda.company_id.isin(ids)].sort_values('_m')
urgent = keg[(keg.status_tampil.isin(['berjalan', 'terlambat'])) & (keg.sisa_hari <= 7)]
active = keg[keg.status_tampil != 'batal']

k = st.columns(4)
ui.kpi(k[0], 'Nasabah dengan temuan', ui.fmt(alarms.company_id.nunique(), 0), f'{period} · {len(alarms)} alarm')
ui.kpi(k[1], 'Perlu dihubungi', ui.fmt(len(fresh), 0), 'Skor peluang ≥ 75 · belum dihubungi atau dijadwalkan')
ui.kpi(k[2], 'Tindak lanjut jatuh tempo', ui.fmt(len(due) + len(urgent), 0), 'Kontak tertarik + kegiatan · sampai 7 hari ke depan', color='#9A2416')
ui.kpi(k[3], 'Agenda Minggu Ini', ui.fmt(len(agenda), 0), f'{week_start:%d/%m}–{(week_end - pd.Timedelta(days=1)):%d/%m} · terjadwal')

ACTION = {
    'distress': 'Konfirmasi kondisi pembayaran dan koordinasikan dengan analis risiko.',
    'buyer_exit': 'Konfirmasi aktivitas pembeli utama dan kebutuhan transaksi nasabah.',
    'contagion': 'Pantau pembayaran dari anchor dan koordinasikan risiko rantai pasok.',
    'expansion': 'Konfirmasi ekspansi dan kebutuhan modal kerja sesuai kelayakan risiko.',
    'wallet_erosion': 'Hubungi PIC treasury untuk membahas retensi transaksi di BNI.',
    'spike': 'Verifikasi apakah lonjakan transaksi berulang atau hanya sekali.'}

st.subheader('Perlu Aksi')
left, right = st.columns([1.15, 1])
with left, st.container(border=True):
    st.markdown(f'#### Temuan · {period}')
    st.caption(f'Periode {period} · satu temuan utama per nasabah; seluruh alarm tersedia di detail.')
    events = ['Semua'] + sorted(alarms.event_type.unique())
    event = st.selectbox('Jenis temuan', events, format_func=lambda x: ui.EVENT_STYLE.get(x, ('', '', x, ''))[2], key='ov_event')
    findings = alarms if event == 'Semua' else alarms[alarms.event_type == event]
    for r in findings.drop_duplicates('company_id').head(4).itertuples():
        a, b = st.columns([4, 1])
        a.markdown(f"{ui.event_badge(r.event_type)} **{ui.esc(store.co.name.get(r.company_id, r.company_id))}**", unsafe_allow_html=True)
        a.caption(f'{r.company_id} · {period}')
        a.write(str(r.reason) if pd.notna(r.reason) else 'Detail insight belum tersedia.')
        a.caption('Aksi: ' + ACTION.get(r.event_type, 'Konfirmasi temuan bersama nasabah.'))
        if b.button('Profil', key=f'ov_alarm_{r.company_id}'):
            state.focus_company(r.company_id)
    if findings.empty:
        st.info('Tidak ada temuan untuk cakupan dan jenis ini.')
    with st.expander('Lihat seluruh alarm'):
        details = findings[['company_id', 'event_type', 'reason', 'score']].copy()
        details.insert(1, 'nama', details.company_id.map(store.co.name))
        st.dataframe(details, hide_index=True, use_container_width=True,
                     column_config={'company_id': 'ID', 'nama': 'Nasabah', 'event_type': 'Temuan', 'reason': 'Insight', 'score': 'Skor alarm'})

with right, st.container(border=True):
    st.markdown('#### Tindak lanjut jatuh tempo')
    st.caption('Tanggal operasional · keterlambatan dan tenggat 7 hari ke depan')
    for r in urgent.sort_values('sisa_hari').head(3).itertuples():
        st.markdown(f'**{ui.esc(store.co.name.get(r.company_id, r.company_id))}**', unsafe_allow_html=True)
        st.write(r.judul)
        st.caption(f"{r.aksi or 'Konfirmasi tahap berikutnya'} · " +
                   (f'terlambat {abs(int(r.sisa_hari))} hari' if r.sisa_hari < 0 else f'tenggat {r.tenggat}'))
    for r in due.head(3).itertuples():
        a, b = st.columns([4, 1])
        name = store.co.name.get(r.party_id, r.party_id)
        a.markdown(f'**{ui.esc(name) if pd.notna(name) else r.party_id}**', unsafe_allow_html=True)
        a.caption(f'{r.product_id} · konfirmasi minat dan sepakati langkah berikutnya')
        a.caption(f'Tenggat {r.jatuh_tempo:%d/%m/%Y} · ' +
                  (f'terlambat {r.telat_hari} hari' if r.telat_hari > 0 else 'jatuh tempo dalam 7 hari'))
        if b.button('Profil', key=f'ov_due_{r.party_id}'):
            state.focus_company(r.party_id)
    if due.empty and urgent.empty:
        st.success('Tidak ada tindak lanjut jatuh tempo dalam 7 hari.')
    if st.button('Buka tindak lanjut', key='ov_followup'):
        ss.tl_tab = 'Progress kegiatan'; state.go('tindak')

st.subheader('Peluang Nasabah')
with st.container(border=True):
    chart, detail = st.columns([1.4, 1])
    with chart:
        st.markdown('#### Peta peluang portofolio')
        st.caption('Klik titik untuk memilih nasabah. Warna menunjukkan segmen; bentuk titik menunjukkan kelas risiko.')
        if not pf.empty:
            plot = pf.join(co[['gap_bn', 'pred_class']]).reset_index()
            plot = plot.rename(columns={plot.columns[0]: 'company_id'})
            plot['skor'] = plot.opportunity_score * 100
            plot['risiko'] = plot.pred_class.fillna('Belum tersedia')
            fig = px.scatter(plot, x='gap_bn', y='skor', color='segment', symbol='risiko', hover_name='name',
                             custom_data=['company_id'], hover_data={'gap_bn': ':.1f', 'skor': ':.0f', 'company_id': True},
                             color_discrete_map=ui.SEG_COLOR, category_orders={'segment': data.SEGS},
                             symbol_map={'Low': 'circle', 'Medium': 'diamond', 'High': 'x', 'Belum tersedia': 'square'},
                             labels={'gap_bn': 'Estimasi omzet belum lewat BNI (Rp miliar)', 'skor': 'Skor peluang', 'risiko': 'Risiko', 'segment': 'Segmen'})
            fig.update_traces(marker_size=12)
            viz._layout(fig, 340, legend=True)
            fig.add_hline(y=75, line_dash='dot', line_color=ui.INK2)
            selection = st.plotly_chart(fig, use_container_width=True, key=f'ov_opportunities_{rm}', on_select='rerun', selection_mode='points')
            points = selection['selection']['points']
            picked = points[-1]['customdata'][0] if points and points[-1].get('customdata') else None
        else:
            picked = None
            st.info('Tidak ada skor peluang dalam cakupan ini.')
    with detail:
        st.markdown('#### Perlu Dihubungi')
        if picked in pf.index:
            r = pf.loc[picked]
            st.markdown(f"**{ui.esc(r['name'])}**", unsafe_allow_html=True)
            purpose, _ = agent._purpose(store, picked, r.to_dict())
            st.write(purpose)
            state.company_actions(store, picked, 'ov_selected', sumber='Overview · Peluang')
            st.divider()
        for cid, r in fresh.head(3).iterrows():
            st.markdown(f"**{ui.esc(r['name'])}**", unsafe_allow_html=True)
            st.caption(f'{cid} · skor {r.opportunity_score * 100:.0f} · {r.recommended_products}')
            purpose, _ = agent._purpose(store, cid, r.to_dict())
            st.write(purpose)
            a, b = st.columns(2)
            if a.button('Profil', key=f'ov_fresh_{cid}', use_container_width=True):
                state.focus_company(cid)
            if b.button('Jadwalkan', key=f'ov_schedule_{cid}', use_container_width=True):
                state.schedule_visit(store, cid, purpose, 'Overview · Peluang')
        if fresh.empty:
            st.caption('Semua prioritas sudah dihubungi atau dijadwalkan.')

st.subheader('Progress & Jadwal')
progress, schedule = st.columns(2)
with progress, st.container(border=True):
    st.markdown('#### Progress Tindak Lanjut')
    st.caption('Status seluruh kegiatan aktif · tenggat mengikuti tanggal operasional')
    if active.empty:
        st.info('Belum ada kegiatan tindak lanjut. Tambahkan melalui feedback kunjungan.')
    else:
        labels = {'berjalan': 'Berjalan', 'terlambat': 'Terlambat', 'selesai': 'Selesai'}
        counts = active.status_tampil.map(labels).value_counts().rename_axis('Status').reset_index(name='Kegiatan')
        fig = px.pie(counts, names='Status', values='Kegiatan', hole=0.65, color='Status',
                     color_discrete_map={'Berjalan': ui.NAVY2, 'Terlambat': '#9A2416', 'Selesai': '#17613F'})
        viz._layout(fig, 260, legend=True)
        fig.update_traces(textinfo='label+value', hovertemplate='%{label}: %{value} kegiatan (%{percent})<extra></extra>')
        st.plotly_chart(fig, use_container_width=True, key='ov_progress')
        completed = int((active.status_tampil == 'selesai').sum())
        st.progress(completed / len(active), text=f'{completed} dari {len(active)} tahap selesai')
        status = st.selectbox('Tampilkan tahap', ['Semua', 'Terlambat', 'Berjalan', 'Selesai'], key='ov_status')
        rows = active if status == 'Semua' else active[active.status_tampil.map(labels) == status]
        table = rows[['company_id', 'judul', 'aksi', 'tenggat', 'status_tampil']].copy()
        table['company_id'] = table.company_id.map(store.co.name).fillna(table.company_id)
        table['status_tampil'] = table.status_tampil.map(labels)
        st.dataframe(table, hide_index=True, use_container_width=True,
                     column_config={'company_id': 'Nasabah', 'judul': 'Tahap', 'aksi': 'Aksi berikutnya', 'tenggat': 'Tenggat', 'status_tampil': 'Status'})
    if st.button('Kelola progress', key='ov_manage_progress'):
        ss.tl_tab = 'Progress kegiatan'; state.go('tindak')

with schedule, st.container(border=True):
    st.markdown('#### Agenda Minggu Ini')
    st.caption(f'Senin–Minggu · {week_start:%d/%m/%Y}–{(week_end - pd.Timedelta(days=1)):%d/%m/%Y}')
    if agenda.empty:
        st.info('Belum ada agenda terjadwal minggu ini.')
    else:
        channel_colors = {'Kunjungan': ('#E7EDF8', '#1E3A6E'), 'Telepon': ('#E4F1EA', '#17613F'),
                          'Email': ('#FBEFD6', '#7A4E00'), 'Rapat internal': ('#EDE9F6', '#4C3A86')}
        for r in agenda.itertuples():
            a, b = st.columns([4, 1])
            bg, fg = channel_colors.get(r.kanal, ('#EEF0F3', '#374151'))
            a.markdown(f"<span style='display:inline-block;padding:3px 10px;border-radius:12px;"
                       f"background:{bg};color:{fg};font-size:12px;font-weight:600'>{ui.esc(r.kanal)}</span>", unsafe_allow_html=True)
            a.markdown(f'**{ui.esc(r.judul)}**', unsafe_allow_html=True)
            a.caption(state.when(r.mulai))
            if b.button('Buka', key=f'ov_agenda_{r.id}'):
                state.open_calendar(r.id, r.mulai)
            st.divider()
    if st.button('Buka kalender', key='ov_calendar'):
        state.open_calendar()

if st.button('Susun rencana aksi', type='primary', key='ov_plan'):
    ss.copilot_task = 'plan'
    state.go('copilot')

with st.expander('Analisis portofolio: produk, segmen, dan industri'):
    st.caption(f'Cakupan {rm} · data {period}')
    a, b = st.columns(2)
    clients = co[co.is_client]
    with a:
        st.markdown('**Peluang produk pada nasabah**')
        products = store.prod[store.prod.company_id.isin(clients.index) & (store.prod.need_score >= 0.5) & ~store.prod.ditunda_risiko]
        if products.empty:
            st.caption('Belum ada celah produk yang memenuhi kriteria.')
        else:
            gaps = products.groupby('product_id').company_id.nunique().sort_values(ascending=False)
            master = data.read_optional('data/raw/product_master.csv')
            names = master.set_index('product_id').product_name if master is not None else pd.Series(dtype=str)
            for start in range(0, len(gaps), 2):
                cards = st.columns(2)
                for card, (pid, count) in zip(cards, gaps.iloc[start:start + 2].items()):
                    ui.kpi(card, f'{pid} · {names.get(pid, pid)}', f'{count} nasabah',
                           f'{count / max(len(clients), 1):.0%} dari portofolio nasabah', color=ui.NAVY2)
            st.caption('Jumlah nasabah dengan celah produk; produk yang ditunda karena risiko dikecualikan.')
    with b:
        st.markdown('**Komposisi portofolio**')
        dim = st.radio('Kelompokkan berdasarkan', ['Segmen', 'Industri'], horizontal=True, key='ov_composition')
        counts = co.groupby('segment' if dim == 'Segmen' else 'industry').size().sort_values(ascending=False)
        if counts.empty:
            st.caption('Belum ada perusahaan dalam cakupan ini.')
        elif dim == 'Segmen':
            composition = counts.rename_axis('Segmen').reset_index(name='Perusahaan')
            fig = px.pie(composition, names='Segmen', values='Perusahaan', color='Segmen',
                         color_discrete_map=ui.SEG_COLOR, category_orders={'Segmen': data.SEGS})
            fig.update_traces(textinfo='label+percent',
                              hovertemplate='%{label}: %{value} perusahaan (%{percent})<extra></extra>')
            viz._layout(fig, 340, legend=True)
            st.plotly_chart(fig, use_container_width=True, key='ov_segment_pie')
            st.caption('Warna segmen sama dengan titik pada Peta peluang portofolio.')
        else:
            st.plotly_chart(viz.hbar(counts.index, counts.values, h=260), use_container_width=True, key='ov_industry_chart')
    if st.button('Jelajahi Potensi Wilayah', key='ov_region'):
        state.go('wilayah')

if co.empty:
    st.info('Tidak ada perusahaan yang sesuai filter. Ubah filter untuk melihat portofolio.')
