"""Koreksi koordinat untuk tampilan peta: titik perusahaan & cabang dipindah ke kecamatan yang benar.

Centroid di tabel GEO (egi_generator.py) bergeser rata-rata ±6 km dari lokasi asli kecamatannya
(dicek terhadap batas administratif OpenStreetMap, Okt 2026). Skrip ini:
  1. memakai poligon batas kecamatan OSM (data/raw/kecamatan_boundaries.geojson) → centroid luas;
     4 kecamatan Kota Bekasi tidak ada di OSM → centroid manual (kantor camat/pusat wilayah, ±1 km);
  2. menggeser semua titik di satu kecamatan ikut centroid baru (sebaran dalam kecamatan dipertahankan);
  3. bila titik jatuh di luar poligon (atau di luar radius setara luas untuk Bekasi), jaraknya ke
     centroid diperkecil sampai masuk.

Yang berubah : data/raw/geography.csv (centroid_lat/lon), companies.csv & branches.csv (latitude/longitude).
Yang TIDAK   : fitur, model, skor NB03–NB08. dist_branch_km tetap dihitung dari geometri lama (data sintetis).
Aman dijalankan ulang (titik yang sudah di dalam kecamatan tidak berubah). Jalankan lagi setelah NB01/generator.

    uv run python src/fix_geo_coords.py              # pakai geojson yang tersimpan
    uv run python src/fix_geo_coords.py --download   # unduh ulang poligon dari Overpass API
"""
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.path import Path as MPath

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data' / 'raw'
GEOJSON = RAW / 'kecamatan_boundaries.geojson'
BBOX = (-6.40, 106.55, -6.05, 107.10)
# Kota Bekasi: tidak ada poligon kecamatan/kelurahan di OSM
MANUAL = {'L033': (-6.24000, 106.98000), 'L034': (-6.24400, 107.01700), 'L035': (-6.21000, 107.00800), 'L036': (-6.18500, 106.98000)}
KM_PER_DEG = 111.0


def _stitch(ways):
    """Gabungkan potongan way 'outer' menjadi cincin tertutup."""
    segs, rings = [list(w) for w in ways if len(w) > 1], []
    while segs:
        ring = segs.pop(0)
        while ring[0] != ring[-1]:
            for i, s in enumerate(segs):
                if s[0] == ring[-1]:
                    ring += s[1:]; break
                if s[-1] == ring[-1]:
                    ring += s[::-1][1:]; break
            else:
                break
            segs.pop(i)
        if len(ring) >= 4:
            rings.append(ring)
    return rings


def download():
    q = f'[out:json][timeout:180];(relation["boundary"="administrative"]["admin_level"="6"]{BBOX};);out geom;'
    req = urllib.request.Request('https://overpass-api.de/api/interpreter', data=urllib.parse.urlencode({'data': q}).encode(),
                                 headers={'User-Agent': 'egi-capstone-geofix/1.0'})
    d = json.load(urllib.request.urlopen(req, timeout=240))
    geo = pd.read_csv(RAW / 'geography.csv')
    feats = []
    for _, g in geo.iterrows():
        rel = [e for e in d['elements'] if e['tags'].get('name', '').lower() == g.district.lower()]
        if not rel:
            continue
        ways = [[(round(p['lon'], 5), round(p['lat'], 5)) for p in m['geometry']] for m in rel[0]['members'] if m['type'] == 'way' and m.get('role') == 'outer']
        rings = _stitch(ways)
        feats.append({'type': 'Feature', 'properties': {'location_id': g.location_id, 'district': g.district, 'osm_relation': rel[0]['id']},
                      'geometry': {'type': 'MultiPolygon', 'coordinates': [[[list(p) for p in r]] for r in rings]}})
    GEOJSON.write_text(json.dumps({'type': 'FeatureCollection', 'source': '© OpenStreetMap contributors (ODbL), Overpass API', 'features': feats}))
    print(f'{len(feats)} poligon kecamatan disimpan ke {GEOJSON.relative_to(ROOT)}')


def load_shapes():
    shapes = {}
    for f in json.loads(GEOJSON.read_text())['features']:
        rings = [np.array(poly[0]) for poly in f['geometry']['coordinates']]
        shapes[f['properties']['location_id']] = rings
    return shapes


def area_centroid(rings):
    a_tot, cx, cy = 0.0, 0.0, 0.0
    for r in rings:
        x, y = r[:, 0], r[:, 1]
        cr = x[:-1] * y[1:] - x[1:] * y[:-1]
        a = cr.sum() / 2
        if a == 0:
            continue
        a_tot += a; cx += ((x[:-1] + x[1:]) * cr).sum() / 6; cy += ((y[:-1] + y[1:]) * cr).sum() / 6
    return cy / a_tot, cx / a_tot      # lat, lon


def place(df, centers, old_centers, inside, lat='latitude', lon='longitude'):
    """Translasi ke centroid baru; titik di luar kecamatan ditarik ke centroid sampai masuk."""
    d = df.copy()
    pulled = 0
    for i, r in d.iterrows():
        l = r.location_id
        c_lat, c_lon = centers[l]
        o_lat, o_lon = r[lat] - old_centers[l][0], r[lon] - old_centers[l][1]
        k = 1.0
        pt = lambda k: (round(c_lat + o_lat * k, 5), round(c_lon + o_lon * k, 5))   # dicek setelah dibulatkan (stabil saat diulang)
        while k > 0.02 and not inside[l](*pt(k)):
            k *= 0.8
        pulled += k < 1.0
        d.at[i, lat], d.at[i, lon] = pt(k)
    return d, pulled


def main():
    if '--download' in sys.argv or not GEOJSON.exists():
        download()
    shapes = load_shapes()
    geo_s = pd.read_csv(RAW / 'geography.csv', dtype=str, keep_default_na=False)
    geo = geo_s.astype({'centroid_lat': float, 'centroid_lon': float, 'area_km2': float}).set_index('location_id')
    old_centers = {l: (geo.at[l, 'centroid_lat'], geo.at[l, 'centroid_lon']) for l in geo.index}

    centers, inside = {}, {}
    for l in geo.index:
        if l in shapes:
            centers[l] = area_centroid(shapes[l])
            paths = [MPath(r) for r in shapes[l]]
            inside[l] = lambda la, lo, ps=paths: any(p.contains_point((lo, la)) for p in ps)
        elif l in MANUAL:
            centers[l] = MANUAL[l]
            rad = 0.8 * np.sqrt(geo.at[l, 'area_km2'] / np.pi) / KM_PER_DEG     # radius lingkaran setara luas
            inside[l] = lambda la, lo, c=MANUAL[l], rr=rad: np.hypot(la - c[0], (lo - c[1]) * np.cos(np.radians(c[0]))) <= rr
        else:
            raise SystemExit(f'Tidak ada poligon/centroid untuk {l} {geo.at[l, "district"]}')
        if not inside[l](*centers[l]):
            print(f'Peringatan: centroid {geo.at[l, "district"]} di luar poligonnya')

    report = []
    for name in ('companies.csv', 'branches.csv'):
        s = pd.read_csv(RAW / name, dtype=str, keep_default_na=False)
        num = s.astype({'latitude': float, 'longitude': float})
        new, pulled = place(num, centers, old_centers, inside)
        s['latitude'] = new.latitude.map('{:.5f}'.format); s['longitude'] = new.longitude.map('{:.5f}'.format)
        s.to_csv(RAW / name, index=False)
        report.append(f'{name}: {len(s)} titik, {pulled} ditarik masuk batas kecamatan')

    geo_s['centroid_lat'] = geo_s.location_id.map(lambda l: f'{centers[l][0]:.5f}')
    geo_s['centroid_lon'] = geo_s.location_id.map(lambda l: f'{centers[l][1]:.5f}')
    geo_s.to_csv(RAW / 'geography.csv', index=False)
    print(f'{len(shapes)} kecamatan pakai poligon OSM, {len(MANUAL)} manual (Bekasi). ' + ' · '.join(report))


if __name__ == '__main__':
    main()
