# 前端改版时 JS 契约核对(选择器/id/data-* 是暗契约)

> UI 改版、视觉重写、加新视图时,最容易出的错是"JS 里写了 `document.querySelector('.x')` 但你改了 HTML class,或者新增 DOM 没用 JS 期待的 ID"。本次 melon-hub UI v2 改版实测全流程。

## 结论速览

- **改 HTML 前先列出 JS 用到的全部 selector**,改完跑 headless Chrome 断言("每个 id/class 还在")
- **断言写一次性 Python/CDP 脚本**,不要靠肉眼

**适用条件**:任何手写 JS + HTML/CSS 的项目(尤其是 vanilla JS 直接管 DOM,没用框架)。React/Vue 项目里数据流由框架管,本条不适用。

---

## ✅ JS 契约清单 + headless CDP 断言流程(2026-09-30 实测)

- **为何值得记**:melon-hub 改版涉及 50+ 个 JS 操作的 id/class,人手 grep 容易漏;改完一次直接跑断言脚本立刻能报告"哪个选择器没了/对应 DOM 在哪",省一小时盲查。
- **断言模板**(实测通过,可直接改造用):

```python
# scripts/ui_contract_assert.py(模板,按需改)
import asyncio, json, base64, subprocess, time, urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
PORT = 9333

async def run(url, script):
    """script 是 JS 字符串,返回值会被打印。"""
    proc = subprocess.Popen([CHROME, "--headless=new", "--disable-gpu",
        f"--remote-debugging-port={PORT}", "--hide-scrollbars",
        "--window-size=1440,900", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(30):
        try: urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version"); break
        except Exception: time.sleep(0.3)
    import websockets
    req = urllib.request.Request(f"http://127.0.0.1:{PORT}/json/new?about:blank", method="PUT")
    with urllib.request.urlopen(req) as r: tab = json.loads(r.read())
    async with websockets.connect(tab["webSocketDebuggerUrl"], max_size=64*1024*1024) as ws:
        mid = 0
        async def send(method, params=None):
            nonlocal mid; mid += 1; i = mid
            await ws.send(json.dumps({"id": i, "method": method, "params": params or {}}))
            while True:
                m = json.loads(await ws.recv())
                if m.get("id") == i: return m.get("result", {})
        async def ev(expr):
            return (await send("Runtime.evaluate", {"expression": expr, "returnByValue": True})).get("result", {})
        await send("Page.enable")
        await send("Emulation.setDeviceMetricsOverride", {"width":1440,"height":900,"deviceScaleFactor":1,"mobile":False})
        await send("Page.navigate", {"url": url})
        await asyncio.sleep(2)
        result = await ev(script)
        print(json.dumps(result.get("value"), ensure_ascii=False, indent=2))
    proc.terminate()

# 用例:melon-hub 改版后断言所有 id 都在
asyncio.run(run("http://127.0.0.1:8787/", """
  ['feed-meta','card-flow','load-more','reader-backdrop','reader-close',
   'reader-source','reader-title','reader-date','reader-origin','article-content',
   'sync-backdrop','sync-sites','sync-start','sync-btn','reader-body']
   .map(id=>({id, ok:!!document.getElementById(id)}))
"""))
```

- **断言内容物不止 id 在不在**:还要断言**功能行为**(tab 切换 / 视图切换 / 抽屉打开 / 同步面板渲染 / 表单字段可写):

```python
# 同脚本继续:模拟点击
await send("Runtime.evaluate", {"expression": 'document.querySelector(".view-btn[data-view=\\"timeline\\"]').click()'})
await asyncio.sleep(0.5)
state = await ev("({tl_items: document.querySelectorAll('.tl-item').length})")
# 时间线该有 50 个条目
```

- **为什么这样做**:JS 契约是**隐性 API**——HTML 里的 class/id/data-* 对 JS 就是签名;视觉改版改的是 CSS/布局,不该动 DOM 结构(尤其 id);用断言可以在 commit 前发现"少了个 `.sync-site`"级问题。
- **适用条件**:vanilla JS 项目;**前端改版前后必跑**(同一断言列表复用,改版后再跑一遍对比)
- **验证证据**:melon-hub UI v2 改版后断言全过(50 卡片/3 tab/4 view 切换/抽屉打开/同步面板 3 行)
- **交叉验证**:单 agent;改版流程截图存档在 `/tmp/melon-ui/{before,after,final}/` 可对比
- **关键步骤**:
  1. 改 HTML/CSS 前把现有 JS 用到的所有 selector `grep -E "\$\(|getElementById|querySelector" web/app.js > /tmp/contracts.txt`
  2. 改版时同步维护一张"暗契约清单"(改了哪个 id/class 要在清单里同步标记)
  3. 改完跑 CDP 断言脚本
  4. 断言失败一律回滚,不允许"先 commit 再说"
- **易错点**:
  - **新增 DOM 元素时容易忘记给 JS 期待的 id**——本次 settings.html 加镜像面板时差点没加 `id="sites-detail-list"`,断言立刻发现
  - `data-*` 属性变更也是契约(如 `data-source="hl365"`),改 selector 时容易忽略
  - headless 里 `document.scrollTo` 不会触发 `scroll` 事件——测滚动相关契约要 `Element.scrollTop = N` 然后手动 `dispatchEvent`

---

## 🔶 待验证:改版前后 UI 截图对比归档机制

- **当前推断**:`/tmp/melon-ui/{before,after,final}/*.png` 这种"改版前/后/最终"三目录归档很有用(用户随时能回看),但如果改版多次,`/tmp/` 会被清空
- **已到哪一步**:改版时把截图复制到 `docs/ui-snapshots/<日期>-<主题>/` 并 commit,作为视觉历史
- **下一步验证动作**:下次再改版时跑通这条流水线(写个 `scripts/ui_snapshot.sh`),如果好用纳入常规
- **为何值得继续**:本次发现"改完用户立刻能对比"是降低沟通成本的关键;没有归档就只剩文字描述
