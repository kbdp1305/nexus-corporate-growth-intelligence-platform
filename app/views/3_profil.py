from datetime import date

import numpy as np
import pandas as pd
import streamlit as st

from egi import agent, data, llm, sim, state, ui, viz
import reports as R  # noqa: E402  (src/ ditambahkan ke sys.path oleh egi.data)

store = data.get_store(); ss = st.session_state
ss.setdefault('narr', {})

# ------------------------------------------------------------------ pilih perusahaan
mine = list(store.portfolio(ss.rm).sort_values('opportunity_score', ascending=False).index)
mine_set = set(mine)
others = [c for c in store.co.index if c not in mine_set]
opts = mine + others
cur = ss.focus_company if ss.focus_company in store.co.index else (opts[0] if opts else None)
cid = st.selectbox('Perusahaan', opts, index=opts.index(cur), format_func=lambda c: f"{store.co.name[c]} · {c}" + (' · portofolio saya' if c in mine_set else ''))
if cid != ss.focus_company:
    ss.focus_company = cid; st.query_params['company'] = cid

fp = R.fact_pack(store, cid)
c = store.cox.loc[cid]
narr, mode = ss.narr.get(cid, (None, None))[:2] if cid in ss.narr else (llm.template_company(fp), 'template')

# ------------------------------------------------------------------ kepala
ui.page_header(f"{cid} · {fp['industri']} · {fp['kecamatan']}, {fp['kota']} · RM {fp['rm'] or '—'}", fp['nama'])
an = fp['anomali']
st.markdown(ui.badge(fp['segmen'] or '—', ui.SEG_COLOR.get(fp['segmen'], '#999'), '#fff') + ui.badge(fp['tipe'], '#EEF0F3', '#374151')
            + ui.risk_badge(fp['risiko']['kelas']) + ''.join(ui.badge('alarm ' + j, '#FADFDB', '#9A2416') for j in an['jenis_3bln'])
            + (ui.badge('listed', '#EEF2F9', ui.NAVY2) if fp['listed'] else ''), unsafe_allow_html=True)

k = st.columns(5)
pl = fp.get('peluang')
ui.kpi(k[0], 'Skor peluang', ui.fmt(pl['skor'] / 100, 2) if pl else '—', f"peringkat {pl['peringkat']} dari {pl['n_segmen']} di segmen" if pl else 'prospect: lihat skor akuisisi', color=ui.ORANGE)
ui.kpi(k[1], 'Peluang risiko High', ui.fmt(fp['risiko']['p_high'], 0, pct=True), f"keputusan: {fp['risiko']['keputusan']}")
ak = fp['arus_kas']
ui.kpi(k[2], 'Porsi wallet di BNI', ui.fmt(ak['capture_now'] * 100, 0, pct=True) if ak['capture_now'] == ak['capture_now'] else '—', f"{ui.fmt(ak['capture_chg_6m'], 0)} poin dalam 6 bulan")
j = fp['jaringan']
ui.kpi(k[3], 'Mitra aktif', ui.fmt(j['mitra'], 0), f"median peer {ui.fmt(j['median_peer'], 0)} · {j['prospect']} prospect")
ui.kpi(k[4], 'Produk dimiliki', f"{len(fp['produk_dimiliki'])} / 8", ', '.join(fp['produk_dimiliki']) or '—')
st.write('')

b1, b2, b3, b4, b5 = st.columns(5)
if b1.button('+ Rencana minggu', use_container_width=True):
    state.add_to_plan(store, cid)
if b5.button('Ajukan kunjungan', use_container_width=True, help='Ajukan ke supervisor dan ajak divisi lain mendampingi'):
    ss.pj_company = cid; ss.tl_tab = 'Pengajuan kunjungan'; state.go('tindak')
if b2.button('Siapkan kunjungan di Copilot', use_container_width=True):
    ss.copilot_task = 'brief'; state.go('copilot')
cfg = llm.config()
if b3.button('Tulis ulang dengan LLM' if cfg['enabled'] else 'LLM belum aktif', use_container_width=True, disabled=not cfg['enabled']):
    with st.spinner('Copilot menulis ringkasan…'):
        n2, m2, bad = llm.company_narrative(fp)
    ss.narr[cid] = (n2, m2, bad); narr, mode = n2, m2
    data.audit('narasi_llm', company=cid, rm=ss.rm, mode=m2, bagian_ditolak=[b[0] for b in bad or []])
    if bad:
        st.warning('Bagian ' + ', '.join(b[0] for b in bad) + ' memuat angka yang tidak ada di data, jadi diganti teks template.')
with b4:
    if st.button('Buat PDF ringkasan', use_container_width=True):
        buf, (n, badn) = R.company_summary_pdf(fp, narr, generated_by='Copilot (LLM)' if mode == 'LLM' else 'Copilot (template)')
        ss['pdf_' + cid] = buf.getvalue() if hasattr(buf, 'getvalue') else buf
        data.audit('pdf_ringkasan', company=cid, rm=ss.rm, mode=mode, angka=n, tidak_cocok=len(badn))
    if ss.get('pdf_' + cid):
        st.download_button('Unduh PDF', ss['pdf_' + cid], file_name=f'ringkasan_{cid}.pdf', mime='application/pdf', use_container_width=True)

src = 'paket fakta NB04–NB08' + (' · narasi LLM, angka divalidasi' if mode == 'LLM' else ' · teks template')
tabs = st.tabs(['Ringkasan', 'Keuangan', 'Anomali & arus kas', 'Jaringan', 'Produk & EV', 'Riwayat & catatan'])

# ------------------------------------------------------------------ 1 ringkasan
with tabs[0]:
    a, b = st.columns([1.3, 1])
    with a:
        ui.ai_box('Ringkasan eksekutif', narr['ringkasan'], src, mode)
        st.markdown('**Rekomendasi**')
        for x in narr['rekomendasi']:
            st.markdown(f'- {x}')
        st.markdown('**Pertanyaan pembuka**')
        for x in narr['pertanyaan']:
            st.markdown(f'- {x}')
    with b:
        if pl:
            comps = {'Dompet belum digarap': 'dompet_belum_digarap', 'Ekosistem': 'ekosistem', 'Kebutuhan modal': 'kebutuhan_modal', 'Celah produk': 'celah_produk', 'Erosi wallet': 'erosi_wallet'}
            vals = {lab: pl['komponen'].get(key, np.nan) for lab, key in comps.items()}
            st.plotly_chart(viz.hbar(list(vals), list(vals.values()), [ui.fmt(x, 0) for x in vals.values()], h=220, xmax=115, title='Kenapa perusahaan ini (persentil di segmen)'), use_container_width=True)
            st.caption(pl['alasan'])
        else:
            if cid in store.acq.index:
                q = store.acq.loc[cid]
                st.metric('Skor akuisisi prospect', ui.fmt(q.acquisition_score, 2), f"peringkat {int(q.rank_in_segment)} di segmen")
        r = fp['risiko']
        st.markdown('**Alasan model risiko** (kontribusi SHAP terbesar, NB06)')
        for x in r['alasan']:
            if isinstance(x, str) and x:
                st.markdown(f'- {x}')
        st.caption(f"P(Low/Medium/High) = {ui.fmt(r['p_low'], 0)} / {ui.fmt(r['p_med'], 0)} / {ui.fmt(r['p_high'], 0)}% · himpunan conformal {r['himpunan']}")
        ui.ai_box('Interpretasi risiko', narr['risiko'], 'NB06 champion + conformal', mode)

# ------------------------------------------------------------------ 2 keuangan
with tabs[1]:
    kf = fp['keuangan']
    if not kf:
        st.info('Belum ada laporan keuangan untuk perusahaan ini.')
    else:
        a, b = st.columns([1, 1.1])
        with a:
            pos = pd.DataFrame([(lab, v[0], v[1], kf['perubahan_pct'][lab]) for lab, v in kf['pos'].items()], columns=['Pos (Rp M)', '2024', '2025', 'Δ %'])
            st.dataframe(pos, hide_index=True, use_container_width=True,
                         column_config={'2024': st.column_config.NumberColumn(format='%.1f'), '2025': st.column_config.NumberColumn(format='%.1f'), 'Δ %': st.column_config.NumberColumn(format='%+.0f%%')})
            st.caption(f"{'Diaudit' if kf['diaudit'] else 'Belum diaudit'} · peer: {kf['peer']} ({kf['n_peer']} perusahaan, 2025)")
            lab = {'DER': 'Utang / ekuitas', 'CR': 'Rasio lancar', 'NPM': 'Margin laba bersih %', 'ICR': 'Cakupan bunga', 'ROA': 'ROA %'}
            rt = pd.DataFrame([(lab[k], v['2024'], v['2025'], v['median_peer'], v['persentil']) for k, v in kf['rasio'].items()],
                              columns=['Rasio', '2024', '2025', 'Median peer', 'Persentil'])
            st.dataframe(rt, hide_index=True, use_container_width=True,
                         column_config={x: st.column_config.NumberColumn(format='%.2f') for x in ['2024', '2025', 'Median peer']} | {'Persentil': st.column_config.NumberColumn(format='%.0f')})
        with b:
            df = pd.DataFrame({'rasio': [lab[k] for k in kf['rasio']], 'persentil': [v['persentil'] for v in kf['rasio'].values()],
                               'label': [f"{ui.fmt(v['2025'], 2)} vs median {ui.fmt(v['median_peer'], 2)}" for v in kf['rasio'].values()]})
            st.plotly_chart(viz.ratio_vs_peer(df), use_container_width=True)
            ui.ai_box('Interpretasi keuangan', narr['keuangan'], 'financials.csv 2024–2025 vs peer industri & ukuran', mode)

# ------------------------------------------------------------------ 3 anomali
with tabs[2]:
    a, b = st.columns([1.2, 1])
    with a:
        s = ak['capture_seri']
        if s:
            x = list(s); y = [v * 100 for v in s.values()]
            st.plotly_chart(viz.line(x, y, title='Porsi transaksi lewat BNI (capture, %)', fmt_y=lambda v: f'{v:.0f}%'), use_container_width=True)
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
        for r in al.head(6).itertuples():
            st.markdown(f"{ui.event_badge(r.event_type)} <span class='egi-muted'>{r.ym} · {ui.esc(r.reason)}</span>", unsafe_allow_html=True)
        ui.ai_box('Interpretasi anomali', narr['anomali'], 'panel arus kas bulanan + aturan alarm NB07', mode)
        if an['jenis_3bln'] and st.button('Investigasi alarm di Copilot', use_container_width=True):
            ss.copilot_task = 'alarm'; state.go('copilot')

# ------------------------------------------------------------------ 4 jaringan
with tabs[3]:
    ego = store.ego(cid)
    a, b = st.columns([1.5, 1])
    with a:
        if len(ego):
            st.plotly_chart(viz.ego_graph(fp['nama'], ego), use_container_width=True)
        else:
            st.caption('Tidak ada relasi aktif.')
    with b:
        m = st.columns(3)
        m[0].metric('Mitra', j['mitra'], f"median peer {ui.fmt(j['median_peer'], 0)}", delta_color='off')
        m[1].metric('Nilai/thn', f"Rp {ui.fmt(j['nilai_M'], 0)} M")
        m[2].metric('Mitra distress', j['mitra_distress'])
        st.caption(f"{j['bni']} nasabah BNI · {j['prospect']} prospect · {j['eksternal']} eksternal")
        ui.ai_box('Interpretasi jaringan', narr['jaringan'], 'relationships.csv (aktif per Jun 2026)', mode)
        if j['prospect_teratas']:
            st.markdown('**Prospect di jaringan nasabah ini**')
            for pid, nm, dist, val in j['prospect_teratas']:
                x1, x2 = st.columns([3, 1])
                x1.markdown(f"{ui.esc(nm)}<br><span class='egi-muted'>{pid} · {ui.esc(dist)} · Rp {ui.fmt(val, 1)} M/thn</span>", unsafe_allow_html=True)
                if x2.button('Jalan masuk', key=f'intro_{pid}'):
                    ss.prospect_focus = pid; state.go('prospect')

# ------------------------------------------------------------------ 5 produk & EV
with tabs[4]:
    st.markdown('**Sudah dimiliki:** ' + (' '.join(ui.badge(p, '#E4F1EA', '#17613F') for p in fp['produk_dimiliki']) or '—'), unsafe_allow_html=True)
    if fp.get('produk'):
        pr = pd.DataFrame(fp['produk'])
        pr['status'] = pr.ditunda.map({True: 'ditunda (risiko)', False: 'boleh ditawarkan'})
        st.dataframe(pr[['produk', 'peer_pct', 'peluang', 'deal', 'ev', 'ev_lo', 'ev_hi', 'status']], hide_index=True, use_container_width=True,
                     column_config={'produk': 'Produk', 'peer_pct': st.column_config.NumberColumn('Dipegang peer', format='%.0f%%'),
                                    'peluang': st.column_config.NumberColumn('P(konversi)', format='%.0f%%'), 'deal': st.column_config.NumberColumn('Deal (Rp juta)', format='%.0f'),
                                    'ev': st.column_config.NumberColumn('EV (Rp juta)', format='%.1f'), 'ev_lo': st.column_config.NumberColumn('EV P10', format='%.1f'),
                                    'ev_hi': st.column_config.NumberColumn('EV P90', format='%.1f'), 'status': 'Status'})
        st.caption('EV = P(konversi) × ukuran deal × (margin − PD × LGD) × 1 tahun − biaya kontak. Rentang P10–P90 dari simulasi asumsi (NB08 bagian I).')
    else:
        st.caption('Belum ada rekomendasi produk (prospect atau tanpa celah).')

    # -------------------------------------------------------------- simulasi produk
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
            c = cat.loc[pid]
            ui.ai_box(f"{c.product_name} · {c.product_category}", f"{c.key_benefit}. Untuk: {c.target_segment}. Syarat: {c.eligibility}. Biaya: {c.pricing_note}.",
                      f"product_master.csv · {c.owner_department}")
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
        if b1.button('Siapkan penawaran di Copilot', use_container_width=True, key=f'sim_cp_{k}'):
            ss.copilot_task = 'chat'
            ss.pending_q = (f"Siapkan penawaran {c.product_name} ({pid}) untuk {fp['nama']} ({cid}). Simulasi saya: peluang konversi {ui.fmt(p_ * 100, 1)}%, "
                            f"deal Rp {ui.fmt(deal, 1)} juta, EV Rp {ui.fmt(r['ev'], 1)} juta, titik impas {ui.fmt(imp * 100, 0) + '%' if reach else 'tidak tercapai'}. "
                            'Susun poin pembicaraan sesuai kebutuhan nasabah dan draf pesan janji temu.')
            state.go('copilot')
        if b2.button('+ Rencana dengan tujuan ini', use_container_width=True, key=f'sim_pl_{k}'):
            state.add_to_plan(store, cid, f"tawarkan {pid} {c.product_name} (EV Rp {ui.fmt(r['ev'], 1)} jt)")

# ------------------------------------------------------------------ 6 riwayat & catatan
with tabs[5]:
    lg = store.log_all[store.log_all.party_id == cid].sort_values('contact_date', ascending=False)
    st.dataframe(lg[['contact_date', 'rm_id', 'channel', 'product_id', 'response', 'feedback_note', 'sumber']], hide_index=True, use_container_width=True,
                 column_config={'contact_date': 'Tanggal', 'rm_id': 'RM', 'channel': 'Kanal', 'product_id': 'Produk', 'response': 'Respons', 'feedback_note': 'Catatan', 'sumber': 'Sumber'})
    st.markdown('**Catat kunjungan baru**')
    with st.form(f'visit_{cid}', clear_on_submit=False):
        note = st.text_area('Catatan bebas', placeholder='Mis. Bertemu CFO, tertarik payroll untuk 120 karyawan, minta simulasi biaya minggu depan.')
        kanal = st.selectbox('Kanal', ['Kunjungan', 'Telepon', 'Email'])
        sub = st.form_submit_button('Ekstrak dengan Copilot')
    if sub and note.strip():
        prods = [p['produk'] for p in fp.get('produk', [])] or ['P01']
        ss['visit_draft'] = (cid, kanal, note, *llm.visit_extract(note, prods))
    vd = ss.get('visit_draft')
    if vd and vd[0] == cid:
        _, kanal, note, ex, m = vd
        st.markdown(f'Hasil ekstraksi ({m}). Periksa lalu setujui:')
        x = st.columns(4)
        resp = x[0].selectbox('Respons', ['Converted', 'Interested', 'Not interested', 'No response'], index=['Converted', 'Interested', 'Not interested', 'No response'].index(ex['respons']))
        prod = x[1].text_input('Produk', ex.get('produk', ''))
        keb = x[2].text_input('Keberatan', ex.get('keberatan', ''))
        nxt = x[3].text_input('Langkah berikut', ex.get('langkah_berikut', ''))
        if st.button('Setujui & simpan ke log', type='primary'):
            row = {'action_id': f"APP-{pd.Timestamp.now():%Y%m%d%H%M%S}", 'track': 'Deepening' if c.is_client else 'Acquisition', 'party_id': cid, 'product_id': prod,
                   'rm_id': ss.rm, 'contact_date': date.today().isoformat(), 'channel': kanal, 'tier_at_contact': '', 'response': resp, 'converted': int(resp == 'Converted'),
                   'deal_value_idr_mn': 0.0, 'rm_rating': '', 'feedback_note': f"{note.strip()} | keberatan: {keb} | lanjut: {nxt}"}
            store.append_visit(row); data.audit('catat_kunjungan', company=cid, rm=ss.rm, respons=resp, mode=m)
            ss.visit_draft = None; st.success('Tersimpan di outputs/app/visit_log.csv'); st.rerun()
    st.caption('Catatan dari dashboard disimpan terpisah dari data asli dan tidak mengubah skor sampai notebook dijalankan ulang.')
