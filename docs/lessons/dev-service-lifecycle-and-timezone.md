# ZCode 后台任务跑服务:随会话休眠死掉 + 时间戳双轨误判

## 结论速览

- **方案**:macOS 开发期起 8787 服务只能当**临时进程**用(ZCode 后台任务),排查"页面挂了/轮询断"先 `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8787/api/sync/status` 探活(000 = 进程死,重启即愈,别查采集器);比对调度计时一律用 `sync.last_interval_run` 里的 **UTC 值**,别拿日志的北京时间肉眼比。
- **适用条件**:macOS 开发环境 + ZCode 会话内起 uvicorn;生产归宿是 Docker 常驻容器(进程活着机制就活着),本坑在容器内不存在。

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