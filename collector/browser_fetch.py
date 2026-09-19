"""kimi-webbridge 驱动:真实浏览器渲染后取 HTML(过 CF 盾 + 客户端渲染)。

daemon 协议见 skill 文档:POST http://127.0.0.1:10086/command,每次调用带 session。
健康检查失败(连接拒绝)时尝试自启 daemon;扩展未连接则报错提示用户。
"""
import json
import subprocess
import time

import requests

DAEMON = 'http://127.0.0.1:10086/command'
SESSION = 'melon-hub-imgfix'


class BrowserError(RuntimeError):
    pass


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


def ensure_ready():
    """健康检查:扩展连接可用即通过。"""
    tabs = _call('list_tabs')
    if not tabs.get('success'):
        raise BrowserError('kimi-webbridge 扩展未连接,请确认浏览器已打开并启用扩展')


def navigate(url, wait_selector='.post-card', wait_seconds=25):
    """打开页面并等待渲染出目标节点(SPA 需等数据注入)。

    会话无标签页时新开专用 tab;已有则导航当前 tab(脚本全程独占)。
    """
    result = None
    for attempt in range(3):  # 慢页面导航偶发超时,重试
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
            ok = eval_js(
                f'!!document.querySelector("{wait_selector}")')
            if ok:
                return result
        except BrowserError:
            pass
        time.sleep(2)
    raise BrowserError(f'等待 {wait_selector} 超时:{url}')


def eval_js(code, timeout=45):
    result = _call('evaluate', {'code': code}, timeout=timeout)
    return result.get('value')


def fetch_rendered(url, wait_selector='.post-card', chunks=40000):
    """导航到 URL,返回 (documentElement 渲染后 HTML, 标题)。

    HTML 里的内嵌 base64 占位图与背景图先被替换为 [B64],避免无效传输;
    大 HTML 按块传输,块间遵守 2 秒频控。
    """
    navigate(url, wait_selector=wait_selector)
    time.sleep(2)
    meta = None
    for attempt in range(3):  # 慢页面 evaluate 偶发超时,重试
        try:
            meta = eval_js(
                '''(() => { const clone=document.documentElement.cloneNode(true);
                clone.querySelectorAll('*').forEach(el=>{ const st=el.getAttribute('style');
                if(st && st.indexOf('data:')>=0) el.setAttribute('style','');
                for(const at of [...el.attributes]){ if(at.value.startsWith('data:'))
                el.setAttribute(at.name,'[B64]'); } });
                window.__mhHtml = clone.outerHTML;
                return JSON.stringify({len: window.__mhHtml.length,
                    title: document.title}); })()''')
            break
        except (BrowserError, requests.RequestException) as exc:
            if attempt == 2:
                raise BrowserError(f'页面渲染提取失败(重试 3 次): {url}: {exc}')
            time.sleep(4)
    info = json.loads(meta)
    parts = []
    offset = 0
    while offset < info['len']:
        part = eval_js(f'window.__mhHtml.slice({offset}, {offset + chunks})')
        parts.append(part)
        offset += chunks
        if offset < info['len']:
            time.sleep(2)
    eval_js('window.__mhHtml = null')
    return ''.join(parts), info['title']


def close_session():
    _call('close_session')
