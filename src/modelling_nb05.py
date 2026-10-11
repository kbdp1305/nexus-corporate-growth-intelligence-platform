"""BNI EGI — utilitas notebook 05 (Modelling Optimization).

Kelas di modul ini (bukan di notebook) supaya model yang disimpan dengan joblib bisa di-load di NB06–07 dan dashboard:
    sys.path.insert(0, str(PROJECT_ROOT / 'src'))
    model = joblib.load(PROJECT_ROOT / 'models' / '05_optimization' / 'champion__set_core.joblib')
    P = model.predict_proba(df)          # [Low, Medium, High], sudah terkalibrasi

Isi:
- make_prep            : ColumnTransformer (PeerZScaler di dalam fold + kolom lain diteruskan)
- class_sample_weight  : bobot kelas: seimbang, tanpa bobot, seimbang^γ, cost-sensitive (matriks biaya §5.4), atau gabungan
- RiskModel            : satu pembungkus untuk LR (L2 / elastic net) dan pohon ordinal monoton, dengan skema bobot di atas
                         atau SMOTE (hanya di data latih), plus bobot sampel tambahan (importance weighting)
- EnsembleModel        : rata-rata (berbobot) probabilitas beberapa RiskModel
- PriorTemperatureCalibrator, IsotonicCalibrator, CalibratedModel
- metrik: bal_logloss, macro_f1, recall_high, brier, ece
- conformal: conformal_q, mondrian_q, weighted_conformal_q, sets_from_q
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import sklearn
from scipy.optimize import minimize
from sklearn.base import BaseEstimator, ClassifierMixin, clone
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.utils.class_weight import compute_sample_weight

from features import PeerZScaler, RATIO_COLS, PEER_KEYS
from modelling import OrdinalMonotone

PZ_OUT = list(PeerZScaler().get_feature_names_out())
SK_VER = tuple(int(x) for x in sklearn.__version__.split('.')[:2])

try:
    from imblearn.over_sampling import SMOTE as _SMOTE
    HAS_IMBLEARN = True
except ImportError:
    HAS_IMBLEARN = False


# ----------------------------------------------------------------------------- pra-proses
def make_prep(cols):
    """PeerZScaler (bila set memuat kolom *_pz) dihitung ulang dari rasio mentah; kolom lain diteruskan."""
    use_pz = any(c in PZ_OUT for c in cols)
    other = [c for c in cols if c not in PZ_OUT]
    parts = ([('pz', PeerZScaler(), RATIO_COLS + PEER_KEYS)] if use_pz else []) + [('rest', 'passthrough', other)]
    return ColumnTransformer(parts, remainder='drop', verbose_feature_names_out=False).set_output(transform='pandas')


def make_logreg(C=1.0, l1_ratio=0.0, seed=2026):
    """L2 (l1_ratio = 0, solver lbfgs) atau elastic net (0 < l1_ratio ≤ 1, solver saga); aman untuk scikit-learn < 1.8 dan ≥ 1.8."""
    if not l1_ratio:
        return LogisticRegression(C=C, max_iter=5000)
    if SK_VER >= (1, 8):
        return LogisticRegression(C=C, l1_ratio=l1_ratio, solver='saga', max_iter=8000, tol=1e-3, random_state=seed)
    return LogisticRegression(C=C, penalty='elasticnet', l1_ratio=l1_ratio, solver='saga', max_iter=8000, tol=1e-3, random_state=seed)


def simple_smote(X, y, k=5, seed=2026):
    """SMOTE sederhana (Chawla dkk., 2002) bila imbalanced-learn tidak terpasang: setiap kelas dinaikkan ke jumlah kelas terbesar
    dengan interpolasi ke tetangga terdekat sekelas (jarak pada data terstandardisasi)."""
    rng = np.random.default_rng(seed); X = np.asarray(X, float); y = np.asarray(y)
    mu, sd = X.mean(0), X.std(0) + 1e-9; Z = (X - mu) / sd
    n_max = np.bincount(y).max(); Xs, ys = [X], [y]
    for c in np.unique(y):
        idx = np.flatnonzero(y == c); need = n_max - len(idx)
        if need <= 0 or len(idx) < 2: continue
        Zc = Z[idx]; d = ((Zc[:, None, :] - Zc[None, :, :]) ** 2).sum(-1); np.fill_diagonal(d, np.inf)
        nn = np.argsort(d, 1)[:, :min(k, len(idx) - 1)]
        a = rng.integers(0, len(idx), need); b = nn[a, rng.integers(0, nn.shape[1], need)]; lam = rng.random((need, 1))
        Xs.append(X[idx[a]] + lam * (X[idx[b]] - X[idx[a]])); ys.append(np.full(need, c))
    return np.vstack(Xs), np.concatenate(ys)


# ----------------------------------------------------------------------------- bobot kelas (penanganan tidak seimbang)
COST_MATRIX = np.array([[0, 1, 2], [3, 0, 1], [10, 5, 0]])   # §5.4: baris = sebenarnya (Low/Medium/High), kolom = prediksi
WEIGHTINGS = ['balanced', 'none', 'balanced^0.5', 'balanced^1.5', 'cost', 'cost_balanced', 'smote']


def class_sample_weight(y, weighting='balanced'):
    """Bobot sampel per kelas, dinormalisasi ke rata-rata 1 (skala regularisasi tetap sebanding antar-skema).
    - 'balanced'      : n / (3 · n_k), sama dengan class_weight='balanced'
    - 'none', 'smote' : semua 1 (SMOTE menyeimbangkan lewat sampel sintetis)
    - 'balanced^γ'    : (n / (3 · n_k))^γ; γ < 1 lebih lunak, γ > 1 lebih menekankan kelas jarang
    - 'cost'          : biaya salah klasifikasi terbesar kelas itu (Elkan, 2001): Low 2, Medium 3, High 10
    - 'cost_balanced' : 'balanced' × 'cost'"""
    y = np.asarray(y).astype(int)
    if weighting == 'balanced':
        return compute_sample_weight('balanced', y)
    n_k = np.bincount(y, minlength=3).astype(float); bal = len(y) / (3 * np.maximum(n_k, 1))
    if weighting in ('none', 'smote'):
        w_k = np.ones(3)
    elif weighting.startswith('balanced^'):
        w_k = bal ** float(weighting.split('^')[1])
    elif weighting == 'cost':
        w_k = COST_MATRIX.max(1).astype(float)
    elif weighting == 'cost_balanced':
        w_k = bal * COST_MATRIX.max(1)
    else:
        raise ValueError(f'weighting tidak dikenal: {weighting!r}; pilihan: {WEIGHTINGS} atau balanced^<γ>')
    w = w_k[y]
    return w / w.mean()


# ----------------------------------------------------------------------------- model
class RiskModel(BaseEstimator, ClassifierMixin):
    """kind = 'lr' (params: C, l1_ratio) atau base pohon OrdinalMonotone: 'rf' | 'xgb' | 'lgb' | 'hgb_depth' | 'hgb_leaf'.
    weighting = 'balanced' (bobot kelas seimbang) | 'none' | 'balanced^γ' | 'cost' | 'cost_balanced' (lihat class_sample_weight)
                | 'smote' (SMOTE hanya di data latih fold ini).
    sample_weight di fit() dikalikan dengan bobot kelas (dipakai untuk importance weighting prospect)."""

    def __init__(self, kind='lr', cols=None, params=None, weighting='balanced', seed=2026):
        self.kind, self.cols, self.params, self.weighting, self.seed = kind, cols, params, weighting, seed

    def _estimator(self):
        p = dict(self.params or {})
        if self.kind == 'lr':
            return make_pipeline(SimpleImputer(strategy='median', add_indicator=True, keep_empty_features=True), StandardScaler(),
                                 make_logreg(p.get('C', 1.0), p.get('l1_ratio', 0.0), self.seed))
        return OrdinalMonotone(self.kind, p, monotone=True, seed=self.seed)

    def fit(self, X, y, sample_weight=None):
        y = np.asarray(y).astype(int)
        self.prep_ = make_prep(self.cols).fit(X)
        Xt = self.prep_.transform(X)
        w = class_sample_weight(y, self.weighting)
        if sample_weight is not None: w = w * np.asarray(sample_weight, float)
        if self.weighting == 'smote':
            self.smote_imp_ = SimpleImputer(strategy='median', keep_empty_features=True).fit(Xt)
            Xi = self.smote_imp_.transform(Xt)
            if HAS_IMBLEARN:
                Xr, yr = _SMOTE(random_state=self.seed, k_neighbors=5).fit_resample(Xi, y)
            else:
                Xr, yr = simple_smote(Xi, y, seed=self.seed)
            Xt, y, w = pd.DataFrame(Xr, columns=Xt.columns), yr, np.ones(len(yr))
        self.est_ = self._estimator()
        if self.kind == 'lr':
            self.est_.fit(Xt, y, logisticregression__sample_weight=w)
        else:
            self.est_.fit(Xt, y, sample_weight=w)
        self.classes_ = np.array([0, 1, 2]); self.feature_names_ = list(Xt.columns)
        return self

    def transform_features(self, X):
        Xt = self.prep_.transform(X)
        if self.weighting == 'smote': Xt = pd.DataFrame(self.smote_imp_.transform(Xt), columns=Xt.columns, index=Xt.index)
        return Xt

    def predict_proba(self, X):
        P = np.asarray(self.est_.predict_proba(self.transform_features(X)), float)
        return P / P.sum(1, keepdims=True)

    def predict(self, X):
        return self.predict_proba(X).argmax(1)


class EnsembleModel(BaseEstimator, ClassifierMixin):
    """Rata-rata berbobot probabilitas model anggota (anggota sudah di-fit)."""

    def __init__(self, members=None, weights=None):
        self.members, self.weights = members, weights
        self.classes_ = np.array([0, 1, 2])

    def predict_proba(self, X):
        w = np.asarray(self.weights, float); w = w / w.sum()
        return sum(wi * m.predict_proba(X) for wi, m in zip(w, self.members))

    def predict(self, X):
        return self.predict_proba(X).argmax(1)


# ----------------------------------------------------------------------------- kalibrasi
class PriorTemperatureCalibrator:
    """Temperature scaling (Guo dkk., 2017) + koreksi prior per kelas: p ∝ exp(log p / T + b), b_Low = 0.
    Koreksi prior perlu karena model dilatih dengan bobot seimbang (probabilitas High terdorong naik)."""

    def fit(self, P, y):
        L = np.log(np.clip(P, 1e-6, 1)); y = np.asarray(y).astype(int)
        def nll(theta):
            T = np.exp(theta[0]); Z = L / T + np.r_[0, theta[1:]]; Z -= Z.max(1, keepdims=True)
            return -(Z[np.arange(len(y)), y] - np.log(np.exp(Z).sum(1))).mean()
        self.theta_ = minimize(nll, np.zeros(3), method='L-BFGS-B').x
        return self

    def transform(self, P):
        L = np.log(np.clip(P, 1e-6, 1)); Z = L / np.exp(self.theta_[0]) + np.r_[0, self.theta_[1:]]
        Z -= Z.max(1, keepdims=True); E = np.exp(Z); return E / E.sum(1, keepdims=True)


class IsotonicCalibrator:
    """Isotonic per kelas (one-vs-rest), lalu dinormalisasi ke jumlah 1."""

    def fit(self, P, y):
        y = np.asarray(y).astype(int)
        self.iso_ = [IsotonicRegression(out_of_bounds='clip', y_min=0, y_max=1).fit(P[:, k], (y == k).astype(float)) for k in range(3)]
        return self

    def transform(self, P):
        Q = np.column_stack([iso.predict(P[:, k]) for k, iso in enumerate(self.iso_)]) + 1e-6
        return Q / Q.sum(1, keepdims=True)


class IdentityCalibrator:
    def fit(self, P, y): return self
    def transform(self, P): return P


CALIBRATORS = {'tanpa': IdentityCalibrator, 'temperature+prior': PriorTemperatureCalibrator, 'isotonic': IsotonicCalibrator}


def crossfit_calibrate(P, y, folds, method):
    """Kalibrasi lintas-fold: kalibrator di-fit di OOF fold lain, diterapkan ke fold ini (penilaian jujur)."""
    Q = np.zeros_like(P)
    for tr, va in folds:
        Q[va] = CALIBRATORS[method]().fit(P[tr], y[tr]).transform(P[va])
    return Q


class CalibratedModel(BaseEstimator, ClassifierMixin):
    """Model final + kalibrator (di-fit pada OOF). Ini objek yang disimpan untuk dashboard / NB06."""

    def __init__(self, model=None, calibrator=None, name=''):
        self.model, self.calibrator, self.name = model, calibrator, name
        self.classes_ = np.array([0, 1, 2])

    def predict_proba(self, X):
        return self.calibrator.transform(self.model.predict_proba(X))

    def predict(self, X):
        return self.predict_proba(X).argmax(1)


# ----------------------------------------------------------------------------- metrik
def bal_logloss(y, P):
    """Log-loss berbobot seimbang (setiap kelas sama penting) — versi halus dari metrik 'macro'. Objektif HPO."""
    y = np.asarray(y).astype(int)
    return log_loss(y, np.clip(P, 1e-6, 1), sample_weight=compute_sample_weight('balanced', y), labels=[0, 1, 2])


def _cm3(y, p):
    return np.bincount(3 * np.asarray(y).astype(int) + np.asarray(p).astype(int), minlength=9).reshape(3, 3)


def macro_f1(y, p):
    cm = _cm3(y, p); tp = np.diag(cm); den = cm.sum(0) + cm.sum(1)
    return float(np.mean(np.divide(2 * tp, den, out=np.zeros(3), where=den > 0)))


def recall_high(y, p):
    cm = _cm3(y, p); return float(cm[2, 2] / cm[2].sum()) if cm[2].sum() else 0.0


def brier(y, P):
    return float(((P - np.eye(3)[np.asarray(y).astype(int)]) ** 2).sum(1).mean())


def ece(y, P, n_bins=10, cls=None):
    """Expected calibration error. cls=None → top-label ECE; cls=k → ECE untuk P(kelas k)."""
    y = np.asarray(y).astype(int)
    if cls is None:
        conf = P.max(1); hit = (P.argmax(1) == y).astype(float)
    else:
        conf = P[:, cls]; hit = (y == cls).astype(float)
    edges = np.linspace(0, 1, n_bins + 1); b = np.clip(np.digitize(conf, edges[1:-1]), 0, n_bins - 1)
    return float(sum(abs(hit[b == i].mean() - conf[b == i].mean()) * (b == i).mean() for i in range(n_bins) if (b == i).any()))


# ----------------------------------------------------------------------------- conformal (LAC; Angelopoulos & Bates, 2021)
def conformal_q(y, P, alpha=0.10):
    s = 1 - P[np.arange(len(y)), np.asarray(y).astype(int)]; n = len(s)
    return float(np.quantile(s, min(1.0, np.ceil((n + 1) * (1 - alpha)) / n), method='higher'))


def mondrian_q(y, P, groups, alpha=0.10):
    """q̂ per kelompok (Mondrian conformal; Vovk dkk., 2005): jaminan cakupan berlaku di tiap kelompok."""
    groups = np.asarray(groups)
    return {g: conformal_q(np.asarray(y)[groups == g], P[groups == g], alpha) for g in pd.unique(groups)}


def weighted_conformal_q(scores_cal, w_cal, w_test, alpha=0.10):
    """Weighted conformal (Tibshirani dkk., 2019) untuk pergeseran kovariat: q̂(x) per titik uji.
    Distribusi skor = Σ p_i δ(s_i) + p_{n+1} δ(+∞), p_i = w_i / (Σw + w(x))."""
    o = np.argsort(scores_cal); s = np.asarray(scores_cal)[o]; cw = np.cumsum(np.asarray(w_cal, float)[o]); W = cw[-1]
    q = np.full(len(w_test), np.inf)
    for j, wt in enumerate(np.asarray(w_test, float)):
        k = np.searchsorted(cw, (1 - alpha) * (W + wt), side='left')
        if k < len(s): q[j] = s[k]
    return q


def classcond_q(y, P, alpha=0.10):
    """Conformal per kelas (Mondrian per label; Vovk dkk., 2005): q̂_k dari titik kalibrasi berkelas k.
    Menjamin cakupan ≥ 1 − α di SETIAP kelas, termasuk High yang jarang."""
    y = np.asarray(y).astype(int)
    return np.array([conformal_q(np.full((y == k).sum(), k), P[y == k], alpha) for k in range(3)])


def sets_classcond(P, qk):
    """Himpunan kelas {k : P(k) ≥ 1 − q̂_k}."""
    return P >= 1 - np.asarray(qk, float)[None, :]


def sets_from_q(P, q):
    """Himpunan kelas {k : P(k) ≥ 1 − q̂}; q boleh skalar atau vektor per baris."""
    q = np.asarray(q, float).reshape(-1, 1) if np.ndim(q) else q
    return P >= 1 - q
