"""hl365 首页列表兜底验证:列表解析 / 时间解析 / 文章页正文解析。

背景:RSS 自 2026-11-06 起滞后,首页已有 11-08 新文(feed 无),采集需
用首页列表兜底。本脚本先验证解析器,不写任何数据。
用法:.venv/bin/python scripts/verify_hl365_home.py
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


FIXTURE_HOME = '''<article>
  <a href="/archives/225567.html">
    <div class="post-card" id="post-card-225567">
      <div class="blog-background">
        <img z-image-loader-url="https://pic.hdhwqx.cn/x.jpeg" alt="">
      </div>
      <div class="post-card-mask">
        <span class="post-card-title"><div class="wrap"><span>热搜 HOT</span></div></span>
        <div class="post-card-info">
          <span itemprop="datePublished" content="2026-11-08T03:26:00+00:00">2026/11/08</span>
        </div>
        <h2 class="post-card-bottom-title">
          <p class="post-card-bottom-text">测试标题占位内容</p>
        </h2>
      </div>
    </div>
  </a>
</article>
<article>
  <a href="/archives/225287.html">
    <div class="post-card" id="post-card-225287">
      <span class="post-card-title"><span>热搜 HOT</span></span>
      <span itemprop="datePublished" content="2026-11-05T06:49:00+00:00">2026/11/05</span>
      <h2 class="post-card-bottom-title">
        <p class="post-card-bottom-text">第二条测试占位内容</p>
      </h2>
    </div>
  </a>
</article>'''

FIXTURE_ARTICLE = '''<div class="post-content">
  <p>正文第一段。</p>
  <img z-image-loader-url="https://pic.hdhwqx.cn/20261108/a.jpeg" alt="图1">
</div>'''


def test_parse_fixture_home():
    from collector.hl365 import parse_home_list
    items = parse_home_list(FIXTURE_HOME, 'https://hl365.com/')
    assert len(items) == 2, items
    first = items[0]
    assert first['article_key'] == '225567', first
    assert first['url'] == 'https://hl365.com/archives/225567.html', first
    assert first['title'] == '测试标题占位内容', first
    assert first['published_at'] == '2026-11-08T03:26:00Z', first


def test_parse_fixture_article():
    from collector.typecho import parse_article
    html, urls = parse_article(FIXTURE_ARTICLE)
    assert 'post-content' in html, html
    assert urls == ['https://pic.hdhwqx.cn/20261108/a.jpeg'], urls


def test_live_home_has_newer_than_feed():
    site = load_config()['sites']['hl365']
    html = fetch.get(site['home'].rstrip('/') + '/').text
    from collector.hl365 import parse_home_list
    items = parse_home_list(html, site['home'])
    assert items, '真实首页未解析到条目'
    latest = max(items, key=lambda it: it['article_key'])
    assert int(latest['article_key']) >= 225412, \
        f"首页最新 id {latest['article_key']} 未超过库内最新 225412"
    assert latest['published_at'], latest


def test_live_article_parse():
    site = load_config()['sites']['hl365']
    html = fetch.get(site['home'].rstrip('/') + '/archives/225567.html').text
    from collector.typecho import parse_article
    body, urls = parse_article(html)
    assert 'post-content' in body, '文章页正文容器缺失'
    assert len(body) > 200, f'正文过短: {len(body)}'
    assert urls, '正文未解析到图片'


def main():
    check('合成首页列表解析', test_parse_fixture_home)
    check('合成文章页正文解析', test_parse_fixture_article)
    check('真实首页可解析且含新文(联网)', test_live_home_has_newer_than_feed)
    check('真实文章页正文可解析(联网)', test_live_article_parse)

    width = max(len(n) for n, _, _ in RESULTS)
    failed = 0
    for name, status, detail in RESULTS:
        print(f'{name:<{width}}  {status}' + (f'  {detail}' if detail else ''))
        failed += status == 'FAIL'
    print(f'\n{len(RESULTS) - failed}/{len(RESULTS)} 通过')
    return 1 if failed else 0


if __name__ == '__main__':
    raise SystemExit(main())
