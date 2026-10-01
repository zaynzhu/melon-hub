"""浏览器渲染取 HTML:双后端,按 MELON_BROWSER_BACKEND 切换。

- webbridge:借宿主机 kimi-webbridge 扩展驱动真实 Chrome(默认,与历史一致)。
  daemon 协议见 docs/webbridge-playbook.md:POST http://127.0.0.1:10086/command,带 session。
- playwright:容器内自跑无头 Chromium(过 CF 托管挑战,docs/lessons/headless-browser-pass-cf.md 已实测);
  适用于 Docker/NAS 自治场景;采集完会关闭 browser,不常驻内存。

对外接口签名不变:navigate/eval_js/fetch_rendered/ensure_ready/close_session/BrowserError/DAEMON。
"""
import json
import os
import subprocess
import time

import requests

_BACKEND = os.environ.get('MELON_BROWSER_BACKEND', 'webbridge')
DAEMON = 'http://127.0.0.1:10086/command'
SESSION = 'melon-hub-imgfix'


class BrowserError(RuntimeError):
    pass


def backend_name():
    """返回当前生效的浏览器后端标识(webbridge|playwright),供调度层判断依赖。"""
    return _BACKEND


def _use_playwright():
    """playwright 需显式启用(MELON_BROWSER_BACKEND=playwright),webbridge 仍是默认。"""
    return _BACKEND == 'playwright'


# ---- webbridge 后端(默认) ----

def _call(action, args=None, timeout=45):
    payload = {'action': action, 'args': args or {}, 'session': SESSION}
    try:
        resp = requests.post(DAEMON, json=payload, timeout=timeout)
    except requests.ConnectionError:
        subprocess.run(
            [f'{__import__("os").path.expanduser("~")}/.kimi-webbridge/bin/kimi-webbridge',
             'start'], check=False, capture_output=True)
        time.sleep(3)
        resp = requests.post(DAEMON, json=payload, timeout=timeout)
    data = resp.json()
    if not data.get('ok'):
        raise BrowserError(f'{action} 失败: {data.get("error")}')
    return data['data']


def _ensure_webbridge():
    tabs = _call('list_tabs')
    if not tabs.get('success'):
        raise BrowserError('kimi-webbridge 扩展未连接,请确认浏览器已打开并启用扩展')


def _navigate_webbridge(url, wait_selector='.post-card', wait_seconds=25):
    result = None
    for attempt in range(3):
        try:
            tabs = _call('list_tabs').get('tabs', [])
            result = _call('navigate',
                           {'url': url, 'newTab': not tabs}, timeout=60)
            break
        except requests.RequestException as exc:
            if attempt == 2:
                raise BrowserError(f'导航超时(重试 3 次): {url}: {exc}')
            time.sleep(4)
    if not result.get('success'):
        raise BrowserError(f'导航失败: {result}')
    deadline = time.time() + wait_seconds
    while time.time() < deadline:
        try:
            ok = _eval_webbridge(
                f'!!document.querySelector("{wait_selector}")')
            if ok:
                return result
        except BrowserError:
            pass
        # 站点广告会 JS 跳走,发现当前页已不是目标 URL 时拉回来重试
        try:
            href = _eval_webbridge('location.href', timeout=10)
            if isinstance(href, str) and not href.startswith(url.rstrip('/')):
                _call('navigate', {'url': url}, timeout=60)
                deadline = time.time() + wait_seconds
        except (BrowserError, requests.RequestException):
            pass
        time.sleep(2)
    raise BrowserError(f'等待 {wait_selector} 超时:{url}')


def _eval_webbridge(code, timeout=45):
    result = _call('evaluate', {'code': code}, timeout=timeout)
    return result.get('value')


def _fetch_rendered_webbridge(url, wait_selector='.post-card', chunks=40000):
    _navigate_webbridge(url, wait_selector=wait_selector)
    time.sleep(2)
    set_js = '''(() => { const clone=document.documentElement.cloneNode(true);
                clone.querySelectorAll('*').forEach(el=>{ const st=el.getAttribute('style');
                if(st && st.indexOf('data:')>=0) el.setAttribute('style','');
                for(const at of [...el.attributes]){ if(at.value.startsWith('data:'))
                el.setAttribute(at.name,'[B64]'); } });
                window.__mhHtml = clone.outerHTML;
                return JSON.stringify({len: window.__mhHtml.length,
                    title: document.title}); })()'''
    last_err = None
    for attempt in range(3):
        try:
            meta = _eval_webbridge(set_js)
            info = json.loads(meta)
            parts = []
            offset = 0
            while offset < info['len']:
                part = _eval_webbridge(f'window.__mhHtml.slice({offset}, {offset + chunks})')
                parts.append(part)
                offset += chunks
                if offset < info['len']:
                    time.sleep(2)
            _eval_webbridge('window.__mhHtml = null')
            return ''.join(parts), info['title']
        except (BrowserError, requests.RequestException, json.JSONDecodeError) as exc:
            last_err = exc
            time.sleep(4)
    raise BrowserError(f'页面渲染提取失败(重试 3 次): {url}: {last_err}')


def _close_webbridge():
    _call('close_session')


# ---- playwright 后端(容器内无头 Chromium) ----

_playwright_state = {'browser': None, 'ctx': None, 'page': None}


def _launch_playwright_browser():
    """起 browser 单例(模块级缓存);采集完由 close_session 关闭,不常驻。"""
    if _playwright_state['browser'] is not None:
        return
    from playwright.sync_api import sync_playwright
    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    ctx = browser.new_context(
        user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                   'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        viewport={'width': 1280, 'height': 800})
    page = ctx.new_page()
    _playwright_state['browser'] = browser
    _playwright_state['ctx'] = ctx
    _playwright_state['page'] = page
    _playwright_state['pw'] = pw


def _ensure_playwright():
    _launch_playwright_browser()


def _navigate_playwright(url, wait_selector='.post-card', wait_seconds=25):
    page = _playwright_state['page']
    deadline = time.time() + wait_seconds
    page.goto(url, timeout=45000, wait_until='domcontentloaded')
    time.sleep(8)  # CF 托管挑战放行窗口,见 docs/lessons/headless-browser-pass-cf.md
    while time.time() < deadline:
        try:
            ok = page.evaluate(f'!!document.querySelector("{wait_selector}")')
            if ok:
                return
        except Exception:
            pass
        try:
            href = page.evaluate('location.href')
            if isinstance(href, str) and not href.startswith(url.rstrip('/')):
                page.goto(url, timeout=45000, wait_until='domcontentloaded')
                time.sleep(8)
                deadline = time.time() + wait_seconds
        except Exception:
            pass
        time.sleep(2)
    raise BrowserError(f'等待 {wait_selector} 超时:{url}')


def _eval_playwright(code, timeout=45):
    page = _playwright_state['page']
    try:
        result = page.evaluate(code)
        return result
    except Exception as exc:
        raise BrowserError(f'evaluate 失败:{type(exc).__name__}: {exc}') from exc


def _fetch_rendered_playwright(url, wait_selector='.post-card'):
    _navigate_playwright(url, wait_selector=wait_selector)
    time.sleep(2)
    html = _eval_playwright('document.documentElement.outerHTML')
    title = _eval_playwright('document.title') or ''
    return html, title


def _close_playwright():
    state = _playwright_state
    for key in ('page', 'ctx', 'browser'):
        obj = state.get(key)
        if obj is not None:
            try:
                obj.close()
            except Exception:
                pass
            state[key] = None
    if state.get('pw') is not None:
        try:
            state['pw'].stop()
        except Exception:
            pass
        state['pw'] = None


# ---- 对外统一接口(按后端分流) ----

def ensure_ready():
    if _use_playwright():
        _ensure_playwright()
    else:
        _ensure_webbridge()


def navigate(url, wait_selector='.post-card', wait_seconds=25):
    if _use_playwright():
        return _navigate_playwright(url, wait_selector, wait_seconds)
    return _navigate_webbridge(url, wait_selector, wait_seconds)


def eval_js(code, timeout=45):
    if _use_playwright():
        return _eval_playwright(code, timeout)
    return _eval_webbridge(code, timeout)


def fetch_rendered(url, wait_selector='.post-card', chunks=40000):
    if _use_playwright():
        html, title = _fetch_rendered_playwright(url, wait_selector)
        return html, title
    return _fetch_rendered_webbridge(url, wait_selector, chunks)


def close_session():
    if _use_playwright():
        _close_playwright()
    else:
        _close_webbridge()
