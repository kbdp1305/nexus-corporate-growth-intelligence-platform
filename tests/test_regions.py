"""Penetration semantics, map layers, and account-scoped drill-downs."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from egi import data, profile_workspace as PW, region_hover, regions  # noqa: E402


class RegionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = data.get_store()

    def page(self, role='rm', view='Semua RM'):
        app = AppTest.from_file(str(ROOT / 'app/app.py'), default_timeout=30)
        app.session_state['user'] = {'username': 'region-test', 'nama': 'Test', 'role': role,
                                     'rm_id': 'RM-001' if role == 'rm' else 'Semua RM'}
        app.session_state['rm'] = view
        app.run()
        app.switch_page('views/4_wilayah.py').run()
        return app

    def test_denominator_and_no_data(self):
        co = self.store.cox
        stats = regions.aggregate(self.store, co)
        district = co.district.iloc[0]
        local = co[co.district == district]
        self.assertEqual(stats.loc[district, 'perusahaan'], len(local))
        self.assertAlmostEqual(stats.loc[district, 'penetrasi'], local.is_client.sum() / len(local))
        empty = regions.aggregate(self.store, co.iloc[:0])
        self.assertTrue(empty.penetrasi.isna().all())
        self.assertTrue((empty.perusahaan == 0).all())
        self.assertEqual(regions.penetration_color(float('nan')), regions.NO_DATA)

    def test_fixed_color_and_no_white_space_dependency(self):
        co = self.store.cox
        stats = regions.aggregate(self.store, co)
        empty_points = co.iloc[:0]
        deck = json.loads(regions.map_deck(stats, self.store.shapes, empty_points).to_json())
        colors = {}
        for layer in deck['layers']:
            self.assertNotIn('white_space', layer['id'])
            for obj in layer['data']:
                colors[obj['district']] = obj['fill']
        district = stats.index[0]
        expected = regions.penetration_color(stats.loc[district, 'penetrasi'])
        self.assertEqual(colors[district], expected)
        subset = stats.loc[[district]]
        deck = json.loads(regions.map_deck(subset, self.store.shapes, empty_points).to_json())
        self.assertEqual(deck['layers'][0]['data'][0]['fill'], expected)

    def test_rm_explicit_selection_and_scoped_actions(self):
        app = self.page()
        self.assertFalse(app.exception)
        self.assertFalse(app.slider)
        self.assertFalse(any(b.key and b.key.startswith('region_profile_') for b in app.button))
        district = self.store.co.loc[self.store.co.rm_id == 'RM-001', 'district'].iloc[0]
        pick = next(s for s in app.selectbox if s.label == 'Pilih wilayah untuk melihat peluang')
        pick.select(district).run()
        self.assertFalse(app.exception)
        allowed = PW.accessible_ids(self.store, dict(app.session_state['user']))
        ids = [b.key.removeprefix('region_profile_') for b in app.button if b.key and b.key.startswith('region_profile_')]
        self.assertTrue(ids)
        self.assertLessEqual(set(ids), allowed)
        app.selectbox(key='region_segment').select('S1 Kecil').run()
        self.assertFalse(app.exception)
        ids = [b.key.removeprefix('region_profile_') for b in app.button if b.key and b.key.startswith('region_profile_')]
        self.assertTrue(all(not self.store.cox.loc[cid, 'is_client'] or self.store.cox.loc[cid, 'segment'] == 'S1 Kecil' for cid in ids))

    def test_supervisor_and_layer_controls(self):
        app = self.page('supervisor')
        self.assertFalse(app.exception)
        app.checkbox(key='region_clients').uncheck()
        app.checkbox(key='region_prospects').uncheck()
        app.checkbox(key='region_branches').uncheck()
        app.run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['rm'], 'Semua RM')

    def test_supervisor_view_as_rm_counts_only_that_rm(self):
        for role, view in [('rm', 'Semua RM'), ('supervisor', 'RM-001')]:
            app = self.page(role, view)
            self.assertFalse(app.exception)
            label = 'Nasabah Saya' if role == 'rm' else 'Nasabah RM-001'
            self.assertEqual(app.checkbox(key='region_clients').label, label)
            table = app.dataframe[0].value
            own = self.store.cox[self.store.cox.is_client & self.store.cox.rm_id.eq('RM-001')]
            self.assertNotIn('nasabah', table.columns)
            self.assertEqual(int(table.nasabah_saya.sum()), len(own))

    def test_segment_filter_keeps_prospects_and_penetration(self):
        with patch('egi.region_hover.render', return_value=None) as render:
            app = self.page('supervisor')
            original = render.call_args.args[0]
            app.selectbox(key='region_segment').select('S1 Kecil').run()
            self.assertFalse(app.exception)
            filtered = render.call_args.args[0]
        self.assertEqual({c['id'] for c in original['companies'] if not c['client']},
                         {c['id'] for c in filtered['companies'] if not c['client']})
        self.assertTrue(all(c['segment'] == 'S1 Kecil' for c in filtered['companies'] if c['client']))
        self.assertEqual(original['regions'], filtered['regions'])

    def test_map_company_selection_uses_visible_ids(self):
        co = self.store.cox[self.store.cox.rm_id == 'RM-001']
        stats = regions.aggregate(self.store, self.store.cox)
        cid = co.index[0]
        event = {'selection': {'objects': {'perusahaan_relevan': [{'company_id': cid}]}}}
        self.assertEqual(regions.company_selection(event, stats, co), (co.loc[cid, 'district'], cid))
        outside = next(c for c in self.store.cox.index if c not in co.index)
        event['selection']['objects']['perusahaan_relevan'][0]['company_id'] = outside
        self.assertEqual(regions.company_selection(event, stats, co), (None, None))
        deck = json.loads(regions.map_deck(stats, self.store.shapes, co, selected_company=cid).to_json())
        layer = next(layer for layer in deck['layers'] if layer['id'] == 'perusahaan_relevan')
        self.assertEqual({r['company_id'] for r in layer['data']}, set(co.index))
        self.assertEqual(next(r['radius'] for r in layer['data'] if r['company_id'] == cid), 180)

    def test_hover_detail_navigation(self):
        cid = self.store.co.index[self.store.co.rm_id == 'RM-001'][0]
        with patch('egi.region_hover.render', return_value={'action': 'company', 'company_id': cid, 'nonce': 1}):
            app = self.page()
        self.assertFalse(app.exception)
        self.assertEqual(app.query_params['company'], cid)
        self.assertTrue(app.tabs)

    def test_hover_payload_potential_and_scope(self):
        co = self.store.cox[self.store.cox.rm_id == 'RM-001']
        stats = regions.aggregate(self.store, self.store.cox)
        payload = region_hover.payload(self.store, stats, co, None, {})
        self.assertEqual({c['id'] for c in payload['companies']}, set(co.index))
        for company in payload['companies']:
            self.assertEqual(company['potential'], company['score'] is not None and company['score'] >= 75)
            expected = self.store.opp.loc[company['id'], 'p_convert'] * 100
            self.assertAlmostEqual(company['conversion'], expected)
        self.assertFalse(payload['branches'])
        prospects = self.store.cox[self.store.cox.customer_type == 'Prospect'].head(2)
        payload = region_hover.payload(self.store, stats, prospects, None, {})
        self.assertTrue(all(c['conversion'] is None for c in payload['companies']))

    def test_signal_categories_latest_record_and_period(self):
        alerts = pd.DataFrame([
            {'company_id': 'C1', 'event_type': 'distress', 'ym': '2026-05', 'score': .9, 'reason': 'Old'},
            {'company_id': 'C1', 'event_type': 'distress', 'ym': '2026-06', 'score': .8, 'reason': 'Latest'},
            {'company_id': 'C1', 'event_type': 'expansion', 'ym': '2026-06', 'score': .7, 'reason': 'Expansion'},
            {'company_id': 'C1', 'event_type': 'spike', 'ym': '2026-06', 'score': .6, 'reason': 'Spike'},
            {'company_id': 'C1', 'event_type': 'buyer_exit', 'ym': '2026-07', 'score': .99, 'reason': 'Future'}])
        with patch.object(self.store, 'why_now', return_value=alerts):
            signals = region_hover.company_signals(self.store, ['C1'])['C1']
        self.assertEqual(len(signals), 3)
        self.assertEqual({s['category'] for s in signals}, {'risk', 'momentum', 'other'})
        self.assertEqual(next(s['reason'] for s in signals if s['type'] == 'distress'), 'Latest')
        self.assertTrue(all(s['month'] <= data.REF_MONTH for s in signals))


if __name__ == '__main__':
    unittest.main()
