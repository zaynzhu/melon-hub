"""回家路页镜像自动发现。

抓取各站官方"回家路/线路"发布页,提取候选域名,经内容指纹验证后:
- 默认只报告(候选可用性、当前 home 健康度);
- --apply 时,若当前 home 指纹失效且有候选通过验证,则把 home 换成该候选
  (sites.yaml 行级替换,保留注释;旧 home 仍留在 mirrors 池,人工复核)。

指纹 = 页面标题/正文含站点标识词 + 含主题结构标记(防"51吃瓜官方入口"
式蹭名站:标题像但内容是养生文章,见侦察档案 9.2 节)。

用真实浏览器抓取:回家路页与候选站均可能挂 CF,隔离会话 melon-hub-collect。
"""
import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from collector import browser_fetch, fetch
from collector.config import load_config, project_root

# 回家路页里的非镜像链接(社媒/短链/邮箱等),不作为候选
_SKIP_HOST_PARTS = (
    't.me', 't.co', 'x.com', 'twitter.com', 'telegram', 'mailto',
    'github', 'google', 'youtube', 'qq.com', '163.com', '126.net',
)
# 常见真实 TLD 白名单:挡住 JS 标识符(window.datalayer)与资源名(bg.png)误判
_REAL_TLDS = {
    'com', 'net', 'org', 'cc', 'me', 'io', 'co', 'su', 'fun', 'vip', 'top',
    'xyz', 'site', 'online', 'club', 'icu', 'cyou', 'ink', 'ltd', 'shop',
    'live', 'info', 'biz', 'tv', 'ai', 'news', 'pro', 'one', 'app', 'pw',
}
_ASSET_SUFFIX_RE = re.compile(r'\.(js|css|png|jpe?g|gif|webp|ico|svg|woff2?|mp4)$', re.I)
_HREF_RE = re.compile(r'href=["\'](?:https?:)?//([a-z0-9.-]+)', re.I)


def _norm(host):
    return host.lower().strip('.').removeprefix('www.')


def _plausible(host):
    labels = host.split('.')
    return (len(labels) >= 2 and labels[-1] in _REAL_TLDS
            and not _ASSET_SUFFIX_RE.search(host))


def _known_hosts(site):
    urls = [site.get('home', '')] + list(site.get('mirrors', []))
    hosts = {_norm(urlparse(u).netloc) for u in urls if u}
    page_hosts = {_norm(urlparse(u).netloc) for u in site.get('homeway_pages', []) if u}
    return hosts, page_hosts


def _extract_hosts(html):
    """从渲染后 HTML 的 href 链接提取候选域名(不做全文裸域名匹配,避免 JS 噪声)。"""
    hosts = []
    for m in _HREF_RE.finditer(html):
        host = _norm(m.group(1))
        if _plausible(host) and not any(p in host for p in _SKIP_HOST_PARTS):
            hosts.append(host)
    return list(dict.fromkeys(hosts))


def _check_site(url, markers, theme_marker):
    """渲染 url 首页做指纹验证,返回 (通过, 说明)。"""
    try:
        browser_fetch.navigate(url, wait_selector='body', wait_seconds=15)
        time.sleep(2)
        title = browser_fetch.eval_js('document.title', timeout=20) or ''
        themed = browser_fetch.eval_js(
            f'document.documentElement.outerHTML.includes({json.dumps(theme_marker)})'
            if theme_marker else 'true', timeout=20)
    except Exception as exc:  # noqa: BLE001 挑战页/挂起/死链统一视为不可用
        return False, f'无法打开({type(exc).__name__})'
    if markers and not any(m in str(title) for m in markers):
        return False, '标题标识词不符(疑似蹭名站)'
    if not themed:
        return False, '缺主题结构标记'
    return True, f'指纹匹配(标题: {str(title)[:40]})'


def _apply_home(site_id, old_home, new_home):
    """行级替换 sites.yaml 中该站 home 行,保留全部注释。"""
    path = Path(project_root()) / 'config' / 'sites.yaml'
    text = path.read_text(encoding='utf-8')
    pattern = re.compile(
        rf'(  {re.escape(site_id)}:\n(?:(?!  \w+:).*\n)*?    home: ){re.escape(old_home)}')
    new_text, n = pattern.subn(lambda m: m.group(1) + new_home, text)
    if n != 1:
        raise RuntimeError(f'sites.yaml 中未唯一定位 {site_id} 的 home 行(命中 {n})')
    path.write_text(new_text, encoding='utf-8')


def discover_site(site_id, site, apply):
    disc = site.get('discover') or {}
    markers = disc.get('markers') or []
    theme = disc.get('theme_marker', '')
    if not markers:
        print(f'[{site_id}] 未配置 discover.markers,跳过')
        return
    print(f'[{site_id}] 开始发现(标识词: {markers}, 主题标记: {theme or "无"})')

    known_hosts, page_hosts = _known_hosts(site)
    candidates = []
    for page in site.get('homeway_pages', []):
        page_host = _norm(urlparse(page).netloc)
        try:
            html, _title = browser_fetch.fetch_rendered(page, wait_selector='body')
        except Exception as exc:  # noqa: BLE001
            print(f'  [warn] 回家路页打不开 {page}: {type(exc).__name__}')
            continue
        fresh = [h for h in _extract_hosts(html)
                 if h not in known_hosts and h not in page_hosts
                 and h != page_host and len(h) <= 40]
        print(f'  回家路 {page}: 候选 {len(fresh)} 个 -> {fresh[:6]}')
        candidates.extend(fresh)
    candidates = list(dict.fromkeys(candidates))[:3]

    verified = []
    for host in candidates:
        url = f'https://{host}/'
        ok, note = _check_site(url, markers, theme)
        print(f'  验证 {host}: {"✓" if ok else "✗"} {note}')
        if ok:
            verified.append(url)
        time.sleep(2)

    home = site.get('home', '')
    # CF 偶发摩擦会造成单次误判,连续两次失败才认定失效(--apply 场景的安全阀)
    home_ok, home_note = False, '未配置'
    for attempt in range(2):
        home_ok, home_note = _check_site(home, markers, theme) if home else (False, '未配置')
        if home_ok:
            break
        print(f'  [warn] home 自检第 {attempt + 1} 次失败: {home_note}')
        time.sleep(5)
    print(f'  当前 home {home}: {"✓ 健康" if home_ok else "✗ 失效"} {home_note}')

    if home_ok:
        if verified:
            print(f'  结论: home 健康,无需变更;备用候选 {[u for u in verified]} 可人工复核进 mirrors')
        else:
            print('  结论: home 健康,回家路未发现新地址')
        return
    if not verified:
        print('  结论: home 失效且无通过验证的候选,需人工介入(查 TG/侦察档案地址簿)')
        return
    target = verified[0]
    if apply:
        _apply_home(site_id, home, target)
        print(f'  结论: --apply 已把 home 换成 {target}(旧地址仍在 mirrors,建议人工复核)')
    else:
        print(f'  结论: home 失效,候选 {target} 可用;加 --apply 写入 sites.yaml')


def main():
    parser = argparse.ArgumentParser(description='回家路页镜像自动发现')
    parser.add_argument('--apply', action='store_true',
                        help='home 失效且有可用候选时写入 sites.yaml')
    args = parser.parse_args()
    config = load_config()
    browser_fetch.ensure_ready()
    try:
        for site_id, site in config['sites'].items():
            discover_site(site_id, site, args.apply)
            time.sleep(2)
    finally:
        browser_fetch.close_session()


if __name__ == '__main__':
    main()
