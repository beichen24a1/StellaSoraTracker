"""Independent calendar adapter for public Stella Sora CN announcements."""
from __future__ import annotations

import hashlib
import io
import json
import math
import re
import threading
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from PIL import Image

from .archive_layout import write_atomic

ORIGIN = 'https://stellasora.yostar.cn'
ASSET_HOSTS = frozenset({'stellasora.yostar.cn', 'webusstatic.yo-star.com', 'webstatic.yo-star.com'})
FRESH_SECONDS = 15 * 60
RECENT_SECONDS = 14 * 86400
CN_TIME = timezone(timedelta(hours=8))
KINDS = frozenset({'version', 'event', 'permanent', 'recruit'})
DATE = re.compile(r'(\d{4})[年./-](\d{1,2})[月./-](\d{1,2})日?')
CLOCK = re.compile(r'^\s*(\d{1,2})[:：](\d{2})')


class _ArticleText(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.images = []
        self.hidden = 0

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.hidden += 1
        if tag in ('p', 'div', 'br', 'li'):
            self.parts.append('\n')
        if tag == 'img' and not self.hidden:
            self.images.append(dict(attrs).get('src', ''))

    def handle_endtag(self, tag):
        if tag in ('script', 'style') and self.hidden:
            self.hidden -= 1

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def article_text(value):
    parser = _ArticleText()
    parser.feed(str(value or '')[:2_000_000])
    return re.sub(r'\\[nr]', ' ', ''.join(parser.parts)), parser.images


def safe_asset_url(value):
    if not isinstance(value, str):
        return ''
    try:
        parsed = urlsplit(value)
        return value if (parsed.scheme == 'https' and parsed.hostname in ASSET_HOSTS
                         and parsed.port in (None, 443) and not parsed.username and not parsed.password) else ''
    except ValueError:
        return ''


class _OfficialRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not safe_asset_url(newurl):
            raise ValueError('官网资源重定向到了不支持的地址')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _read_http(url, limit, deadline):
    if not safe_asset_url(url):
        raise ValueError('不支持的官网资源地址')
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError('读取活动日历超时')
    request = Request(url, headers={'Referer': ORIGIN+'/', 'User-Agent': 'Mozilla/5.0 StellaSoraTracker'})
    with build_opener(_OfficialRedirect()).open(request, timeout=min(8, remaining)) as response:
        body = response.read(limit+1)
    if len(body) > limit:
        raise ValueError('官网资源超过大小限制')
    return body


def _read_json(url, deadline):
    payload = json.loads(_read_http(url, 3_000_000, deadline).decode('utf-8-sig'))
    if not isinstance(payload, dict) or payload.get('code') not in (0, 200):
        raise ValueError('官网暂未返回有效活动数据')
    return payload.get('data') or {}


def _window(text):
    labels = [text.find(label) for label in ('活动时间', '开放时间', '招募时间', '活动期间')]
    positions = [position for position in labels if position >= 0]
    section = text[min(positions):min(positions)+350] if positions else text
    dates = list(DATE.finditer(section))
    for first, last in zip(dates, dates[1:]):
        between = section[first.end():last.start()]
        if not re.search(r'[~～至—–-]', between):
            continue
        start_clock = CLOCK.match(between)
        end_clock = CLOCK.match(section[last.end():])
        if not end_clock:
            continue  # Do not invent an end time from a date-only announcement.
        try:
            start = datetime(*map(int, first.groups()),
                             *(map(int, start_clock.groups()) if start_clock else (0, 0)), tzinfo=CN_TIME)
            end = datetime(*map(int, last.groups()), *map(int, end_clock.groups()), tzinfo=CN_TIME)
        except ValueError:
            continue
        if end > start:
            # Announcements specify the final minute, not its first second.
            return int(start.timestamp()), int(end.timestamp())+60, not bool(start_clock)
    return None


def parse_announcement(row):
    if not isinstance(row, dict) or type(row.get('id')) is not int or not 0 < row['id'] < 1_000_000_000:
        return None
    title = ' '.join(article_text(row.get('title'))[0].split())[:200]
    if not any(word in title for word in ('活动', '招募', '灾变防线', '猎影合围')):
        return None
    if any(word in title for word in ('维护公告', '商品', '上新', '礼包', '充值', '兑换码', '问卷', '补偿', '预告')):
        return None
    text = article_text(row.get('description') or row.get('content'))[0]
    window = _window(text)
    if not window:
        return None
    kind = 'recruit' if '招募' in title else 'version' if '一览' in title else 'event'
    if any(name in title for name in ('灾变防线', '猎影合围', '创业激励基金')):
        kind = 'permanent'
    name = title
    for opening, closing in (('「', '」'), ('【', '】'), ('[', ']'), ('《', '》')):
        if title.startswith(opening) and closing in title:
            name = title[1:title.index(closing)].strip()
            break
    start, end, approximate = window
    return {'id': row['id'], 'name': name, 'title': title, 'kind': kind,
            'startAt': start, 'endAt': end, 'startApproximate': approximate,
            'description': ' '.join(text.split())[:260], 'cover': '',
            'thumbnail': safe_asset_url(row.get('thumbnail')), 'url': f'{ORIGIN}/news/{row["id"]}'}


class OfficialCalendar:
    def __init__(self, application):
        self.app = application
        self.directory = application.output/'calendar'
        self.images = self.directory/'images'
        self.cache = self.directory/'index.json'
        self.lock = threading.RLock()
        self.image_gate = threading.Lock()
        self.loading = False
        self.error = ''
        self.updated = 0
        self.items = []
        self.cancelled = threading.Event()
        self._restore()

    def _restore(self):
        try:
            if self.cache.stat().st_size > 1_500_000:
                return
            data = json.loads(self.cache.read_text('utf-8'))
            stamp = data['updatedAt']
            if type(stamp) not in (int, float) or not math.isfinite(stamp) or not 0 < stamp <= time.time()+86400:
                return
            items = data['items']
            if not isinstance(items, list) or len(items) > 120:
                return
            for item in items:
                if (not isinstance(item, dict) or type(item.get('id')) is not int
                        or not 0 < item['id'] < 1_000_000_000 or item.get('kind') not in KINDS
                        or type(item.get('startAt')) is not int or type(item.get('endAt')) is not int
                        or not 0 < item['startAt'] < item['endAt'] < 40_000_000_000):
                    raise ValueError('活动缓存格式无效')
                for field in ('name', 'title', 'description'):
                    if not isinstance(item.get(field), str) or len(item[field]) > 1000:
                        raise ValueError('活动缓存格式无效')
                item['url'] = f'{ORIGIN}/news/{item["id"]}'
                item['startApproximate'] = item.get('startApproximate') is True
                if not re.fullmatch(r'[a-f0-9]{64}\.webp', str(item.get('cover', ''))):
                    item['cover'] = ''
            self.items, self.updated = items, int(stamp)
        except (OSError, ValueError, KeyError, TypeError):
            pass

    def snapshot(self):
        with self.lock:
            items = []
            for item in self.items:
                if item['endAt'] < time.time()-RECENT_SECONDS:
                    continue
                value = {key: item[key] for key in ('id', 'name', 'title', 'kind', 'startAt', 'endAt',
                                                    'startApproximate', 'description', 'url')}
                image = self.images/item['cover'] if item.get('cover') else None
                try:
                    value['cover'] = f'app://calendar/{image.name}?v={image.stat().st_mtime_ns}' if image and image.is_file() else ''
                except OSError:
                    value['cover'] = ''
                items.append(value)
            return {'items': items, 'updatedAt': self.updated, 'loading': self.loading,
                    'stale': bool(self.updated and (self.error or time.time()-self.updated > FRESH_SECONDS)),
                    'error': self.error, 'offline': self.app.offline, 'source': '星塔旅人国服官网', 'sourceUrl': ORIGIN}

    def publish(self):
        self.app.emit({'type': 'event', 'name': 'calendar', 'payload': self.snapshot()})

    def _cover(self, item, deadline):
        if self.cancelled.is_set():
            return item
        url = item.get('thumbnail', '')
        try:
            data = _read_json(f'{ORIGIN}/api/resource/news/{item["id"]}', deadline)
            content = (data.get('news') or {}).get('content', '')
            candidates = article_text(content)[1]
            url = next((safe_asset_url(value) for value in candidates if safe_asset_url(value)), url)
        except Exception:
            pass  # The official list thumbnail is a useful fallback.
        if not url or self.cancelled.is_set():
            return item
        name = hashlib.sha256(url.encode('utf-8')).hexdigest()+'.webp'
        target = self.images/name
        try:
            if not target.is_file() or time.time()-target.stat().st_mtime > 86400:
                body = _read_http(url, 8_000_000, deadline)
                # Network requests stay parallel. Serialize Pillow's lazy plugin
                # initialization and replacements of covers shared by articles.
                with self.image_gate:
                    with Image.open(io.BytesIO(body)) as image:
                        if image.width * image.height > 32_000_000:
                            raise ValueError('活动图片过大')
                        image.thumbnail((1800, 1100))
                        rendered = io.BytesIO()
                        image.convert('RGB').save(rendered, format='WEBP', quality=86)
                    self.images.mkdir(parents=True, exist_ok=True)
                    with tempfile.NamedTemporaryFile(dir=self.images, suffix='.tmp', delete=False) as handle:
                        handle.write(rendered.getvalue())
                        temporary = Path(handle.name)
                    try:
                        temporary.replace(target)
                    finally:
                        temporary.unlink(missing_ok=True)
            item['cover'] = name
        except Exception:
            pass
        return item

    def refresh(self, *, force=False):
        with self.lock:
            if self.loading:
                return {'loading': True}
            if self.app.offline:
                self.error = '离线模式，显示已保存的活动日历。' if self.updated else '离线模式下尚无活动缓存，请联网后刷新。'
                self.publish()
                return {'cached': True}
            if not force and self.updated and not self.error and time.time()-self.updated < FRESH_SECONDS:
                self.publish()
                return {'cached': True}
            self.loading = True
            self.error = ''
            self.cancelled.clear()
            self.publish()

        def work(progress, _operation):
            try:
                deadline = time.monotonic()+50
                rows = {}
                for page in range(1, 9):
                    if self.cancelled.is_set():
                        raise InterruptedError('活动刷新已停止')
                    progress(f'正在读取官网活动公告（第 {page} 页）')
                    data = _read_json(f'{ORIGIN}/api/resource/news?index={page}', deadline)
                    batch = data.get('rows')
                    if not isinstance(batch, list):
                        raise ValueError('官网活动列表格式变化')
                    if not batch:
                        break
                    previous = len(rows)
                    for row in batch:
                        if isinstance(row, dict) and type(row.get('id')) is int:
                            rows[row['id']] = row
                    if len(rows) == previous:
                        break
                if not rows:
                    raise ValueError('官网活动列表暂不可用')
                parsed = [item for row in rows.values() if (item := parse_announcement(row))]
                if not parsed:
                    raise ValueError('暂未识别出公告中的活动时间，请查看官网公告')
                unique = {}
                for item in parsed:
                    if item['endAt'] >= time.time()-RECENT_SECONDS:
                        key = (item['name'], item['kind'], item['startAt'], item['endAt'])
                        if key not in unique or item['id'] > unique[key]['id']:
                            unique[key] = item
                items = sorted(unique.values(), key=lambda item: (item['startAt'], item['id']))[:100]
                progress('正在缓存活动主视觉与封面')
                with ThreadPoolExecutor(max_workers=4) as pool:
                    items = list(pool.map(lambda item: self._cover(item, deadline), items))
                if self.cancelled.is_set():
                    raise InterruptedError('活动刷新已停止')
                stamp = int(time.time())
                write_atomic(self.cache, {'version': 1, 'updatedAt': stamp, 'items': items})
                with self.lock:
                    self.items, self.updated = items, stamp
                progress(f'已更新 {len(items)} 项官网活动')
            except Exception:
                with self.lock:
                    self.error = '暂时无法获取官网活动，请重试。' + ('已保留上次日历。' if self.updated else '也可直接查看官网公告。')
                raise
            finally:
                with self.lock:
                    self.loading = False
                self.publish()
        return self.app.job('刷新活动日历', work, exclusive=False)
