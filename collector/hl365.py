"""hl365(黑料不打烊)采集器:RSS 全文 → 清洗 → 图片入对象存储 → 元数据入库。

RSS feed 直接带 content:encoded 全文(2026-09-19 实测,修正了侦察档案
"无全文"的结论),文章页抓取仅作后续兜底,当前不实现。

用法:.venv/bin/python -m collector.hl365 [--pages N]
增量幂等:同一文章标题与内容指纹均未变化时跳过;图片按源 URL 哈希落盘。
"""
import argparse
import hashlib
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
from urllib.parse import urljoin

from collector import clean, fetch, typecho
from collector.config import load_config
from collector.store import Database, ObjectStore, sha16

SOURCE = 'hl365'
_ARTICLE_ID_RE = re.compile(r'/archives/(\d+)\.html')
_POST_CARD_ID_RE = re.compile(r'post-card-(\d+)')
_CONTENT_NS = '{http://purl.org/rss/1.0/modules/content/}encoded'


def parse_feed(xml_bytes):
    """解析 RSS 2.0,返回条目字典列表。"""
    root = ET.fromstring(xml_bytes)
    items = []
    for item in root.iter('item'):
        def text(tag):
            node = item.find(tag)
            return (node.text or '').strip() if node is not None else ''

        link = text('link')
        m = _ARTICLE_ID_RE.search(link)
        if not m:
            continue
        items.append({
            'article_key': m.group(1),
            'url': link,
            'title': text('title'),
            'summary': text('description'),
            'published_at': _to_iso(text('pubDate')),
            'content_html': (item.find(_CONTENT_NS).text or '')
            if item.find(_CONTENT_NS) is not None else '',
        })
    return items


def _to_iso(rfc822):
    if not rfc822:
        return None
    try:
        return parsedate_to_datetime(rfc822).strftime('%Y-%m-%dT%H:%M:%SZ')
    except (TypeError, ValueError):
        return None


def _iso_utc(text):
    if not text:
        return None
    try:
        return datetime.fromisoformat(text).astimezone(
            timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except ValueError:
        return None


def parse_home_list(html, base_url):
    """解析首页列表卡片,供 RSS 漏条兜底。

    卡片结构:article > a[href=/archives/<id>.html] > .post-card#post-card-<id>。
    标题取 .post-card-bottom-title(卡内 .post-card-title 是"热搜 HOT"栏目位,
    不是文章标题);时间取 span[itemprop=datePublished] 的 content。
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    items, seen = [], set()
    for card in soup.select('.post-card'):
        m = _POST_CARD_ID_RE.search(card.get('id') or '')
        if not m or m.group(1) in seen:
            continue
        a = card.find_parent('a', href=_ARTICLE_ID_RE)
        if a is None:
            continue
        title_el = (card.select_one('.post-card-bottom-title')
                    or card.select_one('.post-card-title'))
        title = title_el.get_text(' ', strip=True) if title_el else ''
        if len(title) < 6 or title == '热搜 HOT':
            continue
        time_el = card.select_one('span[itemprop="datePublished"]')
        published = _iso_utc(time_el.get('content', '')) if time_el else None
        seen.add(m.group(1))
        items.append({
            'article_key': m.group(1),
            'url': urljoin(base_url, a['href']),
            'title': title,
            'published_at': published,
            'summary': '',
        })
    return items


def download_images(urls, article_key, store, source=SOURCE):
    """下载图片入对象存储,key 由源 URL 哈希导出(重跑幂等)。

    返回 [{source_url, key}];单图失败不阻断采集,只记录告警。
    """
    images = []
    for url in urls:
        digest = hashlib.sha256(url.encode('utf-8')).hexdigest()[:12]
        key = f'{source}/{article_key}/img-{digest}.{clean.img_ext(url)}'
        if store.exists(key):
            images.append({'source_url': url, 'key': key})
            continue
        try:
            resp = fetch.get(url)
            resp.raise_for_status()
            ext = clean.img_ext(url, resp.headers.get('Content-Type'))
            key = f'{source}/{article_key}/img-{digest}.{ext}'
            store.put(key, resp.content)
            images.append({'source_url': url, 'key': key})
        except Exception as exc:  # noqa: BLE001 单图失败继续
            print(f'  [warn] 图片下载失败 {url}: {exc}', file=sys.stderr)
            images.append({'source_url': url, 'key': ''})
    return images


def collect(pages=1):
    site = load_config()['sites'][SOURCE]
    db = Database()
    store = ObjectStore()

    stats = {'new': 0, 'updated': 0, 'skipped': 0,
             'home_new': 0, 'home_failed': 0}
    seen = 0
    first_keys = set()
    feed_keys = set()
    for page in range(1, pages + 1):
        feed_url = site['home'].rstrip('/') + site['feed_path']
        if page > 1:
            feed_url += f'/?paged={page}'
        resp = fetch.get(feed_url)
        resp.raise_for_status()
        items = parse_feed(resp.content)
        if not items:
            break
        # 实测 ?paged=N 无效(返回同一页),靠内容判定防止重复处理
        if items[0]['article_key'] in first_keys:
            print(f'  第 {page} 页与之前内容重复,停止翻页')
            items = [it for it in items if it['article_key'] not in first_keys]
            if not items:
                break
        first_keys.update(it['article_key'] for it in items)
        feed_keys.update(it['article_key'] for it in items)
        seen += len(items)

        for entry in items:
            cleaned, image_urls = clean.clean_html(entry['content_html'])
            title_hash = sha16(entry['title'])
            content_hash = sha16(clean.clean_text(cleaned))
            old = db.find(SOURCE, entry['article_key'])
            if old and old['title_hash'] == title_hash \
                    and old['content_hash'] == content_hash:
                stats['skipped'] += 1
                continue

            images = download_images(image_urls, entry['article_key'], store)
            html_stored = cleaned
            for img in images:
                if img['key']:
                    html_stored = html_stored.replace(
                        f'src="{img["source_url"]}"', f'src="{img["key"]}"')
            payload = {
                'source': SOURCE,
                'article_key': entry['article_key'],
                'url': entry['url'],
                'title': entry['title'],
                'published_at': entry['published_at'],
                'html': html_stored,
                'images': images,
            }
            object_key = f'{SOURCE}/{entry["article_key"]}/content.json'
            store.put(object_key, json.dumps(
                payload, ensure_ascii=False).encode('utf-8'))

            db.upsert(
                source=SOURCE, article_key=entry['article_key'],
                url=entry['url'], title=entry['title'],
                summary=clean.clean_text(entry['summary']),
                published_at=entry['published_at'],
                title_hash=title_hash, content_hash=content_hash,
                content_object=object_key, images=images)
            stats['updated' if old else 'new'] += 1
            print(f'  [{SOURCE}/{entry["article_key"]}] '
                  f'{"更新" if old else "入库"}:{entry["title"][:40]} '
                  f'({len(images)} 图)')

    # RSS 漏条兜底(2026-11-06 起 feed 滞后):首页列表有、feed 没有且比库内
    # 最新发布时间更新的条目,直接抓文章页入库;单篇失败下轮重试(首页覆盖
    # 近几天文章)。只补比库内最新更新的,避免把首页置顶老文全量重抓。
    newest = ''
    latest_rows = db.list_articles(SOURCE, limit=1)
    if latest_rows and latest_rows[0].get('published_at'):
        newest = latest_rows[0]['published_at']
    home_items = []
    try:
        home_resp = fetch.get(site['home'].rstrip('/') + '/')
        home_resp.raise_for_status()
        home_items = parse_home_list(home_resp.text, site['home'])
    except Exception as exc:  # noqa: BLE001 兜底失败不阻断 RSS 主流程
        print(f'[warn] 首页兜底抓取失败:{exc}', file=sys.stderr)
    for entry in home_items:
        if entry['article_key'] in feed_keys:
            continue
        published = entry['published_at'] or ''
        if newest and published and isinstance(newest, str) and published < newest:
            continue
        old = db.find(SOURCE, entry['article_key'])
        if old and old['content_object']:
            continue
        try:
            art_resp = fetch.get(entry['url'])
            art_resp.raise_for_status()
            cleaned, image_urls = typecho.parse_article(art_resp.text)
            if not cleaned:
                print(f'  [warn] 正文容器缺失,跳过 {entry["url"]}',
                      file=sys.stderr)
                stats['home_failed'] += 1
                continue
            time.sleep(2)
            images = download_images(image_urls, entry['article_key'], store)
            html_stored = cleaned
            for img in images:
                if img['key']:
                    html_stored = html_stored.replace(
                        f'src="{img["source_url"]}"', f'src="{img["key"]}"')
            text = clean.clean_text(cleaned)
            payload = {
                'source': SOURCE,
                'article_key': entry['article_key'],
                'url': entry['url'],
                'title': entry['title'],
                'published_at': entry['published_at'],
                'html': html_stored,
                'images': images,
            }
            object_key = f'{SOURCE}/{entry["article_key"]}/content.json'
            store.put(object_key, json.dumps(
                payload, ensure_ascii=False).encode('utf-8'))
            db.upsert(
                source=SOURCE, article_key=entry['article_key'],
                url=entry['url'], title=entry['title'],
                summary=text[:150],
                published_at=entry['published_at'],
                title_hash=sha16(entry['title']),
                content_hash=sha16(text),
                content_object=object_key, images=images)
            stats['home_new'] += 1
            stats['new'] += 1
            print(f'  [{SOURCE}/{entry["article_key"]}] 首页兜底入库:'
                  f'{entry["title"][:40]} ({len(images)} 图)')
        except Exception as exc:  # noqa: BLE001 单篇失败不中断
            print(f'  [warn] 首页兜底失败 {entry["article_key"]}: {exc}',
                  file=sys.stderr)
            stats['home_failed'] += 1
            time.sleep(2)

    print(f'完成:拉取 {seen} 条,新增 {stats["new"]},更新 {stats["updated"]},'
          f'跳过 {stats["skipped"]};首页兜底新增 {stats["home_new"]},'
          f'失败 {stats["home_failed"]}')
    return stats


def parse_list_html(html):
    """解析列表翻页 HTML(Mirages 主题),返回条目列表。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, 'html.parser')
    items, seen = [], set()
    for a in soup.select('a[href*="/archives/"]'):
        m = _ARTICLE_ID_RE.search(a.get('href') or '')
        title = a.get_text(' ', strip=True)
        if not m or len(title) < 6 or m.group(1) in seen:
            continue
        seen.add(m.group(1))
        # 时间取卡片内 schema 微数据 datePublished(Mirages 主题无 <time>/<meta>,
        # 是 <span itemprop=datePublished content=ISO8601>,位于卡片 <a> 内部)
        pm = a.find(attrs={'itemprop': 'datePublished'})
        published = _iso_utc(pm.get('content', '')) if pm else None
        items.append({
            'article_key': m.group(1),
            'url': f'{SOURCE_URL_BASE}/archives/{m.group(1)}.html',
            'title': title,
            'published_at': published,
        })
    return items


def backfill_html(pages=4, article_limit=200):
    """hl365 历史文章补齐:列表翻页入库 + curl 文章页抓正文文字。

    正文图片是 CDN 密文(渲染不出),仅保留文字,图片位置由前端占位。
    """
    site = load_config()['sites'][SOURCE]
    base = site['home'].rstrip('/')
    global SOURCE_URL_BASE
    SOURCE_URL_BASE = base
    db = Database()
    store = ObjectStore()
    stats = {'new': 0, 'fixed': 0}

    for page in range(1, pages + 1):
        url = base if page == 1 else f'{base}/page/{page}/'
        resp = fetch.get(url)
        resp.raise_for_status()
        items = parse_list_html(resp.text)
        print(f'第 {page} 页:解析 {len(items)} 条')
        for it in items:
            old = db.find(SOURCE, it['article_key'])
            if old:
                continue
            db.upsert(
                source=SOURCE, article_key=it['article_key'], url=it['url'],
                title=it['title'], summary='', published_at=it['published_at'],
                title_hash=sha16(it['title']), content_hash=None,
                content_object=None, images=[], status='pending')
            stats['new'] += 1
    print(f'列表入库:新增 {stats["new"]} 条(pending)')

    # 逐篇抓正文文字(仅 pending)
    pending = [r for r in db.list_articles(SOURCE, limit=500)
               if r['status'] == 'pending'][:article_limit]
    print(f'待抓正文 {len(pending)} 篇')
    for row in pending:
        try:
            resp = fetch.get(row['url'])
            resp.raise_for_status()
            cleaned, image_urls = clean.clean_html(_extract_content(resp.text))
        except Exception as exc:  # noqa: BLE001
            print(f'  [warn] {row["url"]} 失败: {exc}', file=sys.stderr)
            continue
        if not cleaned:
            continue
        # 图片为 CDN 密文,不入库;正文仅文字
        text_summary = clean.clean_text(cleaned)[:150]
        payload = {
            'source': SOURCE, 'article_key': row['article_key'],
            'url': row['url'], 'title': row['title'],
            'published_at': row['published_at'],
            'html': cleaned, 'images': [],
        }
        object_key = f'{SOURCE}/{row["article_key"]}/content.json'
        store.put(object_key, json.dumps(
            payload, ensure_ascii=False).encode('utf-8'))
        db.upsert(
            source=SOURCE, article_key=row['article_key'], url=row['url'],
            title=row['title'], summary=text_summary,
            published_at=row['published_at'],
            title_hash=sha16(row['title']),
            content_hash=sha16(clean.clean_text(cleaned)),
            content_object=object_key, images=[], status='ok')
        stats['fixed'] += 1
        if stats['fixed'] % 10 == 0:
            print(f'  已补正文 {stats["fixed"]} 篇...')
    print(f'hl365 补齐完成:列表新增 {stats["new"]},正文补齐 {stats["fixed"]}')
    return stats


SOURCE_URL_BASE = 'https://hl365.com'


def _extract_content(article_html):
    """从文章页 HTML 提取正文容器( Mirages 主题 .post-content)。"""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(article_html, 'html.parser')
    box = soup.select_one('.post-content') or soup.select_one('.content')
    return str(box) if box else ''


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--pages', type=int, default=1, help='RSS 翻页数,每页 10 条')
    parser.add_argument('--backfill', action='store_true', help='历史文章补齐(列表翻页+正文)')
    parser.add_argument('--backfill-pages', type=int, default=4)
    args = parser.parse_args()
    if args.backfill:
        backfill_html(pages=args.backfill_pages)
    else:
        collect(args.pages)
