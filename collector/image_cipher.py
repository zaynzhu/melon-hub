"""图床密文图片:运行时密钥提取、下载、AES 解密、缩略图压缩。

三站图片 CDN 对所有 HTTP 客户端返回 AES-128-CBC 密文,密钥硬编码在站内
image.*.js 的字符码拼接串里(2026-09 起)。2026-10-30 wacg51 改版后密钥
编码从双引号改为单引号、解密移入 Worker,但密钥体系未变(实测 wacg51 密文
可用 mrds JS 提取的 key/iv 解开),故提取器兼容两种形式、在解密调用点窗口
内定位,不依赖混淆器函数名。

密钥不落仓库:运行时抓站点首页 → 找 image.*.js → 提取。
原理与踩坑详见 docs/image-decrypt-playbook.md。
"""
import base64
import io
import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from collector import fetch

_KEYIV_CACHE = {}
_JS_REF_RE = re.compile(r"""["']([^"']*image[^"']*\.js(?:\?[^"']*)?)["']""", re.I)
_UNDERSCORE_RE = re.compile(r"""['"]([0-9]+(?:_[0-9]+)+)['"]""")
_DECRYPT_CALL_RE = re.compile(r"AES'\]\['decrypt'\]|AES\.decrypt|'decryptjs'")
_POST_CARD_ID_RE = re.compile(r'post-card-(\d+)')


def _decode_candidate(raw):
    try:
        text = ''.join(chr(int(x)) for x in raw.split('_'))
    except ValueError:
        return None
    if len(text) == 16 and text.isprintable():
        return text
    return None


def extract_keyiv(js_text):
    """从站内混淆 JS 提取 AES key/iv,要求解密调用点窗口内恰好 2 个候选。"""
    windows = []
    for m in _DECRYPT_CALL_RE.finditer(js_text):
        windows.append(js_text[max(0, m.start() - 200):m.end() + 1500])
    for window in windows:
        decoded = []
        for cand in _UNDERSCORE_RE.findall(window):
            text = _decode_candidate(cand)
            if text and text not in decoded:
                decoded.append(text)
        if len(decoded) == 2:
            return decoded[0].encode(), decoded[1].encode()
    raise ValueError('未能从 JS 提取出恰好 2 个 16 字符 key/iv 候选')


def find_image_js_urls(html, base_url):
    """从页面 HTML 找 image.*.js 引用并补全绝对地址(去重保序)。"""
    urls = []
    for ref in _JS_REF_RE.findall(html):
        url = urljoin(base_url, ref)
        if url not in urls:
            urls.append(url)
    return urls


def load_keyiv(site_id):
    """抓站点首页找当前版本的 image.*.js,提取并缓存 key/iv。"""
    if site_id in _KEYIV_CACHE:
        return _KEYIV_CACHE[site_id]
    from collector.config import load_config
    home = load_config()['sites'][site_id]['home'].rstrip('/')
    resp = fetch.get(home + '/')
    resp.raise_for_status()
    js_urls = find_image_js_urls(resp.text, home)
    if not js_urls:
        raise ValueError(f'{site_id} 首页未找到 image.*.js')
    last_exc = None
    for js_url in js_urls:
        try:
            js = fetch.get(js_url)
            js.raise_for_status()
            key, iv = extract_keyiv(js.text)
        except Exception as exc:  # noqa: BLE001 逐个 JS 尝试
            last_exc = exc
            continue
        _KEYIV_CACHE[site_id] = (key, iv)
        return key, iv
    raise ValueError(f'{site_id} 所有 image.*.js 均未提取到密钥: {last_exc}')


def fetch_cipher(url, tries=4):
    """服务端取密文字节。CDN 偶发 200 但 body 空,重试即可。"""
    for _ in range(tries):
        try:
            resp = fetch.get(url)
            if resp.content:
                return resp.content
        except Exception:  # noqa: BLE001 单次失败重试
            pass
        time.sleep(2)
    return b''


def decrypt(raw, key, iv):
    """AES-128-CBC + PKCS7;填充不合法视为失败,不做宽松去填充。"""
    if not raw or len(raw) % 16 != 0:
        return None
    from Crypto.Cipher import AES
    pt = AES.new(key, AES.MODE_CBC, iv).decrypt(raw)
    pad = pt[-1]
    if not (1 <= pad <= 16) or pt[-pad:] != bytes([pad]) * pad:
        return None
    return pt[:-pad]


def kind(raw):
    """魔数判图:HTTP 200 与扩展名都发现不了密文。"""
    if raw[:2] == b'\xff\xd8':
        return 'jpg'
    if raw[:3] == b'GIF':
        return 'gif'
    if raw[:4] == b'\x89PNG':
        return 'png'
    if raw[:4] == b'RIFF':
        return 'webp'
    return None


def fetch_plain_image(url, site_id):
    """下载并确保得到明文图片字节(密文自动解密);失败返回 None。"""
    raw = fetch_cipher(url)
    if not raw:
        return None
    if kind(raw):
        return raw
    key, iv = load_keyiv(site_id)
    plain = decrypt(raw, key, iv)
    return plain if plain and kind(plain) else None


def make_thumb(raw, width=360, quality=72):
    """压缩为列表缩略图(JPEG);动图取首帧。"""
    from PIL import Image
    img = Image.open(io.BytesIO(raw))
    if getattr(img, 'is_animated', False):
        img.seek(0)
    img = img.convert('RGB')
    height = max(1, round(img.height * width / img.width))
    img = img.resize((width, height), Image.LANCZOS)
    out = io.BytesIO()
    img.save(out, 'JPEG', quality=quality)
    return out.getvalue()


def _card_source(card):
    """取单张卡片的图片源:新属性优先,兼容旧 style base64 与 mrds 内联脚本。"""
    bg = card.select_one('.blog-background')
    if bg is not None:
        src = bg.get('x-bg-loader-url') or bg.get('z-bg-loader-url') or ''
        if not src:
            m = re.search(r'base64,([A-Za-z0-9+/=]+)', bg.get('style') or '')
            if m:
                src = 'data:image/jpeg;base64,' + m.group(1)
        if not src:
            img = bg.select_one('img[z-image-loader-url], img[x-image-loader-url]')
            if img is not None:
                src = (img.get('z-image-loader-url')
                       or img.get('x-image-loader-url') or '')
        if src:
            return src
    for script in card.select('script'):
        m = re.search(r"loadBannerDirect\(['\"]([^'\"]+)['\"]",
                      script.get_text() or '')
        if m:
            return m.group(1)
    return ''


def extract_card_sources(html):
    """从列表页 HTML 提取 [(article_key, 图片URL/data:base64)],跳过广告卡。"""
    soup = BeautifulSoup(html, 'html.parser')
    pairs = []
    for card in soup.select('.post-card'):
        m = _POST_CARD_ID_RE.search(card.get('id') or '')
        if not m:
            continue
        src = _card_source(card)
        if src:
            pairs.append((m.group(1), src))
    return pairs


def extract_article_image_srcs(html):
    """从文章页 .post-content 提取图片 URL(loader 属性优先,data: 兼容)。"""
    soup = BeautifulSoup(html, 'html.parser')
    box = soup.select_one('.post-content')
    if box is None:
        return []
    srcs = []
    for img in box.select('img'):
        src = (img.get('z-image-loader-url') or img.get('x-image-loader-url')
               or img.get('src') or img.get('data-src') or '')
        src = src.strip()
        if not src or (not src.startswith(('http://', 'https://', 'data:image/'))):
            continue
        if src not in srcs:
            srcs.append(src)
    return srcs


def data_uri_bytes(src):
    """data:image/...;base64,... → 原始字节;非法返回 None。"""
    try:
        return base64.b64decode(src.split(',', 1)[1])
    except (IndexError, ValueError):
        return None
