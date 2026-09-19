# 上游站点侦察档案 · melon-hub

> **侦察日期**：2026-09-19（curl 实测 + Tavily 搜索交叉验证）
> **用途**：采集器开发的原始依据。结论版见 `docs/handoffs/melon-hub.md`，本文档保留全部细节与复现命令。
> **时效警告**：此类站点域名与结构常变，本文数据仅在侦察时点有效；接手后动手前应按第 5 节命令重新核验。

---

## 0. 总览

| 站点 | 真身 | 源头/主域名（候选，未逐一实测） | CF 盾 | 采集路径 |
|------|------|-------------------------------|-------|----------|
| hl365.com | 黑料不打烊（吃瓜/爆料内容农场） | **heiliao.com**（自称主域名；官方 X：@heiliao0） | 无（直连 200） | RSS `/feed` + 文章页抓正文 |
| 51cg1.com | 51吃瓜 的"回家的路"导航页 | **51cg.fun**（自称永久地址、需 VPN）+ **wacg4.com**（国内最新入口） | 有（403 challenge） | kimi-webbridge 真实浏览器 |
| www.mrds66.com | 每日大赛（66 号镜像） | **mrds.fun**（自称官网，未实测） | 有（challenge） | kimi-webbridge（**Vue SPA，必须渲染**） |

---

## 1. hl365.com（黑料不打烊）

### 1.1 访问实测

- `GET https://hl365.com/` → **HTTP 200，249,168 字节**，无反爬拦截，UA 为普通桌面 Chrome UA 即可。
- 页面 `<title>`：`黑料不打烊 - 吃瓜黑料、八卦爆料，24小时不打烊 | 深夜吃瓜观察室`
- 无 Cloudflare 痕迹。

### 1.2 内容结构（首页实测）

- **WordPress 系**：页面带 RSS 2.0 / RSS 1.0 / ATOM 1.0 订阅链接。
- 列表条目：`<li class="item">` 结构；条目含日期字段（样本 `2026-09-19`、`2026/09/19`），更新频繁（侦察当天即有当日内容）。
- 文章 URL 模式：`/archives/<数字id>.html`（实测样本：`221898`、`221894`、`221845`、`221827`、`221814`）。
- 广告密度：**61 个 `<script>` 标签、0 个 iframe**——广告全部来自内联脚本，清洗时按节点类型剔除即可。
- 站方推广元素：`黑料不打烊app` 下载、`Telegram` 引导（均为站方自有推广，采集时同样剔除）。

### 1.3 RSS feed 实测（`/feed`）

- `GET https://hl365.com/feed` → **HTTP 200，164,587 字节**。
- 每页 10 条（WordPress 默认）。
- 字段实测：
  - `<title>`：有（完整标题）
  - `<link>`：有（文章永久链接，如 `https://hl365.com/archives/221898.html`）
  - `<pubDate>`：有（如 `Sat, 19 Sep 2026 04:45:00 +0000`）
  - `<description>`：有，约 112 字符的短摘要
  - `content:encoded` 全文字段：**无** → 全文需按文章页单独抓取
- 分页规律（WordPress 惯例，未实测）：`/feed`、`/feed/?paged=2`…（接手后验证）。

### 1.4 镜像与源头（Tavily 搜索交叉验证）

| 域名/渠道 | 角色 | 来源 |
|-----------|------|------|
| heiliao.com | **源头主域名**（自称"主域名是 heiliao.com"，收录 6.5 万条，每日更新） | Tavily score 0.64，站点自述 |
| heiliao0（X 账号） | 官方 X，用于发布最新地址 | Tavily |
| heiliao.su | 线路之一 | Tavily（Google Sites 发布页） |
| hlbdy1.com | 线路页（"回家的路"性质，含免翻墙地址邮箱推送） | Tavily |
| 696.aovcyphn.cc | 入口发布页（含 App 下载链接 heiliao.tvckrxhd.cc、TG 群） | Tavily |
| hl365.com | 上述体系的一条线路（本档案实测对象） | 实测 |

**采集启示**：黑料体系的地址发布渠道（邮箱自动回复、X 账号、线路页）都是"镜像自动发现"的现成数据源，优先级建议：线路页 HTML 解析 > X 账号（需 API/浏览）> 邮箱自动推送（需交互）。

### 1.5 未验证项

- 文章页 `/archives/<id>.html` 的 DOM 结构与正文清洗规则（未抓取样例页）。
- RSS 分页参数是否有效。
- 镜像域名与 hl365 的内容同步延迟（hl365 与 heiliao.com 内容是否完全一致）。

---

## 2. 51cg1.com（51吃瓜）

### 2.1 访问实测

- `GET https://51cg1.com/` → **HTTP 403，5,485 字节**，`<title>Just a moment...</title>`——**Cloudflare challenge**，curl 无法通过。
- 需真实浏览器渲染（kimi-webbridge 路线）。

### 2.2 站点定位（Tavily 交叉验证）

- `51cg1.com/homeway.html` = **"回家的路"导航页**：51吃瓜最新地址、官方 TG/QQ/推特、邮箱自动推送、备用域名跳转——**镜像自动发现的首选入口**。
- 品牌官方渠道（Tavily）：51吃瓜官方频道 **@chiguaa51**（TG）；其发布的地址体系：
  - 最新入口（国内）：**wacg4.com**
  - 永久地址（需 VPN）：**51cg.fun**
  - 备用地址：lby52…（搜索结果截断，接手后从导航页/TG 获取全量）
- ⚠️ 甄别警告：搜索结果中的 `cg51.com` 内容为养生文章，**疑似无关/蹭名站**——同形域名未必同源，接入任何新域名前先比对内容指纹（标题/正文与已知内容交集）。

### 2.3 内容结构

- **未实测**（CF 挡住，未获取真实渲染页面）。列表/正文结构要在真实浏览器拿到渲染后 DOM 后才能写解析器。
- 同类站的通用特征（供预期管理）：列表 + 分页 + 图集为主，正文页广告密集。

### 2.4 未验证项

- wacg4.com / 51cg.fun 可达性与是否同样有 CF；真实渲染后的列表 DOM；文章/图集页结构；图片 CDN 域名。

---

## 3. www.mrds66.com（每日大赛）

### 3.1 访问实测

- `GET https://www.mrds66.com/` → HTTP 200 但内容为 **Cloudflare challenge**（`<title>Just a moment...</title>`，262KB challenge 页）——curl 拿不到真实内容。
- **首页 HTML 中出现 Vue 模板语法（`{{u.username}}`、`{{u.uid}}`）** → **SPA，客户端渲染**。即使过 CF，无 JS 渲染也拿不到列表 → **必须真实浏览器**。
- Tavily 能抓到其首页可见内容（说明其内容对真实浏览器可读）：站点标题"每日大赛-畅享24小时吃瓜爆料"，含"热搜"栏目（示例条目带日期"2026 年 09 月 18 日"，更新频繁）。

### 3.2 镜像与源头（Tavily 交叉验证）

| 域名/渠道 | 角色 | 来源 |
|-----------|------|------|
| mrds.fun | 自称"每日大赛官网"（校园大赛、反差大赛、吃瓜爆料聚集地） | Tavily（mobirise 站点页，**未实测可达性**） |
| www.mrds66.com | 66 号镜像 + **回家路页 `/ybml.html`**（最新地址列表 + 邮箱自动推送 + 备用域名跳转） | Tavily + 实测（页面存在） |
| mrds_9527（X 账号） | 官方发布渠道 | Tavily |

**采集启示**：`/ybml.html` 就是本站的"地址配置源"——定期抓这一页即可自动更新镜像列表；它也是 CF 后面的页面，同样走真实浏览器。

### 3.3 未验证项

- mrds.fun 可达性；真实渲染后的 DOM 结构（列表条目字段、翻页方式）；图片/视频资源 CDN 域名；内容是否有登录墙（搜索结果首页出现"我的钱包/消息中心"等用户功能文案 → 站点可能有会员体系，但浏览列表是否需要登录**待实测**；如遇登录墙即停，向用户请示）。

---

## 4. 跨站共性

1. **同一内容多站分发**：三站（及其镜像群）互抄严重，同一瓜常在 2-3 站出现——一期不去重，但 DB 指纹字段预留（title_hash / content_hash）。
2. **域名轮换是常态**：镜像号（51cg**1**、mrds**66**）+ 线路页 + 官方 TG/X 构成完整的"地址发布体系"——采集器配置化（源头 + 镜像池 + 发现源）是硬要求，用户已确认。
3. **内容农场同款页面特征**：大量内联 script 广告、App/TG 引导、SEO 尾巴——正文清洗器按"白名单节点保留"策略写，比"黑名单剔除"更稳。
4. **均无登录墙（浏览层）**：列表浏览当前均无需登录；若某站升级为登录可见，采集即停并向用户请示（红线）。

---

## 5. 复现命令（接手后核验用）

```bash
UA='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36'

# hl365 首页（预期 200，约 249KB）
curl -sL --max-time 25 'https://hl365.com/' -A "$UA" -o /tmp/hl365.html -w '%{http_code} %{size_download}B\n'

# hl365 RSS（预期 200，约 165KB，10 条/页）
curl -sL 'https://hl365.com/feed' -A "$UA" -o /tmp/hl365-feed.xml -w '%{http_code} %{size_download}B\n'

# 51cg1（预期 403 CF）
curl -s -o /dev/null -w '%{http_code}\n' 'https://51cg1.com/' -A "$UA"

# mrds66（预期 200 但为 CF challenge 页，标题 Just a moment）
curl -sL 'https://www.mrds66.com/' -A "$UA" | grep -oE '<title>[^<]*</title>' | head -1

# Tavily 搜索源头（使用 enhanced-tavily-search skill 的脚本）
# python3 ~/.claude/skills/enhanced-tavily-search/scripts/tavily_search.py '<查询词>'
```

## 6. 证据临时文件（可能已失效）

侦察时的原始抓取文件在 `/tmp`（机器重启即失效，关键事实已内嵌本文）：
`/tmp/site_c50562.html`（hl365 首页）、`/tmp/hl365-feed.xml`、`/tmp/site_e51691.html`（51cg1 CF 页）、`/tmp/site_314c94.html`（mrds66 challenge 页）。

## 7. 地址簿（防丢失总表 · 2026-09-19 快照）

> 本节是全档案的"联系人卡片"。域名会死，**收藏本表 + 回家路页**即可自愈；任何域名失效时按第 5 节复现命令重新核验。

### 7.1 黑料不打烊（hl365.com 线路）

| 类型 | 地址 | 说明 |
|------|------|------|
| 源头主域名 | https://heiliao.com | 自称主域名，收录 6.5 万条，每日更新 |
| 实测线路 | https://hl365.com | 本档案的实测对象，无 CF，有 RSS |
| 线路（备用） | https://heiliao.su | Tavily 记录，未实测 |
| 线路/回家路 | https://hlbdy1.com | 含免翻墙地址邮箱自动推送 |
| 入口发布页 | https://696.aovcyphn.cc | 发布最新入口（含 App 下载） |
| App 下载页 | https://heiliao.tvckrxhd.cc | 站方 App（仅记录，采集不涉及） |
| 官方 X | https://x.com/heiliao0 | 最新地址通知渠道 |
| 官方 TG 群 | 链接未拿到全量（在入口发布页里） | 接手后从 696.aovcyphn.cc 提取 |

### 7.2 51吃瓜

| 类型 | 地址 | 说明 |
|------|------|------|
| 永久地址（需 VPN） | https://51cg.fun | 官方频道公布 |
| 国内最新入口 | https://wacg4.com | 官方频道公布，未实测 |
| 备用地址 | https://lby52…（截断） | 完整清单在导航页/TG 里 |
| 回家路导航页 | https://51cg1.com/homeway.html | 本项目实测对象之一（CF 403，需真实浏览器） |
| 官方 TG | @chiguaa51（https://t.me/chiguaa51，由 tgstat 镜像页反推） | 地址发布主渠道 |
| ⚠️ 无关站 | https://cg51.com | 内容为养生文章，疑似蹭名，勿混入 |

### 7.3 每日大赛（mrds66 线路）

| 类型 | 地址 | 说明 |
|------|------|------|
| 官网候选（未实测） | https://mrds.fun | 自称官网（校园/反差/吃瓜赛事聚合） |
| 实测镜像 | https://www.mrds66.com | CF challenge + Vue SPA |
| 回家路页 | https://www.mrds66.com/ybml.html | 最新地址列表 + 邮箱自动推送 + 备用域名跳转（**镜像自动发现首选源**） |
| 官方 X | https://x.com/mrds_9527 | 发布渠道 |

### 7.4 地址自愈机制备忘

- 每站的"回家路"页（51cg1 `/homeway.html`、mrds66 `/ybml.html`、黑料的线路页）是**官方地址发布口**——采集器定时抓这些页即可自动更新镜像池。
- 官方 TG/X 是兜底发布渠道；TG 链接多藏在入口发布页内（注意页内邮箱是 Cloudflare email-protection 混淆的，需真实浏览器或解码才能看到明文）。
- 新域名接入前先做内容指纹比对（标题/正文与已知内容交集），防止蹭名站混入（参见 2.2 的 cg51.com 警告）。

## 8. 侦察方法备忘

- HTTP 层用 `curl -sL` + 桌面 Chrome UA（不重试、不加压，单次单请求，遵守 2 秒频控规范）。
- 域名归属与官方渠道用 Tavily 搜索交叉验证，不轻信单一来源；同形域名需内容比对后才认定同源。
- 真实渲染层（CF 后两站）留待 kimi-webbridge 实测：健康检查 → 打开页面 → 语义读取 → 保存渲染后 HTML → 关闭 session。