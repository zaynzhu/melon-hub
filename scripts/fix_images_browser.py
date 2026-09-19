"""借用户浏览器(kimi-webbridge)取解密后的真图字节,修复已采集文章的坏图。

原理:图片 CDN 返回加密字节(任何 HTTP 客户端拿到的都是密文),站内
z-image-loader JS 解密后把 <img>.src 换成 blob: 地址。因此在文章页上下文里
fetch(blob) 即可拿到真图。

用法:.venv/bin/python scripts/fix_images_browser.py [--limit N](默认 10 张)
"""
import argparse
import base64
import json
import sys
import time

sys.path.insert(0, __import__('os').path.dirname(__import__('os').path.dirname(__import__('os').path.abspath(__file__))))

from collector import browser_fetch  # noqa: E402
from collector.store import Database, ObjectStore  # noqa: E402

_CHUNK = 40000  # base64 分块大小


def _magic_ok(raw):
    return (raw[:2] == b'\xff\xd8' or raw[:3] == b'GIF'
            or raw[:4] == b'\x89PNG' or raw[:4] == b'RIFF')


def fetch_blob_base64(index):
    """把第 index 张已解密图读入 window.__mhB64,返回 (总长, 声明的源 URL)。"""
    code = f'''(async () => {{
      const img = window.__mhList[{index}];
      if (!img) return JSON.stringify({{err: 'no img'}});
      const r = await fetch(img.src);
      const b = await r.blob();
      const buf = new Uint8Array(await b.arrayBuffer());
      let s = '';
      for (let i = 0; i < buf.length; i += 8192)
        s += String.fromCharCode.apply(null, buf.subarray(i, i + 8192));
      window.__mhB64 = btoa(s);
      return JSON.stringify({{len: window.__mhB64.length,
          src: img.getAttribute('z-image-loader-url') || ''}});
    }})()'''
    return json.loads(browser_fetch.eval_js(code))


def _pass_age_gate():
    """hl365 年龄门:确认 18+ 后站内解密流程才启动(localStorage 持久)。"""
    result = browser_fetch.eval_js('''(() => {
      const btns = [...document.querySelectorAll('button,a,div')].filter(
        b => b.textContent.includes('18岁') && b.textContent.includes('进入'));
      if (btns.length) { btns[btns.length - 1].click(); return 'clicked'; }
      return 'no gate';
    })()''')
    if result == 'clicked':
        print('  已通过年龄门,等待解密流程启动...')
        time.sleep(4)


def fix_article(url, store, want=10, fixed=0):
    """修复一篇文章的图片,返回本次修复的张数。

    每步实时查询 DOM(点年龄门后页面会重载,不能缓存元素引用):
    逐张 scrollIntoView 触发站内解密 → src 变 blob: → fetch 取真图。
    """
    try:
        current = browser_fetch.eval_js('location.href')
    except browser_fetch.BrowserError:
        current = ''
    if current != url:  # 已在该页则复用已解密状态,避免重载清零
        browser_fetch.navigate(url, wait_selector='.post-content')
        time.sleep(3)
    _pass_age_gate()

    lazy_selector = 'img[z-image-loader-url]'
    n_all = json.loads(browser_fetch.eval_js(
        f'JSON.stringify({{n: document.querySelectorAll("{lazy_selector}").length}})'))['n']
    total = min(n_all, want + 4)
    print(f'  正文图片 {n_all} 张,本轮处理前 {total} 张')

    for i in range(total):
        if fixed >= want:
            break
        # 滚到该图,等站内解密(src 变 blob:);每次按索引实时取元素
        browser_fetch.eval_js(
            f'document.querySelectorAll("{lazy_selector}")[{i}]'
            '.scrollIntoView({block: "center"})')
        for _ in range(6):  # 单张最多等 12s
            state = json.loads(browser_fetch.eval_js(f'''(() => {{
              const img = document.querySelectorAll("{lazy_selector}")[{i}];
              if (!img) return JSON.stringify({{missing: true}});
              const blob = (img.src || '').startsWith('blob:')
                && img.naturalWidth > 0;
              return JSON.stringify({{blob,
                src: img.getAttribute('z-image-loader-url') || ''}});
            }})()'''))
            if state.get('blob'):
                break
            if state.get('missing'):
                break
            time.sleep(2)
        if not state.get('blob') or state.get('missing'):
            print(f'  [warn] 第 {i} 张解密超时,跳过', file=sys.stderr)
            continue
        # 取该图的 blob 字节(实时定位第 i 张)
        meta_code = f'''(async () => {{
          const img = document.querySelectorAll("{lazy_selector}")[{i}];
          const r = await fetch(img.src);
          const b = await r.blob();
          const buf = new Uint8Array(await b.arrayBuffer());
          let s = '';
          for (let k = 0; k < buf.length; k += 8192)
            s += String.fromCharCode.apply(null, buf.subarray(k, k + 8192));
          window.__mhB64 = btoa(s);
          return JSON.stringify({{len: window.__mhB64.length,
              src: img.getAttribute('z-image-loader-url') || ''}});
        }})()'''
        meta = json.loads(browser_fetch.eval_js(meta_code))
        if 'err' in meta:
            continue
        b64 = ''
        offset = 0
        while offset < meta['len']:
            b64 += browser_fetch.eval_js(
                f'window.__mhB64.slice({offset}, {offset + _CHUNK})')
            offset += _CHUNK
            if offset < meta['len']:
                time.sleep(2)
        browser_fetch.eval_js('window.__mhB64 = null')
        raw = base64.b64decode(b64)
        if not _magic_ok(raw):
            print(f'  [warn] 第 {i} 张非图片格式,跳过', file=sys.stderr)
            continue
        import hashlib
        if raw[:2] == b'\xff\xd8':
            ext = 'jpg'
        elif raw[:4] == b'\x89PNG':
            ext = 'png'
        else:
            ext = 'gif'
        key = (f'hl365/{url.rstrip("/").split("/")[-1]}/'
               f'img-{hashlib.sha256(meta["src"].encode()).hexdigest()[:12]}.{ext}')
        store.put(key, raw)
        fixed += 1
        print(f'  [真图] {key}({len(raw)}B)')
        time.sleep(2)
    return fixed


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=10)
    parser.add_argument('--source', default='hl365')
    parser.add_argument('--article', default=None, help='指定文章 key,默认取最新一篇')
    args = parser.parse_args()

    browser_fetch.ensure_ready()
    db = Database()
    store = ObjectStore()
    if args.article:
        rows = [db.find(args.source, args.article)]
        rows = [r for r in rows if r]
    else:
        rows = db.list_articles(args.source, limit=3)
    want = args.limit
    fixed = 0
    for r in rows:
        if fixed >= want:
            break
        if not r.get('url'):
            continue
        print(f'处理 {r["source"]}/{r["article_key"]}:{r["title"][:30]}')
        fixed += fix_article(r['url'], store, want=want, fixed=fixed)
    print(f'完成:本次修复真图 {fixed} 张')


if __name__ == '__main__':
    main()
