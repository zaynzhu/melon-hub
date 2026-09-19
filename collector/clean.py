"""正文清洗:白名单思路 + 针对性推广剔除,输出干净 HTML 与图片地址。"""
import re

from bs4 import BeautifulSoup

# hl365 站方推广特征:命中即整块剔除
_PROMO_HINTS = ('最新地址', '官方APP', '官方QQ群', '获取最新网址')
_SCRIPTISH = ('script', 'style', 'iframe', 'form', 'ins')

_IMG_EXT_RE = re.compile(r'\.(jpe?g|png|gif|webp)(?:[?#]|$)', re.I)


def _is_promo(text):
    return any(h in text for h in _PROMO_HINTS)


def clean_html(html):
    """清洗 content:encoded / 文章页正文 HTML。

    返回 (清洗后 HTML 字符串, 图片 URL 列表)。
    图片真实地址取 z-image-loader-url(懒加载),回退 src/data-src。
    """
    soup = BeautifulSoup(html, 'html.parser')

    for tag in soup.find_all(_SCRIPTISH):
        tag.decompose()

    for bq in soup.find_all('blockquote'):
        if _is_promo(bq.get_text()):
            bq.decompose()

    for p in soup.find_all('p'):
        if _is_promo(p.get_text()):
            p.decompose()

    image_urls = []
    for img in soup.find_all('img'):
        src = (img.get('z-image-loader-url')
               or img.get('src') or img.get('data-src') or '').strip()
        alt = img.get('alt') or ''
        if not src or _is_promo(alt):
            img.decompose()
            continue
        img.attrs = {'src': src, 'alt': alt}
        if src not in image_urls:
            image_urls.append(src)

    # 空链接导航/推广残余一并去掉
    for a in soup.find_all('a'):
        if a.get('rel') and 'sponsored' in a.get('rel'):
            a.unwrap()

    return str(soup), image_urls


def clean_text(html):
    """HTML → 纯文本(用于摘要与内容指纹)。"""
    return ' '.join(BeautifulSoup(html, 'html.parser').get_text(' ').split())


def img_ext(url, content_type=''):
    m = _IMG_EXT_RE.search(url)
    if m:
        ext = m.group(1).lower()
        return 'jpg' if ext == 'jpeg' else ext
    ct = (content_type or '').split(';')[0].strip().lower()
    return {'image/jpeg': 'jpg', 'image/png': 'png',
            'image/gif': 'gif', 'image/webp': 'webp'}.get(ct, 'jpg')
