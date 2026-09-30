# ZCode 后台任务跑服务:随会话休眠死掉 + 时间戳双轨误判 + SQL 方言/静态缓存两坑

## 结论速览

- **方案**:macOS 开发期起 8787 服务只能当**临时进程**用(ZCode 后台任务),排查"页面挂了/轮询断"先 `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8787/api/sync/status` 探活(000 = 进程死,重启即愈,别查采集器);比对调度计时一律用 `sync.last_interval_run` 里的 **UTC 值**,别拿日志的北京时间肉眼比。SQL 遇 MySQL 保留字(`key`/`order`/`group`)一律反引号包裹,SQLite 测试通过不能证明 MySQL 能跑;FastAPI StaticFiles 默认无 Cache-Control,前端改版不生效先查浏览器缓存(修法:响应头加 `no-cache`)。
- **适用条件**:macOS 开发环境 + ZCode 会话内起 uvicorn;生产归宿是 Docker 常驻容器(进程活着机制就活着),服务生命周期坑在容器内不存在;SQL 方言与缓存坑跨环境通用。

## ✅ ZCode 后台任务跑的服务随会话休眠死掉(2026-09-30)

- **环境**:macOS(darwin 25.6.0 arm64)、ZCode 会话后台任务(run_in_background)起的 uvicorn(melon-hub 8787)、Python 3.9 venv
- **为何值得记**:用户报"51吃瓜一直卡住"+"状态查询失败: Failed to fetch",第一反应查采集器/前端就全错了;真因是进程死了,排查方向差了整条链路。会话休眠(Mac 合盖/隔夜)必然复现。
- **最终方案**:
  ```bash
  # 排查第一步:探活(000 = 进程已死)
  curl -s -o /dev/null -w "%{http_code}\n" --max-time 3 http://127.0.0.1:8787/api/sync/status
  # 确认死后看退出痕迹
  pgrep -fl uvicorn   # 无输出即进程没了
  # 服务日志尾部有 "Shutting down / Application shutdown complete" = 收到信号优雅退出
  # 重启即愈(调度器自带幂等,重启自动补上错过的周期,无需人工补采)
  cd <项目根> && .venv/bin/python -m uvicorn server.app:app --port 8787
  ```
- **为什么这样做**:ZCode 后台任务的生命周期绑定会话,Mac 休眠/会话隔夜恢复时宿主收掉任务句柄,uvicorn 收到 SIGTERM 优雅退出(日志实证);前端轮询 fetch 失败报 `Failed to fetch`,长耗时浏览器采集"看起来卡住"其实也是服务死了轮询断。**死的是进程,不是机制**——重启后间隔/每日模式按 settings 计时键自动补判,不用人工干预。
- **适用条件**:仅 macOS 开发环境;Docker 常驻容器(用户定的生产归宿)无此问题——调度/同步/收尾校验全部内建在应用进程内,容器活着机制就活着。
- **验证证据**(2026-09-30 实测):
  - 服务日志:`INFO: Shutting down → Waiting for application shutdown → Application shutdown complete → Finished server process [37646]`(08:44,无任何异常栈)
  - 探活:`curl ... /api/sync/status` → `HTTP 000`;`pgrep -fl uvicorn` 无输出
  - 重启后:调度线程正常启动,昨晚该进程生前的日志证明间隔/每日模式自动跑过(`[sync 09-30 01:23:25] 间隔 6h 采集完成`、`[sync 09-30 03:02:04] 每日 03:00 采集完成`)
  - 用户侧:重启后面板轮询恢复,同步正常触发
- **交叉验证**:单 agent 单次;佐证入口 `docs/handoffs/melon-hub.md` 2026-09-30 前后增量块与服务日志原文。
- **关键步骤**:探活(000)→ pgrep 确认无进程 → 查日志尾部确认优雅退出而非崩溃 → 重启 → 观察调度线程启动日志。
- **易错点**:
  - 别先怀疑采集器/前端——"采集卡住"和"轮询失败"同时出现时,先探活。
  - 用户明确要求:**macOS 不装 launchd/开机自启,不承担拉取数据的定时任务**(开发环境不污染);本地起服务就是临时进程,接受隔夜死掉,重开即可。
  - 重启前不用手工补数据:调度器幂等,`last_interval_run` 距今超 6h 会在下个 30s tick 自动补采;每日模式同理按当日键补判。

## ✅ 调度时间戳双轨:日志北京时间 vs settings UTC,肉眼比对必误判(2026-09-30)

- **环境**:同上;melon-hub `server/sync.py`(日志用 `_tz()` 北京时间,`sync.last_interval_run` 存 `_now_iso()` UTC)
- **为何值得记**:排查"间隔模式没触发"时,拿日志里 `[sync 09-30 08:58:02]`(北京)对比 `last_interval_run=2026-09-29T23:24:27Z`(UTC)肉眼算出差近 10 小时,判定"超 6h 应触发没触发=调度卡死",实际 UTC 只过了 1.6h,tick 不触发完全正确——**一次差点写不存在 bug 的误判**。
- **最终方案**:比对调度计时先换算同区:
  ```bash
  .venv/bin/python -c "
  from datetime import datetime, timedelta, timezone
  last = datetime.fromisoformat('2026-09-29T23:24:27+00:00')  # settings 值,Z→+00:00
  print(datetime.now(timezone.utc) - last >= timedelta(hours=6))"
  ```
- **为什么这样做**:项目约定日志面向人(本地时区)、存储面向机器(UTC ISO),两轨都正确,错的是跨轨肉眼比对。
- **适用条件**:任何"日志时间 vs DB 时间戳"跨轨比对的场景。
- **验证证据**:2026-09-30 08:58(北京)误判后,进程外复现:`now(UTC)=2026-09-30T01:01:14+00:00`,`差值 = 1:36:47`,`≥ 6h ? False`——tick 不触发正确,调度无 bug。
- **交叉验证**:单 agent 单次,复现命令即证据。
- **易错点**:`Z` 后缀就是 UTC,别忽略;日志无时区后缀但实际是 `MELON_TZ`。
## ✅ MySQL 保留字:SQLite 测试全绿、生产 MySQL 必炸(2026-09-29)

- **环境**:pymysql、MySQL 8、SQLite 3(测试替身)
- **为何值得记**:`get_setting` 的 SQL `WHERE key=%s` 在 SQLite 测试全过,生产 MySQL 直接 1064 语法错——**用户一句"hl365 咋能没数据"拦下的上线即炸 bug**;任何"用 SQLite 测试、MySQL 生产"的项目都会再撞。
- **报错原文**:
  ```
  pymysql.err.ProgrammingError: (1064, "You have an error in your SQL syntax; ... right syntax to use near 'key='sync.initialized'' at line 1")
  ```
- **报错稳定片段**:`ProgrammingError: (1064`、`near 'key=`
- **最终方案**:MySQL 里保留字列一律反引号——`SELECT value FROM settings WHERE `key`=%s`;**INSERT 语句同样要包**(`INSERT INTO settings (`key`, ...)`)。SQLite 对反引号也兼容,统一包裹两边都能跑。
- **为什么这样做**:MySQL 8 保留字表含 `key`/`order`/`group`/`rank` 等高频词,SQLite 宽松不报错——**测试替身与生产方言不一致时,"测试通过"对 SQL 层零证明力**。
- **验证证据**:修复后在生产 MySQL 真实读写验证 `写入后读回: ok / 覆写读回: overwrite`(2026-09-29)。
- **交叉验证**:单 agent;用户线上拦截促成。佐证:handoff 2026-09-29 增量块。
- **易错点**:双驱动 store(Database 类 ph 占位符分支)最容易只顾一边;新写 SQL 时对表名列名全包裹最省心。

## ✅ FastAPI StaticFiles 无 Cache-Control:前端改版后用户拿旧页面(2026-09-29)

- **环境**:FastAPI StaticFiles、Chrome
- **为何值得记**:前端大改版后用户报"图片没了",实际服务端数据全对——**浏览器对无 Cache-Control 的静态资源走启发式强缓存,旧 index.html/JS 一直占着**,旧 JS 配新数据产生各种灵异现象(误报方向全错,排查浪费一整轮)。
- **最终方案**:
  ```python
  class NoCacheFiles(StaticFiles):
      def file_response(self, *args, **kwargs):
          resp = super().file_response(*args, **kwargs)
          resp.headers['Cache-Control'] = 'no-cache'
          return resp
  app.mount('/', NoCacheFiles(directory=web_dir, html=True))
  ```
- **为什么这样做**:`no-cache` 不是不缓存——仍走 ETag 协商,未变 304 不重传,变了立刻拿新版;默认无头时浏览器启发式缓存(基于 Last-Modified)可能强缓存数天。
- **适用条件**:任何"FastAPI/后端直挂静态前端 + 前端会改版"的项目。
- **验证证据**:`curl -sI .../app.js` 出现 `cache-control: no-cache`;带 If-None-Match 请求返回 304;IAB 重新加载后顶栏从旧「刷新」按钮变新版「同步」按钮(2026-09-29)。
- **交叉验证**:单 agent;handoff 2026-09-29 缓存坑增量块为佐证。
- **易错点**:改版不生效时**先 curl 服务端确认实际在发什么**(服务端对的就查缓存),别急着怀疑代码;IAB 里旧页面行为怪异先换 headless Chrome 复现再定性(见 [[iab-does-not-render-img]] 同族环境怪癖)。
