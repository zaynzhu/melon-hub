"""手动同步与进程内定时调度:与 FastAPI 同进程,配置持久化在 settings 表。

语义(改这里要同步改 docs/handoffs/melon-hub.md「同步与调度」):
- 间隔模式:interval_hours>0 且距上次 ≥N 小时 → 采 hl365 1 页
- 每日模式:每天 HH:MM(时区 MELON_TZ,默认 Asia/Shanghai)→ 采 hl365 3 页
- 计时键在发起采集时写入(尝试语义):采集失败也计数,等下个周期再试,不重试轰炸
- 手动同步与定时采集共用一把锁:手动冲突返回 409,定时冲突跳过本 tick
- 定时只调度 hl365;wacg51/mrds 依赖宿主机 kimi-webbridge,仅手动可点
"""
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

TICK_SECONDS = 30
DEFAULT_INTERVAL_HOURS = 6
DEFAULT_DAILY_AT = '03:00'
KEY_INTERVAL = 'sync.interval_hours'
KEY_DAILY = 'sync.daily_at'
KEY_LAST_INTERVAL = 'sync.last_interval_run'
KEY_LAST_DAILY = 'sync.last_daily_date'
KEY_INITIALIZED = 'sync.initialized'

# 运行锁:手动/定时互斥;非阻塞获取失败即"采集正在进行"
_run_lock = threading.Lock()
_state_lock = threading.Lock()
_state = {
    'running': False, 'trigger': '', 'current': '', 'sources': [],
    'results': {}, 'started_at': '', 'finished_at': '',
}


def _tz():
    name = os.environ.get('MELON_TZ') or 'Asia/Shanghai'
    try:
        return ZoneInfo(name)
    except Exception:
        return ZoneInfo('Asia/Shanghai')


def _log(msg):
    print(f'[sync {datetime.now(_tz()).strftime("%m-%d %H:%M:%S")}] {msg}', flush=True)


def _now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _pending_result():
    return {'status': 'pending', 'stats': None, 'error': ''}


def _set_state(**kw):
    with _state_lock:
        _state.update(kw)


def _set_result(source, **kw):
    with _state_lock:
        _state['results'].setdefault(source, _pending_result()).update(kw)


def _result_summary(result):
    if result['status'] == 'ok':
        stats = result.get('stats') or {}
        detail = ','.join(f'{k} {v}' for k, v in stats.items())
        return '成功' + (f'({detail})' if detail else '')
    return f"失败:{result.get('error') or '未知错误'}"


def read_schedule_config(db):
    """读取定时配置;键缺失时用默认值(间隔 6h、每日 03:00)。"""
    raw_interval = db.get_setting(KEY_INTERVAL)
    raw_daily = db.get_setting(KEY_DAILY)
    try:
        interval_hours = int(raw_interval) if raw_interval is not None else DEFAULT_INTERVAL_HOURS
    except ValueError:
        interval_hours = DEFAULT_INTERVAL_HOURS
    daily_at = raw_daily if raw_daily is not None else DEFAULT_DAILY_AT
    return {'interval_hours': interval_hours, 'daily_at': daily_at}


def valid_sources():
    from collector.config import load_config
    return list(load_config()['sites'].keys())


# ---- 手动同步 ----

def start_manual_sync(sources):
    """触发手动同步:后台线程顺序跑所选站。返回 (ok, message)。"""
    if not _run_lock.acquire(blocking=False):
        with _state_lock:
            label = '定时' if _state['trigger'] == 'schedule' else '手动'
        return False, f'{label}采集正在进行中,请稍候'
    try:
        with _state_lock:
            _state.update(
                running=True, trigger='manual', current='', sources=list(sources),
                results={s: _pending_result() for s in sources},
                started_at=_now_iso(), finished_at='')
        threading.Thread(target=_manual_run, args=(tuple(sources),), daemon=True).start()
        return True, ''
    except Exception:
        _run_lock.release()
        raise


def _manual_run(sources):
    try:
        for src in sources:
            _set_state(current=src)
            _set_result(src, status='running')
            result = _collect_source(src)
            _set_result(src, **result)
            _log(f'手动同步 {src}:{_result_summary(result)}')
    finally:
        _set_state(running=False, current='', finished_at=_now_iso())
        _run_lock.release()


def _collect_source(source, pages=1):
    """采集单站并返回结果 dict;任何异常都不外抛。"""
    try:
        if source == 'hl365':
            from collector import hl365
            stats = hl365.collect(pages=pages)
            stats['img_decrypted'] = _decrypt_new_cipher_images()
            return {'status': 'ok', 'stats': stats, 'error': ''}
        if source in ('wacg51', 'mrds'):
            return _collect_browser_site(source)
        return {'status': 'error', 'stats': None, 'error': f'站点 {source} 无采集器'}
    except Exception as exc:  # noqa: BLE001 单站失败不中断整批
        return {'status': 'error', 'stats': None, 'error': str(exc)}


def _decrypt_new_cipher_images():
    """采集收尾校验:新落的密文图自动解密(三站 CDN 加密分发,见 playbook)。

    全库幂等盘点(明文秒过),密文仅在配置了 MELON_DECRYPT_JS 时解密,
    未配置则计入 failed 并打警告——宁可显式暴露也不静默留密文。
    """
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'scripts'))
    from article_img_decrypt import auto_decrypt_new
    try:
        stats = auto_decrypt_new()
        if stats['cipher'] and not stats['ok'] and not os.environ.get('MELON_DECRYPT_JS'):
            _log(f"[warn] {stats['cipher']} 张密文图未解密:"
                 '配置 MELON_DECRYPT_JS 指向站内 image.*.js 后自动生效')
        return stats
    except SystemExit as exc:
        _log(f'[warn] 密文图自动解密中止:{exc}')
        return {'checked': 0, 'cipher': 0, 'ok': 0, 'failed': []}


def _collect_browser_site(source):
    from collector import browser_fetch, typecho_collector
    if not _browser_daemon_reachable():
        return {'status': 'error', 'stats': None,
                'error': '需本机浏览器环境(kimi-webbridge daemon 未运行),请在宿主机运行采集器'}
    try:
        browser_fetch.ensure_ready()
        stats = dict(typecho_collector.collect_list(source))
        stats.update(typecho_collector.collect_articles(source, limit=12))
        stats['img_decrypted'] = _decrypt_new_cipher_images()
        return {'status': 'ok', 'stats': stats, 'error': ''}
    finally:
        try:
            browser_fetch.close_session()
        except Exception:
            pass


def _browser_daemon_reachable():
    """TCP 探测 webbridge daemon,不通直接降级,避免触发 daemon 自启重试。"""
    from collector.browser_fetch import DAEMON
    parsed = urlparse(DAEMON)
    try:
        with socket.create_connection((parsed.hostname, parsed.port or 80), timeout=1):
            return True
    except OSError:
        return False


# ---- 定时调度 ----

def start_scheduler(db):
    return threading.Thread(
        target=_scheduler_loop, args=(db,), daemon=True, name='melon-sync-scheduler').start()


def _scheduler_loop(db):
    tz = _tz()
    _log(f'调度线程启动(tick {TICK_SECONDS}s,时区 {tz.key})')
    _initialize(db, tz)
    while True:
        try:
            _tick(db, tz)
        except Exception as exc:  # noqa: BLE001 tick 异常不终止调度
            _log(f'[warn] tick 异常:{exc}')
        time.sleep(TICK_SECONDS)


def _initialize(db, tz):
    """首次启动(无 initialized 键):落默认配置并采集一次,计时三键一次写入防双跑。"""
    if db.get_setting(KEY_INITIALIZED) is not None:
        return
    cfg = read_schedule_config(db)
    db.set_setting(KEY_INTERVAL, str(cfg['interval_hours']))
    db.set_setting(KEY_DAILY, cfg['daily_at'])
    _log(f'首次启动:默认配置 间隔 {cfg["interval_hours"]}h / 每日 {cfg["daily_at"] or "关"}')
    if cfg['interval_hours'] > 0 or cfg['daily_at']:
        if _run_scheduled(pages=1, label='首次启动'):
            db.set_setting(KEY_LAST_INTERVAL, _now_iso())
            db.set_setting(KEY_LAST_DAILY, datetime.now(tz).date().isoformat())
    db.set_setting(KEY_INITIALIZED, '1')


def _tick(db, tz):
    cfg = read_schedule_config(db)
    now_local = datetime.now(tz)
    interval_due = cfg['interval_hours'] > 0 and _interval_due(db, cfg['interval_hours'])
    daily_due = bool(cfg['daily_at']) and _daily_due(db, cfg['daily_at'], now_local)
    if not interval_due and not daily_due:
        return
    label = '+'.join(filter(None, [
        f'间隔 {cfg["interval_hours"]}h' if interval_due else '',
        f'每日 {cfg["daily_at"]}' if daily_due else '']))
    # 双模式同 tick 到期合并为一次采集,每日模式多拉两页
    pages = 3 if daily_due else 1
    if _run_scheduled(pages=pages, label=label):
        if interval_due:
            db.set_setting(KEY_LAST_INTERVAL, _now_iso())
        if daily_due:
            db.set_setting(KEY_LAST_DAILY, now_local.date().isoformat())


def _interval_due(db, hours):
    raw = db.get_setting(KEY_LAST_INTERVAL)
    if not raw:
        return True  # 从未采过 → 立即触发
    try:
        last = datetime.fromisoformat(raw.replace('Z', '+00:00'))
    except ValueError:
        return True
    return datetime.now(timezone.utc) - last >= timedelta(hours=hours)


def _daily_due(db, daily_at, now_local):
    try:
        hh, mm = (int(x) for x in daily_at.split(':'))
    except ValueError:
        _log(f'[warn] daily_at 格式非法,每日调度暂停:{daily_at!r}')
        return False
    if (now_local.hour, now_local.minute) < (hh, mm):
        return False
    return db.get_setting(KEY_LAST_DAILY) != now_local.date().isoformat()


def _run_scheduled(pages, label):
    """定时/首启采集(调度线程内联执行):锁忙返回 False,下个 tick 自动补判。"""
    if not _run_lock.acquire(blocking=False):
        _log(f'{label}:有采集正在进行,跳过本次调度')
        return False
    try:
        with _state_lock:
            _state.update(
                running=True, trigger='schedule', current='hl365',
                sources=['hl365'], results={'hl365': _pending_result()},
                started_at=_now_iso(), finished_at='')
        _set_result('hl365', status='running')
        result = _collect_source('hl365', pages=pages)
        _set_result('hl365', **result)
        _log(f'{label} 采集完成:{_result_summary(result)}')
        return True
    finally:
        _set_state(running=False, current='', finished_at=_now_iso())
        _run_lock.release()


# ---- 状态与配置 ----

def get_status(db):
    with _state_lock:
        payload = {
            'running': _state['running'],
            'trigger': _state['trigger'],
            'current': _state['current'],
            'sources': list(_state['sources']),
            'results': {k: dict(v) for k, v in _state['results'].items()},
            'started_at': _state['started_at'],
            'finished_at': _state['finished_at'],
        }
    payload['last_interval_run'] = db.get_setting(KEY_LAST_INTERVAL) or ''
    payload['last_daily_date'] = db.get_setting(KEY_LAST_DAILY) or ''
    return payload


def reset_timers_after_save(db):
    """保存配置后重置计时:间隔从现在重新计时;每日按新时刻重新判定。"""
    cfg = read_schedule_config(db)
    if cfg['interval_hours'] > 0:
        db.set_setting(KEY_LAST_INTERVAL, _now_iso())
    if cfg['daily_at']:
        db.set_setting(KEY_LAST_DAILY, '')