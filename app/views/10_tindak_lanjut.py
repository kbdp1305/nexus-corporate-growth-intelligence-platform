import json
from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st

from egi import agen_tindak as A, auth, data, kalender as K, llm, state, tindak as T, ui

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

        a, b = st.columns([1, 1.3], gap='large')
        pk = f'fb_plan_{eid}'                                       # rencana agen tersimpan: {'sig': isian saat dibuat, 'hasil': keluaran agen}

        def buat_rencana(nonce_step=0):
            ss[f'fb_nonce_{eid}'] = ss.get(f'fb_nonce_{eid}', 0) + nonce_step
            ss[f'fb_go_{eid}'] = True

        with a, st.container(border=True):
            ui.section(1, 'Hasil kunjungan', 'Isi hasil kunjungan, lalu klik Buat Rencana')
            hasil = st.radio('Hasil', T.HASIL, format_func=T.HASIL_ID.get, horizontal=True, key=f'fb_h_{eid}')
            produk = st.multiselect('Produk yang dibahas', list(PNAME), format_func=fmt_prod, key=f'fb_p_{eid}')
            catatan = st.text_area('Catatan hasil kunjungan', key=f'fb_c_{eid}', height=150,
                                   placeholder='Mis. Bertemu CFO. Ada rencana ekspansi gudang tahun depan, tertarik payroll untuk 120 karyawan, '
                                               'tapi keberatan dengan biaya administrasi. Minta simulasi minggu depan.')
            keberatan = st.text_input('Keberatan nasabah (opsional)', key=f'fb_k_{eid}')
            st.caption(f"Produk dimiliki: {', '.join(held) or '—'} · rekomendasi model: {', '.join(rec) or '—'}")
            st.button('Buat Rencana', key=f'fb_make_{eid}', type='primary', use_container_width=True, on_click=buat_rencana,
                      disabled=not catatan.strip(), help='Agen membaca hasil kunjungan, memeriksa data nasabah & produk, lalu menyarankan langkah berikutnya.'
                      if catatan.strip() else 'Isi catatan hasil kunjungan dulu.')
        hit, sug, hold = T.suggest(catatan, produk)
        riwayat = T.history(cid, eid)
        ulang = T.needs_reconsider(hasil, catatan, keberatan)
        isian = [hasil, catatan, keberatan, sorted(produk)]
        if ss.pop(f'fb_go_{eid}', False) and catatan.strip():
            with st.spinner('Agen membaca catatan dan menyusun rencana…'):
                ss[pk] = {'sig': isian, 'hasil': A.run(store, company_id=cid, rm_id=ev['rm_id'], hasil=hasil, catatan=catatan, keberatan=keberatan,
                                                       produk=produk, isu=hit, hold=hold, ulang=ulang, riwayat=riwayat, nonce=ss.get(f'fb_nonce_{eid}', 0))}
        hasil_agen = (ss.get(pk) or {}).get('hasil')
        ada = hasil_agen is not None
        usang = ada and ss[pk]['sig'] != isian
        rencana = hasil_agen['rencana'] if ada else {'langkah': [], 'keberatan': [], 'pesan_divisi': '', 'divisi': [], 'perlu_jadwal_ulang': False,
                                                     'pemahaman': '', 'pertanyaan_kunci': [], 'jadwal': {'hari': 7, 'jam': '10:00', 'kanal': 'Kunjungan', 'tujuan': ''}}
        ulang = ulang or rencana['perlu_jadwal_ulang']
        jd = rencana['jadwal']
        when = T.free_slot(ev['rm_id'], datetime.combine(date.today() + timedelta(days=jd['hari']), time.fromisoformat(jd['jam'])),
                           K.R.DURASI_MENIT.get(jd['kanal'], 60))

        def follow(key, auto):                                    # isian ikut agen selama belum diubah manual
            if key not in ss or ss[key] == ss.get(f'_auto_{key}'):
                ss[key] = auto
            ss[f'_auto_{key}'] = auto

        sig = abs(hash(json.dumps(rencana['langkah'], ensure_ascii=False, default=str))) % 10**8   # rekomendasi baru → centang direset
        mk = f'fb_manual_{eid}'
        ss.setdefault(mk, [])
        DIV_KEY = {v: k for k, v in T.DIVISI.items()}
        OWNERS = ['RM'] + list(T.DIVISI.values())
        tgt = lambda d: ui.badge('hari ini' if d == 0 else f'{d} hari', *(('#FBEFD6', '#7A4E00') if d <= 2 else ('#EEF0F3', '#374151')))
        # divisi koordinasi: saran AI → nama divisi (str); kegiatan manual → daftar kunci divisi
        dnames = lambda k: [T.DIVISI.get(d, d) for d in k['divisi']] if isinstance(k.get('divisi'), list) else ([k['divisi']] if k.get('divisi') else [])
        koor = lambda k: ''.join(ui.badge(f'Koordinasi · {d}', '#EDE9F6', '#4C3A86') for d in dnames(k))

        def tambah_manual():
            t = str(ss.get(f'fb_mt_{eid}', '')).strip()
            if t:
                dv = list(ss.get(f'fb_mdv_{eid}') or [])
                koord = {} if not dv else {'prioritas': ss.get(f'fb_mpr_{eid}', 'Normal'), 'tenggat': ss.get(f'fb_mtg_{eid}', date.today() + timedelta(days=5)),
                                           'pesan': str(ss.get(f'fb_mm_{eid}', '')).strip()}
                ss[mk] = ss[mk] + [{'judul': A.judul_singkat(t), 'aksi': t, 'pemilik': ss.get(f'fb_mp_{eid}', 'RM'), 'divisi': dv,
                                    'tenggat_hari': int(ss.get(f'fb_mh_{eid}', 3)), 'alasan': '', 'sumber': 'Manual', **koord}]
                ss[f'fb_mt_{eid}'] = ''; ss[f'fb_mm_{eid}'] = ''; ss[f'fb_mdv_{eid}'] = []; ss.pop(f'fb_mm_{eid}_mode', None)

        def hapus_manual(i):
            ss[mk] = [m for j, m in enumerate(ss[mk]) if j != i]

        def susun(target, divisi, kegiatan_teks, cadangan=''):
            """Tombol "Susun permintaan dengan AI": isi kolom permintaan (target) dari hasil kunjungan + kegiatan yang perlu koordinasi."""
            txt, md = A.susun_permintaan(store, company_id=cid, hasil=hasil, catatan=catatan, keberatan=keberatan, produk=produk,
                                         divisi=divisi, kegiatan=kegiatan_teks, cadangan=cadangan)
            ss[target] = txt
            ss[f'{target}_mode'] = md

        with b:
            # ---------------- 2 · rencana lanjutan: ringkasan, saran agen (centang), koordinasi divisi
            with st.container(border=True):
                ui.section(2, 'Rencana lanjutan', 'Centang langkah yang disarankan; yang dicentang masuk ke Kegiatan selanjutnya')
                disetujui = []
                if not ada:
                    st.markdown("<div class='egi-empty'>"
                                "<div class='s'><span class='i'>1</span><b>Isi hasil kunjungan</b>Siapa yang ditemui, apa yang diminta, kebutuhan, keberatan, kapan bisa dihubungi lagi.</div>"
                                "<div class='s'><span class='i'>2</span><b>Klik Buat Rencana</b>Agen membaca catatan, memeriksa data nasabah & produk, lalu menyarankan langkah.</div>"
                                "<div class='s'><span class='i'>3</span><b>Centang & simpan</b>Centang saran yang disetujui atau tambah kegiatan sendiri, lalu simpan.</div>"
                                "</div>", unsafe_allow_html=True)
                else:
                    if usang:
                        st.markdown("<div class='egi-warn'>Hasil kunjungan berubah sejak rencana dibuat. Klik <b>Buat Rencana</b> lagi untuk memperbarui saran.</div>",
                                    unsafe_allow_html=True)
                    if rencana['keberatan']:
                        st.markdown("<div class='egi-sec' style='margin-top:4px'>Ringkasan</div>"
                                    + ''.join(f"<div class='egi-obj'><span class='k'>{ui.esc(k['keberatan'])}</span><br>{ui.esc(k['respon'])}</div>"
                                              for k in rencana['keberatan']), unsafe_allow_html=True)
                    st.markdown("<div class='egi-sec' style='margin-bottom:8px'>Langkah yang disarankan</div>", unsafe_allow_html=True)
                    for i, l in enumerate(rencana['langkah'], 1):
                        dv = l['pemilik'] if l['pemilik'] in DIV_KEY else ''
                        c0, c1 = st.columns([0.06, 0.94], gap='small', vertical_alignment='top')
                        ok = c0.checkbox(f'Setujui langkah {i}', key=f'fb_ok_{eid}_{sig}_{i}', label_visibility='collapsed')
                        c1.markdown(f"<div class='egi-rec{' on' if ok else ''}'><span class='no'>{i}</span><div>"
                                    f"<b>{ui.esc(l.get('judul') or A.judul_singkat(l['aksi']))}</b><div class='d'>{ui.esc(l['aksi'])}</div>"
                                    f"<div class='mt'>{ui.badge(l['pemilik'], '#EEF2F9', ui.NAVY2)}{tgt(l['tenggat_hari'])}</div>"
                                    + (f"<div class='al'>{ui.esc(l['alasan'])}</div>" if l.get('alasan') else '') + '</div></div>', unsafe_allow_html=True)
                        if ok:
                            disetujui.append({**l, 'divisi': dv, 'sumber': 'Saran AI'})
                kegiatan = disetujui + ss[mk]

                # koordinasi dengan divisi: baru muncul setelah Buat Rencana (tiket dikirim saat feedback disimpan)
                divs, prio, tenggat, pesan = [], 'Normal', '', ''
                if ada:
                    st.markdown("<div class='egi-sec'>Koordinasi dengan divisi</div>", unsafe_allow_html=True)
                    if hit:
                        st.markdown('Isu terdeteksi dari catatan: ' + ''.join(ui.badge(T.issues().issue_name.get(i, i), '#EEF2F9', ui.NAVY2) for i in hit),
                                    unsafe_allow_html=True)
                    if hold:
                        st.markdown("<div class='egi-warn'>Ada isu legal / tekanan likuiditas: produk kredit ditahan, libatkan Legal atau Risiko Kredit dulu.</div>",
                                    unsafe_allow_html=True)
                    # kegiatan manual yang memilih divisi punya tiketnya sendiri (diisi di Kegiatan selanjutnya)
                    sug = list(dict.fromkeys(sug + rencana['divisi'] + [DIV_KEY[k['divisi']] for k in disetujui if k.get('divisi') in DIV_KEY]))
                    divs = st.multiselect('Kirim tiket ke divisi', list(T.DIVISI), default=sug, format_func=fmt_div, key=f'fb_d_{eid}_{"-".join(sug)}',
                                          help='Saran dari isu di catatan, produk yang dibahas, dan saran agen yang dicentang; bisa diubah.')
                    if divs:
                        y1, y2 = st.columns(2)
                        prio = y1.selectbox('Prioritas', T.PRIORITAS, index=1 if hasil == 'Converted' or hold else 0, key=f'fb_pr_{eid}')
                        tenggat = y2.date_input('Tenggat', date.today() + timedelta(days=5), format='DD/MM/YYYY', key=f'fb_tg_{eid}')
                        pesan = st.text_area('Permintaan ke divisi', key=f'fb_m_{eid}', height=130,
                                             placeholder='Tulis permintaan ke divisi, atau klik "Susun permintaan dengan AI" di bawah.')
                        st.button('Susun permintaan dengan AI', key=f'fb_ai_{eid}', on_click=susun, use_container_width=True,
                                  args=(f'fb_m_{eid}', divs, [k['aksi'] for k in disetujui if k.get('divisi')] or [k['aksi'] for k in disetujui], rencana['pesan_divisi']),
                                  help='AI menyusun permintaan dari hasil kunjungan, divisi yang dipilih, dan langkah yang dicentang; hasilnya bisa diedit.')
                        if ss.get(f'fb_m_{eid}_mode') == 'tanpa LLM':
                            st.caption('LLM tidak aktif atau jawabannya memuat angka di luar data: draf disusun dari rencana agen.')

                    if hasil_agen['info']:
                        st.caption(hasil_agen['info'])
                    elif hasil_agen['mode'] != 'LLM' and not llm.config()['enabled']:
                        st.caption('LLM belum aktif: saran disusun tanpa AI. Isi LLM_PROVIDER & API key di .env agar agen memahami catatan secara utuh.')
                    if rencana['pertanyaan_kunci']:
                        with st.expander('Saran pertanyaan untuk kunjungan selanjutnya'):
                            st.markdown('\n'.join(f'- {ui.esc(q)}' for q in rencana['pertanyaan_kunci']))

            # ---------------- kegiatan selanjutnya: saran yang dicentang + isian manual RM (inilah yang disimpan)
            with st.container(border=True):
                ui.section('✓', 'Kegiatan selanjutnya', 'Daftar yang akan disimpan: saran AI yang dicentang dan kegiatan yang Anda tambahkan',
                           ui.badge(f'{len(kegiatan)} kegiatan', '#E4F1EA', '#17613F') if kegiatan else '')
                if not kegiatan:
                    st.caption('Belum ada kegiatan. Centang langkah yang disarankan, atau tambahkan kegiatan sendiri di bawah.')
                n_ai = len(disetujui)
                for i, k in enumerate(kegiatan, 1):
                    src = ui.badge('Saran AI', '#EEF2F9', ui.NAVY2) if k['sumber'] == 'Saran AI' else ui.badge('Manual', '#FDEBDD', '#9A3412')
                    tiket = (ui.badge(f"Prioritas {k['prioritas']}", '#FADFDB', '#9A2416') if k.get('prioritas') in ('Tinggi', 'Mendesak') else '') \
                        + (ui.badge(f"tiket s.d. {k['tenggat']:%d/%m}", '#EEF0F3', '#374151') if k.get('tenggat') else '')
                    html = (f"<div class='egi-act'><span class='no'>{i}</span><div><b>{ui.esc(k['aksi'])}</b>"
                            f"<div class='mt'>{src}{ui.badge(k['pemilik'], '#FFFFFF', ui.NAVY2)}{koor(k)}{tgt(k['tenggat_hari'])}{tiket}</div>"
                            + (f"<div class='al' style='margin-top:4px'>Permintaan: {ui.esc(k['pesan'])}</div>" if k.get('pesan') else '') + '</div></div>')
                    if k['sumber'] == 'Manual':
                        r1, r2 = st.columns([0.9, 0.1], vertical_alignment='center')
                        r1.markdown(html, unsafe_allow_html=True)
                        r2.button('✕', key=f'fb_del_{eid}_{i}', on_click=hapus_manual, args=(i - 1 - n_ai,), help='Hapus kegiatan manual ini')
                    else:
                        st.markdown(html, unsafe_allow_html=True)
                langkah = '\n'.join(f"{i}. {k['aksi']} — {k['pemilik']}" + (f", koordinasi {', '.join(dnames(k))}" if dnames(k) else '') + ', '
                                    + ('hari ini' if k['tenggat_hari'] == 0 else f"dalam {k['tenggat_hari']} hari") for i, k in enumerate(kegiatan, 1))

                st.markdown("<div class='egi-sec'>Tambah kegiatan manual</div>", unsafe_allow_html=True)
                st.text_input('Kegiatan', key=f'fb_mt_{eid}', label_visibility='collapsed',
                              placeholder='Tulis kegiatan sendiri, mis. telepon Bu Rina untuk konfirmasi tanggal rapat direksi')
                m1, m2 = st.columns(2)
                m1.selectbox('Penanggung jawab', OWNERS, key=f'fb_mp_{eid}')
                m2.number_input('Tenggat kegiatan (hari)', min_value=0, max_value=120, value=3, step=1, key=f'fb_mh_{eid}')

                # koordinasi dengan divisi untuk kegiatan manual: sama dengan bagian di Rencana lanjutan
                st.markdown("<div class='egi-sec'>Koordinasi dengan divisi</div>", unsafe_allow_html=True)
                mdv = st.multiselect('Kirim tiket ke divisi', list(T.DIVISI), format_func=fmt_div, key=f'fb_mdv_{eid}',
                                     help='Pilih bila kegiatan ini perlu melibatkan divisi lain; tiket dikirim saat feedback disimpan.')
                n1, n2 = st.columns(2)                                      # selalu tampil; dipakai bila ada divisi yang dipilih
                n1.selectbox('Prioritas', T.PRIORITAS, key=f'fb_mpr_{eid}')
                n2.date_input('Tenggat', date.today() + timedelta(days=5), format='DD/MM/YYYY', key=f'fb_mtg_{eid}')
                st.text_area('Permintaan ke divisi', key=f'fb_mm_{eid}', height=130,
                             placeholder='Tulis permintaan ke divisi, atau pilih divisi lalu klik "Susun permintaan dengan AI" di bawah.')
                st.button('Susun permintaan dengan AI', key=f'fb_mai_{eid}', on_click=susun, use_container_width=True, disabled=not mdv,
                          args=(f'fb_mm_{eid}', list(mdv), [str(ss.get(f'fb_mt_{eid}', '')).strip() or 'tindak lanjut hasil kunjungan']),
                          help='AI menyusun permintaan dari kegiatan yang Anda tulis, divisi yang dipilih, dan hasil kunjungan; hasilnya bisa diedit.'
                          if mdv else 'Pilih divisi di "Kirim tiket ke divisi" dulu.')
                if not mdv:
                    st.caption('Prioritas, tenggat, dan permintaan dipakai bila Anda memilih divisi di atas.')
                elif ss.get(f'fb_mm_{eid}_mode') == 'tanpa LLM':
                    st.caption('LLM tidak aktif atau jawabannya memuat angka di luar data: draf disusun dari isian kunjungan.')
                st.write('')
                st.button('Tambah kegiatan', key=f'fb_add_{eid}', on_click=tambah_manual, use_container_width=True,
                          help='Masukkan kegiatan ini ke daftar di atas (kolom kegiatan harus diisi).')

            # ---------------- jadwal berikutnya
            with st.container(border=True):
                ui.section('◷', 'Jadwal ulang' if ulang else 'Jadwal berikutnya', 'Slot kosong dicari otomatis di kalender ' + ev['rm_id'])
                follow(f'fb_j_{eid}', ada and (hasil in ('Converted', 'Interested') or ulang))
                jadwal = st.toggle('Masukkan ke kalender', key=f'fb_j_{eid}')
                lanjut = None
                if jadwal:
                    follow(f'fb_t_{eid}', when.date()); follow(f'fb_jm_{eid}', when.time()); follow(f'fb_kn_{eid}', jd['kanal'])
                    x1, x2, x3 = st.columns([1.3, 1, 1.2])
                    tgl = x1.date_input('Tanggal', format='DD/MM/YYYY', key=f'fb_t_{eid}')
                    jam = x2.time_input('Jam', step=900, key=f'fb_jm_{eid}')
                    kanal = x3.selectbox('Kanal', K.KANAL, key=f'fb_kn_{eid}')
                    m = datetime.combine(tgl, jam); lanjut = (m, m + timedelta(minutes=K.R.DURASI_MENIT.get(kanal, 60)), kanal)
                    st.markdown(f"<div class='egi-when' style='margin-top:4px'><b>{ui.tanggal(m)} · {m:%H.%M}</b><span>{ui.esc(kanal)}</span>"
                                + (f"<span class='tj'>{ui.esc(jd['tujuan'])}</span>" if jd['tujuan'] else '') + '</div>', unsafe_allow_html=True)
                elif ada:
                    st.caption(f"Saran agen: {ui.tanggal(when)}, {when:%H.%M} · {jd['kanal']}. Nyalakan untuk memasukkannya ke kalender.")
        st.write('')
        manual_tiket = [k for k in ss[mk] if isinstance(k.get('divisi'), list) and k['divisi']]
        n_tiket = len(divs) + sum(len(k['divisi']) for k in manual_tiket)
        if st.button('Simpan feedback' + (f' & kirim {n_tiket} tiket' if n_tiket else ''), type='primary', use_container_width=True):
            if not catatan.strip():
                st.error('Isi catatan hasil kunjungan dulu.')
            else:
                fb, fu, tk = T.save_feedback(store, ev, hasil=hasil, produk=produk, catatan=catatan.strip(), keberatan=keberatan.strip(), isu=hit,
                                             langkah=langkah.strip(), lanjut=lanjut, divs=divs, prioritas=prio, tenggat=tenggat, pesan_divisi=pesan.strip(),
                                             user=user['username'], ulang=ulang)
                nama = store.co.name.get(cid, cid)
                for k in manual_tiket:                             # tiket per kegiatan manual, dengan prioritas/tenggat/permintaannya sendiri
                    tk += T.create_tickets(k['divisi'], jenis='Koordinasi kegiatan', rm_id=ev['rm_id'], company_id=cid,
                                           judul=f"{A.judul_singkat(k['aksi'], 6)} · {nama}",
                                           isi=f"Kegiatan: {k['aksi']}\n" + (f"Permintaan: {k['pesan']}\n" if k.get('pesan') else '')
                                               + f"Hasil kunjungan {ev['mulai'][:10]}: {T.HASIL_ID.get(hasil, hasil)}.",
                                           prioritas=k.get('prioritas', 'Normal'), tenggat=k.get('tenggat', ''), ref=fb, event_id=ev['id'], user=user['username'])
                ss.pop(mk, None)
                tujuan = [fmt_div(d) for d in divs] + [fmt_div(d) for k in manual_tiket for d in k['divisi']]
                ss.fb_done = f"Feedback tersimpan · jadwal ditandai selesai · dicatat ke riwayat nasabah" \
                             + ((' · jadwal ulang masuk kalender' if ulang else ' · tindak lanjut masuk kalender') if fu else '') \
                             + (f" · {len(tk)} tiket ke {', '.join(dict.fromkeys(tujuan))}" if tk else '')
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
