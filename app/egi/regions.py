"""Dataset penetration by district, separate from account-scoped company details."""
import numpy as np
import pandas as pd
import pydeck as pdk

from . import ui, viz

NO_DATA = [190, 195, 203, 165]


def penetration_color(value):
    return NO_DATA.copy() if pd.isna(value) else viz.seq_rgb(1 - float(np.clip(value, 0, 1)))


def aggregate(store, companies):
    registry = store.cox.groupby('district').agg(kota=('city', 'first'), lat=('latitude', 'mean'),
                                                lon=('longitude', 'mean'), cabang=('district_has_branch', 'max'),
                                                jarak=('dist_branch_km', 'mean'))
    for district, rings in store.shapes.items():
        if district not in registry.index and rings:
            coords = np.asarray(rings[0])
            registry.loc[district] = ['Tidak tersedia', coords[:, 1].mean(), coords[:, 0].mean(), np.nan, np.nan]
    counts = companies.assign(prospect=companies.customer_type == 'Prospect').groupby('district').agg(
        perusahaan=('name', 'size'), nasabah=('is_client', 'sum'), prospect=('prospect', 'sum'))
    result = registry.join(counts)
    for column in ['perusahaan', 'nasabah', 'prospect']:
        result[column] = result[column].fillna(0).astype(int)
    result['penetrasi'] = result.nasabah.div(result.perusahaan.replace(0, np.nan))
    return result.sort_values(['penetrasi', 'perusahaan'], ascending=[True, False], na_position='last')


def company_selection(event, districts, companies):
    objects = event.get('selection', {}).get('objects', {})
    for obj in objects.get('perusahaan_relevan', []):
        cid = obj.get('company_id')
        if cid in companies.index:
            return companies.loc[cid, 'district'], cid
    for layer in ('penetrasi_wilayah', 'penetrasi_lingkaran'):
        for obj in objects.get(layer, []):
            district = obj.get('district')
            if district in districts.index:
                return district, None
    return None, None


def map_deck(stats, shapes, companies, branches=None, focus=None, selected_company=None):
    polygons, circles = [], []
    for district, row in stats.iterrows():
        label = (f'<b>{ui.esc(district)}</b><br>Penetrasi: {row.penetrasi:.0%}<br>'
                 f'{row.nasabah} nasabah BNI / {row.perusahaan} perusahaan dalam data') if row.perusahaan else (
                     f'<b>{ui.esc(district)}</b><br>Tidak ada data perusahaan untuk filter ini')
        item = {'district': district, 'fill': penetration_color(row.penetrasi), 'label': label}
        if shapes.get(district):
            polygons.extend({**item, 'polygon': ring} for ring in shapes[district])
        else:
            circles.append({**item, 'lon': row.lon, 'lat': row.lat})
    layers = []
    if polygons:
        layers.append(pdk.Layer('PolygonLayer', polygons, id='penetrasi_wilayah', get_polygon='polygon',
                                get_fill_color='fill', stroked=False, filled=True, pickable=True))
    if circles:
        layers.append(pdk.Layer('ScatterplotLayer', circles, id='penetrasi_lingkaran', get_position='[lon, lat]',
                                get_fill_color='fill', get_radius=900, radius_min_pixels=12, pickable=True))
    if not companies.empty:
        points = companies[['longitude', 'latitude', 'name', 'district', 'is_client']].copy()
        points['company_id'] = points.index
        points['radius'] = [180 if cid == selected_company else 75 for cid in points.index]
        points['rgb'] = [viz.MINE_RGB if client else viz.PROSPECT_RGB for client in points.is_client]
        points['label'] = [f'<b>{ui.esc(name)}</b><br>{ui.esc(district)} · ' + ('Nasabah BNI' if client else 'Prospect')
                           for name, district, client in zip(points.name, points.district, points.is_client)]
        points = points.drop(columns=['name', 'is_client']).rename(columns={'longitude': 'lon', 'latitude': 'lat'})
        layers.append(pdk.Layer('ScatterplotLayer', points, id='perusahaan_relevan', get_position='[lon, lat]',
                                get_fill_color='rgb', get_radius='radius', radius_min_pixels=3, radius_max_pixels=9,
                                stroked=True, get_line_color=[255, 255, 255, 200], line_width_min_pixels=1, pickable=True))
    if branches is not None and not branches.empty:
        layers.append(pdk.Layer('ScatterplotLayer', viz.branch_points(branches), id='dukungan_cabang', get_position='[lon, lat]',
                                get_radius=150, radius_min_pixels=5, radius_max_pixels=8, get_fill_color=[255, 255, 255],
                                stroked=True, get_line_color=[17, 24, 39], line_width_min_pixels=2, pickable=False))
    lat, lon, zoom = -6.2, 106.85, 10.2
    if focus in stats.index:
        lat, lon, zoom = stats.loc[focus, 'lat'], stats.loc[focus, 'lon'], 12
    return viz._CompactDeck(layers=layers, initial_view_state=pdk.ViewState(latitude=lat, longitude=lon, zoom=zoom),
                            map_provider='carto', map_style='light', tooltip={'html': '{label}',
                            'style': {'backgroundColor': ui.NAVY, 'color': 'white', 'fontSize': '12px'}})
