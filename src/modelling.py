"""BNI EGI — estimator model risiko (notebook 04–07).

Didefinisikan di modul, bukan di notebook, supaya model yang disimpan dengan joblib
(models/04_modelling/*.joblib) bisa dibaca lagi di notebook lain:

    import sys; sys.path.insert(0, str(PROJECT_ROOT / 'src'))
    import joblib
    model = joblib.load(PROJECT_ROOT / 'models' / '04_modelling' / 'M1__set_core.joblib')

Isi:
- MONO            : arah monoton per fitur (§5.3): +1 = makin besar makin berisiko, −1 = sebaliknya.
- OrdinalMonotone : dekomposisi ordinal Frank & Hall (2001) dengan batasan monoton.
"""
import numpy as np
import pandas as pd
from sklearn.base import BaseEstimator, ClassifierMixin
from sklearn.ensemble import RandomForestClassifier, HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer

try:
    import xgboost as xgb
except ImportError:
    xgb = None
try:
    import lightgbm as lgb
except ImportError:
    lgb = None

SEED = 2026

MONO = {**{c: +1 for c in ['fin_log_der', 'der_pz', 'pay_late_6m', 'pay_late_12m', 'pay_late_30m', 'tax_late_6m', 'tax_late_12m', 'tax_late_30m',
                          'pay_split_12m', 'timing_delta', 'out_in_6m', 'out_in_12m', 'utilization', 'top_buyer_share', 'exp_shocked_anchor',
                          'max_inflow_z_12m', 'inflow_cv_sa']},
        **{c: -1 for c in ['fin_log_cr', 'cr_pz', 'fin_npm', 'npm_pz', 'fin_sicr', 'icr_pz', 'has_report', 'is_audited', 'inflow_growth_sa', 'capture_ratio']}}


class OrdinalMonotone(BaseEstimator, ClassifierMixin):
    """Dekomposisi ordinal Frank & Hall dengan batasan monoton.
    base: 'rf' | 'xgb' | 'lgb' | 'hgb_depth' (pengganti XGBoost) | 'hgb_leaf' (pengganti LightGBM)."""

    def __init__(self, base='rf', params=None, monotone=True, seed=SEED):
        self.base, self.params, self.monotone, self.seed = base, params, monotone, seed

    def _estimator(self, cst):
        p = dict(self.params or {}); s = self.seed
        if self.base == 'rf':
            return RandomForestClassifier(**{**dict(n_estimators=500, min_samples_leaf=3, max_features='sqrt', n_jobs=-1, random_state=s), **p}, monotonic_cst=cst)
        if self.base == 'xgb':
            return xgb.XGBClassifier(**{**dict(n_estimators=300, learning_rate=0.05, max_depth=3, min_child_weight=3, subsample=0.8, colsample_bytree=0.8,
                                               reg_lambda=1.0, tree_method='hist', eval_metric='logloss', n_jobs=4, random_state=s), **p},
                                     monotone_constraints='(' + ','.join(str(int(v)) for v in cst) + ')')
        if self.base == 'lgb':
            return lgb.LGBMClassifier(**{**dict(n_estimators=300, learning_rate=0.05, num_leaves=15, min_child_samples=20, subsample=0.8, subsample_freq=1,
                                                colsample_bytree=0.8, reg_lambda=1.0, n_jobs=4, random_state=s, verbose=-1), **p},
                                      monotone_constraints=[int(v) for v in cst])
        if self.base == 'hgb_depth':
            return HistGradientBoostingClassifier(**{**dict(max_depth=3, learning_rate=0.05, max_iter=300, min_samples_leaf=20, l2_regularization=1.0,
                                                            early_stopping=False, max_bins=63, random_state=s), **p}, monotonic_cst=cst)
        if self.base == 'hgb_leaf':
            return HistGradientBoostingClassifier(**{**dict(max_leaf_nodes=15, max_depth=None, learning_rate=0.05, max_iter=300, min_samples_leaf=20,
                                                            l2_regularization=1.0, max_features=0.8, early_stopping=False, max_bins=63, random_state=s), **p}, monotonic_cst=cst)
        raise ValueError(self.base)

    def fit(self, X, y, sample_weight=None):
        X = pd.DataFrame(X); y = np.asarray(y)
        self.feature_names_in_ = np.array(X.columns); self.classes_ = np.array([0, 1, 2])
        self.cst_ = [int(MONO.get(c, 0)) if self.monotone else 0 for c in X.columns]
        if self.base == 'rf':                          # RF scikit-learn dengan batasan monoton tidak menerima NaN
            self.imp_ = SimpleImputer(strategy='median', keep_empty_features=True).fit(X); Xf = self.imp_.transform(X)
        else:
            self.imp_ = None; Xf = X.to_numpy(dtype=float)
        self.models_ = [self._estimator(self.cst_).fit(Xf, (y > k).astype(int), sample_weight=sample_weight) for k in (0, 1)]
        return self

    def predict_proba(self, X):
        X = pd.DataFrame(X)[self.feature_names_in_]
        Xf = self.imp_.transform(X) if self.imp_ is not None else X.to_numpy(dtype=float)
        p1 = self.models_[0].predict_proba(Xf)[:, 1]; p2 = np.minimum(self.models_[1].predict_proba(Xf)[:, 1], p1)
        return np.column_stack([1 - p1, p1 - p2, p2])

    def predict(self, X):
        return self.predict_proba(X).argmax(1)
