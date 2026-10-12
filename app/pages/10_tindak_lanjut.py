from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st

from egi import auth, data, kalender as K, llm, state, tindak as T, ui

store = data.get_store(); ss = st.session_state
user = auth.current()
ui.page_header(f"{ss.rm} · feedback setelah kunjungan, rencana lanjutan, dan koordinasi dengan divisi", 'Tindak lanjut kunjungan')

TABS = ['Feedback kunjungan', 'Pengajuan kunjungan']
if ss.get('tl_tab') in TABS:                      # lompatan dari Kalender / Profil memilih tab
    ss['tl_sel'] = ss.pop('tl_tab')
ss.setdefault('tl_sel', TABS[0])
tab = st.segmented_control('Bagian', TABS, key='tl_sel') or TABS[0]
PNAME = T.products().product_name.to_dict()
fmt_prod = lambda p: f"{p} · {PNAME.get(p, '')}"
fmt_div = lambda d: T.DIVISI.get(d, d)
fmt_co = lambda c: f"{store.co.name.get(c, c)} · {c}"


def show_thread(row):
    for e in T.thread(row):
        st.markdown(f"<span class='egi-muted'>{e['waktu'][:16].replace('T', ' ')} · {ui.esc(e['oleh'])}"
                    + (f" · <b>{ui.esc(e['status'])}</b>" if e.get('status') else '') + f"</span><br>{ui.esc(e['pesan'])}", unsafe_allow_html=True)


# ================================================================== feedback kunjungan
if tab == 'Feedback kunjungan':
    due = T.pending_feedback(ss.rm)
    pre = ss.pop('fb_event', None)
    if pre and pre not in set(due.id):            # jadwal yang belum lewat tapi dipilih dari kalender
        cal = K.load(); row = cal[cal.id == pre]
        if len(row):
            due = pd.concat([row.assign(_m=pd.to_datetime(row.mulai)), due])
    if due.empty:
        st.info('Tidak ada kunjungan yang menunggu feedback. Jadwal kunjungan/telepon yang sudah lewat di Kalender kunjungan akan muncul di sini.')
    else:
        st.markdown(f"**{len(due)} kunjungan menunggu feedback**")
        ids = list(due.id)
        lab = {r.id: f"{pd.Timestamp(r.mulai):%a %d %b %H.%M} · {r.kanal} · {r.judul}" + (f" · {r.rm_id}" if ss.rm == 'Semua RM' else '') for r in due.itertuples()}
        eid = st.selectbox('Kunjungan', ids, index=ids.index(pre) if pre in ids else 0, format_func=lab.get)
        ev = due[due.id == eid].iloc[0].to_dict()
        if not auth.can_edit(ev['rm_id']):
            st.caption('Hanya RM pemilik jadwal yang bisa mengisi feedback.'); st.stop()
        cid = ev['company_id']
        held = sorted(store.hold[store.hold.company_id == cid].product_id.unique()) if cid else []
        rec = [p for p in store.prod[store.prod.company_id == cid].sort_values('rank_produk').product_id][:3] if cid else []

        a, b = st.columns([1.25, 1])
        with a:
            st.markdown('##### 1 · Hasil kunjungan')
            hasil = st.radio('Hasil', T.HASIL, format_func=T.HASIL_ID.get, horizontal=True, key=f'fb_h_{eid}')
            produk = st.multiselect('Produk yang dibahas', list(PNAME), format_func=fmt_prod, key=f'fb_p_{eid}')
            catatan = st.text_area('Catatan hasil kunjungan', key=f'fb_c_{eid}', height=120,
                                   placeholder='Mis. Bertemu CFO. Ada rencana ekspansi gudang tahun depan, tertarik payroll untuk 120 karyawan, '
                                               'tapi keberatan dengan biaya administrasi.')
            keberatan = st.text_input('Keberatan nasabah (opsional)', key=f'fb_k_{eid}')
            st.caption(f"Produk dimiliki: {', '.join(held) or '—'} · rekomendasi model: {', '.join(rec) or '—'}")
        hit, sug, hold = T.suggest(catatan, produk)
        riwayat = T.history(cid, eid)
        ulang = T.needs_reconsider(hasil, catatan, keberatan)
        sig = (hasil, catatan, keberatan, tuple(produk))
        if ss.get(f'fb_sx_{eid}', {}).get('sig') != sig:          # saran LLM usang bila isian berubah
            ss.pop(f'fb_sx_{eid}', None)
        saran, mode = T.followup_rule(hasil, catatan, keberatan, produk, hold, riwayat), 'aturan'
        if f'fb_sx_{eid}' in ss:
            saran, mode = ss[f'fb_sx_{eid}']['saran'], 'LLM'
        when = T.free_slot(ev['rm_id'], datetime.combine(date.today() + timedelta(days=saran['hari']), time.fromisoformat(saran['jam'])),
                           K.R.DURASI_MENIT.get(saran['kanal'], 60))

        def follow(key, auto):                                    # isian ikut saran selama belum diubah manual
            if key not in ss or ss[key] == ss.get(f'_auto_{key}'):
                ss[key] = auto
            ss[f'_auto_{key}'] = auto

        def pakai_saran():
            ss[f'fb_l_{eid}'] = saran['langkah']
            for key, v in [(f'fb_j_{eid}', True), (f'fb_t_{eid}', when.date()), (f'fb_jm_{eid}', when.time()), (f'fb_kn_{eid}', saran['kanal'])]:
                ss[key] = ss[f'_auto_{key}'] = v

        def saran_llm():
            ctx = {'perusahaan': store.co.name.get(cid, cid), 'hari_ini': f'{date.today():%A %d %b %Y}', 'kanal_kunjungan_ini': ev['kanal'],
                   'hasil': T.HASIL_ID.get(hasil, hasil), 'produk_dibahas': [PNAME.get(p, p) for p in produk], 'catatan': catatan, 'keberatan': keberatan,
                   'isu': [T.issues().issue_name.get(i, i) for i in hit], 'kredit_ditahan': hold, 'perlu_pertimbangan_ulang': ulang,
                   'produk_dimiliki': [PNAME.get(p, p) for p in held], 'rekomendasi_model': [PNAME.get(p, p) for p in rec],
                   'riwayat_kunjungan': [{'tanggal': r.tanggal, 'kanal': r.kanal, 'hasil': T.HASIL_ID.get(r.hasil, r.hasil), 'catatan': r.catatan,
                                          'keberatan': r.keberatan, 'langkah_lanjut': r.langkah_lanjut} for r in riwayat.head(5).itertuples()]}
            s, md = llm.followup_suggest(ctx, T.followup_rule(hasil, catatan, keberatan, produk, hold, riwayat), K.KANAL)
            if md == 'LLM':
                ss[f'fb_sx_{eid}'] = {'sig': sig, 'saran': s}
            else:
                ss.fb_llm_err = llm.complete.last_error or 'LLM tidak membalas dengan format yang benar.'

        with b:
            st.markdown('##### 2 · Rencana lanjutan')
            if ulang:
                st.markdown("<div class='egi-warn'>Nasabah perlu pertimbangan ulang: disarankan menjadwalkan ulang kunjungan setelah nasabah menimbang.</div>",
                            unsafe_allow_html=True)
            langkah = st.text_input('Langkah berikutnya', key=f'fb_l_{eid}', placeholder='Mis. kirim simulasi payroll & jadwalkan presentasi ke direksi')
            st.markdown(f"<div class='egi-ai'><div class='h'>Suggestion · {'LLM' if mode == 'LLM' else 'otomatis (aturan)'}</div>{ui.esc(saran['langkah'])}"
                        f"<div class='src'>{ui.esc(saran['alasan'])}<br>{'Jadwal ulang' if ulang else 'Jadwal berikutnya'}: "
                        f"{when:%a %d %b %Y, %H.%M} · {ui.esc(saran['kanal'])} (slot kosong di kalender {ev['rm_id']})</div></div>", unsafe_allow_html=True)
            s1, s2, _ = st.columns([1, 1.3, 0.7])
            s1.button('Pakai saran', key=f'fb_use_{eid}', on_click=pakai_saran, use_container_width=True,
                      help='Isi langkah berikutnya dan jadwal dengan saran ini; tetap bisa diubah manual.')
            on = llm.config()['enabled']
            s2.button('Buat ulang dengan LLM' if mode == 'LLM' else 'Buat saran dengan LLM', key=f'fb_llm_{eid}', on_click=saran_llm, disabled=not on,
                      use_container_width=True, help='Saran dari catatan, keberatan, dan riwayat kunjungan sebelumnya.' if on
                      else 'LLM belum dikonfigurasi (LLM_PROVIDER & API key di .env); saran memakai aturan otomatis.')
            if ss.get('fb_llm_err'):
                st.caption(f"LLM gagal, saran memakai aturan otomatis: {ss.pop('fb_llm_err')[:160]}")
            follow(f'fb_j_{eid}', hasil in ('Converted', 'Interested') or ulang)
            jadwal = st.toggle('Jadwalkan ulang kunjungan di kalender' if ulang else 'Jadwalkan tindak lanjut di kalender', key=f'fb_j_{eid}')
            lanjut = None
            if jadwal:
                follow(f'fb_t_{eid}', when.date()); follow(f'fb_jm_{eid}', when.time()); follow(f'fb_kn_{eid}', saran['kanal'])
                x1, x2, x3 = st.columns([1.3, 1, 1.2])
                tgl = x1.date_input('Tanggal', format='DD/MM/YYYY', key=f'fb_t_{eid}')
                jam = x2.time_input('Jam', step=900, key=f'fb_jm_{eid}')
                kanal = x3.selectbox('Kanal', K.KANAL, key=f'fb_kn_{eid}')
                m = datetime.combine(tgl, jam); lanjut = (m, m + timedelta(minutes=K.R.DURASI_MENIT.get(kanal, 60)), kanal)
            st.markdown('##### 3 · Koordinasi dengan divisi')
            if hit:
                st.markdown('Isu terdeteksi dari catatan: ' + ''.join(ui.badge(T.issues().issue_name.get(i, i), '#EEF2F9', ui.NAVY2) for i in hit), unsafe_allow_html=True)
            if hold:
                st.markdown("<div class='egi-warn'>Ada isu legal / tekanan likuiditas: produk kredit ditahan, libatkan Legal atau Risiko Kredit dulu.</div>",
                            unsafe_allow_html=True)
            divs = st.multiselect('Kirim tiket ke divisi', list(T.DIVISI), default=sug, format_func=fmt_div, key=f'fb_d_{eid}_{"-".join(sug)}',
                                  help='Saran otomatis dari isu di catatan dan pemilik produk yang dibahas; bisa diubah.')
            if divs:
                y1, y2 = st.columns(2)
                prio = y1.selectbox('Prioritas', T.PRIORITAS, index=1 if hasil == 'Converted' or hold else 0, key=f'fb_pr_{eid}')
                tenggat = y2.date_input('Tenggat', date.today() + timedelta(days=5), format='DD/MM/YYYY', key=f'fb_tg_{eid}')
                pesan = st.text_area('Permintaan ke divisi', key=f'fb_m_{eid}', height=80, placeholder='Mis. mohon simulasi limit KMK dan dokumen yang dibutuhkan.')
            else:
                prio, tenggat, pesan = 'Normal', '', ''
        if st.button('Simpan feedback' + (f' & kirim {len(divs)} tiket' if divs else ''), type='primary'):
            if not catatan.strip():
                st.error('Isi catatan hasil kunjungan dulu.')
            else:
                fb, fu, tk = T.save_feedback(store, ev, hasil=hasil, produk=produk, catatan=catatan.strip(), keberatan=keberatan.strip(), isu=hit,
                                             langkah=langkah.strip(), lanjut=lanjut, divs=divs, prioritas=prio, tenggat=tenggat, pesan_divisi=pesan.strip(),
                                             user=user['username'], ulang=ulang)
                ss.fb_done = f"Feedback tersimpan · jadwal ditandai selesai · dicatat ke riwayat nasabah" \
                             + ((' · jadwal ulang masuk kalender' if ulang else ' · tindak lanjut masuk kalender') if fu else '') \
                             + (f" · {len(tk)} tiket ke {', '.join(fmt_div(d) for d in divs)}" if tk else '')
                st.rerun()
    if ss.get('fb_done'):
        st.success(ss.pop('fb_done'))
        c1, c2, _ = st.columns([1, 1, 3])
        if c1.button('Buka kalender', use_container_width=True):
            state.go('kalender')
        if c2.button('Lihat tiket', use_container_width=True):
            state.go('koordinasi')

    st.markdown('#### Riwayat feedback')
    fb = T.FEEDBACK.load()
    fb = fb if ss.rm == 'Semua RM' else fb[fb.rm_id == ss.rm]
    if fb.empty:
        st.caption('Belum ada.')
    else:
        fb = fb.sort_values('dibuat_pada', ascending=False)
        show = fb.assign(perusahaan=fb.company_id.map(lambda c: store.co.name.get(c, c)), hasil=fb.hasil.map(T.HASIL_ID),
                         tiket=fb.tiket.map(lambda s: len([x for x in s.split(';') if x])), lanjut=fb.jadwal_lanjut_id.ne(''), ulang=fb.pertimbangan_ulang.eq('ya'))
        st.dataframe(show[['tanggal', 'rm_id', 'perusahaan', 'kanal', 'hasil', 'produk', 'langkah_lanjut', 'ulang', 'lanjut', 'tiket']], hide_index=True, use_container_width=True,
                     column_config={'tanggal': 'Tanggal', 'rm_id': 'RM', 'perusahaan': 'Perusahaan', 'kanal': 'Kanal', 'hasil': 'Hasil', 'produk': 'Produk',
                                    'langkah_lanjut': 'Langkah berikutnya', 'ulang': st.column_config.CheckboxColumn('Pertimbangan ulang'),
                                    'lanjut': st.column_config.CheckboxColumn('Dijadwalkan'), 'tiket': 'Tiket divisi'})

# ================================================================== pengajuan kunjungan
else:
    req = T.REQ.load()
    pj = req[req.jenis == 'Pengajuan kunjungan']
    if user['role'] == 'supervisor':
        q = pj[pj.status == 'Diajukan'].sort_values('usulan_mulai')
        st.markdown(f"#### Menunggu persetujuan · {len(q)}")
        if q.empty:
            st.caption('Tidak ada pengajuan baru.')
        for r in q.to_dict('records'):
            m = datetime.fromisoformat(r['usulan_mulai'])
            divs = [d for d in r['divisi_terlibat'].split(';') if d]
            with st.container(border=True):
                st.markdown(f"**{ui.esc(r['judul'])}** · {r['rm_id']} · {r['kanal']} · {m:%a %d %b %Y, %H.%M}–{r['usulan_selesai'][11:16].replace(':', '.')}"
                            f"<br><span class='egi-muted'>{ui.esc(r['isi']).replace(chr(10), '<br>')}</span>"
                            + (f"<br>Divisi pendamping: {', '.join(fmt_div(d) for d in divs)}" if divs else ''), unsafe_allow_html=True)
                bentrok = K.load()
                bentrok = bentrok[(bentrok.rm_id == r['rm_id']) & (bentrok.status == 'Terjadwal') & (bentrok.mulai < r['usulan_selesai']) & (bentrok.selesai > r['usulan_mulai'])]
                if len(bentrok):
                    st.markdown(f"<div class='egi-warn'>Bentrok dengan jadwal {r['rm_id']}: {ui.esc(', '.join(bentrok.judul))}</div>", unsafe_allow_html=True)
                kom = st.text_input('Komentar', key=f"kom_{r['id']}", placeholder='opsional')
                c1, c2, _ = st.columns([1, 1, 3])
                if c1.button('Setujui', key=f"ok_{r['id']}", type='primary', use_container_width=True):
                    T.decide_visit(store, r, True, kom, user['username']); st.toast('Disetujui · masuk kalender RM'); st.rerun()
                if c2.button('Tolak', key=f"no_{r['id']}", use_container_width=True):
                    T.decide_visit(store, r, False, kom, user['username']); st.toast('Ditolak'); st.rerun()
        st.divider()

    st.markdown('#### Ajukan kunjungan')
    if user['role'] == 'supervisor':
        rms = sorted(store.co.rm_id.dropna().unique())
        owner = st.selectbox('Untuk RM', rms, index=rms.index(ss.rm) if ss.rm in rms else 0)
    else:
        owner = user['rm_id']
    mine = list(store.co.index[store.co.rm_id == owner])
    opts = mine + [c for c in store.co.index if c not in set(mine)]
    pre = ss.get('pj_company') or ss.focus_company
    a, b = st.columns([1.25, 1])
    with a:
        cid = st.selectbox('Perusahaan', opts, index=opts.index(pre) if pre in opts else 0,
                           format_func=lambda c: fmt_co(c) + (' · portofolio' if c in set(mine) else ' · prospect/RM lain'))
        c = store.cox.loc[cid]
        st.markdown(ui.badge(c.segment or '—', ui.SEG_COLOR.get(c.segment, '#999'), '#fff') + ui.risk_badge(c.pred_class)
                    + ui.badge('nasabah' if c.is_client else 'prospect', '#EEF0F3', '#374151') + f" <span class='egi-muted'>Kec. {ui.esc(c.district)}</span>",
                    unsafe_allow_html=True)
        tujuan = st.text_area('Tujuan kunjungan', height=90, key='pj_tujuan', placeholder='Mis. presentasi cash management & payroll ke CFO.')
        rec = [p for p in store.prod[store.prod.company_id == cid].sort_values('rank_produk').product_id][:2]
        produk = st.multiselect('Produk yang dibawa', list(PNAME), default=[p for p in rec if p in PNAME], format_func=fmt_prod, key=f'pj_p_{cid}')
    with b:
        x1, x2, x3 = st.columns([1.3, 1, 1])
        tgl = x1.date_input('Usulan tanggal', date.today() + timedelta(days=3), format='DD/MM/YYYY')
        jm = x2.time_input('Mulai', time(10, 0), step=900)
        js = x3.time_input('Selesai', time(11, 30), step=900)
        kanal = st.selectbox('Kanal', ['Kunjungan', 'Rapat internal', 'Telepon'])
        _, sug, _ = T.suggest(tujuan, produk)
        divs = st.multiselect('Ajak divisi mendampingi', list(T.DIVISI), default=sug, format_func=fmt_div, key=f'pj_d_{"-".join(sug)}',
                              help='Saran dari produk yang dibawa & tujuan kunjungan. Divisi menerima tiket setelah supervisor menyetujui.')
        catatan = st.text_input('Catatan untuk supervisor', key='pj_cat')
        if c.pred_class == 'High' and any(p in ('P06', 'P07') for p in produk):
            st.markdown("<div class='egi-warn'>Risiko High: produk kredit ditunda. Pertimbangkan hanya produk non-kredit.</div>", unsafe_allow_html=True)
    if st.button('Ajukan ke supervisor', type='primary'):
        if not tujuan.strip():
            st.error('Isi tujuan kunjungan.')
        elif js <= jm:
            st.error('Jam selesai harus setelah jam mulai.')
        else:
            T.submit_visit(rm_id=owner, company_id=cid, nama=store.co.name.get(cid, cid), mulai=datetime.combine(tgl, jm), selesai=datetime.combine(tgl, js),
                           kanal=kanal, tujuan=tujuan.strip(), produk=produk, divs=divs, catatan=catatan.strip(), user=user['username'])
            ss.pop('pj_company', None)
            st.success('Pengajuan terkirim. Setelah disetujui supervisor, jadwal masuk ke Kalender kunjungan dan divisi pendamping menerima tiket.')

    st.markdown('#### Pengajuan saya' if user['role'] == 'rm' else '#### Semua pengajuan')
    lst = pj if user['role'] == 'supervisor' else pj[pj.rm_id == user['rm_id']]
    if lst.empty:
        st.caption('Belum ada pengajuan.')
    for r in lst.sort_values('dibuat_pada', ascending=False).head(30).to_dict('records'):
        tone = {'Diajukan': ('#FBEFD6', '#7A4E00'), 'Disetujui': ('#E4F1EA', '#17613F'), 'Ditolak': ('#FADFDB', '#9A2416')}.get(r['status'], ('#EEF0F3', '#374151'))
        with st.expander(f"{r['status']} · {r['judul']} · {r['usulan_mulai'][:16].replace('T', ' ')} · {r['rm_id']}"):
            st.markdown(ui.badge(r['status'], *tone) + f" <span class='egi-muted'>{r['kanal']}</span><br>{ui.esc(r['isi']).replace(chr(10), '<br>')}", unsafe_allow_html=True)
            show_thread(r)
            if r['status'] == 'Diajukan' and auth.can_edit(r['rm_id']) and st.button('Batalkan pengajuan', key=f"cx_{r['id']}"):
                T.reply(r['id'], user['username'], 'Dibatalkan oleh RM', 'Dibatalkan'); st.rerun()
