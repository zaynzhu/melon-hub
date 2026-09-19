"""51吃瓜 / 每日大赛 共用解析器(两站同套 Typecho 主题,DOM 结构一致)。

输入为真实浏览器渲染后的 HTML(kimi-webbridge 采集),离线解析:
  列表:  a[href*="/archives/<id>/"] > .post-card(id/post-card-title/post-card-info)
  正文:  .post-content(剔除 SEO 广告块与推广,图片真实地址藏在随机命名的
         懒加载属性中,与 hl365 同方案但属性名不同,故按"属性值为图片 URL"
         通用识别,不硬编码属性名)
"""
import re

from bs4 import BeautifulSoup

_ARTICLE_HREF_RE = re.compile(r'/archives/(\d+)/?')
_DATE_CN_RE = re.compile(r'(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日')
_IMG_URL_RE = re.compile(r'^https?://\S+\.(?:jpe?g|png|gif|webp)(?:[?#].*)?$', re.I)
# 正文头部/穿插的 SEO 广告词串,命中两个以上判定为广告节点
_SEO_HINTS = ('约炮', '包养', '棋牌', '直播', '免费看', '黄片', '杏吧', '蜜桃',
              '偷拍', '福利', '破解', '暗网', '免费AI', '抖阴', '魔改短剧')


def parse_date_cn(text):
    m = _DATE_CN_RE.search(text or '')
    if not m:
        return None
    return f'{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'


def parse_list(html, base_url):
    """解析渲染后的列表页,返回条目字典列表(已排除广告卡)。"""
    soup = BeautifulSoup(html, 'html.parser')
    items, seen = [], set()
    for card in soup.select('.post-card'):
        a = card.find_parent('a', href=_ARTICLE_HREF_RE)
        if not a or 'ad-card' in (card.get('id') or ''):
            continue
        m = _ARTICLE_HREF_RE.search(a['href'])
        key = m.group(1)
        if key in seen:
            continue
        seen.add(key)
        title_el = card.select_one('.post-card-title')
        info_el = card.select_one('.post-card-info')
        info_text = info_el.get_text(' ', strip=True) if info_el else ''
        author = info_text.split('•')[0].strip() if info_text else ''
        title = title_el.get_text(' ', strip=True) if title_el else ''
        # 首页"热搜 HOT"等栏目位卡片没有真实标题,排除
        if len(title) < 6 or title == '热搜 HOT':
            continue
        items.append({
            'article_key': key,
            'url': f'{base_url.rstrip("/")}/archives/{key}/',
            'title': title,
            'published_at': parse_date_cn(info_text),
            'author': author,
            'categories': [s.strip() for s in info_text.split('•')[2:]] if info_text else [],
        })
    return items


def _find_image_url(img):
    """从 img 任意属性中识别真实图片 URL(懒加载属性名随机)。"""
    for _, value in img.attrs.items():
        if isinstance(value, str) and _IMG_URL_RE.match(value.strip()):
            return value.strip()
    return None


def parse_article(html):
    """解析渲染后的正文页,返回 (清洗后 HTML, 图片 URL 列表)。"""
    soup = BeautifulSoup(html, 'html.parser')
    box = soup.select_one('.post-content')
    if box is None:
        return '', []

    for bad in box.select('div.txt-apps, script, style, iframe, form'):
        bad.decompose()

    for node in box.find_all(['blockquote', 'p', 'div']):
        text = node.get_text(' ', strip=True)
        hits = sum(1 for h in _SEO_HINTS if h in text)
        if hits >= 2 or ('最新地址' in text and node.name == 'blockquote'):
            node.decompose()

    image_urls = []
    for img in box.find_all('img'):
        src = _find_image_url(img)
        alt = (img.get('alt') or '').strip()
        if not src:
            img.decompose()
            continue
        img.attrs = {'src': src, 'alt': alt}
        if src not in image_urls:
            image_urls.append(src)

    # 清掉残留空段落/空 span,让正文紧凑
    for empty in box.find_all(['p', 'span']):
        if not empty.get_text(strip=True) and not empty.find('img'):
            empty.decompose()

    return str(box), image_urls
