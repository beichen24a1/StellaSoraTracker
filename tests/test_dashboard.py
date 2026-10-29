import json
import tempfile
import unittest
from pathlib import Path

from stellasora_toolkit import accounts, affinity, roster
from stellasora_toolkit.desktop_engine import Engine


class DashboardTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)/'中文 空格'
        self.engine = Engine(self.root, self.root, lambda _event: None, offline=True)
        self.a = accounts.create(self.root, uid='100000001', name='A')
        self.b = accounts.create(self.root, uid='100000002', name='B')
        accounts.switch(self.root, self.a.key)
        self.archive = self.root/f'{self.a.uid}.json'
        self.archive.write_text(json.dumps({'version': 1, 'uid': self.a.uid, 'categories': {'1': [{'Gid': 10162, 'Time': 1792700000, 'Ids': [162, 103]}]}}), encoding='utf-8')
        roster.save_cache(self.root, self.a.uid, [roster.Character(130, '多娜', 90, 8, True)])
        affinity.save_cache(self.root, self.a.uid, [affinity.Affinity(156, '小禾', 65, 6040, 33100, True)])

    def test_current_account_summary_is_real_and_read_only(self):
        paths = [self.archive, roster.cache_path(self.root, self.a.uid), affinity.cache_path(self.root, self.a.uid)]
        before = [path.read_bytes() for path in paths]
        value = self.engine.dispatch('home.summary', {})
        self.assertEqual((value['accountKey'], value['uid']), (self.a.key, self.a.uid))
        self.assertEqual(value['roster']['count'], 1)
        self.assertEqual(value['roster']['highestLevel'], 90)
        self.assertEqual(value['affinity']['highestLevel'], 65)
        self.assertEqual([item['itemId'] for item in value['recentFive']], [162])
        self.assertEqual([path.read_bytes() for path in paths], before)

    def test_switching_account_does_not_borrow_either_sidecar(self):
        accounts.switch(self.root, self.b.key)
        value = self.engine.dispatch('home.summary', {})
        for key in ('roster', 'affinity'):
            self.assertFalse(value[key]['available'])
            self.assertEqual(value[key]['count'], 0)
            self.assertEqual(value[key]['portraits'], [])
        self.assertEqual(value['recentFive'], [])

    def test_corrupt_and_mismatched_sidecars_do_not_hide_other_summaries(self):
        roster.cache_path(self.root, self.a.uid).write_text('{bad', encoding='utf-8')
        wrong = {'version': 1, 'uid': self.b.uid, 'entries': []}
        affinity.cache_path(self.root, self.a.uid).write_text(json.dumps(wrong), encoding='utf-8')
        value = self.engine.dispatch('home.summary', {})
        self.assertIn('error', value['roster'])
        self.assertIn('error', value['affinity'])
        self.assertEqual(len(value['recentFive']), 1)

    def test_summary_limits_portraits_and_keeps_full_details_out_of_response(self):
        roster.save_cache(self.root, self.a.uid, [roster.Character(1000+i, '旅人', i, 0, False) for i in range(500)])
        value = self.engine.dispatch('home.summary', {})
        self.assertEqual(value['roster']['count'], 500)
        self.assertEqual(len(value['roster']['portraits']), 3)
        self.assertEqual(value['roster']['portraits'][0]['level'], 499)
        self.assertNotIn('characters', value['roster'])
        self.assertLess(len(json.dumps(value)), 4000)
