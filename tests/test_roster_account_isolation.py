import json
import tempfile
import unittest
from pathlib import Path

from stellasora_toolkit import accounts, roster, service
from stellasora_toolkit.application import Application
from stellasora_toolkit.desktop_engine import Engine


class RosterIsolationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)/'中文 空格'
        self.app = Application(self.output, offline=True)
        self.a = accounts.create(self.output, uid='100000001', name='A')
        self.b = accounts.create(self.output, uid='100000002', name='B')
        self.hero = roster.Character(130, '多娜', 90, 8, True)
        roster.save_cache(self.output, self.a.uid, [self.hero])

    def test_known_account_without_cache_never_uses_another_account(self):
        accounts.switch(self.output, self.b.key)
        result = service.load_roster(self.output)
        self.assertEqual(result['uid'], self.b.uid)
        self.assertEqual(result['characters'], [])
        self.assertEqual(Path(result['path']).resolve(), roster.cache_path(self.output, self.b.uid).resolve())

    def test_unknown_account_only_reads_unverified_cache(self):
        unknown = accounts.create(self.output, name='未绑定')
        accounts.switch(self.output, unknown.key)
        self.assertEqual(service.load_roster(self.output)['characters'], [])
        roster.save_cache(self.output, '', [self.hero])
        self.assertEqual(service.load_roster(self.output)['uid'], '')
        self.assertEqual(len(service.load_roster(self.output)['characters']), 1)

    def test_mismatched_or_corrupt_cache_is_preserved_without_fallback(self):
        accounts.switch(self.output, self.b.key)
        path = roster.cache_path(self.output, self.b.uid)
        for content in ('{broken', json.dumps({'version': 1, 'uid': self.a.uid, 'characters': [self.hero.as_dict()]})):
            path.write_text(content, encoding='utf-8')
            original = path.read_bytes()
            self.assertEqual(service.load_roster(self.output)['characters'], [])
            self.assertEqual(path.read_bytes(), original)

    def test_nested_cache_fields_are_normalized_without_rewriting(self):
        path = roster.cache_path(self.output, self.a.uid)
        entry = self.hero.as_dict()
        entry.update(potentials=[1], talent={'nodes': 12, 'names': {'bad': 'shape'}},
                     skills=None, slots=42, emblems=[{'slot': 1, 'name': '旧缓存纹章'}])
        path.write_text(json.dumps({'uid': self.a.uid, 'characters': [entry]}), encoding='utf-8')
        original = path.read_bytes()
        item = roster.load_cache(path)['characters'][0]
        self.assertEqual(item['potentials'], {})
        self.assertEqual(item['talent']['nodes'], [])
        self.assertEqual(item['slots'], [])
        self.assertEqual(item['emblems'][0]['upgrades'], [])
        self.assertEqual(item['emblems'][0]['skillAffixes'], [])
        self.assertEqual(path.read_bytes(), original)

    def test_bad_numeric_entries_do_not_hide_valid_characters(self):
        path = roster.cache_path(self.output, self.a.uid)
        malformed = self.hero.as_dict()
        malformed['emblems'] = [{'slot': 1, 'attrs': [{'value': float('inf')}]}]
        path.write_text(json.dumps({'uid': self.a.uid, 'characters': [malformed, self.hero.as_dict()]}), encoding='utf-8')
        self.assertEqual(len(roster.load_cache(path)['characters']), 1)

    def test_engine_loads_each_account_without_mutating_the_archive(self):
        archive = self.output/f'{self.a.uid}.json'
        archive.write_text(json.dumps({'uid': self.a.uid, 'categories': {'1': [{'Gid': 10162, 'Time': 100, 'Ids': [103]}]}}), encoding='utf-8')
        before = archive.read_bytes()
        engine = Engine(self.output, self.output, lambda _event: None, offline=True)
        accounts.switch(self.output, self.a.key)
        self.assertEqual(len(engine.dispatch('roster.load', {})['characters']), 1)
        accounts.switch(self.output, self.b.key)
        self.assertEqual(engine.dispatch('roster.load', {})['characters'], [])
        self.assertEqual(archive.read_bytes(), before)
