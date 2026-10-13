"""Konteks bersama antar-halaman: RM aktif, fokus (perusahaan / kecamatan), jadwal ke Kalender kunjungan."""
from __future__ import annotations

import streamlit as st

from datetime import datetime

from . import auth, llm, tindak
from . import kalender as K
from .ui import esc

PAGE = {'overview': 'views/1_overview.py', 'prioritas': 'views/2_prioritas.py', 'profil': 'views/3_profil.py', 'wilayah': 'views/4_wilayah.py',
        'prospect': 'views/5_prospect.py', 'copilot': 'views/6_copilot.py', 'kinerja': 'views/7_kinerja.py', 'metodologi': 'views/8_metodologi.py',
        'kalender': 'views/9_kalender.py', 'tindak': 'views/10_tindak_lanjut.py', 'koordinasi': 'views/11_koordinasi.py'}


def init(store):
    ss = st.session_state
    rms = sorted(store.co.rm_id.dropna().unique())
    ss.setdefault('rm', 'RM-017' if 'RM-017' in rms else rms[0])
    ss.setdefault('focus_company', None)
    ss.setdefault('focus_district', None)
    ss.setdefault('plan', [])               # [{'id','nama','jenis','catatan'}]
    ss.setdefault('chat', [])
    ss.setdefault('agent_result', None)
    q = st.query_params
    if 'company' in q and q['company'] in store.co.index:
        ss.focus_company = q['company']
    return rms


def go(page_key):
    st.switch_page(PAGE[page_key])


def focus_company(cid, open_profile=True):
    st.session_state.focus_company = cid
    st.query_params['company'] = cid
    if open_profile:
        go('profil')


def focus_district(d, open_page=None):
    st.session_state.focus_district = d
    if open_page:
        go(open_page)


HARI_PENDEK = ['Sen', 'Sel', 'Rab', 'Kam', 'Jum', 'Sab', 'Min']
BULAN = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des']


def when(iso):
    m = datetime.fromisoformat(iso)
    return f"{HARI_PENDEK[m.weekday()]} {m.day} {BULAN[m.month - 1]} {m:%H.%M}"


def _saved(store, cid, status, row, sumber, rerun=True):
    """Catat hasil simpan: kotak konfirmasi di sidebar, toast, audit."""
    ss = st.session_state
    name = store.co.name.get(cid, cid)
    if status == 'gagal':
        st.toast(row); return None
    ss.sched_notice = {'id': row['id'], 'nama': name, 'mulai': row['mulai'], 'kanal': row['kanal'], 'baru': status == 'baru'}
    ss._toast = f"{'Dijadwalkan' if status == 'baru' else 'Sudah terjadwal'}: {name} · {row['kanal'].lower()} {when(row['mulai'])}"
    if status == 'baru':
        from . import data
        data.audit('jadwalkan', rm=row['rm_id'], company=cid, mulai=row['mulai'], sumber=sumber)
    if rerun:
        st.rerun()
    return row


def schedule_now(store, cid, catatan='', sumber='Copilot', prefer=None, rerun=True):
    """Tanpa dialog: untuk tindakan yang sudah disetujui RM di tempat lain (mis. kartu usulan agen Copilot)."""
    status, row = K.schedule(store, st.session_state.rm, cid, auth.current()['username'], catatan, sumber, prefer)
    return _saved(store, cid, status, row, sumber, rerun)


def _close_dialog():
    st.session_state.pop('sched_dlg', None)


@st.dialog('Jadwalkan kunjungan', width='large', on_dismiss=_close_dialog)
def _schedule_dialog(store, cid, catatan, sumber, prefer):
    from datetime import time as dtime, timedelta
    from . import agent
    ss = st.session_state
    rm = K.owner(store, ss.rm, cid)
    c = store.cox.loc[cid] if cid in store.cox.index else None
    name = store.co.name.get(cid, cid)
    st.markdown(f"**{esc(name)}** <span class='egi-muted'>{cid} · {c.segment if c is not None else ''} · Kec. {store.co.district.get(cid, '—')}"
                + (f" · {rm}" if rm else '') + '</span>', unsafe_allow_html=True)
    if not rm:
        rms = sorted(store.co.rm_id.dropna().unique())
        rm = st.selectbox('Untuk RM', rms, help='Prospect ini belum punya RM; pilih RM yang akan menjadwalkan.')
    blocked = None
    who, why = K.holder(K.load(), cid)
    if who and who != rm:
        blocked = (f"{name} dipegang {who} ({why}). Satu perusahaan hanya ditangani satu RM"
                   + ('.' if store.cox.is_client.get(cid, False) else '; minta supervisor memindahkan klaim bila perlu.'))
        st.error(blocked)
    ex = K.existing(rm, cid)
    if len(ex):
        e = ex.iloc[0]
        st.info(f"Sudah terjadwal: {e.kanal.lower()} {when(e.mulai)}" + (f" · {len(ex) - 1} jadwal lain" if len(ex) > 1 else '')
                + '. Simpan di bawah hanya bila memang perlu jadwal tambahan (mis. tindak lanjut).')
    kanal0 = K.default_kanal(store, cid)
    dur0 = K.R.DURASI_MENIT.get(kanal0, 60)
    sug = K.suggest_slots(store, rm, cid, dur0, 3, prefer)
    labels = [f"{when(s.isoformat())} · {kanal0} — {why}" for s, why in sug] + ['Atur sendiri…']
    pick = st.radio('Waktu', labels, index=0, key=f'dlg_pick_{cid}',
                    captions=['saran terbaik: rute paling efisien'] + [''] * (len(labels) - 1) if sug else None)
    if pick == 'Atur sendiri…' or not sug:
        base = sug[0][0] if sug else datetime.now().replace(minute=0, second=0, microsecond=0) + timedelta(days=1)
        x1, x2 = st.columns(2)
        tgl = x1.date_input('Tanggal', base.date(), min_value=datetime.now().date(), format='DD/MM/YYYY', key=f'dlg_d_{cid}')
        jam = x2.time_input('Jam mulai', base.time(), step=900, key=f'dlg_t_{cid}')
        y1, y2 = st.columns(2)
        kanal = y1.selectbox('Kanal', K.KANAL, index=K.KANAL.index(kanal0), key=f'dlg_k_{cid}')
        dur = y2.number_input('Durasi (menit)', 15, 240, int(K.R.DURASI_MENIT.get(kanal, 60)), 15, key=f'dlg_m_{cid}_{kanal}')   # ganti kanal → durasi default kanal itu
        start = datetime.combine(tgl, jam)
        if start.weekday() >= 5:
            st.warning('Tanggal ini akhir pekan.')
        clash = K.overlaps(rm, start, dur)
        if len(clash):
            blocked = blocked or 'bentrok'
            st.error('Bertabrakan dengan: ' + '; '.join(f"{r.judul} ({when(r.mulai)})" for r in clash.itertuples()) + '. Pilih jam lain.')
    else:
        start, kanal, dur = sug[labels.index(pick)][0], kanal0, dur0
    if not catatan:
        pf = agent.candidates(store, rm) if rm else None
        catatan = agent._purpose(store, cid, pf.loc[cid].to_dict())[0] if pf is not None and cid in pf.index else ''
    note = st.text_area('Tujuan / catatan', catatan, height=90, key=f'dlg_n_{cid}')
    b1, b2 = st.columns(2)
    if b1.button('Batal', use_container_width=True, key=f'dlg_x_{cid}'):
        _close_dialog(); st.rerun()
    if b2.button('Simpan ke kalender', type='primary', use_container_width=True, key=f'dlg_ok_{cid}', disabled=bool(blocked)):
        status, row = K.schedule(store, rm, cid, auth.current()['username'], note, sumber, start=start, kanal=kanal, minutes=dur)
        _close_dialog(); _saved(store, cid, status, row, sumber)


def schedule_visit(store, cid, catatan='', sumber=None, prefer=None):
    """Tombol 'Jadwalkan' di semua halaman: buka dialog dengan saran slot (sadar rute); jadwal baru tersimpan setelah RM menekan Simpan.
    Dialog yang terbuka disimpan di session dan digambar dari sidebar() di setiap render sampai Simpan/Batal/ditutup."""
    st.session_state.sched_dlg = {'cid': cid, 'catatan': catatan, 'sumber': sumber or 'Dashboard', 'prefer': prefer}
    st.rerun()


add_to_plan = schedule_visit          # nama lama (dipakai halaman lama)


def open_calendar(event_id=None, mulai=None):
    ss = st.session_state
    if event_id:
        ss.cal_sel, ss.cal_new = event_id, None
    if mulai:
        ss.cal_date = mulai[:10]
    go('kalender')


def company_actions(store, cid, key, show_profile=True, sumber='Dashboard'):
    """Tombol seragam untuk setiap perusahaan: profil · jadwalkan · Copilot."""
    cols = st.columns(3 if show_profile else 2)
    i = 0
    if show_profile:
        if cols[i].button('Lihat profil', key=f'p_{key}_{cid}', use_container_width=True):
            focus_company(cid)
        i += 1
    if cols[i].button('📅 Jadwalkan', key=f'r_{key}_{cid}', use_container_width=True, help='Masukkan ke Kalender kunjungan (slot kosong terdekat)'):
        schedule_visit(store, cid, sumber=sumber)
    if cols[i + 1].button('Copilot', key=f'c_{key}_{cid}', use_container_width=True):
        st.session_state.focus_company = cid
        st.session_state.copilot_task = 'brief'
        go('copilot')


def sidebar(store, rms):
    ss = st.session_state
    if ss.get('_toast'):
        st.toast(ss.pop('_toast'))
    dlg = ss.get('sched_dlg')
    if dlg and dlg['cid'] in store.co.index:
        _schedule_dialog(store, dlg['cid'], dlg['catatan'], dlg['sumber'], dlg['prefer'])
    with st.sidebar:
        st.markdown('<div style="display:flex;gap:10px;align-items:center;margin-bottom:8px"><div style="width:34px;height:34px;border-radius:8px;'
                    'background:#C2500A;color:#fff;display:flex;align-items:center;justify-content:center;font-weight:700">EG</div>'
                    '<div><strong>Growth Intelligence</strong><br><span style="font-size:12px">Ruang kerja RM</span></div></div>', unsafe_allow_html=True)
        n = lambda r: int((store.co.rm_id == r).sum())
        user = auth.current()
        if user['role'] == 'supervisor':
            opts = rms + ['Semua RM']
            ss.rm = st.selectbox('Lihat sebagai', opts, index=opts.index(ss.rm) if ss.rm in opts else len(rms), format_func=lambda r: f'{r} · {n(r)} nasabah' if r != 'Semua RM' else r)
        elif user['role'] == 'divisi':
            ss.rm = 'Semua RM'
            st.markdown(f"**{esc(user['nama'])}**")
        else:
            ss.rm = user['rm_id']
            st.markdown(f"**{esc(ss.rm)}** · {n(ss.rm)} nasabah")
        c1, c2 = st.columns(2)
        with c1.popover('Akun', use_container_width=True):
            st.caption(f"Masuk sebagai **{user['username']}** ({user['role']})")
            auth.change_password_form()
        if c2.button('Keluar', use_container_width=True):
            auth.logout()
        cnt = {k: v for k, v in tindak.badge_counts(user).items() if v}
        if cnt:                                  # pemberitahuan: feedback tertunda, kegiatan terlambat, pengajuan menunggu, tiket baru
            st.markdown(' · '.join(f"<span style='color:#F6B48A;font-weight:600'>{v}</span> {k}" for k, v in cnt.items()), unsafe_allow_html=True)
            if user['role'] != 'divisi' and st.button('Buka tindak lanjut', use_container_width=True):
                ss.tl_tab = ('Feedback kunjungan' if cnt.get('feedback tertunda') else 'Progress kegiatan' if cnt.get('kegiatan terlambat')
                             else 'Pengajuan kunjungan' if cnt.get('pengajuan menunggu') else 'Feedback kunjungan')
                go('tindak')
        st.divider()
        if user['role'] == 'divisi':
            st.caption('Data per 30 Jun 2026 · data sintetis v8')
            return
        st.markdown('**Fokus**')
        if ss.focus_company:
            c1, c2 = st.columns([5, 1])
            c1.markdown(f"{esc(store.co.name.get(ss.focus_company, ss.focus_company))}<br><span style='font-size:11px'>{ss.focus_company}</span>", unsafe_allow_html=True)
            if c2.button('×', key='clr_c', help='Lepas fokus perusahaan'):
                ss.focus_company = None; st.query_params.clear(); st.rerun()
        if ss.focus_district:
            c1, c2 = st.columns([5, 1])
            c1.markdown(f'Kecamatan {esc(ss.focus_district)}')
            if c2.button('×', key='clr_d', help='Lepas fokus kecamatan'):
                ss.focus_district = None; st.rerun()
        if not ss.focus_company and not ss.focus_district:
            st.caption('tidak ada')
        note = ss.get('sched_notice')
        if note:
            with st.container(border=True):
                st.markdown(f"<span style='font-size:13px'>{'✅ Dijadwalkan' if note['baru'] else '📅 Sudah terjadwal'}<br><b>{esc(note['nama'])}</b><br>"
                            f"{note['kanal']} · {when(note['mulai'])}</span>", unsafe_allow_html=True)
                c1, c2 = st.columns(2)
                if c1.button('Buka', key='sn_open', use_container_width=True, help='Buka di Kalender kunjungan'):
                    ss.sched_notice = None; open_calendar(note['id'], note['mulai'])
                if note['baru']:
                    if c2.button('Batalkan', key='sn_undo', use_container_width=True, help='Hapus jadwal ini dari kalender'):
                        K.delete(note['id']); ss.sched_notice = None; ss._toast = f"Dibatalkan: {note['nama']}"; st.rerun()
                elif c2.button('Tutup', key='sn_close', use_container_width=True):
                    ss.sched_notice = None; st.rerun()
        up = K.upcoming(ss.rm, 7)
        st.markdown(f"**Jadwal 7 hari** · {len(up)}")
        for r in up.head(6).itertuples():
            st.markdown(f"<span style='font-size:12px'>{when(r.mulai)} · {'📞 ' if r.kanal == 'Telepon' else ''}{esc(r.judul.rsplit(' (', 1)[0])}</span>",
                        unsafe_allow_html=True)
        if len(up) > 6:
            st.caption(f'+{len(up) - 6} lainnya')
        if not len(up):
            st.caption('Belum ada. Klik 📅 Jadwalkan di daftar mana pun.')
        if st.button('Buka Kalender kunjungan', use_container_width=True):
            open_calendar()
        st.divider()
        cfg = llm.config()
        st.caption(f"Copilot: {'LLM · ' + cfg['provider'] + ' · ' + cfg['model'] if cfg['enabled'] else 'mode template (tanpa LLM)'}")
        st.caption('Data per 30 Jun 2026 · data sintetis v8')
