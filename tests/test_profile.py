"""Profil 360 role scopes, company details, and interactive drill-downs."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from egi import data, profile_workspace as PW  # noqa: E402


class ProfileTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = data.get_store()
        cls.user = {'username': 'profile-test', 'nama': 'Test', 'role': 'rm', 'rm_id': 'RM-001'}
        cls.cid = cls.store.portfolio('RM-001').index[0]

    def profile(self, role='rm', cid=None):
        app = AppTest.from_file(str(ROOT / 'app/app.py'), default_timeout=30)
        user = dict(self.user) if role == 'rm' else {**self.user, 'role': 'supervisor', 'rm_id': 'Semua RM'}
        app.session_state['user'] = user
        app.session_state['rm'] = user['rm_id']
        app.run()
        if cid:
            app.query_params['company'] = cid
        app.switch_page('views/3_profil.py').run()
        return app

    def test_rm_directory_scope_and_filters(self):
        app = self.profile()
        self.assertFalse(app.exception)
        cards = [b.key.removeprefix('profile_open_') for b in app.button if b.key and b.key.startswith('profile_open_')]
        self.assertTrue(cards)
        self.assertTrue(all(self.store.co.loc[cid, 'rm_id'] == 'RM-001' for cid in cards))
        scope = next(g for g in app.get('button_group') if g.key == 'profile_scope')
        self.assertNotIn('Seluruh bank', scope.options)
        app.selectbox(key='profile_risk').select('High').run()
        self.assertFalse(app.exception)
        cards = [b.key.removeprefix('profile_open_') for b in app.button if b.key and b.key.startswith('profile_open_')]
        self.assertTrue(all(self.store.cox.loc[cid, 'pred_class'] == 'High' for cid in cards))

    def test_other_rm_direct_url_is_blocked(self):
        allowed = PW.accessible_ids(self.store, self.user)
        other = next(cid for cid in self.store.co.index if cid not in allowed)
        app = self.profile(cid=other)
        self.assertFalse(app.exception)
        self.assertFalse(app.tabs)
        self.assertNotIn('company', app.query_params)
        self.assertTrue(any('di luar portofolio' in w.value for w in app.warning))

    def test_supervisor_can_open_other_company(self):
        other = next(cid for cid in self.store.co.index if self.store.co.loc[cid, 'rm_id'] != 'RM-001')
        app = self.profile('supervisor', other)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.tabs), 6)
        app = self.profile('supervisor')
        scope = next(g for g in app.get('button_group') if g.key == 'profile_scope')
        scope.set_value('Seluruh bank').run()
        self.assertFalse(app.exception)

    def test_detail_chart_range_and_partner_selection(self):
        app = self.profile(cid=self.cid)
        self.assertFalse(app.exception)
        self.assertIn('Peluang Produk', [t.label for t in app.tabs])
        ranges = next(g for g in app.get('button_group') if g.key == f'profile_cash_range_{self.cid}')
        ranges.set_value('3 bulan').run()
        self.assertFalse(app.exception)
        chart = next(c for c in app.get('plotly_chart') if c.proto.id.endswith(f'profile_cash_chart_{self.cid}'))
        self.assertLessEqual(len(json.loads(chart.proto.spec)['data'][0]['x']), 3)
        ego = self.store.ego(self.cid)
        if not ego.empty:
            partner = ego.iloc[0].id
            app.session_state[f'profile_network_{self.cid}'] = {'selection': {
                'points': [{'customdata': [partner]}], 'point_indices': [0], 'box': [], 'lasso': []}}
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any(partner in c.value for c in app.caption))

    def test_prospect_empty_states(self):
        allowed = PW.accessible_ids(self.store, self.user)
        prospect = next(cid for cid in allowed if self.store.co.loc[cid, 'customer_type'] == 'Prospect')
        app = self.profile(cid=prospect)
        self.assertFalse(app.exception)
        self.assertEqual(len(app.tabs), 6)
        self.assertTrue(any('rekomendasi produk' in i.value for i in app.info))

    def test_prospect_directory_has_no_segment_filter(self):
        app = self.profile()
        next(g for g in app.get('button_group') if g.key == 'profile_scope').set_value('Prospect Jaringan').run()
        self.assertFalse(app.exception)
        self.assertFalse(any(s.key == 'profile_segment' for s in app.selectbox))

    def test_timeline_combines_contact_agenda_feedback_and_activity(self):
        logs = pd.DataFrame([{'contact_date': '2026-06-01', 'channel': 'Telepon', 'response': 'Interested',
                              'product_id': 'P03', 'feedback_note': 'Minta proposal'}])
        calendar = pd.DataFrame([{'mulai': '2026-06-04T09:00', 'judul': 'Kunjungan CFO', 'kanal': 'Kunjungan',
                                  'catatan': 'Bahas proposal', 'status': 'Terjadwal'}])
        feedback = pd.DataFrame([{'tanggal': '2026-06-02', 'hasil': 'Interested', 'catatan': 'Siapkan proposal'}])
        activities = pd.DataFrame([{'status': 'Belum', 'selesai_pada': '', 'tenggat': '2026-06-03',
                                    'judul': 'Kirim proposal', 'aksi': 'Kirim ke CFO', 'pemilik': 'RM-001', 'status_tampil': 'berjalan'}])
        rows = PW.timeline(logs, calendar, activities, feedback)
        self.assertEqual(set(rows.jenis), {'Kontak', 'Agenda', 'Feedback', 'Kegiatan'})
        self.assertTrue(rows.waktu.is_monotonic_decreasing)
        self.assertEqual(rows.iloc[0].judul, 'Kunjungan CFO')

    def test_notes_approval_keeps_company_and_rm_context(self):
        app = self.profile(cid=self.cid)
        app.session_state['visit_draft'] = (self.cid, 'Telepon', 'Nasabah minta proposal',
            {'respons': 'Interested', 'produk': 'P03', 'keberatan': '', 'langkah_berikut': 'Kirim proposal'}, 'template')
        app.run()
        self.assertFalse(app.exception)
        with patch('egi.tindak.record_contact') as save, patch('egi.data.audit'):
            next(b for b in app.button if b.label == 'Setujui & simpan ke log').click().run()
            self.assertFalse(app.exception)
            row = save.call_args.args[1]
            self.assertEqual(row['party_id'], self.cid)
            self.assertEqual(row['rm_id'], 'RM-001')
            self.assertEqual(row['track'], 'Deepening')


if __name__ == '__main__':
    unittest.main()
