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

容器入口会启动时采集一次 hl365 并每小时增量；API 与前端在 8787 端口。

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
.venv/bin/python -m collector.hl365 --backfill           # 列表翻页入库 + 纯文字正文
.venv/bin/python -m collector.wacg51 --backfill --pages 4
.venv/bin/python -m collector.wacg51 --thumbs            # 补抓列表缩略图(两站通用)
.venv/bin/python -m collector.discover                   # 回家路页镜像自动发现(--apply 才写配置)
```

### 启动阅读面板

```bash
.venv/bin/python -m uvicorn server.app:app --port 8787
```

顶栏切换三站 / 时间线视图，点卡片进全屏阅读抽屉，右上角"查看原文"跳转源站。

---

## 🗺️ Roadmap

| 状态 | 事项 |
|------|------|
| ✅ | 三站聚合浏览 + 全屏阅读抽屉 + 时间线视图 |
| ✅ | MySQL + RustFS 存储、本地自动回退 |
| ✅ | 历史文章翻页补齐、列表缩略图采集 |
| ✅ | 三栏总览视图、回家路页自动发现新镜像 |
| 📋 | 跨站去重视图 |
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

部分内容站的图片走加密分发链路，且该链路当前对全部客户端失效（源站原文图片同样无法渲染）。前端检测到失效图片会自动替换为占位符，不影响文字阅读；源站恢复后可通过修复脚本补齐。
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
