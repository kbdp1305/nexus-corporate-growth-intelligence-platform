"""Hover cards inside the map; component events preserve the logged-in session."""
from pathlib import Path

import pandas as pd
import streamlit.components.v1 as components

from . import data, regions, ui

_map = components.declare_component('region_hover_map', path=str(Path(__file__).with_name('region_hover')))


def company_signals(store, ids):
    alerts = store.why_now(ids, months=3)
    alerts = alerts[alerts.ym <= data.REF_MONTH].sort_values(['ym', 'score'], ascending=False)
    result = {}
    for alert in alerts.drop_duplicates(['company_id', 'event_type']).itertuples():
        category = ('risk' if alert.event_type in {'distress', 'buyer_exit', 'contagion'} else
                    'momentum' if alert.event_type in {'expansion', 'wallet_erosion'} else 'other')
        result.setdefault(alert.company_id, []).append({
            'type': alert.event_type, 'label': ui.EVENT_STYLE.get(alert.event_type, ('', '', alert.event_type, ''))[2],
            'category': category, 'month': str(alert.ym), 'reason': str(alert.reason) if pd.notna(alert.reason) else ''})
    return result


def payload(store, stats, points, branches, claims, focus=None, highlight='Semua'):
    areas = []
    for district, row in stats.iterrows():
        rgb = regions.penetration_color(row.penetrasi)
        label = f'<b>{ui.esc(district)}</b><br>' + (
            f'Penetrasi BNI {row.penetrasi:.0%}<br>{row.nasabah} nasabah / {row.perusahaan} perusahaan dalam data'
            if row.perusahaan else 'Tanpa data perusahaan untuk filter ini')
        areas.append({'district': district, 'rings': store.shapes.get(district, []), 'center': [row.lat, row.lon],
                      'color': '#%02x%02x%02x' % tuple(rgb[:3]), 'label': label})
    companies = []
    signals = company_signals(store, points.index)
    for cid, company in points.iterrows():
        scores, column = (store.opp, 'opportunity_score') if company.is_client else (store.acq, 'acquisition_score')
        score = float(scores.loc[cid, column] * 100) if cid in scores.index and pd.notna(scores.loc[cid, column]) else None
        conversion = (float(store.opp.loc[cid, 'p_convert']) * 100
                      if company.is_client and cid in store.opp.index and pd.notna(store.opp.loc[cid, 'p_convert']) else None)
        owner = company.rm_id if company.is_client else claims.get(cid)
        companies.append({'id': cid, 'name': str(company['name']), 'industry': str(company.industry),
                          'district': str(company.district), 'segment': str(company.segment), 'risk': str(company.pred_class),
                          'client': bool(company.is_client), 'score': score, 'potential': score is not None and score >= 75,
                          'conversion': conversion,
                          'signals': signals.get(cid, []),
                          'owner': str(owner) if pd.notna(owner) and owner else 'Belum diklaim',
                          'center': [float(company.latitude), float(company.longitude)]})
    center = [float(stats.loc[focus, 'lat']), float(stats.loc[focus, 'lon'])] if focus in stats.index else [-6.2, 106.85]
    return {'regions': areas, 'companies': companies, 'branches': [] if branches is None else [
        {'name': str(b['name']), 'center': [float(b.latitude), float(b.longitude)]} for _, b in branches.iterrows()],
        'center': center, 'zoom': 12 if focus in stats.index else 10, 'date': f'{data.SNAPSHOT:%d/%m/%Y}', 'highlight': highlight}


def render(payload, key):
    return _map(payload=payload, key=key, default=None)
