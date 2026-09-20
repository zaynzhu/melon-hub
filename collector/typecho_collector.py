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
    """逐篇抓取 pending 条目的正文并入库。"""
    site = _site(site_id)
    db = Database()
    store = ObjectStore()
    pending = [r for r in db.list_articles(site_id, limit=500)
               if r['status'] == 'pending'][:limit]
    print(f'{site_id} 待抓正文 {len(pending)} 篇')

    for row in pending:
        url = row['url']
        try:
            html, _ = browser_fetch.fetch_rendered(url, wait_selector='.post-content')
        except Exception as exc:  # noqa: BLE001 单篇失败(含 daemon 超时)不中断整批
            print(f'  [warn] 页面抓取失败,跳过 {url}: {exc}', file=sys.stderr)
            time.sleep(2)
            continue
        cleaned, image_urls = typecho.parse_article(html)
        if not cleaned:
            print(f'  [warn] 正文容器缺失,跳过 {url}', file=sys.stderr)
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
        print(f'  [正文] {site_id}/{row["article_key"]} 入库({len(images)} 图)')


def collect_thumbs(site_id, limit=40, page_url=None):
    """从列表页卡片的 base64 背景图(站点服务端直出明文)生成缩略图入库。

    页面内 canvas 压到 360px 宽 JPEG 再分块传回,避开加密 CDN 与大传输。

    漏网文章(被挤出可翻页范围)的缩略图补抓走
    scripts/thumbs_backfill.py(文章页首图是明文 data:URI,可兜底);
    原理与踩坑详见 docs/image-decrypt-playbook.md。
    """
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
            meta = json.loads(browser_fetch.eval_js(f'''(async () => {{
              const card = document.querySelectorAll('.post-card')[{i}];
              const key = (card.id || '').replace('post-card-', '');
              if (!/^\\d+$/.test(key)) return JSON.stringify({{err: 'ad card'}});
              const style = (card.querySelector('.blog-background')
                ?.getAttribute('style')) || '';
              const m = style.match(/base64,([A-Za-z0-9+/=]+)/);
              if (!m) return JSON.stringify({{err: 'no bg'}});
              const img = new Image();
              await new Promise((res, rej) => {{
                img.onload = res; img.onerror = rej;
                img.src = 'data:image/jpeg;base64,' + m[1];
              }});
              const w = 360;
              const h = Math.max(1, Math.round(img.naturalHeight * w / img.naturalWidth));
              const cv = document.createElement('canvas');
              cv.width = w; cv.height = h;
              cv.getContext('2d').drawImage(img, 0, 0, w, h);
              window.__mhThumbB64 = cv.toDataURL('image/jpeg', 0.72).split(',')[1];
              return JSON.stringify({{len: window.__mhThumbB64.length, key}});
            }})()'''.replace('if (!db_ref) {}', '')))
        except browser_fetch.BrowserError as exc:
            print(f'  [warn] 第 {i} 张缩略图失败,跳过: {exc}', file=sys.stderr)
            time.sleep(2)
            continue
        if 'err' in meta:
            time.sleep(1)
            continue
        b64, offset = '', 0
        while offset < meta['len']:
            b64 += browser_fetch.eval_js(
                f'window.__mhThumbB64.slice({offset}, {offset + 40000})')
            offset += 40000
            if offset < meta['len']:
                time.sleep(2)
        browser_fetch.eval_js('window.__mhThumbB64 = null')
        import base64 as _b64
        raw = _b64.b64decode(b64)
        if raw[:2] != b'\xff\xd8':
            print(f'  [warn] 第 {i} 张非 JPEG,跳过', file=sys.stderr)
            continue
        key = meta['key']
        thumb_key = f'{site_id}/{key}/thumb.jpg'
        store.put(thumb_key, raw)
        db.set_thumb(site_id, key, thumb_key)
        done += 1
        print(f'  [缩略图] {thumb_key}({len(raw)}B)')
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
