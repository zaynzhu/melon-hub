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
import xml.etree.ElementTree as ET
from email.utils import parsedate_to_datetime

from collector import clean, fetch
from collector.config import load_config
from collector.store import Database, ObjectStore, sha16

SOURCE = 'hl365'
_ARTICLE_ID_RE = re.compile(r'/archives/(\d+)\.html')
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

    stats = {'new': 0, 'updated': 0, 'skipped': 0}
    seen = 0
    first_keys = set()
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

    print(f'完成:拉取 {seen} 条,新增 {stats["new"]},更新 {stats["updated"]},'
          f'跳过 {stats["skipped"]}')
    return stats


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--pages', type=int, default=1,
                        help='RSS 翻页数,每页 10 条')
    collect(parser.parse_args().pages)
