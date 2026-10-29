# Playwright sync API 在长驻线程的 loop 泄漏:一次 launch 失败污染整条调度

## 结论速览

- **最终方案**:`sync_playwright().start()` 拿到引用的**第一时间**存入 close 逻辑可达的位置(本例 `_playwright_state['pw']`),保证 launch/context/page 任一步失败时都能 `pw.stop()`——否则 loop+greenlet 泄漏在当前 OS 线程,同线程之后每次 `start()` 必报 "It looks like you are using Playwright Sync API inside the asyncio loop"。复现与回归:`scripts/verify_pw_loop_leak.py`。
- **适用条件**:Python playwright sync API + **长驻后台线程**反复起停 browser 的架构(FastAPI 调度线程等);一次性脚本跑完即退,无此坑。

## ✅ NAS 定时采集三连败:根因是 loop 泄漏,不是版本变化(2026-10-29)

- **环境**:NAS 极空间 Z4S 容器(python:3.12-slim,playwright 1.64.1,镜像 melon-hub:ce5d0f3),FastAPI + threading 调度线程;排查机 macOS,playwright 1.63.0/1.64.0/1.64.1 三版本 wheel 对比
- **为何值得记**:排查跨三层(构建日志考古 / DB 时间线 / wheel 源码 diff / 最小复现),8 轮收敛;症状极易误判为"playwright 升级引入"或"环境坏了",本次两条都排过
- **症状三特征**(识别此坑的指纹,5 秒判定):
  1. 走浏览器的站全报错,不走浏览器的正常(本例 hl365 ok,wacg51/mrds 败)
  2. **手动触发正常,定时/后台触发必败**——手动每次新线程,定时在长驻线程(被污染的只有那一个线程)
  3. 从某天起**每天必现**同一句错(不是偶发);面板上 `discover: null` 也吻合——镜像发现流程在同线程再起 start 同样被拦,被内层 except 吞掉
- **机制**:`sync_playwright().start()`(1.64.1 `sync_api/_context_manager.py`)在无 running loop 的线程里 `new_event_loop()` 并用 greenlet 驱动;若拿到 pw 后、引用存入 state 前,`chromium.launch()` 等步骤失败,close 逻辑拿不到 pw 去 `stop()` → loop+greenlet **泄漏在当前 OS 线程**(`asyncio.get_running_loop()` 是 thread-local,泄漏的 loop 挂着这个线程的标志位);同线程下次 `start()` 时 `get_running_loop()` 命中 + `is_running()` → 抛错。调度线程永不退出 → 永久污染。
- **验证证据**:
  - 复现脚本(走真实项目模块,非模拟):`scripts/verify_pw_loop_leak.py` RED(修复前同线程二轮 start 精确复现报错,exit 1)→ GREEN(修复后报 launch 注入错而非 loop 错,exit 0);注入方式 `PLAYWRIGHT_BROWSERS_PATH` 指向不存在目录,不依赖浏览器安装、零写数据
  - 源码 diff:playwright 1.64.0 与 1.64.1 wheel 解包,`sync_api/_context_manager.py`、`_impl/_connection.py`、`_impl/_greenlets.py` **逐字节一致**,排除版本行为变化
  - DB 时间线:浏览器站末次入库北京 10-27 03:03,10-27 起零入库;镜像 10-23 部署且 10-24/25/26 正常——排除"镜像一上线就坏";触发点是 10-27 03:13 mrds 轮 `chromium.launch()` 一次性失败(原始原因未查证,推测 NAS 资源瞬时压力,部署后建议看容器日志该时刻附近)
  - 生产验证(完整终态):部署修复镜像 melon-hub:1c70694 后 NAS 手动同步两浏览器站全 ok——wacg51 新 9+补正文 19 零失败、mrds 新 21+补正文 26(失败 1),10-27 起三天积压正文一轮基本清零,Playwright loop 错未再现;遗留 gaps(wacg51 缩略图 24、mrds pending 1)属采集协议下轮自动消化项,不属本坑
- **交叉验证**:单 agent 单会话多轮(构建日志考古→DB 时间线→wheel diff→复现实验→RED→GREEN→调度器回归→生产部署观察);证据入口:`scripts/verify_pw_loop_leak.py`、`docs/handoffs/melon-hub.md` 2026-10-29 增量块
- **关键步骤**(下次撞上按此 5 分钟定位):
  1. 看到 "Sync API inside the asyncio loop" 在**定时/后台**任务反复出现而手动正常 → 直接查长驻线程里 playwright 引用的生命周期
  2. grep 项目里 `sync_playwright().start()` 返回值的存放位置,沿失败路径检查有没有 stop
  3. 跑 `scripts/verify_pw_loop_leak.py` 复现/回归(需含 playwright 的解释器;项目 .venv 默认无,借任意装了 playwright 的 venv)
- **易错点**:
  - 把锅甩给"playwright 升级"很顺手——报错日期紧跟镜像更新日期时直觉更强;**先 diff 两个版本源码再下结论**(wheel 解包 `unzip -oq *.whl 'playwright/sync_api/*'` 几分钟的事)
  - close 逻辑用 `state.get('pw')` 宽松取值,失败路径上 state 里根本没存 → 静默跳过清理 → 泄漏
  - `get_running_loop()` 是 **thread-local**:泄漏只影响被污染线程,手动正常、定时必败不是玄学
  - 重启容器能临时止血(泄漏标志随进程消失),但下次 launch 失败即复发——修复必须在代码层
  - verify 脚本在缺 `requests` 的解释器下用 `sys.modules` stub 通过模块级 import(playwright 路线不依赖 requests)

## ⛔ 误判路线:按"版本更新引入行为变化"排查(2026-10-29)

- **报错原文**:It looks like you are using Playwright Sync API inside the asyncio loop.\nPlease use the Async API instead.
- **稳定片段**:`Sync API inside the asyncio loop`(供 grep 命中)
- **错误原因**:项目 requirements 未锁版本(`playwright>=1.45`),两次云端构建分别装了 1.64.0/1.64.1;报错日期紧跟镜像更新日期,直觉把排查引向"新版本加严检测"
- **为何不可再采用**:1.64.0/1.64.1 关键源码 diff 逐字节一致;该报错的检测(`__enter__` 里 `get_running_loop()`+`is_running()`)语义由 Python asyncio 线程模型决定,与 playwright patch 版本无关
- **替代方案**:按症状三特征直接定位线程生命周期,见本文件 ✅ 条目
- **判定时效**:基于 playwright 1.63/1.64(2026-10);若后续版本改动 `_context_manager.py` 检测逻辑需重验,但 thread-local loop 的机制性结论长期有效

> 修订 2026-10-29:生产验证证据由"手动同步进行中(未再现 loop 错)"补为完整终态——两浏览器站 ok、三天积压正文(45 篇)一轮清零;终态 gaps 遗留项属采集协议正常消化,与 loop 泄漏无关。