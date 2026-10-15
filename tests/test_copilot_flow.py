"""Copilot context, failed actions, latest contact history, and scope regressions."""
from datetime import timedelta
from pathlib import Path
import sys
import unittest
import tempfile
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from egi import data, agent, copilot_flow as flow, profile_workspace as PW  # noqa: E402
import reports as R


class CopilotFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.store = data.get_store()
        cls.cid = cls.store.portfolio('RM-001').index[0]

    def page(self, task='chat', supervisor=False):
        app = AppTest.from_file(str(ROOT / 'app/app.py'), default_timeout=30)
        app.session_state['user'] = {'username': 'copilot-test', 'nama': 'Test',
                                     'role': 'supervisor' if supervisor else 'rm', 'rm_id': 'Semua RM' if supervisor else 'RM-001'}
        app.session_state['rm'] = 'RM-001'
        app.run()
        app.session_state['copilot_task'] = task
        app.switch_page('views/6_copilot.py').run()
        self.assertFalse(app.exception)
        return app

    def proposal(self):
        return {'id': 'A1', 'tipe': 'rencana', 'company_id': self.cid, 'nama': 'Test Company',
                'status': 'menunggu', 'catatan': 'Konfirmasi kebutuhan', '_rm': 'RM-001'}

    def test_failed_schedule_not_marked_approved(self):
        app = self.page()
        app.session_state['chat'] = [{'role': 'assistant', 'text': 'Usulan jadwal', 'usulan': [self.proposal()]}]
        app.run()
        with patch('egi.kalender.schedule', return_value=('gagal', 'Tidak ada slot kosong')), patch('egi.data.audit'):
            app.button(key='ok_0_A1').click().run()
        self.assertFalse(app.exception)
        proposal = app.session_state['chat'][0]['usulan'][0]
        self.assertEqual(proposal['status'], 'gagal')
        self.assertEqual(proposal['hasil'], 'Tidak ada slot kosong')

    def test_successful_schedule_preserves_actual_result(self):
        app = self.page()
        app.session_state['chat'] = [{'role': 'assistant', 'text': 'Usulan jadwal', 'usulan': [self.proposal()]}]
        app.run()
        with patch('egi.kalender.schedule', return_value=('baru', {'mulai': '2026-10-20T09:00'})), patch('egi.data.audit'):
            app.button(key='ok_0_A1').click().run()
        self.assertFalse(app.exception)
        proposal = app.session_state['chat'][0]['usulan'][0]
        self.assertEqual(proposal['status'], 'disetujui')
        self.assertIn('Jadwal tersimpan', proposal['hasil'])

    def test_old_week_plan_hidden(self):
        app = self.page('plan')
        week = app.date_input(key='copilot_plan_week').value
        app.session_state['agent_result'] = ('plan', {'rm': 'RM-001', 'minggu_mulai': (week - timedelta(days=7)).isoformat()})
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(any(b.label == 'Setujui rencana' for b in app.button))
        self.assertTrue(any('minggu rencana telah berubah' in i.value for i in app.info))
        self.assertFalse(flow.plan_matches({'rm': 'RM-002', 'minggu_mulai': week.isoformat()}, 'RM-001', week))

    def test_partial_plan_is_reported_as_partial(self):
        app = self.page('plan')
        week = app.date_input(key='copilot_plan_week').value
        plan = {'rm': 'RM-001', 'minggu_mulai': week.isoformat(), 'minggu': 'minggu rencana', 'portofolio': 'Test',
                'status': 'draf', 'ringkasan': 'Rencana uji', 'kpi': [('Aksi', '1', '')],
                'hari': [{'hari': 'Selasa', 'kanal': 'Telepon', 'tema': 'Konfirmasi', 'item': [self.item(self.cid)]}], 'pesan': [], 'jejak': []}
        app.session_state['agent_result'] = ('plan', plan)
        app.run()
        self.assertFalse(app.exception)
        with tempfile.TemporaryDirectory() as directory, patch('egi.data.APP_OUT', Path(directory)), \
             patch('egi.data.audit'), \
             patch('egi.kalender.fit_free', side_effect=lambda rows, rm: rows), \
             patch('egi.kalender.upsert', return_value=(1, 0, [('other', 'Bentrok jadwal')])):
            next(b for b in app.button if b.label == 'Setujui rencana').click().run()
        self.assertFalse(app.exception)
        self.assertIn('Bentrok jadwal', app.session_state['plan_to_cal'])
        self.assertTrue(any('Bentrok jadwal' in w.value for w in app.warning))

    def item(self, cid):
        return {'id': cid, 'nama': self.store.co.loc[cid, 'name'], 'jam': '09.00', 'info': 'Test',
                'tujuan': 'Konfirmasi kebutuhan', 'peluang': '30%', 'siapkan': 'Ringkasan'}

    def test_four_tasks_and_review_submodes(self):
        app = self.page()
        tasks = next(g for g in app.get('button_group') if g.key == 'task_sel')
        self.assertEqual(tasks.options, ['Tanya Copilot', 'Siapkan Bahan Kunjungan', 'Tinjau Temuan', 'Susun Rencana'])
        tasks.set_value('Tinjau Temuan').run()
        self.assertFalse(app.exception)
        app.radio(key='copilot_review_mode').set_value('Analisis Perusahaan').run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['copilot_task'], 'alarm')

    def test_chat_answer_format_unchanged(self):
        app = self.page()
        answer = 'Jawaban asli tetap utuh.\n\n- Fakta pertama\n- Fakta kedua'
        app.session_state['chat'] = [{'role': 'assistant', 'text': answer}]
        app.run()
        self.assertFalse(app.exception)
        self.assertTrue(any(m.value == answer for m in app.markdown))

    def test_only_selected_plan_items_are_saved(self):
        app = self.page('plan')
        week = app.date_input(key='copilot_plan_week').value
        second = self.store.portfolio('RM-001').index[1]
        plan = {'rm': 'RM-001', 'minggu_mulai': week.isoformat(), 'minggu': 'minggu rencana', 'portofolio': 'Test',
                'status': 'draf', 'ringkasan': 'Dua usulan', 'kpi': [('Aksi', '2', '')], 'pesan': [], 'jejak': [],
                'hari': [{'hari': 'Selasa', 'kanal': 'Telepon', 'tema': 'Konfirmasi', 'item': [self.item(self.cid), self.item(second)]}]}
        app.session_state['agent_result'] = ('plan', plan)
        app.run()
        self.assertFalse(app.exception)
        next(c for c in app.checkbox if c.key and c.key.startswith('plan_item_') and c.key.endswith(second)).uncheck().run()
        with tempfile.TemporaryDirectory() as directory, patch('egi.data.APP_OUT', Path(directory)), patch('egi.data.audit'), \
             patch('egi.kalender.fit_free', side_effect=lambda rows, rm: rows), \
             patch('egi.kalender.upsert', return_value=(1, 0, [])) as save:
            next(b for b in app.button if b.label == 'Setujui rencana').click().run()
        self.assertFalse(app.exception)
        self.assertEqual([r['company_id'] for r in save.call_args.args[0]], [self.cid])

    def test_rm_change_clears_chat_and_plan(self):
        app = self.page(supervisor=True)
        app.session_state['chat'] = [{'role': 'assistant', 'text': 'Konteks RM sebelumnya'}]
        app.session_state['agent_result'] = ('plan', {'rm': 'RM-001'})
        app.session_state['week_plan_ctx'] = {'plan': {'rm': 'RM-001'}}
        next(s for s in app.selectbox if s.label == 'Lihat sebagai').select('RM-002').run()
        self.assertFalse(app.exception)
        self.assertEqual(app.session_state['chat'], [])
        self.assertIsNone(app.session_state['agent_result'])
        self.assertIsNone(app.session_state['week_plan_ctx'])

    def test_latest_dashboard_contact_in_facts_and_brief(self):
        original = self.store.log_all
        latest = original.iloc[0].copy()
        latest['party_id'] = self.cid
        latest['contact_date'] = '2026-10-14'
        latest['feedback_note'] = 'Catatan dashboard terbaru untuk bahan kunjungan'
        with patch.object(self.store, 'log_all', pd.concat([original, pd.DataFrame([latest])], ignore_index=True)):
            self.assertEqual(R.fact_pack(self.store, self.cid)['kunjungan'][-1]['catatan'], latest['feedback_note'])
            app = self.page('brief')
            app.session_state['focus_company'] = self.cid
            app.run()
            self.assertFalse(app.exception)
            self.assertTrue(any(latest['feedback_note'] in m.value for m in app.markdown))

    def test_executor_and_brief_reject_outside_scope(self):
        user = {'role': 'rm', 'rm_id': 'RM-001'}
        allowed = PW.accessible_ids(self.store, user)
        outside = next(cid for cid in self.store.co.index if cid not in allowed)
        execute = agent.make_executor(self.store, 'RM-001')
        self.assertIn('error', execute('company_facts', {'company_id': outside}))
        found = execute('search_company', {'query': outside})
        self.assertEqual(found['jumlah'], 0)
        app = self.page('brief')
        app.session_state['focus_company'] = outside
        app.run()
        self.assertFalse(app.exception)
        self.assertIsNone(app.session_state['focus_company'])
        choices = next(s for s in app.selectbox if s.label == 'Perusahaan').options
        self.assertFalse(any(outside in choice for choice in choices))

    def test_proposal_guard_does_not_shadow_guardrail_module(self):
        proposals = []
        execute = agent.make_executor(self.store, 'RM-001', proposals)
        result = execute('propose_message', {'company_id': self.cid, 'jenis': 'janji', 'isi': 'Konfirmasi waktu pertemuan.'})
        self.assertNotIn('error', result)
        self.assertEqual(len(proposals), 1)


if __name__ == '__main__':
    unittest.main()
