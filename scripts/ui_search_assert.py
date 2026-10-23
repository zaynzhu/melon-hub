"""标题搜索的前端契约断言(headless Chrome CDP,数值/文本断言,不用截图)。

两种用法(shell 侧先设隔离 env,参考 scripts/verify_search.py 头注):
  种数据:.venv/bin/python -I scripts/ui_search_assert.py --seed
  跑断言:.venv/bin/python -I scripts/ui_search_assert.py [URL]
  (默认 URL http://127.0.0.1:8788/,测试时用隔离实例端口)

A 段 = 旧契约(改版前后必须同样全绿,防止改 HTML 时弄坏现有功能);
B 段 = 搜索新行为(实现前为 RED)。
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request

# -I 模式不注入脚本目录,手动把项目根插进 sys.path(collector/server 都是包内相对根导入)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# ---- --seed:往隔离 SQLite 种测试数据 ----
SEED_ARTICLES = None  # 在 seed() 里按当天日期构造


def seed():
    import os
    from datetime import datetime, timedelta

    from collector.store import Database
    import server.sync as sync

    db = Database()

    today = datetime.now().date()
    days = {0: today, 1: today - timedelta(days=1), 3: today - timedelta(days=3)}

    def at(day_off, hh, mm):
        d = days[day_off]
        return f'{d.isoformat()}T{hh:02d}:{mm:02d}:00Z'

    fixtures = [
        ('hl365', 'k1', '张某某深夜爆料,全网吃瓜中', at(0, 8, 0)),
        ('hl365', 'k2', '吃瓜前线:某顶流人设崩塌实录', at(0, 10, 30)),
        ('hl365', 'k3', '李某某工作室发声明否认', at(1, 9, 0)),
        ('hl365', 'k4', '旧闻回顾:圈内秘辛再起', at(3, 11, 0)),
        ('wacg51', 'k5', '吃瓜群众集合!某选秀内幕曝光', at(0, 12, 0)),
        ('wacg51', 'k6', '100% 真实:某剧组恋情实锤', at(1, 18, 0)),
        ('wacg51', 'k7', '吃瓜不倦:本周热点盘点', at(1, 21, 0)),
        ('wacg51', 'k8', '某网红直播间翻车现场', at(3, 14, 0)),
        ('mrds', 'k9', '大赛吃瓜:选手后台互撕全记录', at(0, 15, 0)),
        ('mrds', 'k10', '吃瓜团速递:赛场花絮', at(0, 17, 0)),
        ('mrds', 'k11', '某某事件完整时间线梳理', at(1, 23, 0)),
        ('mrds', 'k12', '无瓜说:本周无大瓜', at(3, 20, 0)),
    ]
    for src, key, title, pub in fixtures:
        db.upsert(src, key, f'https://example.com/{key}', title, '摘要',
                  pub, f'th-{key}', None, None, [])

    # 调度器保持空转:已有 initialized、双模式全关,首启不采集、tick 永不到期
    db.set_setting(sync.KEY_INITIALIZED, '1')
    db.set_setting(sync.KEY_INTERVAL, '0')
    db.set_setting(sync.KEY_DAILY, '')
    db.set_setting(sync.KEY_LAST_INTERVAL, time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()))
    db.set_setting(sync.KEY_LAST_DAILY, today.isoformat())
    print(f'seed 完成:{len(fixtures)} 篇(吃瓜 6 / 内幕+选秀 1 / 张某某 1),调度空转')


# ---- CDP 断言(模板来自 docs/lessons/ui-contract-assert.md 实测版) ----
CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'
CDP_PORT = 9343

_FAILED = []


def check(label, cond, detail=''):
    print(f'[{"ok" if cond else "FAIL"}] {label}' + (f' — {detail}' if detail and not cond else ''))
    if not cond:
        _FAILED.append(label)
    return bool(cond)


async def main(url, width=1440):
    import websockets

    proc = subprocess.Popen(
        [CHROME, '--headless=new', '--disable-gpu',
         f'--remote-debugging-port={CDP_PORT}', '--hide-scrollbars',
         f'--window-size={width},900', 'about:blank'],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(30):
            try:
                urllib.request.urlopen(f'http://127.0.0.1:{CDP_PORT}/json/version', timeout=1)
                break
            except Exception:
                await asyncio.sleep(0.3)
        req = urllib.request.Request(
            f'http://127.0.0.1:{CDP_PORT}/json/new?about:blank', method='PUT')
        with urllib.request.urlopen(req) as r:
            tab = json.loads(r.read())
        async with websockets.connect(tab['webSocketDebuggerUrl'], max_size=64 * 1024 * 1024) as ws:
            mid = 0

            async def send(method, params=None):
                nonlocal mid
                mid += 1
                i = mid
                await ws.send(json.dumps({'id': i, 'method': method, 'params': params or {}}))
                while True:
                    m = json.loads(await ws.recv())
                    if m.get('id') == i:
                        return m.get('result', {})

            async def ev(expr):
                r = (await send('Runtime.evaluate',
                                {'expression': expr, 'returnByValue': True}))['result']
                return r.get('value')

            async def click(selector):
                await ev(f'document.querySelector({json.dumps(selector)}).click()')

            async def type_input(text, submit=None):
                """submit: 'enter' 回车 / None 触发 input 事件(配合防抖) / 'esc' 清空"""
                js = ('(() => { const i = document.getElementById("search-input");'
                      f'i.value = {json.dumps(text)};')
                if submit == 'enter':
                    js += 'i.dispatchEvent(new KeyboardEvent("keydown", {key: "Enter"}));'
                elif submit == 'esc':
                    js += 'i.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape"}));'
                else:
                    js += 'i.dispatchEvent(new Event("input", {bubbles: true}));'
                js += '})()'
                await ev(js)

            async def wait_until(expr, timeout=5.0, poll=0.05):
                t0 = time.monotonic()
                while True:
                    if await ev(expr):
                        return time.monotonic() - t0
                    if time.monotonic() - t0 > timeout:
                        return None
                    await asyncio.sleep(poll)

            CARDS = 'document.querySelectorAll("#card-flow .card").length'

            async def card_titles():
                return await ev(
                    '[...document.querySelectorAll("#card-flow .card .card-title")]'
                    '.map(e => e.textContent)')

            await send('Page.enable')
            await send('Emulation.setDeviceMetricsOverride',
                       {'width': width, 'height': 900, 'deviceScaleFactor': 1, 'mobile': False})
            await send('Page.navigate', {'url': url})
            ok = await wait_until(f'{CARDS} > 0', timeout=8)
            check('A1 页面载入且出卡片', ok is not None,
                  '8 秒内没有渲染出任何 .card')

            # ---- A 段:旧契约(app.js 依赖的 DOM 暗契约 + 现有功能行为) ----
            ids = ['feed-meta', 'card-flow', 'load-more', 'reader-backdrop', 'reader-close',
                   'reader-source', 'reader-title', 'reader-date', 'reader-origin',
                   'article-content', 'reader-body', 'sync-backdrop', 'sync-sites',
                   'sync-start', 'sync-close', 'sync-note', 'sync-btn', 'settings-link',
                   'site-tabs']
            missing = await ev(
                f'{json.dumps(ids)}.filter(id => !document.getElementById(id))')
            check('A2 旧契约 id 全部在(19 个)', missing == [], f'缺失:{missing}')

            n_tabs = await ev('document.querySelectorAll(".site-tab").length')
            check('A3 站点 Tab 4 个(全部+3站)', n_tabs == 4, str(n_tabs))
            n_sec = await ev('document.querySelectorAll(".date-section").length')
            check('A4 日期分章 3 段(今天/昨天/前天-3)', n_sec == 3, str(n_sec))
            n_cards = await ev(CARDS)
            check('A5 全部视图 12 张卡', n_cards == 12, str(n_cards))

            await click('.view-btn[data-view="timeline"]')
            ok = await wait_until('document.querySelectorAll(".tl-item").length === 12')
            check('A6 时间线切换:12 条', ok is not None)

            await click('.view-btn[data-view="columns"]')
            ok = await wait_until('document.querySelectorAll(".tri-col").length === 3')
            check('A7 三栏总览:3 栏', ok is not None)

            await click('.view-btn[data-view="cards"]')
            ok = await wait_until(f'{CARDS} === 12')
            check('A8 切回卡片流恢复 12 张', ok is not None)

            await click('#card-flow .card')
            ok = await wait_until('!document.getElementById("reader-backdrop").classList.contains("hidden")'
                                  ' && document.getElementById("reader-title").textContent.length > 0')
            check('A9 阅读抽屉打开且有标题', ok is not None)
            await ev('document.dispatchEvent(new KeyboardEvent("keydown", {key: "Escape"}))')
            ok = await wait_until('document.getElementById("reader-backdrop").classList.contains("hidden")')
            check('A10 ESC 关抽屉', ok is not None)

            await click('#sync-btn')
            n_sites = await ev('document.querySelectorAll(".sync-site").length')
            vis = await ev('!document.getElementById("sync-backdrop").classList.contains("hidden")')
            check('A11 同步面板打开且 3 行', vis and n_sites == 3, f'visible={vis} rows={n_sites}')
            await click('#sync-close')

            # ---- B 段:搜索新行为 ----
            has_input = await ev('!!document.getElementById("search-input")')
            if not check('B1 顶栏存在搜索框 #search-input', has_input, '功能未实现'):
                print('\nB 段后续断言依赖搜索框,跳过(实现后再跑)')
                return

            # 先回到干净状态:全部 Tab + 卡片流
            await click('.site-tab[data-source=""]')
            await wait_until(f'{CARDS} === 12')

            await type_input('吃瓜')  # input 事件 → 300ms 防抖自动搜
            ok = await wait_until(
                f'{CARDS} === 6 && document.getElementById("feed-meta").textContent.includes("搜索")',
                timeout=3)
            titles = await card_titles() if ok is not None else []
            check('B2 输入"吃瓜"防抖自动搜:6 张且标题都含"吃瓜"',
                  ok is not None and len(titles) == 6 and all('吃瓜' in t for t in titles),
                  str(titles))

            await type_input('', submit='esc')
            ok = await wait_until(
                f'{CARDS} === 12 && !document.getElementById("feed-meta").textContent.includes("搜索")')
            check('B3 ESC 清空恢复全部 12 张', ok is not None)

            await ev('(() => { const i = document.getElementById("search-input");'
                     'i.value = "张某某"; })()')  # 只改值不发 input:证明回车不等防抖
            t0 = time.monotonic()
            await type_input('张某某', submit='enter')
            elapsed = await wait_until(
                'document.getElementById("feed-meta").textContent.includes("搜索")', timeout=2)
            n = await ev(CARDS) if elapsed is not None else -1
            check('B4 回车立即搜(不等防抖):1 张"张某某"',
                  elapsed is not None and elapsed < 0.25 and n == 1, f'elapsed={elapsed} n={n}')

            await type_input('', submit='esc')
            await wait_until(f'{CARDS} === 12')
            await type_input('内幕 选秀', submit='enter')  # 多词 AND
            ok = await wait_until(f'{CARDS} === 1')
            titles = await card_titles()
            check('B5 多词 AND"内幕 选秀":只 1 张(选秀内幕那篇)',
                  ok is not None and titles == ['吃瓜群众集合!某选秀内幕曝光'], str(titles))

            await type_input('', submit='esc')
            await wait_until(f'{CARDS} === 12')
            await type_input('量子纠缠', submit='enter')
            ok = await wait_until(
                f'{CARDS} === 0 && document.getElementById("feed-meta").textContent.includes("没有匹配")')
            check('B6 无命中:0 卡且有"没有匹配"提示', ok is not None)

            await type_input('', submit='esc')
            await wait_until(f'{CARDS} === 12')
            await click('.view-btn[data-view="timeline"]')
            await wait_until('document.querySelectorAll(".tl-item").length === 12')
            await type_input('吃瓜')
            ok = await wait_until(
                'document.querySelector(".view-btn[data-view=\\"cards\\"]")'
                '.classList.contains("active") && document.querySelectorAll("#card-flow .card").length === 6')
            check('B7 时间线下搜索自动切回卡片流', ok is not None)

            await type_input('', submit='esc')
            await wait_until(f'{CARDS} === 12')
            await type_input('吃瓜', submit='enter')
            await wait_until(f'{CARDS} === 6')
            await click('.view-btn[data-view="columns"]')
            ok = await wait_until('document.querySelectorAll(".tri-col").length === 3'
                                  ' && document.getElementById("search-input").value === ""'
                                  ' && document.getElementById("feed-meta").textContent.includes("三栏")')
            check('B8 三栏总览时清空搜索(该视图不吃 q)', ok is not None)

            await click('.view-btn[data-view="cards"]')
            await click('.site-tab[data-source="wacg51"]')
            ok = await wait_until(f'{CARDS} === 4')
            check('B9 单站 Tab 4 张(wacg51)', ok is not None)
            await type_input('吃瓜', submit='enter')
            ok = await wait_until(f'{CARDS} === 2')
            srcs = await ev('[...document.querySelectorAll("#card-flow .card")]'
                            '.map(c => c.dataset.source)')
            check('B10 站内搜索"wacg51+吃瓜":2 张且都是 wacg51',
                  ok is not None and srcs == ['wacg51', 'wacg51'], str(srcs))

            await click('.site-tab[data-source=""]')  # 切 Tab 应清空搜索
            ok = await wait_until(
                f'{CARDS} === 12 && document.getElementById("search-input").value === ""')
            check('B11 切 Tab 自动清空搜索框', ok is not None)
    finally:
        proc.terminate()

    print()
    if _FAILED:
        print(f'结果:{len(_FAILED)} 项未过')
        for f in _FAILED:
            print(f'  - {f}')
        sys.exit(1)
    print('结果:全部通过')


if __name__ == '__main__':
    if sys.argv[1:2] == ['--seed']:
        seed()
    else:
        args = [a for a in sys.argv[1:] if not a.startswith('--width=')]
        url = args[0] if args else 'http://127.0.0.1:8788/'
        width = int(next((a[8:] for a in sys.argv[1:] if a.startswith('--width=')), 1440))
        asyncio.run(main(url, width))