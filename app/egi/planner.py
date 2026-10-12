"""Rute perjalanan untuk rencana minggu (RM Copilot).

Jadwal (hari, jam, durasi, status) dikelola Kalender kunjungan (egi/kalender.py). Modul ini hanya:
jarak & urutan kunjungan per hari, dan KPI rencana.
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


def refresh_kpi(plan, store):
    """Hitung ulang KPI rencana (dipakai layar, PDF, JSON)."""
    ids = list(all_ids(plan))
    n_prio = int(store.opp.opportunity_score.reindex(ids).ge(0.75).sum())
    visit = {i for i in ids if not store.cox.is_client.get(i, False)}                     # prospect yang dijadwalkan langsung
    intro = {d['intro'][0] for d in plan['hari'] if d.get('intro')} - visit               # prospect lewat perkenalan nasabah sendiri
    plan['kpi'] = [('Aksi', str(len(ids)), f"{len(plan['hari'])} hari"), ('Nasabah prioritas', str(n_prio), 'skor peluang ≥ 0,75'),
                   ('Prospect', str(len(visit) + len(intro)), f"{len(visit)} dikunjungi · {len(intro)} lewat perkenalan"),
                   plan['kpi'][3] if len(plan.get('kpi', [])) > 3 else ('Alarm dicek dulu', '0', '')]
