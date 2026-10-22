# Docker 化交付完整闭环:云端 Buildx 多架构 + 无头 Chromium 容器 + NAS 部署排坑

## 结论速览

- 最终方案：Dockerfile 装 `playwright` + `chromium` → GitHub Actions `buildx --platform linux/amd64` → `docker save` 打 tar 包 → NAS `docker load` + `docker compose up`。
- 适用条件：镜像 ≤2GB、amd64/x86_64、NAS 上能跑 `docker compose`(极空间 Z4S 可以）、构建机与目标机同架构或 QEMU 支持。
- 运行期保活（2026-10-22 新增）：NAS docker 容器间链路会掐 MySQL 长连接——DB 访问必须断线自愈（`store.py` `_exec` 前置 `ping(reconnect=True)`）；「重启容器才恢复」属于未修复状态。详见下方 ✅ 条目。

## ✅ 云端 Buildx QEMU 跨架构构建（已验证）

- Date: 2026-10-01 至 2026-10-08
- 环境：GitHub Actions `ubuntu-latest`、`docker/setup-qemu-action@v3`、`docker/setup-buildx-action@v3`
- 验证证据：[run 36852793131](https://github.com/zaynzhu/melon-hub/actions/runs/36852793131)、[run 36853271957](https://github.com/zaynzhu/melon-hub/actions/runs/36853271957)、[run 37656382930](https://github.com/zaynzhu/melon-hub/actions/runs/37656382930)

### 最终方案

```yaml
- uses: docker/setup-qemu-action@v3
- uses: docker/setup-buildx-action@v3

- run: |
    docker buildx build \
      --platform linux/amd64 \
      --load \
      -t melon-hub:8138b13 .
```

- **为什么这样做**: `--load` 把多架构构建结果直接载入本机 Docker daemon，不需要额外 push/pull 中转，验证快、tar 包制作简单。
- **适用条件**: `docker buildx` 版本 ≥ 0.10、构建上下文不含大文件（>2GB 需拆步骤）、目标机架构与 `--platform` 一致。
- **易错点**: `--load` 与 `--push` 不能同时用；多架构（`linux/amd64,linux/arm64`）单次 `--load` 会失败，必须逐个平台构建、分别加载、分别打 tar 包。

## ✅ 离线 tar 包 + NAS `docker load`（已验证）

### 最终方案

```bash
# 云端（构建机）
gzip -c melon-hub.tar > melon-hub-8138b13-linux-amd64.tar.gz

# NAS（目标机）
gunzip -c melon-hub-8138b13-linux-amd64.tar.gz | docker load
```

- **验证证据**：2026-10-08 解压后 `docker load` 成功，镜像 ID `sha256:9e6d0c4f3d...`（详见会话记录）。
- **为什么这样做**：离线 tar 包不依赖 Docker Hub，适合无公网或内网环境部署。
- **关键约束**:
  - 必须是单架构（`--load` 后 `docker save` 只含本机当前平台）;
  - 多语言环境（如 macOS 开发机构建 → NAS amd64 部署）必须 `--platform linux/amd64`;
  - tar 包体积大（539MB），传输前先 `gzip -9` 压缩。

## ✅ Playwright 无头 Chromium 容器化（已验证）

### 最终方案

```dockerfile
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir playwright==1.55.0
RUN playwright install-deps chromium
RUN playwright install chromium
WORKDIR /app
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8787/api/sources || exit 1
EXPOSE 8787
```

- **验证证据**:2026-10-08 NAS 上 `docker logs melon-hub` 看到 `INFO:playwright:Chromium launched successfully`，采集器跑通 51cg/mrds 无 CF 拦截。
- **为什么这样做**: `playwright install-deps` 一次性装齐 Chromium 所需系统库（X11、NSS、GStreamer 等），比手动列依赖更不易遗漏。
- **关键约束**:
  - **必须 `pip install playwright` 在基础镜像层完成**，NAS 上 build 不可行（太慢）;
  - 镜像体积大（539MB），但 `slim` 基础镜像已精简；
  - `healthcheck` 用简单 HTTP GET 探测，不用启动 Chromium。

## ✅ NAS 网络池耗尽与 IPv6 冲突排查（已验证）

### 问题现象

```text
Error: failed to create network melon-hub_default
failed to create network melon-hub_default: Error response from daemon:
could not find an available, non-overlapping IPv4 address pool
```

### 根因

NAS 极空间 Z4S 运行多容器后，Docker 默认 IPv4 地址池（172.17.0.0/12 和 192.168.0.0/16）可能耗尽；或 IPv6 子网冲突。

### 修复方案

```bash
# 查看现有网络,删除无用网络释放地址池
docker network ls
docker network prune

# 查看所有网络配置,找出冲突的 IPv6 子网
docker network inspect <network_name>
```

- **验证证据**:2026-10-08 执行上述命令后 `docker compose up` 成功创建 `melon-net`。
- **为什么这样做**: Docker 桥接网络默认自动分配子网，多容器并发或残留旧网络时易冲突。
- **关键约束**: `docker network prune` 会删除所有未使用的网络，确认没有"未使用但需要保留"的网络再执行。
- **易错点**: 不要全局执行 `docker system prune -a`，会误删正在使用的镜像和卷。

## ✅ browser_fetch 双后端设计（容器/宿主机透明切换）

### 设计思路

```python
# browser_fetch.py
def get_fetch_impl():
    backend = os.getenv("MELON_BROWSER_BACKEND", "playwright")
    if backend == "webbridge":
        return WebBridgeFetch()  # 宿主机 kimi-webbridge 扩展
    else:
        return PlaywrightFetch() # 容器内无头 Chromium
```

- **验证证据**:2026-10-08 NAS 上 `MELON_BROWSER_BACKEND=playwright` 采集成功；本地开发机 `MELON_BROWSER_BACKEND=webbridge` 正常工作。
- **为什么这样做**: 开发机 macOS 已有成熟 `webbridge` 后端（借 Chrome 扩展过 CF)，容器内无此扩展；按环境变量切换，代码一套、部署灵活。
- **关键约束**:
  - playwight 后端默认（容器场景）;
  - 宿主机上必须设置环境变量 `MELON_BROWSER_BACKEND=webbridge`;
  - 切换后端后 `sync.py` 的 daemon 依赖判断随之切换，无额外配置。

## ✅ 部署 Compose 配置内置（已验证）

### 最终方案

```yaml
services:
  app:
    image: melon-hub:8138b13
    container_name: melon-hub
    restart: unless-stopped
    ports:
      - "50026:8787"
    volumes:
      - ./data:/data
      - ./keys:/run/melon:ro
    environment:
      MELON_DATA_DIR: /data
      TZ: Asia/Shanghai
      MELON_TZ: Asia/Shanghai
      MELON_BROWSER_BACKEND: playwright
    # 无头 Chromium 需要大 /dev/shm;采集时临时 +300-500MB,跑完自动关
    shm_size: '1gb'
    mem_limit: '2g'
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://127.0.0.1:8787/api/sources"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
```

- **验证证据**：多轮构建确认；端口映射（50026:8787）可用。
- **为什么这样做**：所有配置直接写在 `environment` 段，避免 `env_file` 依赖，单一文件便于管理。
- **易错点**:
  - `shm_size: 1gb`：无头 Chromium 需要大共享内存，否则启动失败；
  - `mem_limit: 2g`：容器内存限制，防止 Chromium 采集时吃光 NAS 资源；
  - `healthcheck` 用 `curl -sf`（非 0 即失败）探测，`start_period: 10s` 避免启动时误报。

## ⛔ 已确认的坑（不可再犯）

### 坑 1：云端 Buildx QEMU 构建超时

- **报错片段**: `Time limit exceeded, process ended`
- **原因**: `pip install` 和 `playwright install` 在 QEMU 下速度极慢，超过 GitHub Actions 10 分钟限制。
- **解决方案**: 构建阶段拆成多步（先 pip install → 单独缓存层 → 再 playwright install)，利用 Docker 层缓存复用。
- **判定时效**: 2026-10-01 至 2026-10-08，GitHub Actions 标准 runner 限制。

### 坑 2：NAS `docker load` 权限拒绝

- **报错片段**: `docker: Permission denied`
- **原因**: 极空间 Z4S 终端 Docker 命令需 `sudo`。
- **解决方案**: `sudo gunzip -c xxx.tar.gz | docker load`
- **判定时效**: 2026-10-08 后持续适用。

## ✅ NAS 容器间链路掐断 MySQL 长连接（2026-10-22）

- **为何值得记**：故障表象极具迷惑性——同一后端里不碰 DB 的接口全 200、碰 DB 的全 500；MySQL 本机直连正常、服务参数全是健康默认值。三轮排除才锁定「容器间链路掐长连接」，修复本身一行，没这份记录下次还得从 500 反推一遍。且 NAS 上其他容器（whatsnew）连同一 MySQL，此条同样适用。
- **最终方案**（`collector/store.py` `_exec`）：
  ```python
  def _exec(self, sql, args=()):
      """统一执行:pymysql 走 cursor,sqlite3 直接 execute,均返回可 fetch 的游标。"""
      if self._mysql:
          # NAS docker 容器间链路会掐断长连接(在线实测 24h 内两次),断了自动重连
          self.conn.ping(reconnect=True)
          cur = self.conn.cursor()
          cur.execute(sql, args)
          return cur
      return self.conn.execute(sql, args)
  ```
  配套验证脚本：`scripts/verify_db_reconnect.py`（`.venv/bin/python -I scripts/verify_db_reconnect.py`，真实 MySQL：KILL 自身连接 → 断言自动重连后查询成功）。
- **为什么这样做**：pymysql 长连接被服务端/链路断开后，连接对象不自愈，之后每个查询抛异常直到进程重启。每次执行前置 `ping(reconnect=True)` 在「发现死」的同一回合用原参数重建；autocommit 场景无事务中段断连风险，常态开销仅一个轻量 ping 包（tick 30s + 用户请求量级，可忽略）。所有调用方持 `_lock`，ping 天然线程安全。
- **适用条件**：极空间 Z4S docker（2026-10-22 实测）；任何容器间通信可能掐长连接的环境。若未来引入显式事务/多语句写，需重新评估重连时机（事务中段断连 ping 救不了——ping 只在执行前恢复连接）。
- **验证证据**（四段，全部真实执行）：
  1. 生产症状对照：`/api/sources`（纯 yaml，不碰 DB）200，`/api/articles`、`/api/sync/status`、`/api/settings` 500；本机直连 MySQL 正常（articles 899 篇可查，排除服务挂）。
  2. 本地 KILL 实测：验证脚本用旁路连接 `KILL <id>` 掉 Database 的连接，复现 `pymysql.err.OperationalError: (2013, 'Lost connection to MySQL server during query')`；加修复后 KILL 自动重连、查询成功。
  3. 生产 KILL 实测：`SHOW PROCESSLIST` 锁定容器连接（host `172.27.0.1`(docker 网关) + db `melon_hub`，2 条）全部 KILL → 3 秒后 `/api/sync/status` 恢复 200、采集未中断（`running=True`）；其后总库数 905→925（补采 +20 篇入库，写路径实证）。
  4. 跨项目佐证（2026-10-22，来源：共享该 MySQL 的 whatsnew 项目会话 whatsnew-81 提供）：其日志存在零星 `Server has closed the connection`（Prisma 报 P1017）——同一链路现象的独立客户端观察，佐证掐线是 NAS docker bridge 的**常态低频随机**行为，不只在容器重启等事件时发生。
- **交叉验证**：单 agent 单会话、多轮收敛（症状对照 → 本地 KILL 复现 → 修复 → 本地 KILL 通过 → 生产 KILL 通过）；无书面审查产物，口头收敛。
- **诊断时序**（同症状复现时照抄）：① 同进程下分「碰 DB / 不碰 DB」两组接口对照 200/500 → ② 本机（非容器）直连 MySQL 查数据在不在 → ③ `SHOW VARIABLES LIKE 'wait_timeout'` + `SHOW PROCESSLIST` 看服务侧参数与连接方 → ④ KILL 复现/验证修复。
- **易错点**：
  - **「MySQL 活着」≠「容器能连」**——本机走局域网直连，容器走 docker bridge NAT（hairpin），是两条不同路径，必须分别验证。
  - **别猜空闲超时**——应用的调度 tick 每 30s 摸一次 settings，保活充足；先拿数据（接口对照、直连、SHOW VARIABLES）说话，再下结论。
  - **docker healthcheck 是监控盲区**——探的是 `/api/sources`（不碰 DB），DB 断连时容器仍显示 healthy，极空间界面不会变红。
  - **KILL 验证用 `host=172.27.0.1` + `db=melon_hub` 锁定容器连接**，避免误杀 Mac（局域网 IP 段）/DbGate 的连接；KILL 后**第一个请求即自愈**（ping 在查询之前），不需要等 30s tick。
  - KILL 时若 `running=True`（采集进行中）实测照样能做——采集线程下一步写操作会 ping 重连，反而同时验证了写路径。
  - 浏览器站补采一轮可达 40+ 分钟（每篇 40-50s），排障时别干等它结束，直接 KILL 实测反而更快更全。
  - **客户端重连语义决定故障烈度**——同一次链路掐线：单条长连接（pymysql 裸用）表现为挂死 500 需重启（本条主场景)；连接池按查询重连（如 Prisma）表现为偶发单条失败后自愈。新建客户端要么选带按查询重连语义的池化客户端，要么裸长连接必须前置 `ping(reconnect=True)`——裸长连接无重连 = 故障放大器。

> 修订 2026-10-22：吸收 whatsnew-81 会话提供的跨项目佐证（共享 MySQL 的 whatsnew/Prisma 日志零星 `Server has closed the connection`/P1017 与本条同源），掐线定性由「事件触发偶发」修正为「常态低频随机」，增补「客户端重连语义决定故障烈度」易错点；验证证据扩为四段。

## ⛔ 「调大 MySQL 参数/内存就能解决断连」（2026-10-22）

- **报错原文**：无报错（此为方案层面的绕路否决）。
- **错误原因**：实测 NAS MySQL 参数全为标准健康值（`wait_timeout=28800`（8h）、`max_connections=200`、MySQL 8.4.9），melon-hub 仅占用 1 条连接；断连根源在容器间链路，与服务参数无关。
- **为何不可再采用**：调参修不掉链路断连；且把内存限制调到小于实际用量反而会造成 MySQL 被 OOM 杀、真·断掉全部连接。
- **替代方案**：本文件上方 ✅「断线自动重连」条目。
- **判定时效**：2026-10-22 / MySQL 8.4.9；将来若换 MySQL 实例或版本，先重查参数再下此结论。

## 交叉验证

| 主题 | 验证方式 | 审查收敛度 |
|------|----------|------------|
| 云端构建流程 | 3 次 GitHub Actions 构建成功 | 口头收敛（本会话自审） |
| Chromium 容器化 | NAS 实跑采集成功 | 口头收敛 |
| NAS 网络池修复 | `docker network prune` 后 `up` 成功 | 单 agent 单次 |
| browser_fetch 双后端 | 容器/宿主机双环境验证 | 口头收敛 |

## 适用条件汇总

| 条件 | 要求 |
|------|------|
| 目标架构 | linux/amd64 (x86_64) NAS |
| 构建平台 | GitHub Actions ubuntu-latest |
| 镜像基础 | python:3.13-slim |
| 浏览器后端 | 容器必须用 playwright,宿主机可选 webbridge |
| NAS 限制 | 内存 ≥ 2GB、能跑 docker compose、可 `docker network prune` |

**未来验证需求**:
- ⬜ 镜像体积优化（当前 539MB，可试验 python:alpine 基础镜像）
- ⬜ 多架构构建（如需 linux/arm64）需验证 `--load` 兼容性
