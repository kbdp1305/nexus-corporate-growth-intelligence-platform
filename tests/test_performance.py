"""Checks for performance scope, conversion counting and period boundaries."""
from pathlib import Path
import sys
import unittest

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from egi import performance as P


class PerformanceTests(unittest.TestCase):
    def history(self):
        rows = [
            ('A', 'P1', '2026-05-20', 'Converted', 1, 1000, 'RM-001'),
            ('A', 'P1', '2026-06-01', 'Converted', 1, 0, 'RM-001'),
            ('A', 'P1', '2026-06-02', 'Interested', 0, 0, 'RM-001'),
            ('A', 'P2', '2026-06-03', 'Interested', 0, 0, 'RM-001'),
            ('A', 'P2', '2026-06-03', 'Converted', 1, 500, 'RM-001'),
            ('B', 'P3', '2026-05-01', 'Interested', 0, 0, 'RM-001'),
            ('C', 'P1', '2026-06-30', 'Interested', 0, 0, 'RM-001'),
            ('D', 'P1', '2026-06-01', 'Converted', 1, 99999, 'RM-002'),
        ]
        frame = pd.DataFrame(rows, columns=['party_id', 'product_id', 'contact_date', 'response',
                                           'converted', 'deal_value_idr_mn', 'rm_id'])
        return P.contacts(frame, 'RM-001')

    def test_period_metrics_and_unique_conversion(self):
        result = P.metrics(self.history(), '2026-06-01', '2026-06-30')
        self.assertEqual(result, {'companies': 2, 'contacts': 5, 'conversions': 1, 'deal_bn': .5})

    def test_pipeline_history_and_same_date_order(self):
        pipe = P.pipeline(self.history(), '2026-06-30')
        self.assertEqual(list(pipe.party_id), ['B', 'C'])
        self.assertEqual(list(pipe.hari_menunggu), [60, 0])
        # As-of date must not see a later conversion.
        before = P.pipeline(self.history(), '2026-06-02')
        self.assertEqual(list(before.party_id), ['B'])

    def test_empty_period_and_rm(self):
        frame = self.history()
        self.assertEqual(P.metrics(frame, '2026-07-01', '2026-07-31')['contacts'], 0)
        empty = P.contacts(frame, 'RM-999')
        self.assertTrue(P.pipeline(empty, '2026-07-31').empty)

    def page(self, role='rm'):
        app = AppTest.from_file(str(ROOT / 'app/app.py'), default_timeout=30)
        app.session_state['user'] = {'username':'perf-test', 'nama':'Test', 'role':role,
                                     'rm_id':'RM-001' if role == 'rm' else 'Semua RM'}
        app.session_state['rm'] = 'Semua RM'
        app.run()
        return app.switch_page('views/7_kinerja.py').run()

    def test_rm_filters_and_removed_comparisons(self):
        app = self.page()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['rm'], 'RM-001')
        self.assertFalse(any('Peringkat' in x.value or 'median RM' in x.value for x in app.markdown))
        app.selectbox(key='perf_month').select('2026-07').run()
        self.assertFalse(app.exception)
        self.assertTrue(any('Belum ada catatan kontak' in x.value for x in app.info))
        app.selectbox(key='perf_period').select('Rentang tanggal').run()
        app.date_input(key='perf_dates').set_value((pd.Timestamp('2026-01-01').date(),
                                                   pd.Timestamp('2026-06-30').date())).run()
        self.assertFalse(app.exception)

    def test_supervisor_all_rm_stops(self):
        app = self.page('supervisor')
        self.assertFalse(app.exception)
        self.assertTrue(any('Pilih satu RM' in x.value for x in app.info))
        self.assertFalse(app.get('plotly_chart'))

    def test_progress_navigation(self):
        app = self.page()
        app.button(key='perf_progress').click().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['tl_sel'], 'Progress kegiatan')


if __name__ == '__main__':
    unittest.main()
