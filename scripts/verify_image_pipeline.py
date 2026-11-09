"""图片管线验证:卡片图片 URL 提取 / 密钥提取 / 密文解密 / 缩略图压缩。

覆盖 2026-10 源站改版后的新机制:
  - wacg51:卡片 x-bg-loader-url 属性 + 单引号字符码密钥串
  - mrds:卡片内联 loadBannerDirect('URL') 脚本
  - 旧站兼容:style 内联 base64
真实密钥与密文样本需联网;离线只跑解析项。
用法:.venv/bin/python scripts/verify_image_pipeline.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector import fetch  # noqa: E402
from collector.config import load_config  # noqa: E402

RESULTS = []


def check(name, fn):
    try:
        fn()
        RESULTS.append((name, 'PASS', ''))
    except Exception as exc:  # noqa: BLE001 验证脚本逐项收集,不中断
        RESULTS.append((name, 'FAIL', f'{type(exc).__name__}: {exc}'))


def _get(url):
    resp = fetch.get(url)
    resp.raise_for_status()
    return resp


WACG_HTML = '''<div class="post-card" id="post-card-281467">
  <div class="blog-background" x-bg-loader-url="https://pic.gyezbp.cn/a.jpeg"></div>
</div>
<div class="post-card" id="post-card-281468">
  <div class="blog-background"
       style="background-image:url(&quot;data:image/jpeg;base64,/9j/4AAQ&quot;)"></div>
</div>'''

MRDS_HTML = '''<div class="post-card" id="post-card-200701">
  <div class="blog-background"></div>
  <script type="text/javascript">
    loadBannerDirect('https://pic.gyezbp.cn//b.jpeg', '',
      document.querySelector('#post-card-200701'), '-1', 300, 200);
  </script>
</div>'''

ARTICLE_HTML = '''<div class="post-content">
  <p>x</p>
  <img z-image-loader-url="https://pic.hdhwqx.cn/c.jpeg" alt="">
  <img x-image-loader-url="https://pic.gyezbp.cn/d.jpeg" alt="">
</div>'''


def test_extract_card_sources():
    from collector import image_cipher
    wacg = dict(image_cipher.extract_card_sources(WACG_HTML))
    assert wacg['281467'] == 'https://pic.gyezbp.cn/a.jpeg', wacg
    assert wacg['281468'].startswith('data:image/jpeg;base64,'), wacg
    mrds = dict(image_cipher.extract_card_sources(MRDS_HTML))
    assert mrds['200701'] == 'https://pic.gyezbp.cn//b.jpeg', mrds


def test_extract_article_srcs():
    from collector import image_cipher
    srcs = image_cipher.extract_article_image_srcs(ARTICLE_HTML)
    assert srcs == ['https://pic.hdhwqx.cn/c.jpeg',
                    'https://pic.gyezbp.cn/d.jpeg'], srcs


def test_extract_keyiv_from_live_js():
    from collector import image_cipher
    home = load_config()['sites']['wacg51']['home'].rstrip('/')
    html = _get(home).text
    js_urls = image_cipher.find_image_js_urls(html, home)
    assert js_urls, 'wacg51 首页未找到 image.*.js'
    js = _get(js_urls[0]).text
    key, iv = image_cipher.extract_keyiv(js)
    assert len(key) == 16 and len(iv) == 16, (len(key), len(iv))


def test_decrypt_and_thumb_live():
    from collector import image_cipher
    for site in ('mrds', 'wacg51'):
        home = load_config()['sites'][site]['home'].rstrip('/')
        html = _get(home + '/').text
        sources = image_cipher.extract_card_sources(html)
        assert sources, f'{site} 首页未提取到卡片图'
        sample = None
        for _, src in sources[:3]:
            if src.startswith('data:'):
                continue
            raw = image_cipher.fetch_cipher(src)
            assert raw, f'{site} 密文下载失败'
            key, iv = image_cipher.load_keyiv(site)
            plain = image_cipher.decrypt(raw, key, iv)
            assert plain and image_cipher.kind(plain), f'{site} 解密未得到图片'
            sample = plain
            break
        assert sample, f'{site} 没有可用的 http 图源样本'
        thumb = image_cipher.make_thumb(sample)
        assert thumb[:2] == b'\xff\xd8', f'{site} 缩略图非 JPEG'
        from PIL import Image
        import io
        width = Image.open(io.BytesIO(thumb)).width
        assert width == 360, f'{site} 缩略图宽度 {width}'


def main():
    check('卡片图片 URL 提取(wacg 属性/旧 base64/mrds 脚本)', test_extract_card_sources)
    check('正文首图 URL 提取(loader 属性)', test_extract_article_srcs)
    check('新版单引号 JS 密钥提取(联网)', test_extract_keyiv_from_live_js)
    check('密文解密 + 360px 缩略图(联网)', test_decrypt_and_thumb_live)

    width = max(len(n) for n, _, _ in RESULTS)
    failed = 0
    for name, status, detail in RESULTS:
        print(f'{name:<{width}}  {status}' + (f'  {detail}' if detail else ''))
        failed += status == 'FAIL'
    print(f'\n{len(RESULTS) - failed}/{len(RESULTS)} 通过')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
