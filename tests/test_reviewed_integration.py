import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from stellasora_toolkit import accounts, service, server_config, rem_upload, exporter
from stellasora_toolkit.account_guard import AccountSafetyError
from stellasora_toolkit.account_uid import UidSearch
from stellasora_toolkit.account_verification import verified_uid_search
from stellasora_toolkit.presentation import overview
from stellasora_toolkit.process import GameProcess


def group(gid=1001, timestamp=1792500000, ids=None):
    return {'Gid':gid,'Time':timestamp,'Ids':ids or [144,211001,133]}


class StrictCaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name, options in (
            ('detect_and_apply', {'return_value':(server_config.PROFILES['cn'],'',['cn'])}),
            ('find_process_id', {'return_value':20}),
            ('RemoteProcess', {}), ('Lua53Reader', {}), ('LuaTableDiscovery', {}),
            ('verified_uid_search', {'return_value':UidSearch(uid='100000001',field_name='_uid')}),
        ):
            patcher = patch('stellasora_toolkit.service.'+name, **options)
            setattr(self,name,patcher.start())
            self.addCleanup(patcher.stop)
        self.process = self.RemoteProcess.return_value.__enter__.return_value
        self.process.get_creation_time.return_value = 1000
        self.LuaTableDiscovery.return_value.read_target_field.return_value = {6:[group()]}

    def read(self):
        return service.extract_snapshot(self.root, process_id=20)

    def test_anniversary_capture_round_trip_csv_and_share(self):
        snap = self.read()
        self.assertEqual(self.verified_uid_search.call_count,2)
        self.assertEqual(set(snap.gacha_categories),{6})
        self.assertEqual(json.loads(snap.share_file.read_text())['categories']['6'][0]['Gid'],1001)
        csv = next(path for path in snap.files if path.suffix=='.csv')
        categories,_uid = exporter.parse_import_text(service.read_import_text(csv),'.csv')
        self.assertEqual(set(categories),{6})
        self.assertEqual(rem_upload.validate_record(snap.share_file,snap.uid)['categories']['6'][0]['Gid'],1001)

    def test_uid_failure_never_uses_manual_uid_or_writes_archive(self):
        accounts.ensure_ready(self.root)
        service.save_manual_uid(accounts.active_data_dir(self.root),'100000009')
        self.verified_uid_search.side_effect = AccountSafetyError('UID not confirmed')
        with self.assertRaises(AccountSafetyError): self.read()
        self.assertEqual(list(self.root.rglob('stellasora_gacha_archive.json')),[])
        # 临时读不到 UID 不能把整个游戏会话永久标记成"已切号"。
        self.assertFalse((self.root/'account_sessions/20-1000.blocked').exists())
        self.verified_uid_search.side_effect = None
        self.assertEqual(self.read().uid,'100000001')

    def test_switch_during_read_preserves_existing_archive(self):
        first = self.read()
        original = first.share_file.read_bytes()
        self.verified_uid_search.side_effect = [UidSearch(uid='100000001'),UidSearch(uid='100000002')]
        with self.assertRaises(AccountSafetyError): self.read()
        self.assertEqual(first.share_file.read_bytes(),original)
        self.verified_uid_search.side_effect = None
        with self.assertRaises(AccountSafetyError): self.read()
        self.process.get_creation_time.return_value = 2000
        self.assertEqual(self.read().uid,'100000001')

    def test_pid_reuse_during_read_is_blocked(self):
        self.process.get_creation_time.side_effect = [1000,2000]
        with self.assertRaises(AccountSafetyError): self.read()
        self.assertEqual(list(self.root.rglob('stellasora_gacha_archive.json')),[])

    def test_unknown_category_never_replaces_archive(self):
        first=self.read()
        before=first.share_file.read_bytes()
        self.LuaTableDiscovery.return_value.read_target_field.return_value={5:[group()]}
        with self.assertRaises(ValueError): self.read()
        self.assertEqual(first.share_file.read_bytes(),before)

    def test_unclaimed_legacy_is_preserved_in_separate_account(self):
        old={1:[group(10162,100,[162])]}
        service._write_archive(self.root,old)
        before=(self.root/service.ARCHIVE_FILENAME).read_bytes()
        snap=self.read()
        self.assertEqual(set(snap.gacha_categories),{6})
        self.assertEqual((self.root/service.ARCHIVE_FILENAME).read_bytes(),before)
        self.assertTrue((self.root/'accounts/default'/service.ARCHIVE_FILENAME).exists())

    def test_damaged_active_archive_is_not_silently_overwritten(self):
        first=self.read()
        archive=first.share_file
        archive.write_bytes(b'{broken')
        with self.assertRaises(AccountSafetyError): self.read()
        self.assertEqual(archive.read_bytes(),b'{broken')

    def test_repeated_other_uid_records_block_upload_and_import(self):
        rows=[group(10162,t,[162]) for t in (100,200,300)]
        service._write_archive(self.root,{1:rows},uid='100000002')
        accounts.ensure_ready(self.root)
        incoming=self.root/'100000001.json'
        incoming.write_text(json.dumps({'version':1,'uid':'100000001','categories':{'1':rows}}))
        with self.assertRaises(AccountSafetyError): service.import_gacha_file(self.root,incoming)
        with patch('stellasora_toolkit.rem_upload.urlopen') as request:
            with self.assertRaises(rem_upload.RemUploadError): rem_upload.upload_file(incoming)
            request.assert_not_called()

    def test_merge_rejects_different_uid_and_unclaimed_archives_without_modifying(self):
        accounts.ensure_ready(self.root)
        target=accounts.create(self.root,uid='100000001')
        source=accounts.create(self.root,uid='100000002')
        service._write_archive(accounts.data_dir(self.root,target.key),{6:[group()]},uid=target.uid)
        for source_uid in ('100000002',''):
            # Corrupt/ambiguous ownership is a disk fixture, never produced by the writer.
            archive=self.root/f'{source.uid}.json'
            archive.write_text(json.dumps(service._archive_payload({6:[group(timestamp=1792500001)]},uid=source_uid)))
            before={p:p.read_bytes() for p in self.root.rglob('*.json')}
            with self.assertRaises(AccountSafetyError):
                service.merge_accounts(self.root,source.key,target.key)
            self.assertTrue(all(p.read_bytes()==data for p,data in before.items()))


class CombinedUidTests(unittest.TestCase):
    def check(self, learned, player):
        with patch('stellasora_toolkit.account_verification.find_account_uid',return_value=learned), \
             patch('stellasora_toolkit.account_verification.read_game_uid_from_process',**(
                 {'side_effect':player} if isinstance(player,Exception) else {'return_value':player})):
            return verified_uid_search(object(),object())

    def test_player_source_wins_over_learned_source(self):
        self.assertEqual(self.check(UidSearch(uid='100000001'),'100000001').uid,'100000001')
        # 国服实测: nUid 是内部账号 ID, 玩家表里的 _nPlayerId 才是游戏 UID。
        self.assertEqual(self.check(UidSearch(uid='1011690183'),'100872990').uid,'100872990')

    def test_overseas_player_source_and_learned_field_fallback(self):
        self.assertEqual(self.check(UidSearch(),'300000001').uid,'300000001')
        self.assertEqual(self.check(UidSearch(uid='100000001'),LookupError()).uid,'100000001')
        with self.assertRaises(AccountSafetyError): self.check(UidSearch(),LookupError())
        # 玩家表已经给出 UID 时, 不再因为通用 Lua 字段扫描超时而阻断。
        self.assertEqual(self.check(UidSearch(budget_exceeded=True),'100000001').uid,'100000001')


class CurrentInterfaceTests(unittest.TestCase):
    def test_anniversary_is_shown_as_an_activity_pool(self):
        from stellasora_toolkit.presentation import activity_pools
        stats = overview([group()])
        self.assertEqual(len(stats.category_stats), 4)
        self.assertNotIn('anniversary_selected', stats.category_stats)
        self.assertEqual(len(stats.category_stats['traveler_limited'].five_stars), 2)
        self.assertEqual([row['gid'] for row in activity_pools([group()])], [1001])

    def test_process_picker_selects_exact_pid(self):
        from stellasora_toolkit.application import Application
        previous = server_config.active().key
        self.addCleanup(server_config.set_active, previous)
        choices = [GameProcess('StellaSora.exe', 10, 'D:/one.exe'), GameProcess('StellaSora.exe', 20, 'D:/two.exe')]
        with tempfile.TemporaryDirectory() as directory:
            app = Application(Path(directory), offline=True)
            with patch('stellasora_toolkit.application.find_game_processes', return_value=choices):
                self.assertEqual(app.select_process(20).pid, 20)
                self.assertEqual(server_config.load_key(server_config.config_path(app.output)), 'intl')

    def test_cli_combines_server_and_pid(self):
        from stellasora_toolkit.cli import build_parser
        args = build_parser().parse_args(['--server', 'tw', '--pid', '20'])
        self.assertEqual((args.server, args.pid), ('tw', 20))

    def test_removed_demo_cli_flags_are_rejected(self):
        from stellasora_toolkit.desktop_launcher import main
        for flag in ('--demo', '--beta'):
            with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                main([flag])
