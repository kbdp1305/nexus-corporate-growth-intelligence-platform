"""BNI EGI — generator data sintetis v8 (diekstrak dari 01_Dataset_Generation_and_Validation.ipynb).
Pakai (dari akar proyek): python src/egi_generator.py --seed 2026            → data/raw/
                         python src/egi_generator.py --out folder_lain"""
import json, os, re, time, warnings
import numpy as np
import pandas as pd
warnings.filterwarnings('ignore')

CFG = dict(
    n_core=2000, n_credit=1000, n_noncredit=400,             # 2.000 perusahaan inti: 1.000 nasabah kredit, 400 nasabah non-kredit, 600 prospect
    n_ent_l1=3000, n_ent_l2=1800,                            # mitra bisnis di luar perusahaan inti (lapis 1 & 2)
    months=pd.period_range('2024-01', '2026-06', freq='M'),  # 30 bulan data fitur; cutoff 30 Jun 2026
    outcome_window=('2026-07', '2026-09'),                   # hasil yang diprediksi — terjadi SETELAH cutoff
    risk_quantiles=(0.57, 0.82),                             # ambang Low | Medium | High pada kondisi normal
    sigma_unobserved=0.25,                                   # faktor risiko yang tidak terekam data (batas akurasi alami)
    label_error_rate=0.04,                                   # kesalahan rating oleh analis (dicatat di ground truth)
    health_shift=0.0,                                        # < 0 = krisis, > 0 = ekonomi membaik (uji kondisi ekstrem)
    group_frac=0.08,                                         # porsi perusahaan inti yang tergabung dalam grup usaha
    gravity_km=8.0,                                          # skala jarak: mitra dagang cenderung berdekatan
    gravity_floor=0.03,                                      # peluang dasar bermitra jauh
    city_boost=3.0,                                          # pengali bila mitra satu kota/kabupaten (klaster industri)
    new_edge_rate=0.07,                                      # porsi relasi dagang yang baru dimulai dalam periode data
    n_actions_deepening=1500, n_actions_acq=500, max_visit_notes=450,
    dq=dict(dup_tx=0.003, zero_tx=0.0001, nan_channel=0.005, nan_cp=0.01, nan_ebit=0.012),   # masalah kualitas data yang disengaja
)
SEED = 2026
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT = PROJECT_ROOT / 'data' / 'raw'
CUTOFF = '2026-06-30'


class World(dict):
    """Wadah semua variabel dunia sintetis; tiap tahap membaca input & menulis output ke sini."""
    __getattr__ = dict.__getitem__
    def put(self, **kw): self.update(kw)
    def get_(self, names): return [self[n] for n in names.split()]

WHITE_SPACE = ['L017', 'L018', 'L027', 'L028', 'L036', 'L040']   # kecamatan industri padat, penetrasi BNI rendah, tanpa cabang

GEO = [('L001', 'DKI Jakarta', 'Jakarta Pusat', 'Gambir', -6.19983, 106.83722, 21.9, 2), ('L002', 'DKI Jakarta', 'Jakarta Pusat', 'Tanah Abang', -6.18669, 106.82322, 38.9, 4), ('L003', 'DKI Jakarta', 'Jakarta Pusat', 'Menteng', -6.16629, 106.82609, 13.7, 1), ('L004', 'DKI Jakarta', 'Jakarta Pusat', 'Senen', -6.16395, 106.88474, 12.6, 1), ('L005', 'DKI Jakarta', 'Jakarta Pusat', 'Kemayoran', -6.20924, 106.87054, 17.7, 2), ('L006', 'DKI Jakarta', 'Jakarta Pusat', 'Sawah Besar', -6.16734, 106.8563, 14.9, 1), ('L007', 'DKI Jakarta', 'Jakarta Selatan', 'Kebayoran Baru', -6.25515, 106.83159, 30.9, 2), ('L008', 'DKI Jakarta', 'Jakarta Selatan', 'Setiabudi', -6.24932, 106.79009, 25.6, 0), ('L009', 'DKI Jakarta', 'Jakarta Selatan', 'Tebet', -6.27726, 106.81851, 17.1, 2), ('L010', 'DKI Jakarta', 'Jakarta Selatan', 'Cilandak', -6.29421, 106.76707, 16.7, 5), ('L011', 'DKI Jakarta', 'Jakarta Selatan', 'Pasar Minggu', -6.21364, 106.79251, 16.1, 1), ('L012', 'DKI Jakarta', 'Jakarta Selatan', 'Mampang Prapatan', -6.27443, 106.85582, 22.7, 3), ('L013', 'DKI Jakarta', 'Jakarta Selatan', 'Pancoran', -6.30085, 106.79008, 27.7, 2), ('L014', 'DKI Jakarta', 'Jakarta Selatan', 'Kebayoran Lama', -6.30204, 106.81352, 26.9, 1), ('L015', 'DKI Jakarta', 'Jakarta Utara', 'Penjaringan', -6.15617, 106.82128, 27.4, 4), ('L016', 'DKI Jakarta', 'Jakarta Utara', 'Tanjung Priok', -6.1013, 106.85594, 13.9, 5), ('L017', 'DKI Jakarta', 'Jakarta Utara', 'Koja', -6.11848, 106.91356, 22.1, 10), ('L018', 'DKI Jakarta', 'Jakarta Utara', 'Cilincing', -6.07734, 106.9054, 38.8, 3), ('L019', 'DKI Jakarta', 'Jakarta Utara', 'Kelapa Gading', -6.12457, 106.85153, 25.9, 6), ('L020', 'DKI Jakarta', 'Jakarta Utara', 'Pademangan', -6.16566, 106.8664, 18.4, 3), ('L021', 'DKI Jakarta', 'Jakarta Barat', 'Grogol Petamburan', -6.19355, 106.82991, 25.3, 0), ('L022', 'DKI Jakarta', 'Jakarta Barat', 'Kebon Jeruk', -6.13512, 106.76064, 33.6, 4), ('L023', 'DKI Jakarta', 'Jakarta Barat', 'Cengkareng', -6.16892, 106.80768, 8.7, 1), ('L024', 'DKI Jakarta', 'Jakarta Barat', 'Kalideres', -6.14225, 106.77266, 27.8, 2), ('L025', 'DKI Jakarta', 'Jakarta Barat', 'Tambora', -6.14166, 106.76672, 28.2, 2), ('L026', 'DKI Jakarta', 'Jakarta Barat', 'Palmerah', -6.20648, 106.76112, 35.9, 2), ('L027', 'DKI Jakarta', 'Jakarta Timur', 'Cakung', -6.2291, 106.90473, 37.3, 10), ('L028', 'DKI Jakarta', 'Jakarta Timur', 'Pulo Gadung', -6.24653, 106.88142, 25.4, 9), ('L029', 'DKI Jakarta', 'Jakarta Timur', 'Jatinegara', -6.23535, 106.94869, 8.6, 7), ('L030', 'DKI Jakarta', 'Jakarta Timur', 'Duren Sawit', -6.25806, 106.86639, 39.6, 5), ('L031', 'DKI Jakarta', 'Jakarta Timur', 'Kramat Jati', -6.22984, 106.90519, 7.6, 3), ('L032', 'DKI Jakarta', 'Jakarta Timur', 'Pasar Rebo', -6.27414, 106.84512, 20.0, 9), ('L033', 'Jawa Barat', 'Kota Bekasi', 'Bekasi Barat', -6.25241, 106.98266, 20.6, 5), ('L034', 'Jawa Barat', 'Kota Bekasi', 'Bekasi Timur', -6.23569, 106.99172, 16.9, 3), ('L035', 'Jawa Barat', 'Kota Bekasi', 'Bekasi Utara', -6.21761, 106.98639, 36.1, 3), ('L036', 'Jawa Barat', 'Kota Bekasi', 'Medan Satria', -6.21289, 107.03807, 19.0, 10), ('L037', 'Banten', 'Kota Tangerang', 'Tangerang', -6.17782, 106.65617, 21.8, 8), ('L038', 'Banten', 'Kota Tangerang', 'Karawaci', -6.16857, 106.64139, 30.8, 3), ('L039', 'Banten', 'Kota Tangerang', 'Cipondoh', -6.25251, 106.61809, 23.5, 8), ('L040', 'Banten', 'Kota Tangerang', 'Batuceper', -6.16094, 106.65712, 22.5, 5)]

# industri: (nama, kbli, bobot, efek risiko, p impor, amplitudo Lebaran, modal kerja, capex, ritel/VA, preferensi kawasan industri)
IND = [('Perdagangan besar', 46, 185, 0.05, 0.40, 0.30, 1, 0, 1, 0.3), ('Industri makanan & minuman', 10, 126, -0.05, 0.30, 0.40, 1, 1, 1, 1.0),
       ('Konstruksi gedung', 41, 121, 0.45, 0.15, 0.08, 1, 1, 0, 0.3), ('Perdagangan eceran', 47, 107, 0.15, 0.10, 0.45, 1, 0, 1, 0.0),
       ('Industri tekstil & pakaian', 13, 89, 0.35, 0.45, 0.35, 1, 1, 0, 1.0), ('Angkutan & logistik', 49, 86, 0.20, 0.10, 0.20, 0, 1, 0, 0.7),
       ('Aktivitas kesehatan', 86, 78, -0.30, 0.10, 0.05, 0, 1, 1, 0.0), ('Teknologi informasi', 62, 75, -0.10, 0.05, 0.05, 0, 0, 1, 0.0),
       ('Industri kimia', 20, 71, 0.10, 0.50, 0.10, 1, 1, 0, 1.0), ('Real estat', 68, 62, 0.40, 0.02, 0.05, 0, 1, 1, 0.0)]
INDF = pd.DataFrame(IND, columns=['industry', 'kbli', 'w', 'risk', 'p_import', 'season', 'wc', 'capex', 'va', 'ind_pref']).set_index('industry')
# Level rasio STRUKTURAL per industri (bukan sinyal risiko) → rasio mentah menyesatkan, rasio relatif-peer lebih informatif
IND_LEVEL = {  # (offset log DER, offset log CR, offset margin EBIT)
    # sengaja TIDAK sejalan dengan efek risiko industri: RS & logistik padat aset (DER tinggi) tapi risikonya rendah-sedang;
    # tekstil & eceran DER rendah tapi risikonya tinggi → rasio mentah menyesatkan, rasio relatif-peer tidak
    'Real estat': (0.55, 0.10, 0.06), 'Konstruksi gedung': (0.05, -0.20, -0.02), 'Perdagangan besar': (0.15, 0.05, -0.04), 'Perdagangan eceran': (-0.35, -0.30, -0.04),
    'Industri tekstil & pakaian': (-0.40, 0.15, -0.01), 'Angkutan & logistik': (0.60, -0.15, 0.01), 'Industri kimia': (0.30, 0.15, 0.02),
    'Industri makanan & minuman': (0.00, 0.00, 0.01), 'Aktivitas kesehatan': (0.65, -0.10, 0.05), 'Teknologi informasi': (-0.55, 0.40, 0.06)}
SIZE_LEVEL = {'Kecil': (-0.20, -0.12, -0.01), 'Menengah': (0.0, 0.0, 0.0), 'Besar': (0.30, 0.10, 0.01)}   # perusahaan besar lebih leverage (akses kredit)
# Profil musiman per industri (tambahan di luar Lebaran): bulan → efek
IND_MONTH = {'Konstruksi gedung': {12: 0.30, 1: -0.14, 2: -0.10}, 'Teknologi informasi': {12: 0.20, 1: -0.08}, 'Real estat': {12: 0.12, 6: 0.06},
             'Perdagangan eceran': {12: 0.12, 1: -0.06}, 'Industri makanan & minuman': {12: 0.08}, 'Aktivitas kesehatan': {}, 'Angkutan & logistik': {12: 0.10, 1: -0.05}}
LEBARAN = {'2024-03': 0.45, '2024-04': 0.75, '2025-03': 0.85, '2025-04': 0.35, '2026-02': 0.25, '2026-03': 1.0}   # Idulfitri 10 Apr 2024, 31 Mar 2025, 20 Mar 2026
SIZES = ['Kecil', 'Menengah', 'Besar']
REV_MED = {'Kecil': 8.0, 'Menengah': 32.0, 'Besar': 160.0}          # omzet median (Rp miliar)
EMP_PER_BN = {'Kecil': 4.5, 'Menengah': 3.0, 'Besar': 1.8}
PRODUCTS = [('P01', 'Giro', 'Funding'), ('P02', 'Deposito', 'Funding'), ('P03', 'Virtual Account', 'Transactional'), ('P04', 'Cash Management', 'Transactional'),
            ('P05', 'Payroll', 'Transactional'), ('P06', 'Kredit Modal Kerja', 'Lending'), ('P07', 'Kredit Investasi', 'Lending'), ('P08', 'Trade Finance', 'Trade')]
PIDS = [p[0] for p in PRODUCTS]
W1 = ['Maju', 'Sinar', 'Karya', 'Cahaya', 'Mega', 'Prima', 'Graha', 'Mitra', 'Surya', 'Bumi', 'Indo', 'Global', 'Bintang', 'Sentosa', 'Agung', 'Bahtera', 'Cipta', 'Dharma']
W2 = ['Sejahtera', 'Nusantara', 'Utama', 'Lestari', 'Gemilang', 'Mandiri', 'Perkasa', 'Abadi', 'Jaya', 'Kencana', 'Makmur', 'Santosa', 'Pratama', 'Raya']
W3 = ['Group', 'Indah', 'Sentral', 'Bersama', 'Persada', 'Investama', 'Industri', 'Niaga', 'Logistik', 'Teknik', 'Solusi', 'Internasional']
sig = lambda x: 1 / (1 + np.exp(-x))


def make_names(rng, n, prefix_pool=('PT', 'PT', 'PT', 'CV'), used=None):
    used = set() if used is None else used; out = []
    while len(out) < n:
        nm = f"{rng.choice(prefix_pool)} {rng.choice(W1)} {rng.choice(W2)} {rng.choice(W3)}"
        if rng.random() < 0.35: nm += f" {rng.choice(W2)}"
        if nm not in used: used.add(nm); out.append(nm)
    return out, used

# Rantai nilai antarindustri: VALUE_CHAIN[pemasok][pembeli] = kekuatan aliran dagang (0,05 bila tidak disebut).
VALUE_CHAIN = {
    'Industri kimia': {'Industri tekstil & pakaian': 3, 'Industri makanan & minuman': 2, 'Konstruksi gedung': 2, 'Aktivitas kesehatan': 2, 'Perdagangan besar': 2, 'Industri kimia': 1},
    'Industri tekstil & pakaian': {'Perdagangan besar': 3, 'Perdagangan eceran': 3, 'Industri tekstil & pakaian': 1, 'Aktivitas kesehatan': 0.5},
    'Industri makanan & minuman': {'Perdagangan besar': 3, 'Perdagangan eceran': 3, 'Aktivitas kesehatan': 0.5, 'Industri makanan & minuman': 0.5, 'Angkutan & logistik': 0.3},
    'Perdagangan besar': {'Perdagangan eceran': 3, 'Industri makanan & minuman': 1.5, 'Konstruksi gedung': 1.5, 'Aktivitas kesehatan': 1, 'Perdagangan besar': 1,
                          'Real estat': 0.5, 'Industri tekstil & pakaian': 0.5},
    'Konstruksi gedung': {'Real estat': 4, 'Aktivitas kesehatan': 1, 'Perdagangan besar': 0.5, 'Angkutan & logistik': 0.5, 'Industri kimia': 0.5, 'Industri makanan & minuman': 0.5},
    'Angkutan & logistik': {'Perdagangan besar': 2, 'Industri makanan & minuman': 2, 'Perdagangan eceran': 1.5, 'Industri kimia': 1, 'Industri tekstil & pakaian': 1,
                            'Konstruksi gedung': 1, 'Aktivitas kesehatan': 0.5},
    'Teknologi informasi': {'Perdagangan besar': 1, 'Aktivitas kesehatan': 1.5, 'Real estat': 1, 'Perdagangan eceran': 1, 'Angkutan & logistik': 1,
                            'Industri makanan & minuman': 0.5, 'Industri kimia': 0.5},
    'Aktivitas kesehatan': {'Aktivitas kesehatan': 1, 'Perdagangan eceran': 0.5, 'Teknologi informasi': 0.3},
    'Perdagangan eceran': {'Industri makanan & minuman': 0.5, 'Aktivitas kesehatan': 0.5, 'Perdagangan eceran': 0.3},
    'Real estat': {'Perdagangan eceran': 1.5, 'Aktivitas kesehatan': 1, 'Industri makanan & minuman': 0.5, 'Teknologi informasi': 0.5, 'Perdagangan besar': 0.5}}
VC = pd.DataFrame(0.05, index=INDF.index, columns=INDF.index)
for s_, row in VALUE_CHAIN.items():
    for b_, v_ in row.items(): VC.loc[s_, b_] = v_
B2C = {'Perdagangan eceran', 'Aktivitas kesehatan'}          # penjualan utama ke konsumen akhir → sedikit pembeli korporat


def haversine_km(lat1, lon1, lat2, lon2):
    p = np.pi / 180; a = np.sin((lat2 - lat1) * p / 2) ** 2 + np.cos(lat1 * p) * np.cos(lat2 * p) * np.sin((lon2 - lon1) * p / 2) ** 2
    return 12742 * np.arcsin(np.sqrt(a))

def s01_profile(w):
    cfg, rng = w.cfg, w.rng
    N = cfg['n_core']; M = cfg['months']; nm_ = len(M)
    geo = pd.DataFrame(GEO, columns=['location_id', 'province', 'city', 'district', 'centroid_lat', 'centroid_lon', 'area_km2', 'poi_industrial_count'])
    ind = rng.choice(INDF.index, N, p=(INDF.w / INDF.w.sum()).values)
    size = np.array([rng.choice(SIZES, p=[.40, .43, .17]) for _ in range(N)])
    est = np.clip(np.round(2026 - rng.gamma(2.2, 7.5, N)), 1985, 2023).astype(int)
    loc_w = np.array([[(1 + g.poi_industrial_count) ** (2 * INDF.at[i, 'ind_pref']) * g.area_km2 for g in geo.itertuples()] for i in INDF.index])
    loc_w = loc_w / loc_w.sum(1, keepdims=True); ind_ix = {k: j for j, k in enumerate(INDF.index)}
    loc = np.array([geo.location_id[rng.choice(len(geo), p=loc_w[ind_ix[i]])] for i in ind])
    ids = [f'C{i + 1:04d}' for i in range(N)]
    names, used = make_names(rng, N)
    size_lvl = pd.Series(size).map({'Kecil': 0, 'Menengah': 1, 'Besar': 2}).values
    # grup usaha: anggota dari perusahaan Menengah/Besar, 2–5 anggota per grup
    group = np.full(N, None, dtype=object); pool_ = list(rng.permutation(np.where(size != 'Kecil')[0]))
    for k in range(int(round(N * cfg['group_frac'] / 3.5))):
        for i in [pool_.pop() for _ in range(int(rng.integers(2, 6)))]: group[i] = f'GRP-{k + 1:03d}'
    w.put(N=N, M=M, nm_=nm_, geo=geo, G=geo.set_index('location_id'), ind=ind, size=size, est=est, loc=loc, loc_w=loc_w, ind_ix=ind_ix,
          ids=ids, names=names, used=used, size_lvl=size_lvl, age=2026 - est, group=group, in_group=np.array([g_ is not None for g_ in group]),
          ix_of=lambda s_: list(M).index(pd.Period(s_, 'M')))

def s02_latent(w):
    rng, N, ind, size_lvl, age, group, in_group, cfg = w.get_('rng N ind size_lvl age group in_group cfg')
    z_grp = {g_: rng.normal() for g_ in sorted({x for x in group if x})}
    grp_eff = np.array([z_grp[g_] if g_ else 0.0 for g_ in group])
    h = (rng.normal(0, 1, N) * np.where(in_group, 0.85, 1.0) + 0.55 * grp_eff - 0.5 * INDF.loc[ind, 'risk'].values + 0.15 * (size_lvl - 1)
         + 0.15 * np.tanh((age - 12) / 10) + cfg['health_shift'])
    g = rng.normal(0.06, 0.11, N) + 0.035 * h + 0.03 * cfg['health_shift']
    legal = rng.random(N) < 0.015 + 0.02 * (h < -1)
    has_import = rng.random(N) < INDF.loc[ind, 'p_import'].values
    w.put(h=h, g=g, legal=legal, has_import=has_import, grp_eff=grp_eff)

def s03_network(w):
    rng, cfg, N, ids, ind, size, loc, geo, G, loc_w, ind_ix, used, group, ix_of, est = w.get_('rng cfg N ids ind size loc geo G loc_w ind_ix used group ix_of est')
    nL1, nL2 = cfg['n_ent_l1'], cfg['n_ent_l2']; nE = nL1 + nL2
    e_ids = [f'E{i + 1:05d}' for i in range(nE)]; e_names, used = make_names(rng, nE, ('PT', 'CV', 'CV', 'UD'), used)
    e_ind = rng.choice(INDF.index, nE, p=(INDF.w / INDF.w.sum()).values); e_size = rng.choice(SIZES, nE, p=[.62, .33, .05])
    e_loc = np.array([geo.location_id[rng.choice(len(geo), p=loc_w[ind_ix[i]])] for i in e_ind])
    e_bni = rng.random(nE) < np.r_[np.full(nL1, .30), np.full(nL2, .25)]
    entities = pd.DataFrame(dict(entity_id=e_ids, entity_name=[n + ' (dummy)' for n in e_names], industry=e_ind, size_class_reference=e_size,
                                 city=G.loc[e_loc, 'city'].values, location_id=e_loc, layer=np.r_[np.ones(nL1, int), np.full(nL2, 2)], is_bni_customer=e_bni))
    # kandidat mitra = perusahaan inti + entitas lapis 1
    pool_ids = np.array(ids + e_ids[:nL1]); P = len(pool_ids)
    pool_size = np.r_[size, e_size[:nL1]]
    attract = np.where(pool_size == 'Besar', 25.0, np.where(pool_size == 'Menengah', 3.0, 1.0)) * np.exp(rng.normal(0, .8, P))
    attract[N:] *= 0.5
    pi = np.array([ind_ix[x] for x in np.r_[ind, e_ind[:nL1]]])
    loc_ix = {l: k for k, l in enumerate(geo.location_id)}; pl = np.array([loc_ix[x] for x in np.r_[loc, e_loc[:nL1]]])
    la, lo = geo.centroid_lat.values, geo.centroid_lon.values
    D = haversine_km(la[:, None], lo[:, None], la[None, :], lo[None, :]); grav = cfg['gravity_floor'] + np.exp(-D / cfg['gravity_km'])
    grav = grav * np.where(np.asarray(geo.city, dtype=object)[:, None] == np.asarray(geo.city, dtype=object)[None, :], cfg['city_boost'], 1.0)
    VCm = VC.values; grp_pool = np.r_[group, np.full(nL1, None, dtype=object)]
    rel_rows = []
    for i in range(N):
        b2c = ind[i] in B2C
        nb = int(rng.integers(1, 4)) if b2c else int(rng.integers(2, 8)); ns = int(rng.integers(2, 7))
        base = attract * grav[pl[i], pl]; base[i] = 0.0
        if group[i] is not None: base = base * np.where(grp_pool == group[i], 6.0, 1.0)
        conc = rng.uniform(0.4, 1.6)                                    # makin kecil → makin bergantung pada 1 pembeli
        for rtype, k in [('Customer', nb), ('Supplier', ns)]:
            wgt = base * (VCm[pi[i], pi] if rtype == 'Customer' else VCm[pi, pi[i]])
            cand = rng.choice(P, k, replace=False, p=wgt / wgt.sum())
            scale = rng.uniform(.15, .40) if (b2c and rtype == 'Customer') else rng.uniform(.55, .90)
            share = rng.dirichlet(np.full(k, conc if rtype == 'Customer' else 0.9)) * scale
            for c, sh in zip(cand, share):
                t = 'Distributor' if rtype == 'Customer' and rng.random() < 0.3 else rtype
                rel_rows.append((ids[i], pool_ids[c], t, sh, 1))
    # grup usaha: anggota → induk (perusahaan terbesar di grup)
    for g_ in sorted({x for x in group if x}):
        mem = np.where(group == g_)[0]; head = mem[np.argmax(w.size_lvl[mem] * 10 + rng.random(len(mem)))]
        rel_rows += [(ids[m], ids[head], 'Subsidiary', 0.0, 1) for m in mem if m != head]
    # lapis 2: pemasok dari mitra lapis 1 (mengikuti rantai nilai)
    e2_ix = np.array([ind_ix[x] for x in e_ind[nL1:]])
    for j_ in range(nL1):
        if rng.random() < 0.6:
            wg = VCm[e2_ix, ind_ix[e_ind[j_]]]
            for c in rng.choice(nL2, int(rng.integers(1, 4)), replace=False, p=wg / wg.sum()):
                rel_rows.append((e_ids[j_], e_ids[nL1 + c], 'Supplier', rng.uniform(.05, .5), 2))
    rel = pd.DataFrame(rel_rows, columns=['source_id', 'target_id', 'relationship_type', 'dependency_share', 'layer_from_core'])
    rel = rel.drop_duplicates(['source_id', 'target_id', 'relationship_type']).reset_index(drop=True)
    rel['dependency_share'] = rel.dependency_share.round(3)
    # tanggal mulai relasi: sebagian besar historis; sebagian kecil baru di periode data (start_ix = indeks bulan)
    trade = rel.relationship_type.isin(['Customer', 'Distributor', 'Supplier']) & rel.layer_from_core.eq(1)
    new = trade & (rng.random(len(rel)) < cfg['new_edge_rate'])
    rel['start_ix'] = -1; rel.loc[new, 'start_ix'] = rng.integers(ix_of('2024-04'), ix_of('2026-03') + 1, new.sum())
    est_of = dict(zip(ids, est))
    lo_y = np.array([max(2008, est_of.get(s_, 2000) + 1) for s_ in rel.source_id])
    yr = np.minimum(lo_y + (rng.random(len(rel)) * (2024 - lo_y)).astype(int), 2023)
    hist = pd.to_datetime(pd.DataFrame(dict(year=yr, month=rng.integers(1, 13, len(rel)), day=rng.integers(1, 29, len(rel)))))
    newd = pd.to_datetime([str(w.M[k]) + f'-{int(d):02d}' if k >= 0 else '2000-01-01' for k, d in zip(rel.start_ix, rng.integers(1, 29, len(rel)))])
    rel['relationship_start'] = np.where(rel.start_ix >= 0, newd.strftime('%Y-%m-%d'), hist.dt.strftime('%Y-%m-%d'))
    buyers = rel[rel.relationship_type.isin(['Customer', 'Distributor']) & rel.source_id.str.startswith('C')]
    top_buyer = buyers.sort_values('dependency_share', ascending=False).drop_duplicates('source_id').set_index('source_id')
    top_share = np.array([top_buyer.dependency_share.get(c, 0.0) for c in ids])
    # anchor = pembeli besar: perusahaan inti yang paling banyak dijadikan pembeli oleh perusahaan lain
    buy_in = buyers.target_id.value_counts()
    anchors = [c for c in buy_in.index if c.startswith('C')][:12]
    w.put(entities=entities, e_ids=e_ids, e_names=e_names, e_bni=e_bni, nL1=nL1, used=used, rel=rel, buyers=buyers, top_buyer=top_buyer,
          top_share=top_share, anchors=anchors)

def s04_events(w):
    rng, N, M, nm_, ids, h, g, size_lvl, ix_of, top_share, top_buyer, anchors, buyers, rel = w.get_(
        'rng N M nm_ ids h g size_lvl ix_of top_share top_buyer anchors buyers rel')
    sig_ = sig
    p_dis = 0.03 + 0.12 * sig_(-1.6 * h - 1.0); p_exp = 0.08 + 0.14 * sig_(5 * g)
    u_ = rng.random(N); regime = np.where(u_ < p_dis, 'distress', np.where(u_ < p_dis + p_exp, 'expansion', 'normal'))
    mag = np.where(regime == 'expansion', rng.choice([0.15, 0.30, 0.60], N, p=[.4, .4, .2]), np.where(regime == 'distress', rng.choice([0.12, 0.22, 0.35], N, p=[.4, .4, .2]), 0.0))
    start_ix = rng.integers(ix_of('2024-10'), nm_ - 1, N)
    anchor_ix = np.array([ids.index(a) for a in anchors[:12]])
    big = anchor_ix[:6]                                                                  # 6 pembeli terbesar
    distressed_anchors = big[np.argsort(h[big])[:2]]                                    # 2 yang paling lemah mengalami distress
    regime[anchor_ix[regime[anchor_ix] == 'distress']] = 'normal'                       # anchor lain stabil
    regime[distressed_anchors] = 'distress'; mag[distressed_anchors] = 0.45; start_ix[distressed_anchors] = ix_of('2025-07')
    recover = (regime == 'distress') & (rng.random(N) < 0.25); recover[distressed_anchors] = False
    spike = rng.random(N) < 0.10; spike_ix = rng.integers(3, nm_, N); spike_mult = rng.choice([2.5, 4.0, 7.0], N, p=[.4, .4, .2])
    top_new = np.array([top_buyer.start_ix.get(c, -1) >= 0 for c in ids])            # pembeli utama yang relasinya baru → tidak bisa "keluar"
    exit_cand = (top_share >= 0.22) & ~np.isin(np.arange(N), anchor_ix) & ~top_new
    buyer_exit = exit_cand & (rng.random(N) < 0.07) & (regime != 'distress'); exit_ix = rng.integers(ix_of('2025-03'), nm_ - 1, N)
    erosion = (regime == 'normal') & ~buyer_exit & ~np.isin(np.arange(N), anchor_ix) & (rng.random(N) < 0.09); erosion_ix = rng.integers(ix_of('2025-01'), ix_of('2026-03'), N)
    da_ids = {ids[k] for k in distressed_anchors}
    sup_to = buyers[buyers.target_id.isin(da_ids)].groupby('source_id').dependency_share.sum()
    contagion = np.array([sup_to.get(c, 0.0) for c in ids]); contagion[distressed_anchors] = 0
    cont_ix = ix_of('2025-07') + 2
    m2025 = np.array([p.year == 2025 for p in M])
    frac_2025 = lambda ix: np.array([m2025[k:].sum() / 12 if k < nm_ else 0 for k in ix])
    exp_eff = np.where(regime == 'expansion', mag * frac_2025(start_ix), 0)
    dis_eff = np.where(regime == 'distress', mag * frac_2025(start_ix), 0) + np.minimum(0.5, 0.7 * contagion) * m2025[cont_ix:].sum() / 12
    w.put(regime=regime, mag=mag, start_ix=start_ix, anchor_ix=anchor_ix, distressed_anchors=distressed_anchors, recover=recover, spike=spike,
          spike_ix=spike_ix, spike_mult=spike_mult, buyer_exit=buyer_exit, exit_ix=exit_ix, erosion=erosion, erosion_ix=erosion_ix, da_ids=da_ids,
          contagion=contagion, cont_ix=cont_ix, exp_eff=exp_eff, dis_eff=dis_eff)

def s05_financials(w):
    rng, N, ind, size, h, g, exp_eff, dis_eff = w.get_('rng N ind size h g exp_eff dis_eff')
    lv = np.array([IND_LEVEL[x] for x in ind]) + np.array([SIZE_LEVEL[s_] for s_ in size])
    rev24 = np.array([REV_MED[s_] for s_ in size]) * np.exp(rng.normal(0, 0.55, N) + 0.12 * h)
    rev25 = rev24 * (1 + g + 0.6 * exp_eff - 0.8 * dis_eff + rng.normal(0, 0.04, N))
    fin_rows = []
    for yr, rev, shock in [(2024, rev24, 0 * h), (2025, rev25, dis_eff)]:
        assets = rev / np.exp(rng.normal(0.05, 0.30, N) - 0.4 * lv[:, 0])
        der = np.exp(0.15 + lv[:, 0] - 0.50 * h + 1.3 * shock + rng.normal(0, 0.30, N))
        debt = assets * der / (1 + der); equity = assets - debt
        cr = np.exp(0.30 + lv[:, 1] + 0.26 * h - 0.9 * shock + rng.normal(0, 0.18, N))
        ca = assets * np.clip(rng.beta(4, 4, N) + 0.05, 0.1, 0.92)
        cl = np.minimum(ca / cr, debt * 0.97)
        ebit_m = np.clip(0.085 + lv[:, 2] + 0.038 * h - 0.25 * shock + rng.normal(0, 0.028, N), -0.15, 0.40)
        ebit = rev * ebit_m; interest = debt * rng.uniform(0.085, 0.13, N)
        net = np.where(ebit - interest > 0, (ebit - interest) * 0.78, ebit - interest)
        fin_rows.append(pd.DataFrame(dict(fiscal_year=yr, revenue_idr_bn=rev, total_assets_idr_bn=assets, total_equity_idr_bn=equity, total_debt_idr_bn=debt,
                                          current_assets_idr_bn=ca, current_liabilities_idr_bn=cl, ebit_idr_bn=ebit, interest_expense_idr_bn=interest, net_profit_idr_bn=net)))
    w.put(rev24=rev24, rev25=rev25, fin_rows=fin_rows)

def s06_clients_needs(w):
    rng, cfg, N, loc, size, size_lvl, age, h, g, ind, rev25, fin_rows, regime, has_import = w.get_(
        'rng cfg N loc size size_lvl age h g ind rev25 fin_rows regime has_import')
    ws = np.isin(loc, WHITE_SPACE)
    client_score = 0.8 * size_lvl + 0.03 * np.minimum(age, 25) - 1.2 * ws + 0.2 * h + rng.normal(0, 0.8, N)
    order = np.argsort(-client_score); n_cli = cfg['n_credit'] + cfg['n_noncredit']
    is_client = np.zeros(N, bool); is_client[order[:n_cli]] = True
    emp = np.maximum(5, np.round(rev25 * pd.Series(size).map(EMP_PER_BN).values * np.exp(rng.normal(0, 0.3, N)))).astype(int)
    npm25 = fin_rows[1].net_profit_idr_bn.values / fin_rows[1].revenue_idr_bn.values
    logit = np.c_[
        np.full(N, 3.0),
        -1.1 + 1.4 * (npm25 > 0.06) + 0.35 * size_lvl,
        -1.3 + 1.6 * INDF.loc[ind, 'va'].values + 0.35 * size_lvl,
        -2.0 + 0.95 * size_lvl + 0.6 * (regime == 'expansion'),
        -2.3 + 0.75 * np.log1p(emp / 25),
        -0.9 + 1.0 * INDF.loc[ind, 'wc'].values + 1.1 * (regime == 'expansion') + 0.6 * (g > 0.08) + 0.6 * (regime == 'distress'),
        -2.0 + 1.0 * INDF.loc[ind, 'capex'].values + 1.3 * (regime == 'expansion') + 0.3 * size_lvl,
        np.where(has_import, 2.2, -3.2)]
    need = (rng.random((N, 8)) < sig(logit)).astype(int); need[:, 0] = 1
    credit_score = need[:, 5] + need[:, 6] + 0.10 * h + rng.normal(0, 0.6, N)
    cli_idx = np.where(is_client)[0]; cr_order = cli_idx[np.argsort(-credit_score[cli_idx])]
    is_credit = np.zeros(N, bool); is_credit[cr_order[:cfg['n_credit']]] = True
    ctype = np.where(is_credit, 'Existing credit client', np.where(is_client, 'Existing non-credit client', 'Prospect'))
    no_cr = is_credit & (need[:, 5] + need[:, 6] == 0); need[no_cr, 5] = 1
    wallet = np.where(is_client, np.clip(rng.beta(2.2, 2.5, N) + 0.05, 0.05, 0.95), 0.0)
    w.put(is_client=is_client, cli_idx=cli_idx, emp=emp, npm25=npm25, need=need, is_credit=is_credit, ctype=ctype, wallet=wallet)

def s07_risk(w):
    rng, cfg, N, h, ind, size, age, regime, mag, legal, top_share, contagion, is_credit = w.get_(
        'rng cfg N h ind size age regime mag legal top_share contagion is_credit')
    s_det = (-1.0 * h + 0.6 * INDF.loc[ind, 'risk'].values + 0.30 * (size == 'Kecil') - 0.15 * (size == 'Besar') + 0.25 * (age < 5)
             + 2.8 * np.where(regime == 'distress', mag, 0) + 0.6 * legal + 2.6 * np.maximum(0, top_share - 0.30) + 1.6 * contagion)
    u = rng.normal(0, cfg['sigma_unobserved'], N); s_real = s_det + u
    q1, q2 = np.quantile(s_real + cfg['health_shift'], cfg['risk_quantiles'])
    cls = lambda s: np.where(s >= q2, 'High', np.where(s >= q1, 'Medium', 'Low'))
    true_cls = cls(s_real)
    flip = is_credit & (rng.random(N) < cfg['label_error_rate'])
    adj = {'Low': ['Medium'], 'Medium': ['Low', 'High'], 'High': ['Medium']}
    obs_cls = true_cls.copy(); obs_cls[flip] = [rng.choice(adj[c]) for c in true_cls[flip]]
    w.put(s_det=s_det, u=u, s_real=s_real, true_cls=true_cls, obs_cls=obs_cls, flip=flip, oracle_cls=cls(s_det))

def s08_companies(w):
    rng, cfg, N, h, size, size_lvl, is_client, is_credit, cli_idx, est, loc, G, ids, names, ind, ctype, emp, has_import, group, fin_rows = w.get_(
        'rng cfg N h size size_lvl is_client is_credit cli_idx est loc G ids names ind ctype emp has_import group fin_rows')
    p_miss = sig(-3.4 - 0.8 * h + 0.8 * (size == 'Kecil') + 1.1 * (~is_client) - 2.5 * is_credit)
    has_fin = rng.random(N) >= p_miss
    audited = rng.random(N) < sig(-1.2 + 1.3 * size_lvl + 0.5 * is_credit)
    onboard = pd.Series(pd.NaT, index=range(N), dtype='datetime64[ns]')
    for i in cli_idx:
        lo_ = pd.Timestamp(max(est[i] + 1, 2005), 1, 1); hi_ = pd.Timestamp('2026-03-31')
        onboard[i] = lo_ + pd.Timedelta(days=int(rng.integers(0, max((hi_ - lo_).days, 1))))
    rm_pool = [f'RM-{k:03d}' for k in range(1, 41)]
    lat = G.loc[loc, 'centroid_lat'].values + rng.normal(0, 0.012, N); lon = G.loc[loc, 'centroid_lon'].values + rng.normal(0, 0.012, N)
    companies = pd.DataFrame(dict(company_id=ids, company_name=[n + ' (dummy)' for n in names], industry=ind, kbli_2digit=INDF.loc[ind, 'kbli'].values,
                                  size_class_reference=size, customer_type=ctype, establishment_year=est, employees=emp, city=G.loc[loc, 'city'].values,
                                  district=G.loc[loc, 'district'].values, location_id=loc, latitude=lat.round(5), longitude=lon.round(5),
                                  is_listed=(size == 'Besar') & (rng.random(N) < 0.30), has_import_activity=has_import,
                                  onboarding_date=onboard.dt.strftime('%Y-%m-%d').where(onboard.notna(), None).values,
                                  rm_id=np.where(is_client, rng.choice(rm_pool, N), None), payroll_bank='Bank lain', is_anchor_candidate=False,
                                  business_group=group))
    fin = pd.concat([f.assign(company_id=ids) for f in fin_rows])
    fin['is_audited'] = np.tile(audited, 2)
    fin = fin[np.tile(has_fin, 2)].copy()
    for c_ in [c for c in fin.columns if c.endswith('_bn')]: fin[c_] = fin[c_].round(3 if 'interest' in c_ else 2)
    for c_ in ['ebit_idr_bn', 'interest_expense_idr_bn']: fin.loc[rng.random(len(fin)) < cfg['dq']['nan_ebit'], c_] = np.nan
    fin = fin[['company_id', 'fiscal_year', 'revenue_idr_bn', 'total_assets_idr_bn', 'total_equity_idr_bn', 'total_debt_idr_bn', 'current_assets_idr_bn',
               'current_liabilities_idr_bn', 'ebit_idr_bn', 'interest_expense_idr_bn', 'net_profit_idr_bn', 'is_audited']].sort_values(['company_id', 'fiscal_year'])
    w.put(p_miss=p_miss, has_fin=has_fin, onboard=onboard, rm_pool=rm_pool, companies=companies, fin=fin)

def s09_network_finalize(w):
    rel, ids, rev25, buyer_exit, top_buyer, M, exit_ix, companies, anchors = w.get_('rel ids rev25 buyer_exit top_buyer M exit_ix companies anchors')
    rev_map = dict(zip(ids, rev25))
    rel['annual_transaction_value_idr_mn'] = (rel.dependency_share * rel.source_id.map(rev_map).fillna(5.0) * 1000 * np.where(rel.relationship_type.eq('Supplier'), 0.6, 1.0)).round(1)
    rel['relationship_end'] = None
    for i in np.where(buyer_exit)[0]:
        r_ = top_buyer.loc[ids[i]]; rel.loc[(rel.source_id == ids[i]) & (rel.target_id == r_.target_id), 'relationship_end'] = str(M[exit_ix[i]])
    companies['is_anchor_candidate'] = companies.company_id.isin(anchors)
    w.put(rel=rel)

def s10_products_credit(w):
    rng, N, is_client, is_credit, onboard, need, wallet, regime, mag, nm_, start_ix, recover, h, contagion, rev25, true_cls, legal, ind, ids, companies = w.get_(
        'rng N is_client is_credit onboard need wallet regime mag nm_ start_ix recover h contagion rev25 true_cls legal ind ids companies')
    other_bank = (rng.random((N, 8)) < 0.55).astype(int)
    tenure = np.where(is_client, (pd.Timestamp('2026-06-30') - onboard).dt.days.fillna(0).values / 365, 0)
    own = np.zeros((N, 8), int)
    for k in range(8):
        p = np.where(need[:, k] == 1, sig(-0.5 + 2.0 * wallet + 0.07 * np.minimum(tenure, 15) - 1.2 * other_bank[:, k]), 0.02)
        own[:, k] = (rng.random(N) < p) & is_client
    own[is_client, 0] = 1; own[~is_client] = 0
    own[is_credit, 5] = np.where(need[is_credit, 5] == 1, 1, own[is_credit, 5]); own[is_credit, 6] = np.where(need[is_credit, 6] == 1, 1, own[is_credit, 6])
    own[~is_credit, 5] = 0; own[~is_credit, 6] = 0
    own[is_credit & (own[:, 5] + own[:, 6] == 0), 5] = 1
    payroll_bank = np.where(own[:, 4] == 1, 'BNI', 'Bank lain'); companies['payroll_bank'] = payroll_bank
    dis_now = np.where(regime == 'distress', mag * np.clip((nm_ - start_ix) / 4, 0, 1) * np.where(recover, 0.4, 1.0), 0.0)
    util = np.clip(0.52 - 0.08 * h + 0.9 * dis_now + 0.35 * np.minimum(0.5, 0.7 * contagion) + 0.06 * need[:, 5] + rng.normal(0, 0.14, N), 0.10, 1.0)
    coll_p = {'Low': [.97, .03, 0, 0, 0], 'Medium': [.66, .32, .02, 0, 0], 'High': [.18, .44, .18, .10, .10]}
    cf_rows = []
    for i in np.where(is_credit)[0]:
        ft = 'KMK + KI' if own[i, 5] and own[i, 6] else ('Kredit Modal Kerja' if own[i, 5] else 'Kredit Investasi')
        lim = rev25[i] * rng.uniform(0.10, 0.35); col = int(rng.choice([1, 2, 3, 4, 5], p=coll_p[true_cls[i]]))
        dpd = {1: rng.integers(0, 11), 2: rng.integers(11, 91), 3: rng.integers(91, 121), 4: rng.integers(121, 181), 5: rng.integers(181, 360)}[col]
        pol = 'Legal issue' if legal[i] and rng.random() < .7 else ('Sector limit' if ind[i] in ('Real estat', 'Konstruksi gedung') and rng.random() < .15 else None)
        cf_rows.append((ids[i], ft, round(lim, 2), round(lim * util[i], 2), round(util[i], 3), col, int(dpd), bool(col >= 3 or rng.random() < .03),
                        bool(col >= 2 and rng.random() < .55), pol))
    credit = pd.DataFrame(cf_rows, columns=['company_id', 'facility_type', 'limit_idr_bn', 'outstanding_idr_bn', 'utilization', 'collectibility', 'max_dpd_12m',
                                            'restructuring_flag', 'watchlist_flag', 'policy_restriction'])
    w.put(other_bank=other_bank, tenure=tenure, own=own, payroll_bank=payroll_bank, util=util, credit=credit)

def _transactions(rng, cfg, companies, ids, size, rev25, wallet, is_client, emp, has_import, own, regime, mag, start_ix, spike, spike_ix, spike_mult,
                  buyer_exit, exit_ix, top_buyer, rel, mult, h, bni_parties, da_ids=(), cont_ix=10**6, share_mult=None):
    M = cfg['months']; N = len(ids); n_in = {'Kecil': 7, 'Menengah': 13, 'Besar': 22}
    buy = rel[rel.relationship_type.isin(['Customer', 'Distributor'])].groupby('source_id')[['target_id', 'dependency_share', 'start_ix']].agg(list)
    sup = rel[rel.relationship_type.eq('Supplier')].groupby('source_id')[['target_id', 'dependency_share', 'start_ix']].agg(list)
    cols = {k: [] for k in ['company_id', 'transaction_date', 'direction', 'amount_idr_mn', 'channel', 'transaction_type', 'counterparty_id', 'counterparty_bank', 'data_visibility']}
    spike_rows = []; tid = 0
    def emit(cid, dates, d, amts, ch, tt, cps, vis):
        n = len(amts)
        cols['company_id'] += [cid] * n; cols['transaction_date'] += dates; cols['direction'] += [d] * n; cols['amount_idr_mn'] += list(np.round(amts, 2))
        cols['channel'] += list(ch); cols['transaction_type'] += [tt] * n; cols['counterparty_id'] += list(cps)
        cols['counterparty_bank'] += ['BNI' if (c in bni_parties or (c.startswith('EXT') and rng.random() < .3)) else 'Bank lain' for c in cps]
        cols['data_visibility'] += [vis] * n
    for i in range(N):
        cid = ids[i]; client = is_client[i]; vis_share = wallet[i] if client else rng.uniform(.04, .12)
        base_in = rev25[i] * 1000 / 12 * vis_share                   # rev25 di sini = omzet 2024 (pertumbuhan ada di mult)
        pre = start_ix[i] - 3 if regime[i] == 'distress' else 10 ** 6  # fase sinyal dini distress: mulai 3 bulan sebelum omzet turun
        b_t, b_s, b_st = (buy.loc[cid].target_id, np.array(buy.loc[cid].dependency_share), np.array(buy.loc[cid].start_ix)) if cid in buy.index else ([], np.array([]), np.array([]))
        s_t, s_s, s_st = (np.array(sup.loc[cid].target_id), np.array(sup.loc[cid].dependency_share), np.array(sup.loc[cid].start_ix)) if cid in sup.index else (np.array([]), np.array([]), np.array([]))
        ex_t = top_buyer.at[cid, 'target_id'] if buyer_exit[i] else None
        out_ratio = 0.93 - 0.03 * h[i]
        chronic = sig(-1.8 * h[i] - 1.6)                               # kas ketat kronis (perusahaan lemah) → pajak/gaji kadang telat
        for t, p in enumerate(M):
            dim = p.days_in_month; total_in = base_in * mult[i, t]
            k_in = max(1, rng.poisson(n_in[size[i]] * (1 if client else .25) * min(mult[i, t], 2)))
            w = rng.lognormal(0, 1.0, k_in); amts = total_in * w / w.sum()
            day = lambda k, lo=1, hi=None: [f'{p.year}-{p.month:02d}-{int(x):02d}' for x in rng.integers(lo, (hi or dim) + 1, k)]
            act_m = [(st <= t) and not (b == ex_t and t >= exit_ix[i]) for b, st in zip(b_t, b_st)]       # relasi aktif: sudah dimulai & belum berakhir
            act_b = [b for b, m_ in zip(b_t, act_m) if m_]
            sh = np.array([s * (0.65 if (b in da_ids and t >= cont_ix) else 1.0) for b, s, m_ in zip(b_t, b_s, act_m) if m_])
            prog = float(np.clip((t - pre + 1) / 4, 0, 1))                 # 0 = normal … 1 = tekanan penuh
            cps = [rng.choice(act_b, p=(sh + 1e-3) / (sh + 1e-3).sum()) if act_b and rng.random() < .7 else f'EXT-{rng.integers(10000, 99999)}' for _ in range(k_in)]
            types = np.where(rng.random(k_in) < .72, 'Collection', 'Transfer')
            if not client:
                keep = np.array([c in bni_parties for c in cps]) | (rng.random(k_in) < .15); amts, cps, types = amts[keep], list(np.array(cps)[keep]), types[keep]
            for tt in ['Collection', 'Transfer']:
                mk = types == tt
                if mk.any():
                    ch = rng.choice(['Virtual account', 'Transfer masuk', 'Kliring'], mk.sum(), p=[.45, .4, .15]) if tt == 'Collection' else rng.choice(['Transfer masuk', 'Kliring', 'Internet banking'], mk.sum())
                    emit(cid, day(mk.sum()), 'IN', amts[mk], ch, tt, np.array(cps, dtype=object)[mk], 'Full - rekening BNI' if client else 'Partial - via counterparty BNI')
            if spike[i] and t == spike_ix[i] and client:
                k_ = int(rng.integers(1, 4)); a_ = base_in * spike_mult[i] / k_ * np.ones(k_); emit(cid, day(k_), 'IN', a_, ['Kliring'] * k_, 'Transfer', [f'EXT-{rng.integers(10000, 99999)}' for _ in range(k_)], 'Full - rekening BNI')
                spike_rows.append((cid, len(cols['amount_idr_mn']) - k_, k_))
            if not client: continue
            dis = regime[i] == 'distress' and t >= start_ix[i]
            total_out = total_in * (out_ratio + (0.08 if dis else 0)) * np.exp(rng.normal(0, .05))
            pay = emp[i] * rng.uniform(5.5, 7.5) * (1 if own[i, 4] else vis_share * 1.5) * (1.9 if p.month == 3 else 1)   # THR jelang Lebaran (Mar 2024/2025/2026)
            pay = pay * (share_mult[i, t] if share_mult is not None else 1)
            ch_p = [rng.choice(['Cash management', 'Internet banking'])]
            if prog > 0 and rng.random() < 0.25 + 0.6 * prog:          # SINYAL DINI: gaji dibayar makin telat & dicicil
                d1 = min(dim, 27 + int(round(3 * prog + rng.integers(0, 2))))
                if rng.random() < 0.6 * prog:
                    emit(cid, [f'{p.year}-{p.month:02d}-{d1:02d}', f'{p.year}-{p.month:02d}-{dim:02d}'], 'OUT', np.array([pay * .6, pay * .4]), ch_p * 2, 'Payroll', ['PAYROLL-BATCH'] * 2, 'Full - rekening BNI')
                else:
                    emit(cid, [f'{p.year}-{p.month:02d}-{d1:02d}'], 'OUT', np.array([pay]), ch_p, 'Payroll', ['PAYROLL-BATCH'], 'Full - rekening BNI')
            else:
                pay_day = min(dim, int(rng.choice([25, 25, 26, 27]))) if rng.random() < .92 - 0.35 * chronic else min(dim, int(rng.integers(28, 31)))
                emit(cid, [f'{p.year}-{p.month:02d}-{pay_day:02d}'], 'OUT', np.array([pay]), ch_p, 'Payroll', ['PAYROLL-BATCH'], 'Full - rekening BNI')
            tax = total_in * rng.uniform(.03, .05)
            late = rng.random() < 0.04 + 0.30 * chronic + 0.70 * prog                      # SINYAL DINI: pajak lewat tanggal 15
            emit(cid, day(1, 16, min(dim, 28)) if late else day(1, 5, 15), 'OUT', np.array([tax]), ['Internet banking'], 'Tax', [f'EXT-{rng.integers(10000, 99999)}'], 'Full - rekening BNI')
            rest = max(total_out - pay - tax, total_in * .2)
            imp = rest * rng.uniform(.15, .35) if has_import[i] else 0
            rest = rest * (1 - 0.35 * prog)                                # SINYAL DINI: menahan pembayaran ke supplier
            k_s = max(1, rng.poisson(n_in[size[i]] * .6 * (1 - 0.4 * prog))); w = rng.lognormal(0, 1.0, k_s); a_ = (rest - imp) * w / w.sum()
            sa = s_st <= t; st_a, ss_a = s_t[sa], s_s[sa]
            cps = [rng.choice(st_a, p=(ss_a + 1e-3) / (ss_a + 1e-3).sum()) if len(st_a) and rng.random() < .7 else f'EXT-{rng.integers(10000, 99999)}' for _ in range(k_s)]
            tt = np.where(rng.random(k_s) < .75, 'Supplier payment', 'Transfer')
            for t_ in ['Supplier payment', 'Transfer']:
                mk = tt == t_
                if mk.any(): emit(cid, day(mk.sum()), 'OUT', a_[mk], rng.choice(['Cash management', 'Internet banking', 'Transfer keluar', 'Teller'], mk.sum(), p=[.35, .35, .2, .1]), t_, np.array(cps, dtype=object)[mk], 'Full - rekening BNI')
            if imp: emit(cid, day(1), 'OUT', np.array([imp]), ['Cash management'], 'Import payment', [f'EXT-{rng.integers(10000, 99999)}'], 'Full - rekening BNI')
    tx = pd.DataFrame(cols)
    tx.insert(0, 'transaction_id', [f'T{k + 1:07d}' for k in range(len(tx))])
    spike_ids = [tx.transaction_id.iloc[s + j] for _, s, k in spike_rows for j in range(k)]
    dq = cfg['dq']; n = len(tx)
    tx.loc[rng.random(n) < dq['nan_channel'], 'channel'] = np.nan; tx.loc[rng.random(n) < dq['nan_cp'], 'counterparty_id'] = np.nan
    tx.loc[rng.random(n) < dq['zero_tx'], 'amount_idr_mn'] = 0.0
    dup = tx.sample(frac=dq['dup_tx'], random_state=1)
    tx = pd.concat([tx, dup]).sort_values(['company_id', 'transaction_date', 'transaction_id']).reset_index(drop=True)
    return tx, spike_ids

def s11_transactions(w, with_tx=True):
    rng, cfg, N, M, nm_, ind, g, h, regime, mag, start_ix, recover, buyer_exit, exit_ix, top_buyer, contagion, erosion, erosion_ix, spike, spike_ix, spike_mult, distressed_anchors, ids, cont_ix = w.get_(
        'rng cfg N M nm_ ind g h regime mag start_ix recover buyer_exit exit_ix top_buyer contagion erosion erosion_ix spike spike_ix spike_mult distressed_anchors ids cont_ix')
    mult = np.ones((N, nm_)); vol = (0.09 + 0.14 * sig(-1.2 * h)) * pd.Series(w.size).map({'Kecil': 1.25, 'Menengah': 1.0, 'Besar': 0.6}).values   # usaha besar lebih stabil
    for t, p in enumerate(M):
        ind_m = np.array([IND_MONTH.get(x, {12: 0.06, 1: -0.05}).get(p.month, 0.0) for x in ind])
        mult[:, t] *= (1 + ind_m) * (1 + INDF.loc[ind, 'season'].values * LEBARAN.get(str(p), 0)) * (1 + g) ** (t / 12)
    mult *= np.exp(rng.normal(0, 1, (N, nm_)) * vol[:, None])
    ramp = lambda k, n: np.clip((np.arange(nm_) - k + 1) / n, 0, 1)
    share_mult = np.ones((N, nm_))
    for i in range(N):
        if regime[i] == 'expansion': mult[i] *= 1 + mag[i] * ramp(start_ix[i], 3)
        if regime[i] == 'distress':
            d = mag[i] * ramp(start_ix[i], 4)
            if recover[i]: d = d * (1 - ramp(start_ix[i] + 6, 4))
            mult[i] *= 1 - d
        if buyer_exit[i]: mult[i, exit_ix[i]:] *= 1 - top_buyer.at[ids[i], 'dependency_share'] * 0.55
        if contagion[i] > 0: mult[i] *= 1 - min(0.5, 0.7 * contagion[i]) * ramp(cont_ix, 3)
        if erosion[i]: share_mult[i] = 1 - 0.55 * ramp(erosion_ix[i], 8)
    events = []
    for i in range(N):
        if regime[i] != 'normal':
            up = regime[i] == 'expansion'
            events.append((ids[i], 'Business activity surge' if up else 'Business activity decline', f"{'+' if up else '-'}{int(mag[i] * 100)}%", str(M[start_ix[i]]),
                           str(M[min(start_ix[i] + 5, nm_ - 1)]) if recover[i] else str(M[-1]), regime[i], 'up' if up else 'down', 'inflow' if up else 'inflow+outflow',
                           'menang tender / pesanan baru' if up else ('anchor ekosistem bermasalah' if i in distressed_anchors else 'permintaan turun / pembayaran pelanggan melambat'),
                           regime[i] == 'distress'))
            if regime[i] == 'distress':
                events.append((ids[i], 'Early warning: payment behaviour', 'payroll & pajak makin telat', str(M[max(start_ix[i] - 3, 0)]), str(M[start_ix[i]]), 'early_warning',
                               'down', 'payroll/tax timing', 'tekanan kas sebelum omzet turun', True))
        if buyer_exit[i]:
            events.append((ids[i], 'Major buyer exit', f"-{int(top_buyer.at[ids[i], 'dependency_share'] * 55)}%", str(M[exit_ix[i]]), str(M[-1]), 'buyer_exit', 'down',
                           'counterparty', f"buyer utama {top_buyer.at[ids[i], 'target_id']} berhenti", True))
        if contagion[i] > 0.05:
            events.append((ids[i], 'Ecosystem contagion', f"-{int(min(0.5, 0.7 * contagion[i]) * 100)}%", str(M[cont_ix]), str(M[-1]), 'contagion', 'down', 'counterparty',
                           f"anchor {', '.join(sorted(w.da_ids))} bermasalah (lag 2 bulan)", True))
        if erosion[i]:
            events.append((ids[i], 'Share-of-wallet erosion', '-55%', str(M[erosion_ix[i]]), str(M[-1]), 'wallet_erosion', 'down', 'share-of-wallet',
                           'aliran dana pindah ke bank pesaing; omzet tetap', False))
        if spike[i]:
            events.append((ids[i], 'One-off spike', f"x{spike_mult[i]:.1f}", str(M[spike_ix[i]]), str(M[spike_ix[i]]), 'spike', 'neutral', 'inflow', 'termin proyek / penjualan aset', False))
    gt_anom = pd.DataFrame(events, columns=['company_id', 'anomaly_type', 'surge_magnitude', 'start_month', 'end_month', 'event_type', 'direction', 'mechanism', 'cause', 'affects_risk'])
    tx, spike_tx = None, []
    if with_tx:
        tx, spike_tx = _transactions(rng, cfg, w.companies, ids, w.size, w.rev24, w.wallet, w.is_client, w.emp, w.has_import, w.own, regime, mag, start_ix, spike, spike_ix,
                                     spike_mult, buyer_exit, exit_ix, top_buyer, w.rel, mult * share_mult, h,
                                     set(np.array(ids)[w.is_client]) | set(np.array(w.e_ids)[w.e_bni]), w.da_ids, cont_ix, share_mult)
    w.put(gt_anom=gt_anom, tx=tx, spike_tx=spike_tx)

def s12_rm_actions_holdings(w):
    rng, cfg, N, size_lvl, need, own, cli_idx, is_client, other_bank, rev25, companies, ids, e_ids, e_bni, nL1, rm_pool, onboard, wallet, credit, util = w.get_(
        'rng cfg N size_lvl need own cli_idx is_client other_bank rev25 companies ids e_ids e_bni nL1 rm_pool onboard wallet credit util')
    acts = []; days = pd.bdate_range('2026-01-05', '2026-06-26')
    proxy = 0.6 * size_lvl + 0.4 * need[:, 1:].sum(1) / 7 + rng.normal(0, .5, N)
    q80, q55 = np.quantile(proxy, .80), np.quantile(proxy, .55)
    tier_of = lambda v: 'A' if v > q80 else ('B' if v > q55 else 'C')
    pairs = [(i, k) for i in cli_idx for k in range(1, 8) if not own[i, k]]
    pw = np.array([0.4 + need[i, k] for i, k in pairs]); sel = rng.choice(len(pairs), min(cfg['n_actions_deepening'], len(pairs)), replace=False, p=pw / pw.sum())
    pros_idx = np.where(~is_client)[0]
    acq_targets = list(rng.choice(pros_idx, cfg['n_actions_acq'] // 2)) + list(rng.choice(np.where(~e_bni[:nL1])[0], cfg['n_actions_acq'] - cfg['n_actions_acq'] // 2) + N)
    notes_conv = ['Nasabah tertarik dan langsung onboarding', 'Nasabah setuju, dokumen sedang diproses', 'Produk sudah aktif setelah kunjungan']
    for j, (i, k) in enumerate([pairs[s] for s in sel] + [(t, int(rng.choice([0, 3, 4]))) for t in acq_targets]):
        is_core = i < N; d = days[rng.integers(0, len(days))]; ch = rng.choice(['Kunjungan', 'Telepon', 'Email'], p=[.45, .40, .15])
        if is_core and is_client[i] and d < onboard[i]: d = days[days >= onboard[i]][int(rng.integers(0, 5))]          # deepening hanya setelah menjadi nasabah
        nd = need[i, k] if is_core else int(rng.random() < .5); ob = other_bank[i, k] if is_core else int(rng.random() < .5)
        tier = tier_of(proxy[i]) if is_core else rng.choice(['A', 'B', 'C'], p=[.1, .2, .7])
        if rng.random() < (0.30 if ch == 'Email' else 0.15):
            resp, note = 'No response', rng.choice(['Belum dapat dihubungi', 'PIC sedang tidak di tempat', 'Jadwal pertemuan ditunda'])
        else:
            pc = sig(-2.6 + 2.9 * nd + 0.5 * (tier == 'A') + 0.45 * (ch == 'Kunjungan') - 1.1 * ob)
            r = rng.random()
            if r < pc and is_core and not is_client[i]: resp, note = 'Interested', 'Nasabah setuju, dokumen sedang diproses'
            elif r < pc: resp, note = 'Converted', rng.choice(notes_conv)
            elif r < pc + 0.35 * (1 - pc) * (nd + 0.3): resp, note = 'Interested', rng.choice(['Nasabah tertarik, minta proposal harga', 'Minta simulasi biaya dan manfaat', 'Perlu diskusi lanjutan dengan direktur keuangan'])
            else: resp, note = 'Not interested', ('Belum ada kebutuhan saat ini' if not nd else 'Sudah memakai produk serupa di bank lain' if ob else 'Biaya dinilai kurang kompetitif')
        conv = int(resp == 'Converted'); party = ids[i] if is_core else e_ids[i - N]
        dv = round(float(rng.lognormal(np.log(max(rev25[i] if is_core else 5, 1) * 12), 0.6)), 1) if conv else 0.0
        acts.append((f'A{j + 1:05d}', 'Deepening' if is_core and is_client[i] else 'Acquisition', party, PIDS[k], (companies.rm_id[i] if is_core and is_client[i] else rng.choice(rm_pool)),
                     str(d.date()), ch, tier, resp, conv, dv, int(np.clip(round(1 + 4 * (0.25 * (resp == 'Converted') + 0.2 * (resp == 'Interested') + 0.35 * rng.random() + 0.2 * nd)), 1, 5)), note))
        if conv and is_core and is_client[i]: own[i, k] = 1
    actions = pd.DataFrame(acts, columns=['action_id', 'track', 'party_id', 'product_id', 'rm_id', 'contact_date', 'channel', 'tier_at_contact', 'response', 'converted',
                                          'deal_value_idr_mn', 'rm_rating', 'feedback_note']).sort_values('contact_date').reset_index(drop=True)
    conv_month = actions[actions.converted.eq(1) & actions.party_id.str.startswith('C')].groupby(['party_id', 'product_id']).contact_date.min().str[:7]
    hold = []; cr_out = dict(zip(credit.company_id, credit.outstanding_idr_bn))
    for i in cli_idx:
        ob_m = pd.Period(onboard[i], 'M')
        for k in np.where(own[i])[0]:
            om = conv_month.get((ids[i], PIDS[k]))
            if om is None:
                lo_ = max(ob_m, pd.Period('2005-01', 'M')); span = max((pd.Period('2025-12', 'M') - lo_).n, 0)
                om = str(lo_ + int(rng.integers(0, span + 1)) if k else lo_)
            vis = rev25[i] * 1000 * wallet[i]; o_ = cr_out.get(ids[i], 0.0) * 1000
            bal = vis * rng.uniform(.03, .08) if k == 0 else vis * rng.uniform(.04, .15) if k == 1 else o_ * .6 if k == 5 else o_ * .4 if k == 6 else vis * rng.uniform(.005, .02)
            hold.append((ids[i], PIDS[k], '2026-06', 1, om, round(max(bal, 5), 1), round(util[i], 3) if k in (5, 6) else np.nan, round(vis * .5 * rng.uniform(.3, 1.2), 1)))
    holdings = pd.DataFrame(hold, columns=['company_id', 'product_id', 'snapshot_month', 'active', 'open_month', 'balance_or_outstanding_idr_mn', 'utilization', 'transaction_value_6m_idr_mn'])
    w.put(actions=actions, holdings=holdings, own=own)

def s13_outcome(w):
    rng, actions, cli_idx, own, need, regime, h, other_bank, ids, rev25 = w.get_('rng actions cli_idx own need regime h other_bank ids rev25')
    interested = actions[actions.response.eq('Interested') & actions.party_id.str.startswith('C')].assign(k=lambda d: d.product_id.map({p: j for j, p in enumerate(PIDS)}))
    intr = set(zip(interested.party_id, interested.k)); out = []
    for i in cli_idx:
        for k in range(1, 8):
            if own[i, k]: continue
            p = sig(-2.6 + 2.6 * need[i, k] + 0.6 * (regime[i] == 'expansion') + 0.9 * ((ids[i], k) in intr) + 0.25 * h[i] - 0.7 * other_bank[i, k])
            a = int(rng.random() < p)
            out.append((ids[i], PIDS[k], '2026-06', a, round(float(rng.lognormal(np.log(max(rev25[i], 1) * 10), .6)), 1) if a else 0.0))
    w.put(outcome=pd.DataFrame(out, columns=['company_id', 'product_id', 'observation_end', 'adopted_jul_sep_2026', 'deal_value_idr_mn']))

VISIT_TEXT = {
    'modal_kerja': ['Perusahaan butuh tambahan dana untuk putaran usaha karena pesanan naik.', 'Mereka kekurangan modal kerja untuk membeli bahan baku proyek berikutnya.',
                    'Kas operasional terasa kurang untuk membiayai stok beberapa bulan ke depan.', 'Perputaran uang mereka sedang ketat sejak dapat proyek baru.'],
    'ekspansi_investasi': ['Ada rencana membangun gudang baru tahun depan.', 'Manajemen ingin menambah mesin produksi dan armada.', 'Perusahaan berencana membuka cabang baru di luar kota.', 'Owner bercerita ingin memperbesar kapasitas produksi dua kali lipat.'],
    'impor_ekspor_valas': ['Sebagian bahan baku didatangkan dari luar negeri dan dibayar dalam dolar.', 'Pembayaran ke supplier di Tiongkok sering terganggu fluktuasi kurs.',
                           'Mereka mulai menjajaki ekspor ke Malaysia dan butuh L/C.', 'Sebagian besar bahan dibeli dari pemasok di Korea.'],
    'piutang_lambat': ['Tagihan ke pelanggan sering mundur sampai 60 hari.', 'Penagihan invoice ke kontraktor utama lambat.', 'Banyak pembayaran dari distributor yang telat.', 'Pembeli besar biasanya baru melunasi setelah dua bulan.'],
    'buyer_utama_keluar': ['Salah satu pembeli terbesar mereka berhenti order sejak beberapa bulan lalu.', 'Kontrak dengan pelanggan utama tidak diperpanjang.', 'Klien terbesarnya sudah pindah ke vendor lain.'],
    'payroll_bank_lain': ['Gaji karyawan masih dibayarkan lewat bank lain.', 'Penggajian seluruh pegawai saat ini memakai rekening di bank lain.'],
    'legal_perizinan': ['Perusahaan sedang menghadapi sengketa lahan dengan pemilik lama.', 'Ada gugatan dari mitra terkait kontrak lama.', 'Izin usaha sedang dalam proses perpanjangan yang tertunda.'],
    'tekanan_likuiditas': ['Beberapa kewajiban ke supplier sudah lewat jatuh tempo.', 'Manajemen mengakui sedang kesulitan membayar cicilan bulan ini.', 'Penjualan turun dan arus kas sedang tertekan.', 'Mereka minta keringanan jadwal pembayaran ke beberapa pihak.'],
    'dana_mengendap': ['Ada kelebihan kas yang belum ditempatkan.', 'Dana hasil penjualan banyak yang mengendap di rekening giro.'],
    'kebutuhan_pribadi_pemilik': ['Pemilik menanyakan layanan investasi untuk keperluan pribadi.', 'Owner tertarik layanan prioritas untuk keluarganya.'],
    'biaya_tidak_kompetitif': ['Mereka menilai biaya layanan kita lebih mahal dari bank lain.', 'Keberatan utama ada di biaya administrasi.'],
    'sudah_pakai_bank_lain': ['Untuk layanan ini mereka sudah memakai bank lain dan cukup puas.', 'Produk serupa sudah aktif di bank lain.'],
}
NEG_TEXT = {
    'modal_kerja': 'Kebutuhan dana operasional saat ini masih tercukupi.', 'piutang_lambat': 'Tidak ada masalah penagihan ke pelanggan.',
    'legal_perizinan': 'Tidak ada sengketa atau masalah perizinan.', 'tekanan_likuiditas': 'Arus kas aman dan tidak ada tunggakan.',
    'impor_ekspor_valas': 'Perusahaan tidak melakukan impor maupun ekspor.', 'payroll_bank_lain': 'Gaji karyawan sudah lewat rekening BNI.',
    'ekspansi_investasi': 'Belum ada rencana ekspansi dalam waktu dekat.', 'buyer_utama_keluar': 'Pelanggan utama masih rutin order.'}
FILLER = ['Diskusi berjalan baik dan terbuka.', 'Perusahaan menunjukkan minat untuk kerja sama lebih lanjut.', 'Pertemuan berlangsung sekitar satu jam.',
          'Mereka meminta proposal tertulis setelah pertemuan.', 'RM menjelaskan profil layanan BNI secara umum.']


def _visit_text(rng, issues):
    parts = [rng.choice(VISIT_TEXT[s]) for s in issues]
    cand_neg = [k for k in NEG_TEXT if k not in issues]; negated = []
    if cand_neg and rng.random() < .40:
        k = rng.choice(cand_neg); parts.append(NEG_TEXT[k]); negated.append(k)
    parts += list(rng.choice(FILLER, int(rng.integers(1, 3)), replace=False)); rng.shuffle(parts)
    return ' '.join(parts), negated

def s14_visit_notes(w):
    rng, cfg, N, need, regime, g, ind, has_import, buyer_exit, payroll_bank, legal, is_credit, util, npm25, actions, ids, seed = w.get_(
        'rng cfg N need regime g ind has_import buyer_exit payroll_bank legal is_credit util npm25 actions ids seed')
    issues_of = {}
    for i in range(N):
        iss = []
        if need[i, 5] and (regime[i] == 'expansion' or g[i] > 0.1 or INDF.at[ind[i], 'wc']): iss.append('modal_kerja')
        if need[i, 6] and regime[i] == 'expansion': iss.append('ekspansi_investasi')
        if has_import[i] and need[i, 7]: iss.append('impor_ekspor_valas')
        if buyer_exit[i] or (need[i, 2] and rng.random() < .35): iss.append('piutang_lambat')
        if buyer_exit[i]: iss.append('buyer_utama_keluar')
        if payroll_bank[i] == 'Bank lain' and need[i, 4]: iss.append('payroll_bank_lain')
        if legal[i]: iss.append('legal_perizinan')
        if regime[i] == 'distress' or (is_credit[i] and util[i] > 0.85): iss.append('tekanan_likuiditas')
        if need[i, 1] and npm25[i] > 0.08 and rng.random() < .6: iss.append('dana_mengendap')
        if rng.random() < .05: iss.append('kebutuhan_pribadi_pemilik')
        issues_of[i] = iss
    visits = actions[actions.channel.eq('Kunjungan') & actions.party_id.str.startswith('C')].drop_duplicates('party_id')
    visits = visits.sample(min(cfg['max_visit_notes'], len(visits)), random_state=seed)
    vn, vgt = [], []
    for j, v in enumerate(visits.itertuples()):
        i = ids.index(v.party_id); iss = list(issues_of[i])
        if v.feedback_note == 'Biaya dinilai kurang kompetitif': iss.append('biaya_tidak_kompetitif')
        if v.feedback_note == 'Sudah memakai produk serupa di bank lain': iss.append('sudah_pakai_bank_lain')
        text, negated = _visit_text(rng, iss); vid = f'V{j + 1:04d}'
        vn.append((vid, v.party_id, v.action_id, v.rm_id, v.contact_date, rng.choice(['CFO', 'Direktur Keuangan', 'Manajer Keuangan', 'Direktur Utama', 'Owner']), text))
        vgt += [(vid, s, 1) for s in iss] + [(vid, s, 0) for s in negated]
    w.put(visit_notes=pd.DataFrame(vn, columns=['visit_id', 'company_id', 'action_id', 'rm_id', 'visit_date', 'met_with', 'note_text']),
          gt_visit=pd.DataFrame(vgt, columns=['visit_id', 'issue_id', 'present']))

def _matching(rng, companies, entities, names, e_names, is_client, tx):
    cl = companies[is_client]
    acct = lambda n: rng.integers(1_000_000_000, 9_999_999_999, n)
    ent_bni = entities[entities.is_bni_customer]
    master = pd.concat([pd.DataFrame(dict(customer_id=cl.company_id, legal_name=np.array(names)[is_client], city=cl.city, segment='Core corporate/commercial')),
                        pd.DataFrame(dict(customer_id=ent_bni.entity_id, legal_name=[e_names[int(e[1:]) - 1] for e in ent_bni.entity_id], city=ent_bni.city, segment='Other BNI customer'))])
    master['account_no'] = acct(len(master))
    pros = companies[~is_client]
    registry = pd.concat([pd.DataFrame(dict(registry_id=pros.company_id, legal_name=np.array(names)[~is_client], industry=pros.industry, size_class=pros.size_class_reference,
                                            city=pros.city, location_id=pros.location_id, establishment_year=pros.establishment_year)),
                          pd.DataFrame(dict(registry_id=entities.entity_id, legal_name=e_names, industry=entities.industry, size_class=entities.size_class_reference,
                                            city=entities.city, location_id=entities.location_id, establishment_year=rng.integers(1985, 2024, len(entities))))])
    if tx is None:
        return master, registry, pd.DataFrame(), pd.DataFrame()
    t = tx[(tx.transaction_date >= '2025-07-01') & tx.counterparty_id.astype(str).str.match(r'^[CE]\d') & tx.data_visibility.str.startswith('Full')]
    agg = t.groupby(['company_id', 'direction', 'counterparty_id']).agg(n=('amount_idr_mn', 'size'), v=('amount_idr_mn', 'sum'),
                                                                        f=('transaction_date', 'min'), l=('transaction_date', 'max')).reset_index()
    agg = agg.sample(frac=min(1, 5500 / max(len(agg), 1)), random_state=3)
    nm_of = {**dict(zip(companies.company_id, names)), **dict(zip(entities.entity_id, e_names))}
    city_of = {**dict(zip(companies.company_id, companies.city)), **dict(zip(entities.entity_id, entities.city))}
    acc_of = dict(zip(master.customer_id, master.account_no)); bni = set(master.customer_id)
    def noisy(nm):
        s = nm; r = rng.random()
        if r < .25: s = s.replace('PT ', 'PT. ').replace('CV ', 'CV. ')
        elif r < .45: s = re.sub(r'^(PT|CV|UD) ', '', s)
        elif r < .65:
            w = s.split(); j = int(rng.integers(1, len(w))); w[j] = w[j][:-1] if len(w[j]) > 4 else w[j]; s = ' '.join(w)
        if rng.random() < .15: s = s.upper()
        return s
    cpt = pd.DataFrame(dict(record_id=[f'R{k + 1:06d}' for k in range(len(agg))], bni_party_id=agg.company_id, direction=agg.direction,
                            counterparty_name_raw=[noisy(nm_of[c]) for c in agg.counterparty_id],
                            counterparty_city_raw=[None if rng.random() < .09 else city_of[c] for c in agg.counterparty_id],
                            counterparty_bank=['BNI' if c in bni else f"Bank {rng.choice(list('ABCD'))} (dummy)" for c in agg.counterparty_id],
                            counterparty_account_no=[acc_of[c] if c in bni and rng.random() < .65 else np.nan for c in agg.counterparty_id],
                            txn_count_12m=agg.n.values, txn_value_12m_idr_mn=agg.v.round(1).values, first_txn_month=agg.f.str[:7].values, last_txn_month=agg.l.str[:7].values))
    gt = pd.DataFrame(dict(record_id=cpt.record_id, true_party_id=agg.counterparty_id.values, true_is_bni_customer=[c in bni for c in agg.counterparty_id]))
    return master, registry, cpt, gt

def s15_matching(w):
    master, registry, cpt, gt_match = _matching(w.rng, w.companies, w.entities, w.names, w.e_names, w.is_client, w.tx)
    w.put(master=master, registry=registry, cpt=cpt, gt_match=gt_match)

def s16_geo_branches(w):
    rng, companies, geo, G, seed = w.get_('rng companies geo G seed')
    geo = geo.copy()
    cnt = companies.groupby('location_id').size().reindex(geo.location_id, fill_value=0).values
    corp = np.round(cnt * rng.uniform(9, 16, len(geo)) * np.where(geo.location_id.isin(WHITE_SPACE), 1.6, 1.0)).astype(int)
    geo['total_business_count'] = np.round(corp * rng.uniform(3.5, 5.5, len(geo))).astype(int); geo['corporate_count'] = corp
    geo['regional_gdp_idr_bn'] = np.round(geo.total_business_count * rng.uniform(14, 22, len(geo)), 0)
    geo = geo[['location_id', 'province', 'city', 'district', 'centroid_lat', 'centroid_lon', 'area_km2', 'total_business_count', 'regional_gdp_idr_bn', 'poi_industrial_count', 'corporate_count']]
    br_loc = geo[~geo.location_id.isin(WHITE_SPACE)].sample(40, replace=True, random_state=seed).location_id.values
    btype = rng.choice(['KCU', 'KCP', 'Sentra Bisnis Komersial'], 40, p=[.3, .5, .2]); seen = {}; br_rows = []
    for b, (l, t) in enumerate(zip(br_loc, btype)):
        dname = G.at[l, 'district']; seen[dname] = seen.get(dname, 0) + 1
        nm = f"{'Sentra Bisnis Komersial' if t.startswith('Sentra') else 'Kantor Cabang'} {dname}{' ' + 'I' * seen[dname] if seen[dname] > 1 else ''} (dummy)"
        br_rows.append((f'B{b + 1:03d}', nm, t, round(G.at[l, 'centroid_lat'] + rng.normal(0, .006), 5), round(G.at[l, 'centroid_lon'] + rng.normal(0, .006), 5), l))
    w.put(geo_out=geo, branches=pd.DataFrame(br_rows, columns=['branch_id', 'branch_name', 'branch_type', 'latitude', 'longitude', 'location_id']))

PRODUCT_INFO = [
    ('P01', 'Giro', 'Funding', 'semua korporasi', 'rekening operasional, cek/bilyet giro, terhubung cash management', 'badan usaha berizin', 'biaya administrasi bulanan', 'Funding'),
    ('P02', 'Deposito', 'Funding', 'korporasi dengan kas berlebih', 'imbal hasil tetap untuk dana mengendap', 'saldo minimal sesuai ketentuan', 'suku bunga negosiasi untuk nominal besar', 'Treasury / Funding'),
    ('P03', 'Virtual Account', 'Transactional', 'usaha dengan banyak pelanggan/pembayar', 'rekonsiliasi otomatis penerimaan, mempercepat penagihan', 'nasabah giro BNI', 'biaya per transaksi', 'Transaction Banking'),
    ('P04', 'Cash Management', 'Transactional', 'korporasi menengah–besar', 'kontrol likuiditas, pembayaran massal, laporan real-time', 'nasabah giro BNI', 'paket bulanan', 'Transaction Banking'),
    ('P05', 'Payroll', 'Transactional', 'perusahaan dengan banyak karyawan', 'penggajian massal, rekening karyawan', 'nasabah giro BNI', 'gratis/negosiasi per jumlah karyawan', 'Transaction Banking (Payroll)'),
    ('P06', 'Kredit Modal Kerja', 'Lending', 'usaha dengan siklus kas/proyek', 'membiayai persediaan, piutang, proyek', 'analisis kredit & agunan', 'suku bunga berdasarkan risiko — keputusan analis', 'Kredit Komersial'),
    ('P07', 'Kredit Investasi', 'Lending', 'usaha yang ekspansi/beli aset', 'membiayai mesin, gudang, armada', 'analisis kredit, studi kelayakan', 'suku bunga berdasarkan risiko — keputusan analis', 'Kredit Komersial + Corporate Banking'),
    ('P08', 'Trade Finance', 'Trade', 'importir/eksportir', 'L/C, SKBDN, lindung nilai valas', 'dokumen perdagangan', 'fee per dokumen', 'Trade Finance & Treasury')]
ISSUES = [
    ('modal_kerja', 'Kebutuhan modal kerja', 'modal kerja|dana operasional|putaran usaha|stok|bahan baku|kas operasional', 'P06;P04', 'Kredit Komersial (Analis Kredit)', True, False),
    ('ekspansi_investasi', 'Rencana ekspansi / investasi', 'ekspansi|gudang|mesin|armada|cabang baru|investasi', 'P07', 'Kredit Komersial + Corporate Banking', True, False),
    ('impor_ekspor_valas', 'Transaksi impor/ekspor & valas', 'impor|ekspor|luar negeri|dolar|kurs|l/c', 'P08', 'Trade Finance & Treasury', False, False),
    ('piutang_lambat', 'Penagihan piutang lambat', 'piutang|penagihan|tagihan|invoice|telat|mundur', 'P03;P04', 'Transaction Banking', False, False),
    ('buyer_utama_keluar', 'Pembeli utama berhenti', 'pembeli terbesar|pelanggan utama|berhenti order|tidak diperpanjang', 'P04', 'Risiko Kredit (monitoring) + RM', False, False),
    ('payroll_bank_lain', 'Payroll masih di bank lain', 'gaji|penggajian|payroll', 'P05', 'Transaction Banking (Payroll)', False, False),
    ('legal_perizinan', 'Masalah legal / perizinan', 'sengketa|gugatan|izin|perizinan|legal', '', 'Legal & Compliance', False, True),
    ('tekanan_likuiditas', 'Tekanan likuiditas / tunggakan', 'jatuh tempo|tunggakan|kesulitan membayar|cicilan|tertekan', '', 'Risiko Kredit / Remedial', False, True),
    ('dana_mengendap', 'Dana mengendap', 'kelebihan kas|mengendap|belum ditempatkan', 'P02;P01', 'Treasury / Funding', False, False),
    ('kebutuhan_pribadi_pemilik', 'Kebutuhan pribadi pemilik', 'pemilik|owner|pribadi|keluarga', '', 'Wealth Management', False, False),
    ('biaya_tidak_kompetitif', 'Keberatan biaya', 'biaya|mahal|administrasi', '', 'RM + Pricing', False, False),
    ('sudah_pakai_bank_lain', 'Sudah memakai bank lain', 'bank lain|sudah aktif|sudah memakai', '', 'RM (strategi akuisisi)', False, False)]

def s17_catalog(w):
    w.put(product_master=pd.DataFrame(PRODUCT_INFO, columns=['product_id', 'product_name', 'product_category', 'target_segment', 'key_benefit', 'eligibility', 'pricing_note', 'owner_department']),
          issue_map=pd.DataFrame(ISSUES, columns=['issue_id', 'issue_name', 'keywords', 'solution_products', 'department', 'credit_relevant', 'hold_credit']))

def s18_assemble(w):
    ids, h, g, wallet, regime, mag, start_ix, M, buyer_exit, spike, legal, has_fin, p_miss, erosion, erosion_ix, top_share, contagion, distressed_anchors, grp_eff, N = w.get_(
        'ids h g wallet regime mag start_ix M buyer_exit spike legal has_fin p_miss erosion erosion_ix top_share contagion distressed_anchors grp_eff N')
    gt_latent = pd.DataFrame(dict(company_id=ids, health=h.round(4), growth=g.round(4), wallet_share_bni=wallet.round(3), regime=regime, regime_magnitude=mag,
                                  regime_start=[str(M[k]) if r != 'normal' else None for k, r in zip(start_ix, regime)], buyer_exit=buyer_exit, spike=spike,
                                  legal_issue=legal, has_financial_report=has_fin, p_report_missing=p_miss.round(4),
                                  wallet_erosion=erosion, erosion_start=[str(M[k]) if e else None for k, e in zip(erosion_ix, erosion)],
                                  top_buyer_share=top_share.round(3), contagion_exposure=contagion.round(3), is_distressed_anchor=np.isin(np.arange(N), distressed_anchors),
                                  group_effect=grp_eff.round(3)))
    gt_risk = pd.DataFrame(dict(company_id=ids, customer_type=w.ctype, risk_score_latent=w.s_det.round(4), unobserved_factor=w.u.round(4), risk_score_realized=w.s_real.round(4),
                                true_risk_class=w.true_cls, observed_label=np.where(w.is_credit, w.obs_cls, None), label_flipped=w.flip, oracle_class=w.oracle_cls))
    gt_need = pd.DataFrame([(ids[i], PIDS[k], int(w.need[i, k]), int(w.other_bank[i, k])) for i in range(N) for k in range(8)],
                           columns=['company_id', 'product_id', 'true_need', 'served_by_other_bank'])
    risk_labels = pd.DataFrame(dict(company_id=np.array(ids)[w.is_credit], risk_class=w.obs_cls[w.is_credit], label_date=CUTOFF))
    rel = w.rel[['source_id', 'target_id', 'relationship_type', 'annual_transaction_value_idr_mn', 'dependency_share', 'layer_from_core', 'relationship_start', 'relationship_end']]
    data = {'companies': w.companies, 'financials': w.fin, 'transactions': w.tx, 'product_master': w.product_master, 'product_holdings': w.holdings,
            'geography': w.geo_out, 'branches': w.branches, 'risk_labels': risk_labels, 'credit_facilities': w.credit, 'network_entities': w.entities,
            'relationships': rel, 'bni_customer_master': w.master, 'external_company_registry': w.registry, 'counterparty_transactions': w.cpt,
            'rm_action_log': w.actions, 'outcome_product_adoption': w.outcome, 'rm_visit_notes': w.visit_notes, 'issue_product_map': w.issue_map,
            'gt_prospect_risk': gt_risk[gt_risk.customer_type.eq('Prospect')][['company_id', 'true_risk_class']],
            'gt_anomaly_events': w.gt_anom, 'gt_counterparty_match': w.gt_match,
            'gt_client_risk': gt_risk[gt_risk.observed_label.notna()][['company_id', 'true_risk_class', 'label_flipped']].assign(label_flipped=lambda d: d.label_flipped.astype(int)),
            'gt_risk': gt_risk, 'gt_company_latent': gt_latent, 'gt_product_need': gt_need, 'gt_visit_issues': w.gt_visit,
            'gt_transaction_flags': pd.DataFrame({'transaction_id': w.spike_tx, 'flag': 'one_off_spike'})}
    return {k: v for k, v in data.items() if v is not None and len(v)}

STAGES = [s01_profile, s02_latent, s03_network, s04_events, s05_financials, s06_clients_needs, s07_risk, s08_companies, s09_network_finalize,
          s10_products_credit, s11_transactions, s12_rm_actions_holdings, s13_outcome, s14_visit_notes, s15_matching, s16_geo_branches, s17_catalog]


def generate(seed=SEED, n_core=None, with_tx=True, verbose=False, **over):
    cfg = {**CFG, **over}
    if n_core: cfg.update(n_core=n_core, n_credit=int(n_core * .5), n_noncredit=int(n_core * .2), n_ent_l1=int(n_core * 1.5), n_ent_l2=int(n_core * .9),
                          n_actions_deepening=int(n_core * .75), n_actions_acq=int(n_core * .25))
    w = World(cfg=cfg, rng=np.random.default_rng(seed), seed=seed)
    for st in STAGES:
        t0 = time.time()
        st(w, with_tx) if st is s11_transactions else st(w)
        if verbose: print(f'{st.__name__:26s} {time.time() - t0:6.1f} dtk')
    return s18_assemble(w), cfg

FILE_DOC = {
    'companies': 'Profil 2.000 perusahaan inti (nasabah kredit, nasabah non-kredit, prospect)',
    'financials': 'Laporan keuangan 2024–2025 (perusahaan tanpa laporan = hilang MNAR); kolom baru is_audited',
    'transactions': 'Transaksi per transaksi Jan 2024–Jun 2026 (prospect: hanya yang terlihat lewat counterparty BNI)',
    'product_master': 'Katalog 8 produk + segmen, manfaat, syarat, catatan harga, departemen (untuk grounding GenAI)',
    'product_holdings': 'Produk aktif nasabah per Jun 2026; open_month = bulan konversi untuk deal dari aksi RM',
    'geography': '40 kecamatan Jabodetabek; corporate_count & penetrasi diturunkan dari data',
    'branches': '40 cabang (tidak ada di kecamatan white-space)',
    'risk_labels': 'Rating internal nasabah kredit per Jun 2026 (mengandung ±5% kesalahan rating, lihat gt_client_risk)',
    'credit_facilities': 'Fasilitas kredit. PERINGATAN: collectibility, max_dpd_12m, watchlist_flag, restructuring_flag adalah PROXY LABEL — jangan dipakai sebagai fitur model risiko',
    'network_entities': 'Mitra non-inti (layer 1–2) dengan status nasabah BNI',
    'relationships': 'Relasi supplier/customer/distributor/subsidiary; kolom baru relationship_end (buyer keluar)',
    'bni_customer_master': 'Master nasabah BNI untuk modul company matching (opsional)',
    'external_company_registry': 'Registry eksternal untuk modul company matching (opsional)',
    'counterparty_transactions': 'Agregat 12 bln counterparty dengan nama mentah (typo, singkatan) untuk matching (opsional)',
    'rm_action_log': 'Aksi RM Jan–Jun 2026 + respons + feedback_note (bahan feedback loop & agent)',
    'outcome_product_adoption': 'Adopsi produk Jul–Sep 2026 (HANYA validasi; kolom baru deal_value_idr_mn)',
    'rm_visit_notes': 'BARU — catatan kunjungan RM (teks bebas, parafrase, ±40% berisi kalimat negasi)',
    'issue_product_map': 'BARU — 12 jenis masalah nasabah → produk solusi → departemen (dibaca agent, tidak di-hardcode)',
    'gt_prospect_risk': 'GT — kelas risiko prospect', 'gt_client_risk': 'GT — kelas risiko nasabah sebelum kesalahan rating + penanda label salah',
    'gt_risk': 'GT — skor risiko laten, faktor tak teramati, kelas realisasi, oracle_class (plafon akurasi)',
    'gt_company_latent': 'GT — kesehatan, pertumbuhan, wallet share, regime, kejadian, legal, peluang laporan hilang',
    'gt_anomaly_events': 'GT — kejadian (expansion/distress/buyer_exit/spike) + arah, mekanisme, penyebab',
    'gt_product_need': 'GT — kebutuhan produk sebenarnya + apakah dilayani bank lain',
    'gt_counterparty_match': 'GT — identitas sebenarnya counterparty (matching)',
    'gt_visit_issues': 'GT — masalah yang benar-benar ada (present=1) / dinegasikan (present=0) di tiap catatan kunjungan',
    'gt_transaction_flags': 'GT — transaction_id lonjakan sesaat (spike)'}
FILE_DOC.update({'companies': 'Profil 2.000 perusahaan inti (nasabah kredit, nasabah non-kredit, prospect); kolom baru business_group',
                 'relationships': 'Relasi supplier/customer/distributor/subsidiary (rantai nilai + jarak + grup usaha); relationship_start & relationship_end',
                 'gt_anomaly_events': 'GT — 7 jenis kejadian (expansion, distress, early_warning, buyer_exit, contagion, wallet_erosion, spike) + arah & penyebab',
                 'gt_company_latent': 'GT — kesehatan, pertumbuhan, wallet share, regime, kejadian, legal, peluang laporan hilang, efek grup'})
ID_COLS = {'company_id', 'transaction_id', 'product_id', 'location_id', 'branch_id', 'entity_id', 'source_id', 'target_id', 'customer_id', 'registry_id', 'record_id',
           'action_id', 'party_id', 'visit_id', 'issue_id', 'rm_id', 'bni_party_id', 'counterparty_id', 'account_no', 'counterparty_account_no', 'true_party_id'}
ROLE_OVERRIDE = {('risk_labels', 'risk_class'): 'label', ('risk_labels', 'label_date'): 'id',
                 **{('credit_facilities', c): 'proxy-label' for c in ['collectibility', 'max_dpd_12m', 'watchlist_flag', 'restructuring_flag']},
                 **{('outcome_product_adoption', c): 'outcome' for c in ['adopted_jul_sep_2026', 'deal_value_idr_mn', 'observation_end']},
                 ('rm_visit_notes', 'note_text'): 'teks', ('rm_action_log', 'feedback_note'): 'teks',
                 ('companies', 'company_name'): 'id', ('network_entities', 'entity_name'): 'id'}


def data_dictionary(data):
    rows = []
    for t, df in data.items():
        for c in df.columns:
            role = ('ground-truth' if t.startswith('gt_') else ROLE_OVERRIDE.get((t, c)) or ('id' if c in ID_COLS else
                    'referensi' if t in ('product_master', 'issue_product_map') else 'fitur'))
            s = df[c]
            rows.append(dict(tabel=t, kolom=c, tipe=str(s.dtype), peran=role, terisi=round(float(s.notna().mean()), 4), unik=int(s.nunique()),
                             contoh=str(s.dropna().iloc[0])[:40] if s.notna().any() else ''))
    return pd.DataFrame(rows)


def save(data, cfg, out=OUT, seed=SEED):
    os.makedirs(out, exist_ok=True)
    for k, df in data.items(): df.to_csv(f'{out}/{k}.csv', index=False)
    meta = {k: (str(v) if not isinstance(v, (int, float, dict, tuple, list)) else v) for k, v in cfg.items() if k != 'months'}
    meta.update(seed=seed, months=f"{cfg['months'][0]}..{cfg['months'][-1]}", cutoff=CUTOFF, files={k: len(v) for k, v in data.items()})
    json.dump(meta, open(f'{out}/generator_config.json', 'w'), indent=1, default=str)
    dd = data_dictionary(data); dd.to_csv(f'{out}/data_dictionary.csv', index=False)
    return dd


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(); ap.add_argument('--seed', type=int, default=SEED); ap.add_argument('--out', default=OUT)
    ap.add_argument('--n', type=int, default=None); ap.add_argument('--no-tx', action='store_true'); ap.add_argument('--health-shift', type=float, default=0.0)
    a = ap.parse_args()
    data, cfg = generate(a.seed, a.n, with_tx=not a.no_tx, health_shift=a.health_shift, verbose=True)
    save(data, cfg, a.out, a.seed)
    for k, v in data.items(): print(f'{k:28s} {len(v):>9,}')
