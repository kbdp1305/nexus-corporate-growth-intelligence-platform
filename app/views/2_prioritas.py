import pandas as pd
import streamlit as st

from egi import agent, data, state, ui, viz
from egi import kalender as K

store = data.get_store(); ss = st.session_state

PLAYBOOK = {
    'S1 Kecil': 'Kanal murah dulu: telepon / email, paket produk standar (P01 + payroll). Kunjungan hanya untuk skor ≥ 0,85 atau ada alarm ekspansi.',
    'S2 Menengah': 'Campuran: kunjungan untuk Top-20, telepon untuk sisanya. Fokus celah produk yang sudah dipegang peer sesegmen.',
    'S3 Besar': 'Kunjungan tatap muka dan solusi ekosistem (supply-chain financing, cash management). Libatkan analis untuk produk kredit.',
}
PLAYBOOK_P = {
    'S1 Kecil': 'Minta perkenalan dari nasabah sendiri lewat pesan singkat, lalu telepon. Tawarkan paket pembukaan standar (giro + virtual account).',
    'S2 Menengah': 'Perkenalan lewat nasabah anchor, lalu kunjungan. Mulai dari produk transaksi yang menghubungkan ke nasabah (VA, payroll).',
    'S3 Besar': 'Pendekatan ekosistem: tawarkan pembiayaan rantai pasok bersama anchor. Libatkan tim korporasi dan analis sejak awal.',
}
COMP = {'pct_dompet_belum_digarap': 'Dompet belum digarap', 'pct_ekosistem': 'Ekosistem', 'pct_kebutuhan_modal': 'Kebutuhan modal',
        'pct_celah_produk': 'Celah produk', 'pct_erosi_wallet': 'Erosi wallet'}
COMP_P = {'pct_skala': 'Skala (omzet)', 'pct_ekosistem': 'Ekosistem', 'pct_jalur_kenalan': 'Jalur kenalan'}

ui.page_header(f'{ss.rm} · peringkat dibuat per segmen', 'Daftar prioritas')
pf = agent.candidates(store, ss.rm)
sched = K.scheduled_ids(ss.rm)
claims = K.claims()


def prospect_frame(rm):
    """Prospect RM: yang bertransaksi dengan nasabahnya (jaringan) + yang sudah ia klaim lewat jadwal. Supervisor 'Semua RM': semua prospect."""
    acq = store.acq.join(store.cox[['name', 'district', 'industry']])
    net = store.prospects_for(rm) if rm != 'Semua RM' else pd.DataFrame(columns=['lewat_nama', 'nilai_M', 'lewat'])
    ids = set(acq.index) if rm == 'Semua RM' else (set(net.index) | {c for c, r in claims.items() if r == rm and c in acq.index})
    p = acq.loc[sorted(ids)].copy()
    p['lewat_nama'] = net.lewat_nama.reindex(p.index).fillna('—')
    p['nilai_M'] = net.nilai_M.reindex(p.index).fillna(0.0)
    p['pemegang'] = pd.Series(claims).reindex(p.index).fillna('')
    p['white_space'] = p.district.isin(set(store.districts().query('white_space').index))
    return p


pr = prospect_frame(ss.rm)
lab_n = f"{'Nasabah' if ss.rm == 'Semua RM' else 'Nasabah saya'} · {len(pf)}"
mode = st.segmented_control('Tampilkan', [lab_n, f'Prospect · {len(pr)}'], default=lab_n, key='prio_mode') or lab_n

# ================================================================== nasabah
if mode.startswith('Nasabah'):
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
    top10 = pf.nlargest(10, 'opportunity_score').ev_idr_mn   # Rp juta, 1 tahun, produk teratas per nasabah (asumsi ilustratif NB08)
    ui.kpi(k[3], 'Nilai harapan Top-10', f"Rp {ui.fmt(top10.sum(), 1)} jt", f"{int((top10 > 0).sum())} dari {len(top10)} ber-EV positif · 1 tahun, asumsi ilustratif")
    st.write('')

    tabs = st.tabs([f"{s} · {int((v.segment == s).sum())}" for s in data.SEGS])
    for tab, sname in zip(tabs, data.SEGS):
        with tab:
            st.markdown(f"<div class='egi-card' style='border-left:4px solid {ui.SEG_COLOR[sname]}'><b>Playbook {sname}.</b> {PLAYBOOK[sname]}</div>", unsafe_allow_html=True)
            g = v[v.segment == sname].copy()
            if g.empty:
                st.caption('Tidak ada nasabah yang cocok dengan filter.'); continue
            g['status'] = g.caution.map({True: '⚠ alarm risiko', False: ''}) + g.why_up.map({True: ' ↑ Why Now', False: ''}) + g.contacted.map({True: '', False: ' · baru'}) + pd.Series(g.index.isin(sched), index=g.index).map({True: ' · 📅 terjadwal', False: ''})
            t = g[['name', 'district', 'opportunity_score', 'rank_in_segment', 'risk_class', 'status', 'recommended_products', 'p_convert', 'ev_idr_mn']].reset_index()
            ev = st.dataframe(t, hide_index=True, use_container_width=True, height=min(38 + 35 * len(t), 460), on_select='rerun', selection_mode='single-row', key=f'tbl_{sname}',
                              column_config={'company_id': 'ID', 'name': 'Perusahaan', 'district': 'Kecamatan',
                                             'opportunity_score': st.column_config.ProgressColumn('Skor peluang', min_value=0, max_value=1, format='%.2f'),
                                             'rank_in_segment': st.column_config.NumberColumn('Peringkat', format='%d'), 'risk_class': 'Risiko', 'status': 'Status',
                                             'recommended_products': 'Produk disarankan', 'p_convert': st.column_config.NumberColumn('P(konversi)', format='%.2f'),
                                             'ev_idr_mn': st.column_config.NumberColumn('EV (Rp juta)', format='%.1f',
                                                                                         help='Nilai harapan 1 tahun untuk produk teratas: P(konversi) × deal × margin − biaya aksi. Asumsi ilustratif NB08.')})
            rows = ev.selection.rows if ev and hasattr(ev, 'selection') else []
            cid = t.company_id.iloc[rows[0]] if rows else t.company_id.iloc[0]
            r = g.loc[cid]
            st.markdown(f"#### {ui.esc(r['name'])} <span class='egi-muted'>{cid} · {ui.esc(r.district)}</span>", unsafe_allow_html=True)
            a, b = st.columns([1.1, 1])
            with a:
                st.markdown(ui.risk_badge(r.risk_class) + ''.join(ui.event_badge(e.strip()) for e in str(r.alarm).split(',') if e.strip()), unsafe_allow_html=True)
                ui.ai_box('Kenapa nasabah ini', str(r.reason), source='komponen skor peluang NB08 + aturan risiko')
                state.company_actions(store, cid, f'pr_{sname}', sumber='Daftar prioritas')
            with b:
                comps = {lab: float(r[c]) * 100 for c, lab in COMP.items() if c in r.index and pd.notna(r[c])}
                st.plotly_chart(viz.hbar(list(comps), list(comps.values()), [f'{x:.0f}' for x in comps.values()], h=210, xmax=115,
                                         title='Komponen (persentil di segmen)'), use_container_width=True, key=f'cmp_{sname}_{cid}')
    st.caption('Skor = persentil gabungan komponen di dalam segmen + bonus Why Now; risiko High → produk kredit ditunda, Medium → kredit × 0,5. '
               'Pilih baris untuk melihat alasannya.')

# ================================================================== prospect
else:
    if pr.empty:
        st.info('Belum ada prospect yang terhubung ke nasabah RM ini atau yang sudah diklaim lewat jadwal.'); st.stop()
    mine = pr.pemegang == ss.rm
    other = (pr.pemegang != '') & ~mine
    f1, f2, f3, f4 = st.columns([2, 1.2, 1, 1])
    kec = f1.multiselect('Kecamatan', sorted(pr.district.unique()), default=[ss.focus_district] if ss.focus_district in set(pr.district) else [], key='pp_kec')
    urut = f2.selectbox('Urutkan', ['Skor akuisisi', 'Nilai relasi dengan nasabah saya'] if ss.rm != 'Semua RM' else ['Skor akuisisi'], key='pp_sort')
    no_high = f3.toggle('Sembunyikan risiko High', value=True, key='pp_high')
    no_other = f4.toggle('Sembunyikan milik RM lain', value=True, key='pp_other', disabled=ss.rm == 'Semua RM',
                         help='Prospect yang sedang diklaim RM lain (satu perusahaan, satu RM).')
    v = pr.copy()
    if kec: v = v[v.district.isin(kec)]
    if no_high: v = v[v.risk_class != 'High']
    if no_other and ss.rm != 'Semua RM': v = v[~other.reindex(v.index)]
    v = v.sort_values('acquisition_score' if urut == 'Skor akuisisi' else 'nilai_M', ascending=False)

    k = st.columns(4)
    ui.kpi(k[0], 'Prospect di jaringan saya' if ss.rm != 'Semua RM' else 'Prospect', ui.fmt(len(pr), 0),
           ' · '.join(f"{s.split()[0]} {int((pr.segment == s).sum())}" for s in data.SEGS))
    ui.kpi(k[1], 'Diklaim saya', ui.fmt(int(mine.sum()), 0), 'punya jadwal aktif / kunjungan ≤ 30 hari', color=ui.ORANGE)
    ui.kpi(k[2], 'Dipegang RM lain', ui.fmt(int(other.sum()), 0), 'tidak bisa dijadwalkan (satu perusahaan, satu RM)')
    ui.kpi(k[3], 'Risiko High', ui.fmt(int((pr.risk_class == 'High').sum()), 0), 'produk kredit ditunda')
    st.write('')

    tabs = st.tabs([f"{s} · {int((v.segment == s).sum())}" for s in data.SEGS])
    for tab, sname in zip(tabs, data.SEGS):
        with tab:
            st.markdown(f"<div class='egi-card' style='border-left:4px solid {ui.SEG_COLOR[sname]}'><b>Playbook akuisisi {sname}.</b> {PLAYBOOK_P[sname]}</div>",
                        unsafe_allow_html=True)
            g = v[v.segment == sname].copy()
            if g.empty:
                st.caption('Tidak ada prospect yang cocok dengan filter.'); continue
            g['status'] = [' · '.join(x for x in [('✋ diklaim saya' if h == ss.rm else f'🔒 {h}' if h else ''), ('📅 terjadwal' if c in sched else ''),
                                                 ('white-space' if ws else '')] if x)
                           for c, h, ws in zip(g.index, g.pemegang, g.white_space)]
            cols = ['name', 'district', 'acquisition_score', 'rank_in_segment', 'risk_class', 'status'] + (['lewat_nama', 'nilai_M'] if ss.rm != 'Semua RM' else [])
            t = g[cols].reset_index()
            ev = st.dataframe(t, hide_index=True, use_container_width=True, height=min(38 + 35 * len(t), 460), on_select='rerun', selection_mode='single-row', key=f'ptbl_{sname}',
                              column_config={'company_id': 'ID', 'name': 'Prospect', 'district': 'Kecamatan',
                                             'acquisition_score': st.column_config.ProgressColumn('Skor akuisisi', min_value=0, max_value=1, format='%.2f',
                                                                                                  help='Persentil di segmen dari skala + ekosistem + jalur kenalan (NB08). Deskriptif, belum tervalidasi.'),
                                             'rank_in_segment': st.column_config.NumberColumn('Peringkat', format='%d'), 'risk_class': 'Risiko', 'status': 'Status',
                                             'lewat_nama': 'Lewat nasabah saya', 'nilai_M': st.column_config.NumberColumn('Nilai relasi (Rp M/thn)', format='%.1f')})
            rows = ev.selection.rows if ev and hasattr(ev, 'selection') else []
            pid = t.company_id.iloc[rows[0]] if rows else t.company_id.iloc[0]
            r = g.loc[pid]
            st.markdown(f"#### {ui.esc(r['name'])} <span class='egi-muted'>{pid} · {ui.esc(r.industry)} · {ui.esc(r.district)}</span>", unsafe_allow_html=True)
            a, b = st.columns([1.1, 1])
            with a:
                badges = ui.risk_badge(r.risk_class) + (ui.badge('white-space', '#FDEBDD', '#9A3412') if r.white_space else '')
                if r.pemegang and r.pemegang != ss.rm:
                    badges += ui.badge(f'dipegang {r.pemegang}', '#EEF0F3', '#374151')
                elif r.pemegang == ss.rm:
                    badges += ui.badge('diklaim saya', '#E4F1EA', '#17613F')
                st.markdown(badges, unsafe_allow_html=True)
                why = (f"Skala persentil {r.pct_skala * 100:.0f} di {sname}, ekosistem {r.pct_ekosistem * 100:.0f}, dan "
                       f"{int(r.relasi_dengan_nasabah_BNI)} relasi aktif dengan nasabah BNI (persentil jalur kenalan {r.pct_jalur_kenalan * 100:.0f}).")
                if r.risk_class == 'High':
                    why += ' Risiko High: tawarkan produk non-kredit saja.'
                ui.ai_box('Kenapa prospect ini', why, source='skor akuisisi NB08 (deskriptif, belum tervalidasi)')
                paths = store.intro_paths(pid, ss.rm) if ss.rm != 'Semua RM' else store.intro_paths(pid, '')
                if len(paths):
                    best = paths.iloc[0]
                    txt = (f"Lewat nasabah Anda sendiri, {best['name']} (Rp {ui.fmt(best.nilai_M, 1)} M/thn, {best.jenis})." if best.milik_saya else
                           f"Jalur terkuat lewat {best['name']} milik {best.rm_id}; koordinasikan dengan RM tersebut.")
                    st.markdown(f"**Jalan masuk.** {ui.esc(txt)}")
                if r.pemegang and r.pemegang != ss.rm and ss.rm != 'Semua RM':
                    st.caption(f'Sedang dipegang {r.pemegang}. Satu perusahaan hanya ditangani satu RM; minta supervisor memindahkan klaim bila perlu.')
                state.company_actions(store, pid, f'pp_{sname}', sumber='Daftar prioritas · prospect')
                if st.button('Jalur kenalan & draf perkenalan', key=f'pp_intro_{sname}_{pid}', use_container_width=True):
                    ss.prospect_focus = pid; state.go('prospect')
            with b:
                comps = {lab: float(r[c]) * 100 for c, lab in COMP_P.items() if pd.notna(r[c])}
                st.plotly_chart(viz.hbar(list(comps), list(comps.values()), [f'{x:.0f}' for x in comps.values()], h=170, xmax=115,
                                         title='Komponen skor akuisisi (persentil di segmen)'), use_container_width=True, key=f'pcmp_{sname}_{pid}')
    st.caption('Prospect = perusahaan yang bertransaksi dengan nasabah Anda, ditambah yang sudah Anda klaim lewat jadwal. Skor akuisisi bersifat deskriptif '
               '(belum ada data konversi prospect untuk memvalidasinya). Prospect yang sudah dijadwalkan RM lain dikunci untuk RM itu selama ada jadwal aktif + 30 hari.')
