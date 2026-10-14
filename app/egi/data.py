"""Lapisan data dashboard: memuat output notebook 04–08 sekali, lalu menyediakan tabel turunan.

Dashboard hanya MEMBACA output notebook; tidak melatih ulang model apa pun.
Satu-satunya yang ditulis: outputs/app/ (catatan kunjungan, rencana yang disetujui, log audit).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st


def find_root(start: Path | None = None) -> Path:
    start = start or Path(__file__).resolve()
    for p in [start, *start.parents]:
        if (p / 'pyproject.toml').exists():
            return p
    raise FileNotFoundError('pyproject.toml tidak ditemukan — jalankan dari dalam folder proyek')


ROOT = find_root()
if str(ROOT / 'src') not in sys.path:
    sys.path.insert(0, str(ROOT / 'src'))
import reports as R  # noqa: E402

APP_OUT = ROOT / 'outputs' / 'app'
WS_PEN = 0.45                       # penetrasi < 45% & tanpa cabang = white-space
REF_MONTH = '2026-06'
SNAPSHOT = pd.Timestamp('2026-06-30')     # "hari ini" dashboard = tanggal potong data
FOLLOWUP_DAYS = 14
SEGS = ['S1 Kecil', 'S2 Menengah', 'S3 Besar']
CLIENT_TYPES = ('Existing credit client', 'Existing non-credit client')
DEFAULT_W = {'gap': 3, 'prospect': 2, 'low_pen': 2, 'poi': 1, 'eksp': 1}

REQUIRED = ['data/raw/companies.csv', 'data/raw/financials.csv', 'data/raw/relationships.csv', 'data/raw/product_holdings.csv',
            'data/raw/rm_action_log.csv', 'data/processed/features_risk.csv.gz', 'data/processed/features_anomaly_panel.csv.gz',
            'outputs/scores/risk_scores.csv', 'outputs/scores/opportunity_scores.csv', 'outputs/scores/opportunity_products.csv',
            'outputs/scores/segments.csv', 'outputs/scores/prospect_acquisition_scores.csv']


def missing_files():
    return [p for p in REQUIRED if not (ROOT / p).exists()]


def _simplify(ring, tol=0.00015):
    """Ramer–Douglas–Peucker dalam derajat (0,00015° ≈ 17 m): cukup untuk peta, payload ±10× lebih kecil. Cincin tetap tertutup."""
    pts = np.asarray(ring, dtype=float)
    if len(pts) < 8:
        return ring
    keep = np.zeros(len(pts), bool); keep[[0, -1]] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        a, b = stack.pop()
        if b <= a + 1:
            continue
        seg, d = pts[b] - pts[a], pts[a + 1:b] - pts[a]
        n = np.hypot(*seg)
        dist = np.abs(seg[0] * d[:, 1] - seg[1] * d[:, 0]) / n if n else np.hypot(d[:, 0], d[:, 1])
        i = int(dist.argmax())
        if dist[i] > tol:
            keep[a + 1 + i] = True; stack += [(a, a + 1 + i), (a + 1 + i, b)]
    out = pts[keep].round(5).tolist()
    return out if len(out) >= 4 else ring


class Store(R.Data):
    """Semua tabel + turunan. Dibuat sekali per sesi server (st.cache_resource)."""

    def __init__(self, root=ROOT):
        super().__init__(root)
        self.fr = pd.read_csv(root / 'data/processed/features_risk.csv.gz').set_index('company_id')
        self.acq = pd.read_csv(root / 'outputs/scores/prospect_acquisition_scores.csv').set_index('company_id')
        self.alerts_src = 'v2 (NB07, shadow)' if (root / 'outputs/scores/anomaly_alerts_v2_shadow.csv').exists() else 'v1 (NB04/NB06)'
        if 'champion_or_shadow' in self.alerts and self.alerts_src.startswith('v1'):
            self.alerts = self.alerts[self.alerts.champion_or_shadow == 'champion']
        co = self.co.join(self.seg[['segment', 'segment_confidence']]).join(self.risk[['pred_class', 'p_high', 'decision']])
        co['is_client'] = co.customer_type.isin(CLIENT_TYPES)
        co['rev_bn'] = self.fin[self.fin.fiscal_year == 2025].set_index('company_id').revenue_idr_bn.reindex(co.index)
        ratio = (co.rev_bn / co.employees).groupby(co.segment).median()
        co['rev_bn'] = co.rev_bn.fillna(co.segment.map(ratio) * co.employees)
        cap = self.fr.capture_ratio.reindex(co.index)
        co['gap_bn'] = np.where(co.is_client, (1 - cap.fillna(cap.median()).clip(0, 1)) * co.rev_bn, co.rev_bn)
        co = co.join(self.fr[['district_poi', 'district_has_branch', 'dist_branch_km']])
        recent = self.alerts[self.alerts.ym > '2026-03']
        co['eksp_recent'] = co.index.isin(recent[recent.event_type == 'expansion'].company_id)
        self.cox = co
        self.n_prod = self.hold.groupby('company_id').size()
        self.branches = pd.read_csv(root / 'data/raw/branches.csv')
        self.branches['name'] = self.branches.branch_name.str.replace(' (dummy)', '', regex=False)
        f = root / 'data/raw/kecamatan_boundaries.geojson'      # poligon OSM (src/fix_geo_coords.py); Bekasi tidak ada
        self.shapes = {ft['properties']['district']: [_simplify(poly[0]) for poly in ft['geometry']['coordinates']]
                       for ft in json.loads(f.read_text())['features']} if f.exists() else {}
        self.load_app_log()

    # ---------------------------------------------------------- log aksi (data asli + catatan dari dashboard)
    def load_app_log(self):
        f = APP_OUT / 'visit_log.csv'
        app = pd.read_csv(f) if f.exists() else pd.DataFrame(columns=self.log.columns)
        self.log_all = pd.concat([self.log.assign(sumber='rm_action_log'), app.assign(sumber='dashboard')], ignore_index=True)

    # ---------------------------------------------------------- wilayah
    def districts(self, w=None, seg=None):
        w = w or DEFAULT_W
        c = self.cox if not seg or seg == 'Semua' else self.cox[self.cox.segment == seg]
        g = c.groupby('district').agg(kota=('city', 'first'), n=('name', 'size'), nasabah=('is_client', 'sum'), besar=('segment', lambda s: (s == 'S3 Besar').sum()),
                                      cabang=('district_has_branch', 'max'), poi=('district_poi', 'mean'), jarak=('dist_branch_km', 'mean'),
                                      gap_T=('gap_bn', lambda s: s.sum() / 1000), eksp=('eksp_recent', 'sum'), lat=('latitude', 'mean'), lon=('longitude', 'mean'))
        g['prospect'] = g.n - g.nasabah
        g['pen'] = g.nasabah / g.n
        r = lambda s: s.rank(pct=True)
        tot = sum(w.values()) or 1
        g['skor'] = ((r(g.gap_T) * w['gap'] + r(g.prospect) * w['prospect'] + r(1 - g.pen) * w['low_pen'] + r(g.poi) * w['poi'] + r(g.eksp) * w['eksp']) / tot * 100).round(0)
        g['white_space'] = (g.pen < WS_PEN) & (g.cabang == 0)
        return g.sort_values('skor', ascending=False)

    # ---------------------------------------------------------- portofolio RM
    def portfolio(self, rm):
        ids = self.co.index[self.co.rm_id == rm] if rm != 'Semua RM' else self.co.index[self.cox.is_client]
        o = self.opp.reindex(ids).dropna(subset=['segment'])
        return o.join(self.cox[['name', 'industry', 'district', 'city']])

    def contacted(self, rm):
        return set(self.log_all[self.log_all.rm_id == rm].party_id) if rm != 'Semua RM' else set(self.log_all.party_id)

    def why_now(self, ids=None, months=3):
        a = self.alerts[self.alerts.ym > str(pd.Period(REF_MONTH, 'M') - months)]
        return a if ids is None else a[a.company_id.isin(ids)]

    # ---------------------------------------------------------- prospect lewat jaringan
    def prospects_for(self, rm):
        mine = set(self.co.index[self.co.rm_id == rm]) if rm != 'Semua RM' else set(self.cox.index[self.cox.is_client])
        a = self.act
        lk = a[a.source_id.isin(mine) | a.target_id.isin(mine)].copy()
        lk['me'] = lk.source_id.where(lk.source_id.isin(mine), lk.target_id)
        lk['other'] = lk.target_id.where(lk.source_id.isin(mine), lk.source_id)
        pp = lk[lk.other.isin(self.acq.index)]
        if pp.empty:
            return pd.DataFrame()
        g = pp.groupby('other').agg(lewat=('me', lambda s: sorted(set(s))), nilai_M=('annual_transaction_value_idr_mn', lambda s: s.sum() / 1000))
        g = g.join(self.acq[['segment', 'acquisition_score', 'risk_class', 'relasi_dengan_nasabah_BNI']]).join(self.cox[['name', 'district', 'industry']])
        ws = set(self.districts().query('white_space').index)
        g['white_space'] = g.district.isin(ws)
        g['lewat_nama'] = g.lewat.apply(lambda l: ', '.join(self.co.name.get(i, i) for i in l))
        return g.sort_values('nilai_M', ascending=False)

    def intro_paths(self, pid, rm):
        a = self.act
        lk = a[(a.source_id == pid) | (a.target_id == pid)]
        o = lk.source_id.where(lk.target_id == pid, lk.target_id)
        df = pd.DataFrame({'id': o.values, 'nilai_M': lk.annual_transaction_value_idr_mn.values / 1000, 'jenis': lk.relationship_type.values,
                           'arah': np.where(lk.source_id == pid, 'prospect → mitra', 'mitra → prospect')})
        df = df[df.id.isin(self.cox.index[self.cox.is_client])].join(self.co[['name', 'rm_id', 'customer_type']], on='id')
        df['milik_saya'] = df.rm_id == rm
        return df.sort_values(['milik_saya', 'nilai_M'], ascending=[False, False])

    # ---------------------------------------------------------- jaringan ego (untuk grafik)
    def ego(self, cid, limit=40):
        a = self.act
        lk = a[(a.source_id == cid) | (a.target_id == cid)]
        other = np.where(lk.source_id == cid, lk.target_id, lk.source_id)
        df = pd.DataFrame({'id': other, 'nilai': lk.annual_transaction_value_idr_mn.values, 'jenis': lk.relationship_type.values,
                           'peran': np.where(lk.source_id == cid, 'mitra (keluar)', 'mitra (masuk)')})
        df = df.groupby('id').agg(nilai=('nilai', 'sum'), jenis=('jenis', 'first'), peran=('peran', 'first')).reset_index()
        df['tipe'] = df.id.map(self.co.customer_type).fillna('Eksternal')
        df['nama'] = df.id.map(self.co.name).fillna(df.id)
        dis = set(self.why_now(df.id).query("event_type == 'distress'").company_id)
        df['distress'] = df.id.isin(dis)
        return df.sort_values('nilai', ascending=False).head(limit)

    def followups(self, rm, days=FOLLOWUP_DAYS):
        """Perusahaan yang kontak terakhirnya 'Interested' → tindak lanjut jatuh tempo kontak + days hari."""
        lg = self.log_all if rm == 'Semua RM' else self.log_all[self.log_all.rm_id == rm]
        last = lg.sort_values('contact_date').groupby('party_id').tail(1)
        f = last[last.response == 'Interested'].copy()
        f['jatuh_tempo'] = pd.to_datetime(f.contact_date) + pd.Timedelta(days=days)
        f['telat_hari'] = (pd.Timestamp.now().normalize() - f.jatuh_tempo).dt.days
        f['name'] = f.party_id.map(self.co.name)
        return f.sort_values('jatuh_tempo')

    # ---------------------------------------------------------- tulis (dashboard)
    def append_visit(self, row: dict):
        from .tables import WRITE_LOCK
        with WRITE_LOCK:
            APP_OUT.mkdir(parents=True, exist_ok=True)
            f = APP_OUT / 'visit_log.csv'
            frame = pd.read_csv(f, keep_default_na=False) if f.exists() else pd.DataFrame()
            if len(frame) and (frame.action_id == row['action_id']).any():
                return
            if row.get('event_id') and 'event_id' in frame and frame.event_id.eq(row['event_id']).any():
                return
            frame = pd.concat([frame, pd.DataFrame([row])], ignore_index=True)
            tmp = f.with_suffix('.tmp')
            frame.to_csv(tmp, index=False)
            tmp.replace(f)
            self.load_app_log()


def audit(event: str, **kw):
    APP_OUT.mkdir(parents=True, exist_ok=True)
    with open(APP_OUT / 'audit_log.jsonl', 'a', encoding='utf-8') as f:
        f.write(json.dumps({'waktu': datetime.now().isoformat(timespec='seconds'), 'event': event, **kw}, ensure_ascii=False, default=str) + '\n')


@st.cache_resource(show_spinner='Memuat data proyek…')
def get_store() -> Store:
    return Store(ROOT)


def read_optional(rel):
    p = ROOT / rel
    return pd.read_csv(p) if p.exists() else None
