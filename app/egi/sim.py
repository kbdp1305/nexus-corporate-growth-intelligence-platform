"""Simulasi produk per perusahaan: rumus & asumsi EV yang sama dengan NB08.

EV = P(konversi) × ukuran deal × (margin − PD_harapan × LGD [hanya kredit]) × horizon − biaya aksi
PD_harapan = P(Low)·PD_Low + P(Medium)·PD_Medium + P(High)·PD_High (probabilitas model risiko NB06).
Asumsi dibaca dari outputs/scores/assumptions_opportunity.csv; semua bisa digeser di layar.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .data import ROOT

CREDIT = {'P06', 'P07'}           # produk kredit (Lending) → kena PD × LGD dan ditahan untuk risiko High


def assumptions() -> dict:
    a = pd.read_csv(ROOT / 'outputs/scores/assumptions_opportunity.csv')
    return dict(zip(a.asumsi, a.nilai))


def catalog() -> pd.DataFrame:
    return pd.read_csv(ROOT / 'data/raw/product_master.csv').set_index('product_id')


def pd_expected(risk_row, A) -> float:
    return float(risk_row.p_low * A['PD_Low'] + risk_row.p_medium * A['PD_Medium'] + risk_row.p_high * A['PD_High'])


def defaults(store, cid, pid, A) -> dict:
    """Nilai awal simulasi: dari opportunity_products bila ada, selain itu median produk di segmen."""
    seg = store.seg.segment.get(cid) or 'S2 Menengah'
    row = store.prod[(store.prod.company_id == cid) & (store.prod.product_id == pid)]
    peer = store.prod[(store.prod.product_id == pid) & (store.prod.seg == seg)]
    p = float(row.p_konversi.iloc[0]) if len(row) else float(peer.p_konversi.median()) if len(peer) else 0.1
    deal = A.get(f'ukuran_deal_{seg}_{pid}_Rp_juta', float(peer.ukuran_deal_Rp_juta.median()) if len(peer) else 100.0)
    credit = pid in CREDIT
    return {'seg': seg, 'p': p, 'deal': float(deal), 'credit': credit, 'margin': A['margin_kredit'] if credit else A['margin_non_kredit'],
            'pd': pd_expected(store.risk.loc[cid], A) if credit else 0.0, 'lgd': A['LGD'], 'horizon': A['horizon_tahun'],
            'cost': A[f'biaya_aksi_{seg}_Rp_juta'], 'dari_model': bool(len(row))}


def ev(p, deal, margin, pd_, lgd, horizon, cost) -> dict:
    """Rincian EV (Rp juta). Titik impas = P(konversi) minimum agar EV ≥ 0."""
    unit = deal * (margin - pd_ * lgd) * horizon          # nilai bersih bila deal terjadi
    pendapatan, kerugian = p * deal * margin * horizon, p * deal * pd_ * lgd * horizon
    impas = cost / unit if unit > 0 else np.nan
    return {'pendapatan': pendapatan, 'kerugian': kerugian, 'biaya': cost, 'ev': p * unit - cost, 'nilai_bila_deal': unit,
            'impas_p': impas, 'roi': (p * unit - cost) / cost if cost else np.nan}
