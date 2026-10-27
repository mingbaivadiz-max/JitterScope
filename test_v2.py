# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 SanyLok
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import csv
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from PyQt6.QtCore import QSettings
import test_controller as legacy
import controller.model as model
import controller.network as net
import controller.ui as ui
from controller.storage import HistoryStore
from controller.profiles import Profiles
from controller.dialogs import HistoryDialog


class ModelV2Tests(unittest.TestCase):
    def test_loss_overrides_a_single_fast_reply(self):
        points = [model.Sample(None)]*59 + [model.Sample(20)]
        self.assertEqual(model.quality(points[-1],model.summarize(points)),'bad')

    def test_jitter_and_errors_affect_quality(self):
        points = [model.Sample(10),model.Sample(100),model.Sample(10)]
        self.assertEqual(model.quality(points[-1],model.summarize(points)),'bad')
        self.assertEqual(model.quality(model.Sample(20),{'count':10,'errors':1,'loss':0,'jitter':0}),'warning')

    def test_control_only_slow_has_its_own_message(self):
        nodes = {role:{'sample':model.Sample(value),'samples':[model.Sample(10)]*5+[model.Sample(value)]}
                 for role,value in [('target',10),('gateway',10),('control',100)]}
        self.assertIn('только контрольный',model.diagnostic_hint(nodes))

    def test_percentiles_and_error_denominator(self):
        points = [model.Sample(10),model.Sample(20),model.Sample(None),model.Sample(100),model.Sample(None,'access')]
        stats = model.summarize(points)
        self.assertEqual(stats['count'],4)
        self.assertEqual(stats['errors'],1)
        self.assertEqual(stats['loss'],25)
        self.assertEqual(stats['p50'],20)
        self.assertAlmostEqual(stats['p95'],92)

    def test_alerts_debounce_recovery_and_cooldown(self):
        tracker = model.AlertTracker()
        bad = {'count':10,'total':10,'loss':10,'jitter':0}
        good = {'count':10,'total':10,'loss':0,'jitter':0}
        self.assertIsNone(tracker.update(model.Sample(20),bad,0))
        self.assertIsNone(tracker.update(model.Sample(20),bad,1))
        self.assertEqual(tracker.update(model.Sample(20),bad,2),'degraded')
        for now in range(3,30):
            self.assertIsNone(tracker.update(model.Sample(20),bad,now))
        for now in range(30,34):
            self.assertIsNone(tracker.update(model.Sample(20),good,now))
        self.assertEqual(tracker.update(model.Sample(20),good,34),'recovered')
        for now in range(35,40):
            self.assertIsNone(tracker.update(model.Sample(20),bad,now))
        self.assertEqual(tracker.update(model.Sample(20),bad,123),'degraded')


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='usb-net-history-test-')
        self.path = Path(self.temp.name)/'history.sqlite'
        self.store = HistoryStore(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def sample(self, session, rtt, error='', timestamp=None, role='target'):
        self.store.append(session,{'timestamp':timestamp or time.time(),'nodes':{role:{'sample':model.Sample(rtt,error),
                          'address':'1.1.1.1','mode':'icmp','port':None}},'traffic':(10,2),'adapter':'phone'})

    def test_history_survives_restart_and_marks_interrupted_session(self):
        session = self.store.start_session({'host':'1.1.1.1','profile':'phone'})
        self.sample(session,42)
        self.store.flush()
        self.store.close()
        self.store = HistoryStore(self.path)
        metadata,rows,stats = self.store.session_data(session)
        self.assertEqual(rows[0]['rtt'],42)
        self.assertEqual(metadata['status'],'interrupted')
        self.assertEqual(stats['target']['avg'],42)

    def test_sql_summary_matches_in_memory_calculation(self):
        session = self.store.start_session({'host':'1.1.1.1'})
        points = [(10,''),(20,''),(None,''),(100,''),(None,'no socket'),(40,''),(42,'')]
        for index,(rtt,error) in enumerate(points):
            self.sample(session,rtt,error,time.time()+index)
        self.store.flush()
        _,stats,_ = self.store.summary_session(session)
        expected = model.summarize([model.Sample(*point) for point in points])
        for field in ('count','total','errors','received','loss','avg','p50','p95','jitter','min','max'):
            with self.subTest(field=field):
                self.assertAlmostEqual(stats['target'][field],expected[field])

    def test_csv_html_escape_and_different_sessions(self):
        first = self.store.start_session({'host':'1.1.1.1','profile':'<script>alert(1)</script>'})
        self.sample(first,10)
        self.sample(first,None,'=BAD()')
        second = self.store.start_session({'host':'8.8.8.8','profile':'office'})
        self.sample(second,60)
        self.store.end_session(first)
        self.store.flush()
        csv_path,html_path = self.store.export_session(first,Path(self.temp.name)/'reports')
        text = html_path.read_text(encoding='utf-8')
        self.assertNotIn('<script>',text)
        self.assertIn('&lt;script&gt;',text)
        with csv_path.open(encoding='utf-8-sig',newline='') as src:
            rows = list(csv.DictReader(src))
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[1]['error'],"'=BAD()")
        comparison = self.store.compare_sessions(first,second)
        self.assertEqual([entry['stats']['avg'] for entry in comparison],[10,60])
        self.assertEqual(self.store.session_data(first)[0]['status'],'complete')

    def test_retention_removes_old_rows(self):
        session = self.store.start_session({'host':'1.1.1.1'})
        self.sample(session,10,timestamp=time.time()-2*86400)
        self.sample(session,20)
        self.store.set_retention(1)
        self.store.flush()
        _,rows,_ = self.store.session_data(session)
        self.assertEqual([r['rtt'] for r in rows],[20])

    def test_chart_is_bounded_and_preserves_spikes_and_loss(self):
        session = self.store.start_session({'host':'1.1.1.1'})
        base = time.time()
        rows = [(session,base+i,'target','1.1.1.1','icmp',None,999 if i==1234 else 10,
                 '',1,1,None) for i in range(2000)]
        rows[200] = (session,base+200,'target','1.1.1.1','icmp',None,None,'',1,1,None)
        self.store.flush()
        with self.store.connect() as db:
            db.executemany('INSERT INTO samples VALUES(?,?,?,?,?,?,?,?,?,?,?)',rows)
        points = self.store.chart_points(session)
        self.assertLessEqual(len(points),600)
        self.assertEqual(max(p['rtt'] or 0 for p in points),999)
        self.assertTrue(any(p['loss'] for p in points))

    def test_close_flushes_queued_measurements(self):
        session = self.store.start_session({'host':'1.1.1.1'})
        for i in range(100):
            self.sample(session,i)
        self.store.close()
        self.assertEqual(len(self.store.session_data(session)[1]),100)

    def test_writer_failure_is_reported(self):
        self.store.flush()
        self.store._put(('samples',[('invalid tuple',)]))
        with self.assertRaises(OSError):
            self.store.flush()
        self.assertEqual(self.store.dropped_rows,1)

    def test_bulk_queue_flushes_without_dropping_rows(self):
        session=self.store.start_session({'host':'1.1.1.1'})
        for i in range(1000):
            self.sample(session,float(i%100))
        self.store.flush(timeout=10)
        self.assertEqual(self.store.summary_session(session)[2]['rows'],1000)
        self.assertEqual(self.store.dropped_rows,0)

    def test_bad_operation_does_not_rollback_good_neighbors(self):
        session=self.store.start_session({'host':'1.1.1.1'})
        for i in range(10):
            self.sample(session,i)
        self.store._put(('samples',[('bad tuple',)]))
        for i in range(10):
            self.sample(session,i+10)
        try:
            self.store.flush()
        except OSError:
            pass
        self.assertEqual(self.store.summary_session(session)[2]['rows'],20)
        self.assertEqual(self.store.dropped_rows,1)


class ProfileTests(unittest.TestCase):
    def test_profiles_persist_and_validate(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = QSettings(str(Path(directory)/'profiles.ini'),QSettings.Format.IniFormat)
            profiles = Profiles(settings)
            profiles.save({'name':'Phone','host':'1.1.1.1','mode':'tcp','port':443,'compare':['8.8.8.8']})
            restored = Profiles(settings)
            self.assertEqual(restored.items[0]['compare'],['8.8.8.8'])
            with self.assertRaises(ValueError):
                profiles.save({'name':'bad','host':'invalid;command'})
            profiles.remove('Phone')
            self.assertEqual(Profiles(settings).items,[])


class WidgetV2Tests(unittest.TestCase):
    setUp = legacy.WidgetTests.setUp
    tearDown = legacy.WidgetTests.tearDown
    reopen = legacy.WidgetTests.reopen

    def test_dns_failure_keeps_control_gateway_and_traffic_running(self):
        with patch.object(ui.QHostInfo,'lookupHost',return_value=123),patch.object(ui.QHostInfo,'abortHostLookup'):
            self.widget.address.setText('slow.example.com')
            self.widget.apply_target()
            self.widget.lookup_timeout()
            self.assertTrue(legacy.until(lambda:self.widget._last_data is not None and self.widget._last_data['nodes']['control']['count'] >= 2))
            data = self.widget._last_data
            self.assertTrue(data['sample'].error)
            self.assertEqual(data['nodes']['control']['sample'].rtt,35.5)
            self.assertEqual(data['nodes']['gateway']['sample'].rtt,35.5)
            self.assertIsNotNone(data['traffic'])

    def test_default_control_is_not_the_same_destination(self):
        nodes = self.widget._last_data['nodes']
        self.assertNotEqual(nodes['target']['address'],nodes['control']['address'])

    def test_large_loss_is_red_in_main_and_mini(self):
        samples = [model.Sample(None)]*59+[model.Sample(20)]
        self.widget.update_dashboard({'generation':self.widget.generation,'sample':samples[-1],'samples':samples,
                                     'traffic':None,'traffic_error':'',**model.summarize(samples)})
        self.assertIn('#ff6289',self.widget.ping_label.styleSheet())
        self.assertIn('#ff6289',self.widget.mini_ping.styleSheet())

    def test_extra_dns_failure_does_not_stop_main(self):
        with patch.object(ui.QHostInfo,'lookupHost',return_value=123),patch.object(ui.QHostInfo,'abortHostLookup'):
            self.widget.configure_comparison(['missing.example.com','192.0.2.10'])
            self.widget.extra_timeout('missing.example.com',self.widget._extra_token)
            self.assertTrue(legacy.until(lambda:self.widget._last_data is not None and 'compare:missing.example.com' in self.widget._last_data['nodes']))
            data = self.widget._last_data
            self.assertTrue(data['nodes']['compare:missing.example.com']['sample'].error)
            self.assertEqual(data['nodes']['compare:192.0.2.10']['sample'].rtt,35.5)
            self.assertEqual(data['sample'].rtt,35.5)

    def test_profiles_apply_and_persist_last_name(self):
        self.widget.address.setText('127.0.0.1')
        with patch.object(ui.QInputDialog,'getText',return_value=('Phone USB',True)):
            self.widget.save_profile()
        self.widget.address.setText('8.8.8.8')
        self.widget.apply_target()
        self.widget.profile_combo.setCurrentIndex(0)
        self.widget.profile_combo.setCurrentIndex(self.widget.profile_combo.findData('Phone USB'))
        self.assertEqual(self.widget._active_address,'127.0.0.1')
        self.reopen()
        self.assertEqual(self.widget.profile_name,'Phone USB')

    def test_comparison_limit_and_stale_dns(self):
        callbacks=[]
        with patch.object(ui.QHostInfo,'lookupHost',side_effect=lambda host,cb:callbacks.append(cb) or 123),patch.object(ui.QHostInfo,'abortHostLookup'):
            self.widget.configure_comparison(['first.example.com'])
            self.widget.configure_comparison(['192.0.2.10'])
            info=legacy.QHostInfo()
            info.setAddresses([legacy.QHostAddress('203.0.113.1')])
            callbacks[0](info)
            self.assertEqual(self.widget.comparison_hosts,['192.0.2.10'])
            self.widget.configure_comparison([f'192.0.2.{i}' for i in range(1,7)])
            self.assertEqual(self.widget.comparison_hosts,['192.0.2.10'])

    def test_history_dialog_can_render_and_close_during_chart_read(self):
        self.widget.store.flush()
        dialog=HistoryDialog(self.widget.store,self.widget)
        dialog.show()
        self.assertGreaterEqual(dialog.table.rowCount(),1)
        dialog.table.selectRow(0)
        self.assertTrue(legacy.until(lambda:dialog.chart_job is None))
        self.assertFalse(dialog.grab().isNull())
        dialog.close()

    def test_close_during_background_export_stays_responsive(self):
        self.widget.store.flush()
        dialog=HistoryDialog(self.widget.store,self.widget)
        dialog.show()
        dialog.table.selectRow(0)
        def delayed(*args):
            time.sleep(.25)
            return Path(self.temp.name)/'report.csv',Path(self.temp.name)/'report.html'
        with patch('controller.dialogs.QFileDialog.getExistingDirectory',return_value=self.temp.name), \
             patch.object(self.widget.store,'export_session',side_effect=delayed):
            dialog.export()
            started=time.monotonic()
            self.widget.close()
            self.assertLess(time.monotonic()-started,.15)
            self.assertTrue(legacy.until(lambda:not self.widget.isVisible() and not self.widget.worker.isRunning()))

    def test_notifications_debounce_and_recovery_signal(self):
        events=[]
        self.widget.alert_emitted.connect(lambda title,message:events.append(title))
        self.widget.preferences['alerts']=True
        bad=[model.Sample(None)]*5+[model.Sample(20)]
        good=[model.Sample(20)]*10
        for samples in (bad,bad,bad,good,good,good,good,good):
            self.widget.update_dashboard({'generation':self.widget.generation,'sample':samples[-1],
                                         'samples':samples,'traffic':None,'traffic_error':'',**model.summarize(samples)})
        self.assertEqual(events,['Связь ухудшилась','Связь восстановилась'])
        self.widget.preferences['alerts']=False

    def test_failed_dns_schedules_retry_and_can_recover(self):
        callbacks=[]
        with patch.object(ui.QHostInfo,'lookupHost',side_effect=lambda host,cb:callbacks.append(cb) or 123),patch.object(ui.QHostInfo,'abortHostLookup'):
            self.widget.address.setText('retry.example.com')
            self.widget.apply_target()
            self.widget.lookup_timeout()
            self.assertTrue(self.widget.retry_timer.isActive())
            self.widget.retry_dns()
            self.assertEqual(len(callbacks),2)
            info=legacy.QHostInfo()
            info.setAddresses([legacy.QHostAddress('203.0.113.5')])
            callbacks[1](info)
            self.assertEqual(self.widget.worker._config[1],'203.0.113.5')
            self.assertFalse(self.widget.retry_timer.isActive())
            self.widget.cancel_lookup()


if __name__=='__main__':
    unittest.main()
