"""Overview scope and interaction checks against the dashboard's real data."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from egi import data, tindak, ui  # noqa: E402


class OverviewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = data.get_store()

    def dashboard(self, role='rm'):
        app = AppTest.from_file(str(ROOT / 'app/app.py'), default_timeout=30)
        app.session_state['user'] = {'username': 'overview-test', 'nama': 'Test',
                                     'role': role, 'rm_id': 'RM-001' if role == 'rm' else 'Semua RM'}
        # An RM must never inherit a previous supervisor's all-bank scope.
        app.session_state['rm'] = 'Semua RM'
        return app

    def scatter_ids(self, app):
        charts = [json.loads(c.proto.spec) for c in app.get('plotly_chart')]
        return {row[0] for chart in charts for trace in chart['data']
                if trace['type'] in ('scatter', 'scattergl') for row in trace.get('customdata', [])}

    def test_rm_sees_only_own_portfolio(self):
        app = self.dashboard().run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['rm'], 'RM-001')
        self.assertFalse(app.get('button_group'))
        allowed = set(self.store.co.index[self.store.co.rm_id == 'RM-001'])
        self.assertTrue(self.scatter_ids(app))
        self.assertLessEqual(self.scatter_ids(app), allowed)
        for chart in app.get('plotly_chart'):
            spec = json.loads(chart.proto.spec)
            for trace in spec['data']:
                if trace['type'] in ('scatter', 'scattergl') and trace.get('customdata'):
                    for row in trace['customdata']:
                        self.assertEqual(trace['marker']['color'], ui.SEG_COLOR[self.store.cox.loc[row[0], 'segment']])
            if chart.proto.id.endswith('ov_segment_pie'):
                trace = spec['data'][0]
                self.assertEqual(list(trace['marker']['colors']), [ui.SEG_COLOR[s] for s in trace['labels']])
        app.selectbox(key='ov_segment').select('S1 Kecil').run()
        self.assertFalse(app.exception)
        allowed &= set(self.store.cox.index[self.store.cox.segment == 'S1 Kecil'])
        self.assertLessEqual(self.scatter_ids(app), allowed)

    def test_supervisor_can_see_whole_bank(self):
        app = self.dashboard('supervisor').run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['rm'], 'Semua RM')
        self.assertTrue(app.get('button_group'))
        self.assertGreater(len(self.scatter_ids(app)), 100)
        app.get('button_group')[0].set_value('Portofolio RM').run()
        self.assertFalse(app.exception)
        app.selectbox(key='ov_rm').select('RM-001').run()
        self.assertFalse(app.exception)
        allowed = set(self.store.co.index[self.store.co.rm_id == 'RM-001'])
        self.assertLessEqual(self.scatter_ids(app), allowed)

    def test_empty_filter_combination(self):
        base = self.store.cox[self.store.cox.rm_id == 'RM-001']
        city, industry, segment = next(
            (city, industry, segment)
            for city in base.city.unique() for industry in base.industry.unique() for segment in data.SEGS
            if base[(base.city == city) & (base.industry == industry) & (base.segment == segment)].empty)
        app = self.dashboard().run()
        app.selectbox(key='ov_city').select(city)
        app.selectbox(key='ov_industry').select(industry)
        app.selectbox(key='ov_segment').select(segment)
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(self.scatter_ids(app))
        self.assertTrue(any('Tidak ada perusahaan' in i.value for i in app.info))

    def test_scatter_selection_shows_company_actions(self):
        app = self.dashboard().run()
        cid = sorted(self.scatter_ids(app))[0]
        app.session_state['ov_opportunities_RM-001'] = {
            'selection': {'points': [{'customdata': [cid]}], 'point_indices': [0], 'box': [], 'lasso': []}}
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any(b.key == f'p_ov_selected_{cid}' for b in app.button))

    def test_switch_composition_between_segment_and_industry(self):
        for role in ('rm', 'supervisor'):
            with self.subTest(role=role):
                app = self.dashboard(role).run()
                app.radio(key='ov_composition').set_value('Industri').run()
                self.assertFalse(app.exception)
                chart = next(c for c in app.get('plotly_chart') if c.proto.id.endswith('ov_industry_chart'))
                self.assertEqual(json.loads(chart.proto.spec)['data'][0]['type'], 'bar')
                industry = app.selectbox(key='ov_industry').options[1]
                app.selectbox(key='ov_industry').select(industry).run()
                self.assertFalse(app.exception)
                chart = next(c for c in app.get('plotly_chart') if c.proto.id.endswith('ov_industry_chart'))
                self.assertEqual(json.loads(chart.proto.spec)['data'][0]['y'], [industry])
                app.radio(key='ov_composition').set_value('Segmen').run()
                self.assertFalse(app.exception)
                self.assertTrue(any(c.proto.id.endswith('ov_segment_pie') for c in app.get('plotly_chart')))

    def test_progress_chart_and_status_filter(self):
        cid = self.store.co.index[self.store.co.rm_id == 'RM-001'][0]
        today = pd.Timestamp.now(tz='Asia/Bangkok').tz_localize(None).normalize()
        rows = []
        for status, offset in [('Belum', -2), ('Belum', 3), ('Selesai', -1), ('Dibatalkan', -1)]:
            row = {column: '' for column in tindak.KEGIATAN.cols}
            row.update(company_id=cid, rm_id='RM-001', status=status, judul='Tahap uji', aksi='Konfirmasi PIC',
                       tenggat=str((today + pd.Timedelta(days=offset)).date()), sisa_hari=offset,
                       status_tampil='berjalan')
            rows.append(row)
        with patch('egi.tindak.kegiatan_for', return_value=pd.DataFrame(rows)):
            app = self.dashboard().run()
            self.assertFalse(app.exception)
            pies = [json.loads(c.proto.spec) for c in app.get('plotly_chart')
                    if c.proto.id.endswith('ov_progress')]
            self.assertEqual(len(pies), 1)
            self.assertEqual(set(pies[0]['data'][0]['labels']), {'Berjalan', 'Terlambat', 'Selesai'})
            app.selectbox(key='ov_status').select('Terlambat').run()
            self.assertFalse(app.exception)
            table = next(d.value for d in app.dataframe if 'status_tampil' in d.value.columns)
            self.assertEqual(table.status_tampil.tolist(), ['Terlambat'])

    def test_this_week_agenda_list(self):
        cid = self.store.co.index[self.store.co.rm_id == 'RM-001'][0]
        today = pd.Timestamp.now(tz='Asia/Bangkok').tz_localize(None).normalize()
        start = today - pd.Timedelta(days=today.weekday()) + pd.Timedelta(hours=9)
        agenda = pd.DataFrame([{'id': 'overview-test-event', 'company_id': cid, 'judul': 'Kunjungan uji',
                                'mulai': start.isoformat(), '_m': start, 'kanal': 'Kunjungan', 'status': 'Terjadwal'},
                               {'id': 'next-week', 'company_id': cid, 'judul': 'Minggu depan',
                                'mulai': (start + pd.Timedelta(days=7)).isoformat(), '_m': start + pd.Timedelta(days=7),
                                'kanal': 'Email', 'status': 'Terjadwal'}])
        with patch('egi.kalender.active', return_value=agenda):
            app = self.dashboard().run()
            self.assertFalse(app.exception)
            self.assertTrue(any(b.key == 'ov_agenda_overview-test-event' for b in app.button))
            self.assertFalse(any(b.key == 'ov_agenda_next-week' for b in app.button))
            self.assertTrue(any('background:#E7EDF8' in m.value and 'Kunjungan' in m.value for m in app.markdown))
            self.assertFalse(any(c.proto.id.endswith('ov_agenda') for c in app.get('plotly_chart')))


if __name__ == '__main__':
    unittest.main()
