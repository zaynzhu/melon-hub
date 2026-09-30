"""手动同步与进程内定时调度:与 FastAPI 同进程,配置持久化在 settings 表。

语义(改这里要同步改 docs/handoffs/melon-hub.md「同步与调度」):
- 间隔模式:interval_hours>0 且距上次 ≥N 小时 → 采 hl365 1 页
- 每日模式:每天 HH:MM(时区 MELON_TZ,默认 Asia/Shanghai)→ 采 hl365 3 页
- 计时键在发起采集时写入(尝试语义):采集失败也计数,等下个周期再试,不重试轰炸
- 手动同步与定时采集共用一把锁:手动冲突返回 409,定时冲突跳过本 tick
- 定时只调度 hl365;wacg51/mrds 依赖宿主机 kimi-webbridge,仅手动可点
"""
import json
import os
import socket
import threading
import time
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo


def _new_db():
    """收尾步骤自建短命连接(与 auto_decrypt_new 同模式),避免共享 app 的连接。"""
    from collector.store import Database
    return Database()

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
        result = None
        if source == 'hl365':
            from collector import hl365
            stats = hl365.collect(pages=pages)
            stats['img_decrypted'] = _decrypt_new_cipher_images()
            stats['thumbs'] = _backfill_hl365_thumbs()
            result = {'status': 'ok', 'stats': stats, 'error': ''}
        elif source in ('wacg51', 'mrds'):
            result = _collect_browser_site(source)
        else:
            result = {'status': 'error', 'stats': None, 'error': f'站点 {source} 无采集器'}
        # 终检闸门:采集完成≠数据可用,逐类资源盘点,缺口显式亮出(2026-09-29 用户明令)
        result['gaps'] = _audit_gaps(source)
        if any(result['gaps'].values()):
            _log(f"[gap] {source} 仍有缺口:{result['gaps']}")
        # 采集失败:跑一次镜像发现,把 home 自检结论+候选写到结果里——
        # 只报告不改 yaml,人工跑 scripts/discover.py --apply 才落地(项目红线)
        if result['status'] == 'error':
            result['discover'] = _discover_advice(source)
        return result
    except Exception as exc:  # noqa: BLE001 单站失败不中断整批
        r = {'status': 'error', 'stats': None, 'error': str(exc)}
        r['discover'] = _discover_advice(source)
        return r


def _discover_advice(source):
    """主站疑似挂了时跑镜像自动发现,返回 home 健康度/候选/切换建议。

    永远不修改 sites.yaml;只在采集失败时给面板一个可执行的下步提示。
    浏览器 daemon 不可达(hl365 也走 curl,不经过 webbridge 的场景)时,hl365 走
    服务端 curl 即可,wacg51/mrds 的回家路页挂 CF 需真实浏览器,daemon 不通则跳过。
    任何异常都吞掉返回 None(发现失败不应挡住采集本身的错误回报)。
    """
    try:
        # 浏览器站需要 daemon,daemon 不通则跳过 discover(避免触发 daemon 自启风暴)
        if source in ('wacg51', 'mrds') and not _browser_daemon_reachable():
            _log(f'[warn] {source} 采集失败但 webbridge 不在,跳过镜像发现')
            return None
        if source in ('wacg51', 'mrds'):
            from collector import browser_fetch
            try:
                browser_fetch.ensure_ready()
            except Exception as e:  # noqa: BLE001
                _log(f'[warn] {source} 浏览器就绪失败,跳过 discover: {e}')
                return None
        from collector.config import load_config
        from collector import discover as _disc_module
        site = load_config()['sites'].get(source)
        if not site:
            return None
        _log(f'{source} 采集失败,跑镜像发现找备用(home 自检 + 回家路)')
        return _disc_module.discover_site(source, site, apply=False)
    except Exception as exc:  # noqa: BLE001
        _log(f'[warn] {source} discover 失败:{type(exc).__name__}: {exc}')
        return None


def _audit_gaps(source):
    """终检:盘点该站资源缺口——正文排队(pending)/无缩略图/图片下载失败。

    只读盘点,不做修复(修复职责在各收尾步骤);返回计数 dict。
    pending_content 是浏览器站正常排队(每轮限抓 12 篇,下轮继续),
    与 no_thumb/img_failed 同透传前端,让"还要几轮"可见,不让用户猜。
    """
    try:
        db = _new_db()
        with db.conn.cursor() as c:
            c.execute(
                f"SELECT COUNT(*) AS n FROM articles WHERE source='{source}' "
                "AND status='pending'")
            pending = c.fetchone()['n']
            c.execute(
                f"SELECT COUNT(*) AS n FROM articles WHERE source='{source}' "
                "AND (thumb_object IS NULL OR thumb_object='')")
            no_thumb = c.fetchone()['n']
            c.execute(
                f"SELECT images_json FROM articles WHERE source='{source}' "
                "AND images_json IS NOT NULL AND images_json != '[]'")
            bad_imgs = sum(
                1 for row in c.fetchall()
                for im in json.loads(row['images_json'])
                if not im.get('key'))
        db.close()
        return {'pending_content': pending, 'no_thumb': no_thumb,
                'img_failed': bad_imgs}
    except Exception as exc:  # noqa: BLE001 终检失败不阻断主流程,但必须留痕
        _log(f'[warn] {source} 终检失败:{type(exc).__name__}: {exc}')
        return {'pending_content': -1, 'no_thumb': -1, 'img_failed': -1}


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


def _backfill_hl365_thumbs():
    """采集收尾:hl365 新采文章自动补缩略图(RSS 无图,列表密文图需解密)。

    幂等只补缺;纯 Python 离线路线,不依赖浏览器;无缺时零开销。
    """
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'scripts'))
    from thumbs_backfill import backfill_hl365_offline
    try:
        db = _new_db()
        from collector.store import ObjectStore
        with db.conn.cursor() as c:
            c.execute("SELECT article_key FROM articles WHERE source='hl365' "
                      "AND (thumb_object IS NULL OR thumb_object='')")
            missing = [r['article_key'] for r in c.fetchall()]
        if not missing:
            return {'missing': 0, 'ok': 0, 'no_src': [], 'failed': []}
        _log(f'hl365 {len(missing)} 篇缺缩略图,自动补抓(离线路线)')
        return backfill_hl365_offline(db, ObjectStore(), missing)
    except Exception as exc:  # noqa: BLE001 收尾失败不阻断采集主流程
        _log(f'[warn] hl365 缩略图补抓失败:{type(exc).__name__}: {exc}')
        return {'missing': 0, 'ok': 0, 'no_src': [], 'failed': []}


def _backfill_browser_site_thumbs(source, browser):
    """采集收尾:wacg51/mrds 新采文章补缩略图(文章页首图明文 data:URI 路线)。

    collect_thumbs 只能拿到当前列表页卡(40 张上限),新采/翻出去的文章会漏。
    复用 scripts/thumbs_backfill.backfill_article_firstimg,浏览器已在当前会话不浪费;
    幂等只补缺;无缺时零开销。Docker 场景必须自动跑(2026-09-30 用户明令)。
    """
    import sys
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))), 'scripts'))
    from thumbs_backfill import backfill_article_firstimg
    try:
        db = _new_db()
        from collector.store import ObjectStore
        with db.conn.cursor() as c:
            c.execute(
                f"SELECT article_key FROM articles WHERE source='{source}' "
                "AND (thumb_object IS NULL OR thumb_object='')")
            missing = [r['article_key'] for r in c.fetchall()]
        if not missing:
            return {'missing': 0, 'ok': 0}
        _log(f'{source} {len(missing)} 篇缺缩略图(漏网),自动补抓(文章页首图路线)')
        # backfill_article_firstimg 自己打印进度,无返回值;包一层计数
        before_ok = 0
        try:
            backfill_article_firstimg(db, ObjectStore(), source, missing, browser)
            with db.conn.cursor() as c:
                c.execute(
                    f"SELECT COUNT(*) AS n FROM articles WHERE source='{source}' "
                    "AND (thumb_object IS NULL OR thumb_object='')")
                remain = c.fetchone()['n']
            before_ok = len(missing) - remain
        except Exception as e:  # noqa: BLE001
            _log(f'[warn] {source} 缩略图补抓主流程异常:{type(e).__name__}: {e}')
        return {'missing': len(missing), 'ok': before_ok}
    except Exception as exc:  # noqa: BLE001 收尾失败不阻断采集主流程
        _log(f'[warn] {source} 缩略图补抓失败:{type(exc).__name__}: {exc}')
        return {'missing': 0, 'ok': 0}



def _has_pending(source):
    """库里是否还有 pending 正文(排队消化续轮判据)。"""
    db = _new_db()
    try:
        with db.conn.cursor() as c:
            c.execute(f"SELECT COUNT(*) AS n FROM articles "
                      f"WHERE source='{source}' AND status='pending'")
            return c.fetchone()['n'] > 0
    finally:
        db.close()


def _collect_browser_site(source):
    from collector import browser_fetch, typecho_collector
    if not _browser_daemon_reachable():
        return {'status': 'error', 'stats': None,
                'error': '需本机浏览器环境(kimi-webbridge daemon 未运行),请在宿主机运行采集器'}
    try:
        browser_fetch.ensure_ready()
        stats = dict(typecho_collector.collect_list(source))
        # 列表页正开着,顺手采缩略图(卡片 base64 明文,幂等只补缺)——
        # 不采的话新文章卡片没图(2026-09-29 hl365 同坑,用户明令不再犯)
        try:
            typecho_collector.collect_thumbs(source)
        except Exception as exc:  # noqa: BLE001 缩略图失败不挡正文
            _log(f'[warn] {source} 缩略图采集失败:{type(exc).__name__}: {exc}')
        stats.update(typecho_collector.collect_articles(source, limit=12))
        # 排队消化:一轮限 12 篇,剩的自动续轮直到清零,上限防失控;
        # 连续失败≥2 说明浏览器路线当天不稳,停止续轮留待下次——
        # 用户明确不要"每次弄一半就结束"
        rounds = 1
        while rounds < 6 and stats['failed'] < 2 and _has_pending(source):
            _log(f'{source} 仍有排队正文,自动续抓第 {rounds + 1} 轮')
            more = typecho_collector.collect_articles(source, limit=12)
            stats['done'] += more['done']
            stats['failed'] += more['failed']
            rounds += 1
        stats['img_decrypted'] = _decrypt_new_cipher_images()
        # 缩略图补漏网:collect_thumbs 只能拿到当前列表页卡,新增/翻出去的文章
        # 要走文章页首图兜底(复用 thumbs_backfill 的明文路线,浏览器还开着不浪费)
        # ——Docker 场景必须自动跑,不能留给人发现(用户 2026-09-30 明令)
        stats['thumbs_backfill'] = _backfill_browser_site_thumbs(source, browser_fetch)
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