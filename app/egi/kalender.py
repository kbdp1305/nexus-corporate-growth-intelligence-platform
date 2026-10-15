"""Kalender kunjungan bersama: jadwal disimpan di outputs/app/calendar.csv (dibaca & ditulis semua pengguna dashboard).

Satu baris = satu jadwal. id stabil untuk jadwal dari rencana Copilot ({rm}-{perusahaan}-{tanggal}),
sehingga menyetujui ulang rencana memperbarui jadwal yang sama, tidak menggandakan.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pandas as pd

import reports as R

from . import data
from .tables import CsvTable, now, transactional

COLS = ['id', 'rm_id', 'company_id', 'judul', 'kanal', 'mulai', 'selesai', 'lokasi', 'catatan', 'status', 'sumber', 'dibuat_oleh', 'diubah_pada']
KANAL = ['Kunjungan', 'Telepon', 'Email', 'Rapat internal']
STATUS = ['Terjadwal', 'Selesai', 'Dibatalkan']
WARNA = {'Kunjungan': '#C2500A', 'Telepon': '#1E3A6E', 'Email': '#4D6FAE', 'Rapat internal': '#6B7280'}
T = CsvTable('calendar.csv', COLS)
load = T.load


CLAIM_DAYS = 30          # klaim prospect bertahan selama ada jadwal aktif + 30 hari setelah kunjungan terakhir


def _owner_map():
    """company_id → RM pemilik untuk NASABAH (rm_id di data). Prospect tidak punya pemilik tetap."""
    store = data.get_store()
    co = store.cox
    return co.rm_id[co.is_client & co.rm_id.notna()].to_dict(), store.co.name.to_dict()


def holder(df, cid, now=None):
    """(RM, alasan) yang memegang perusahaan ini, atau (None, '').
    Nasabah → RM pemiliknya. Prospect → RM dengan jadwal tidak dibatalkan yang mulai ≥ hari ini − CLAIM_DAYS (paling baru)."""
    owners, _ = _owner_map()
    if cid in owners:
        return owners[cid], 'nasabah RM ini'
    now = now or datetime.now()
    h = df[(df.company_id == cid) & (df.status != 'Dibatalkan')].copy()
    h['_m'] = pd.to_datetime(h.mulai, errors='coerce')
    h = h[h._m >= pd.Timestamp(now - timedelta(days=CLAIM_DAYS))].sort_values('_m')
    if h.empty:
        return None, ''
    r = h.iloc[-1]
    return r.rm_id, f"prospect diklaim sejak {r.mulai[:10]}"


def claims(now=None) -> dict:
    """company_id → RM yang sedang mengklaim (untuk prospect; aturan sama dengan holder(), dihitung sekaligus)."""
    now = now or datetime.now()
    df = load()
    df = df[(df.status != 'Dibatalkan') & (df.company_id != '')].copy()
    df['_m'] = pd.to_datetime(df.mulai, errors='coerce')
    df = df[df._m >= pd.Timestamp(now - timedelta(days=CLAIM_DAYS))].sort_values('_m')
    return df.groupby('company_id').rm_id.last().to_dict()


def check(df, r, now=None, ignore_owner=False):
    """Alasan penolakan, atau None. Hanya jadwal berstatus Terjadwal yang dijaga (Selesai/Dibatalkan boleh diedit bebas)."""
    try:
        m = pd.Timestamp(r['mulai'])
        s = pd.Timestamp(r.get('selesai') or m + pd.Timedelta(minutes=60))
        if pd.isna(m) or pd.isna(s) or s <= m:
            return 'Jam selesai harus setelah jam mulai.'
    except (ValueError, TypeError, KeyError):
        return 'Tanggal atau jam jadwal tidak valid.'
    if r.get('status') == 'Selesai':
        from . import tindak
        for kid in tindak.KEGIATAN.load().loc[lambda f: f.kal_id == r.get('id'), 'id']:
            reason = tindak.completion_block(kid)
            if reason:
                return reason
    if r.get('status', 'Terjadwal') != 'Terjadwal':
        return None
    others = df[df.id != r['id']]
    cid = r.get('company_id') or ''
    if cid and not ignore_owner:
        who, why = holder(others, cid, now)
        if who and who != r['rm_id']:
            _, names = _owner_map()
            return f"{names.get(cid, cid)} dipegang {who} ({why}). Satu perusahaan hanya ditangani satu RM."
    m, s = pd.Timestamp(r['mulai']), pd.Timestamp(r['selesai'] or r['mulai']) + (pd.Timedelta(0) if r['selesai'] else pd.Timedelta(minutes=60))
    mine = others[(others.rm_id == r['rm_id']) & (others.status != 'Dibatalkan')]
    mm = pd.to_datetime(mine.mulai, errors='coerce', format='mixed')
    ms = pd.to_datetime(mine.selesai, errors='coerce', format='mixed').fillna(mm + pd.Timedelta(minutes=60))
    clash = mine[(mm < s) & (ms > m)]
    if len(clash):
        c = clash.iloc[0]
        return f"Bertabrakan dengan {c.judul} ({c.mulai[11:16]}–{c.selesai[11:16]}) di kalender {r['rm_id']}."
    return None


@transactional
def upsert(rows: list[dict], user: str, *, _internal=False):
    """Tambah/perbarui jadwal berdasarkan id, dengan penjaga: tidak boleh bertabrakan (per RM) dan satu perusahaan satu RM.
    Mengembalikan (baru, diperbarui, ditolak) — ditolak = [(judul, alasan)]."""
    stamp = {'dibuat_oleh': user, 'diubah_pada': now()}
    with T._lock:
        df = load()
        new = upd = 0
        rejected = []
        for r in rows:
            r = {**r, **stamp, 'id': r.get('id') or uuid.uuid4().hex[:12]}
            r = {k: '' if r.get(k) is None else str(r.get(k)) for k in COLS}
            if not _internal:
                from . import auth, tindak
                actor = auth.current()
                if not actor or not auth.can_edit(r['rm_id']) or (r['company_id'] and r['company_id'] not in tindak.assignment_ids(data.get_store(), r['rm_id'], actor)):
                    rejected.append((r['judul'], 'Agenda berada di luar akses akun Anda.')); continue
            why = check(df, r)
            if why:
                rejected.append((r['judul'], why)); continue
            hit = df.index[df.id == r['id']]
            if len(hit):
                df.loc[hit[0], COLS] = [r[k] for k in COLS]; upd += 1
            else:
                df = pd.concat([df, pd.DataFrame([r])], ignore_index=True); new += 1
        T._write(df)
        from . import tindak
        for r in rows:
            if r.get('id') in set(df.id) and not any(j == r.get('judul') for j, _ in rejected):
                tindak.sync_calendar_event(r['id'], user)
    return new, upd, rejected


@transactional
def transfer(cid, to_rm, user):
    """Supervisor: pindahkan klaim prospect — jadwal Terjadwal perusahaan ini berpindah ke RM lain (dicek bentrok di kalender RM tujuan)."""
    from . import auth
    if not auth.current() or auth.current()['role'] != 'supervisor':
        return 0, [('', 'Serah terima hanya dapat dilakukan supervisor.')]
    if cid in _owner_map()[0]:
        return 0, [('', 'Fitur ini hanya untuk prospect.')]
    df = load()
    rows = [{**r, 'rm_id': to_rm} for r in df[(df.company_id == cid) & (df.status == 'Terjadwal')].to_dict('records')]
    if not rows:
        return 0, [('', 'Tidak ada jadwal aktif untuk dipindahkan.')]
    with T._lock:
        cur = load()
        cur = cur[~cur.id.isin([r['id'] for r in rows])]
        bad = []
        checking = cur.copy()
        for row in rows:
            reason = check(checking, row, ignore_owner=True)
            if reason:
                bad.append((row['judul'], reason))
            checking = pd.concat([checking, pd.DataFrame([row])], ignore_index=True)
        if bad:
            return 0, bad
        cur = pd.concat([cur, pd.DataFrame(rows)], ignore_index=True)
        cur.loc[cur.id.isin([r['id'] for r in rows]), ['dibuat_oleh', 'diubah_pada']] = [user, now()]
        T._write(cur)
        from . import tindak
        tindak.transfer_work(cid, to_rm, user)
    return len(rows), []


def set_status(event_id, status, user, *, _internal=False):
    row = load().set_index('id').loc[event_id].to_dict()
    row.update(id=event_id, status=status)
    _, _, rejected = upsert([row], user, _internal=_internal)
    if rejected:
        raise ValueError(rejected[0][1])


@transactional
def delete(event_id):
    from . import tindak
    if event_id in set(tindak.FEEDBACK.load().event_id):
        raise ValueError('Agenda dengan feedback tidak dapat dihapus; riwayat harus dipertahankan.')
    set_status(event_id, 'Dibatalkan', 'kalender')


def for_rm(rm) -> pd.DataFrame:
    df = load()
    return df if rm == 'Semua RM' else df[df.rm_id == rm]


def from_plan(plan: dict, week_start, status='Terjadwal'):
    """Rencana minggu Copilot → baris kalender (pakai event yang sama dengan ekspor .ics)."""
    rows = []
    for e in R.plan_events(plan, week_start):
        kanal, rest = e['judul'].split(': ', 1)
        cid = rest.rsplit('(', 1)[-1].rstrip(')')
        rows.append({'id': e['uid'].split('@')[0], 'rm_id': plan['rm'], 'company_id': cid, 'judul': rest, 'kanal': kanal,
                     'mulai': e['mulai'].isoformat(timespec='minutes'), 'selesai': (e['mulai'] + timedelta(minutes=e['menit'])).isoformat(timespec='minutes'),
                     'lokasi': e['lokasi'], 'catatan': e['deskripsi'], 'status': status, 'sumber': 'Copilot'})
    return rows


def to_fullcalendar(df: pd.DataFrame, show_rm=False):
    ev = []
    for r in df.itertuples():
        title = (f'{r.rm_id} · ' if show_rm else '') + f'{r.kanal}: {r.judul}'
        col = '#9CA3AF' if r.status == 'Dibatalkan' else '#17613F' if r.status == 'Selesai' else WARNA.get(r.kanal, '#374151')
        ev.append({'id': r.id, 'title': title, 'start': r.mulai, 'end': r.selesai or None, 'backgroundColor': col, 'borderColor': col,
                   'textColor': '#FFFFFF'})
    return ev


def to_ics(df: pd.DataFrame, name):
    events = []
    for r in df[df.status != 'Dibatalkan'].itertuples():
        m, s = datetime.fromisoformat(r.mulai), datetime.fromisoformat(r.selesai) if r.selesai else None
        events.append({'uid': f'{r.id}@egi-rm-copilot', 'mulai': m, 'menit': int(((s - m).total_seconds() // 60) if s else 60),
                       'judul': f'{r.kanal}: {r.judul}', 'deskripsi': r.catatan, 'lokasi': r.lokasi})
    return R.calendar_ics(events, name)


# ---------------------------------------------------------------- jadwalkan langsung (tombol "Jadwalkan" di semua halaman)
SLOTS = ['09.00', '11.00', '14.00', '16.00']      # sama dengan slot rencana Copilot (agent.JAM)
HARI = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat']
HORIZON = 10                                       # hari kerja ke depan yang dicari
MAX_PER_DAY = 4


def _workdays(start, n):
    d, out = start, []
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


def active(rm) -> pd.DataFrame:
    """Jadwal RM yang belum dibatalkan, dengan kolom datetime _m/_s."""
    df = for_rm(rm)
    df = df[df.status != 'Dibatalkan'].copy()
    df['_m'] = pd.to_datetime(df.mulai, errors='coerce')
    df['_s'] = pd.to_datetime(df.selesai, errors='coerce').fillna(df._m + pd.Timedelta(minutes=60))
    return df.dropna(subset=['_m'])


def upcoming(rm, days=7, now=None):
    now = now or datetime.now()
    df = active(rm)
    return df[(df._m >= pd.Timestamp(now)) & (df._m < pd.Timestamp(now) + pd.Timedelta(days=days)) & (df.status == 'Terjadwal')].sort_values('_m')


def scheduled_ids(rm, now=None):
    """Perusahaan yang sudah punya jadwal mendatang (status Terjadwal)."""
    now = now or datetime.now()
    df = active(rm)
    return set(df[(df._m >= pd.Timestamp(now)) & (df.status == 'Terjadwal')].company_id) - {''}


def _free(busy, start, minutes):
    end = start + timedelta(minutes=minutes)
    return not ((busy._m < pd.Timestamp(end)) & (busy._s > pd.Timestamp(start))).any()


def overlaps(rm, start, minutes, ignore_id=None):
    """Jadwal RM yang bertabrakan dengan rentang ini (untuk peringatan saat RM mengatur sendiri)."""
    busy = active(rm)
    if ignore_id:
        busy = busy[busy.id != ignore_id]
    end = start + timedelta(minutes=minutes)
    return busy[(busy._m < pd.Timestamp(end)) & (busy._s > pd.Timestamp(start))]


def suggest_slots(store, rm, cid, minutes, n=3, prefer=None, now=None):
    """Saran slot kosong dalam HORIZON hari kerja, maksimal satu per hari, urut skor (awal + dekat rute).
    Hari yang sudah punya kunjungan di kecamatan sama / dekat didahulukan. Mengembalikan [(datetime, alasan)]."""
    from . import planner
    now = now or datetime.now()
    busy = active(rm)
    days = _workdays(now.date() + timedelta(days=1), HORIZON)
    at = lambda d, jam: datetime(d.year, d.month, d.day, *map(int, jam.split('.')))
    out = []
    if prefer and prefer[0] in HARI:
        d = next((x for x in days if x.weekday() == HARI.index(prefer[0])), None)
        if d is not None and _free(busy, at(d, prefer[1] or SLOTS[0]), minutes):
            out.append((-99, at(d, prefer[1] or SLOTS[0]), 'sesuai permintaan'))
    here = planner.coords(store, cid) if cid in store.co.index else None
    dist = store.co.district.get(cid)
    for i, d in enumerate(days):
        today = busy[busy._m.dt.date == d]
        if len(today) >= MAX_PER_DAY:
            continue
        slot = next((at(d, j) for j in SLOTS if _free(busy, at(d, j), minutes)), None)
        if slot is None:
            continue
        others = [c for c in today.company_id if c in store.co.index and c != cid]     # jadwal perusahaan ini sendiri bukan 'searah rute'
        same = [c for c in others if dist and store.co.district.get(c) == dist]
        if same:
            near, why = -3.0, f"{len(same)} jadwal lain di {dist} hari itu (satu rute)"
        elif others and here:
            k = min(planner.km(here, planner.coords(store, c)) for c in others)
            near, why = k / 5, f"±{k:.1f} km dari jadwal lain hari itu"
        else:
            near, why = 1.5, 'hari masih kosong' if not len(today) else f'{len(today)} jadwal lain hari itu'
        out.append((i + near, slot, why))
    out.sort(key=lambda x: x[0])
    seen, res = set(), []
    for _, slot, why in out:
        if slot.date() not in seen:
            seen.add(slot.date()); res.append((slot, why))
        if len(res) == n:
            break
    return res


def find_slot(store, rm, cid, minutes, prefer=None, now=None):
    s = suggest_slots(store, rm, cid, minutes, 1, prefer, now)
    return s[0][0] if s else None


def default_kanal(store, cid):
    return 'Telepon' if store.seg.segment.get(cid) == 'S1 Kecil' else 'Kunjungan'          # playbook: S1 lewat telepon


def existing(rm, cid):
    """Jadwal mendatang (Terjadwal) untuk perusahaan ini, paling awal dulu."""
    act = active(rm)
    return act[(act.company_id == cid) & (act.status == 'Terjadwal') & (act._m >= pd.Timestamp(datetime.now()))].sort_values('_m')


def owner(store, rm, cid):
    """RM pemilik jadwal: RM aktif, atau (untuk supervisor 'Semua RM') RM nasabah itu."""
    if rm != 'Semua RM':
        return rm
    r = store.co.rm_id.get(cid)
    return r if isinstance(r, str) else None


def schedule(store, rm, cid, user, catatan='', sumber='Dashboard', prefer=None, start=None, kanal=None, minutes=None):
    """Simpan jadwal. start/kanal/minutes dari dialog; tanpa start → slot terbaik (dipakai usulan agen yang sudah disetujui).
    Mengembalikan (status, baris|pesan): 'baru' | 'sudah' | 'gagal'."""
    rm = owner(store, rm, cid)
    if not rm:
        return 'gagal', 'Pilih RM di sidebar dulu: prospect ini belum punya RM.'
    who, why = holder(load(), cid)
    if who and who != rm:
        return 'gagal', f"{store.co.name.get(cid, cid)} dipegang {who} ({why})."
    ex = existing(rm, cid)
    if start is None and len(ex):
        return 'sudah', ex.iloc[0].drop(['_m', '_s']).to_dict()
    kanal = kanal or default_kanal(store, cid)
    minutes = int(minutes or R.DURASI_MENIT.get(kanal, 60))
    start = start or find_slot(store, rm, cid, minutes, prefer)
    if start is None:
        return 'gagal', f'Tidak ada slot kosong dalam {HORIZON} hari kerja ke depan.'
    name = store.co.name.get(cid, cid)
    row = {'id': f'{rm}-{cid}-{start:%Y%m%d%H%M}', 'rm_id': rm, 'company_id': cid, 'judul': f'{name} ({cid})', 'kanal': kanal,
           'mulai': start.isoformat(timespec='minutes'), 'selesai': (start + timedelta(minutes=minutes)).isoformat(timespec='minutes'),
           'lokasi': f"Kec. {store.co.district.get(cid, '')}" if kanal == 'Kunjungan' else '', 'catatan': catatan,
           'status': 'Terjadwal', 'sumber': sumber}
    _, _, rej = upsert([row], user)
    if rej:
        return 'gagal', rej[0][1]
    return 'baru', row


def fit_free(rows, rm):
    """Geser jadwal rencana Copilot yang bertabrakan dengan jadwal yang sudah ada ke slot kosong berikutnya di hari yang sama."""
    busy = active(rm)
    busy = busy[~busy.id.isin([r['id'] for r in rows])]
    out = []
    for r in rows:
        m, s = datetime.fromisoformat(r['mulai']), datetime.fromisoformat(r['selesai'])
        dur = int((s - m).total_seconds() // 60)
        if not _free(busy, m, dur):
            d = m.date()
            cand = [datetime(d.year, d.month, d.day, *map(int, j.split('.'))) for j in SLOTS] + [m + timedelta(minutes=30 * k) for k in range(1, 16)]
            m = next((c for c in sorted(set(cand)) if c >= m.replace(hour=8) and c.hour < 18 and _free(busy, c, dur)), m)
            r = {**r, 'mulai': m.isoformat(timespec='minutes'), 'selesai': (m + timedelta(minutes=dur)).isoformat(timespec='minutes')}
        busy = pd.concat([busy, pd.DataFrame([{'id': r['id'], '_m': pd.Timestamp(m), '_s': pd.Timestamp(m + timedelta(minutes=dur))}])], ignore_index=True)
        out.append(r)
    return out
