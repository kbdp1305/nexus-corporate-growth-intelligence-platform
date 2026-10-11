"""Penyedia LLM (Anthropic, OpenAI-compatible: OpenAI / Gemini / Ollama / Groq) + cadangan template.

Prinsip: LLM tidak pernah menghitung. Semua angka datang dari paket fakta (reports.fact_pack);
LLM hanya menulis narasi, lalu reports.check_numbers memastikan tidak ada angka karangan.
Bila LLM mati / tidak dikonfigurasi / angka tidak cocok → teks template dipakai.

Konfigurasi lewat .env di folder proyek:
  LLM_PROVIDER=anthropic | openai | none
  LLM_MODEL=...                      (mis. claude-sonnet-5-5, gpt-4o-mini, gemini-2.0-flash, llama3.1)
  ANTHROPIC_API_KEY=...  /  OPENAI_API_KEY=...
  OPENAI_BASE_URL=...                (opsional: Gemini, Ollama http://localhost:11434/v1, Groq, dll.)
"""
from __future__ import annotations

import json
import os
import re

import numpy as np

try:
    from dotenv import load_dotenv
    from .data import ROOT
    load_dotenv(ROOT / '.env')
except Exception:  # pragma: no cover
    pass

import reports as R

SYSTEM = ("Anda adalah RM Copilot untuk Relationship Manager korporasi sebuah bank di Indonesia. Tulis dalam bahasa Indonesia yang lugas dan profesional. "
          "Aturan: (1) hanya gunakan angka yang ada di FAKTA, jangan menghitung atau mengarang angka baru; (2) jangan memberi keputusan kelayakan kredit, "
          "itu wewenang analis; (3) bandingkan dengan peer bila datanya ada; (4) setiap saran harus bisa dikerjakan RM; (5) data bersifat sintetis.")


def config():
    prov = os.getenv('LLM_PROVIDER', 'none').lower().strip()
    key = os.getenv('ANTHROPIC_API_KEY') if prov == 'anthropic' else os.getenv('OPENAI_API_KEY', 'ollama' if os.getenv('OPENAI_BASE_URL') else None)
    default_model = {'anthropic': 'claude-sonnet-5-5', 'openai': 'gpt-4o-mini'}.get(prov, '')
    return {'provider': prov, 'model': os.getenv('LLM_MODEL', default_model), 'enabled': prov in ('anthropic', 'openai') and bool(key), 'key': key}


def _client():
    cfg = config()
    if not cfg['enabled']:
        return None, cfg
    if cfg['provider'] == 'anthropic':
        import anthropic
        return anthropic.Anthropic(api_key=cfg['key']), cfg
    import openai
    return openai.OpenAI(api_key=cfg['key'], base_url=os.getenv('OPENAI_BASE_URL') or None), cfg


def complete(prompt, system=SYSTEM, max_tokens=1200):
    """Satu panggilan teks. Mengembalikan None bila LLM tidak tersedia atau gagal."""
    try:
        cl, cfg = _client()
        if cl is None:
            return None
        if cfg['provider'] == 'anthropic':
            r = cl.messages.create(model=cfg['model'], max_tokens=max_tokens, system=system, messages=[{'role': 'user', 'content': prompt}])
            return ''.join(b.text for b in r.content if getattr(b, 'type', '') == 'text')
        r = cl.chat.completions.create(model=cfg['model'], max_tokens=max_tokens, messages=[{'role': 'system', 'content': system}, {'role': 'user', 'content': prompt}])
        return r.choices[0].message.content
    except Exception as e:  # jaringan, kuota, model salah → template
        complete.last_error = str(e)
        return None


complete.last_error = ''


def complete_json(prompt, keys, system=SYSTEM, max_tokens=1600):
    txt = complete(prompt + f"\n\nBalas HANYA dengan JSON berisi kunci: {', '.join(keys)}. Nilai berupa string, kecuali yang diminta berupa daftar.", system, max_tokens)
    if not txt:
        return None
    m = re.search(r'\{.*\}', txt, re.S)
    try:
        return json.loads(m.group()) if m else None
    except json.JSONDecodeError:
        return None


def _facts_json(fp):
    def conv(o):
        if isinstance(o, dict): return {k: conv(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)): return [conv(v) for v in o]
        if isinstance(o, (np.floating, float)): return None if not np.isfinite(o) else round(float(o), 3)
        if isinstance(o, np.integer): return int(o)
        return o
    return json.dumps(conv(fp), ensure_ascii=False)


# ---------------------------------------------------------------- template (tanpa LLM)
def template_company(fp):
    f, r, ak, j, an = R.fmt, fp['risiko'], fp['arus_kas'], fp['jaringan'], fp['anomali']
    o, k = fp.get('peluang'), fp.get('keuangan')
    prod = fp.get('produk') or []
    top = next((p for p in prod if not p['ditunda']), None)
    s = [f"{fp['nama']} adalah {('nasabah ' + fp['segmen']) if fp['tipe'] != 'Prospect' else 'prospect ' + str(fp['segmen'])} di {fp['kecamatan']} dengan risiko kredit {r['kelas']} "
         f"(peluang High {f(r['p_high'], 1)}%, keputusan {r['keputusan'].lower()})."]
    if k:
        g = k['perubahan_pct'].get('Omzet')
        if g is not None and np.isfinite(g):
            s.append(f"Omzet FY2025 Rp {f(k['pos']['Omzet'][1], 1)} M ({'naik' if g >= 0 else 'turun'} {f(abs(g), 0)}%).")
    if ak['capture_chg_6m'] is not None and np.isfinite(ak['capture_chg_6m']):
        s.append(f"Porsi transaksi di BNI kini {f(ak['capture_now'], 2)}, berubah {f(ak['capture_chg_6m'], 0)} poin dalam 6 bulan.")
    s.append(f"Perusahaan ini punya {j['mitra']} mitra aktif (median industri {f(j['median_peer'], 0)}), {j['prospect']} di antaranya belum menjadi nasabah BNI.")
    if o:
        s.append(f"Peringkat {o['peringkat']} dari {o['n_segmen']} di segmennya; alasan utama: {o['alasan']}.")
    ringkasan = ' '.join(s)
    keu = '—'
    if k:
        rat = k['rasio']; parts = []
        for key, lab in [('CR', 'current ratio'), ('DER', 'utang/ekuitas'), ('ICR', 'ICR'), ('NPM', 'margin bersih')]:
            v = rat[key]; pos = 'lebih baik dari' if v['persentil'] >= 60 else ('lebih buruk dari' if v['persentil'] <= 40 else 'setara dengan')
            parts.append(f"{lab} {f(v['2025'], 2)} {pos} median peer {f(v['median_peer'], 2)}")
        keu = f"Dibanding {k['n_peer']} peer ({k['peer']}): " + '; '.join(parts) + '. Kelayakan kredit tetap dinilai analis.'
    risiko = f"Kelas {r['kelas']} (Low {f(r['p_low'], 1)}%, Medium {f(r['p_med'], 1)}%, High {f(r['p_high'], 1)}%). Pendorong utama: " + '; '.join(r['alasan']) + '.'
    if an['resmi_3bln']:
        anom = f"Ada alarm dalam 3 bulan terakhir: {', '.join(an['jenis_3bln'])}. Cek arus kas dan riwayat sebelum menawarkan produk kredit."
    elif an['sinyal_bawah_ambang']:
        anom = (f"Tidak ada alarm resmi, tetapi porsi wallet berubah {f(ak['capture_chg_6m'], 0)} poin dalam 6 bulan sementara keterlambatan bayar {f(ak['telat_3m'], 0)}%. "
                'Polanya lebih dekat ke perpindahan transaksi ke bank lain daripada kesulitan keuangan; perlakukan sebagai kunjungan retensi.')
    elif not ak.get('ada_data', True):
        anom = 'Belum ada data arus kas karena perusahaan ini belum bertransaksi lewat BNI; sinyal awal hanya dari jaringan mitra.'
    else:
        anom = f"Tidak ada alarm dalam 3 bulan terakhir; keterlambatan bayar {f(ak['telat_3m'], 0)}% dan outflow {f(ak['out_in_3m'], 2)} dari inflow."
    pt = j['prospect_teratas']
    jar = (f"{j['mitra']} relasi senilai Rp {f(j['nilai_M'], 0)} M per tahun. " + (f"Prospect terbesar: {pt[0][1]} (Rp {f(pt[0][3], 1)} M). " if pt else '')
           + (f"{j['mitra_distress']} mitra sedang alarm distress (Rp {f(j['nilai_distress_M'], 0)} M); pantau pembayaran dari mereka." if j['mitra_distress'] else 'Tidak ada mitra yang sedang alarm distress.'))
    rek = []
    if an['sinyal_bawah_ambang'] or (ak['capture_chg_6m'] or 0) < -5:
        rek.append('Kunjungan retensi: tanyakan pembayaran mana yang pindah ke bank lain dan alasannya.')
    if top:
        rek.append(f"Tawarkan {top['produk']} (peluang {f(top['peluang'], 0)}%, dipakai {f(top['peer_pct'], 0)}% peer).")
    if pt:
        rek.append(f'Tawarkan pembiayaan rantai pasok untuk mitra yang belum menjadi nasabah, mulai dari {pt[0][1]}.')
    if fp['payroll'] != 'BNI' and fp['tipe'] != 'Prospect':
        rek.append(f"Payroll masih di bank lain: siapkan penawaran payroll untuk {f(fp['karyawan'], 0)} karyawan.")
    tanya = ['Apa rencana bisnis 12 bulan ke depan dan kebutuhan pembiayaannya?']
    if an['sinyal_bawah_ambang']:
        tanya.insert(0, 'Pembayaran pemasok mana yang sekarang lewat bank lain, dan apa alasannya?')
    return {'ringkasan': ringkasan, 'keuangan': keu, 'risiko': risiko, 'anomali': anom, 'jaringan': jar, 'rekomendasi': rek or ['Lengkapi profil nasabah.'], 'pertanyaan': tanya}


def company_narrative(fp):
    """Narasi per bagian. Mengembalikan (dict, mode, info_validasi)."""
    base = template_company(fp)
    prompt = ('Tulis ringkasan eksekutif nasabah untuk RM. Kunci JSON: ringkasan (4–6 kalimat), keuangan (2–4 kalimat, bandingkan dengan median peer), '
              'risiko (2–3 kalimat), anomali (2–3 kalimat), jaringan (2–3 kalimat), rekomendasi (daftar 3–4 butir yang bisa dikerjakan), '
              'pertanyaan (daftar 2 pertanyaan pembuka). Format angka gaya Indonesia (koma desimal).\n\nFAKTA:\n' + _facts_json(fp))
    out = complete_json(prompt, R.NARRATIVE_KEYS)
    if not out:
        return base, 'template', None
    narr = {k: out.get(k) or base[k] for k in R.NARRATIVE_KEYS}
    for k in ('rekomendasi', 'pertanyaan'):
        if isinstance(narr[k], str):
            narr[k] = [x.strip('-• ') for x in narr[k].split('\n') if x.strip()]
    bad_keys = []
    for k in R.NARRATIVE_KEYS:     # validasi per bagian: bagian dengan angka asing diganti template
        _, bad = R.check_numbers({k: narr[k]}, fp)
        if bad:
            bad_keys.append((k, bad)); narr[k] = base[k]
    return narr, 'LLM', bad_keys


def visit_extract(note, products):
    """Catatan bebas → isian log aksi. LLM bila ada, aturan kata kunci bila tidak."""
    out = complete_json(f"Ekstrak dari catatan kunjungan RM berikut. Produk yang mungkin: {', '.join(products)}.\nCATATAN: {note}",
                        ['respons', 'produk', 'keberatan', 'langkah_berikut'],
                        system=SYSTEM + " Respons harus salah satu: Converted, Interested, Not interested, No response.")
    if out and out.get('respons') in ('Converted', 'Interested', 'Not interested', 'No response'):
        return out, 'LLM'
    t = note.lower()
    resp = 'Converted' if any(w in t for w in ('setuju', 'onboarding', 'aktif', 'tanda tangan')) else \
           'Not interested' if any(w in t for w in ('tidak tertarik', 'belum butuh', 'belum ada kebutuhan', 'menolak')) else \
           'No response' if any(w in t for w in ('tidak dapat dihubungi', 'tidak ada respons', 'tidak di tempat')) else 'Interested'
    prod = next((p for p in products if p.lower() in t), products[0] if products else '')
    keb = 'biaya' if 'biaya' in t or 'mahal' in t else ('sudah di bank lain' if 'bank lain' in t else '')
    nxt = 'kirim simulasi' if 'simulasi' in t else ('kirim proposal' if 'proposal' in t else 'jadwalkan tindak lanjut')
    return {'respons': resp, 'produk': prod, 'keberatan': keb, 'langkah_berikut': nxt}, 'template'


def draft_message(kind, ctx: dict):
    prompts = {'janji': 'Tulis pesan WhatsApp singkat dan sopan dari RM untuk membuat janji kunjungan.',
               'intro': 'Tulis pesan WhatsApp singkat dan sopan dari RM kepada nasabahnya, meminta bantuan memperkenalkan bank kepada mitra usaha mereka.'}
    txt = complete(prompts[kind] + ' Maksimal 3 kalimat, tanpa angka yang tidak ada di konteks.\nKONTEKS: ' + json.dumps(ctx, ensure_ascii=False), max_tokens=300)
    if txt:
        return txt.strip(), 'LLM'
    if kind == 'janji':
        return (f"Selamat pagi Bapak/Ibu di {ctx.get('nama')}, saya {ctx.get('rm')} dari BNI. Saya ingin berkunjung {ctx.get('waktu', 'minggu ini')} "
                f"untuk membahas {ctx.get('topik', 'kebutuhan layanan perusahaan')}. Apakah waktu tersebut sesuai?"), 'template'
    return (f"Selamat pagi Bapak/Ibu di {ctx.get('perantara')}, terima kasih atas kerja samanya selama ini. Kami ingin berkenalan dengan "
            f"{ctx.get('prospect')}, mitra usaha Bapak/Ibu. Apakah berkenan membantu memperkenalkan kami?"), 'template'


# ---------------------------------------------------------------- tool use (agen)
def run_tools(system, user_msg, tools, executor, max_steps=10):
    """Loop agen dengan tool use. tools = [{'name','description','parameters'(JSON schema)}].
    executor(name, args) → hasil (dict/str). Mengembalikan (jawaban, jejak) atau (None, []) bila LLM tidak tersedia."""
    cl, cfg = _client()
    if cl is None:
        return None, []
    trace = []
    try:
        if cfg['provider'] == 'anthropic':
            msgs = [{'role': 'user', 'content': user_msg}]
            tl = [{'name': t['name'], 'description': t['description'], 'input_schema': t['parameters']} for t in tools]
            for _ in range(max_steps):
                r = cl.messages.create(model=cfg['model'], max_tokens=1500, system=system, tools=tl, messages=msgs)
                calls = [b for b in r.content if b.type == 'tool_use']
                if not calls:
                    return ''.join(b.text for b in r.content if b.type == 'text'), trace
                msgs.append({'role': 'assistant', 'content': r.content})
                res = []
                for c in calls:
                    out = executor(c.name, c.input); trace.append((c.name, c.input, out))
                    res.append({'type': 'tool_result', 'tool_use_id': c.id, 'content': json.dumps(out, ensure_ascii=False, default=str)[:6000]})
                msgs.append({'role': 'user', 'content': res})
        else:
            msgs = [{'role': 'system', 'content': system}, {'role': 'user', 'content': user_msg}]
            tl = [{'type': 'function', 'function': {'name': t['name'], 'description': t['description'], 'parameters': t['parameters']}} for t in tools]
            for _ in range(max_steps):
                r = cl.chat.completions.create(model=cfg['model'], messages=msgs, tools=tl, max_tokens=1500)
                m = r.choices[0].message
                if not m.tool_calls:
                    return m.content, trace
                msgs.append({'role': 'assistant', 'content': m.content or '', 'tool_calls': [tc.model_dump() for tc in m.tool_calls]})
                for tc in m.tool_calls:
                    args = json.loads(tc.function.arguments or '{}')
                    out = executor(tc.function.name, args); trace.append((tc.function.name, args, out))
                    msgs.append({'role': 'tool', 'tool_call_id': tc.id, 'content': json.dumps(out, ensure_ascii=False, default=str)[:6000]})
        return 'Batas langkah agen tercapai; ringkasan di atas dibuat dari langkah yang sudah selesai.', trace
    except Exception as e:
        complete.last_error = str(e)
        return None, trace
