"""Kalender kunjungan bersama: jadwal disimpan di outputs/app/calendar.csv (dibaca & ditulis semua pengguna dashboard).

Satu baris = satu jadwal. id stabil untuk jadwal dari rencana Copilot ({rm}-{perusahaan}-{tanggal}),
sehingga menyetujui ulang rencana memperbarui jadwal yang sama, tidak menggandakan.
"""
from __future__ import annotations

import threading
import uuid
from datetime import datetime, timedelta

import pandas as pd

import reports as R

from . import data

FILE = data.APP_OUT / 'calendar.csv'
COLS = ['id', 'rm_id', 'company_id', 'judul', 'kanal', 'mulai', 'selesai', 'lokasi', 'catatan', 'status', 'sumber', 'dibuat_oleh', 'diubah_pada']
KANAL = ['Kunjungan', 'Telepon', 'Email', 'Rapat internal']
STATUS = ['Terjadwal', 'Selesai', 'Dibatalkan']
WARNA = {'Kunjungan': '#C2500A', 'Telepon': '#1E3A6E', 'Email': '#4D6FAE', 'Rapat internal': '#6B7280'}
_lock = threading.Lock()


def load() -> pd.DataFrame:
    if not FILE.exists():
        return pd.DataFrame(columns=COLS)
    df = pd.read_csv(FILE, dtype=str, keep_default_na=False)
    return df.reindex(columns=COLS, fill_value='')


def _write(df):
    data.APP_OUT.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix('.tmp')
    df[COLS].to_csv(tmp, index=False)
    tmp.replace(FILE)


def upsert(rows: list[dict], user: str):
    """Tambah/perbarui jadwal berdasarkan id. Mengembalikan jumlah (baru, diperbarui)."""
    now = datetime.now().isoformat(timespec='seconds')
    with _lock:
        df = load()
        new = upd = 0
        for r in rows:
            r = {**r, 'id': r.get('id') or uuid.uuid4().hex[:12], 'dibuat_oleh': user, 'diubah_pada': now}
            r = {k: '' if r.get(k) is None else str(r.get(k)) for k in COLS}
            hit = df.index[df.id == r['id']]
            if len(hit):
                df.loc[hit[0], COLS] = [r[k] for k in COLS]; upd += 1
            else:
                df = pd.concat([df, pd.DataFrame([r])], ignore_index=True); new += 1
        _write(df)
    return new, upd


def delete(event_id: str):
    with _lock:
        df = load()
        _write(df[df.id != event_id])


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
