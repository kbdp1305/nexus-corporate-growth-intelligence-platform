import numpy as np
import pandas as pd
import plotly.express as px
import streamlit as st

from egi import agent, auth, data, llm, profile_list, profile_workspace as PW, sim, state, tindak, ui, viz
from egi import kalender as K
import reports as R  # noqa: E402  (src/ ditambahkan ke sys.path oleh egi.data)

store = data.get_store(); ss = st.session_state
ss.setdefault('narr', {})
user = auth.current()
if not user or user['role'] not in ('rm', 'supervisor'):
    st.stop()
if user['role'] == 'rm':
    ss.rm = user['rm_id']
allowed = PW.accessible_ids(store, user)

# ------------------------------------------------------------------ pilih perusahaan
mine = list(store.portfolio(ss.rm).sort_values('opportunity_score', ascending=False).index)
mine_set = set(mine)
others = sorted((c for c in allowed if c not in mine_set), key=lambda c: str(store.co.name[c]).casefold())
opts = mine + others

# Only an explicit company selection or a direct company link opens the details.
requested = ss.pop('profile_requested', None)
if requested in store.co.index:
    st.query_params['company'] = requested
cid = st.query_params.get('company')
if cid in store.co.index and cid not in allowed:
    st.warning('Perusahaan ini berada di luar portofolio dan prospect jaringan Anda.')
    st.query_params.pop('company', None)
    cid = None
if cid not in store.co.index:
    st.query_params.pop('company', None)
    profile_list.render(store, mine_set, opts)
    st.stop()

if st.button('← Kembali ke daftar perusahaan', key='profile_back'):
    st.query_params.pop('company', None)
    st.rerun()
ss.focus_company = cid

fp = R.fact_pack(store, cid)
c = store.cox.loc[cid]
catalog = sim.catalog()
logs, calendar, upcoming, activities = PW.context(store, cid, user)
holder, _ = K.holder(K.load(), cid)
can_act = user['role'] == 'supervisor' or holder in (None, user['rm_id'])
narr, mode = ss.narr.get(cid, (None, None))[:2] if cid in ss.narr else (llm.template_company(fp), 'template')

# ------------------------------------------------------------------ kepala
an = fp['anomali']
pl = fp.get('peluang')
ak = fp['arus_kas']
j = fp['jaringan']
title, actions = st.columns([1.8, 1.2], vertical_alignment='center')
with title:
    st.markdown(f"<h1 style='font-size:28px;line-height:1.2;margin:0;padding:0'>{ui.esc(fp['nama'])}</h1>", unsafe_allow_html=True)
    st.caption(f"{cid} · {fp['industri']} · {fp['kecamatan']}, {fp['kota']} · RM {fp['rm'] or '—'} · Data {data.SNAPSHOT:%d/%m/%Y}")
    st.markdown(ui.badge(fp['segmen'] or '—', ui.SEG_COLOR.get(fp['segmen'], '#999'), '#fff')
                + ui.risk_badge(fp['risiko']['kelas']) + ui.badge(fp['tipe'], '#EEF0F3', '#374151'), unsafe_allow_html=True)
with actions:
    b1, b2 = st.columns(2)
    if b1.button('Jadwalkan Kunjungan', type='primary', disabled=not can_act, use_container_width=True):
        state.schedule_visit(store, cid, sumber='Profil')
    if b2.button('Siapkan Bahan Kunjungan', use_container_width=True):
        ss.copilot_task = 'brief'; state.go('copilot')
    cfg = llm.config()
    with st.popover('Tindakan lainnya', use_container_width=True):
        if st.button('Ajukan kunjungan dengan pendampingan', disabled=not can_act, use_container_width=True):
            ss.pj_company = cid; ss.tl_tab = 'Pengajuan kunjungan'; state.go('tindak')
        if st.button('Perbarui ringkasan', disabled=not cfg['enabled'], use_container_width=True):
            with st.spinner('Copilot memperbarui ringkasan…'):
                n2, m2, bad = llm.company_narrative(fp)
            ss.narr[cid] = (n2, m2, bad); narr, mode = n2, m2
            data.audit('narasi_llm', company=cid, rm=ss.rm, mode=m2, bagian_ditolak=[b[0] for b in bad or []])
            if bad:
                st.warning('Beberapa bagian diganti karena memuat angka di luar data.')
        if st.button('Buat PDF ringkasan', use_container_width=True):
            buf, (n, badn) = R.company_summary_pdf(fp, narr, generated_by='Copilot (LLM)' if mode == 'LLM' else 'Copilot (template)')
            ss['pdf_' + cid] = buf.getvalue() if hasattr(buf, 'getvalue') else buf
            data.audit('pdf_ringkasan', company=cid, rm=ss.rm, mode=mode, angka=n, tidak_cocok=len(badn))
        if ss.get('pdf_' + cid):
            st.download_button('Unduh PDF', ss['pdf_' + cid], file_name=f'ringkasan_{cid}.pdf', mime='application/pdf', use_container_width=True)

k = st.columns(4)
score = pl['skor'] if pl else (store.acq.loc[cid, 'acquisition_score'] * 100 if cid in store.acq.index else None)
ui.kpi(k[0], 'Skor prioritas', f'{ui.fmt(score, 1)} / 100' if score is not None else '—',
       f"Peringkat {pl['peringkat']} di segmen" if pl else 'Akuisisi prospect')
k[0].caption('Prioritas relatif dalam segmen, bukan probabilitas konversi.')
ui.kpi(k[1], 'Kelas risiko', fp['risiko']['kelas'], fp['risiko']['keputusan'],
       color=ui.RISK_STYLE.get(fp['risiko']['kelas'], ('', ui.INK, ''))[1])
ui.kpi(k[2], 'Porsi wallet di BNI', ui.fmt(ak['capture_now'] * 100, 0, pct=True), f"{ui.fmt(ak['capture_chg_6m'], 0)} poin dalam 6 bulan")
ui.kpi(k[3], 'Produk aktif', f"{len(fp['produk_dimiliki'])} / {len(catalog)}", 'Produk yang sudah dimiliki')

with st.container(border=True, key='profile_relationship_strip'):
    last, nxt = st.columns(2, vertical_alignment='center')
    if logs.empty:
        last.caption('Kontak terakhir · belum ada kontak tercatat')
    else:
        contact = logs.iloc[0]
        last.markdown(f"**Kontak terakhir** · {ui.esc(contact.contact_date)} · {ui.esc(contact.channel)}")
        last.caption(tindak.HASIL_ID.get(contact.response, contact.response))
    if upcoming.empty:
        nxt.caption('Agenda berikutnya · belum dijadwalkan')
    else:
        visit = upcoming.iloc[0]
        text, button = nxt.columns([4, 1])
        text.markdown(f"**Agenda berikutnya** · {ui.esc(state.when(visit.mulai))}")
        text.caption(f'{visit.kanal} · {visit.judul}')
        if button.button('Buka', key=f'profile_next_{cid}'):
            state.open_calendar(visit.id, visit.mulai)

tabs = st.tabs(['Ringkasan', 'Keuangan', 'Arus Kas & Temuan', 'Jaringan', 'Peluang Produk', 'Riwayat'])

# ------------------------------------------------------------------ 1 ringkasan
with tabs[0]:
    main, next_action = st.columns([1.85, 1])
    with main:
        ui.ai_box('Kondisi Nasabah', narr['ringkasan'], f'Data per {data.SNAPSHOT:%d/%m/%Y}')
        st.markdown('#### Peluang Utama')
        recommendations = [p for p in fp.get('produk', []) if not p['ditunda']][:3]
        if recommendations:
            for p in recommendations:
                with st.container(border=True):
                    st.markdown(f"**{catalog.product_name.get(p['produk'], p['produk'])}** · peluang konversi {ui.fmt(p['peluang'], 0)}%")
                    st.caption(f"{ui.fmt(p['peer_pct'], 0)}% peer memiliki produk · estimasi nilai bersih Rp {ui.fmt(p['ev'], 1)} jt")
        else:
            st.info('Belum ada rekomendasi produk yang boleh ditawarkan. Konfirmasi kebutuhan nasabah terlebih dahulu.')
        with st.expander('Alasan prioritas dan risiko'):
            if pl:
                comps = {'Wallet belum digarap': 'dompet_belum_digarap', 'Ekosistem': 'ekosistem', 'Kebutuhan modal': 'kebutuhan_modal', 'Celah produk': 'celah_produk', 'Erosi wallet': 'erosi_wallet'}
                vals = {lab: pl['komponen'].get(key, np.nan) for lab, key in comps.items()}
                st.plotly_chart(viz.hbar(list(vals), list(vals.values()), h=220, xmax=115, title='Faktor peluang (persentil di segmen)'), use_container_width=True)
                st.caption(pl['alasan'])
            ui.ai_box('Interpretasi risiko', narr['risiko'], fp['risiko']['keputusan'])
            for reason in fp['risiko']['alasan']:
                if isinstance(reason, str) and reason:
                    st.write(reason)
    with next_action, st.container(border=True):
        st.markdown('#### Aksi Berikutnya')
        for recommendation in narr['rekomendasi'][:3]:
            st.markdown(f'- {recommendation}')
        total = activities[activities.status_tampil != 'batal']
        pending = total[total.status_tampil != 'selesai'].sort_values('sisa_hari', na_position='last')
        if not total.empty:
            done = int((total.status_tampil == 'selesai').sum())
            st.progress(done / len(total), text=f'{done} dari {len(total)} tahap selesai')
        if not pending.empty:
            task = pending.iloc[0]
            st.markdown(f"**Tahap: {ui.esc(task.judul)}**", unsafe_allow_html=True)
            st.write(task.aksi)
            st.caption(f'PIC: {task.pemilik or "Belum ditentukan"} · tenggat {task.tenggat or "Belum ditentukan"} · {task.status_tampil}')
        elif not upcoming.empty:
            st.info(f'Persiapkan {upcoming.iloc[0].kanal.lower()} pada {state.when(upcoming.iloc[0].mulai)}.')
        else:
            st.caption('Sepakati langkah berikutnya bersama nasabah.')
        conversion = store.opp.loc[cid, 'p_convert'] if cid in store.opp.index else None
        st.metric('Probabilitas konversi', ui.fmt(conversion * 100, 1, pct=True) if pd.notna(conversion) else 'Belum tersedia',
                  help='Estimasi model untuk produk rekomendasi teratas, bukan kepastian konversi. Belum tersedia untuk prospect.')
        with st.expander('Pertanyaan pembuka'):
            for question in narr['pertanyaan']:
                st.markdown(f'- {question}')

# ------------------------------------------------------------------ 2 keuangan
with tabs[1]:
    kf = fp['keuangan']
    if not kf:
        st.info('Belum ada laporan keuangan untuk perusahaan ini.')
    else:
        chart, interpretation = st.columns([1.85, 1])
        pos = pd.DataFrame([(lab, v[0], v[1], kf['perubahan_pct'][lab]) for lab, v in kf['pos'].items()], columns=['Pos (Rp M)', '2024', '2025', 'Δ %'])
        with chart:
            comparison = pos.melt(id_vars=['Pos (Rp M)'], value_vars=['2024', '2025'], var_name='Tahun', value_name='Rp miliar')
            fig = px.bar(comparison, x='Pos (Rp M)', y='Rp miliar', color='Tahun', barmode='group',
                         color_discrete_map={'2024': '#8FA9D6', '2025': ui.NAVY2})
            viz._layout(fig, 320, legend=True)
            st.plotly_chart(fig, use_container_width=True, key=f'profile_financial_{cid}')
            st.caption(f"{'Diaudit' if kf['diaudit'] else 'Belum diaudit'} · {kf['peer']} · {kf['n_peer']} perusahaan pembanding")
        with interpretation:
            ui.ai_box('Interpretasi Keuangan', narr['keuangan'], 'Laporan 2024–2025 dibandingkan peer')
        lab = {'DER': 'Utang / ekuitas', 'CR': 'Rasio lancar', 'NPM': 'Margin laba bersih %', 'ICR': 'Cakupan bunga', 'ROA': 'ROA %'}
        df = pd.DataFrame({'rasio': [lab[k] for k in kf['rasio']], 'persentil': [v['persentil'] for v in kf['rasio'].values()],
                           'label': [f"{ui.fmt(v['2025'], 2)} vs median {ui.fmt(v['median_peer'], 2)}" for v in kf['rasio'].values()]})
        st.plotly_chart(viz.ratio_vs_peer(df), use_container_width=True, key=f'profile_ratios_{cid}')
        with st.expander('Tabel keuangan dan rasio lengkap'):
            st.dataframe(pos, hide_index=True, use_container_width=True)
            rt = pd.DataFrame([(lab[k], v['2024'], v['2025'], v['median_peer'], v['persentil']) for k, v in kf['rasio'].items()],
                              columns=['Rasio', '2024', '2025', 'Median peer', 'Persentil'])
            st.dataframe(rt, hide_index=True, use_container_width=True)

# ------------------------------------------------------------------ 3 anomali
with tabs[2]:
    a, b = st.columns([1.85, 1])
    with a:
        s = ak['capture_seri']
        if s:
            months = st.segmented_control('Rentang tren', ['3 bulan', '6 bulan', '12 bulan'], default='12 bulan', key=f'profile_cash_range_{cid}') or '12 bulan'
            values = pd.Series(s).sort_index().tail(int(months.split()[0]))
            x = list(values.index); y = list(values.values * 100)
            fig = viz.line(x, y, title='Porsi transaksi lewat BNI (%)', fmt_y=lambda v: f'{v:.0f}%')
            alarm_months = set(store.alerts.loc[store.alerts.company_id == cid, 'ym'])
            marked = [i for i, month in enumerate(x) if month in alarm_months]
            if marked:
                fig.add_scatter(x=[x[i] for i in marked], y=[y[i] for i in marked], mode='markers',
                                marker=dict(color='#9A2416', size=12, symbol='diamond'), name='Bulan dengan alarm',
                                hovertemplate='%{x}: %{y:.0f}% · ada alarm<extra></extra>')
                fig.update_layout(showlegend=True)
            st.plotly_chart(fig, use_container_width=True, key=f'profile_cash_chart_{cid}')
        m = st.columns(4)
        m[0].metric('Gaji/pajak telat (3 bln)', ui.fmt(ak['telat_3m'], 0, pct=True))
        m[1].metric('Outflow / inflow', ui.fmt(ak['out_in_3m'], 2))
        m[2].metric('Inflow 3 vs 6 bln', ui.fmt(ak['chg_3v6'], 2))
        m[3].metric('Inflow dari pembeli hilang', ui.fmt(ak['buyer_exit'], 0, pct=True))
    with b:
        st.markdown(f"**Alarm resmi 3 bulan terakhir: {an['resmi_3bln']} bulan** ({store.alerts_src})")
        al = store.alerts[store.alerts.company_id == cid].sort_values('ym', ascending=False)
        if al.empty:
            st.caption('Belum pernah ada alarm.' + (' Ada sinyal di bawah ambang: porsi wallet turun > 10 poin.' if an['sinyal_bawah_ambang'] else ''))
        for r in al.head(4).itertuples():
            with st.container(border=True):
                st.markdown(ui.event_badge(r.event_type), unsafe_allow_html=True)
                st.caption(r.ym)
                st.write(r.reason)
                st.caption('Aksi: ' + {'distress': 'Konfirmasi pembayaran dan koordinasikan dengan analis risiko.',
                                      'expansion': 'Konfirmasi kebutuhan modal kerja sesuai kelayakan risiko.',
                                      'wallet_erosion': 'Bahas retensi transaksi dengan PIC treasury.'}.get(r.event_type, 'Konfirmasi penyebab temuan bersama nasabah.'))
        ui.ai_box('Interpretasi anomali', narr['anomali'], 'panel arus kas bulanan + aturan alarm NB07', mode)
        if an['jenis_3bln'] and st.button('Investigasi alarm di Copilot', use_container_width=True):
            ss.copilot_task = 'alarm'; state.go('copilot')

# ------------------------------------------------------------------ 4 jaringan
with tabs[3]:
    ego = store.ego(cid)
    graph, detail = st.columns([1.85, 1])
    partner_id = None
    with graph:
        if not ego.empty:
            st.caption('Klik titik mitra untuk memperbarui panel detail di kanan.')
            selected = st.plotly_chart(viz.ego_graph(fp['nama'], ego), use_container_width=True,
                                       key=f'profile_network_{cid}', on_select='rerun', selection_mode='points')
            points = selected['selection']['points']
            partner_id = points[-1]['customdata'][0] if points and points[-1].get('customdata') else None
            with st.expander('Daftar mitra utama'):
                st.dataframe(ego.sort_values('nilai', ascending=False)[['id', 'nama', 'tipe', 'nilai', 'distress']], hide_index=True, use_container_width=True,
                             column_config={'id': 'ID', 'nama': 'Mitra', 'tipe': 'Jenis', 'nilai': 'Transaksi/tahun (Rp juta)', 'distress': 'Alarm distress'})
        else:
            st.info('Tidak ada relasi aktif.')
    with detail, st.container(border=True):
        st.markdown('#### Detail Mitra')
        if partner_id in set(ego.id):
            partner = ego[ego.id == partner_id].iloc[0]
            st.markdown(f"**{ui.esc(partner.nama)}**", unsafe_allow_html=True)
            st.caption(f'{partner_id} · {partner.tipe}')
            st.metric('Transaksi per tahun', f'Rp {ui.fmt(partner.nilai / 1000, 1)} M')
            if partner.distress:
                st.warning('Mitra memiliki alarm distress.')
            if partner_id in allowed and st.button('Buka profil mitra', key=f'profile_partner_{partner_id}', use_container_width=True):
                state.focus_company(partner_id)
        else:
            st.caption('Pilih titik mitra pada grafik untuk melihat detailnya.')
        st.divider()
        a, b = st.columns(2)
        a.metric('Mitra aktif', j['mitra'])
        b.metric('Mitra distress', j['mitra_distress'])
        st.caption(f"{j['bni']} nasabah BNI · {j['prospect']} prospect · {j['eksternal']} eksternal")
        ui.ai_box('Insight jaringan', narr['jaringan'])
        if j['prospect_teratas']:
            st.markdown('**Prospect Utama**')
            for pid, nm, dist, val in j['prospect_teratas']:
                st.markdown(f"**{ui.esc(nm)}**", unsafe_allow_html=True)
                st.caption(f'{pid} · {dist} · Rp {ui.fmt(val, 1)} M/tahun')
                if st.button('Lihat jalan masuk', key=f'intro_{pid}', use_container_width=True):
                    ss.prospect_focus = pid; state.go('prospect')

# ------------------------------------------------------------------ 5 produk & EV
with tabs[4]:
    st.markdown('**Sudah dimiliki:** ' + (' '.join(ui.badge(catalog.product_name.get(p, p), '#E4F1EA', '#17613F') for p in fp['produk_dimiliki']) or '—'), unsafe_allow_html=True)
    PW.product_cards(fp, catalog, f'profile_product_{cid}')
    if fp.get('produk'):
        pr = pd.DataFrame(fp['produk'])
        pr['status'] = pr.ditunda.map({True: 'ditunda (risiko)', False: 'boleh ditawarkan'})
        with st.expander('Rincian perhitungan peluang produk'):
            st.dataframe(pr[['produk', 'peer_pct', 'peluang', 'deal', 'ev', 'ev_lo', 'ev_hi', 'status']], hide_index=True, use_container_width=True,
                     column_config={'produk': 'Produk', 'peer_pct': st.column_config.NumberColumn('Dipegang peer', format='%.0f%%'),
                                    'peluang': st.column_config.NumberColumn('P(konversi)', format='%.0f%%'), 'deal': st.column_config.NumberColumn('Deal (Rp juta)', format='%.0f'),
                                    'ev': st.column_config.NumberColumn('EV (Rp juta)', format='%.1f'), 'ev_lo': st.column_config.NumberColumn('EV P10', format='%.1f'),
                                    'ev_hi': st.column_config.NumberColumn('EV P90', format='%.1f'), 'status': 'Status'})
        st.caption('EV = P(konversi) × ukuran deal × (margin − PD × LGD) × 1 tahun − biaya kontak. Rentang P10–P90 dari simulasi asumsi (NB08 bagian I).')
    else:
        st.caption('Belum ada rekomendasi produk (prospect atau tanpa celah).')

    # -------------------------------------------------------------- simulasi produk
    with st.expander('Simulasi produk dan estimasi nilai', expanded=False):
        st.divider()
        st.markdown('#### Simulasi produk')
        A, cat = sim.assumptions(), sim.catalog()
        rec = [x['produk'] for x in fp.get('produk') or []]
        opts = rec + [x for x in cat.index if x not in rec and x not in fp['produk_dimiliki']]
        if not opts:
            st.caption('Semua produk sudah dimiliki.')
        else:
            pid = st.selectbox('Produk', opts, format_func=lambda x: f"{x} · {cat.product_name[x]}" + (' · disarankan' if x in rec else ''), key=f'sim_p_{cid}')
            dfl = sim.defaults(store, cid, pid, A)
            held = fp['risiko']['kelas'] == 'High' and dfl['credit']
            info, ctl = st.columns([1, 1.25])
            with info:
                product_info = cat.loc[pid]
                ui.ai_box(f"{product_info.product_name} · {product_info.product_category}", f"{product_info.key_benefit}. Untuk: {product_info.target_segment}. Syarat: {product_info.eligibility}. Biaya: {product_info.pricing_note}.",
                          product_info.owner_department)
                if held:
                    st.markdown("<div class='egi-warn'>Risiko High: produk kredit ditahan. Simulasi hanya untuk gambaran, jangan ditawarkan.</div>", unsafe_allow_html=True)
                st.caption(('Peluang awal dari model NB08 untuk perusahaan ini.' if dfl['dari_model'] else 'Produk ini tidak direkomendasikan model; peluang awal = median segmen.')
                           + f" Ukuran deal awal = median {dfl['seg']}.")
            with ctl:
                k = f'{cid}_{pid}'
                x1, x2 = st.columns(2)
                p_ = x1.slider('Peluang konversi (%)', 0.0, 100.0, round(dfl['p'] * 100, 1), 0.5, key=f'sp_{k}') / 100
                deal = x2.number_input('Ukuran deal (Rp juta)', 0.0, 1e6, round(dfl['deal'], 1), 10.0, key=f'sd_{k}')
                x3, x4 = st.columns(2)
                margin = x3.slider('Margin tahunan (%)', 0.0, 10.0, dfl['margin'] * 100, 0.1, key=f'sm_{k}') / 100
                cost = x4.number_input('Biaya aksi (Rp juta)', 0.0, 100.0, float(dfl['cost']), 0.5, key=f'sc_{k}')
                x5, x6 = st.columns(2)
                horizon = x5.slider('Horizon (tahun)', 1.0, 5.0, float(dfl['horizon']), 1.0, key=f'sh_{k}')
                pd_ = x6.slider('PD harapan (%)', 0.0, 30.0, round(dfl['pd'] * 100, 2), 0.1, key=f'spd_{k}', disabled=not dfl['credit'],
                                help='Dari probabilitas kelas risiko NB06 × PD per kelas. Hanya untuk produk kredit.') / 100
            r = sim.ev(p_, deal, margin, pd_, dfl['lgd'], horizon, cost)
            imp = r['impas_p']; reach = imp == imp and imp <= 1      # impas > 100% = mustahil tercapai
            base = sim.ev(dfl['p'], dfl['deal'], dfl['margin'], dfl['pd'], dfl['lgd'], dfl['horizon'], dfl['cost'])
            m = st.columns(4)
            ui.kpi(m[0], 'EV', f"Rp {ui.fmt(r['ev'], 1)} jt", f"asumsi awal Rp {ui.fmt(base['ev'], 1)} jt", color='#17613F' if r['ev'] >= 0 else '#9A2416')
            ui.kpi(m[1], 'Nilai bila deal terjadi', f"Rp {ui.fmt(r['nilai_bila_deal'], 1)} jt", f"pendapatan − kerugian kredit, {horizon:.0f} thn")
            ui.kpi(m[2], 'Titik impas', ui.fmt(imp * 100, 0, pct=True) if reach else 'tidak tercapai',
                   'peluang konversi minimum agar EV ≥ 0' if reach else 'EV negatif meski pasti konversi')
            ui.kpi(m[3], 'ROI aksi', f"{ui.fmt(r['roi'] * 100, 0)}%" if r['roi'] == r['roi'] else '—', 'EV ÷ biaya aksi')
            g1, g2 = st.columns(2)
            g1.plotly_chart(viz.ev_waterfall(r), use_container_width=True)
            ps = np.linspace(0, 100, 101)
            evs = [sim.ev(q / 100, deal, margin, pd_, dfl['lgd'], horizon, cost)['ev'] for q in ps]
            g2.plotly_chart(viz.ev_curve(ps, evs, p_ * 100, r['ev'], imp * 100 if reach else None), use_container_width=True)
            verdict = ('Layak ditawarkan: EV positif pada asumsi ini.' if r['ev'] >= 0 and not held else
                       'Ditahan karena risiko High.' if held else
                       f"Belum impas: perlu peluang konversi ≥ {ui.fmt(imp * 100, 0)}% atau biaya aksi lebih murah (mis. telepon/digital)." if reach else
                       'Tidak impas pada asumsi ini meski nasabah pasti setuju: perbesar ukuran deal/margin atau pakai kanal yang lebih murah.')
            ui.ai_box('Kesimpulan simulasi', verdict, 'rumus EV NB08 · asumsi ilustratif, belum disepakati tim')
            b1, b2 = st.columns(2)
            if b1.button('Siapkan penawaran di Copilot', disabled=held, use_container_width=True, key=f'sim_cp_{k}'):
                ss.copilot_task = 'chat'
                ss.pending_q = (f"Siapkan penawaran {product_info.product_name} ({pid}) untuk {fp['nama']} ({cid}). Simulasi saya: peluang konversi {ui.fmt(p_ * 100, 1)}%, "
                                f"deal Rp {ui.fmt(deal, 1)} juta, EV Rp {ui.fmt(r['ev'], 1)} juta, titik impas {ui.fmt(imp * 100, 0) + '%' if reach else 'tidak tercapai'}. "
                                'Susun poin pembicaraan sesuai kebutuhan nasabah dan draf pesan janji temu.')
                state.go('copilot')
            if b2.button('📅 Jadwalkan dengan tujuan ini', disabled=held or not can_act, use_container_width=True, key=f'sim_pl_{k}'):
                state.schedule_visit(store, cid, f"Tawarkan {pid} {product_info.product_name} (EV Rp {ui.fmt(r['ev'], 1)} jt, peluang {ui.fmt(p_ * 100, 0)}%)", 'Profil · simulasi')

# ------------------------------------------------------------------ 6 riwayat & catatan
with tabs[5]:
    history, notes = st.columns([1.85, 1])
    with history:
        st.markdown('#### Timeline Hubungan')
        feedback = tindak.FEEDBACK.load()
        feedback = feedback[feedback.company_id == cid]
        PW.render_timeline(PW.timeline(logs, calendar, activities, feedback))
        lg = store.log_all[store.log_all.party_id == cid].sort_values('contact_date', ascending=False)
        with st.expander('Tabel seluruh kontak'):
            st.dataframe(lg[['contact_date', 'rm_id', 'channel', 'product_id', 'response', 'feedback_note', 'sumber']], hide_index=True, use_container_width=True,
                     column_config={'contact_date': 'Tanggal', 'rm_id': 'RM', 'channel': 'Kanal', 'product_id': 'Produk', 'response': 'Respons', 'feedback_note': 'Catatan', 'sumber': 'Sumber'})
    with notes, st.container(border=True):
        st.markdown('**Catat kunjungan baru**')
        log_rm = K.owner(store, ss.rm, cid)
        with st.form(f'visit_{cid}', clear_on_submit=False):
            if user['role'] == 'supervisor' and not log_rm:
                log_rm = st.selectbox('RM pelaksana', sorted(store.co.rm_id.dropna().unique()), key=f'profile_contact_rm_{cid}')
            note = st.text_area('Catatan bebas', placeholder='Mis. Bertemu CFO, tertarik payroll untuk 120 karyawan, minta simulasi biaya minggu depan.')
            kanal = st.selectbox('Kanal', ['Kunjungan', 'Telepon', 'Email'])
            sub = st.form_submit_button('Ekstrak dengan Copilot', disabled=not can_act)
        if sub and note.strip() and can_act:
            prods = [p['produk'] for p in fp.get('produk', [])] or ['P01']
            ss['visit_draft'] = (cid, kanal, note, *llm.visit_extract(note, prods))
        vd = ss.get('visit_draft')
        if vd and vd[0] == cid:
            _, kanal, note, ex, m = vd
            st.markdown(f'Hasil ekstraksi ({m}). Periksa lalu setujui:')
            x = [*st.columns(2), *st.columns(2)]
            resp = x[0].selectbox('Respons', ['Converted', 'Interested', 'Not interested', 'No response'], index=['Converted', 'Interested', 'Not interested', 'No response'].index(ex['respons']))
            prod = x[1].text_input('Produk', ex.get('produk', ''))
            keb = x[2].text_input('Keberatan', ex.get('keberatan', ''))
            nxt = x[3].text_input('Langkah berikut', ex.get('langkah_berikut', ''))
            if st.button('Setujui & simpan ke log', type='primary', disabled=not can_act) and can_act:
                log_rm = log_rm or user['rm_id']
                row = {'action_id': f"APP-{pd.Timestamp.now():%Y%m%d%H%M%S}", 'track': 'Deepening' if c.is_client else 'Acquisition', 'party_id': cid, 'product_id': prod,
                       'rm_id': log_rm, 'contact_date': pd.Timestamp.now(tz='Asia/Bangkok').date().isoformat(), 'channel': kanal, 'tier_at_contact': '', 'response': resp, 'converted': int(resp == 'Converted'),
                       'deal_value_idr_mn': 0.0, 'rm_rating': '', 'feedback_note': f"{note.strip()} | keberatan: {keb} | lanjut: {nxt}"}
                try:
                    tindak.record_contact(store, row, user['username'])
                except (ValueError, OSError) as error:
                    st.error(str(error)); st.stop()
                data.audit('catat_kunjungan', company=cid, rm=log_rm, respons=resp, mode=m)
                ss.visit_draft = None; st.success('Catatan kunjungan tersimpan.'); st.rerun()
        st.caption('Catatan dari dashboard disimpan terpisah dari data asli dan tidak mengubah skor sampai notebook dijalankan ulang.')
