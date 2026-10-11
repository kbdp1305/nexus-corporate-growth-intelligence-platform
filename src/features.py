"""BNI EGI — utilitas feature engineering (notebook 03–07).

Isi:
- PeerZScaler   : transformer scikit-learn untuk z robust relatif-peer (industri × ukuran), di-fit ulang di setiap fold.
- load_features : membaca dataset final dari data/processed (parquet atau csv.gz).
- FEATURE_GROUPS, SET_CLIENT, SET_PORTABLE : daftar kolom per kelompok & set.
"""
from pathlib import Path
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, TransformerMixin

RATIO_COLS = ['fin_log_der', 'fin_log_cr', 'fin_npm', 'fin_sicr']          # bahan mentah peer-z
PEER_KEYS = ['industry', 'size_class_reference']


class PeerZScaler(BaseEstimator, TransformerMixin):
    """z robust = (x − median peer) / (1,4826 · MAD peer), dengan back-off:
    industri × ukuran → industri → global bila anggota peer < min_n. Hasil di-clip ke [−clip, clip].

    Input  : DataFrame berisi RATIO_COLS + PEER_KEYS.
    Output : DataFrame kolom '<rasio>_pz' (nama: fin_log_der → der_pz, dst.).
    """

    def __init__(self, cols=RATIO_COLS, keys=PEER_KEYS, min_n=10, clip=6.0):
        self.cols, self.keys, self.min_n, self.clip = cols, keys, min_n, clip

    @staticmethod
    def _stats(s):
        med = s.median(); mad = 1.4826 * (s - med).abs().median()
        return med, (mad if mad and np.isfinite(mad) and mad > 0 else np.nan), s.notna().sum()

    def fit(self, X, y=None):
        X = pd.DataFrame(X)
        self.stats_ = {}
        for c in self.cols:
            g2 = {k: self._stats(v) for k, v in X.groupby(self.keys)[c]}
            g1 = {k: self._stats(v) for k, v in X.groupby(self.keys[0])[c]}
            self.stats_[c] = (g2, g1, self._stats(X[c]))
        return self

    def _lookup(self, c, k2, k1):
        g2, g1, g0 = self.stats_[c]
        for st in (g2.get(k2), g1.get(k1), g0):
            if st is not None and st[2] >= self.min_n and np.isfinite(st[1]):
                return st[0], st[1]
        return g0[0], g0[1]

    def transform(self, X):
        X = pd.DataFrame(X); out = pd.DataFrame(index=X.index)
        keys2 = list(zip(*[X[k] for k in self.keys])); keys1 = X[self.keys[0]].tolist()
        for c in self.cols:
            ms = np.array([self._lookup(c, k2, k1) for k2, k1 in zip(keys2, keys1)], dtype=float)
            z = (X[c].astype(float).values - ms[:, 0]) / ms[:, 1]
            out[self.out_name(c)] = np.clip(z, -self.clip, self.clip)
        return out

    @staticmethod
    def out_name(c):
        return {'fin_log_der': 'der_pz', 'fin_log_cr': 'cr_pz', 'fin_npm': 'npm_pz', 'fin_sicr': 'icr_pz'}.get(c, c + '_pz')

    def get_feature_names_out(self, input_features=None):
        return np.array([self.out_name(c) for c in self.cols])


def read_table(path_no_ext):
    """Baca <path>.parquet bila ada, kalau tidak <path>.csv.gz."""
    p = Path(path_no_ext)
    if p.with_suffix('.parquet').exists():
        return pd.read_parquet(p.with_suffix('.parquet'))
    return pd.read_csv(str(p) + '.csv.gz')


def load_features(root, which='risk'):
    """which = 'risk' (1 baris/perusahaan) atau 'anomaly' (1 baris/nasabah-bulan)."""
    name = {'risk': 'features_risk', 'anomaly': 'features_anomaly_panel'}[which]
    return read_table(Path(root) / 'data' / 'processed' / name)


def load_feature_sets(root):
    """Kelompok & set fitur yang ditulis notebook 03 ke data/processed/feature_sets.json.
    Kembalian: dict dengan kunci 'groups' (kelompok → kolom), 'set_client', 'set_portable', 'peer_raw', 'anomaly'."""
    import json
    return json.loads((Path(root) / 'data' / 'processed' / 'feature_sets.json').read_text(encoding='utf-8'))
