"""BNI EGI — segmentasi skala & Opportunity Score (notebook 08 + Streamlit).

Isi:
- build_scale_features : 7 fitur skala per perusahaan (karyawan, omzet, aset, ekuitas, nilai relasi, mitra, derajat).
- Segmenter            : imputasi dari log karyawan → RobustScaler (clip ±5) → K-means; label urut omzet (S1 Kecil < S2 Menengah < S3 Besar).
- holdings_at          : matriks kepemilikan produk pada bulan acuan (dari open_month; produk yang sudah ditutup tidak terlihat).
- peer_rate            : porsi peer (segmen × industri, tanpa diri sendiri) yang memiliki produk → 'celah produk'.
- build_components     : 5 komponen peluang per perusahaan pada bulan acuan.
- opportunity_score    : skor per segmen (persentil-dalam-segmen) + penyesuaian risiko + bonus Why Now.

Semua fungsi hanya memakai data ≤ bulan acuan (ref). Tidak ada label risiko atau outcome adopsi di sini.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.linear_model import LinearRegression
from sklearn.preprocessing import RobustScaler

SCALE_FEATURES = ['log_emp', 'log_rev', 'log_assets', 'log_equity', 'log_rel_value', 'log_partners', 'log_degree']
SEG_NAMES = {0: 'S1 Kecil', 1: 'S2 Menengah', 2: 'S3 Besar'}
COMPONENTS = ['dompet_belum_digarap', 'ekosistem', 'kebutuhan_modal', 'celah_produk', 'erosi_wallet']

# bobot logika bisnis (tinggi 3, sedang 2, rendah 1) — rencana §8b.5
DEFAULT_WEIGHTS = {
    'S3 Besar':    {'dompet_belum_digarap': 3, 'ekosistem': 3, 'kebutuhan_modal': 2, 'celah_produk': 2, 'erosi_wallet': 3},
    'S2 Menengah': {'dompet_belum_digarap': 2, 'ekosistem': 2, 'kebutuhan_modal': 3, 'celah_produk': 2, 'erosi_wallet': 3},
    'S1 Kecil':    {'dompet_belum_digarap': 1, 'ekosistem': 1, 'kebutuhan_modal': 2, 'celah_produk': 3, 'erosi_wallet': 2},
}
WHY_NOW_UP = ('expansion', 'wallet_erosion')                 # peluang / retensi → naikkan prioritas
WHY_NOW_CAUTION = ('distress', 'buyer_exit', 'contagion')    # tanda bahaya → tunda produk kredit


# ---------------------------------------------------------------- segmentasi
def active_relations(rel, ref_date):
    """Relasi aktif pada tanggal acuan (mulai ≤ ref, belum berakhir)."""
    start = rel.relationship_start.fillna('1900-01-01')
    end = rel.relationship_end
    return rel[(start <= ref_date) & (end.isna() | (end > ref_date))]


def build_scale_features(companies, financials, relationships, fiscal_year=2025, ref_date='2026-06-30'):
    """7 fitur skala. Omzet/aset/ekuitas NaN bila laporan tahun itu tidak ada (diimputasi di Segmenter)."""
    co = companies.set_index('company_id') if 'company_id' in companies else companies
    f = financials[financials.fiscal_year == fiscal_year].set_index('company_id')
    act = active_relations(relationships, ref_date)
    X = pd.DataFrame(index=co.index)
    X['log_emp'] = np.log(co.employees.clip(lower=1))
    for c, src in [('log_rev', 'revenue_idr_bn'), ('log_assets', 'total_assets_idr_bn'), ('log_equity', 'total_equity_idr_bn')]:
        X[c] = np.log(f[src].clip(lower=1e-3)).reindex(X.index)
    X['log_rel_value'] = np.log1p(act.groupby('source_id').annual_transaction_value_idr_mn.sum()).reindex(X.index).fillna(0)
    X['log_partners'] = np.log1p(act.groupby('source_id').target_id.nunique()).reindex(X.index).fillna(0)
    X['log_degree'] = np.log1p(pd.concat([act.source_id, act.target_id]).value_counts()).reindex(X.index).fillna(0)
    return X[SCALE_FEATURES]


class Segmenter:
    """Imputasi (regresi linear dari log_emp) → RobustScaler → clip ±5 → K-means.
    Label diurutkan menurut median log_rev: 0 = terkecil."""

    def __init__(self, k=3, n_init=20, random_state=2026, clip=5.0):
        self.k, self.n_init, self.random_state, self.clip = k, n_init, random_state, clip

    def _impute(self, X):
        X = X[SCALE_FEATURES].copy()
        miss = X[self.imp_cols_].isna().any(axis=1)
        if miss.any():
            for c, lr in self.imputers_.items():
                m = X[c].isna()
                if m.any():
                    X.loc[m, c] = lr.predict(X.loc[m, ['log_emp']])
        return X

    def fit(self, X):
        X = X[SCALE_FEATURES]
        self.imp_cols_ = ['log_rev', 'log_assets', 'log_equity']
        ok = X[self.imp_cols_].notna().all(axis=1)
        self.imputers_ = {c: LinearRegression().fit(X.loc[ok, ['log_emp']], X.loc[ok, c]) for c in self.imp_cols_}
        Xi = self._impute(X)
        self.scaler_ = RobustScaler().fit(Xi)
        Z = np.clip(self.scaler_.transform(Xi), -self.clip, self.clip)
        self.km_ = KMeans(self.k, n_init=self.n_init, random_state=self.random_state).fit(Z)
        raw = self.km_.labels_
        order = pd.Series(Xi.log_rev.values).groupby(raw).median().sort_values().index
        self.map_ = {int(o): i for i, o in enumerate(order)}
        return self

    def transform(self, X):
        return np.clip(self.scaler_.transform(self._impute(X)), -self.clip, self.clip)

    def predict(self, X):
        raw = self.km_.predict(self.transform(X))
        return np.array([self.map_[int(r)] for r in raw])

    def confidence(self, X):
        """1 − d1/d2 (jarak ke centroid terdekat vs kedua). 0 = di perbatasan, 1 = tepat di centroid."""
        D = np.sort(self.km_.transform(self.transform(X)), axis=1)
        return 1 - D[:, 0] / np.maximum(D[:, 1], 1e-9)

    def names(self, labels):
        names = SEG_NAMES if self.k == 3 else {i: f'S{i + 1}' for i in range(self.k)}
        return pd.Series(labels).map(names).values


# ---------------------------------------------------------------- produk
def holdings_at(holdings, ref_month, ids, products):
    """1 bila produk dibuka ≤ ref_month (snapshot Jun 2026; produk yang sudah ditutup tak terlihat)."""
    h = holdings[holdings.open_month <= ref_month]
    H = h.pivot_table(index='company_id', columns='product_id', values='active', aggfunc='max')
    return H.reindex(index=ids, columns=products).fillna(0).astype(int)


def peer_rate(H, groups, min_n=10, fallback=None):
    """Porsi peer (grup yang sama, tanpa diri sendiri) yang memegang tiap produk.
    Grup dengan anggota < min_n memakai fallback (mis. segmen saja)."""
    g = pd.Series(groups, index=H.index)
    s = H.groupby(g).transform('sum'); n = g.map(g.value_counts())
    R = (s - H).div((n - 1).clip(lower=1), axis=0)
    if fallback is not None:
        fb = pd.Series(fallback, index=H.index)
        s2 = H.groupby(fb).transform('sum'); n2 = fb.map(fb.value_counts())
        R2 = (s2 - H).div((n2 - 1).clip(lower=1), axis=0)
        small = n < min_n
        R.loc[small] = R2.loc[small]
    return R


# ---------------------------------------------------------------- komponen
def _rank_within(s, seg):
    return s.groupby(seg).rank(pct=True)


def build_components(ids, seg_name, industry, H, panel_ref, revenue_idr_bn, relationships, ref_date,
                     credit_products, risk_class=None, medium_credit_factor=0.5):
    """Komponen mentah (sebelum persentil) + celah produk per produk.

    Returns (C, NEED): C = DataFrame per perusahaan (5 komponen mentah);
    NEED = DataFrame perusahaan × produk = peer rate untuk produk yang BELUM dimiliki
    (0 bila sudah dimiliki), sesudah penyesuaian risiko pada produk kredit.
    """
    seg = pd.Series(seg_name, index=ids)
    ind = pd.Series(industry, index=ids)
    pan = panel_ref.reindex(ids)
    act = active_relations(relationships, ref_date)
    clients = set(ids)
    C = pd.DataFrame(index=ids)
    cap = pan.capture_t.clip(0, 1)
    C['dompet_belum_digarap'] = np.log1p((1 - cap) * pd.Series(revenue_idr_bn, index=ids) * 1000)    # Rp juta
    nonbni = act[~act.target_id.isin(clients)].groupby('source_id').target_id.nunique()
    val = np.log1p(act.groupby('source_id').annual_transaction_value_idr_mn.sum())
    C['ekosistem'] = (_rank_within(nonbni.reindex(ids).fillna(0), seg) + _rank_within(val.reindex(ids).fillna(0), seg)) / 2
    C['kebutuhan_modal'] = (_rank_within(pan.chg_3v6, seg) + _rank_within(pan.cusum_up, seg)) / 2
    C['erosi_wallet'] = -pan.capture_chg_6m
    R = peer_rate(H, seg.astype(str) + '|' + ind.astype(str), fallback=seg)
    NEED = R.where(H == 0, 0.0)
    if risk_class is not None:
        rc = pd.Series(risk_class, index=ids)
        cp = [p for p in credit_products if p in NEED]
        NEED.loc[rc == 'High', cp] = 0.0
        NEED.loc[rc == 'Medium', cp] = NEED.loc[rc == 'Medium', cp] * medium_credit_factor
    C['celah_produk'] = NEED.max(axis=1)
    return C[COMPONENTS], NEED


def opportunity_score(C, seg_name, weights=None, why_now_up=None, bonus=0.05):
    """Skor = persentil-dalam-segmen(Σ w·persentil komponen / Σ w + bonus Why Now).
    Komponen NaN (mis. tanpa data arus kas) diisi median persentil 0,5."""
    weights = weights or DEFAULT_WEIGHTS
    seg = pd.Series(seg_name, index=C.index)
    P = C.apply(lambda s: _rank_within(s, seg)).fillna(0.5)
    base = pd.Series(0.0, index=C.index)
    for s, w in weights.items():
        m = seg == s
        if m.any():
            tot = sum(w.values())
            base[m] = sum(P.loc[m, k] * v for k, v in w.items()) / tot
    if why_now_up is not None:                      # bonus ditambahkan SEBELUM persentil akhir → tidak ada skor kembar di 1,0
        base = base + bonus * pd.Series(why_now_up, index=C.index).fillna(0).astype(float)
    return _rank_within(base, seg), P


def save_config(path, cfg):
    Path(path).write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding='utf-8')


def load_config(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))
