# melon-hub 部署说明(目标机:极空间 Z4S,linux/amd64)

## 部署形态

- 单容器 FastAPI + 无头 Chromium,应用内定时调度,无外部 DB/对象存储依赖也能跑(回退容器卷)
- 生产建议接 MySQL + RustFS(可改 compose.yaml 的 environment 段接入)

## 镜像与资源

- 基础:`python:3.12-slim` + Chromium 无头浏览器(Playwright)
- 镜像体积:约 900MB
- 运行内存:应用常态 ~150MB;采 wacg51/mrds 时无头 Chromium 临时 +300-500MB,采集完自动关闭不常驻
- compose 限制:`shm_size: 1gb` + `mem_limit: 2g`,Z4S 16GB 够用;CF 被拦时报错不进死循环,等下轮

## 首次部署(离线包路径)

```bash
# 1) 解压部署包
tar -xzf melon-hub-598fab5-linux-amd64.tar.gz
cd melon-hub-598fab5-linux-amd64

# 2) 校验完整性
shasum -a 256 -c SHA256SUMS

# 3) 导入镜像(镜像已包含,无需联网)
gunzip -c images.tar.gz | docker load

# 4) 改配置(如需要)
# compose.yaml 是自包含单文件,所有配置在 environment 段按需改;
# 默认端口 50026 → 容器 8787;要改外部端口只动左侧数字
vi compose.yaml

# 4.5) 图片解密密钥(可选,建议配)
# 三站图片是 CDN 密文,需要站内 JS 才能解;不配则密文保留但面板警告
mkdir -p keys
vi keys/image.js    # 把站内 image.*.js 内容粘进去(见 docs/image-decrypt-playbook.md)
# 然后打开 compose.yaml 取消 environment 里 MELON_DECRYPT_JS 那行的注释

# 5) 建数据目录
mkdir -p data

# 6) 启动
docker compose -f compose.yaml up -d --pull never --no-build

# 7) 验证(注意:外部端口是 50026,容器内仍是 8787)
curl -sf http://127.0.0.1:50026/api/sources
curl -sf http://127.0.0.1:50026/api/sync/status
```

## 升级 / 回滚

- 升级:下载新包 → `docker compose down` → `docker load` 新镜像 → 修改 compose.yaml 的 `image:` tag → `up -d`
- 回滚:改回旧 tag 再 `up -d`;**数据卷不丢**(DB/SQLite 与对象文件全在 ./data)

## 首次启动行为

- 应用启动后**不会自动跑采集**——settings 表无 `sync.initialized` 时只写默认调度配置(间隔 6h/每日 03:00),定时到点才跑
- 三站首次内容需要在 Web UI「同步」面板手动触发一次(浏览器打开 `http://<NAS-IP>:50026/`),或等下个周期自动跑
- 想**立刻**采 hl365(RSS 源,无 CF):界面勾 hl365 点「开始同步」即可

## 浏览器站采集说明

- wacg51/mrds 容器内自跑无头 Chromium:`MELON_BROWSER_BACKEND=playwright`,已实测可过 CF 托管挑战(2026-09-30,见 `docs/lessons/headless-browser-pass-cf.md`)
- **长期稳定性未在容器生产环境实测**,建议你首次上线后先观察 2-3 天手动同步成功率再完全信定时
- **CF 升级(Turnstile/无头检测)后会被拦**——此时该站同步面板会明确报错"CF 挑战未放行",不会静默假装成功;按项目红线**即停**,等降级或源站链路再恢复

## 数据备份

- 正文 JSON 已有本地 git 备份层(`data/backup_content/`),任何覆盖性脚本前必须先跑 `scripts/backup_content.py`
- 生产 RustFS/MySQL 由你已有基建承担;**云端打包流程不携带真实数据**

## 常见坑

- `database is locked`:确认 compose 里 `./data` 映射的是本地磁盘,不是 NFS/SMB 挂载(SQLite 依赖 fcntl 锁,网络文件系统不可靠)
- Chromium `session closed`:确认 compose 有 `shm_size: 1gb` 或 `ipc: host`
- 页面挂了先 `curl /api/sync/status`,进程死重启即愈,调度幂等自动补错过的周期
