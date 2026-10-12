"""Kalender kunjungan bersama: jadwal disimpan di outputs/app/calendar.csv (dibaca & ditulis semua pengguna dashboard).

Satu baris = satu jadwal. id stabil untuk jadwal dari rencana Copilot ({rm}-{perusahaan}-{tanggal}),
sehingga menyetujui ulang rencana memperbarui jadwal yang sama, tidak menggandakan.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

import reports as R

from .tables import CsvTable, now

COLS = ['id', 'rm_id', 'company_id', 'judul', 'kanal', 'mulai', 'selesai', 'lokasi', 'catatan', 'status', 'sumber', 'dibuat_oleh', 'diubah_pada']
KANAL = ['Kunjungan', 'Telepon', 'Email', 'Rapat internal']
STATUS = ['Terjadwal', 'Selesai', 'Dibatalkan']
WARNA = {'Kunjungan': '#C2500A', 'Telepon': '#1E3A6E', 'Email': '#4D6FAE', 'Rapat internal': '#6B7280'}
T = CsvTable('calendar.csv', COLS)
load, delete = T.load, T.delete


def upsert(rows: list[dict], user: str):
    """Tambah/perbarui jadwal berdasarkan id. Mengembalikan jumlah (baru, diperbarui)."""
    new, upd, _ = T.upsert(rows, {'dibuat_oleh': user, 'diubah_pada': now()})
    return new, upd


def set_status(event_id, status, user):
    T.update(event_id, status=status, diubah_pada=now())


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
