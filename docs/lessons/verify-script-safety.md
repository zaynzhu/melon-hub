# 验证/断言脚本自身的安全性与可信度

> 主题:本项目 `scripts/verify_*.py`、`ui_*_assert.py` 这类自写验证工具,自身有两类自伤雷——写数据的脚本缺隔离护栏会污染生产;断言脚本失败路径吞掉退出码会骗过 CI。

## 结论速览

- **直接可用**:① 会写数据的脚本,入口先硬查隔离三件套(DB 必须 sqlite: 临时库、数据目录必须在系统临时区、S3 端点必须显式置空),缺一 `SystemExit` 拒绝运行;② 断言脚本的任何失败分支都要确保进程退出码非零,`return` 会跳过 try/finally 之后的退出码逻辑。
- **适用条件**:Python 验证脚本通过环境变量注入隔离环境、且项目 `.env` 含真实生产凭据的仓库(macOS/Linux 通用)。

---

## ✅ 写数据的验证脚本:入口硬查隔离 env,缺一拒绝运行(2026-10-23)

- **为何值得记**:melon-hub 的断言脚本带 `--seed` 种数据模式,初版无任何防护,被对抗性 code-review 逮出。根因机制在 `collector/config.py`:`load_env()` 在 import 时执行、且是 `os.environ.setdefault`——**不设隔离 env 时 `.env` 里的真实生产 MySQL 自动生效**,忘设四个变量等于开着测试脚本的生产写入权限。以后每写一个带 seed/写操作的验证脚本都要带这套护栏。
- **真实风险**(若触发):`--seed` 会把 12 条假文章 upsert 进生产 articles 表,并把 `sync.interval_hours='0'`、`sync.daily_at=''` 写进生产 settings——**静默关死生产定时采集,且面板无任何告警**。
- **最终方案**(scripts/ui_search_assert.py 的 seed() 开头,可直接抄):

```python
def seed():
    import os, tempfile
    url = os.environ.get('MELON_DB_URL', '')
    if not url.startswith('sqlite:'):
        raise SystemExit(f'拒绝运行:MELON_DB_URL 必须是 sqlite: 临时库(当前 {url or "未设置"};'
                         '不设会经 .env 写入生产 MySQL)')
    data = os.environ.get('MELON_DATA_DIR', '')
    # realpath 归一:macOS 上 /tmp 是 /private/tmp 符号链接,gettempdir 在 /var 下
    tmp_roots = {os.path.realpath(tempfile.gettempdir()), os.path.realpath('/tmp')}
    if not data or not any(os.path.realpath(data).startswith(t) for t in tmp_roots):
        raise SystemExit(f'拒绝运行:MELON_DATA_DIR 必须指向临时目录(当前 {data or "未设置"})')
    if os.environ.get('MELON_S3_ENDPOINT') is None or os.environ.get('MELON_S3_BUCKET') is None:
        raise SystemExit('拒绝运行:先显式置空 MELON_S3_ENDPOINT= MELON_S3_BUCKET= 阻断 .env 的 RustFS')
    # 护栏通过后再 import collector
```

- **为什么这样做**:`load_env` 是 setdefault 语义,反向利用它——把"没设 env"从"自动得真值"翻转成"立即报错";且护栏必须在 **import collector 之前**执行,import 后 `.env` 已注入,再查就晚了。
- **验证证据**:修后实测两路拒绝均 exit 1、errmsg 精确——裸跑:

```
拒绝运行:MELON_DB_URL 必须是 sqlite: 临时库(当前 未设置;不设会经 .env 写入生产 MySQL)
exit=1
```

只设 DB 不设数据目录:`拒绝运行:MELON_DATA_DIR 必须指向临时目录(当前 未设置) exit=1`;四件套齐全时正常 `seed 完成`。
- **交叉验证**:code-review 子会话提出 → 我修时又被护栏反咬一口(macOS `tempfile.gettempdir()` 是 `/var/folders/...` 而 `/tmp` 是符号链接,前缀比较必须 realpath 归一,见易错点)→ 拒绝/放行两路均实证。单仓库、单轮。
- **适用条件**:`.env` 在项目根、env 注入走 setdefault 的 Python 项目;仓库若 `.env` 不入库(本项目正是),风险更高——没人能靠 review 看到本地 `.env` 真值在哪指。
- **易错点**:macOS 路径比较必须 `os.path.realpath` 归一(`/tmp` ↔ `/private/tmp`、gettempdir 在 `/var`),直接 `startswith` 会把合法 `/tmp/xxx` 也拒掉;S3 用 `is None` 判断(区分"没设"与"显式置空"),`get(...) or ''` 会把两者混为一谈。

---

## ✅ 断言脚本:任何失败分支都要以退出码非零收尾(2026-10-23)

- **为何值得记**:断言脚本一旦接 CI/门禁,退出码就是它的全部意义。本次 B1(搜索框存在性)失败分支写的是"记入失败表后 `return`",该 return 位于 try/finally 块内——finally 只清理 Chrome 进程,函数尾部 `if _FAILED: sys.exit(1)` 被整体跳过,**搜索功能没了(RED)时进程退出码是 0**,CI 必判全绿。任何"先跳过再汇总退出码"的脚本都要回查这条路径。
- **最终方案**:失败即 `sys.exit(1)`,不 return:

```python
if not check('B1 顶栏存在搜索框 #search-input', has_input, '功能未实现'):
    print('\nB 段后续断言依赖搜索框,跳过(实现后再跑)')
    sys.exit(1)  # return 会跳过 try/finally 之后的退出码逻辑,RED 态 exit 0 骗过 CI
```

- **验证证据**:实证两态退出码——把断言指到无搜索框的页面(`/settings.html`,B1 必 FAIL):

```
RED 态 exit=1
GREEN 态 exit=0   # 对主页全套 23 项全过时
```

- **适用条件**:任何"try/finally 内多处 return、退出码在函数尾部统一计算"结构的断言脚本(Python asyncio + CDP 模式尤其常见)。
- **易错点**:别只信"控制台有 [FAIL] 输出"就当 CI 能接——CI 只看退出码;每加一条早退/跳过分支,都要重跑一次"必然失败的场景"验证 exit≠0。
