"""Penyuntingan rencana minggu: jam, rute, kandidat pengganti, ekspor kalender.

Rencana (dict dari agent.plan_week) tetap satu-satunya sumber: hari → item. Modul ini hanya mengubah
item di dalamnya, jadi PDF (reports.weekly_plan_pdf) dan JSON yang disetujui otomatis ikut terbarui.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np

from . import agent

HARI = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat']
SPEED_KMH = 20          # kecepatan rata-rata dalam kota (Jabodetabek, jam kerja)
DUR_MIN = {'Kunjungan': 60, 'Telepon': 20}


def coords(store, cid):
    c = store.co.loc[cid]
    return float(c.latitude), float(c.longitude)


def km(a, b):
    p = np.pi / 180
    h = np.sin((b[0] - a[0]) * p / 2) ** 2 + np.cos(a[0] * p) * np.cos(b[0] * p) * np.sin((b[1] - a[1]) * p / 2) ** 2
    return float(12742 * np.arcsin(np.sqrt(h)))


def route_km(store, items):
    pts = [coords(store, it['id']) for it in items]
    return sum(km(a, b) for a, b in zip(pts, pts[1:]))


def _round15(m):
    return int(np.ceil(m / 15) * 15)


def duration(day, it):
    """Menit: durasi yang diatur RM (tarik tepi jadwal di kalender) atau default kanal."""
    return int(it.get('durasi') or DUR_MIN.get(day.get('kanal', 'Kunjungan'), 60))


def retime(store, day, start='09:00'):
    """Susun ulang jam: mulai `start`, durasi per kanal + waktu tempuh antar kunjungan (dibulatkan 15 menit); jam_tetap tidak diubah."""
    t = datetime.strptime(start, '%H:%M')
    prev = None
    for it in day['item']:
        if prev is not None and day.get('kanal', 'Kunjungan') == 'Kunjungan':
            t += timedelta(minutes=_round15(km(coords(store, prev['id']), coords(store, it['id'])) / SPEED_KMH * 60))
        if it.get('jam_tetap'):     # jam yang diatur RM dipertahankan; kunjungan berikutnya menyesuaikan
            t = datetime.strptime(it['jam'].replace('.', ':'), '%H:%M')
        it['jam'] = t.strftime('%H.%M')
        t += timedelta(minutes=duration(day, it))
        prev = it


def optimize(store, day):
    """Urutan tetangga terdekat dari kunjungan pertama; item terkunci tetap di posisinya."""
    items = day['item']
    if len(items) < 3:
        return
    locked = {i: it for i, it in enumerate(items) if it.get('kunci')}
    free = [it for it in items if not it.get('kunci')]
    order = [free.pop(0)]
    while free:
        last = coords(store, order[-1]['id'])
        nxt = min(free, key=lambda it: km(last, coords(store, it['id'])))
        free.remove(nxt); order.append(nxt)
    out, it_free = [], iter(order)
    for i in range(len(items)):
        out.append(locked[i] if i in locked else next(it_free))
    day['item'] = out


def all_ids(plan):
    return {it['id'] for d in plan['hari'] for it in d['item']}


def replacements(store, rm, plan, item=None, n=6):
    """Kandidat yang belum ada di rencana; bila item diberi, utamakan kecamatan yang sama."""
    pf = agent.candidates(store, rm)
    pf = pf[~pf.index.isin(all_ids(plan))]
    if item is not None:
        dist = store.co.district.get(item['id'])
        pf = pf.assign(_same=pf.district == dist).sort_values(['_same', 'prio'], ascending=False)
    return pf.head(n)


def make_item(store, rm, cid, siapkan='Profil 360°'):
    pf = agent.candidates(store, rm)
    row = pf.loc[cid].to_dict() if cid in pf.index else {}
    it = agent._item(store, cid, row, '09.00', siapkan)
    if not row:     # prospect / di luar portofolio: tujuan perkenalan
        it['tujuan'] = 'Prospect: perkenalan dan pemetaan kebutuhan.'
        it['peluang'] = '—'
    return it


def add_basket_prospects(store, rm, plan, basket):
    """plan_week hanya memilih dari portofolio; prospect di keranjang dimasukkan ke hari kunjungan tersibuk yang paling dekat."""
    visit_days = [d for d in plan['hari'] if d.get('kanal', 'Kunjungan') == 'Kunjungan'] or plan['hari']
    for b in basket:
        if b['id'] in all_ids(plan) or b['id'] not in store.co.index or not visit_days:
            continue
        here = coords(store, b['id'])
        best = min(visit_days, key=lambda d: min((km(here, coords(store, it['id'])) for it in d['item']), default=99))
        it = make_item(store, rm, b['id'], 'Draf permintaan perkenalan' if b.get('jenis') == 'prospect' else 'Profil 360°')
        if b.get('catatan'):
            it['tujuan'] = f"{b['catatan'].capitalize()}. " + it['tujuan']
        best['item'].append(it)


def week_dates(label, today=None):
    """Senin minggu yang dimaksud ('minggu ini' / 'minggu depan')."""
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    return monday + timedelta(days=7) if 'depan' in (label or '').lower() else monday


def ics(plan, monday):
    """Ekspor kalender (RFC 5545) — bisa diimpor ke Google Calendar / Outlook."""
    stamp = datetime.now().strftime('%Y%m%dT%H%M%S')
    esc = lambda s: str(s).replace('\\', '\\\\').replace(';', '\\;').replace(',', '\\,').replace('\n', '\\n')
    lines = ['BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//EGI//RM Copilot//ID', 'CALSCALE:GREGORIAN']
    for d in plan['hari']:
        if d['hari'] not in HARI:
            continue
        day = monday + timedelta(days=HARI.index(d['hari']))
        for it in d['item']:
            dur = duration(d, it)
            h, m = map(int, it['jam'].replace(':', '.').split('.'))
            s = datetime(day.year, day.month, day.day, h, m)
            lines += ['BEGIN:VEVENT', f"UID:{plan['rm']}-{it['id']}-{s:%Y%m%d%H%M}@egi", f'DTSTAMP:{stamp}',
                      f'DTSTART:{s:%Y%m%dT%H%M%S}', f'DTEND:{s + timedelta(minutes=dur):%Y%m%dT%H%M%S}',
                      f"SUMMARY:{esc(('Telepon ' if d.get('kanal') == 'Telepon' else 'Kunjungan ') + it['nama'])}",
                      f"DESCRIPTION:{esc(it['tujuan'] + chr(10) + 'Siapkan: ' + it['siapkan'] + chr(10) + it['id'] + ' · ' + it['info'])}",
                      f"LOCATION:{esc(it['info'].split(' · ')[1] if ' · ' in it['info'] else '')}", 'END:VEVENT']
    lines.append('END:VCALENDAR')
    return '\r\n'.join(lines) + '\r\n'


def refresh_kpi(plan, store):
    """Hitung ulang KPI rencana setelah disunting (dipakai layar, PDF, JSON)."""
    ids = list(all_ids(plan))
    n_prio = int(store.opp.opportunity_score.reindex(ids).ge(0.75).sum())
    visit = {i for i in ids if not store.cox.is_client.get(i, False)}                     # prospect yang dijadwalkan langsung
    intro = {d['intro'][0] for d in plan['hari'] if d.get('intro')} - visit               # prospect lewat perkenalan nasabah sendiri
    plan['kpi'] = [('Aksi', str(len(ids)), f"{len(plan['hari'])} hari"), ('Nasabah prioritas', str(n_prio), 'skor peluang ≥ 0,75'),
                   ('Prospect', str(len(visit) + len(intro)), f"{len(visit)} dikunjungi · {len(intro)} lewat perkenalan"),
                   plan['kpi'][3] if len(plan.get('kpi', [])) > 3 else ('Alarm dicek dulu', '0', '')]


# ---------------------------------------------------------------- kalender (streamlit-calendar / FullCalendar)
COLOR = {'nasabah': '#2a78d6', 'prospect': '#eb6834', 'telepon': '#1baf7a', 'jalan': '#e1e0d9', 'bentrok': '#f6d3d3'}   # 3 slot pertama palet, lolos uji semua-pasangan


def find(plan, cid):
    for d in plan['hari']:
        for it in d['item']:
            if it['id'] == cid:
                return d, it
    return None, None


def _at(monday, hari, jam):
    day = monday + timedelta(days=HARI.index(hari))
    h, m = map(int, jam.replace(':', '.').split('.'))
    return datetime(day.year, day.month, day.day, h, m)


def to_events(store, plan, monday):
    """Rencana → event FullCalendar. Waktu dikirim tanpa zona & kalender diset UTC, jadi jam dinding tidak bergeser di browser mana pun."""
    ev = []
    for d in plan['hari']:
        if d['hari'] not in HARI:
            continue
        tel = d.get('kanal') == 'Telepon'
        prev = None
        for it in d['item']:
            s = _at(monday, d['hari'], it['jam']); e = s + timedelta(minutes=duration(d, it))
            if prev is not None and not tel:      # blok perjalanan dari kunjungan sebelumnya; merah bila waktunya tidak cukup
                gap = km(coords(store, prev[0]['id']), coords(store, it['id']))
                need = max(15, _round15(gap / SPEED_KMH * 60)); ts = prev[1]; avail = int((s - ts).total_seconds() // 60)
                short = avail < need
                te = ts + timedelta(minutes=max(15, avail) if short else need)
                ev.append({'id': f"jalan-{it['id']}", 'title': f'{gap:.1f} km' + (f' · kurang {need - max(avail, 0)} mnt' if short else ''),
                           'start': f'{ts:%Y-%m-%dT%H:%M:%S}', 'end': f'{te:%Y-%m-%dT%H:%M:%S}', 'color': COLOR['bentrok'] if short else COLOR['jalan'],
                           'textColor': '#9A2416' if short else '#52514e', 'editable': False, 'extendedProps': {'jenis': 'jalan'}})
            client = store.cox.is_client.get(it['id'], False)
            kind = 'telepon' if tel else 'nasabah' if client else 'prospect'
            ev.append({'id': it['id'], 'title': ('🔒 ' if it.get('kunci') else '') + ('📞 ' if tel else '') + it['nama'],
                       'start': f'{s:%Y-%m-%dT%H:%M:%S}', 'end': f'{e:%Y-%m-%dT%H:%M:%S}', 'color': COLOR[kind],
                       'editable': not it.get('kunci'), 'extendedProps': {'jenis': kind, 'info': it['info'], 'tujuan': it['tujuan']}})
            prev = (it, e)
    return ev


def _parse(iso):
    return datetime.fromisoformat(iso.replace('Z', '+00:00')).replace(tzinfo=None)


def apply_change(store, plan, cid, start_iso, end_iso, start='09:00'):
    """Hasil geser/tarik di kalender → pindah hari, jam manual (⏱), durasi. Mengembalikan teks ringkas perubahan."""
    d, it = find(plan, cid)
    if it is None:
        return None
    s, e = _parse(start_iso), _parse(end_iso) if end_iso else None
    hari = HARI[s.weekday()] if s.weekday() < 5 else d['hari']
    tgt = next((x for x in plan['hari'] if x['hari'] == hari), None)
    if tgt is None:                                   # hari baru di luar pengaturan awal
        tgt = {'hari': hari, 'kanal': d.get('kanal', 'Kunjungan'), 'tema': 'ditambahkan RM', 'item': []}
        plan['hari'].append(tgt); plan['hari'].sort(key=lambda x: HARI.index(x['hari']) if x['hari'] in HARI else 9)
    if e is not None:
        it['durasi'] = max(15, int((e - s).total_seconds() // 60))
    it['jam'], it['jam_tetap'] = f'{s:%H.%M}', True
    if tgt is not d:
        d['item'].remove(it); tgt['item'].append(it)
    tgt['item'].sort(key=lambda x: x['jam'])
    for x in {id(d): d, id(tgt): tgt}.values():
        retime(store, x, start)
    return f"{it['nama']} → {tgt['hari']} {it['jam']}" + (f" ({it['durasi']} mnt)" if e is not None else '')


def add_at(store, rm, plan, cid, start_iso, start='09:00'):
    """Tambah kandidat di slot kosong yang dipilih di kalender."""
    s = _parse(start_iso)
    if s.weekday() >= 5:
        return None
    hari = HARI[s.weekday()]
    tgt = next((x for x in plan['hari'] if x['hari'] == hari), None)
    if tgt is None:
        tgt = {'hari': hari, 'kanal': 'Kunjungan', 'tema': 'ditambahkan RM', 'item': []}
        plan['hari'].append(tgt); plan['hari'].sort(key=lambda x: HARI.index(x['hari']) if x['hari'] in HARI else 9)
    it = make_item(store, rm, cid); it['jam'], it['jam_tetap'] = f'{s:%H.%M}', True
    tgt['item'].append(it); tgt['item'].sort(key=lambda x: x['jam']); retime(store, tgt, start)
    return it


def conflicts(store, plan):
    """Kunjungan yang bertabrakan atau tidak menyisakan cukup waktu tempuh dari kunjungan sebelumnya."""
    out = []
    for d in plan['hari']:
        tel = d.get('kanal') == 'Telepon'
        for a, b in zip(d['item'], d['item'][1:]):
            ta, tb = (datetime.strptime(x['jam'].replace('.', ':'), '%H:%M') for x in (a, b))
            avail = int((tb - ta).total_seconds() // 60) - duration(d, a)
            need = 0 if tel else max(15, _round15(km(coords(store, a['id']), coords(store, b['id'])) / SPEED_KMH * 60))
            if avail < need:
                out.append(f"{d['hari']} {b['jam']} · {b['nama']}: " + (f'bertabrakan {-avail} mnt dengan {a["nama"]}' if avail < 0 else
                           f'butuh ±{need} mnt perjalanan dari {a["nama"]}, tersedia {avail} mnt'))
    return out
