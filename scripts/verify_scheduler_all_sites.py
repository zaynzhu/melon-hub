# 调度逻辑隔离验证:不真采外部站点,monkeypatch _collect_source 后验证
# 1) playwright 后端 → 定时顺序采三站  2) webbridge 后端 → 仅 hl365
# 3) 成功后计时键写入  4) 锁被占时跳过返回 False  5) 到期判定 _tick 端到端
import os
import sys
import tempfile

os.environ['MELON_DB_URL'] = f"sqlite:///{tempfile.mkdtemp()}/sched_test.db"
os.environ['MELON_TZ'] = 'Asia/Shanghai'
sys.path.insert(0, '.')

import server.sync as sync
from collector.store import Database

calls = []


def fake_collect(source, pages=1):
    calls.append((source, pages))
    return {'status': 'ok', 'stats': {'done': 1}, 'error': '', 'gaps': {}}


sync._collect_source = fake_collect

failures = []


def check(name, cond, detail=''):
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail else ''))
    if not cond:
        failures.append(name)


# ---- 场景 1:playwright 后端 → 三站顺序 ----
print("场景 1: MELON_BROWSER_BACKEND=playwright")
os.environ['MELON_BROWSER_BACKEND'] = 'playwright'
check('scheduled_sources 三站', sync.scheduled_sources() == ['hl365', 'wacg51', 'mrds'])
calls.clear()
ok = sync._run_scheduled(pages=3, label='间隔 6h+每日 03:00')
check('_run_scheduled 返回 True', ok is True)
check('顺序采集三站', calls == [('hl365', 3), ('wacg51', 1), ('mrds', 1)], str(calls))
check('每日多页只给 hl365', calls[0][1] == 3 and calls[1][1] == 1 and calls[2][1] == 1)
with sync._state_lock:
    check('状态面板三站齐', sync._state['sources'] == ['hl365', 'wacg51', 'mrds'])
    check('trigger=schedule', sync._state['trigger'] == 'schedule')

# ---- 场景 2:webbridge 后端 → 仅 hl365 ----
print("场景 2: MELON_BROWSER_BACKEND=webbridge")
os.environ['MELON_BROWSER_BACKEND'] = 'webbridge'
# _BACKEND 在 browser_fetch 导入时捕获,切后端要 reload 模拟进程重启
import importlib
import collector.browser_fetch
importlib.reload(collector.browser_fetch)
check('scheduled_sources 仅 hl365', sync.scheduled_sources() == ['hl365'])
calls.clear()
ok = sync._run_scheduled(pages=1, label='间隔 6h')
check('仅采 hl365', calls == [('hl365', 1)], str(calls))

# ---- 场景 3:锁被占 → 跳过 ----
print("场景 3: 锁冲突")
sync._run_lock.acquire()
calls.clear()
ok = sync._run_scheduled(pages=1, label='间隔 6h')
check('锁忙返回 False', ok is False)
check('锁忙不触发采集', calls == [])
sync._run_lock.release()

# ---- 场景 4:_tick 端到端(真实临时 SQLite,计时键真读写) ----
print("场景 4: _tick 端到端")
os.environ['MELON_BROWSER_BACKEND'] = 'playwright'
importlib.reload(collector.browser_fetch)
db = Database()
# 全新库:无计时键 → 间隔+每日(本地已过 03:00)双到期,合并一次采集
calls.clear()
sync._tick(db, sync._tz())
check('双到期触发采集', len(calls) == 3, str(calls))
li = db.get_setting(sync.KEY_LAST_INTERVAL)
ld = db.get_setting(sync.KEY_LAST_DAILY)
check('间隔计时键已写', bool(li), str(li))
check('每日计时键已写为今天', bool(ld), str(ld))

# 再 tick 一次:间隔未到 6h、每日今天已采 → 不应再采
calls.clear()
sync._tick(db, sync._tz())
check('未到期不重复采集', calls == [], str(calls))

# ---- 场景 5:采集失败也写计时键(尝试语义) ----
print("场景 5: 尝试语义")
db.set_setting(sync.KEY_LAST_INTERVAL, '')
calls.clear()


def fail_collect(source, pages=1):
    calls.append(source)
    return {'status': 'error', 'stats': None, 'error': '模拟失败', 'gaps': {}}


sync._collect_source = fail_collect
sync._tick(db, sync._tz())
check('失败后仍写计时键', bool(db.get_setting(sync.KEY_LAST_INTERVAL)))
check('单站失败不中断批次', len(calls) == 3, str(calls))
sync._collect_source = fake_collect
db.close()

print()
if failures:
    print(f"结果: {len(failures)} 项失败 — {failures}")
    sys.exit(1)
print("结果: 全部通过")