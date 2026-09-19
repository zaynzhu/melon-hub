# melon-hub

个人多源吃瓜阅读仪表盘:一个界面同时浏览三个内容站(黑料不打烊 / 51吃瓜 / 每日大赛)的最新内容,点开条目进去广告的阅读视图。

## 结构

- `config/sites.yaml` — 站点采集配置(源头、镜像池、回家路页、解析器)
- `collector/` — 采集器(RSS/页面抓取、正文清洗、图片下载、入库)
- `server/` — FastAPI 轻后端
- `web/` — 聚合前端(Tab 切换 + 卡片流 + 阅读抽屉)
- `docs/` — 交接文档与上游侦察档案

## 运行

### 本地(开发)

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m collector.hl365          # 拉取 hl365 最新内容(增量幂等)
.venv/bin/python -m collector.wacg51 --limit 8   # 51吃瓜(需浏览器扩展 kimi-webbridge)
.venv/bin/python -m collector.mrds --limit 8     # 每日大赛(同上)
.venv/bin/python -m uvicorn server.app:app --port 8787
```

### Docker(部署)

```bash
docker build -t melon-hub .
docker run -d --name melon-hub -p 8787:8787 -v melon-data:/data melon-hub
```

容器入口会启动时采集一次 hl365 并每小时增量,API 与前端在 8787 端口。51吃瓜/每日大赛的采集依赖宿主机真实浏览器过 CF,在宿主机执行,并将 `MELON_DATA_DIR` 指向容器的数据卷目录即可共用同一份数据(库已开 WAL)。

## 存储

默认本地回退(SQLite `data/melon.db` + 对象目录 `data/objects/`);接入真实数据库与 RustFS 时通过环境变量提供,不写入本仓库(见 `.env.example`)。

## 边界

个人自用。一期不做跨站去重、不做登录/后台、不公开部署;采集遵守 ≥2 秒频控,遇登录墙/验证码即停。
