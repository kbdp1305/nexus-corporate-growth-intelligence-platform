"""Rute perjalanan & keranjang untuk rencana minggu (RM Copilot).

Jadwal (hari, jam, durasi, status) dikelola Kalender kunjungan (egi/kalender.py). Modul ini hanya:
jarak & urutan kunjungan per hari, dan memasukkan prospect dari keranjang ke rencana.
"""
from __future__ import annotations

import numpy as np

from . import agent

HARI = ['Senin', 'Selasa', 'Rabu', 'Kamis', 'Jumat']
SPEED_KMH = 20          # kecepatan rata-rata dalam kota (Jabodetabek, jam kerja)


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


def optimize(store, day):
    """Urutan tetangga terdekat dari kunjungan pertama. Slot jam hari itu tetap; hanya kunjungan yang ditukar."""
    items = day['item']
    if len(items) < 3:
        return
    slots = sorted(it['jam'] for it in items)
    free = list(items)
    order = [free.pop(0)]
    while free:
        last = coords(store, order[-1]['id'])
        nxt = min(free, key=lambda it: km(last, coords(store, it['id'])))
        free.remove(nxt); order.append(nxt)
    for it, jam in zip(order, slots):
        it['jam'] = jam
    day['item'] = order


def all_ids(plan):
    return {it['id'] for d in plan['hari'] for it in d['item']}


def make_item(store, rm, cid, siapkan='Profil 360°', jam='09.00'):
    pf = agent.candidates(store, rm)
    row = pf.loc[cid].to_dict() if cid in pf.index else {}
    it = agent._item(store, cid, row, jam, siapkan)
    if not row:     # prospect / di luar portofolio: tujuan perkenalan
        it['tujuan'] = 'Prospect: perkenalan dan pemetaan kebutuhan.'
        it['peluang'] = '—'
    return it


def _next_slot(day):
    """Slot jam rencana (agent.JAM) yang belum dipakai di hari itu; kalau penuh, 90 menit setelah slot terakhir."""
    used = {it['jam'] for it in day['item']}
    free = [j for j in agent.JAM if j not in used]
    if free:
        return free[0]
    h, m = map(int, max(used).split('.'))
    t = h * 60 + m + 90
    return f'{t // 60:02d}.{t % 60:02d}'


def add_basket_prospects(store, rm, plan, basket):
    """plan_week hanya memilih dari portofolio; prospect di keranjang dimasukkan ke hari kunjungan yang lokasinya paling dekat."""
    visit_days = [d for d in plan['hari'] if d.get('kanal', 'Kunjungan') == 'Kunjungan'] or plan['hari']
    for b in basket:
        if b['id'] in all_ids(plan) or b['id'] not in store.co.index or not visit_days:
            continue
        here = coords(store, b['id'])
        best = min(visit_days, key=lambda d: min((km(here, coords(store, it['id'])) for it in d['item']), default=99))
        it = make_item(store, rm, b['id'], 'Draf permintaan perkenalan' if b.get('jenis') == 'prospect' else 'Profil 360°', _next_slot(best))
        if b.get('catatan'):
            it['tujuan'] = f"{b['catatan'].capitalize()}. " + it['tujuan']
        best['item'].append(it)
        best['item'].sort(key=lambda x: x['jam'])


def refresh_kpi(plan, store):
    """Hitung ulang KPI rencana setelah keranjang dimasukkan (dipakai layar, PDF, JSON)."""
    ids = list(all_ids(plan))
    n_prio = int(store.opp.opportunity_score.reindex(ids).ge(0.75).sum())
    visit = {i for i in ids if not store.cox.is_client.get(i, False)}                     # prospect yang dijadwalkan langsung
    intro = {d['intro'][0] for d in plan['hari'] if d.get('intro')} - visit               # prospect lewat perkenalan nasabah sendiri
    plan['kpi'] = [('Aksi', str(len(ids)), f"{len(plan['hari'])} hari"), ('Nasabah prioritas', str(n_prio), 'skor peluang ≥ 0,75'),
                   ('Prospect', str(len(visit) + len(intro)), f"{len(visit)} dikunjungi · {len(intro)} lewat perkenalan"),
                   plan['kpi'][3] if len(plan.get('kpi', [])) > 3 else ('Alarm dicek dulu', '0', '')]
