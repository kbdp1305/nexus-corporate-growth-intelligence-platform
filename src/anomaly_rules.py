"""BNI EGI — aturan deteksi anomali "Why Now" (champion NB04), dipakai bersama oleh notebook 06 dan dashboard Streamlit.

    sys.path.insert(0, str(PROJECT_ROOT / 'src'))
    from features import load_features
    from anomaly_rules import load_rules, apply_rules
    rules  = load_rules(PROJECT_ROOT / 'models' / '06_final' / 'anomaly_rules.json')
    alerts = apply_rules(load_features(PROJECT_ROOT, 'anomaly'), rules)       # tabel alarm + alasan bahasa RM

Semua sinyal bersifat online (bulan t hanya memakai data ≤ t). Persentil dihitung per bulan antar-nasabah (penampang lintang).
Isi:
- DEFAULT_RULES       : ambang aturan NB04 (dapat diubah, mis. lewat slider dashboard)
- apply_rules         : panel → alarm champion (setiap nasabah-bulan yang menyala, dengan is_new, skor prioritas, peringkat, alasan)
- apply_challenger    : skor gabungan rank-average untuk distress & ekspansi (anggaran alarm = champion) → mode shadow
- evaluate_alerts     : metrik terhadap ground truth (presisi alarm baru, recall, recall dini, lead time, presisi top-k, alarm palsu)
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import numpy as np
import pandas as pd

EVENT_TYPES = ['spike', 'buyer_exit', 'contagion', 'wallet_erosion', 'distress', 'expansion']

DEFAULT_RULES = {
    'version': 'anomaly-rules-v1 (NB04)',
    'start_month': '2024-07',
    'k_top': 30,
    'spike': {'spike_candidate_eq': 1},
    'buyer_exit': {'buyer_exit_share_min': 0.15},
    'contagion': {'exp_shocked_anchor_t_min': 0.20},
    'wallet_erosion': {'chg_3v6_monthly_pct_max': 0.02, 'timing_delta_t_lt': 0.25, 'capture_chg_6m_le': 0.0},
    'distress': {'timing_jump_3v9_min': 0.30, 'timing_delta_t_min': 0.25, 'confirm_out_in_delta_min': None, 'confirm_cusum_down_min': None},
    'expansion': {'cusum_up_monthly_pct_gt': 0.98, 'chg_3v6_monthly_pct_gt': 0.98},
}

RULE_TEXT = {
    'spike': 'spike_candidate = 1',
    'buyer_exit': 'buyer_exit_share ≥ {buyer_exit_share_min}',
    'contagion': 'exp_shocked_anchor_t ≥ {exp_shocked_anchor_t_min}',
    'wallet_erosion': 'chg_3v6 ≤ p{chg_3v6_monthly_pct_max} bulanan & timing_delta_t < {timing_delta_t_lt} & capture_chg_6m ≤ {capture_chg_6m_le}',
    'distress': 'timing_jump_3v9 ≥ {timing_jump_3v9_min} atau timing_delta_t ≥ {timing_delta_t_min}',
    'expansion': 'cusum_up > p{cusum_up_monthly_pct_gt} atau chg_3v6 > p{chg_3v6_monthly_pct_gt} bulanan',
}


def load_rules(path=None):
    if path is None or not Path(path).exists():
        return copy.deepcopy(DEFAULT_RULES)
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save_rules(rules, path):
    Path(path).write_text(json.dumps(rules, ensure_ascii=False, indent=1), encoding='utf-8')


def _prep(panel, rules):
    P = panel[panel.ym >= rules.get('start_month', '2024-07')].reset_index(drop=True).copy()
    months = sorted(P.ym.unique()); P['m'] = P.ym.map({m: i for i, m in enumerate(months)})
    return P, months


def _mpct(P, s):
    return s.groupby(P.ym).rank(pct=True)


def _signals(P):
    cols = ['inflow_resid_z', 'buyer_exit_share', 'exp_shocked_anchor_t', 'timing_jump_3v9', 'timing_delta_t', 'cusum_up',
            'cusum_down', 'chg_3v6', 'out_in_delta', 'cp_change']
    S = {c: _mpct(P, P[c]) for c in cols}
    S['neg_chg'] = _mpct(P, -P.chg_3v6)
    return S


def rule_flags(P, rules, S=None):
    """{jenis: (flag, skor prioritas, teks aturan)} untuk champion."""
    S = S or _signals(P); r = rules
    q_lo = P.groupby('ym').chg_3v6.transform(lambda s: s.quantile(r['wallet_erosion']['chg_3v6_monthly_pct_max']))
    q_hi_c = P.groupby('ym').chg_3v6.transform(lambda s: s.quantile(r['expansion']['chg_3v6_monthly_pct_gt']))
    q_hi_u = P.groupby('ym').cusum_up.transform(lambda s: s.quantile(r['expansion']['cusum_up_monthly_pct_gt']))
    we, di = r['wallet_erosion'], r['distress']
    # distress: sinyal timing; opsional (v2) wajib dikonfirmasi arus kas: out_in_delta ≥ x ATAU cusum_down ≥ y
    f_dist = (P.timing_jump_3v9 >= di['timing_jump_3v9_min']) | (P.timing_delta_t >= di['timing_delta_t_min'])
    if di.get('confirm_out_in_delta_min') is not None or di.get('confirm_cusum_down_min') is not None:
        conf = pd.Series(False, index=P.index)
        if di.get('confirm_out_in_delta_min') is not None: conf |= P.out_in_delta >= di['confirm_out_in_delta_min']
        if di.get('confirm_cusum_down_min') is not None: conf |= P.cusum_down >= di['confirm_cusum_down_min']
        f_dist = f_dist & conf
    # erosi wallet: syarat capture bisa dimatikan (v2) karena capture_chg_6m sering kosong (lag laporan)
    f_ero = (P.chg_3v6 <= q_lo) & ~(P.timing_delta_t >= we['timing_delta_t_lt'])
    if we.get('capture_chg_6m_le') is not None: f_ero &= ~(P.capture_chg_6m > we['capture_chg_6m_le'])
    out = {
        'spike': (P.spike_candidate == r['spike']['spike_candidate_eq'], S['inflow_resid_z']),
        'buyer_exit': (P.buyer_exit_share >= r['buyer_exit']['buyer_exit_share_min'], S['buyer_exit_share']),
        'contagion': (P.exp_shocked_anchor_t >= r['contagion']['exp_shocked_anchor_t_min'], S['exp_shocked_anchor_t']),
        'wallet_erosion': (f_ero, S['neg_chg']),
        'distress': (f_dist, np.fmax(S['timing_jump_3v9'], S['timing_delta_t'])),
        'expansion': ((P.cusum_up > q_hi_u) | (P.chg_3v6 > q_hi_c), np.fmax(S['cusum_up'], S['chg_3v6'])),
    }
    def num(x): return f'{x:g}'.replace('.', ',')
    def pct(x): return f'{100 * x:g}%'
    def text(k):
        if k == 'spike': return 'spike_candidate = 1'
        if k == 'buyer_exit': return f"buyer_exit_share ≥ {num(r[k]['buyer_exit_share_min'])}"
        if k == 'contagion': return f"exp_shocked_anchor_t ≥ {num(r[k]['exp_shocked_anchor_t_min'])}"
        if k == 'wallet_erosion':
            return (f"chg_3v6 ≤ p{pct(we['chg_3v6_monthly_pct_max'])} & bukan distress"
                    + (' & capture tidak naik' if we.get('capture_chg_6m_le') is not None else ''))
        if k == 'distress':
            t = f"timing_jump_3v9 ≥ {num(di['timing_jump_3v9_min'])} atau timing_delta_t ≥ {num(di['timing_delta_t_min'])}"
            c = [f"out_in_delta ≥ {num(di['confirm_out_in_delta_min'])}" if di.get('confirm_out_in_delta_min') is not None else None,
                 f"cusum_down ≥ {num(di['confirm_cusum_down_min'])}" if di.get('confirm_cusum_down_min') is not None else None]
            c = [x for x in c if x]
            return t + (f" & konfirmasi arus kas ({' atau '.join(c)})" if c else '')
        ex = r['expansion']
        same = ex['cusum_up_monthly_pct_gt'] == ex['chg_3v6_monthly_pct_gt']
        return (f"cusum_up atau chg_3v6 > p{pct(ex['chg_3v6_monthly_pct_gt'])} bulanan" if same else
                f"cusum_up > p{pct(ex['cusum_up_monthly_pct_gt'])} atau chg_3v6 > p{pct(ex['chg_3v6_monthly_pct_gt'])} bulanan")
    return {k: (f, s, text(k)) for k, (f, s) in out.items()}


def reason_text(v, t):
    """Alasan alarm dalam bahasa RM dari baris panel v (Series) dan jenis kejadian t."""
    f = lambda x, fmt: (fmt.format(x) if pd.notna(x) else 'n/a')
    if t == 'spike':
        return f'Inflow bulan ini melonjak (z {f(v.inflow_resid_z, "{:.1f}")} setelah koreksi musim industri); cek apakah transaksi sekali-jadi'
    if t == 'buyer_exit':
        return f'Pembeli yang aktif 12 bln lalu kini diam 2 bln menyumbang {f(v.buyer_exit_share, "{:.0%}")} inflow; counterparty aktif 3 bln: {f(v.n_active_cp_3m, "{:.0f}")}'
    if t == 'contagion':
        return f'{f(v.exp_shocked_anchor_t, "{:.0%}")} relasi bergantung pada anchor yang trennya patah; pantau pembayaran dari anchor'
    if t == 'wallet_erosion':
        return (f'Inflow 3 bln turun ({f(v.chg_3v6, "{:+.2f}")} log vs 6 bln sebelumnya) tanpa memburuknya ketepatan bayar → indikasi pindah bank; '
                f'porsi omzet lewat BNI berubah {f(v.capture_chg_6m, "{:+.1%}")}')
    if t == 'distress':
        return (f'Gaji/pajak telat {f(v.late_share_3m, "{:.0%}")} dalam 3 bln (naik {f(v.timing_jump_3v9, "{:+.0%}")} vs 9 bln sebelumnya); '
                f'outflow÷inflow berubah {f(v.out_in_delta, "{:+.2f}")}')
    return (f'Inflow naik dan bertahan (CUSUM naik {f(v.cusum_up, "{:.1f}")}; {f(v.chg_3v6, "{:+.2f}")} log vs 6 bln sebelumnya); '
            f'jumlah counterparty berubah {f(v.cp_change, "{:+.0f}")}')


def _build(P, flags_scores, source, with_reason=True):
    parts = []
    for typ, (flag, score, rule) in flags_scores.items():
        f = np.asarray(pd.Series(flag).fillna(False), bool)
        parts.append(P.loc[f, ['company_id', 'ym', 'm']].assign(event_type=typ, score=np.asarray(score)[f], rule=rule, source=source))
    A = pd.concat(parts, ignore_index=True).sort_values(['company_id', 'event_type', 'm'])
    prev = A.groupby(['company_id', 'event_type']).m.shift(1)
    A['is_new'] = prev.isna() | (A.m - prev > 1)
    A['rank_in_month'] = A.groupby('ym').score.rank(ascending=False, method='first').astype(int)
    if with_reason:
        PV = P.set_index(['company_id', 'ym'])
        A['reason'] = [reason_text(PV.loc[(c, ym)], t) for c, ym, t in zip(A.company_id, A.ym, A.event_type)]
    return A.reset_index(drop=True)


def apply_rules(panel, rules=None, with_reason=True):
    """Alarm champion untuk semua nasabah di panel. Kolom: company_id, ym, m, event_type, score, rule, source, is_new, rank_in_month, reason."""
    rules = rules or DEFAULT_RULES; P, _ = _prep(panel, rules)
    return _build(P, rule_flags(P, rules), 'aturan (champion)', with_reason)


def apply_challenger(panel, rules=None, with_reason=True):
    """Shadow: distress & ekspansi diganti skor gabungan rank-average; anggaran alarm per bulan = champion."""
    rules = rules or DEFAULT_RULES; P, _ = _prep(panel, rules); S = _signals(P); fl = rule_flags(P, rules, S)
    def rank_avg(cols, min_n):
        M = np.column_stack([S[c].values for c in cols]); n = np.isfinite(M).sum(1)
        with np.errstate(all='ignore'):
            s = np.nanmean(M, axis=1)
        s[n < min_n] = np.nan; return pd.Series(s, index=P.index)
    def equal_budget(score, champ_flag):
        budget = pd.Series(champ_flag).fillna(False).groupby(P.ym).transform('sum')
        r = score.groupby(P.ym).rank(ascending=False, method='first')
        return (r <= budget) & score.notna()
    sd = rank_avg(['timing_jump_3v9', 'timing_delta_t', 'cusum_down', 'out_in_delta', 'neg_chg'], 3)
    se = rank_avg(['cusum_up', 'chg_3v6', 'cp_change'], 2)
    ch = {'distress': (equal_budget(sd, fl['distress'][0]), sd, 'rank-average 5 sinyal (anggaran = champion)'),
          'expansion': (equal_budget(se, fl['expansion'][0]), se, 'rank-average 3 sinyal (anggaran = champion)')}
    return _build(P, ch, 'skor gabungan (challenger)', with_reason)


def evaluate_alerts(alerts, events, firms, months, k_top=30, n_firms=None):
    """Metrik di himpunan perusahaan `firms`.
    events: kolom company_id, ym, event_type, is_onset (early_warning dihitung sebagai distress).
    Alarm benar = kejadian GT jenis sama aktif di bulan t ± 1. Recall kejadian = alarm sejak onset−1 (distress onset−3) s.d. akhir kejadian+1;
    recall dini = s.d. onset+2; lead time distress = onset − alarm pertama di [onset−6, onset+2]."""
    firms = set(firms); n_firms = n_firms or len(firms)
    mi = {m: i for i, m in enumerate(sorted(set(events.ym) | set(months)))}; off = mi[sorted(months)[0]]
    E = events[events.company_id.isin(firms)].copy(); E['type'] = E.event_type.replace({'early_warning': 'distress'}); E['m'] = E.ym.map(mi) - off
    ACT = set(zip(E.company_id, E.type, E.m)); ACT_ANY = set(zip(E.company_id, E.m))
    ON = E[(E.is_onset == 1) & (E.event_type != 'early_warning')][['company_id', 'type', 'm']]
    END = E.groupby(['company_id', 'type']).m.max().to_dict()
    A = alerts[alerts.company_id.isin(firms)].copy()
    A['tp'] = [any((c, t, m + d) in ACT for d in (-1, 0, 1)) for c, t, m in zip(A.company_id, A.event_type, A.m)]
    A['tp_any'] = [any((c, m + d) in ACT_ANY for d in (-1, 0, 1)) for c, m in zip(A.company_id, A.m)]
    new = A[A.is_new]; rows = []
    for typ in sorted(A.event_type.unique()):
        a_t = A[A.event_type == typ]; n_t = new[new.event_type == typ]; ev = ON[ON.type == typ]; lo = -3 if typ == 'distress' else -1
        ms_by = a_t.groupby('company_id').m.apply(list).to_dict(); det, early, leads = [], [], []
        for c, m0 in zip(ev.company_id, ev.m):
            ms = ms_by.get(c, []); m_end = END[(c, typ)]
            det.append(any(m0 + lo <= m <= m_end + 1 for m in ms)); early.append(any(m0 + lo <= m <= m0 + 2 for m in ms))
            ml = [m for m in ms if m0 - 6 <= m <= m0 + 2]
            if typ == 'distress' and ml: leads.append(m0 - min(ml))
        rows.append({'jenis': typ, 'alarm_baru_per_bulan': len(n_t) / len(months), 'presisi_alarm_baru': n_t.tp.mean() if len(n_t) else np.nan,
                     'kejadian_GT': len(ev), 'recall_kejadian': np.mean(det) if det else np.nan, 'recall_dini': np.mean(early) if early else np.nan,
                     'lead_median_bln': np.median(leads) if leads else np.nan, 'pct_lead_ge_1bln': np.mean(np.array(leads) >= 1) if leads else np.nan})
    R = pd.DataFrame(rows)
    top = new.sort_values('score', ascending=False).groupby('ym').head(k_top)
    dist = R.set_index('jenis').reindex(['distress'])
    overall = {'presisi_top_k': top.tp.mean(), 'presisi_top_k_jenis_apa_pun': top.tp_any.mean(), 'k': k_top,
               'alarm_baru_per_bulan': len(new) / len(months), 'alarm_palsu_per_100_nasabah_per_bulan': 100 * (~new.tp_any).sum() / n_firms / len(months),
               'lead_median_distress': dist.lead_median_bln.iloc[0], 'pct_distress_lead_ge_1bln': dist.pct_lead_ge_1bln.iloc[0]}
    return R, overall, top
