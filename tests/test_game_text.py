# -*- coding: utf-8 -*-
"""游戏内存配置表补名: 纯解析 + 注册范围 + 应用层接线。

真实读取需要游戏在跑且管理员权限, 所以这里用假的内存文本表/假的进程对象验证逻辑;
真机验证靠 tools/probe_texts.py(它已经把 key 规则打出来了: Item.<id>.1 是名字)。
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from stellasora_toolkit import catalog, game_text, server_config
from stellasora_toolkit.application import Application

UNKNOWN_TRAVELER = 163          # 161 优叶已进静态表, 163 仍是"前向兼容"的未知序号
UNKNOWN_DISC = 214070


class ItemTextParsingTests(unittest.TestCase):
    def test_only_name_keys_are_kept(self):
        # Item.<id>.1 是名字, .2/.3 是描述; 其它表(Talent/UIText)不能被当成物品名
        texts = {
            "Item.161.1": "优叶",
            "Item.161.2": "攻击力提升<color=#0abec5>&Param1&</color>",
            "Item.214068.1": "帐幕下的酣梦",
            "Item.214068.3": "描述文本",
            "Talent.1610580.1": "沃野上的印痕",
            "UIText.TopBar_Energy_Limit.1": "今日剩余购买次数",
            "Item.abc.1": "坏 key",
        }
        self.assertEqual(game_text.item_names_from_texts(texts), {161: "优叶", 214068: "帐幕下的酣梦"})

    def test_rich_text_is_cleaned(self):
        self.assertEqual(game_text.clean_name("<color=#fff>帐幕</color>下的酣梦"), "帐幕下的酣梦")
        self.assertEqual(game_text.clean_name("造成 &Param1& 点伤害"), "造成 … 点伤害")
        self.assertEqual(game_text.clean_name(None), "")

    def test_read_item_names_filters_requested_ids(self):
        texts = {"Item.161.1": "优叶", "Item.214068.1": "帐幕下的酣梦", "Item.214069.1": "紧急救援"}
        with mock.patch.object(game_text.roster, "find_config_registry", return_value=0x1000), \
                mock.patch.object(game_text.roster, "config_table_texts", return_value=texts):
            names = game_text.read_item_names(object(), lua=object(), only={161, 214070})
        self.assertEqual(names, {161: "优叶"})

    def test_missing_item_ids(self):
        self.assertEqual(game_text.missing_item_ids([161, 163, 214068], catalog.gacha_item_name), {163})

    def test_unreachable_config_table_returns_empty(self):
        with mock.patch.object(game_text.roster, "find_config_registry", return_value=None):
            self.assertEqual(game_text.read_item_names(object(), lua=object()), {})


class RegisterNamesTests(unittest.TestCase):
    def setUp(self):
        self._saved = {
            item_id: (catalog.TRAVELER_NAMES.get(item_id), catalog.FIVE_STAR_DISCS.get(item_id))
            for item_id in (UNKNOWN_TRAVELER, UNKNOWN_DISC, 2501056)
        }

    def tearDown(self):
        for item_id, (traveler_name, disc_name) in self._saved.items():
            if traveler_name is None:
                catalog.TRAVELER_NAMES.pop(item_id, None)
            else:
                catalog.TRAVELER_NAMES[item_id] = traveler_name
            if disc_name is None:
                catalog.FIVE_STAR_DISCS.pop(item_id, None)
                catalog.DISC_NAMES.pop(item_id, None)
            else:
                catalog.FIVE_STAR_DISCS[item_id] = disc_name
            catalog.FIVE_STAR_TRAVELERS.discard(item_id)
            catalog.FIVE_STAR_ITEMS.discard(item_id)

    def test_registers_only_gacha_ranges(self):
        names = {UNKNOWN_TRAVELER: "测试旅人", UNKNOWN_DISC: "测试秘纹", 2501056: "皮肤名"}
        registered = game_text.register_names(names)
        self.assertEqual([item_id for item_id, _kind, _name in registered], [UNKNOWN_TRAVELER, UNKNOWN_DISC])
        self.assertEqual(catalog.gacha_item_name(UNKNOWN_TRAVELER), "测试旅人")
        self.assertEqual(catalog.gacha_item_kind(UNKNOWN_TRAVELER), "traveler")
        self.assertEqual(catalog.gacha_item_name(UNKNOWN_DISC), "测试秘纹")
        self.assertEqual(catalog.gacha_item_kind(UNKNOWN_DISC), "disc")
        # 皮肤/天赋之类的 id 不能被塞进抽卡目录
        self.assertNotIn(2501056, catalog.TRAVELER_NAMES)
        self.assertNotIn(2501056, catalog.DISC_NAMES)


class ApplicationMemoryNamesTests(unittest.TestCase):
    """抓完抽卡, 先吃内存配置表再决定要不要联网。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.app = Application(self.root/'exports', None, offline=True)
        self.addCleanup(catalog.TRAVELER_NAMES.pop, UNKNOWN_TRAVELER, None)
        self.addCleanup(catalog.FIVE_STAR_TRAVELERS.discard, UNKNOWN_TRAVELER)
        self.addCleanup(catalog.FIVE_STAR_ITEMS.discard, UNKNOWN_TRAVELER)
        previous = server_config.active().key
        self.addCleanup(server_config.set_active, previous)

    def _import(self, ids):
        path = self.root/'incoming.json'
        path.write_text(json.dumps({'version': 1, 'uid': '100000001',
                                    'categories': {'1': [{'Gid': 10162, 'Time': 100, 'Ids': ids}]}}),
                        encoding='utf-8')
        self.app.import_files([str(path)], lambda _message: None)

    def test_unknown_ids_are_named_from_game_memory(self):
        self._import([UNKNOWN_TRAVELER])
        logger = []
        with mock.patch.object(game_text, 'read_item_names', return_value={UNKNOWN_TRAVELER: '测试旅人'}), \
                mock.patch('stellasora_toolkit.application.RemoteProcess') as process:
            process.return_value.__enter__.return_value = object()
            self.app.sync_resources(logger.append, pid=4242)
        self.assertEqual(catalog.gacha_item_name(UNKNOWN_TRAVELER), '测试旅人')
        self.assertTrue(any('游戏配置表' in line for line in logger))

    def test_known_records_do_not_touch_memory(self):
        self._import([161, 214068])
        with mock.patch.object(game_text, 'read_item_names',
                               side_effect=AssertionError('序号都认识时不该读内存')):
            self.app.sync_resources(lambda _message: None)
        self.assertEqual(catalog.gacha_item_name(161), '优叶')

    def test_switch_during_read_is_discarded_and_reread(self):
        """review #45 P2: 读取期间切服务器, 旧语言结果不能注册进去。"""
        self._import([UNKNOWN_TRAVELER])
        server_config.set_active('cn')
        seen = []

        def fake_read(_process, only=None):
            seen.append(server_config.active().key)
            if len(seen) == 1:
                server_config.set_active('jp')      # 读完前用户切到了日服
                return {UNKNOWN_TRAVELER: '旧语言名称'}
            return {UNKNOWN_TRAVELER: '新语言名称'}

        logger = []
        with mock.patch.object(game_text, 'read_item_names', side_effect=fake_read), \
                mock.patch('stellasora_toolkit.application.RemoteProcess') as process:
            process.return_value.__enter__.return_value = object()
            self.app.sync_resources(logger.append, pid=4242)
        self.assertEqual(seen, ['cn', 'jp'], '切换后必须按新语言重读一次')
        self.assertEqual(catalog.gacha_item_name(UNKNOWN_TRAVELER), '新语言名称')
        self.assertFalse(any('旧语言名称' == value for value in catalog.TRAVELER_NAMES.values()))

    def test_endless_switch_registers_nothing(self):
        self._import([UNKNOWN_TRAVELER])
        server_config.set_active('cn')

        def fake_read(_process, only=None):
            server_config.set_active('jp' if server_config.active().key == 'cn' else 'cn')
            return {UNKNOWN_TRAVELER: '错语言名称'}

        with mock.patch.object(game_text, 'read_item_names', side_effect=fake_read), \
                mock.patch('stellasora_toolkit.application.RemoteProcess') as process:
            process.return_value.__enter__.return_value = object()
            self.app.sync_resources(lambda _message: None, pid=4242)
        self.assertEqual(catalog.gacha_item_name(UNKNOWN_TRAVELER), '旅人 #163',
                         '语言一直在变时宁可留着占位符, 也不能登记错语言的名称')


if __name__ == '__main__':
    unittest.main()
