"""51吃瓜 / 每日大赛 共用采集流程(浏览器路线)。

流程:渲染列表页 → 解析条目入库(pending)→ 逐篇渲染正文页 →
清洗 + 图片入对象存储 → 正文 JSON 入对象存储 → 条目转 ok。
域名从 config/sites.yaml 的 home 读取,失效时改配置或换 mirrors。

用法:.venv/bin/python -m collector.wacg51 [列表条数上限,默认 12]
"""
import json
import sys
import time

from collector import browser_fetch, typecho
from collector.clean import clean_text
from collector.config import load_config
from collector.hl365 import download_images  # 复用图片下载与对象存储逻辑
from collector.store import Database, ObjectStore, sha16


def _site(site_id):
    return load_config()['sites'][site_id]


def collect_list(site_id, page_url=None):
    """渲染列表页,解析条目入库(status=pending,正文未抓)。"""
    site = _site(site_id)
    html, _ = browser_fetch.fetch_rendered(page_url or site['home'],
                                           wait_selector='.post-card')
    items = typecho.parse_list(html, site['home'])
    db = Database()
    stats = {'new': 0, 'skipped': 0}
    for it in items:
        old = db.find(site_id, it['article_key'])
        if old:
            stats['skipped'] += 1
            continue
        db.upsert(
            source=site_id, article_key=it['article_key'], url=it['url'],
            title=it['title'], summary='', published_at=it['published_at'],
            title_hash=sha16(it['title']), content_hash=None,
            content_object=None, images=[], status='pending')
        stats['new'] += 1
        print(f'  [列表] 新条目 {it["article_key"]} {it["title"][:32]}')
    print(f'{site_id} 列表完成:新增 {stats["new"]},跳过 {stats["skipped"]}')
    return stats


def collect_articles(site_id, limit=12):
    """逐篇抓取 pending 条目的正文并入库,返回统计 dict。"""
    site = _site(site_id)
    db = Database()
    store = ObjectStore()
    pending = [r for r in db.list_articles(site_id, limit=500)
               if r['status'] == 'pending'][:limit]
    print(f'{site_id} 待抓正文 {len(pending)} 篇')
    stats = {'done': 0, 'failed': 0}

    for row in pending:
        url = row['url']
        try:
            html, _ = browser_fetch.fetch_rendered(url, wait_selector='.post-content')
        except Exception as exc:  # noqa: BLE001 单篇失败(含 daemon 超时)不中断整批
            print(f'  [warn] 页面抓取失败,跳过 {url}: {exc}', file=sys.stderr)
            stats['failed'] += 1
            time.sleep(2)
            continue
        cleaned, image_urls = typecho.parse_article(html)
        if not cleaned:
            print(f'  [warn] 正文容器缺失,跳过 {url}', file=sys.stderr)
            stats['failed'] += 1
            continue
        time.sleep(2)  # 同一浏览器连续导航,保持频控
        images = download_images(image_urls, row['article_key'], store,
                                 source=site_id)
        html_stored = cleaned
        for img in images:
            if img['key']:
                html_stored = html_stored.replace(
                    f'src="{img["source_url"]}"', f'src="{img["key"]}"')
        summary = clean_text(cleaned)[:150]
        payload = {
            'source': site_id,
            'article_key': row['article_key'],
            'url': url,
            'title': row['title'],
            'published_at': row['published_at'],
            'html': html_stored,
            'images': images,
        }
        object_key = f'{site_id}/{row["article_key"]}/content.json'
        store.put(object_key, json.dumps(
            payload, ensure_ascii=False).encode('utf-8'))
        db.upsert(
            source=site_id, article_key=row['article_key'], url=url,
            title=row['title'], summary=summary,
            published_at=row['published_at'],
            title_hash=sha16(row['title']),
            content_hash=sha16(clean_text(cleaned)),
            content_object=object_key, images=images, status='ok')
        stats['done'] += 1
        print(f'  [正文] {site_id}/{row["article_key"]} 入库({len(images)} 图)')
    print(f'{site_id} 正文完成:{stats["done"]} 篇,失败 {stats["failed"]} 篇')
    return stats


def collect_thumbs(site_id, limit=40, page_url=None):
    """从列表页卡片读图床 URL,服务端取密文、解密、压缩后入库。

    2026-10-30 起源站改为 x-bg-loader-url 属性(mrds 为卡内
    loadBannerDirect 脚本),由页面 JS 惰性解密;原先读 style 内联
    base64 的路线失效。改为逐卡取 outerHTML → Python 解析 URL →
    服务端下载解密(见 collector/image_cipher.py)→ 压到 360px 入库。

    漏网文章的缩略图补抓走 scripts/thumbs_backfill.py(文章页首图路线);
    原理与踩坑详见 docs/image-decrypt-playbook.md。
    """
    from collector import image_cipher

    site = _site(site_id)
    db = Database()
    store = ObjectStore()
    browser_fetch.navigate(page_url or site['home'], wait_selector='.post-card')
    time.sleep(2)
    total = json.loads(browser_fetch.eval_js(
        'JSON.stringify({n: document.querySelectorAll(".post-card").length})'))['n']
    total = min(total, limit)
    print(f'{site_id} 列表卡片 {total} 张,采集缩略图')

    done = 0
    for i in range(total):
        try:
            card_html = browser_fetch.eval_js(
                f'document.querySelectorAll(".post-card")[{i}].outerHTML')
        except browser_fetch.BrowserError as exc:
            print(f'  [warn] 第 {i} 张卡片读取失败,跳过: {exc}', file=sys.stderr)
            time.sleep(2)
            continue
        pairs = image_cipher.extract_card_sources(card_html)
        if not pairs:
            continue
        key, src = pairs[0]
        try:
            if src.startswith('data:image/'):
                raw = image_cipher.data_uri_bytes(src)
            else:
                raw = image_cipher.fetch_plain_image(src, site_id)
            if not raw:
                print(f'  [warn] 第 {i} 张缩略图无明文({key})', file=sys.stderr)
                continue
            thumb = image_cipher.make_thumb(raw)
        except Exception as exc:  # noqa: BLE001 单张失败不中断整批
            print(f'  [warn] 第 {i} 张缩略图失败({key}): {exc}', file=sys.stderr)
            continue
        if not thumb or thumb[:2] != b'\xff\xd8':
            print(f'  [warn] 第 {i} 张缩略图压缩失败({key})', file=sys.stderr)
            continue
        thumb_key = f'{site_id}/{key}/thumb.jpg'
        store.put(thumb_key, thumb)
        db.set_thumb(site_id, key, thumb_key)
        done += 1
        print(f'  [缩略图] {thumb_key}({len(thumb)}B)')
        time.sleep(2)
    print(f'{site_id} 缩略图完成:{done} 张')


def backfill(site_id, pages=3, per_page=90):
    """全量补齐:逐页入库新条目 + 采集缩略图(含首页翻不到的历史文章)。"""
    site = _site(site_id)
    home = site['home'].rstrip('/')
    total_thumbs = 0
    for page in range(1, pages + 1):
        url = home if page == 1 else f'{home}/page/{page}/'
        print(f'== [{site_id}] 第 {page} 页:{url}')
        try:
            collect_list(site_id, page_url=url)
            collect_thumbs(site_id, limit=per_page, page_url=url)
        except browser_fetch.BrowserError as exc:
            print(f'  [warn] 第 {page} 页失败,跳过: {exc}', file=sys.stderr)
            time.sleep(2)
            continue
    print(f'{site_id} 全量补齐完成')


if __name__ == '__main__':
    raise SystemExit('请通过 collector.wacg51 / collector.mrds 调用')
