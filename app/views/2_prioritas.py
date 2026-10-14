import hashlib

import pandas as pd
import streamlit as st

from egi import agent, auth, data, llm, profile_workspace as PW, sim, state, ui, viz
from egi import kalender as K

store = data.get_store()
ss = st.session_state
user = auth.current()
if not user or user['role'] not in ('rm', 'supervisor'):
    st.stop()
if user['role'] == 'rm':
    ss.rm = user['rm_id']
rm = ss.rm
catalog = sim.catalog()
claims = K.claims()
scheduled = K.scheduled_ids(rm)
contacted = store.contacted(rm)

ui.page_header(f'{rm} · Data per {data.SNAPSHOT:%d/%m/%Y} · prioritas dibandingkan dalam segmen yang sama', 'Daftar Prioritas')
requested = ss.pop('priority_requested', None)
if requested:
    ss.priority_mode = 'Prospect'
    ss.priority_status = 'Semua'
    ss.priority_risk = 'Semua'
    ss.priority_district = []
    ss.priority_hide_other = False
    ss.priority_focus = requested
    ss.priority_request_version = ss.get('priority_request_version', 0) + 1
mode = st.segmented_control('Tampilkan', ['Nasabah', 'Prospect'], default='Nasabah', key='priority_mode') or 'Nasabah'
prospect = mode == 'Prospect'

if prospect:
    frame = store.acq.join(store.cox[['name', 'district', 'industry']]).copy()
    net = store.prospects_for(rm)
    allowed = set(frame.index) if rm == 'Semua RM' else set(net.index) | {cid for cid, owner in claims.items() if owner == rm}
    frame = frame[frame.index.isin(allowed)].copy()
    frame['lewat_nama'] = net.get('lewat_nama', pd.Series(dtype=str)).reindex(frame.index).fillna('Belum ada jalur langsung')
    frame['nilai_M'] = net.get('nilai_M', pd.Series(dtype=float)).reindex(frame.index).fillna(0)
    frame['penghubung'] = net.get('lewat', pd.Series(dtype=object)).map(len).reindex(frame.index).fillna(0).astype(int)
    frame['pemegang'] = pd.Series(claims, dtype=str).reindex(frame.index).fillna('')
    frame['contacted'] = frame.index.isin(contacted)
    frame['why_up'] = False
    score_col = 'acquisition_score'
else:
    frame = agent.candidates(store, rm).copy()
    score_col = 'opportunity_score'

if frame.empty:
    for column in ['name', 'district', 'segment', 'contacted', 'why_up', 'risk_class', score_col,
                   'recommended_products', 'prio', 'ev_idr_mn']:
        if column not in frame:
            frame[column] = pd.Series(dtype=bool if column in ('contacted', 'why_up') else object)

frame['status'] = ['Sudah Terjadwal' if cid in scheduled else 'Sudah Dihubungi' if hit else 'Belum Dihubungi'
                   for cid, hit in zip(frame.index, frame.contacted)]
frame['score'] = frame[score_col] * 100
frame['name'] = frame['name'].fillna(pd.Series(frame.index, index=frame.index))

if prospect:
    f2, f3, f4 = st.columns(3)
else:
    f1, f2, f3, f4 = st.columns(4)
segment = 'Semua prospect' if prospect else f1.selectbox('Segmen', data.SEGS, key='priority_segment')
status = f2.selectbox('Status hubungan', ['Semua', 'Belum Dihubungi', 'Sudah Dihubungi', 'Sudah Terjadwal'], key='priority_status')
risk = f3.selectbox('Risiko', ['Semua', 'Low', 'Medium', 'High'], key='priority_risk')
if prospect:
    sort_options = ['Nilai relasi', 'Jumlah nasabah penghubung', 'Skor akuisisi']
    product = None
    sort = f4.selectbox('Urutkan', sort_options, key='priority_prospect_sort')
    st.caption('Urutan default memakai nilai relasi aktif dengan nasabah BNI yang teramati dalam data. Skor akuisisi tersedia sebagai informasi tambahan prototipe.')
else:
    products = sorted({p.strip() for value in frame.recommended_products.dropna() for p in str(value).split(',') if p.strip()})
    product = f4.selectbox('Peluang produk', ['Semua'] + products, key='priority_product',
                           format_func=lambda pid: catalog.product_name.get(pid, pid))
    sort = st.segmented_control('Urutkan', ['Prioritas aksi', 'Skor peluang', 'Estimasi nilai'], default='Prioritas aksi', key='priority_sort') or 'Prioritas aksi'
    st.caption('Prioritas aksi = skor peluang + bonus momentum + bonus belum dihubungi. Urutan aksi berbeda dari peringkat model per segmen.')

with st.expander('Filter tambahan & pendekatan' if prospect else 'Filter tambahan & pendekatan segmen'):
    a, b = st.columns(2)
    district = a.multiselect('Kecamatan', sorted(frame.district.dropna().unique()),
                             default=[ss.focus_district] if ss.focus_district in set(frame.district) else [], key='priority_district')
    if prospect:
        hide_other = b.checkbox('Sembunyikan prospect milik RM lain', value=True, disabled=user['role'] == 'supervisor', key='priority_hide_other')
        momentum = False
    else:
        momentum = b.checkbox('Hanya Momentum Peluang', key='priority_momentum', help='Ekspansi atau erosi wallet dalam 3 bulan data terakhir.')
        hide_other = False
    approaches = {'S1 Kecil': 'Mulai dengan telepon atau email dan solusi transaksi standar.',
                  'S2 Menengah': 'Pilih kanal sesuai peluang produk dan kebutuhan nasabah.',
                  'S3 Besar': 'Siapkan solusi ekosistem dan libatkan analis untuk pembiayaan.'}
    if not prospect:
        st.caption(approaches[segment])
    if prospect:
        st.caption('Utamakan perkenalan lewat nasabah anchor. Prospect yang dipegang RM lain membutuhkan koordinasi sebelum dijadwalkan.')

view = frame.copy() if prospect else frame[frame.segment == segment].copy()
if status != 'Semua': view = view[view.status == status]
if risk != 'Semua': view = view[view.risk_class == risk]
if district: view = view[view.district.isin(district)]
if momentum: view = view[view.why_up]
if product and product != 'Semua':
    view = view[view.recommended_products.fillna('').map(lambda value: product in [p.strip() for p in str(value).split(',')])]
if prospect and hide_other and user['role'] == 'rm':
    view = view[(view.pemegang == '') | (view.pemegang == rm)]
sort_col = ({'Skor akuisisi': 'acquisition_score', 'Nilai relasi': 'nilai_M', 'Jumlah nasabah penghubung': 'penghubung'} if prospect else
            {'Prioritas aksi': 'prio', 'Skor peluang': 'opportunity_score', 'Estimasi nilai': 'ev_idr_mn'})[sort]
sort_columns = ([sort_col, 'penghubung' if sort_col == 'nilai_M' else 'nilai_M'] if prospect and sort != 'Skor akuisisi' else
                [sort_col, score_col] if sort_col != score_col else [sort_col])
view = view.sort_values(sort_columns, ascending=False, kind='stable')

st.caption(f'{len(view)} hasil sesuai filter · {segment} · {len(frame)} perusahaan dalam cakupan {rm}')
k = st.columns(4)
ui.kpi(k[0], 'Hasil sesuai filter', str(len(view)), segment)
ui.kpi(k[1], 'Belum Dihubungi', str(int((view.status == 'Belum Dihubungi').sum())), 'Dari hasil filter')
ui.kpi(k[2], 'Sudah Terjadwal', str(int((view.status == 'Sudah Terjadwal').sum())), 'Dari hasil filter')
if prospect:
    ui.kpi(k[3], 'Belum diklaim', str(int((view.pemegang == '').sum())), 'Dari hasil filter')
else:
    ui.kpi(k[3], 'Estimasi nilai Top-10', f'Rp {ui.fmt(view.head(10).ev_idr_mn.sum(), 1)} jt', '10 teratas sesuai urutan aktif · asumsi 1 tahun')

table, detail = st.columns([1.85, 1])
cid = None
with table:
    st.markdown('#### Antrean Prioritas')
    st.caption('Klik baris untuk membuka detail di kanan. Skor 0–100; peringkat model hanya dibandingkan dalam segmen.')
    if view.empty:
        st.info('Tidak ada perusahaan yang sesuai filter. Ubah segmen atau filter lainnya.')
    else:
        display = view[['name', 'risk_class', 'status'] if prospect else ['name', 'score', 'risk_class', 'status']].copy()
        display.insert(0, 'urutan', range(1, len(display) + 1))
        if not prospect:
            display['probabilitas_konversi'] = view.p_convert * 100
        if prospect:
            if sort == 'Skor akuisisi':
                display['score'] = view.score
            display['pemegang'] = view.pemegang.replace('', 'Belum diklaim')
            display['jalur_masuk'] = view.lewat_nama
            display['nilai_relasi'] = view.nilai_M
            display['penghubung'] = view.penghubung
        else:
            display['produk'] = view.recommended_products.fillna('').map(
                lambda value: ', '.join(catalog.product_name.get(p.strip(), p.strip()) for p in str(value).split(',') if p.strip()))
            display['temuan'] = ['Alarm risiko' if caution else 'Momentum Peluang' if up else '—'
                                  for caution, up in zip(view.caution, view.why_up)]
        display.index.name = 'company_id'
        display = display.reset_index()
        def cell_color(value):
            colors = {'High': ('#FADFDB', '#9A2416'), 'Medium': ('#FBEFD6', '#7A4E00'), 'Low': ('#E4F1EA', '#17613F'),
                      'Belum Dihubungi': ('#FBEFD6', '#7A4E00'), 'Sudah Dihubungi': ('#EEF0F3', '#374151'),
                      'Sudah Terjadwal': ('#E7EDF8', ui.NAVY2)}
            bg, fg = colors.get(value, ('white', ui.INK))
            return f'background-color: {bg}; color: {fg}'
        styled = display.style.map(cell_color, subset=['risk_class', 'status'])
        # Changing the ordered IDs creates a fresh selection, avoiding stale row indices after filtering/sorting.
        signature = hashlib.sha1((rm + mode + sort + str(ss.get('priority_request_version', 0)) + '|'.join(view.index)).encode()).hexdigest()[:12]
        selected = st.dataframe(styled, hide_index=True, use_container_width=True, height=490,
                                on_select='rerun', selection_mode='single-row', key=f'priority_table_{signature}',
                                column_config={'company_id': None, 'urutan': 'Urutan',
                                               'name': 'Perusahaan', 'score': st.column_config.ProgressColumn('Skor prioritas', min_value=0, max_value=100, format='%.1f',
                                                   help='Posisi relatif dalam segmen, bukan probabilitas konversi. Skor 100 menunjukkan posisi tertinggi dalam segmen.'),
                                               'probabilitas_konversi': st.column_config.NumberColumn('Probabilitas konversi', format='%.1f%%',
                                                   help='Estimasi model untuk produk rekomendasi teratas. Bukan kepastian nasabah akan setuju. Belum tersedia untuk prospect.'),
                                               'jalur_masuk': 'Nasabah penghubung', 'penghubung': 'Jumlah penghubung',
                                               'nilai_relasi': st.column_config.NumberColumn('Relasi (Rp M/tahun)', format='%.1f',
                                                   help='Nilai relasi tahunan yang tercatat dengan nasabah BNI dalam cakupan ini; bukan omzet prospect.'),
                                               'risk_class': 'Risiko', 'status': 'Hubungan', 'produk': 'Peluang produk', 'temuan': 'Temuan', 'pemegang': 'Pemegang'})
        rows = selected['selection']['rows']
        if rows and 0 <= rows[0] < len(view):
            cid = view.index[rows[0]]
            if prospect:
                ss.priority_focus = cid
        elif prospect and ss.get('priority_focus') in view.index:
            cid = ss.priority_focus

with detail, st.container(border=True):
    st.markdown('#### Prospect Terpilih' if prospect else '#### Nasabah Terpilih')
    if cid is None:
        st.caption('Pilih satu perusahaan dari tabel untuk melihat alasan prioritas, konteks hubungan, dan tindakan.')
    else:
        row = view.loc[cid]
        st.markdown(f"**{ui.esc(row['name'])}**", unsafe_allow_html=True)
        st.caption(f'{cid} · {row.industry} · {row.district}')
        bg, fg = {'Belum Dihubungi': ('#FBEFD6', '#7A4E00'), 'Sudah Dihubungi': ('#EEF0F3', '#374151'),
                  'Sudah Terjadwal': ('#E7EDF8', ui.NAVY2)}[row.status]
        st.markdown(ui.risk_badge(row.risk_class) + ui.badge(row.status, bg, fg), unsafe_allow_html=True)
        st.caption(f'Skor prioritas {ui.fmt(row.score, 1)}/100 · peringkat model {int(row.rank_in_segment)} di {row.segment}')
        if row.risk_class == 'High': st.warning('Produk kredit ditunda. Fokus pada produk non-kredit dan konfirmasi kondisi nasabah.')
        elif row.risk_class == 'Medium': st.caption('Rekomendasi kredit memakai penyesuaian risiko Medium.')
        if prospect:
            why = f'{int(row.penghubung)} nasabah penghubung dalam cakupan Anda, dengan nilai relasi tercatat Rp {ui.fmt(row.nilai_M, 1)} miliar per tahun.'
            purpose = f'Perkenalan dan konfirmasi kebutuhan transaksi {row["name"]}.'
        else:
            why = str(row.reason)
            purpose, _ = agent._purpose(store, cid, row.to_dict())
        ui.ai_box('Alasan Prioritas', why)
        if prospect:
            paths = store.intro_paths(cid, rm if rm != 'Semua RM' else '')
            if not paths.empty:
                st.markdown('#### Jalur Masuk Terbaik')
                labels = [f"{path['name']} · {path.jenis} · RM {path.rm_id}" for _, path in paths.iterrows()]
                chosen = st.selectbox('Nasabah penghubung untuk perkenalan', range(len(paths)),
                                      format_func=lambda i: labels[i], key=f'priority_path_{cid}')
                best = paths.iloc[chosen]
                st.caption(f'{best.arah} · Rp {ui.fmt(best.nilai_M, 1)} miliar/tahun')
                if best.milik_saya:
                    st.success('Jalur melalui nasabah Anda sendiri. Konfirmasi kesediaan PIC untuk memperkenalkan.')
                elif rm != 'Semua RM':
                    st.info(f'Nasabah penghubung ditangani {best.rm_id}. Koordinasikan perkenalan dengan RM tersebut.')
                with st.expander('Seluruh jalur alternatif'):
                    st.dataframe(paths[['name', 'rm_id', 'jenis', 'arah', 'nilai_M', 'milik_saya']], hide_index=True,
                                 use_container_width=True, column_config={'name': 'Nasabah penghubung', 'rm_id': 'RM',
                                     'jenis': 'Hubungan bisnis', 'arah': 'Arah relasi', 'nilai_M': 'Rp miliar/tahun', 'milik_saya': 'Nasabah saya'})
                if st.button('Buat Draf Permintaan Perkenalan', key=f'priority_intro_{cid}', use_container_width=True):
                    message, source = llm.draft_message('intro', {'perantara': best['name'], 'prospect': row['name']})
                    ss.priority_intro_draft = {'cid': cid, 'path': best.id, 'name': best['name'], 'message': message, 'mode': source}
                draft = ss.get('priority_intro_draft')
                if draft and draft['cid'] == cid and draft['path'] == best.id:
                    text = st.text_area('Draf pesan — edit sebelum dikirim', draft['message'], height=170,
                                        key=f'priority_intro_text_{cid}_{best.id}_{draft["message"][:20]}')
                    if st.button('Setujui Draf', key=f'priority_approve_{cid}'):
                        data.audit('setujui_pesan_intro', prospect=cid, perantara=best['name'], rm=rm, isi=text)
                        st.success('Draf disetujui. Kirim melalui kanal komunikasi Anda.')
            else:
                st.caption('Belum ada nasabah penghubung yang tercatat. Konfirmasi jalur masuk sebelum menghubungi prospect.')
            st.caption('Skor akuisisi bersifat deskriptif; belum tervalidasi dengan data konversi prospect.')
        else:
            st.write(purpose)
            st.metric('Probabilitas konversi', ui.fmt(row.p_convert * 100, 1, pct=True),
                      help='Estimasi model untuk produk rekomendasi teratas; bukan skor prioritas atau kepastian konversi.')
            st.caption(f'Estimasi nilai bersih Rp {ui.fmt(row.ev_idr_mn, 1)} jt')
            for event in str(row.alarm).split(','):
                if event.strip(): st.markdown(ui.event_badge(event.strip()), unsafe_allow_html=True)
        logs, _, upcoming, _ = PW.context(store, cid, user)
        st.divider()
        st.markdown('**Konteks Hubungan**')
        if logs.empty: st.caption('Belum ada kontak tercatat.')
        else:
            last = logs.iloc[0]
            st.caption(f'Kontak terakhir {last.contact_date} · {last.channel} · {last.response}')
        if upcoming.empty: st.caption('Belum ada agenda mendatang.')
        else: st.caption(f'Agenda berikutnya: {state.when(upcoming.iloc[0].mulai)} · {upcoming.iloc[0].kanal}')
        owner = row.pemegang if prospect else rm
        locked = bool(prospect and owner and owner != rm and user['role'] == 'rm')
        if locked: st.info(f'Prospect dipegang {owner}. Koordinasikan dengan RM tersebut atau supervisor.')
        if st.button('Lihat Profil', key=f'priority_profile_{cid}', use_container_width=True): state.focus_company(cid)
        if st.button('Jadwalkan', key=f'priority_schedule_{cid}', disabled=locked, use_container_width=True):
            state.schedule_visit(store, cid, purpose, 'Daftar Prioritas')
        if st.button('Siapkan Bahan Kunjungan', key=f'priority_brief_{cid}', use_container_width=True):
            ss.focus_company = cid; ss.copilot_task = 'brief'; state.go('copilot')
        with st.expander('Rincian skor'):
            keys = {'pct_skala': 'Skala', 'pct_ekosistem': 'Ekosistem', 'pct_jalur_kenalan': 'Jalur kenalan'} if prospect else {
                'pct_dompet_belum_digarap': 'Wallet belum digarap', 'pct_ekosistem': 'Ekosistem', 'pct_kebutuhan_modal': 'Kebutuhan modal',
                'pct_celah_produk': 'Celah produk', 'pct_erosi_wallet': 'Erosi wallet'}
            values = {label: row[key] * 100 for key, label in keys.items() if key in row and pd.notna(row[key])}
            st.plotly_chart(viz.hbar(list(values), list(values.values()), h=220, xmax=115), use_container_width=True)
