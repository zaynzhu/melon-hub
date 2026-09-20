# kimi-webbridge 工具陷阱手册 · melon-hub 实战沉淀

> **日期**：2026-09-20
> **性质**：kimi-webbridge（真实浏览器驱动）在本项目实战中验证过的坑与应对。通用性高，不限 melon-hub。
> **配套**：图片解密的业务原理见 `docs/image-decrypt-playbook.md`（本文只讲工具层）。

---

## 1. 为什么这份手册存在

kimi-webbridge 是本项目的**一切浏览器路线的地基**：列表采集、文章页兜底、缩略图解密，全靠它驱动真实 Chrome。但工具行为有几个反直觉的点，第一次遇到时会反复踩。这 4 坑在 2026-09-20 三站缩略图补抓中全部踩过并验证过解法。

**调用铁律**（全局规范 + 本项目实践）：
1. 先健康检查（`browser_fetch.ensure_ready()`）——不查就开跑，挂起或无声失败很难定位
2. 页面语义操作，别用坐标截图硬点
3. **任务结束关闭 session**（见第 3 节——本项目目前**没做**，已知缺口）

---

## 2. 反直觉行为与踩坑

### 坑 1：`navigate()` 静默换 tab，上一个 tab 的窗口变量全部丢失

**现象**：连续调两次 `navigate()` 到不同 URL，第二次的 evaluate 报 `Cannot read properties of null`，明明刚才明明有那个节点。

**根因**：`browser_fetch.navigate()` 内部有跳走检测（广告页 JS 跳转自动拉回）。`session` 绑定的 tab 被导航走后，`window.__mhXXX` 之类的**临时变量全部清零**——页面重载连 sessionStorage 都清了。

**解法**（当前代码已有）：**不要把状态塞进 window 跨 navigate 复用**。每次 navigate 后从头建上下文；要跨页面传值走服务端（文件/DB 中转），别走 window 变量。

### 坑 2：`evaluate` 注入大字符串偶发超时/挂起，分块是唯一稳定解法

**现象**：一次 evaluate 注入/出参 200KB+ 的 base64，偶发抖动到 45s 超时；同样代码重跑可能又过。

**解法**：**分块 40KB**，块间 `time.sleep(1.0~1.5)`（遵守同一 host ≥2s 频控，且留解码余量）。注入侧与取出侧都要分块——单侧分块没用。`scripts/thumbs_backfill.py:_decrypt_via_page` 是成熟模板。

**失败特征**：evaluate 挂起 45s 报 daemon 超时，不是 JS 报错。看到"超时"就要往分块/重试想，不是页面 JS 问题。

### 坑 3：`evaluate` 返回值类型不固定，JSON 字符串 vs 原生对象

**现象**：同样的 JS 代码，有时返回 `"[...]"`（字符串需要 `json.loads`），有时直接返回 `list`。

**解法**：页内代码末尾**固定 `JSON.stringify(...)` 返回**，把序列化责任留在页面侧；**外层仍要做类型判断**（webbridge 偶发反序列化差异）：

```python
out = browser.eval_js('(() => { ...; return JSON.stringify(...); })()')
if isinstance(out, str):
    out = json.loads(out)
```

`collector/typecho_collector.py` 所有 eval 均如此，新增代码别偷懒。

### 坑 4：本项目 session 没关，下一位接手前需先清残留（已知缺口）

**现状**：`collector/browser_fetch.py` 用固定 session 名 `melon-hub-imgfix`，**没有 close 动作**；历史采集的 navigate 会复用同一 tab，但 tab 状态（当前 URL、年龄门 localStorage、Cookie）跨会话残留。

**影响**：
- 好处：CF 过盾后的有效 session 复用，省一次挑战
- 坏处：残留状态可能是过期 CF 盾、或者上一个 task 没跑完的解密图（`window.__mhCT` 残留）

**接手自检**：跑采集前先 `pgrep -f collector.\|scripts/` 看有没有孤儿 python 还在跑（2026-09-19 深夜孤儿进程反而干完 24 篇的教训）；如要全新跑，改 `SESSION` 名或直接重启 webbridge daemon。

**待做**：给 `browser_fetch.py` 加 `close()` 入口，各 collector 脚本末尾统一调——二期补自动化时一起做。

---

## 3. 验证工具状态的标准流程（每次开跑前做）

```bash
# 1. 健康检查
.venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from collector import browser_fetch
browser_fetch.ensure_ready()
print('webbridge OK')
"

# 2. 看有没有残留会话/孤儿进程
pgrep -f "scripts/\|collector." 

# 3. 单页小样本验证(别直接跑批量)
.venv/bin/python -c "
import sys; sys.path.insert(0,'.')
from collector import browser_fetch
browser_fetch.navigate('https://example.com')
print(browser_fetch.eval_js('document.title'))
"
```

---

## 4. 本项目已验证的高频操作片段

- **列表采集**（`typecho_collector.collect_list/collect_thumbs`）：base64 背景图取缩略图,卡片 id 用 `post-card-<key>` 命名,过滤 `ad-card-*` 广告卡。
- **文章页兜底首图**（`scripts/thumbs_backfill.py:backfill_article_firstimg`）：正文页第 1 张 `.post-content img` 直接取；**wait_selector 用 `.post-content` 不用 `.post-card`**（文章页没有卡片节点）。
- **密文解密**（`scripts/thumbs_backfill.py:_decrypt_via_page`）：服务端取密文 → 分块注入 window → 页面 `decryptImage` → 分块取出。踩坑细节见配套业务文档。

---

## 5. 对既有记忆的映射

记忆层 `kimi-webbridge-gotchas`（screenshot 挂起 / 图片直链导航不切上下文 / network detail body 可能为空）与本文互补：记忆讲"现象"，本文讲"在本项目里怎么避开"。两份都要读。