from datetime import date, datetime, time, timedelta

import pandas as pd
import streamlit as st

from egi import auth, data, kalender as K, state, tindak as T, ui

try:
    from streamlit_calendar import calendar as fc
except ImportError:              # komponen opsional: tanpa itu tetap ada tabel + form
    fc = None

store = data.get_store(); ss = st.session_state
user = auth.current()
ui.page_header(f"{ss.rm} · jadwal bersama, tersimpan di outputs/app/calendar.csv", 'Kalender kunjungan')

df = K.for_rm(ss.rm)
today = date.today()
wk0 = today - timedelta(days=today.weekday())
mulai = pd.to_datetime(df.mulai, errors='coerce')
this_week = df[(mulai.dt.date >= wk0) & (mulai.dt.date < wk0 + timedelta(days=7))]
k = st.columns(4)
ui.kpi(k[0], 'Jadwal minggu ini', str(len(this_week[this_week.status != 'Dibatalkan'])), f"{wk0:%d %b} – {wk0 + timedelta(days=6):%d %b}")
ui.kpi(k[1], 'Kunjungan minggu ini', str(int(((this_week.kanal == 'Kunjungan') & (this_week.status == 'Terjadwal')).sum())), 'status terjadwal')
ui.kpi(k[2], 'Akan datang', str(int(((mulai >= pd.Timestamp(datetime.now())) & (df.status == 'Terjadwal')).sum())), 'semua minggu')
ui.kpi(k[3], 'Selesai', str(int((df.status == 'Selesai').sum())), 'ditandai selesai')
st.write('')


def _parse(s):
    """FullCalendar dipakai dengan timeZone UTC agar jam tampil apa adanya; buang zona dari callback."""
    return datetime.fromisoformat(str(s).replace('Z', '+00:00')).replace(tzinfo=None)


def _company_opts():
    mine = list(store.co.index[store.co.rm_id == ss.rm]) if ss.rm != 'Semua RM' else []
    return [''] + mine + [c for c in store.co.index if c not in set(mine)]


def _fmt_co(c):
    return '— tanpa perusahaan —' if not c else f"{store.co.name.get(c, c)} · {c}"


cal_col, side = st.columns([2.3, 1])

# ------------------------------------------------------------------ kalender
with cal_col:
    if fc is None:
        st.markdown("<div class='egi-warn'>Komponen <code>streamlit-calendar</code> belum terpasang: <code>pip install streamlit-calendar</code>. "
                    'Jadwal tetap bisa dikelola lewat form dan tabel.</div>', unsafe_allow_html=True)
    else:
        opts = {'initialView': 'timeGridWeek', 'timeZone': 'UTC', 'locale': 'id', 'firstDay': 1, 'height': 640, 'nowIndicator': True,
                'slotMinTime': '07:00:00', 'slotMaxTime': '19:00:00', 'allDaySlot': False, 'selectable': True, 'editable': True,
                'headerToolbar': {'left': 'prev,next today', 'center': 'title', 'right': 'dayGridMonth,timeGridWeek,timeGridDay,listWeek'},
                'buttonText': {'today': 'Hari ini', 'month': 'Bulan', 'week': 'Minggu', 'day': 'Hari', 'list': 'Daftar'}}
        if ss.get('cal_date'):                         # dibuka dari tombol 'Buka' (jadwal baru di sidebar): lompat ke minggunya
            opts['initialDate'] = ss.cal_date
        res = fc(events=K.to_fullcalendar(df, show_rm=ss.rm == 'Semua RM'), options=opts, key=f"cal_{ss.rm}_{ss.get('cal_date', '')}_{ss.get('cal_ver', 0)}",
                 custom_css='.fc-event-title{font-weight:600}.fc .fc-toolbar-title{font-size:1.15rem}',
                 callbacks=['dateClick', 'eventClick', 'eventChange', 'select'])
        cb = (res or {}).get('callback')
        sig = str(res)
        if cb and ss.get('_cal_sig') != sig:            # proses tiap callback sekali
            ss._cal_sig = sig
            if cb == 'dateClick':
                ss.cal_sel, ss.cal_new = None, (_parse(res['dateClick']['date']), None)
            elif cb == 'select':
                ss.cal_sel, ss.cal_new = None, (_parse(res['select']['start']), _parse(res['select']['end']))
            elif cb == 'eventClick':
                ss.cal_sel, ss.cal_new = res['eventClick']['event']['id'], None
            elif cb == 'eventChange':                    # geser / ubah durasi
                ev = res['eventChange']['event']
                row = df[df.id == ev['id']]
                if len(row) and auth.can_edit(row.iloc[0].rm_id):
                    r = row.iloc[0].to_dict()
                    r['mulai'] = _parse(ev['start']).isoformat(timespec='minutes')
                    if ev.get('end'):
                        r['selesai'] = _parse(ev['end']).isoformat(timespec='minutes')
                    _, _, rej = K.upsert([r], user['username'])
                    if rej:                               # ditolak: kalender dirender ulang ke posisi semula
                        ss.cal_ver = ss.get('cal_ver', 0) + 1; ss._toast = f'Tidak dipindah: {rej[0][1]}'
                    else:
                        data.audit('kalender_geser', user=user['username'], id=r['id'], mulai=r['mulai']); ss._toast = 'Jadwal dipindah'
                else:
                    ss.cal_ver = ss.get('cal_ver', 0) + 1; ss._toast = 'Anda hanya bisa mengubah jadwal milik sendiri'
                st.rerun()
        st.caption('Klik tanggal/jam untuk menambah · klik jadwal untuk detail · seret jadwal untuk memindah. '
                   'Warna: oranye kunjungan, biru tua telepon, hijau selesai, abu-abu dibatalkan.')

# ------------------------------------------------------------------ panel kanan: detail / tambah
with side:
    sel = ss.get('cal_sel')
    row = df[df.id == sel] if sel else df.iloc[0:0]
    if len(row):
        r = row.iloc[0].to_dict()
        editable = auth.can_edit(r['rm_id'])
        st.markdown(f"**{ui.esc(r['kanal'])}: {ui.esc(r['judul'])}**<br><span class='egi-muted'>{r['rm_id']} · {r['sumber']} · oleh {r['dibuat_oleh']}</span>",
                    unsafe_allow_html=True)
        with st.form(f'ev_{sel}'):
            m0 = datetime.fromisoformat(r['mulai']); s0 = datetime.fromisoformat(r['selesai']) if r['selesai'] else m0 + timedelta(hours=1)
            tgl = st.date_input('Tanggal', m0.date(), format='DD/MM/YYYY', disabled=not editable)
            c1, c2 = st.columns(2)
            jm = c1.time_input('Mulai', m0.time(), step=900, disabled=not editable)
            js = c2.time_input('Selesai', s0.time(), step=900, disabled=not editable)
            status = st.selectbox('Status', K.STATUS, index=K.STATUS.index(r['status']) if r['status'] in K.STATUS else 0, disabled=not editable)
            lok = st.text_input('Lokasi', r['lokasi'], disabled=not editable)
            cat = st.text_area('Catatan', r['catatan'], height=140, disabled=not editable)
            save = st.form_submit_button('Simpan perubahan', type='primary', use_container_width=True, disabled=not editable)
        if save:
            r.update(mulai=datetime.combine(tgl, jm).isoformat(timespec='minutes'), selesai=datetime.combine(tgl, js).isoformat(timespec='minutes'),
                     status=status, lokasi=lok, catatan=cat)
            _, _, rej = K.upsert([r], user['username'])
            if rej:
                st.error(f'Tidak disimpan: {rej[0][1]}')
            else:
                data.audit('kalender_ubah', user=user['username'], id=sel, status=status)
                ss._toast = 'Tersimpan'; ss.cal_ver = ss.get('cal_ver', 0) + 1; st.rerun()
        b1, b2, b3 = st.columns(3)
        if r['company_id'] in store.co.index and b1.button('Profil', use_container_width=True):
            state.focus_company(r['company_id'])
        if editable and b2.button('Hapus', use_container_width=True):
            K.delete(sel); data.audit('kalender_hapus', user=user['username'], id=sel); ss.cal_sel = None; st.rerun()
        if b3.button('Tutup', use_container_width=True):
            ss.cal_sel = None; st.rerun()
        fb = T.FEEDBACK.load(); fb = fb[fb.event_id == sel]
        if len(fb):
            f0 = fb.iloc[0]
            st.markdown(f"<div class='egi-card'><b>Feedback:</b> {ui.esc(T.HASIL_ID.get(f0.hasil, f0.hasil))}<br>{ui.esc(f0.catatan)}"
                        + (f"<br><span class='egi-muted'>Lanjut: {ui.esc(f0.langkah_lanjut)}</span>" if f0.langkah_lanjut else '')
                        + f"<br><span class='egi-muted'>{len([x for x in f0.tiket.split(';') if x])} tiket koordinasi</span></div>", unsafe_allow_html=True)
        elif editable and r['kanal'] in ('Kunjungan', 'Telepon') and r['status'] != 'Dibatalkan':
            if st.button('Isi feedback & tindak lanjut', type='primary', use_container_width=True):
                ss.fb_event = sel; ss.tl_tab = 'Feedback kunjungan'; state.go('tindak')
        if user['role'] == 'supervisor' and r['company_id'] and not store.cox.is_client.get(r['company_id'], False) and r['status'] == 'Terjadwal':
            with st.expander('Pindahkan klaim prospect ke RM lain'):
                rms_ = [x for x in sorted(store.co.rm_id.dropna().unique()) if x != r['rm_id']]
                to = st.selectbox('RM tujuan', rms_, key=f'tr_{sel}')
                if st.button('Pindahkan semua jadwal aktif perusahaan ini', key=f'trb_{sel}', use_container_width=True):
                    n, bad = K.transfer(r['company_id'], to, user['username'])
                    if bad:
                        st.error('Tidak dipindah: ' + '; '.join(f'{j}: {w}' for j, w in bad))
                    else:
                        data.audit('kalender_pindah_klaim', user=user['username'], company=r['company_id'], ke=to, jadwal=n)
                        ss._toast = f'{n} jadwal dipindah ke {to}'; ss.cal_ver = ss.get('cal_ver', 0) + 1; st.rerun()
        if not editable:
            st.caption('Jadwal RM lain: hanya bisa dilihat.')
    else:
        st.markdown('**Tambah jadwal**')
        start, end = ss.get('cal_new') or (datetime.combine(today + timedelta(days=1), time(9, 0)), None)
        with st.form('ev_new', clear_on_submit=True):
            if user['role'] == 'supervisor':
                rms = sorted(store.co.rm_id.dropna().unique())
                owner = st.selectbox('Untuk RM', rms, index=rms.index(ss.rm) if ss.rm in rms else 0)
            else:
                owner = user['rm_id']
            opts_co = _company_opts()
            fc0 = ss.focus_company if ss.focus_company in opts_co else ''
            cid = st.selectbox('Perusahaan', opts_co, index=opts_co.index(fc0), format_func=_fmt_co)
            judul = st.text_input('Judul (opsional bila perusahaan dipilih)')
            kanal = st.selectbox('Kanal', K.KANAL)
            tgl = st.date_input('Tanggal', start.date(), format='DD/MM/YYYY')
            c1, c2 = st.columns(2)
            jm = c1.time_input('Mulai', start.time(), step=900)
            js = c2.time_input('Selesai', (end or start + timedelta(minutes=90)).time(), step=900)
            lok = st.text_input('Lokasi', f"Kec. {store.cox.district.get(cid, '')}" if cid else '')
            cat = st.text_area('Catatan / tujuan', height=90)
            add = st.form_submit_button('Tambah ke kalender', type='primary', use_container_width=True)
        if add:
            if not cid and not judul.strip():
                st.error('Pilih perusahaan atau isi judul.')
            elif js <= jm:
                st.error('Jam selesai harus setelah jam mulai.')
            else:
                nama = judul.strip() or f"{store.co.name.get(cid, cid)} ({cid})"
                row = {'rm_id': owner, 'company_id': cid, 'judul': nama, 'kanal': kanal, 'mulai': datetime.combine(tgl, jm).isoformat(timespec='minutes'),
                       'selesai': datetime.combine(tgl, js).isoformat(timespec='minutes'), 'lokasi': lok, 'catatan': cat, 'status': 'Terjadwal', 'sumber': 'Manual'}
                _, _, rej = K.upsert([row], user['username'])
                if rej:
                    st.error(f'Tidak ditambahkan: {rej[0][1]}')
                else:
                    data.audit('kalender_tambah', user=user['username'], rm=owner, company=cid, mulai=row['mulai'])
                    ss.cal_new = None; ss._toast = f'Ditambahkan: {nama}'; ss.cal_ver = ss.get('cal_ver', 0) + 1; st.rerun()
        if ss.get('cal_new') and st.button('Reset tanggal', use_container_width=True):
            ss.cal_new = None; st.rerun()

# ------------------------------------------------------------------ daftar + ekspor
st.markdown('#### Jadwal akan datang')
up = df.assign(_m=mulai)[(mulai >= pd.Timestamp(today)) & (df.status != 'Dibatalkan')].sort_values('_m')
if up.empty:
    st.caption('Belum ada jadwal. Tambahkan dari form di atas, atau setujui rencana minggu di RM Copilot — jadwalnya otomatis masuk ke sini.')
else:
    show = up.assign(Waktu=up._m.dt.strftime('%a %d %b %Y · %H.%M'))[['Waktu', 'rm_id', 'kanal', 'judul', 'lokasi', 'status', 'sumber']]
    st.dataframe(show.rename(columns={'rm_id': 'RM', 'kanal': 'Kanal', 'judul': 'Jadwal', 'lokasi': 'Lokasi', 'status': 'Status', 'sumber': 'Sumber'}),
                 hide_index=True, use_container_width=True)
    st.download_button(f'Unduh ke Google Calendar / Outlook (.ics · {len(up)} jadwal)', K.to_ics(up, f'Kalender kunjungan {ss.rm}'),
                       file_name=f"kalender_{ss.rm}_{today:%Y%m%d}.ics", mime='text/calendar')
