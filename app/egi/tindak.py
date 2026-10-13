"""Tindak lanjut kunjungan: feedback RM, rencana lanjutan, pengajuan kunjungan, dan tiket koordinasi ke divisi lain.

Tabel (outputs/app/):
  feedback.csv    satu baris per kunjungan yang sudah diberi feedback
  kegiatan.csv    satu baris per kegiatan lanjutan yang disetujui RM; status & tenggat untuk pelacakan progres
  requests.csv    pengajuan kunjungan (ke supervisor) dan tiket koordinasi (ke divisi); riwayat percakapan di kolom JSON
Divisi tujuan disarankan dari catatan RM lewat data/raw/issue_product_map.csv (kata kunci → isu → divisi).
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from functools import lru_cache

import pandas as pd

from . import data, kalender as K
from .tables import CsvTable, now

DIVISI = {
    'kredit': 'Kredit Komersial (Analis Kredit)',
    'corporate': 'Corporate Banking',
    'risiko': 'Risiko Kredit / Remedial',
    'transaksi': 'Transaction Banking (Cash Mgmt, VA, Payroll)',
    'trade': 'Trade Finance & Treasury',
    'funding': 'Treasury / Funding',
    'legal': 'Legal & Compliance',
    'wealth': 'Wealth Management',
    'pricing': 'Pricing',
}
# teks departemen di issue_product_map / product_master → kunci divisi
_DEPT_KEYS = [('Remedial', 'risiko'), ('Risiko Kredit', 'risiko'), ('Corporate Banking', 'corporate'), ('Kredit Komersial', 'kredit'),
              ('Trade Finance', 'trade'), ('Transaction Banking', 'transaksi'), ('Treasury', 'funding'), ('Funding', 'funding'),
              ('Legal', 'legal'), ('Wealth', 'wealth'), ('Pricing', 'pricing')]
HASIL = ['Converted', 'Interested', 'Not interested', 'No response']
HASIL_ID = {'Converted': 'Setuju / onboarding', 'Interested': 'Tertarik, perlu tindak lanjut', 'Not interested': 'Tidak tertarik', 'No response': 'Tidak ada respons'}
PRIORITAS = ['Normal', 'Tinggi', 'Mendesak']
ST_PENGAJUAN = ['Diajukan', 'Disetujui', 'Ditolak', 'Dibatalkan']
ST_TIKET = ['Baru', 'Diproses', 'Selesai', 'Ditolak']

FEEDBACK = CsvTable('feedback.csv', ['id', 'event_id', 'rm_id', 'company_id', 'tanggal', 'kanal', 'hasil', 'produk', 'catatan', 'keberatan', 'isu',
                                     'langkah_lanjut', 'jadwal_lanjut_id', 'pertimbangan_ulang', 'tiket', 'dibuat_oleh', 'dibuat_pada'])
KEGIATAN = CsvTable('kegiatan.csv', ['id', 'feedback_id', 'event_id', 'rm_id', 'company_id', 'tanggal_kunjungan', 'urutan', 'judul', 'aksi', 'pemilik',
                                     'divisi', 'sumber', 'jenis', 'jadwal', 'kal_id', 'tenggat', 'status', 'selesai_pada', 'n_jadwal_ulang', 'alasan',
                                     'riwayat', 'dibuat_oleh', 'dibuat_pada', 'diubah_pada'])
ALASAN_ULANG = ['Nasabah minta diundur', 'PIC nasabah berhalangan', 'Menunggu dokumen / data nasabah', 'Bentrok jadwal RM',
                'Menunggu respons divisi', 'Lainnya']
ALASAN_BATAL = ['Nasabah membatalkan', 'Tidak relevan lagi', 'Digantikan kegiatan lain', 'Produk ditahan (risiko / legal)', 'Lainnya']
SUMBER_PROGRES = ('Progress kegiatan', 'Rapat dadakan')   # sumber jadwal kalender yang berasal dari tahap kegiatan
JENIS_DADAKAN = {'Rapat internal': 'Rapat internal', 'Rapat dengan nasabah': 'Kunjungan', 'Kunjungan nasabah': 'Kunjungan',
                 'Telepon nasabah': 'Telepon'}          # jenis kegiatan dadakan → kanal kalender
REQ = CsvTable('requests.csv', ['id', 'jenis', 'rm_id', 'company_id', 'divisi', 'judul', 'isi', 'prioritas', 'tenggat', 'status', 'ref',
                                'usulan_mulai', 'usulan_selesai', 'kanal', 'divisi_terlibat', 'event_id', 'riwayat', 'dibuat_oleh', 'dibuat_pada', 'diubah_pada'])


def dept_keys(text) -> list[str]:
    out = []
    for frag, k in _DEPT_KEYS:
        if frag.lower() in str(text).lower() and k not in out:
            out.append(k)
    return out


@lru_cache(maxsize=1)
def issues():
    f = data.ROOT / 'data/raw/issue_product_map.csv'
    return pd.read_csv(f).set_index('issue_id') if f.exists() else pd.DataFrame(columns=['issue_name', 'keywords', 'solution_products', 'department', 'hold_credit'])


@lru_cache(maxsize=1)
def products():
    f = data.ROOT / 'data/raw/product_master.csv'
    return pd.read_csv(f).set_index('product_id') if f.exists() else pd.DataFrame(columns=['product_name', 'owner_department'])


def suggest(note: str, prods=()):
    """Catatan + produk dibahas → (isu terdeteksi, divisi disarankan, ada isu yang menahan kredit)."""
    iss, t = issues(), str(note).lower()
    hit = [i for i, r in iss.iterrows() if any(k.strip() and k.strip() in t for k in str(r.keywords).split('|'))]
    div = []
    for i in hit:
        div += [k for k in dept_keys(iss.loc[i, 'department']) if k not in div]
    pm = products()
    for p in prods:
        if p in pm.index:
            div += [k for k in dept_keys(pm.loc[p, 'owner_department']) if k not in div]
    hold = any(str(iss.loc[i, 'hold_credit']).lower() == 'true' for i in hit)
    return hit, div, hold


# ------------------------------------------------------------------ saran rencana lanjutan & jadwal ulang
_TIMBANG = ('pertimbang', 'menimbang', 'diskusi internal', 'diskusikan', 'rapat direksi', 'persetujuan direksi', 'persetujuan pusat', 'belum memutuskan',
            'belum bisa memutuskan', 'dikabari', 'kabari', 'membandingkan', 'bandingkan', 'pikir-pikir', 'pikir dulu', 'nanti dulu', 'menunggu', 'tunggu')
JAM_KERJA = (8, 16)                              # slot jadwal ulang: hari kerja, jam 08.00–16.00


def needs_reconsider(hasil, catatan, keberatan) -> bool:
    """Nasabah belum memutuskan: menimbang ulang, diskusi internal, menunggu persetujuan, atau tertarik tapi ada keberatan."""
    if hasil == 'Converted':
        return False
    t = f'{catatan} {keberatan}'.lower()
    return any(k in t for k in _TIMBANG) or (hasil == 'Interested' and bool(str(keberatan).strip()))


def history(cid, exclude_event='') -> pd.DataFrame:
    """Feedback kunjungan sebelumnya ke perusahaan yang sama, terbaru dulu."""
    fb = FEEDBACK.load()
    return fb[(fb.company_id == cid) & (fb.event_id != exclude_event)].sort_values('tanggal', ascending=False) if cid else fb.iloc[0:0]


def free_slot(rm, start: datetime, menit=60) -> datetime:
    """Slot hari kerja pertama mulai `start` yang tidak bentrok dengan jadwal Terjadwal milik RM (langkah 30 menit, maks. 30 hari)."""
    cal = K.for_rm(rm)
    cal = cal[cal.status == 'Terjadwal']
    busy = [(datetime.fromisoformat(m), datetime.fromisoformat(s) if s else datetime.fromisoformat(m) + timedelta(minutes=60))
            for m, s in zip(cal.mulai, cal.selesai) if m]
    t, end = start, start + timedelta(days=30)
    h0, m0 = (start.hour, start.minute) if JAM_KERJA[0] <= start.hour < JAM_KERJA[1] else (JAM_KERJA[0], 0)
    while t < end:
        if t.weekday() >= 5 or t.hour < JAM_KERJA[0]:          # akhir pekan / terlalu pagi → jam usulan di hari (kerja) berikutnya
            t = t.replace(hour=h0, minute=m0) + timedelta(days=1 if t.weekday() >= 5 else 0)
            continue
        e = t + timedelta(minutes=menit)
        if e > t.replace(hour=JAM_KERJA[1], minute=0):
            t = t.replace(hour=h0, minute=m0) + timedelta(days=1)
            continue
        if not any(t < b1 and e > b0 for b0, b1 in busy):
            return t
        t += timedelta(minutes=30)
    return start


# ------------------------------------------------------------------ riwayat percakapan tiket
def thread(row) -> list:
    try:
        return json.loads(row['riwayat']) if row['riwayat'] else []
    except (ValueError, TypeError):
        return []


def _entry(user, pesan, status=None):
    return {'waktu': now(), 'oleh': user, 'pesan': pesan, **({'status': status} if status else {})}


def reply(req_id, user, pesan, status=None):
    df = REQ.load(); row = df[df.id == req_id].iloc[0]
    th = thread(row) + [_entry(user, pesan, status)]
    REQ.update(req_id, riwayat=json.dumps(th, ensure_ascii=False), diubah_pada=now(), **({'status': status} if status else {}))


# ------------------------------------------------------------------ tiket koordinasi
def create_tickets(divs, *, jenis, rm_id, company_id, judul, isi, prioritas='Normal', tenggat='', ref='', event_id='', user=''):
    rows = [{'jenis': jenis, 'rm_id': rm_id, 'company_id': company_id, 'divisi': d, 'judul': judul, 'isi': isi, 'prioritas': prioritas,
             'tenggat': str(tenggat or ''), 'status': 'Baru', 'ref': ref, 'event_id': event_id,
             'riwayat': json.dumps([_entry(user, 'Tiket dibuat', 'Baru')], ensure_ascii=False), 'dibuat_oleh': user, 'dibuat_pada': now()} for d in divs]
    _, _, ids = REQ.upsert(rows, {'diubah_pada': now()}) if rows else (0, 0, [])
    return ids


# ------------------------------------------------------------------ feedback kunjungan
def pending_feedback(rm) -> pd.DataFrame:
    """Kunjungan/telepon yang sudah lewat (atau ditandai selesai) dan belum diberi feedback."""
    cal = K.for_rm(rm)
    if cal.empty:
        return cal
    done = set(FEEDBACK.load().event_id)
    m = pd.to_datetime(cal.mulai, errors='coerce')
    due = cal[(cal.kanal.isin(['Kunjungan', 'Telepon'])) & (cal.status != 'Dibatalkan') & ((m <= pd.Timestamp(datetime.now())) | (cal.status == 'Selesai'))
              & ~cal.id.isin(done) & ~cal.sumber.isin(SUMBER_PROGRES)]          # tahap progres / rapat dadakan dilacak di Progress kegiatan
    return due.assign(_m=m[due.index]).sort_values('_m', ascending=False)   # m[due.index]: frame kosong tetap kosong


def save_feedback(store, ev: dict, *, hasil, produk, catatan, keberatan, isu, langkah, lanjut, divs, prioritas, tenggat, pesan_divisi, user, ulang=False,
                  kegiatan=()):
    """Simpan feedback + (opsional) jadwal lanjutan + tiket koordinasi; tandai jadwal selesai; catat ke log aksi RM."""
    cid, rm = ev['company_id'], ev['rm_id']
    nama = store.co.name.get(cid, cid)
    follow_id = ''
    if lanjut:                                   # (mulai, selesai, kanal)
        m, s, kanal = lanjut
        _, _, ids = K.T.upsert([{'rm_id': rm, 'company_id': cid, 'judul': f'{nama} ({cid}) · ' + ('jadwal ulang (pertimbangan ulang)' if ulang else 'tindak lanjut'), 'kanal': kanal,
                                 'mulai': m.isoformat(timespec='minutes'), 'selesai': s.isoformat(timespec='minutes'),
                                 'lokasi': ev.get('lokasi', ''), 'catatan': f'Tindak lanjut kunjungan {ev["mulai"][:10]}: {langkah}',
                                 'status': 'Terjadwal', 'sumber': 'Tindak lanjut'}], {'dibuat_oleh': user, 'diubah_pada': now()})
        follow_id = ids[0]
    fb_id = f"FB-{ev['id']}"
    pnames = ', '.join(f"{p} {products().product_name.get(p, '')}".strip() for p in produk) or '—'
    isi = (f"Hasil kunjungan {ev['mulai'][:10]} ({ev['kanal']}) oleh {rm}: {HASIL_ID.get(hasil, hasil)}.\n"
           f"Produk dibahas: {pnames}.\nCatatan RM: {catatan}\n" + (f"Keberatan: {keberatan}\n" if keberatan else '')
           + (f"Isu: {', '.join(issues().issue_name.get(i, i) for i in isu)}\n" if isu else '') + (f"Langkah lanjut: {langkah}\n" if langkah else '')
           + (f"Permintaan ke divisi: {pesan_divisi}" if pesan_divisi else ''))
    tickets = create_tickets(divs, jenis='Koordinasi hasil kunjungan', rm_id=rm, company_id=cid, judul=f'Hasil kunjungan {nama}', isi=isi,
                             prioritas=prioritas, tenggat=tenggat, ref=fb_id, event_id=ev['id'], user=user)
    FEEDBACK.upsert([{'id': fb_id, 'event_id': ev['id'], 'rm_id': rm, 'company_id': cid, 'tanggal': ev['mulai'][:10], 'kanal': ev['kanal'],
                      'hasil': hasil, 'produk': ';'.join(produk), 'catatan': catatan, 'keberatan': keberatan, 'isu': ';'.join(isu), 'langkah_lanjut': langkah,
                      'jadwal_lanjut_id': follow_id, 'pertimbangan_ulang': 'ya' if ulang else '', 'tiket': ';'.join(tickets), 'dibuat_oleh': user, 'dibuat_pada': now()}])
    save_kegiatan(fb_id, ev, kegiatan, user, nama=nama)
    K.set_status(ev['id'], 'Selesai', user)
    if cid in store.co.index:                    # format sama dengan log aksi RM → muncul di Profil › Riwayat
        store.append_visit({'action_id': f"APP-{fb_id}", 'track': 'Deepening' if store.cox.is_client.get(cid, False) else 'Acquisition', 'party_id': cid,
                            'product_id': produk[0] if produk else '', 'rm_id': rm, 'contact_date': ev['mulai'][:10], 'channel': ev['kanal'],
                            'tier_at_contact': '', 'response': hasil, 'converted': int(hasil == 'Converted'), 'deal_value_idr_mn': 0.0, 'rm_rating': '',
                            'feedback_note': f"{catatan} | keberatan: {keberatan or '-'} | lanjut: {langkah or '-'}"})
    data.audit('feedback_kunjungan', user=user, rm=rm, company=cid, hasil=hasil, tiket=len(tickets), jadwal_lanjut=bool(follow_id), pertimbangan_ulang=ulang)
    return fb_id, follow_id, tickets


# ------------------------------------------------------------------ progres kegiatan lanjutan
def save_kegiatan(fb_id, ev: dict, kegiatan, user, nama=''):
    """Kegiatan selanjutnya (saran AI dicentang + manual) → satu baris per kegiatan, tenggat jadi tanggal, status 'Belum';
    setiap tahap langsung dipasang di Kalender kunjungan RM pada tanggal tenggatnya."""
    rows = []
    for i, k in enumerate(kegiatan, 1):
        dv = k.get('divisi')
        dv = [DIVISI.get(x, x) for x in dv] if isinstance(dv, list) else ([dv] if dv else [])
        rows.append({'id': f'{fb_id}-{i}', 'feedback_id': fb_id, 'event_id': ev['id'], 'rm_id': ev['rm_id'], 'company_id': ev['company_id'],
                     'tanggal_kunjungan': ev['mulai'][:10], 'urutan': i, 'judul': k.get('judul') or k['aksi'][:60], 'aksi': k['aksi'],
                     'pemilik': k.get('pemilik') or 'RM', 'divisi': ';'.join(dv), 'sumber': k.get('sumber', ''),
                     'jenis': 'Kegiatan', 'tenggat': (date.today() + timedelta(days=int(k.get('tenggat_hari') or 0))).isoformat(), 'status': 'Belum',
                     'selesai_pada': '', 'n_jadwal_ulang': 0, 'riwayat': json.dumps([_entry(user, 'Dibuat dari feedback kunjungan')], ensure_ascii=False),
                     'dibuat_oleh': user, 'dibuat_pada': now()})
    for r in rows:
        r['kal_id'], r['jadwal'] = pasang_kalender(r, nama, user)
    if rows:
        KEGIATAN.upsert(rows, {'diubah_pada': now()})
    return len(rows)


def _buat_jadwal(row: dict, mulai: datetime, kanal, nama, user, status='Terjadwal', catatan=''):
    """Satu jadwal kalender untuk satu tahap kegiatan. → id jadwal."""
    dur = timedelta(minutes=K.R.DURASI_MENIT.get(kanal, 60))
    _, _, ids = K.T.upsert([{'rm_id': row['rm_id'], 'company_id': row['company_id'],
                             'judul': f"{nama or row['company_id']} ({row['company_id']}) · {row['judul']}", 'kanal': kanal,
                             'mulai': mulai.isoformat(timespec='minutes'), 'selesai': (mulai + dur).isoformat(timespec='minutes'), 'lokasi': '',
                             'catatan': f"Tahap {row['urutan']} tindak lanjut kunjungan {row['tanggal_kunjungan']}: {row['aksi']}" + (f"\n{catatan}" if catatan else ''),
                             'status': status, 'sumber': 'Progress kegiatan'}], {'dibuat_oleh': user, 'diubah_pada': now()})
    return ids[0]


def pasang_kalender(row: dict, nama, user):
    """Tahap bertenggat → jadwal di kalender pada tanggal tenggat (slot kosong mulai 10.00, tidak melewati tenggat).
    Status kalender mengikuti status tahap. → (id jadwal, waktu mulai iso)."""
    kanal = kanal_kegiatan(row)
    tg = date.fromisoformat(str(row['tenggat'])[:10])
    awal = datetime.combine(tg, datetime.strptime('10:00', '%H:%M').time())
    m = free_slot(row['rm_id'], awal, K.R.DURASI_MENIT.get(kanal, 60))
    m = m if m.date() == tg else awal                        # slot kosong hari itu; bila penuh / akhir pekan tetap di tanggal tenggat
    status = {'Selesai': 'Selesai', 'Dibatalkan': 'Dibatalkan'}.get(row.get('status'), 'Terjadwal')
    return _buat_jadwal(row, m, kanal, nama, user, status), m.isoformat(timespec='minutes')


def sinkron_kalender(rm, nama_of, user) -> int:
    """Tahap yang belum punya jadwal kalender (mis. dibuat sebelum fitur ini) → dipasang di kalender. → jumlah yang dipasang."""
    df = KEGIATAN.load()
    df = df if rm == 'Semua RM' else df[df.rm_id == rm]
    if df.empty:
        return 0
    ada = set(K.load().id)
    n = 0
    perlu = ~df.kal_id.isin(ada) & (df.status != 'Dibatalkan') & ~((df.sumber == 'Dadakan') & (df.kal_id == ''))   # dadakan tanpa kalender = pilihan RM
    for r in df[perlu].to_dict('records'):
        kal_id, jadwal = pasang_kalender(r, nama_of(r['company_id']), user)
        KEGIATAN.update(r['id'], kal_id=kal_id, jadwal=r['jadwal'] or jadwal, diubah_pada=now())
        n += 1
    return n


def kegiatan_for(rm) -> pd.DataFrame:
    """Kegiatan lanjutan milik RM (atau semua) + status tampilan: selesai (hijau), terlambat (merah, lewat tenggat), berjalan."""
    df = KEGIATAN.load()
    df = df if rm == 'Semua RM' else df[df.rm_id == rm]
    if df.empty:
        return df.assign(status_tampil=pd.Series(dtype=str), sisa_hari=pd.Series(dtype=float))
    sisa = (pd.to_datetime(df.tenggat, errors='coerce') - pd.Timestamp(date.today())).dt.days
    status = (pd.Series('berjalan', index=df.index).mask(sisa < 0, 'terlambat').mask(df.status == 'Selesai', 'selesai')
              .mask(df.status == 'Dibatalkan', 'batal'))
    waktu = pd.to_datetime(df.jadwal.where((df.jadwal != '') & (df.kal_id != ''), df.tenggat), errors='coerce')   # jadwal kalender, atau tenggat
    return df.assign(status_tampil=status, sisa_hari=sisa, urutan=pd.to_numeric(df.urutan, errors='coerce'), waktu=waktu,
                     n_jadwal_ulang=pd.to_numeric(df.n_jadwal_ulang, errors='coerce').fillna(0).astype(int))


def _catat(kid, user, pesan, **fields):
    """Perbarui satu kegiatan + tambahkan entri ke riwayat perubahannya."""
    row = KEGIATAN.load().set_index('id').loc[kid]
    th = thread(row) + [_entry(user, pesan)]
    KEGIATAN.update(kid, riwayat=json.dumps(th, ensure_ascii=False), diubah_pada=now(), **fields)


def set_kegiatan(kid, selesai: bool, user):
    row = KEGIATAN.load().set_index('id').loc[kid]
    if row.kal_id:
        K.set_status(row.kal_id, 'Selesai' if selesai else 'Terjadwal', user)
    _catat(kid, user, 'Ditandai selesai' if selesai else 'Tanda selesai dibatalkan',
           status='Selesai' if selesai else 'Belum', selesai_pada=now() if selesai else '')
    data.audit('progres_kegiatan', user=user, id=kid, selesai=selesai)


def kanal_kegiatan(row) -> str:
    """Kanal kalender untuk sebuah kegiatan: dari jenis (kegiatan dadakan) atau ditebak dari teksnya."""
    if row.get('jenis') in JENIS_DADAKAN:
        return JENIS_DADAKAN[row['jenis']]
    if row.get('jenis') in K.KANAL:
        return row['jenis']
    t = f"{row.get('judul', '')} {row.get('aksi', '')}".lower()
    if 'rapat' in t or 'koordinasi' in t or 'diskusi internal' in t:
        return 'Kunjungan' if 'nasabah' in t or 'direksi' in t else 'Rapat internal'
    if any(w in t for w in ('telepon', 'telpon', 'hubungi', 'whatsapp', 'konfirmasi')):
        return 'Telepon'
    if any(w in t for w in ('kunjung', 'presentasi', 'bertemu', 'datang')):
        return 'Kunjungan'
    if any(w in t for w in ('kirim', 'email', 'surel', 'dokumen', 'proposal', 'simulasi')):
        return 'Email'
    return 'Rapat internal' if row.get('pemilik') not in ('', 'RM', None) else 'Telepon'


def reschedule_kegiatan(kid, tanggal: date, alasan, user, jam=None, kanal=None, nama=''):
    """Jadwal ulang mendadak untuk tahap apa pun. Tahap yang sudah punya jadwal kalender digeser; tahap yang baru punya
    tenggat otomatis dibuatkan jadwal di kalender RM pada tanggal & jam baru (lalu dipakai lagi untuk jadwal ulang berikutnya)."""
    row = KEGIATAN.load().set_index('id').loc[kid]
    lama = row.jadwal or row.tenggat
    m0 = datetime.fromisoformat(row.jadwal) if row.jadwal else None
    jam = jam or (m0.time() if m0 else datetime.strptime('10:00', '%H:%M').time())
    m = datetime.combine(tanggal, jam); jadwal = m.isoformat(timespec='minutes')
    kanal = kanal if kanal in K.KANAL else kanal_kegiatan(row.to_dict())
    ev = K.load().set_index('id')
    kal_id = row.kal_id if row.kal_id and row.kal_id in ev.index else ''
    if kal_id:                                               # geser jadwal yang sudah ada (durasi tetap)
        e = ev.loc[kal_id]
        dur = datetime.fromisoformat(e.selesai) - datetime.fromisoformat(e.mulai) if e.selesai else timedelta(minutes=60)
        K.T.update(kal_id, mulai=jadwal, selesai=(m + dur).isoformat(timespec='minutes'), kanal=kanal, status='Terjadwal', diubah_pada=now())
    else:                                                    # tahap tanpa jadwal → buat jadwal baru di kalender
        kal_id = _buat_jadwal({**row.to_dict(), 'id': kid}, m, kanal, nama, user, catatan=f'Dijadwal ulang · alasan: {alasan}')
    n = int(float(row.n_jadwal_ulang or 0)) + 1
    _catat(kid, user, f'Dijadwal ulang dari {str(lama)[:16].replace("T", " ")} ke {jadwal.replace("T", " ")} ({kanal}) · alasan: {alasan}'
           + ('' if row.kal_id else ' · masuk kalender'),
           tenggat=tanggal.isoformat(), jadwal=jadwal, kal_id=kal_id, jenis=row.jenis or kanal, n_jadwal_ulang=n, alasan=alasan,
           status='Belum' if row.status == 'Dibatalkan' else row.status)
    data.audit('jadwal_ulang_kegiatan', user=user, id=kid, ke=jadwal, kanal=kanal, kalender=kal_id, alasan=alasan)
    return kal_id


def batal_kegiatan(kid, alasan, user):
    row = KEGIATAN.load().set_index('id').loc[kid]
    if row.kal_id:
        K.set_status(row.kal_id, 'Dibatalkan', user)
    _catat(kid, user, f'Dibatalkan · alasan: {alasan}', status='Dibatalkan', alasan=alasan, selesai_pada='')
    data.audit('batal_kegiatan', user=user, id=kid, alasan=alasan)


def aktifkan_kegiatan(kid, user):
    row = KEGIATAN.load().set_index('id').loc[kid]
    if row.kal_id:
        K.set_status(row.kal_id, 'Terjadwal', user)
    _catat(kid, user, 'Diaktifkan kembali', status='Belum', alasan='')
    data.audit('aktifkan_kegiatan', user=user, id=kid)


def tambah_dadakan(store, *, company_id, rm_id, feedback_id, event_id, tanggal_kunjungan, setelah, jenis, judul, agenda, mulai: datetime, menit,
                   pemilik, divisi, ke_kalender, undang_divisi, user):
    """Rapat / kegiatan dadakan: disisipkan ke alur setelah tahap `setelah` (urutan tahap berikutnya digeser),
    opsional masuk kalender dan mengundang divisi lewat tiket. → id kegiatan baru."""
    df = KEGIATAN.load()
    alur = df[df.feedback_id == feedback_id]
    for r in alur.itertuples():                              # geser tahap sesudahnya
        if int(float(r.urutan)) > setelah:
            KEGIATAN.update(r.id, urutan=int(float(r.urutan)) + 1)
    nama = store.co.name.get(company_id, company_id)
    kal_id = ''
    if ke_kalender:
        _, _, ids = K.T.upsert([{'rm_id': rm_id, 'company_id': company_id, 'judul': f'{nama} ({company_id}) · {judul}', 'kanal': JENIS_DADAKAN.get(jenis, 'Rapat internal'),
                                 'mulai': mulai.isoformat(timespec='minutes'), 'selesai': (mulai + timedelta(minutes=int(menit))).isoformat(timespec='minutes'),
                                 'lokasi': '', 'catatan': f'{jenis} (dadakan): {agenda}', 'status': 'Terjadwal', 'sumber': 'Rapat dadakan'}],
                               {'dibuat_oleh': user, 'diubah_pada': now()})
        kal_id = ids[0]
    tiket = []
    if undang_divisi and divisi:
        tiket = create_tickets(divisi, jenis='Undangan rapat dadakan', rm_id=rm_id, company_id=company_id, judul=f'{judul} · {nama}',
                               isi=f"{rm_id} mengundang divisi Anda ke {jenis.lower()} pada {mulai:%A %d %b %Y, %H.%M} WIB ({int(menit)} menit).\nAgenda: {agenda}",
                               prioritas='Tinggi', tenggat=mulai.date(), ref=feedback_id, event_id=event_id, user=user)
    kid = f'{feedback_id}-D{datetime.now():%Y%m%d%H%M%S}'
    KEGIATAN.upsert([{'id': kid, 'feedback_id': feedback_id, 'event_id': event_id, 'rm_id': rm_id, 'company_id': company_id,
                      'tanggal_kunjungan': tanggal_kunjungan, 'urutan': setelah + 1, 'judul': judul, 'aksi': agenda or judul, 'pemilik': pemilik,
                      'divisi': ';'.join(DIVISI.get(d, d) for d in divisi), 'sumber': 'Dadakan', 'jenis': jenis, 'jadwal': mulai.isoformat(timespec='minutes'),
                      'kal_id': kal_id, 'tenggat': mulai.date().isoformat(), 'status': 'Belum', 'selesai_pada': '', 'n_jadwal_ulang': 0,
                      'riwayat': json.dumps([_entry(user, f'Ditambahkan sebagai {jenis.lower()} dadakan'
                                                   + (f' · undangan ke {len(tiket)} divisi' if tiket else ''))], ensure_ascii=False),
                      'dibuat_oleh': user, 'dibuat_pada': now()}], {'diubah_pada': now()})
    data.audit('kegiatan_dadakan', user=user, id=kid, jenis=jenis, kalender=bool(kal_id), tiket=len(tiket))
    return kid, kal_id, tiket


# ------------------------------------------------------------------ pengajuan kunjungan
def submit_visit(*, rm_id, company_id, nama, mulai, selesai, kanal, tujuan, produk, divs, catatan, user):
    isi = f"Tujuan: {tujuan}\nProduk dibawa: {', '.join(produk) or '—'}\n" + (f"Catatan: {catatan}" if catatan else '')
    _, _, ids = REQ.upsert([{'jenis': 'Pengajuan kunjungan', 'rm_id': rm_id, 'company_id': company_id, 'divisi': '', 'judul': f'Kunjungan ke {nama}',
                             'isi': isi, 'prioritas': 'Normal', 'status': 'Diajukan', 'usulan_mulai': mulai.isoformat(timespec='minutes'),
                             'usulan_selesai': selesai.isoformat(timespec='minutes'), 'kanal': kanal, 'divisi_terlibat': ';'.join(divs),
                             'riwayat': json.dumps([_entry(user, 'Pengajuan dibuat', 'Diajukan')], ensure_ascii=False),
                             'dibuat_oleh': user, 'dibuat_pada': now()}], {'diubah_pada': now()})
    data.audit('ajukan_kunjungan', user=user, rm=rm_id, company=company_id, mulai=str(mulai), divisi=divs)
    return ids[0]


def decide_visit(store, req: dict, approve: bool, komentar, user):
    if not approve:
        reply(req['id'], user, komentar or 'Ditolak', 'Ditolak')
        data.audit('tolak_pengajuan', user=user, id=req['id'])
        return None, []
    cid = req['company_id']; nama = store.co.name.get(cid, cid)
    divs = [d for d in req['divisi_terlibat'].split(';') if d]
    ev_id = f"PJ-{req['id']}"
    K.T.upsert([{'id': ev_id, 'rm_id': req['rm_id'], 'company_id': cid, 'judul': f'{nama} ({cid})', 'kanal': req['kanal'], 'mulai': req['usulan_mulai'],
                 'selesai': req['usulan_selesai'], 'lokasi': f"Kec. {store.cox.district.get(cid, '')}" if cid in store.cox.index else '',
                 'catatan': req['isi'] + (f"\nDidampingi: {', '.join(DIVISI.get(d, d) for d in divs)}" if divs else ''),
                 'status': 'Terjadwal', 'sumber': 'Pengajuan'}], {'dibuat_oleh': user, 'diubah_pada': now()})
    m = datetime.fromisoformat(req['usulan_mulai'])
    tickets = create_tickets(divs, jenis='Pendampingan kunjungan', rm_id=req['rm_id'], company_id=cid, judul=f'Pendampingan kunjungan ke {nama}',
                             isi=f"{req['rm_id']} mengajak divisi Anda mendampingi {req['kanal'].lower()} ke {nama} pada {m:%A %d %b %Y, %H.%M} WIB.\n{req['isi']}",
                             prioritas='Normal', tenggat=m.date(), ref=req['id'], event_id=ev_id, user=user)
    REQ.update(req['id'], event_id=ev_id)
    reply(req['id'], user, (komentar or 'Disetujui') + (f" · {len(tickets)} divisi diberi tahu" if tickets else ''), 'Disetujui')
    data.audit('setujui_pengajuan', user=user, id=req['id'], jadwal=ev_id, tiket=len(tickets))
    return ev_id, tickets


# ------------------------------------------------------------------ tampilan per pengguna
def visible_requests(user) -> pd.DataFrame:
    df = REQ.load()
    if user['role'] == 'supervisor':
        return df
    if user['role'] == 'divisi':
        return df[(df.jenis != 'Pengajuan kunjungan') & (df.divisi == user['rm_id'])]
    return df[df.rm_id == user['rm_id']]


def badge_counts(user) -> dict:
    df = visible_requests(user)
    if user['role'] == 'divisi':
        return {'tiket baru': int((df.status == 'Baru').sum())}
    out = {'feedback tertunda': len(pending_feedback(user['rm_id'] if user['role'] == 'rm' else 'Semua RM'))}
    keg = kegiatan_for(user['rm_id'] if user['role'] == 'rm' else 'Semua RM')
    out['kegiatan terlambat'] = int((keg.status_tampil == 'terlambat').sum()) if len(keg) else 0      # yang dibatalkan tidak dihitung
    if user['role'] == 'supervisor':
        out['pengajuan menunggu'] = int(((df.jenis == 'Pengajuan kunjungan') & (df.status == 'Diajukan')).sum())
    return out
