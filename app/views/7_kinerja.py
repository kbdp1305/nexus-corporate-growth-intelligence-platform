from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from egi import data, performance as P, state, tindak as T, ui, viz

store = data.get_store()
ss = st.session_state
ui.page_header(f'{ss.rm} · aktivitas, hasil tercatat, dan progres tindak lanjut', 'Kinerja Saya')
if ss.rm == 'Semua RM':
    st.info('Pilih satu RM di sidebar untuk melihat kinerja.')
    st.stop()

history = P.contacts(store.log_all, ss.rm)
latest = history.tanggal.max() if len(history) else data.SNAPSHOT
months = pd.period_range(min(history.tanggal.min(), data.SNAPSHOT) if len(history) else data.SNAPSHOT,
                         max(latest, pd.Timestamp(date.today())), freq='M')[::-1]
labels = {str(m): f'{ui.BULAN[m.month - 1]} {m.year}' for m in months}
a, b = st.columns([1, 2])
mode = a.selectbox('Periode', ['Bulanan', 'Rentang tanggal'], key='perf_period')
if mode == 'Bulanan':
    month = b.selectbox('Bulan', list(labels), index=list(labels).index(str(latest.to_period('M'))),
                        format_func=labels.get, key='perf_month')
    period = pd.Period(month, 'M')
    start, end = period.start_time.normalize(), period.end_time.normalize()
    previous = period - 1
    prev_start, prev_end = previous.start_time.normalize(), previous.end_time.normalize()
else:
    dates = b.date_input('Rentang tanggal', value=(latest.replace(day=1).date(), latest.date()),
                         key='perf_dates', format='DD/MM/YYYY')
    if len(dates) != 2:
        st.info('Pilih tanggal awal dan akhir.')
        st.stop()
    start, end = map(pd.Timestamp, dates)
    span = end - start + pd.Timedelta(days=1)
    prev_end, prev_start = start - pd.Timedelta(days=1), start - span

st.caption(f'Periode {ui.tanggal(start)} – {ui.tanggal(end)} · '
           f'Kontak terakhir tercatat: {ui.tanggal(latest) if len(history) else "belum ada"}. '
           'Data sintetis Jan–Jun 2026 dan catatan yang ditambahkan melalui dashboard.')
selected = P.between(history, start, end)
current, before = P.metrics(history, start, end), P.metrics(history, prev_start, prev_end)
cols = st.columns(4)
cards = [('Perusahaan Dihubungi', 'companies'), ('Aktivitas Kontak', 'contacts'),
         ('Konversi Tercatat', 'conversions'), ('Nilai Deal Tercatat', 'deal_bn')]
for col, (label, key) in zip(cols, cards):
    money = key == 'deal_bn'
    value = f'Rp {ui.fmt(current[key], 2)} miliar' if money else ui.fmt(current[key], 0)
    diff = current[key] - before[key]
    delta = ('+' if diff > 0 else '') + ui.fmt(diff, 2 if money else 0)
    ui.kpi(col, label, value, f'{delta}{" miliar" if money else ""} dibanding periode sebelumnya')
with st.expander('Definisi metrik dan kelengkapan data'):
    st.markdown('**Perusahaan Dihubungi:** perusahaan unik dengan kontak pada periode terpilih. '
                '**Aktivitas Kontak:** jumlah catatan kontak, termasuk kontak berulang. '
                '**Konversi Tercatat:** pasangan perusahaan–produk yang pertama kali dicatat '
                'sebagai Converted pada periode terpilih; status ini berarti setuju/onboarding, '
                'belum merupakan bukti realisasi bisnis. '
                '**Nilai Deal Tercatat:** penjumlahan nilai deal pada catatan kontak dalam periode, '
                'bukan pendapatan bank dan belum direkonsiliasi terhadap transaksi aktual.')
    st.caption(f'Pembanding: {ui.tanggal(prev_start)} – {ui.tanggal(prev_end)}. '
               'Catatan dari dashboard belum menyediakan nilai deal; nilai nol tidak memastikan tidak ada deal.')
    st.caption(f'{int(selected.sumber.eq("dashboard").sum())} dari {len(selected)} kontak periode ini berasal dari dashboard. '
               'Rasio konversi peluang belum ditampilkan karena siklus peluang belum dicatat secara konsisten.')

st.subheader(f'Komposisi Hasil Kontak · {labels[month]}' if mode == 'Bulanan' else 'Komposisi Hasil Kontak Periode Terpilih')
st.caption('Setiap irisan menunjukkan hasil catatan kontak pada periode terpilih. '
           'Kontak berulang ikut dihitung; persentase ini bukan tingkat konversi perusahaan atau peluang.')
status_labels = {'Converted': 'Setuju / onboarding', 'Interested': 'Tertarik',
                 'Not interested': 'Tidak tertarik', 'No response': 'Tidak ada respons'}
status_colors = {'Setuju / onboarding': '#16A34A', 'Tertarik': '#2563EB',
                 'Tidak tertarik': '#F59E0B', 'Tidak ada respons': '#94A3B8',
                 'Status belum tersedia': '#CBD5E1'}
if selected.empty:
    st.info('Belum ada catatan kontak pada periode ini. Angka nol menunjukkan tidak ada catatan yang tersedia.')
else:
    outcomes = selected.response.map(status_labels).fillna('Status belum tersedia')
    counts = outcomes.value_counts().reindex(list(status_colors), fill_value=0)
    counts = counts[counts > 0]
    fig = go.Figure(go.Pie(
        labels=counts.index.tolist(), values=counts.tolist(), hole=.68, sort=False,
        marker=dict(colors=[status_colors[label] for label in counts.index],
                    line=dict(color='white', width=2)),
        textinfo='percent', textposition='inside',
        hovertemplate='%{label}<br>%{value} kontak ? %{percent}<extra></extra>',
    ))
    fig = viz._layout(fig, 360, legend=True)
    fig.update_layout(legend=dict(orientation='h', x=.5, xanchor='center', y=-.08, yanchor='top'))
    fig.add_annotation(x=.5, y=.5, xref='paper', yref='paper', showarrow=False,
                       text=f'<b>{ui.fmt(len(selected), 0)}</b><br>Total kontak',
                       font=dict(size=20, color=ui.NAVY2))
    fig.update_layout(margin=dict(l=15, r=15, t=15, b=65))
    st.plotly_chart(fig, use_container_width=True, key='perf_outcomes')

with st.expander('Lihat tren aktivitas dan hasil tercatat'):
    # Satu bulan menggunakan kelompok mingguan, rentang lebih panjang per bulan.
    frequency = 'W-SUN' if start.to_period('M') == end.to_period('M') else 'M'
    periods = pd.period_range(start, end, freq=frequency)
    labels_trend = []
    for period in periods:
        if frequency == 'W-SUN':
            first = max(period.start_time.normalize(), start)
            last = min(period.end_time.normalize(), end)
            days = str(first.day) if first == last else f'{first.day}–{last.day}'
            labels_trend.append(f'{days}<br>{state.BULAN[first.month - 1]} {first.year}')
        else:
            labels_trend.append(f'{state.BULAN[period.month - 1]}<br>{period.year}')
    contacts_trend = selected.groupby(selected.tanggal.dt.to_period(frequency)).size().reindex(periods, fill_value=0)
    wins = P.between(P.first_conversions(history), start, end)
    wins_trend = wins.groupby(wins.tanggal.dt.to_period(frequency)).size().reindex(periods, fill_value=0)
    for values, name, color in [(contacts_trend, 'Aktivitas kontak', ui.NAVY2),
                                (wins_trend, 'Konversi tercatat', ui.ORANGE)]:
        trend = go.Figure(go.Scatter(x=list(range(len(periods))), y=values, mode='lines+markers',
                                     name=name, line=dict(color=color),
                                     customdata=[label.replace('<br>', ' ') for label in labels_trend],
                                     hovertemplate='%{customdata}<br>' + name + ': %{y}<extra></extra>'))
        trend = viz._layout(trend, 260, title=name)
        tick_step = max(1, (len(periods) + 11) // 12)
        ticks = list(range(0, len(periods), tick_step))
        if ticks[-1] != len(periods) - 1:
            ticks.append(len(periods) - 1)
        trend.update_xaxes(tickmode='array', tickvals=ticks,
                           ticktext=[labels_trend[i] for i in ticks], tickangle=0,
                           title_text='Minggu' if frequency == 'W-SUN' else 'Bulan', automargin=True)
        trend.update_yaxes(title_text='Jumlah kontak' if name == 'Aktivitas kontak' else 'Jumlah konversi',
                           rangemode='tozero', tickformat=',d')
        trend.update_layout(margin=dict(l=45, r=15, t=45, b=75))
        st.plotly_chart(trend, use_container_width=True,
                        key='perf_trend_' + ('contacts' if name == 'Aktivitas kontak' else 'conversions'))
    st.caption('Konversi tercatat dihitung sekali per perusahaan–produk; hasil kontak Converted pada donut dapat mencakup catatan berulang.')

st.subheader('Progres tindak lanjut')
keg = T.kegiatan_for(ss.rm)
created = pd.to_datetime(keg.dibuat_pada, errors='coerce').dt.normalize()
keg = keg[created.between(start, end)]
st.caption('Kegiatan yang dibuat pada periode terpilih, dengan status terkini saat halaman dibuka. '
           'Keterlambatan dihitung terhadap tanggal hari ini; kegiatan dibatalkan dipisahkan.')
progress_cols = st.columns(4)
for col, status, title in zip(progress_cols, ['selesai', 'berjalan', 'terlambat', 'batal'],
                             ['Selesai', 'Berjalan', 'Terlambat', 'Dibatalkan']):
    ui.kpi(col, title, str(int(keg.status_tampil.eq(status).sum())))
if keg.empty:
    st.caption('Belum ada kegiatan tindak lanjut yang dibuat pada periode ini.')
if st.button('Buka Progress Kegiatan', key='perf_progress'):
    ss.tl_tab = 'Progress kegiatan'
    state.go('tindak')

st.subheader('Pipeline yang perlu perhatian')
as_of = min(end, pd.Timestamp(date.today()))
st.caption(f'Peluang berstatus tertarik berdasarkan riwayat sampai {ui.tanggal(as_of)}, '
           'termasuk kontak sebelum periode. Pasangan perusahaan–produk yang pernah Converted dikeluarkan. '
           'Urutan dimulai dari kontak yang paling lama menunggu.')
pipe = P.pipeline(history, as_of)
if pipe.empty:
    st.caption('Tidak ada peluang tertarik yang belum dikonversi dalam catatan sampai akhir periode ini.')
else:
    names = T.products().product_name.to_dict()
    table = pd.DataFrame({
        'Perusahaan': pipe.party_id.map(store.co.name).fillna(pipe.party_id),
        'Produk': pipe.product_id.map(names).fillna(pipe.product_id),
        'Kontak Terakhir': pipe.tanggal.dt.strftime('%d/%m/%Y'),
        'Hari Menunggu': pipe.hari_menunggu,
        'Status': pipe.hari_menunggu.map(lambda days: 'Perlu ditinjau · ≥14 hari' if days >= 14 else 'Tertarik'),
        'Catatan': pipe.feedback_note.fillna(''),
    }).reset_index(drop=True)
    st.dataframe(table, hide_index=True, use_container_width=True,
                 column_config={'Hari Menunggu': st.column_config.NumberColumn(help='Hari sejak kontak terakhir sampai tanggal acuan pipeline yang tercantum di atas.')})
    if st.button('Buka Tindak Lanjut Kunjungan', key='perf_followup'):
        ss.tl_tab = 'Progress kegiatan'
        state.go('tindak')

with st.expander('Analisis tambahan: kanal dan segmen'):
    st.caption('Hasil kontak Converted dibagi jumlah kontak pada kelompok yang sama. '
               'Ini rasio hasil kontak, bukan probabilitas atau rasio konversi peluang; kontak berulang ikut dihitung.')
    def breakdown(frame, column, label):
        grouped = frame.groupby(column, dropna=False).agg(
            Kontak=('party_id', 'size'), Perusahaan=('party_id', 'nunique'),
            Hasil_Converted=('is_conversion', 'sum')).reset_index()
        grouped['Rasio Hasil Kontak'] = grouped.Hasil_Converted / grouped.Kontak * 100
        st.dataframe(grouped.rename(columns={column: label, 'Hasil_Converted': 'Kontak Converted'}),
                     hide_index=True, use_container_width=True,
                     column_config={'Rasio Hasil Kontak': st.column_config.NumberColumn(format='%.1f%%')})
    st.markdown('**Per kanal**')
    breakdown(selected, 'channel', 'Kanal')
    st.markdown('**Per segmen nasabah**')
    clients = selected[selected.party_id.isin(store.cox.index[store.cox.is_client])].join(store.cox.segment, on='party_id')
    breakdown(clients, 'segment', 'Segmen')
    st.caption('Prospect tidak dikelompokkan berdasarkan segmen.')
