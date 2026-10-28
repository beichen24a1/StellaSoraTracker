import io
import json
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image

from stellasora_toolkit.desktop_engine import Engine
from stellasora_toolkit.official_events import OfficialCalendar, ORIGIN, article_text, parse_announcement, safe_asset_url


def row(identifier=100, title='「星之砂」活动说明', dates='2026/10/27 12:00 ~ 2026/11/17 10:59'):
    return {'id': identifier, 'title': title, 'description': '<p>活动时间</p>'+dates,
            'thumbnail': 'https://webusstatic.yo-star.com/test.jpg'}


class ParsingTests(unittest.TestCase):
    def test_official_time_is_china_time_and_includes_last_minute(self):
        item = parse_announcement(row())
        self.assertEqual(item['name'], '星之砂')
        self.assertEqual(datetime.fromtimestamp(item['startAt'], timezone.utc).isoformat(), '2026-10-27T04:00:00+00:00')
        self.assertEqual(datetime.fromtimestamp(item['endAt'], timezone.utc).isoformat(), '2026-11-17T03:00:00+00:00')
        self.assertFalse(item['startApproximate'])

    def test_maintenance_time_is_explicitly_approximate(self):
        item = parse_announcement(row(dates='2026年10月20日 维护结束后至2026年11月03日 03:59'))
        self.assertTrue(item['startApproximate'])

    def test_primary_period_excludes_reward_claiming_dates(self):
        item = parse_announcement(row(dates='2026/10/27 12:00~2026/11/17 10:59 奖励领取时间2026/11/17 11:00~2026/11/24 10:59'))
        self.assertEqual(item['endAt'], parse_announcement(row())['endAt'])

    def test_invalid_or_unrelated_announcements_are_not_events(self):
        for value in [None, [], row(True), row(title='充值活动'), row(title='维护公告活动'),
                      row(dates='2026/10/27 ~ 2026/11/17'), row(dates='2026/11/17 12:00~2026/10/27 10:59'),
                      row(dates='2026/20/27 12:00~2026/11/17 10:59')]:
            self.assertIsNone(parse_announcement(value))

    def test_recruitment_is_not_conflated_with_same_named_event(self):
        self.assertEqual(parse_announcement(row(title='「星之砂」限时招募开启'))['kind'], 'recruit')
        self.assertEqual(parse_announcement(row(title='「灾变防线」活动说明'))['kind'], 'permanent')
        self.assertEqual(parse_announcement(row(title='「星之砂」版本活动一览'))['kind'], 'version')

    def test_untrusted_html_is_reduced_to_plain_text(self):
        text, images = article_text('<script>SECRET</script><p>活动 &amp; 时间</p><img src="https://evil.test/a">')
        self.assertNotIn('SECRET', text)
        self.assertIn('活动 & 时间', text)
        self.assertEqual(images, ['https://evil.test/a'])

    def test_url_allowlist_rejects_credentials_ports_and_malformed_hosts(self):
        for address in ['http://stellasora.yostar.cn/a', 'https://stellasora.yostar.cn.evil.test/a',
                        'https://user@stellasora.yostar.cn/a', 'https://stellasora.yostar.cn:80/a',
                        'https://stellasora.yostar.cn:invalid/a', 'https://[broken', None]:
            self.assertEqual(safe_asset_url(address), '')
        self.assertEqual(safe_asset_url(ORIGIN+'/news/1'), ORIGIN+'/news/1')


class CalendarTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)/'中文 空格'
        clock = patch('stellasora_toolkit.official_events.time.time', return_value=1793156400)
        clock.start()
        self.addCleanup(clock.stop)
        self.events = []
        self.failures = []
        self.app = SimpleNamespace(output=self.output, emit=self.events.append, offline=False, job=self.job)
        self.calendar = OfficialCalendar(self.app)

    def job(self, _label, work, **_kwargs):
        try:
            work(lambda _message: None, 'test')
        except Exception as error:
            self.failures.append(error)
        return {'operationId': 'test'}

    def refresh(self, rows):
        def read(url, _deadline):
            return {'rows': rows if 'index=1' in url else []}
        with patch('stellasora_toolkit.official_events._read_json', side_effect=read), patch.object(self.calendar, '_cover', side_effect=lambda item, _deadline: item):
            self.calendar.refresh(force=True)

    def test_refresh_deduplicates_and_caches_without_account_data(self):
        self.refresh([row(), row(101), row(102, title='「星之砂」限时招募开启')])
        self.assertFalse(self.failures)
        self.assertEqual(len(self.calendar.items), 2)
        self.assertEqual({item['kind'] for item in self.calendar.items}, {'event', 'recruit'})
        restored = OfficialCalendar(self.app)
        self.assertEqual(len(restored.snapshot()['items']), 2)
        self.assertTrue(restored.updated)
        self.assertFalse((self.output/'accounts.json').exists())
        self.assertEqual(self.events[-1]['name'], 'calendar')
        self.assertFalse(self.events[-1]['payload']['loading'])

    def test_failure_and_offline_preserve_previous_cache(self):
        self.refresh([row()])
        original = self.calendar.cache.read_bytes()
        with patch('stellasora_toolkit.official_events._read_json', side_effect=OSError('offline')):
            self.calendar.refresh(force=True)
        self.assertEqual(self.calendar.cache.read_bytes(), original)
        self.assertEqual(len(self.calendar.snapshot()['items']), 1)
        self.assertTrue(self.calendar.snapshot()['stale'])
        self.app.offline = True
        with patch('stellasora_toolkit.official_events._read_http') as network:
            self.calendar.refresh(force=True)
            network.assert_not_called()
        self.assertTrue(self.calendar.snapshot()['offline'])

    def test_fresh_cache_does_not_requery_and_duplicate_refresh_is_ignored(self):
        self.refresh([row()])
        with patch('stellasora_toolkit.official_events._read_http') as network:
            self.assertTrue(self.calendar.refresh()['cached'])
            self.calendar.loading = True
            self.assertTrue(self.calendar.refresh(force=True)['loading'])
            network.assert_not_called()

    def test_corrupt_and_unsafe_cache_are_not_trusted(self):
        self.calendar.cache.parent.mkdir(parents=True)
        for data in [[], {'updatedAt': float('inf'), 'items': []}, {'updatedAt': time.time(), 'items': [{}]}]:
            self.calendar.cache.write_text(json.dumps(data), encoding='utf-8')
            self.assertFalse(OfficialCalendar(self.app).items)
        item = parse_announcement(row())
        item.pop('startApproximate')
        item['cover'] = '../../secrets'
        item['url'] = 'https://evil.test'
        self.calendar.cache.write_text(json.dumps({'updatedAt': time.time(), 'items': [item]}), encoding='utf-8')
        safe = OfficialCalendar(self.app).snapshot()['items'][0]
        self.assertEqual(safe['cover'], '')
        self.assertEqual(safe['url'], ORIGIN+'/news/100')
        self.assertFalse(safe['startApproximate'])

    def test_shared_cover_concurrency_uses_atomic_unique_temporary_files(self):
        image = io.BytesIO()
        Image.new('RGB', (40, 20)).save(image, 'PNG')
        with patch('stellasora_toolkit.official_events._read_json', return_value={}), patch('stellasora_toolkit.official_events._read_http', return_value=image.getvalue()):
            with ThreadPoolExecutor(max_workers=4) as pool:
                items = list(pool.map(lambda index: self.calendar._cover(parse_announcement(row(index+1)), time.monotonic()+10), range(4)))
        self.assertTrue(all(item['cover'] for item in items))
        self.assertEqual(len(list(self.calendar.images.glob('*.webp'))), 1)
        self.assertEqual(list(self.calendar.images.glob('*.tmp')), [])

    def test_engine_exposes_calendar_without_changing_account_or_server(self):
        engine = Engine(self.output, self.output, self.events.append, offline=True)
        before = engine.dispatch('app.state', {})
        self.assertEqual(engine.dispatch('calendar.get', {})['items'], [])
        engine.dispatch('calendar.refresh', {'force': True})
        after = engine.dispatch('app.state', {})
        for key in ('accounts', 'activeAccount', 'server', 'summary'):
            self.assertEqual(before[key], after[key])
        engine.dispatch('app.shutdown', {})
        self.assertTrue(engine.calendar.cancelled.is_set())


if __name__ == '__main__':
    unittest.main()
