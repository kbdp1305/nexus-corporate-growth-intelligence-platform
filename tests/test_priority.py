"""Priority queue scope, sorting, selection, and ownership checks."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from egi import data  # noqa: E402


class PriorityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = data.get_store()

    def queue(self, role='rm'):
        app = AppTest.from_file(str(ROOT / 'app/app.py'), default_timeout=30)
        app.session_state['user'] = {'username': 'priority-test', 'nama': 'Test', 'role': role,
                                     'rm_id': 'RM-001' if role == 'rm' else 'Semua RM'}
        app.session_state['rm'] = 'Semua RM'
        app.run()
        app.switch_page('views/2_prioritas.py').run()
        return app

    def select_first(self, app):
        table = app.dataframe[0]
        cid = table.value.iloc[0].company_id
        app.session_state[table.key] = {'selection': {'rows': [0], 'columns': []}}
        app.run()
        self.assertFalse(app.exception)
        return cid

    def test_scope_score_and_explicit_selection(self):
        app = self.queue()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['rm'], 'RM-001')
        table = app.dataframe[0].value
        allowed = set(self.store.portfolio('RM-001').index)
        self.assertLessEqual(set(table.company_id), allowed)
        self.assertTrue(table.score.between(0, 100).all())
        self.assertFalse(any(b.label == 'Jadwalkan' for b in app.button))
        cid = self.select_first(app)
        self.assertTrue(any(b.key == f'priority_schedule_{cid}' for b in app.button))
        self.assertTrue(any(m.label == 'Probabilitas konversi' and '%' in m.value for m in app.metric))
        values = app.dataframe[0].value
        expected = self.store.opp.loc[values.company_id, 'p_convert'].to_numpy() * 100
        self.assertTrue((values.probabilitas_konversi.to_numpy() == expected).all())

    def test_sort_resets_selection_and_matches_metric(self):
        app = self.queue()
        self.select_first(app)
        next(g for g in app.get('button_group') if g.key == 'priority_sort').set_value('Estimasi nilai').run()
        self.assertFalse(app.exception)
        table = app.dataframe[0].value
        scores = self.store.opp.loc[table.company_id, 'ev_idr_mn']
        self.assertTrue(scores.is_monotonic_decreasing)
        self.assertFalse(any(b.label == 'Jadwalkan' for b in app.button))

    def test_filters_and_empty_queue(self):
        app = self.queue()
        app.selectbox(key='priority_status').select('Belum Dihubungi').run()
        self.assertFalse(app.exception)
        if app.dataframe:
            self.assertTrue((app.dataframe[0].value.status == 'Belum Dihubungi').all())
        with patch('egi.agent.candidates', return_value=pd.DataFrame()):
            app = self.queue()
            self.assertFalse(app.exception)
            self.assertFalse(app.dataframe)
            self.assertTrue(any('Tidak ada perusahaan' in i.value for i in app.info))

    def test_supervisor_and_prospect_selection(self):
        app = self.queue('supervisor')
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['rm'], 'Semua RM')
        next(g for g in app.get('button_group') if g.key == 'priority_mode').set_value('Prospect').run()
        self.assertFalse(app.exception)
        self.assertTrue(app.dataframe)
        self.assertFalse(any(s.key == 'priority_segment' for s in app.selectbox))
        self.assertEqual(len(app.dataframe[0].value), len(self.store.acq))
        self.select_first(app)
        self.assertTrue(any(b.label == 'Buat Draf Permintaan Perkenalan' for b in app.button))

    def test_network_default_order_and_draft(self):
        app = self.queue()
        next(g for g in app.get('button_group') if g.key == 'priority_mode').set_value('Prospect').run()
        self.assertEqual(app.selectbox(key='priority_prospect_sort').value, 'Nilai relasi')
        table = app.dataframe[0].value
        self.assertTrue(table.nilai_relasi.is_monotonic_decreasing)
        self.assertNotIn('probabilitas_konversi', table.columns)
        cid = self.select_first(app)
        with patch('egi.llm.draft_message', return_value=('Halo, mohon perkenalan dengan PIC perusahaan.', 'template')) as draft:
            next(b for b in app.button if b.key == f'priority_intro_{cid}').click().run()
            self.assertFalse(app.exception)
            self.assertEqual(draft.call_args.args[0], 'intro')
        self.assertTrue(any('mohon perkenalan' in t.value for t in app.text_area))

    def test_profile_intro_opens_integrated_queue(self):
        app = self.queue()
        net = self.store.prospects_for('RM-001')
        cid = net.index[0]
        app.session_state['priority_requested'] = cid
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['priority_mode'], 'Prospect')
        self.assertTrue(any(b.key == f'priority_schedule_{cid}' for b in app.button))

    def test_profile_network_link_redirects_to_selected_prospect(self):
        app = self.queue()
        anchor = self.store.prospects_for('RM-001').iloc[0].lewat[0]
        app.query_params['company'] = anchor
        app.switch_page('views/3_profil.py').run()
        self.assertFalse(app.exception)
        button = next(b for b in app.button if b.key and b.key.startswith('intro_'))
        cid = button.key.removeprefix('intro_')
        button.click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['priority_mode'], 'Prospect')
        self.assertTrue(any(b.key == f'priority_schedule_{cid}' for b in app.button))

    def test_other_rm_claim_disables_schedule(self):
        net = self.store.prospects_for('RM-001')
        cid = next(c for c in net.index if c in self.store.acq.index)
        with patch('egi.kalender.claims', return_value={cid: 'RM-002'}):
            app = self.queue()
            next(g for g in app.get('button_group') if g.key == 'priority_mode').set_value('Prospect').run()
            app.checkbox(key='priority_hide_other').uncheck()
            app.run()
            self.assertFalse(app.exception)
            table = app.dataframe[0]
            index = table.value.index[table.value.company_id == cid][0]
            app.session_state[table.key] = {'selection': {'rows': [int(index)], 'columns': []}}
            app.run()
            self.assertFalse(app.exception)
            button = next(b for b in app.button if b.key == f'priority_schedule_{cid}')
            self.assertTrue(button.disabled)


if __name__ == '__main__':
    unittest.main()
