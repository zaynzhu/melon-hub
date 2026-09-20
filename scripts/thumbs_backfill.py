"""三站缩略图补抓:密文解密 + 文章页首图两条路线,幂等只补缺。

原理与踩坑详见 docs/image-decrypt-playbook.md,要点:
  - hl365 缩略图 CDN 返回加密字节,页面全局函数 decryptImage(b64) 是 AES-CBC
    解密入口(密钥硬编码在站内混淆 JS),服务端取密文注入页面解密。
  - wacg51/mrds 列表卡片缩略图是 base64 背景图(typecho_collector.collect_thumbs
    已覆盖);漏网文章(被挤到翻不到的页)走文章页首图——正文页 .post-content
    第一张 img 直接是明文 base64 data:URI,不用解密。

用法:
  .venv/bin/python scripts/thumbs_backfill.py                  # 三站全补(只补缺)
  .venv/bin/python scripts/thumbs_backfill.py --source hl365  # 单站
  .venv/bin/python scripts/thumbs_backfill.py --limit 20      # 限篇数
"""
import argparse
import base64
import json
import re
import sys
import time

sys.path.insert(0, __import__('os').path.dirname(
    __import__('os').path.dirname(__import__('os').path.abspath(__file__))))

import requests  # noqa: E402

from collector import browser_fetch, fetch  # noqa: E402
from collector.config import load_config  # noqa: E402
from collector.store import Database, ObjectStore  # noqa: E402

_CHUNK = 40000  # base64 分块大小:webbridge evaluate 传大串偶发失败,40KB 实测稳定


def _ext_of(raw):
    """按魔数定扩展名:判图必须查魔数,HTTP 200 校验发现不了密文。"""
    if raw[:2] == b'\xff\xd8':
        return 'jpg'
    if raw[:4] == b'\x89PNG':
        return 'png'
    if raw[:3] == b'GIF':
        return 'gif'
    return None


def _save_thumb(db, store, source, key, raw):
    ext = _ext_of(raw)
    if not ext:
        print(f'  [fail] {source}/{key} 非图片魔数: {raw[:4].hex()}', file=sys.stderr)
        return False
    thumb_key = f'{source}/{key}/thumb.{ext}'
    store.put(thumb_key, raw)
    db.set_thumb(source, key, thumb_key)
    print(f'  [缩略图] {thumb_key}({len(raw)}B)')
    return True


def _fetch_cipher(surl, tries=4):
    """服务端取密文字节。CDN 偶发 200 但 body 空(Content-Length 正常),重试即可。"""
    for _ in range(tries):
        try:
            resp = requests.get(surl, headers={'User-Agent': 'Mozilla/5.0'}, timeout=25)
            if resp.content:
                return resp.content
        except requests.RequestException:
            pass
        time.sleep(3)
    return b''


def _decrypt_via_page(browser, cipher_b64):
    """把 base64 密文分块注入页面,调全局 decryptImage 解出明文 base64。

    注意(踩坑):decryptImage 出错时静默返回 '',所以必须查返回长度;
    入参是 base64 密文字符串而不是 URL;注入前清零窗口变量防跨文章残留。
    """
    browser.eval_js('window.__mhCT = ""')
    for i in range(0, len(cipher_b64), _CHUNK):
        browser.eval_js(f'window.__mhCT += "{cipher_b64[i:i + _CHUNK]}"')
        time.sleep(1.0)
    out = browser.eval_js(
        '(() => { const out = decryptImage(window.__mhCT);'
        ' window.__mhPT = out; window.__mhCT = "";'
        ' return JSON.stringify({len: (out || "").length}); })()')
    if isinstance(out, str):
        out = json.loads(out)
    if not out.get('len'):
        return ''
    # 分块取回明文
    plain = ''
    offset = 0
    while offset < out['len']:
        plain += browser.eval_js(f'window.__mhPT.slice({offset}, {offset + _CHUNK})')
        offset += _CHUNK
        if offset < out['len']:
            time.sleep(1.5)
    browser.eval_js('window.__mhPT = ""')
    return plain


def backfill_hl365(db, store, missing, browser):
    """hl365 路线:列表翻页建卡片图映射 → 密文解密;映射外从文章页头图兜底。

    列表页站内解密不触发是 IntersectionObserver 未命中(图不在视口),
    与年龄门/解密链路无关;手动喂密文即可。
    """
    site = load_config()['sites']['hl365']
    base = site['home'].rstrip('/')
    # 列表页卡片 id → z-image-loader-url(密文源 URL)
    card_map = {}
    for page in range(1, 13):
        url = base if page == 1 else f'{base}/page/{page}/'
        resp = fetch.get(url)
        card_map.update(re.findall(
            r'id="post-card-(\d+)"[^>]*>.{0,400}?z-image-loader-url="([^"]+)"',
            resp.text, re.S))
        if not any(k in card_map for k in missing):
            break
    print(f'hl365 列表卡片映射 {len(card_map)} 条')

    # 页面先停在 hl365 任意页:decryptImage 是站点 JS 注入的,上下文必须在 hl365.com
    browser.navigate(site['home'], wait_selector='.post-card')
    time.sleep(3)

    ok = 0
    for key in missing:
        surl = card_map.get(key)
        if not surl:
            # 文章页兜底:meta itemprop=image 指向头图
            try:
                resp = fetch.get(f'{base}/archives/{key}.html')
                m = re.search(r'itemprop="image" content="([^"]+)"', resp.text)
                surl = m.group(1) if m else None
            except Exception as exc:  # noqa: BLE001
                print(f'  [warn] {key} 文章页失败: {exc}', file=sys.stderr)
        if not surl:
            print(f'  [skip] {key} 无图源')
            continue
        cipher = _fetch_cipher(surl)
        if not cipher or _ext_of(cipher):
            # 密文取不到或已是明文
            if cipher and _save_thumb(db, store, 'hl365', key, cipher):
                ok += 1
            continue
        plain = _decrypt_via_page(browser, base64.b64encode(cipher).decode())
        if plain and _save_thumb(db, store, 'hl365', key, base64.b64decode(plain)):
            ok += 1
        time.sleep(2)
    print(f'hl365 完成:本次 {ok}/{len(missing)}')


def backfill_article_firstimg(db, store, source, missing, browser):
    """wacg51/mrds 路线:文章页首图是明文 data:URI,直接取当缩略图。

    踩坑:mrds 文章页没有 .post-card 节点,wait_selector 必须用 .post-content。
    """
    home = load_config()['sites'][source]['home'].rstrip('/')
    ok = 0
    for key in missing:
        url = f'{home}/archives/{key}/'
        try:
            browser.navigate(url, wait_selector='.post-content', wait_seconds=20)
            time.sleep(2)
            meta = json.loads(browser.eval_js('''(async () => {
              const img = document.querySelector(".post-content img");
              if (!img) return JSON.stringify({err: "no img"});
              let s = "";
              if ((img.src || "").startsWith("data:")) s = img.src.split(",")[1];
              else if ((img.src || "").startsWith("blob:")) {
                const r = await fetch(img.src); const b = await r.blob();
                const buf = new Uint8Array(await b.arrayBuffer());
                for (let i = 0; i < buf.length; i += 8192)
                  s += String.fromCharCode.apply(null, buf.subarray(i, i + 8192));
                s = btoa(s);
              } else return JSON.stringify({err: "src:" + img.src.slice(0, 50)});
              window.__mhB64 = s;
              return JSON.stringify({len: s.length});
            })()'''))
            if 'err' in meta:
                print(f'  [skip] {key}: {meta["err"]}', file=sys.stderr)
                continue
            plain = ''
            offset = 0
            while offset < meta['len']:
                plain += browser.eval_js(f'window.__mhB64.slice({offset}, {offset + _CHUNK})')
                offset += _CHUNK
                if offset < meta['len']:
                    time.sleep(2)
            browser.eval_js('window.__mhB64 = ""')
            if _save_thumb(db, store, source, key, base64.b64decode(plain)):
                ok += 1
            time.sleep(2)
        except Exception as exc:  # noqa: BLE001 单篇失败不中断整批
            print(f'  [fail] {key}: {exc}', file=sys.stderr)
    print(f'{source} 完成:本次 {ok}/{len(missing)}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default=None, help='默认三站全跑')
    parser.add_argument('--limit', type=int, default=0, help='最多处理篇数,0 不限')
    args = parser.parse_args()

    db = Database()
    store = ObjectStore()
    sites = [args.source] if args.source else ['hl365', 'wacg51', 'mrds']
    plan = {}
    for source in sites:
        with db.conn.cursor() as cur:
            cur.execute(
                f"select article_key from articles where source='{source}' "
                'and thumb_object is null')
            missing = [r['article_key'] for r in cur.fetchall()]
        if args.limit:
            missing = missing[:args.limit]
        plan[source] = missing
        print(f'{source} 待补 {len(missing)} 篇')

    browser = None
    if any(plan.values()):
        browser_fetch.ensure_ready()
        browser = browser_fetch

    for source, missing in plan.items():
        if not missing:
            continue
        if source == 'hl365':
            backfill_hl365(db, store, missing, browser)
        else:
            backfill_article_firstimg(db, store, source, missing, browser)


if __name__ == '__main__':
    main()