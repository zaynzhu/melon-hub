# 三站图片解密与缩略图补抓 · 实战档案

> **日期**：2026-09-20
> **性质**：技术突破记录 + 可复用操作手册。本文是"为什么"和"怎么复现"；代码固化在 `scripts/thumbs_backfill.py`，原理注释在 `collector/hl365.py`、`collector/typecho_collector.py`。
> **成果**：三站 356 篇缩略图从"仅 wacg51 96/100"补到 **356/356 全覆盖**，全部魔数校验通过（JPEG `FF D8`）。
> **推翻的旧结论**：交接文档曾记"真图补齐唯一路线是等源站解密链路恢复后跑 `scripts/fix_images_browser.py`"——**该结论已过时**，见第 2 节。

---

## 1. 问题背景：为什么图片全是"坏的"

三站正文/缩略图 CDN（hl365 用 `pic.hdhwqx.cn`，wacg51/mrds 共用 `pic.ndhixj.cn`）对**所有 HTTP 客户端**返回加密字节：

- HTTP 200、`content-type: image/jpeg`，但字节非图片魔数（hl365 密文头 `3eaa 708e`，mrds 密文头同族）。
- 加请求头、Referer、cookie 均无效——密钥不在传输层，在**站内 JS**（`z-image-loader` 解密器）。
- 只有浏览器里站内 JS 解密后才能显示，但解密链路（年龄门→IndexedDB→Web Worker）在列表页**根本不触发**。

**判图铁律（再强调）**：校验图片必须查魔数（`FF D8` JPEG / `89 50 4E 47` PNG / `GIF8`），curl 200 校验发现不了密文。

---

## 2. 突破点：`decryptImage()` 是全局函数

### 2.1 关键发现

hl365 页面 window 上挂着一批全局函数（`Object.keys(window)` 过滤 image 相关即可看到）：

```
loadImage, decryptImage, is_cdnimg, loadBackgroundImage, ...
```

`decryptImage(b64密文)` 的真身（从混淆代码还原）：

```
CryptoJS.AES.decrypt(密文b64, KEY, {iv: IV, mode: CBC, padding: Pkcs7})
  → 返回明文 base64（即真图字节）
```

**密钥和 IV 硬编码在 `usr/plugins/ai/common/image.*.js` 的混淆代码里**（`String.fromCharCode(0x65)+...` 拼 "enc"/"Utf8"），站方没换过就永远可用。不需要逆向密钥——直接调这个函数就行。

### 2.2 推翻两个认知

| 旧认知 | 实测真相 |
|--------|----------|
| 列表页解密失败 = 解密链路（年龄门/IndexedDB/Worker）坏了 | 列表页图不在视口，**IntersectionObserver 从不触发**，解密 JS 压根没跑。手动喂密文给 `decryptImage()` 完全可行，与年龄门无关 |
| 真图必须等源站恢复后借浏览器 blob 取（`fix_images_browser.py` 路线） | 服务端拿密文 + 页面内调 `decryptImage` 即可，**不依赖源站恢复**，且比 blob 路线快得多（不用等滚动解密） |

### 2.3 完整解密链路（可复用）

```
服务端 requests GET 密文 URL
  → base64 编码
  → 分块(40KB)注入页面: window.__mhCT += "..."
  → 页面内 eval: decryptImage(window.__mhCT)
  → 得明文 base64(真图)
  → 分块取回 → b64decode → 验魔数 → 入对象存储
```

为什么分块 40KB：webbridge evaluate 传大字符串偶发失败/挂起，40KB 实测稳定；块间 sleep 1-1.5s。

### 2.4 当天实测数据（评估可行性用）

- hl365 列表翻 12 页（每页 30 卡片）建 `post-card id → z-image-loader-url` 映射，覆盖库内 111/112 篇；剩 1 篇（221515）从文章页 `itemprop="image"` 兜底。
- RSS 路线只有 10 篇带图源（feed 里 `content:encoded` 的图片是 `z-image-loader-url` 属性,采集器已存），列表页才是缩略图主来源。
- CDN 密文按 URL 定位；**requests 偶发返回 0 字节但 curl 同 URL 稳定 200**（Content-Length 都有，属瞬时问题，重试 3-4 次即可）。

---

## 3. mrds/wacg51 的捷径：文章页首图是明文

**与 hl365 不同源**：mrds/wacg51 正文页 `.post-content img` 的 src 直接是**明文 base64 data:URI**（`data:image/jpeg;base64,/9j/4AAQ...`），`naturalWidth=800` 正常渲染。不用解密，直接取：

```
navigate 文章页 → 取 .post-content 第一张 img 的 data:src.split(',')[1]
  → b64decode → 验魔数 → 入对象存储
```

适用场景：列表卡片缺图（文章被挤到第 2/3 页、或源站列表根本不渲染它的卡片），从文章页兜底缩略图。mrds 17 篇、wacg51 4 篇（275398/275615/275777/275783）均如此补齐。

**注意**：mrds 文章页没有 `.post-card`（等它超时是浪费），wait_selector 要用 `.post-content`。

---

## 4. 踩坑清单（换人/换 agent 前必读）

1. **`decryptImage` 返回空字符串不报错**——它在函数体里 `catch(e){return ''}`，密文错了只会静默返回空。所以解密后必须**查明文长度**，不能只看"没抛异常"。
2. **解密入参是 base64 密文字符串，不是 URL**。`decryptImage('https://pic...')` 不报错但返回空——先 fetch 密文再喂 base64。
3. **页面内 fetch 密文 CDN 拿不到数据**（CORS 响应剥离，`await r2.arrayBuffer()` 得到 undefined 报 `Cannot read properties of undefined`）。所以必须**服务端取密文**，页面只做解密。
4. **webbridge evaluate 返回值有时是对象不是 JSON 字符串**——同样代码有时返回 `json.loads` 能吃的字符串，有时直接返回 list。稳妥写法：页内代码末尾自己 `JSON.stringify(...)`，外层再判断类型；或像现有 `typecho_collector.py` 那样所有 eval 包一层。
5. **requests 取密文偶发 0 字节**（status 200、Content-Length 120KB、body 空的概率约 2 成）。curl 同 URL 稳定。重试 3-4 次即可，别把它当风控升级。另一个细节：第一次跑服务端 fetch 时用 `len(ct)` 判断，不要信 `resp.status_code==200` 就放过空体。
6. **mrds 文章页导航等待 `.post-card` 必超时**——文章页没有该节点，用 `.post-content`。
7. **`loadImage(img)` 调了没反应**——它内部走 IntersectionObserver 异步链路，列表页不触发的原因没变。别在这条路上浪费时间，直接 `decryptImage`。
8. **注入大 base64 前先 `window.__mhCT = ""` 清零**——跨文章残留会解出上篇的图，不报错、魔数也对，但内容张冠李戴。
9. **hl365 有 PNG 缩略图**（如 221742 的卡片是 `.png`）——存 `thumb.png`，`server/app.py` 的 `_cover` 不挑扩展名直接拼 key，入库时按魔数定扩展名即可。
10. **RSS 只覆盖 10/121 篇的图源**——缩略图主来源是列表页卡片 `z-image-loader-url` 属性，别指望 feed。
11. **本地 `data/melon.db` 是旧库存根**：项目根目录有 `data/melon.db` 但**不是服务所用库**——`.env` 里 `MELON_DB_URL=mysql://192.168.50.233:13306/melon_hub`，服务直连远端 MySQL 和 RustFS。本地库连 `thumb_object` 列都没有（旧 schema 迁移残留）。**排查问题前先 `python -c "from collector.config import data_dir; print(data_dir())"` 看代码实际落点**，别拿本地库当真相源。
12. **`_fetch_cipher` 的空体判断不能漏**：`requests.get` 返回 200 但 body 空的概率约 2 成,必须用 `if resp.content and len(resp.content) > 0` 双重判断;只查 `resp.status_code == 200` 会放过空体导致后续 base64 encode 0 字节、解密静默失败,排障时会误判成"密钥错了"。
13. **hl365 列表卡片页正则的坑**：`id="post-card-(\d+)"[^>]*>.{0,400}?z-image-loader-url` 里 `.{0,400}` 是防 HTML 里跨节点乱撞的保守上界,实测列表页一个卡片平均 400-600 字节标签量,上界写小了会漏匹;同时**必须用 `re.S`**(卡片标签多行),漏了会匹配不到卡片。
14. **`decryptImage` 密钥/IV 位置会变**：`usr/plugins/ai/common/image.0821.js`（2026-09-20 版本)密钥硬编码在 `_0x442c(...)` 索引表里,文件名带日期(`0821`)——站方换版本会同时改密钥。**接手重跑前先 curl 该 JS 文件,确认当前版本与文档记录一致**;不一致时重新从混淆代码提取密钥（找 `String.fromCharCode` 拼接出 "enc"/"Utf8" 的位置）,别默认密钥不变。

**webbridge 层的坑（evaluate 类型抖动/navigate 换 tab/session 残留）见配套的 `docs/webbridge-playbook.md`**——解密链路的坑 2、3、4、8 是工具层的，不是业务层的。

---

## 5. 复用工具：`scripts/thumbs_backfill.py`

本次临时代码已固化为可重跑脚本（幂等：已有 thumb 的跳过）：

```bash
.venv/bin/python scripts/thumbs_backfill.py                    # 三站全跑（默认只补缺）
.venv/bin/python scripts/thumbs_backfill.py --source hl365    # 单站
.venv/bin/python scripts/thumbs_backfill.py --limit 20        # 限篇数
```

路线分工（脚本内自动选择）：
- **wacg51 / mrds**：先列表页 `--thumbs` 流程（卡片 base64 背景图），漏网的走文章页首图（明文 data:URI）。
- **hl365**：列表页翻页建 `卡片→图URL` 映射 → 服务端取密文 → 页面 `decryptImage` 解密 → 入库；映射外文章从文章页 `itemprop="image"` 兜底。

验证方式（跑完必做）：

```bash
# 覆盖率:三站 count(thumb_object is not null) 应等于 count(*)
# 魔数:S3 直链抽查 head -c 2 应为 ffd8
# 前端:/api/articles?limit=50 的 cover 字段零空值
```

---

## 6. 对既有文档的修正

- `docs/handoffs/melon-hub.md` 中"图片真图获取依赖源站解密链路恢复，非本项目代码问题"→ 已被本文第 2 节推翻。
- 记忆层 `melon-hub-upstream-corrections` 已同步此结论（2026-09-20）。
- `scripts/fix_images_browser.py`（正文真图修复）现在有了更优路线：同一解密原理可批量修复正文密文图（`images_json` 里 1800+ 张密文对象），待做。