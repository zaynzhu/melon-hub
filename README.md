<div align="center">

# 🍈 melon-hub

[中文](README.md) | [English](README_EN.md)

[![GitHub Stars](https://img.shields.io/github/stars/zaynzhu/melon-hub?style=flat&logo=github)](https://github.com/zaynzhu/melon-hub/stargazers)
[![Last Commit](https://img.shields.io/github/last-commit/zaynzhu/melon-hub?style=flat&logo=git)](https://github.com/zaynzhu/melon-hub/commits/main)
[![Issues](https://img.shields.io/github/issues/zaynzhu/melon-hub?style=flat&logo=github)](https://github.com/zaynzhu/melon-hub/issues)

**一个界面同时浏览多个内容站的最新内容，点开即读去广告的干净正文。**

</div>

> [!TIP]
> melon-hub 是个人自托管的多源内容聚合阅读面板：采集器把各内容站的最新文章抓进你自己的 MySQL + RustFS（或本地 SQLite），FastAPI 后端提供干净的阅读接口，聚合前端支持卡片流 / 时间线两种视图和全屏阅读抽屉。数据完全落在自有基建，仓库本身不包含任何采集内容。

---

## ✨ Features

- **多源聚合** -- Tab 切换浏览各内容站最新列表，卡片流 / 时间线 / 三栏总览多视图，来源配色一眼区分
- **干净阅读** -- 正文自动清洗去广告，全屏阅读抽屉，缓存命中秒开
- **手动同步** -- 页面一键选站采集，逐站实时进度与结果（浏览器站无环境时自动提示）
- **内置定时** -- 每隔 N 小时 / 每天定点两种模式独立开关，设置页可视化配置，无需系统级定时任务
- **双存储驱动** -- 配置 MySQL + RustFS 即接入自有基建；不配置自动回退 SQLite + 本地目录，上层接口不变
- **可靠采集** -- 主机级 2 秒频控、增量幂等重跑、遇登录墙 / 验证码自动停止
- **优雅降级** -- 失效图片自动占位，列表缩略图独立采集入库
- **容器化** -- 单 Docker 容器同时跑 API、前端与定时采集（实验性）

---

## 🚀 Quick Start

```bash
git clone https://github.com/zaynzhu/melon-hub.git
cd melon-hub
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m collector.hl365
.venv/bin/python -m uvicorn server.app:app --port 8787
```

打开 [http://127.0.0.1:8787](http://127.0.0.1:8787) 即可浏览。默认使用本地存储，无需任何配置。

> [!NOTE]
> hl365 走 RSS 直连采集，无需浏览器。51吃瓜 / 每日大赛两站有 Cloudflare 防护，需在宿主机配置 kimi-webbridge 浏览器通道后运行对应采集器，详见 [Usage](#-usage)。

---

## 📦 Installation

### 方式一：源码运行

```bash
git clone https://github.com/zaynzhu/melon-hub.git
cd melon-hub
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env   # 可选:配置 MySQL / RustFS,不配置则使用本地存储
```

主要依赖：`fastapi`、`uvicorn`、`requests`、`beautifulsoup4`、`PyYAML`、`boto3`、`PyMySQL`。

### 方式二：Docker（实验性）

```bash
docker build -t melon-hub .
docker run -d --name melon-hub -p 8787:8787 -v melon-data:/data melon-hub
```

容器即启动 API 与前端（8787 端口），定时采集由应用内调度器负责：默认「每隔 6 小时 + 每天 03:00」各增量采集一次 hl365，进 `/settings.html` 设置页可改间隔 / 时间或关掉任一模式；顶栏「同步」按钮可随时手动拉取。首次启动会自动采集一次。

> 部署提示：定时调度器运行在 API 进程内，务必保持单实例（uvicorn 单 worker）；多实例会重复采集。

---

## 💡 Usage

### 增量采集

```bash
.venv/bin/python -m collector.hl365             # hl365: RSS 直连,重跑幂等
.venv/bin/python -m collector.wacg51 --limit 8  # 51吃瓜: 浏览器采集,单次正文 8 篇
.venv/bin/python -m collector.mrds --limit 8    # 每日大赛: 同上
```

### 历史补齐与缩略图

```bash
.venv/bin/python -m collector.hl365 --backfill           # 列表翻页入库 + 正文与正文图入库
.venv/bin/python -m collector.wacg51 --backfill --pages 4
.venv/bin/python -m collector.wacg51 --thumbs            # 补抓列表缩略图(两站通用)
.venv/bin/python scripts/thumbs_backfill.py              # 三站缩略图兜底补抓(幂等只补缺)
.venv/bin/python -m collector.discover                   # 回家路页镜像自动发现(--apply 才写配置)
```

> 图片原理与踩坑（CDN 加密分发、页面内解密路线）见 `docs/image-decrypt-playbook.md`。

### 启动阅读面板

```bash
.venv/bin/python -m uvicorn server.app:app --port 8787
```

顶栏切换三站 / 视图（卡片流 / 时间线 / 三栏总览），点卡片进全屏阅读抽屉，右上角"查看原文"跳转源站。**首页按日期分章**（每天一章节，大日期数字+今天+篇数），当日第一条自动升级为焦点大图；时间线日期锚点是大字标题；三栏总览列头显示"今日 +N"。

### 同步与定时采集

- **手动同步**：顶栏「同步」按钮，勾选站点后开始，面板实时显示每站进度（hl365 RSS 直连秒级完成；51吃瓜 / 每日大赛走本机浏览器，单站约需数分钟）。
- **定时采集**：打开 `/settings.html`，两种模式独立开关——「每隔 N 小时」与「每天 HH:MM」（时区 `MELON_TZ`，默认 Asia/Shanghai），可只留一种或全关。定时只采集 hl365（无需浏览器），配置存在数据库，重启不丢。

---

## 🗺️ Roadmap

| 状态 | 事项 |
|------|------|
| ✅ | 三站聚合浏览 + 全屏阅读抽屉 + 时间线视图 |
| ✅ | MySQL + RustFS 存储、本地自动回退 |
| ✅ | 历史文章翻页补齐、列表缩略图采集 |
| ✅ | 三栏总览视图、回家路页自动发现新镜像 |
| ✅ | 正文密文图批量解密入库（2788 张，2026-09-29） |
| ✅ | 页面手动同步 + 应用内定时采集（2026-09-29） |
| ⏸️ | 跨站去重视图（实测真重复仅 2-3 组，语料上量后再评估） |
| 📋 | Docker 镜像构建验证 |

---

## 📚 Documentation

| 文档 | 说明 |
|------|------|
| [docs/handoffs/melon-hub.md](docs/handoffs/melon-hub.md) | 项目交接文档：架构、决策依据、当前状态 |
| [docs/recon-upstream-2026-09-19.md](docs/recon-upstream-2026-09-19.md) | 上游站点侦察档案：数据源与域名实测记录 |
| [config/sites.yaml](config/sites.yaml) | 站点采集配置：源头、镜像池、解析器 |
| [.env.example](.env.example) | 环境变量模板：数据库与对象存储接入 |

---

## 🤝 Contributing

个人自用项目，暂不接受功能 PR；遇到问题欢迎提 [Issue](https://github.com/zaynzhu/melon-hub/issues)。开发环境搭建与 [Quick Start](#-quick-start) 相同，改动验证方式：采集脚本连跑两遍对比幂等、后端接口 curl 抽查。

---

## ❓ FAQ

<details>
<summary>为什么有些图片显示占位符？</summary>

三站图片走 AES-CBC 加密分发（密钥在站内 JS），本项目已通过页面解密路线把 2788 张正文密文图批量解密入库（2026-09-29），缩略图亦全覆盖。个别图仍显示占位符，多为源站图片本身已失效；前端会自动降级，不影响文字阅读。
</details>

<details>
<summary>数据存储在哪里？</summary>

配置 <code>.env</code> 后写入自有的 MySQL 与 RustFS / S3；不配置则回退本地 SQLite（<code>data/melon.db</code>）与对象目录（<code>data/objects/</code>）。仓库本身不包含任何采集内容。
</details>

<details>
<summary>采集会对目标站造成压力吗？</summary>

采集器内置主机级 2 秒频控与增量幂等，遇到登录墙 / 验证码即停止，不做任何绕过站点安全机制的操作。
</details>

---

## ⚠️ Disclaimer

本项目为个人自用的阅读聚合工具，不托管、不转载、不分发任何第三方内容，仓库内不包含任何采集数据；所有内容均来自公开可访问的第三方站点，版权归原作者所有，如有侵权请联系删除。使用时请遵守所在地区法律法规。本项目暂未设置开源许可证（默认保留所有权利）。
