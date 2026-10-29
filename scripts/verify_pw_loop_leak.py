"""browser_fetch playwright 后端线程 loop 泄漏回归验证。

复现 NAS 2026-10-29 故障:某轮 chromium.launch 一次性失败时,
_playwright_state['pw'] 尚未赋值(原实现写在函数最后一行),close_session
拿不到 pw 去 stop → loop/greenlet 泄漏在长驻调度线程;之后同线程每次
sync_playwright().start() 都报:
"It looks like you are using Playwright Sync API inside the asyncio loop."
症状:wacg51/mrds 定时采集每天必失败,hl365(无浏览器路线)与手动同步
(每次新建线程)不受影响。

注入方式:PLAYWRIGHT_BROWSERS_PATH 指向不存在目录,launch 找不到浏览器
二进制必失败——不依赖本机是否装浏览器,不写任何数据,完全隔离。

用法(项目 .venv 默认无 playwright,用任意装了 playwright 的解释器):
  MELON_BROWSER_BACKEND=playwright <有playwright的venv>/python -I scripts/verify_pw_loop_leak.py
退出码:0=无泄漏(修复后);1=泄漏复现(修复前)。
"""
import os
import sys
import threading

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# _BACKEND 在 import 时读取,必须先设;二进制查找路径指向不存在目录强制 launch 失败
os.environ['MELON_BROWSER_BACKEND'] = 'playwright'
os.environ['PLAYWRIGHT_BROWSERS_PATH'] = os.path.join(_ROOT, '.verify-no-browsers')

try:
    import requests  # noqa: F401
except ImportError:
    # playwright 路线不用 requests(仅 webbridge 后端用),stub 只为通过模块级 import
    sys.modules['requests'] = type(sys)('requests')

from collector import browser_fetch  # noqa: E402 需在 env 设置后导入

_MSG = 'Sync API inside the asyncio loop'
_result = {}


def _seq():
    """模拟 _collect_browser_site 的真实序列(同一线程):
    ensure_ready(launch 失败冒异常)→ finally close_session → 下一轮再 ensure_ready。"""
    try:
        browser_fetch.ensure_ready()
        _result['r1'] = 'unexpected-ok(注入失败未生效?)'
    except Exception as exc:  # noqa: BLE001 注入的失败,任意异常类型都算 r1 失败
        _result['r1'] = str(exc).splitlines()[0]
    try:
        browser_fetch.close_session()
    except Exception:
        pass
    try:
        browser_fetch.ensure_ready()
        _result['r2'] = 'ok'
    except Exception as exc:  # noqa: BLE001
        _result['r2'] = str(exc).splitlines()[0]


def main():
    t = threading.Thread(target=_seq)
    t.start()
    t.join()
    print(f'第一轮 launch(预期注入失败): {_result["r1"]}')
    print(f'同线程第二轮 start: {_result["r2"]}')
    if _MSG in _result['r2']:
        print('[RED] loop 泄漏复现:同线程第二次 start 被泄漏 loop 拦截')
        sys.exit(1)
    print('[GREEN] 无泄漏:第二轮失败是 launch 注入错误,不是 asyncio loop 错')
    sys.exit(0)


if __name__ == '__main__':
    main()