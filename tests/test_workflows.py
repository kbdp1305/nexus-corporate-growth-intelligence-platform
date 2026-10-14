"""Regression tests for account handoffs, validation and atomic workflows."""
from contextlib import ExitStack
from datetime import date, datetime, time, timedelta
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from egi import auth, data, kalender as K, performance as P, profile_workspace as PW, tindak as T


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.store = data.get_store()
        self.old_log = self.store.log_all.copy()
        self.tmp = tempfile.TemporaryDirectory()
        self.stack = ExitStack()
        self.actor = {'username':'rm-001','nama':'Audit','role':'rm','rm_id':'RM-001'}
        self.stack.enter_context(patch.object(auth, 'current', side_effect=lambda: self.actor))
        self.stack.enter_context(patch.object(data, 'APP_OUT', Path(self.tmp.name)))
        for table in (K.T, T.FEEDBACK, T.KEGIATAN, T.REQ):
            self.stack.enter_context(patch.object(table, 'file', Path(self.tmp.name) / table.file.name))
        self.cid = self.store.cox.index[(self.store.cox.rm_id == 'RM-001') & self.store.cox.is_client][0]
        self.day = date.today() + timedelta(days=7)
        while self.day.weekday() > 4:
            self.day += timedelta(days=1)
        self.m = datetime.combine(self.day, time(9))

    def tearDown(self):
        self.stack.close()
        self.store.log_all = self.old_log
        self.tmp.cleanup()

    def event(self, cid=None, id='visit', when=None, status='Terjadwal', rm='RM-001'):
        m = when or self.m
        row = dict(id=id, rm_id=rm, company_id=cid or self.cid, judul='Audit', kanal='Kunjungan',
                   mulai=m.isoformat(timespec='minutes'), selesai=(m+timedelta(hours=1)).isoformat(timespec='minutes'),
                   status=status, sumber='Manual')
        _, _, rejected = K.upsert([row], self.actor['username'])
        self.assertFalse(rejected)
        return row

    def feedback(self, event=None, divisions=(), activities=None):
        event = event or self.event(when=datetime.combine(date.today(),time(8)))
        if activities is None:
            activities = [dict(judul='Proposal', aksi='Kirim proposal', pemilik='RM',
                               divisi=list(divisions), tenggat_hari=7)]
        return T.save_feedback(self.store, event, hasil='Interested', produk=['P01','P02'], catatan='Audit feedback',
                               keberatan='', isu=[], langkah='Kirim proposal', lanjut=None, divs=list(divisions),
                               prioritas='Normal', tenggat=self.day, pesan_divisi='Audit request',
                               user=self.actor['username'], kegiatan=activities)

    def division(self, division):
        self.actor = dict(username='div-'+division,nama=division,role='divisi',rm_id=division)

    def finish_ticket(self, tid, division):
        self.division(division)
        T.reply(tid,self.actor['username'],'Diproses','Diproses')
        T.reply(tid,self.actor['username'],'Selesai','Selesai')

    def test_duration_validation_for_edit_and_completed(self):
        for status in ('Terjadwal','Selesai'):
            event=self.event(id=status,status=status)
            event['selesai']=event['mulai']
            _,_,reject=K.upsert([event],'rm-001')
            self.assertTrue(reject)
            self.assertNotEqual(K.load().set_index('id').loc[status,'selesai'],event['selesai'])

    def test_reschedule_clash_rolls_back(self):
        self.feedback()
        stage=T.KEGIATAN.load().iloc[0]
        target=self.m+timedelta(days=1,hours=4)
        self.event(id='busy',when=target)
        before=K.load().set_index('id').loc[stage.kal_id,'mulai']
        with self.assertRaises(ValueError):
            T.reschedule_kegiatan(stage.id,target.date(),'Audit','rm-001',jam=target.time())
        self.assertEqual(K.load().set_index('id').loc[stage.kal_id,'mulai'],before)
        self.assertEqual(T.KEGIATAN.load().set_index('id').loc[stage.id,'n_jadwal_ulang'],stage.n_jadwal_ulang)

    def test_ad_hoc_clash_rolls_back_order_and_calendar(self):
        self.feedback()
        stage=T.KEGIATAN.load().iloc[0]
        before=T.KEGIATAN.load().copy()
        when=datetime.fromisoformat(stage.jadwal)
        with self.assertRaises(ValueError):
            T.tambah_dadakan(self.store,company_id=self.cid,rm_id='RM-001',feedback_id=stage.feedback_id,
                            event_id=stage.event_id,tanggal_kunjungan=stage.tanggal_kunjungan,setelah=0,
                            jenis='Rapat internal',judul='Audit clash',agenda='Audit',mulai=when,menit=60,
                            pemilik='RM',divisi=[],ke_kalender=True,undang_divisi=False,user='rm-001')
        pd.testing.assert_frame_equal(T.KEGIATAN.load(),before)

    def test_rm_cannot_close_division_ticket(self):
        _,_,tickets=self.feedback(divisions=['kredit'])
        with self.assertRaises(ValueError):
            T.reply(tickets[0],'rm-001','Selesai','Selesai')
        self.assertEqual(T.REQ.load().set_index('id').loc[tickets[0],'status'],'Baru')
        T.reply(tickets[0],'rm-001','Dokumen tersedia')

    def test_wrong_division_cannot_reply(self):
        _,_,tickets=self.feedback(divisions=['kredit'])
        self.division('risiko')
        with self.assertRaises(ValueError):
            T.reply(tickets[0],'div-risiko','Audit','Diproses')

    def test_all_divisions_must_finish_before_task(self):
        _,_,tickets=self.feedback(divisions=['kredit','legal'])
        stage=T.KEGIATAN.load().iloc[0]
        with self.assertRaises(ValueError):
            T.set_kegiatan(stage.id,True,'rm-001')
        with self.assertRaises(ValueError):
            K.set_status(stage.kal_id,'Selesai','rm-001')
        by_div=T.REQ.load().set_index('divisi').id.to_dict()
        self.finish_ticket(by_div['kredit'],'kredit')
        self.assertEqual(T.KEGIATAN.load().set_index('id').loc[stage.id,'status'],'Belum')
        self.finish_ticket(by_div['legal'],'legal')
        self.assertEqual(T.KEGIATAN.load().set_index('id').loc[stage.id,'status'],'Selesai')
        self.assertEqual(K.load().set_index('id').loc[stage.kal_id,'status'],'Selesai')

    def test_calendar_changes_sync_task_and_cancel_ticket(self):
        self.feedback(divisions=['kredit'])
        stage=T.KEGIATAN.load().iloc[0]
        row=K.load().set_index('id').loc[stage.kal_id].to_dict() | {'id':stage.kal_id}
        m=datetime.fromisoformat(row['mulai'])+timedelta(days=1)
        row.update(mulai=m.isoformat(timespec='minutes'),selesai=(m+timedelta(hours=1)).isoformat(timespec='minutes'))
        self.assertFalse(K.upsert([row],'rm-001')[2])
        self.assertEqual(T.KEGIATAN.load().set_index('id').loc[stage.id,'jadwal'],row['mulai'])
        K.set_status(stage.kal_id,'Dibatalkan','rm-001')
        self.assertEqual(T.KEGIATAN.load().set_index('id').loc[stage.id,'status'],'Dibatalkan')
        self.assertTrue(T.REQ.load().status.eq('Dibatalkan').all())

    def test_reactivation_checks_conflicts(self):
        self.feedback()
        stage=T.KEGIATAN.load().iloc[0]
        T.batal_kegiatan(stage.id,'Audit','rm-001')
        self.event(id='busy',when=datetime.fromisoformat(stage.jadwal))
        with self.assertRaises(ValueError):
            T.aktifkan_kegiatan(stage.id,'rm-001')
        self.assertEqual(T.KEGIATAN.load().set_index('id').loc[stage.id,'status'],'Dibatalkan')

    def test_feedback_retry_and_multi_product_metrics(self):
        event=self.event(when=datetime.combine(date.today(),time(8)))
        first=self.feedback(event)
        second=self.feedback(event)
        self.assertEqual(first,second)
        self.assertEqual(len(T.FEEDBACK.load()),1)
        own=self.store.log_all[self.store.log_all.get('event_id',pd.Series(index=self.store.log_all.index,dtype=str)).eq('visit')]
        self.assertEqual(len(own),1)
        self.assertEqual(own.iloc[0].product_id,'P01;P02')
        frame=P.contacts(own,'RM-001')
        self.assertEqual(len(P.pipeline(frame,date.today())),2)
        self.assertEqual(P.metrics(frame,date.today(),date.today())['contacts'],1)

    def test_storage_failure_rolls_back_whole_feedback(self):
        event=self.event(when=datetime.combine(date.today(),time(8)))
        before=K.load().copy()
        with patch.object(T.KEGIATAN,'upsert',side_effect=OSError('Audit storage failure')):
            with self.assertRaises(OSError):
                self.feedback(event,divisions=['kredit'])
        self.assertTrue(T.FEEDBACK.load().empty)
        self.assertTrue(T.REQ.load().empty)
        pd.testing.assert_frame_equal(K.load(),before)

    def test_failure_after_contact_write_restores_log(self):
        event=self.event(when=datetime.combine(date.today(),time(8)))
        before=self.store.log_all.copy()
        with patch.object(data,'audit',side_effect=OSError('Audit failure')):
            with self.assertRaises(OSError):
                self.feedback(event,activities=[])
        self.assertFalse((data.APP_OUT/'visit_log.csv').exists())
        self.assertTrue(T.FEEDBACK.load().empty)
        self.assertEqual(len(self.store.log_all),len(self.store.log))

    def test_profile_and_copilot_share_feedback_identity(self):
        event=self.event(when=datetime.combine(date.today(),time(9)))
        row=dict(party_id=self.cid,rm_id='RM-001',contact_date=date.today().isoformat(),
                 channel='Kunjungan',response='Interested',product_id='P01;P02',feedback_note='Audit contact')
        first=T.record_contact(self.store,row,'rm-001')
        second=T.record_contact(self.store,row,'rm-001')
        self.assertEqual(first,second)
        with self.assertRaises(ValueError):
            T.record_contact(self.store,{**row,'feedback_note':'Copilot summary'},'rm-001')
        self.assertEqual(len(T.FEEDBACK.load()),1)
        self.assertEqual(len(self.store.log_all[self.store.log_all.action_id.eq('APP-FB-visit')]),1)

    def test_logout_clears_dialog_and_drafts(self):
        import streamlit as st
        with patch.object(auth,'current',side_effect=lambda: st.session_state.get('user')):
            app=AppTest.from_file(str(ROOT/'app/app.py'),default_timeout=30)
            app.session_state['user']=self.actor
            app.session_state['rm']='RM-001'
            app.run()
            app.session_state['visit_draft']=('private',)
            app.session_state['sched_notice']={'private':'old account'}
            # An invalid company avoids opening a dialog while testing its cleanup.
            app.session_state['sched_dlg']={'cid':'invalid','catatan':'old','sumber':'Audit','prefer':None}
            next(x for x in app.button if x.label=='Keluar').click().run()
            self.assertFalse(app.exception)
            for key in ['visit_draft','sched_notice','sched_dlg','week_plan_ctx','user']:
                self.assertNotIn(key,app.session_state)

    def test_prospect_handoff_moves_open_work_preserves_history(self):
        prospect=next(cid for cid in PW.accessible_ids(self.store,self.actor) if not self.store.cox.is_client[cid])
        event=self.event(cid=prospect,when=datetime.combine(date.today(),time(8)))
        self.feedback(event,divisions=['kredit'])
        self.actor=dict(username='supervisor',nama='Audit',role='supervisor',rm_id='Semua RM')
        count,bad=K.transfer(prospect,'RM-002','supervisor')
        self.assertFalse(bad)
        self.assertGreater(count,0)
        self.assertTrue(T.KEGIATAN.load().rm_id.eq('RM-002').all())
        self.assertTrue(T.REQ.load().rm_id.eq('RM-002').all())
        self.assertEqual(T.FEEDBACK.load().rm_id.iloc[0],'RM-001')
        self.assertEqual(K.load().set_index('id').loc['visit','rm_id'],'RM-001')

    def test_confirmation_and_reconfirmation(self):
        request=T.submit_visit(rm_id='RM-001',company_id=self.cid,nama='Audit',mulai=self.m,
                               selesai=self.m+timedelta(hours=1),kanal='Kunjungan',tujuan='Audit',produk=['P01'],
                               divs=['kredit'],catatan='',user='rm-001')
        self.actor=dict(username='supervisor',nama='Audit',role='supervisor',rm_id='Semua RM')
        req=T.REQ.load().set_index('id').loc[request].to_dict() | {'id':request}
        eid,tickets=T.decide_visit(self.store,req,True,'Audit','supervisor')
        with self.assertRaises(ValueError):
            T.decide_visit(self.store,req,True,'Retry','supervisor')
        self.division('kredit')
        T.reply(tickets[0],'div-kredit','Hadir','Dikonfirmasi')
        self.assertEqual(T.REQ.load().set_index('id').loc[tickets[0],'status'],'Dikonfirmasi')
        self.actor=dict(username='supervisor',nama='Audit',role='supervisor',rm_id='Semua RM')
        row=K.load().set_index('id').loc[eid].to_dict() | {'id':eid}
        row.update(mulai=(self.m+timedelta(days=1)).isoformat(timespec='minutes'),selesai=(self.m+timedelta(days=1,hours=1)).isoformat(timespec='minutes'))
        K.upsert([row],'supervisor')
        self.assertEqual(T.REQ.load().set_index('id').loc[tickets[0],'status'],'Baru')

    def test_reactivation_reopens_linked_tickets(self):
        self.feedback(divisions=['kredit'])
        stage=T.KEGIATAN.load().iloc[0]
        T.batal_kegiatan(stage.id,'Audit','rm-001')
        T.aktifkan_kegiatan(stage.id,'rm-001')
        self.assertEqual(T.KEGIATAN.load().set_index('id').loc[stage.id,'status'],'Belum')
        self.assertTrue(T.REQ.load().status.eq('Baru').all())

    def test_unplanned_contact_can_be_distinct_on_same_day(self):
        first=T.contact_event(self.store,'RM-001',self.cid,datetime.combine(date.today(),time(8)),'Telepon','rm-001',reuse_existing=False)
        second=T.contact_event(self.store,'RM-001',self.cid,datetime.combine(date.today(),time(9)),'Telepon','rm-001',reuse_existing=False)
        self.assertNotEqual(first['id'],second['id'])
        self.assertEqual(len(K.load()),2)

    def test_backend_rejects_foreign_company_even_completed(self):
        foreign=self.store.cox.index[(self.store.cox.rm_id=='RM-002') & self.store.cox.is_client][0]
        row=dict(id='foreign',rm_id='RM-001',company_id=foreign,judul='Audit',kanal='Kunjungan',
                 mulai=self.m.isoformat(timespec='minutes'),selesai=(self.m+timedelta(hours=1)).isoformat(timespec='minutes'),status='Selesai')
        self.assertTrue(K.upsert([row],'rm-001')[2])
        self.assertTrue(K.load().empty)

    def test_company_scope_and_progress_feedback_guard(self):
        foreign=self.store.cox.index[(self.store.cox.rm_id=='RM-002') & self.store.cox.is_client][0]
        self.assertNotIn(foreign,T.assignment_ids(self.store,'RM-001',self.actor))
        with self.assertRaises(ValueError):
            T.contact_event(self.store,'RM-001',foreign,datetime.now()-timedelta(hours=1),'Telepon','rm-001')
        self.feedback()
        stage=T.KEGIATAN.load().iloc[0]
        row=K.load().set_index('id').loc[stage.kal_id].to_dict() | {'id':stage.kal_id}
        with self.assertRaises(ValueError):
            self.feedback(row,activities=[])

    def test_ui_invalid_edit_shows_error_and_preserves_event(self):
        self.event()
        app=AppTest.from_file(str(ROOT/'app/app.py'),default_timeout=30)
        app.session_state['user']=self.actor
        app.session_state['rm']='RM-001'
        app.run().switch_page('views/9_kalender.py').run()
        app.session_state['cal_sel']='visit'
        app.run()
        next(x for x in app.time_input if x.label=='Mulai').set_value(time(11))
        next(x for x in app.time_input if x.label=='Selesai').set_value(time(10))
        next(x for x in app.button if x.label=='Simpan perubahan').click().run()
        self.assertFalse(app.exception)
        self.assertTrue(any('Jam selesai' in x.value for x in app.error))
        self.assertEqual(K.load().set_index('id').loc['visit','mulai'],self.m.isoformat(timespec='minutes'))

    def test_ui_progress_navigation_and_rm_ticket_options(self):
        self.feedback(divisions=['kredit'])
        stage=T.KEGIATAN.load().iloc[0]
        app=AppTest.from_file(str(ROOT/'app/app.py'),default_timeout=30)
        app.session_state['user']=self.actor
        app.session_state['rm']='RM-001'
        app.run().switch_page('views/9_kalender.py').run()
        app.session_state['cal_sel']=stage.kal_id
        app.run()
        self.assertFalse(app.exception)
        self.assertFalse(any(x.label=='Isi feedback & tindak lanjut' for x in app.button))
        self.assertTrue(any(x.label=='Buka kegiatan terkait' for x in app.button))
        app.switch_page('views/11_koordinasi.py').run()
        self.assertFalse(app.exception)
        status=next(x for x in app.selectbox if x.label=='Ubah status')
        self.assertEqual(status.options,['(tetap)','Dibatalkan'])


if __name__=='__main__':
    unittest.main()
