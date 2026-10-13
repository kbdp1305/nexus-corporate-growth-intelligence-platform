"""Guardrail RM Copilot (aturan di kode, tanpa LLM; hasilnya sama setiap kali, bisa diaudit).

Input  : prompt injection / jailbreak (blokir), kata kasar (samarkan, atau tolak bila isinya hanya makian),
         di luar scope (lapis 1 = kata kunci; lapis 2 = penanda <<di_luar_scope>> dari agen), PII (samarkan sebelum ke LLM).
Output : PII & kata kasar disamarkan; kalimat yang menawarkan kredit ke nasabah risiko High dihapus.
Audit  : setiap kejadian dicatat di outputs/app/audit_log.jsonl (event 'guardrail'); pola yang kena hanya ada di log, tidak di layar.
Kill switch: outputs/app/guard_settings.json {"llm_off": true} atau .env LLM_ENABLED=false → Copilot kembali ke mode template.
"""
from __future__ import annotations

import json
import re

from . import data

# ------------------------------------------------------------------ PII (DLP)
# urutan penting: pola yang lebih spesifik dulu. Angka ≥ 10 digit yang didahului "Rp" dianggap nominal, bukan PII.
_PII = [
    ('EMAIL', re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')),
    ('NPWP', re.compile(r'\b\d{2}\.\d{3}\.\d{3}\.\d-\d{3}\.\d{3}\b')),
    ('NO_HP', re.compile(r'(?<![\w.])(?:\+62|62|0)8\d{1,3}[\s-]?\d{3,4}[\s-]?\d{3,5}\b')),
    ('NIK', re.compile(r'(?<![\w.])\d{16}\b')),
    ('NPWP', re.compile(r'(?<![\w.])\d{15}\b')),
    ('NO_REKENING', re.compile(r'(?<![\w.])\d{3,4}[\s-]?\d{3,4}[\s-]?\d{3,8}\b')),
]
_RP = re.compile(r'(?:rp\.?|idr)\s*$', re.I)


def mask_pii(text):
    """→ (teks_tersamar, {jenis: jumlah})."""
    if not isinstance(text, str) or not text:
        return text, {}
    found = {}
    for kind, pat in _PII:
        def sub(m, kind=kind):
            digits = re.sub(r'\D', '', m.group(0))
            if kind == 'NO_REKENING' and not 10 <= len(digits) <= 16:
                return m.group(0)
            if kind != 'EMAIL' and _RP.search(m.string[max(0, m.start() - 5):m.start()]):
                return m.group(0)
            found[kind] = found.get(kind, 0) + 1
            return f'[{kind}]'
        text = pat.sub(sub, text)
    return text, found


# ------------------------------------------------------------------ kata kasar
_LEET = str.maketrans({'0': 'o', '1': 'i', '3': 'e', '4': 'a', '5': 's', '7': 't', '@': 'a', '$': 's', '!': 'i'})
_BAD = {'anjing', 'anjg', 'anjir', 'anying', 'njing', 'bangsat', 'bgst', 'bangsad', 'babi', 'monyet', 'kampret', 'bajingan', 'brengsek', 'keparat',
        'goblok', 'goblog', 'gblk', 'tolol', 'tll', 'bego', 'bodoh', 'idiot', 'dungu', 'kontol', 'kntl', 'memek', 'mmk', 'ngentot', 'ngntt', 'entot',
        'jancok', 'jancuk', 'cok', 'jembut', 'tai', 'taik', 'sialan', 'asu', 'fuck', 'fucking', 'shit', 'bitch', 'bastard', 'asshole', 'stupid', 'dumb', 'wtf'}


def _norm(tok):
    t = tok.lower().translate(_LEET)
    return re.sub(r'(.)\1+', r'\1', t)               # 'goblokkk' → 'goblok'


def mask_profanity(text):
    """→ (teks, jumlah kata kasar disamarkan)."""
    if not isinstance(text, str) or not text:
        return text, 0
    n = 0

    def sub(m):
        nonlocal n
        w = m.group(0)
        if _norm(w) in _BAD or w.lower() in _BAD:
            n += 1
            return w[0] + '*' * (len(w) - 1)
        return w
    return re.sub(r'[\w@$!]+', sub, text), n


# ------------------------------------------------------------------ prompt injection / jailbreak
_INJECT = [re.compile(p, re.I) for p in [
    r'\b(abaikan|lupakan|acuhkan|hiraukan|langgar|ignore|disregard|forget|override)\b.{0,40}\b(instruksi|aturan|perintah|prompt|batasan|pedoman|instructions?|rules?|guidelines?|guardrails?)(mu|nya|ku|an)?\b',
    r'\b(system|sistem)\s*prompt\b|\bprompt\s+sistem\b',
    r'\b(tampilkan|tunjukkan|bocorkan|sebutkan|ulangi|print|reveal|show|repeat)\b.{0,30}\b(instruksi|aturan|prompt|instructions?|rules?)\b.{0,20}\b(awal|asli|sistem|rahasia|kamu|anda|mu|your|system|original|hidden)\b',
    r'\b(jailbreak|DAN mode|developer mode|mode developer|mode dewa|god mode)\b',
    r'\b(kamu|anda|you)\s+(sekarang|adalah|are now)\b.{0,40}\b(bebas|tanpa (batas|aturan|filter)|unrestricted|unfiltered|no (rules|limits))\b',
    r'\b(berpura-pura(lah)?|pura-pura(lah)?|bertindak(lah)? sebagai|act as|pretend( to be)?|roleplay)\b.{0,40}\b(tanpa (batas|aturan|filter)|admin|developer|hacker|unrestricted)\b',
    r'\b(bypass|lewati|matikan|nonaktifkan|disable)\b.{0,25}\b(guardrail|filter|aturan|pengaman|keamanan|safety|persetujuan|approval)\b',
    r'\b(setujui|eksekusi|jalankan)\b.{0,25}\b(tanpa|langsung tanpa)\b.{0,15}\b(persetujuan|approval|konfirmasi)\b',
    r'\b(tidak|tak|bukan)\s+(lagi\s+)?(terikat|dibatasi|tunduk)\b.{0,25}\b(aturan|batasan|instruksi|kebijakan)',
    r'\bprompt\b.{0,40}\b(developer|pengembang|dikasih|diberikan|awal|asli|rahasia|tersembunyi)\b',
    r'\b(anggap(lah)?|bayangkan|seolah)\b.{0,30}\b(kamu|anda)\b.{0,30}\b(analis|admin|supervisor|developer|pengembang|direksi|komite)\b',
    r'\b(izinkan|mengizinkan|boleh|silakan)\b.{0,30}\b(melewati|lewati|abaikan|tanpa)\b.{0,20}\b(persetujuan|approval|aturan|guardrail|batasan)\b',
]]

# ------------------------------------------------------------------ scope
_DOMAIN = re.compile(r'\b(nasabah|klien|debitur|rm|portofolio|portfolio|kredit|pinjaman|limit|produk|giro|deposito|virtual account|payroll|cash management|'
                     r'trade|alarm|alert|distress|risiko|wallet|transaksi|arus kas|kunjungan|kunjungi|jadwal|kalender|rencana|triase|prospect|prospek|'
                     r'kecamatan|wilayah|cabang|segmen|skor|peluang|model|bni|bank|perusahaan|pt|cv|mitra|pemasok|pembeli|eskalasi|analis|divisi|'
                     r'tiket|tindak lanjut|pesan|omzet|keuangan|rasio|industri|konversi|deal|dashboard)\b|\bC\d{4}\b', re.I)
_OFF = re.compile(r'\b(resep|masak|memasak|kuliner|politik|pemilu|pilpres|capres|presiden|partai|dpr|agama|film|drama|lagu|musik|artis|selebriti|gosip|'
                  r'sepak ?bola|piala dunia|game|gim|anime|zodiak|ramalan|horoskop|cuaca|liburan|wisata|pacar|pacaran|cinta|jodoh|diet|olahraga|'
                  r'pr sekolah|tugas sekolah|skripsi|puisi|pantun|cerpen|cerita pendek|dongeng|lirik|coding|ngoding|python|javascript|html|kode program|togel|judi|'
                  r'bitcoin|crypto|kripto|saham apa|beli saham|harga emas|website|toko online)\b', re.I)
OUT_OF_SCOPE = '<<di_luar_scope>>'
SCOPE_HELP = ('Copilot membantu soal portofolio dan nasabah Anda: analisis nasabah, alarm & triase, peluang produk, prospect & wilayah, '
              'rencana kunjungan, dan tindak lanjut. Contoh: "Siapa nasabah saya yang porsi wallet-nya turun?"')

MESSAGES = {
    'injection': 'Permintaan untuk mengubah atau melewati aturan Copilot tidak bisa diproses. Copilot hanya membantu analisis portofolio dan tindak lanjut nasabah. '
                 'Tulis ulang pertanyaan Anda tanpa meminta mengubah aturan.',
    'kasar': 'Copilot siap membantu soal portofolio dan nasabah Anda. Silakan sampaikan pertanyaan Anda.',
    'scope': 'Pertanyaan ini di luar cakupan Copilot. ' + SCOPE_HELP,
}
TITLES = {'injection': 'Ditolak oleh guardrail input', 'kasar': 'Ditolak oleh guardrail input', 'scope': 'Di luar cakupan Copilot'}


def in_domain(text):
    return bool(_DOMAIN.search(text or ''))


def check_input(text):
    """Pemeriksaan sebelum teks RM dikirim ke LLM.
    → {'ok': bool, 'teks': teks aman (PII & kata kasar disamarkan), 'kategori': None|'injection'|'kasar'|'scope', 'catatan': [..], 'pola': ..}"""
    raw = text or ''
    hit = next((p.pattern for p in _INJECT if p.search(raw)), None)
    if hit:
        return {'ok': False, 'teks': mask_pii(raw)[0], 'kategori': 'injection', 'catatan': [], 'pola': hit[:80]}
    safe, n_bad = mask_profanity(raw)
    safe, pii = mask_pii(safe)
    notes = []
    if pii:
        notes.append(f"{sum(pii.values())} data pribadi ({', '.join(k.replace('_', ' ').lower() for k in pii)}) disamarkan sebelum dikirim ke AI")
    if n_bad:
        words = re.findall(r'\w+', safe)
        content = [w for w in words if '*' not in w and len(w) > 2 and w.lower() not in {'kamu', 'anda', 'lu', 'lo', 'dasar', 'copilot', 'bot', 'ini', 'itu', 'banget', 'sekali', 'yang'}]
        if not in_domain(safe) and len(content) < 3:
            return {'ok': False, 'teks': safe, 'kategori': 'kasar', 'catatan': notes, 'pola': f'{n_bad} kata kasar tanpa pertanyaan'}
        notes.append('bahasa tidak pantas disamarkan')
    if _OFF.search(safe) and not in_domain(safe):
        return {'ok': False, 'teks': safe, 'kategori': 'scope', 'catatan': notes, 'pola': _OFF.search(safe).group(0)}
    return {'ok': True, 'teks': safe, 'kategori': None, 'catatan': notes, 'pii': pii, 'kasar': n_bad}


# ------------------------------------------------------------------ output
CREDIT = {'P06': 'Kredit Modal Kerja', 'P07': 'Kredit Investasi'}
_CREDIT_WORD = re.compile(r'\b(P06|P07|kredit modal kerja|kredit investasi|KMK|tambah limit|penambahan limit|top[- ]?up|fasilitas kredit baru|pinjaman)\b', re.I)
_OFFER = re.compile(r'\b(tawarkan|tawari|menawarkan|ditawarkan|ajukan|mengajukan|rekomendasikan|merekomendasikan|usulkan|dorong|pitch|offer|berikan kredit|naikkan limit)\b', re.I)
_NEG = re.compile(r'\b(jangan|tidak|tak|bukan|tunda|ditunda|menunda|tahan|ditahan|hanya non-kredit|non-kredit|hindari|dilarang|belum)\b', re.I)


def credit_violation(text, high_ids, high_names=()):
    """True bila teks menawarkan produk kredit ke nasabah risiko High (tanpa kata penyangkal)."""
    if not text or not _CREDIT_WORD.search(text) or not _OFFER.search(text) or _NEG.search(text):
        return False
    return any(c in text for c in high_ids) or any(n and n.lower() in text.lower() for n in high_names)


def check_output(text, high_ids=(), high_names=()):
    """Bersihkan jawaban sebelum tampil. → (teks, catatan[])."""
    if not text:
        return text, []
    notes = []
    kept, dropped = [], 0
    for line in text.split('\n'):
        parts = re.split(r'(?<=[.!?])\s+', line)
        good = [s for s in parts if not credit_violation(s, high_ids, high_names)]
        dropped += len(parts) - len(good)
        if good or not line.strip():
            kept.append(' '.join(good))
    if dropped:
        notes.append(f'{dropped} kalimat dihapus: tawaran kredit untuk nasabah risiko High tidak diizinkan')
    text = '\n'.join(kept)
    text, n_bad = mask_profanity(text)
    if n_bad:
        notes.append('bahasa tidak pantas disamarkan')
    text, pii = mask_pii(text)
    if pii:
        notes.append(f"{sum(pii.values())} data pribadi disamarkan di jawaban")
    return text, notes


# ------------------------------------------------------------------ audit & kill switch
SETTINGS = data.APP_OUT / 'guard_settings.json'


def log(kategori, tahap, **kw):
    data.audit('guardrail', kategori=kategori, tahap=tahap, **kw)


def settings():
    try:
        return json.loads(SETTINGS.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def set_llm_off(off: bool, user=''):
    data.APP_OUT.mkdir(parents=True, exist_ok=True)
    SETTINGS.write_text(json.dumps({**settings(), 'llm_off': bool(off), 'diubah_oleh': user}, ensure_ascii=False), encoding='utf-8')
    data.audit('kill_switch', llm_off=bool(off), oleh=user)


def versions():
    """Versi model yang dicatat di setiap baris audit chat."""
    try:
        risk = json.loads((data.ROOT / 'models/05_optimization/manifest.json').read_text(encoding='utf-8')).get('model_version')
    except (OSError, ValueError):
        risk = None
    return {'model_risiko': risk}


LABELS = {'injection': 'Prompt injection diblokir', 'kasar': 'Kata kasar', 'scope': 'Di luar cakupan', 'pii': 'PII disamarkan',
          'kredit_high': 'Kredit ke risiko High dicegah', 'angka': 'Angka tak berdasar'}


def stats(rm=None):
    """Hitung kejadian guardrail di log audit (untuk panel Guardrail)."""
    f = data.APP_OUT / 'audit_log.jsonl'
    out = {}
    if not f.exists():
        return out
    for line in f.read_text(encoding='utf-8').splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get('event') != 'guardrail' or (rm and rm != 'Semua RM' and e.get('rm') not in (rm, None)):
            continue
        out[e.get('kategori')] = out.get(e.get('kategori'), 0) + 1
    return out
