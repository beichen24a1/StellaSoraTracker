import hashlib
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from stellasora_toolkit import accounts, app_updater, service, server_config
from stellasora_toolkit.application import Application, read_preferences, safe_message
from stellasora_toolkit.desktop_engine import Engine
from stellasora_toolkit.desktop_updates import DesktopUpdates


def group(timestamp=100, gid=10162, ids=None):
    return {'Gid': gid, 'Time': timestamp, 'Ids': ids or [103, 162]}


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.output = self.root/'中文 空格 exports'
        self.events = []
        self.app = Application(self.output, self.events.append, offline=True)
        previous = server_config.active().key
        self.addCleanup(server_config.set_active, previous)

    def source(self, uid='100000001', categories=None):
        path = self.root/f'incoming-{uid}.json'
        path.write_text(json.dumps({'version': 1, 'uid': uid, 'categories': categories or {'1': [group()]}}), encoding='utf-8')
        return path

    def import_one(self, uid='100000001', categories=None):
        return self.app.import_files([str(self.source(uid, categories))], lambda _msg: None)

    def wait_tasks(self):
        deadline = time.monotonic()+5
        while any(task['state'] == 'running' for task in self.app.tasks) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(any(task['state'] == 'running' for task in self.app.tasks))

    def test_theme_mapping_preserves_legacy_and_unknown_preferences(self):
        for old, expected in [('orbit', 'dark'), ('sky', 'light'), ('journal', 'light'), ('unknown', 'light')]:
            (self.output/'ui_settings.json').write_text(json.dumps({'theme': old, 'future': 42}), encoding='utf-8')
            self.assertEqual(read_preferences(self.output)['color_mode'], expected)
            self.app.save_preferences({'color_mode': 'dark'})
            saved = json.loads((self.output/'ui_settings.json').read_text())
            self.assertEqual(saved['theme'], old)
            self.assertEqual(saved['future'], 42)
            self.assertEqual(saved['color_mode'], 'dark')

    def test_automation_defaults_and_validation(self):
        values = read_preferences(self.output)
        self.assertFalse(values['auto_upload'])
        self.assertTrue(values['auto_update'])
        for change in ({'auto_upload': 'true'}, {'color_mode': 'orange'}, {'pool_columns': True}, {'update_channel': 'evil'}, {'new_option': 1}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.app.save_preferences(change)

    def test_import_export_share_and_summary_keep_raw_anniversary_category(self):
        categories = {'1': [group()], '6': [group(200,1001,[162,103])]}
        self.import_one(categories=categories)
        state = self.app.state()
        self.assertEqual((state['summary']['pulls'], state['summary']['five']), (4,2))
        self.assertEqual(state['preferences']['color_mode'], 'light')
        self.assertTrue(state['summary']['activity'])
        exported = self.root/'导出 文件夹'; exported.mkdir()
        result = self.app.export_records(str(exported), lambda _msg: None)
        self.assertEqual(len(result['files']), 2)
        document = json.loads(Path(result['files'][0]).read_text())
        self.assertEqual(document['categories']['6'], categories['6'])
        path = service.export_share_for_uid(self.output)
        self.assertEqual(path.name, '100000001.json')
        self.assertNotIn('upload_endpoint', json.dumps(state))

    def test_backup_failure_prevents_import_and_keeps_original_bytes(self):
        self.import_one()
        archive = self.output/'100000001.json'
        before = archive.read_bytes()
        source = self.source(categories={'1': [group(300)]})
        with patch.object(self.app, 'backup', side_effect=OSError('disk full')):
            with self.assertRaises(ValueError):
                self.app.import_files([str(source)], lambda _msg: None)
        self.assertEqual(archive.read_bytes(), before)

    def test_manual_uid_cannot_relabel_owned_or_unclaimed_history(self):
        self.import_one()
        archive = self.output/'100000001.json'
        original = archive.read_bytes()
        with self.assertRaises(ValueError): self.app.save_uid('100000002')
        self.assertEqual(archive.read_bytes(), original)
        blank = accounts.create(self.output)
        service._write_archive(accounts.data_dir(self.output, blank.key), {1: [group()]})
        with self.assertRaises(ValueError): self.app.save_uid('100000003')
        self.assertEqual(accounts.active_account(self.output).uid, '')

    def test_account_crud_idempotence_and_cross_uid_merge_protection(self):
        self.import_one()
        first = accounts.active_account(self.output)
        self.import_one('100000002')
        second = accounts.active_account(self.output)
        self.app.account_action('rename', {'key': first.key, 'name': '主账号'})
        self.app.account_action('create', {'uid': first.uid})
        self.assertEqual(accounts.active_account(self.output).key, first.key)
        with self.assertRaises(ValueError):
            self.app.account_action('merge', {'key': first.key, 'target': second.key})
        self.app.account_action('remove', {'key': second.key})
        self.assertFalse((self.output/'100000002.json').exists())
        self.assertTrue(list((self.output/'accounts').glob(second.key+'.deleted_*')))

    def test_job_errors_are_redacted_and_durable_without_archive_contents(self):
        self.app.job('失败测试', lambda _p, _id: (_ for _ in ()).throw(ValueError('https://secret.invalid/private token=secret')))
        self.wait_tasks()
        self.assertEqual(self.app.tasks[0]['state'], 'failed')
        serialized = json.dumps(self.app.tasks)
        self.assertNotIn('secret.invalid', serialized)
        self.assertNotIn('token=secret', serialized)
        self.assertIn('已隐藏', serialized.encode().decode('unicode_escape') if '\\u' in serialized else serialized)
        restored = Application(self.output, offline=True)
        self.assertEqual(restored.tasks[0]['state'], 'failed')

    def test_process_pid_must_match_running_game(self):
        with patch('stellasora_toolkit.application.find_game_processes', return_value=[]):
            with self.assertRaises(ValueError): self.app.select_process(123)
        with self.assertRaises(ValueError): self.app.select_process(True)

    def test_state_read_and_locked_progress_do_not_deadlock(self):
        from threading import Event, Thread
        from stellasora_toolkit.storage_lock import storage_transaction
        held, proceed, reader_started = Event(), Event(), Event()
        def work(progress,_id):
            with storage_transaction(self.output):
                held.set();proceed.wait(2);progress('锁内保存进度')
        self.app.job('并发读取测试',work)
        self.assertTrue(held.wait(2))
        values=[]
        def read():
            reader_started.set();values.append(self.app.state())
        reader=Thread(target=read,daemon=True);reader.start();reader_started.wait(1)
        time.sleep(.05);proceed.set();reader.join(3)
        self.assertFalse(reader.is_alive())
        self.wait_tasks();self.assertEqual(values[0]['summary']['pulls'],0)

    def test_errors_do_not_echo_archive_payloads(self):
        value=safe_message('server response: {"categories":{"6":[{"Ids":[162]}]}}')
        self.assertNotIn('162',value)
        self.assertNotIn('categories',value)

    def test_old_language_request_never_registers_names_after_server_switch(self):
        from stellasora_toolkit import catalog, catalog_sync
        server_config.set_active('cn')
        state=self.output/'catalog_sync_state.json'
        chinese_cache=catalog_sync._catalog_cache_path(state)
        original=catalog.gacha_item_name(103)
        def changed(_progress=None):
            server_config.set_active('jp')
            return [{'id':103,'kind':'traveler','name':'stale Chinese name','rarity':4,'five_star':False,'icon':''}]
        with patch.object(catalog_sync,'_fetch_five_star_catalog',side_effect=changed):
            with self.assertRaises(catalog_sync.CatalogLanguageChanged):catalog_sync._sync_once(state,None)
        self.assertEqual(catalog.gacha_item_name(103),original)
        self.assertTrue(chinese_cache.is_file())
        self.assertFalse(catalog_sync._catalog_cache_path(state).exists())

    def test_100k_records_are_paged_and_searchable(self):
        groups = [group(100+i, ids=[103]*10) for i in range(10000)]
        self.import_one(categories={'1': groups})
        result = self.app.query_records({'mode': 'all', 'pageSize': 50, 'page': 2})
        self.assertEqual(result['total'], 100000)
        self.assertEqual(len(result['items']), 50)
        self.assertEqual(result['items'][0]['time'], 10094)
        searched = self.app.query_records({'mode':'all', 'query':'没有这个名字'})
        self.assertEqual(searched['total'], 0)
        self.assertLess(len(json.dumps(result)), 50000)

    def test_record_results_keep_anniversary_neutral_and_intervals(self):
        self.import_one(categories={'1':[group(ids=[103,162,103,110])], '6':[group(200,1001,[162])]})
        result = self.app.query_records({'mode':'all'})
        annual = next(row for row in result['items'] if row['gid'] == 1001)
        self.assertEqual(annual['result'], '—')
        traveler = next(row for row in result['items'] if row['gid'] == 10162 and row['itemId'] == 162)
        self.assertEqual(traveler['interval'], 2)


class UpdateWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.app = Application(self.root/'exports', offline=False)
        self.updates = DesktopUpdates(self.app, self.root)
        self.data = b'verified update fixture'
        self.update = app_updater.AppUpdate('9.0.0','https://example.test/update.zip',hashlib.sha256(self.data).hexdigest(),'notes')

    def wait(self):
        deadline = time.monotonic()+5
        while any(task['state']=='running' for task in self.app.tasks) and time.monotonic()<deadline: time.sleep(.01)
        self.assertFalse(any(task['state']=='running' for task in self.app.tasks))

    def download(self):
        self.updates.state = {'status':'available','automatic':False,'update':vars(self.update)}
        def fake(update, directory, **kwargs):
            directory.mkdir(parents=True, exist_ok=True)
            path = directory/'verified.zip'; path.write_bytes(self.data)
            kwargs['metrics']({'phase':'downloading','received':len(self.data),'total':len(self.data),'speed':100,'eta':0})
            return path
        with patch.object(app_updater,'download_update',side_effect=fake):
            self.updates.download(); self.wait()

    def test_later_install_restores_and_rechecks_hash(self):
        self.download()
        self.assertEqual(self.updates.state['status'],'ready')
        restored = DesktopUpdates(self.app,self.root)
        self.assertEqual(restored.state['status'],'ready')
        Path(restored.state['package']).write_bytes(b'tampered')
        with self.assertRaises(ValueError): restored.install([])
        self.assertEqual(restored.state['status'],'failed')
        self.assertEqual(DesktopUpdates(self.app,self.root).state['status'],'idle')

    def test_turning_off_auto_update_discards_automatic_pending_package(self):
        self.download()
        self.updates.state['automatic']=True
        package=Path(self.updates.state['package'])
        self.updates.disable_automatic()
        self.assertFalse(package.exists())
        self.assertEqual(self.updates.state['status'],'idle')

    def test_cancellation_ignores_late_success_and_removes_package(self):
        self.updates.state = {'status':'available','automatic':True,'update':vars(self.update)}
        from threading import Event
        entered, release = Event(), Event()
        def delayed(update, directory, **kwargs):
            entered.set(); release.wait(3)
            directory.mkdir(parents=True,exist_ok=True)
            path=directory/'late.zip'; path.write_bytes(self.data)
            return path
        with patch.object(app_updater,'download_update',side_effect=delayed):
            self.updates.download(); self.assertTrue(entered.wait(2))
            self.updates.cancel_download(); release.set(); self.wait()
        self.assertEqual(self.updates.state['status'],'cancelled')
        self.assertFalse((self.updates.directory/'late.zip').exists())

    def test_failure_is_retryable(self):
        self.updates.state={'status':'available','automatic':False,'update':vars(self.update)}
        with patch.object(app_updater,'download_update',side_effect=OSError('network failed')):
            self.updates.download(); self.wait()
        self.assertEqual(self.updates.state['status'],'failed')
        self.download()
        self.assertEqual(self.updates.state['status'],'ready')

    def test_channel_switch_never_reuses_another_channels_ready_package(self):
        self.download()
        self.app.save_preferences({'update_channel':'stable'})
        self.updates.channel_changed()
        self.assertEqual(self.updates.state['status'],'idle')
        self.app.save_preferences({'update_channel':'beta'})
        self.updates.channel_changed()
        self.assertEqual(self.updates.state['status'],'ready')

    def test_disabled_auto_update_does_not_restore_automatic_prompt(self):
        self.download()
        receipt=json.loads(self.updates.receipt.read_text())
        receipt['automatic']=True
        self.updates.receipt.write_text(json.dumps(receipt),encoding='utf-8')
        self.app.save_preferences({'auto_update':False})
        self.assertEqual(DesktopUpdates(self.app,self.root).state['status'],'idle')


class ProtocolTests(unittest.TestCase):
    def test_engine_rejects_unlisted_methods(self):
        with tempfile.TemporaryDirectory() as directory:
            engine=Engine(Path(directory)/'exports',Path(directory),lambda _v:None,offline=True)
            with self.assertRaises(ValueError): engine.dispatch('shell.execute',{})

    def test_subprocess_stdout_is_only_utf8_protocol_and_has_no_qt_import(self):
        with tempfile.TemporaryDirectory() as directory:
            process=subprocess.run([sys.executable,'-m','stellasora_toolkit.desktop_engine','--output',str(Path(directory)/'数据 空格'),'--app-root',directory,'--offline'],
                                   input='{"id":1,"method":"app.state"}\n{"id":2,"method":"app.shutdown"}\n',capture_output=True,text=True,encoding='utf-8',timeout=15)
            self.assertEqual(process.returncode,0,process.stderr)
            messages=[json.loads(line) for line in process.stdout.splitlines()]
            state=next(item['result'] for item in messages if item.get('id')==1)
            self.assertEqual(state['preferences']['color_mode'],'light')
            self.assertEqual(state['protocolVersion'],1)


if __name__=='__main__': unittest.main()
