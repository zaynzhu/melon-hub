"""验证标题模糊搜索:store.list_articles/count_articles 的 q 参数与 /api/articles 透传。

搜索语义(与前端搜索框的约定):
- q 按空白拆词,多词要求全部命中(AND)
- 词按字面子串匹配(instr 语义,% 和 _ 不是通配符)
- 空串/纯空白视为不过滤;q 叠加 source 过滤;分页照常生效

隔离环境:临时 SQLite + 本地对象目录(置空 MELON_S3_* 阻断 .env 里的真实
RustFS),不碰生产数据。
用法:.venv/bin/python -I scripts/verify_search.py
"""
import os
import sys
import tempfile

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

# 隔离注入必须在 import collector 之前(config.load_env 是 setdefault,不会覆盖)
_TMP = tempfile.mkdtemp(prefix='melon-search-verify-')
os.environ['MELON_DB_URL'] = 'sqlite:' + os.path.join(_TMP, 'search.db')
os.environ['MELON_DATA_DIR'] = _TMP
os.environ['MELON_S3_ENDPOINT'] = ''  # 置空走本地对象目录回退
os.environ['MELON_S3_BUCKET'] = ''

from collector.store import Database

# (source, key, title, published_at)
FIXTURES = [
    ('hl365', 'k1', '张某某深夜爆料,全网吃瓜中', '2026-10-23T08:00:00Z'),
    ('hl365', 'k2', '李某某工作室发声明否认', '2026-10-22T09:00:00Z'),
    ('wacg51', 'k3', '吃瓜群众集合!某选秀内幕曝光', '2026-10-22T12:00:00Z'),
    ('wacg51', 'k4', '100% 真实:某剧组恋情实锤', '2026-10-21T10:00:00Z'),
    ('mrds', 'k5', '无瓜说:本周无大瓜', '2026-10-21T18:00:00Z'),
]

_FAILED = []


def check(label, cond, detail=''):
    print(f'[{"ok" if cond else "FAIL"}] {label}' + (f' — {detail}' if detail and not cond else ''))
    if not cond:
        _FAILED.append(label)
    return cond


def titles(rows):
    return [r['title'] for r in rows]


def guard(func, label, *a, **kw):
    """TypeError 视为"功能未实现"记 FAIL 而不是崩掉,让一次运行暴露全部缺口。"""
    try:
        return func(*a, **kw)
    except TypeError as e:
        check(label, False, f'功能未实现:{e}')
        return None


def main():
    db = Database()
    for src, key, title, pub in FIXTURES:
        db.upsert(src, key, f'https://example.com/{key}', title, '摘要',
                  pub, f'th-{key}', None, None, [])

    # ---- 旧契约回归:不带 q 的行为必须一字不变 ----
    # 期望序列 = 按 published_at 倒序(k1→k3→k2→k5→k4),不是固定数组顺序
    DESC_ORDER = [FIXTURES[i][2] for i in (0, 2, 1, 4, 3)]
    rows = guard(lambda: db.list_articles(), '回归:无参列出全部 5 篇(时间倒序)')
    if rows is not None:
        check('回归:无参列出全部 5 篇(时间倒序)',
              titles(rows) == DESC_ORDER, str(titles(rows)))
    n = guard(lambda: db.count_articles(), '回归:无参 count=5')
    if n is not None:
        check('回归:无参 count=5', n == 5, str(n))
    n = guard(lambda: db.count_articles('hl365'), '回归:source 过滤 count=2')
    if n is not None:
        check('回归:source 过滤 count=2', n == 2, str(n))

    # ---- q 参数:store 层 ----
    rows = guard(lambda: db.list_articles(q='瓜'), '单字"瓜"命中 3 篇(时间倒序)')
    if rows is not None:
        check('单字"瓜"命中 3 篇(时间倒序)',
              titles(rows) == [FIXTURES[0][2], FIXTURES[2][2], FIXTURES[4][2]],
              str(titles(rows)))
    n = guard(lambda: db.count_articles(q='瓜'), '单字"瓜" count=3')
    if n is not None:
        check('单字"瓜" count=3', n == 3, str(n))

    rows = guard(lambda: db.list_articles(q='张某某'), '短语"张某某"命中 k1')
    if rows is not None:
        check('短语"张某某"命中 k1', titles(rows) == [FIXTURES[0][2]], str(titles(rows)))

    rows = guard(lambda: db.list_articles(q='吃瓜 内幕'), '多词 AND:"吃瓜 内幕"只命中 k3')
    if rows is not None:
        check('多词 AND:"吃瓜 内幕"只命中 k3', titles(rows) == [FIXTURES[2][2]], str(titles(rows)))
    n = guard(lambda: db.count_articles(q='张某某 内幕'), '多词 AND:词不同篇则 0')
    if n is not None:
        check('多词 AND:词不同篇则 0', n == 0, str(n))

    rows = guard(lambda: db.list_articles(source='hl365', q='吃瓜'), 'q 叠加 source 只命中 k1')
    if rows is not None:
        check('q 叠加 source 只命中 k1', titles(rows) == [FIXTURES[0][2]], str(titles(rows)))

    rows = guard(lambda: db.list_articles(q='不存在的词'), '无命中返回空列表')
    if rows is not None:
        check('无命中返回空列表', rows == [])
    n = guard(lambda: db.count_articles(q='不存在的词'), '无命中 count=0')
    if n is not None:
        check('无命中 count=0', n == 0, str(n))

    # % 是普通字符:只匹配字面含 % 的 k4;若当 LIKE 通配符会命中全部 5 篇
    rows = guard(lambda: db.list_articles(q='%'), 'q="%" 按字面只命中 k4')
    if rows is not None:
        check('q="%" 按字面只命中 k4', titles(rows) == [FIXTURES[3][2]], str(titles(rows)))
    n = guard(lambda: db.count_articles(q='_'), 'q="_" 无命中(不是通配符)')
    if n is not None:
        check('q="_" 无命中(不是通配符)', n == 0, str(n))

    rows = guard(lambda: db.list_articles(q='   '), '纯空白 q 视为不过滤(5 篇)')
    if rows is not None:
        check('纯空白 q 视为不过滤(5 篇)', len(rows) == 5, str(len(rows)))

    rows = guard(lambda: db.list_articles(q='瓜', limit=1, offset=1), 'q+分页:offset=1 跳过最新一条')
    if rows is not None:
        check('q+分页:offset=1 跳过最新一条', titles(rows) == [FIXTURES[2][2]], str(titles(rows)))

    # ---- q 参数:API 层(server.app.articles 透传) ----
    from server.app import articles as api_articles
    res = guard(lambda: api_articles(source=None, limit=50, offset=0, q='吃瓜'),
                'API:q="吃瓜" total=2 且列表一致')
    if res is not None:
        check('API:q="吃瓜" total=2 且列表一致',
              res['total'] == 2 and titles(res['articles']) == [FIXTURES[0][2], FIXTURES[2][2]],
              str(res.get('total')))
    res = guard(lambda: api_articles(source='hl365', limit=50, offset=0, q='吃瓜'),
                'API:q 叠加 source 过滤')
    if res is not None:
        check('API:q 叠加 source 过滤',
              res['total'] == 1 and titles(res['articles']) == [FIXTURES[0][2]], str(res.get('total')))
    res = guard(lambda: api_articles(source=None, limit=50, offset=0, q='  '),
                'API:纯空白 q 等价不过滤')
    if res is not None:
        check('API:纯空白 q 等价不过滤', res['total'] == 5, str(res.get('total')))
    res = guard(lambda: api_articles(source=None, limit=50, offset=0),
                'API:不带 q 行为不变(回归)')
    if res is not None:
        check('API:不带 q 行为不变(回归)',
              res['total'] == 5 and res['articles'][0]['title'] == FIXTURES[0][2]
              and 'cover' in res['articles'][0], str(res.get('total')))

    # 搜索词长度上限(与前端 maxlength=100 对齐,防 curl 直打超长 q 把 SQL 拼爆)
    from fastapi import HTTPException
    try:
        api_articles(source=None, limit=50, offset=0, q='瓜' * 101)
        check('API:q=101 字应返回 400', False, '未拦截')
    except HTTPException as e:
        check('API:q=101 字应返回 400', e.status_code == 400, f'status={e.status_code}')
    res = guard(lambda: api_articles(source=None, limit=50, offset=0, q='瓜' * 100),
                'API:q=100 字(边界)放行')
    if res is not None:
        check('API:q=100 字(边界)放行', isinstance(res.get('total'), int), repr(res)[:60])

    print()
    if _FAILED:
        print(f'结果:{len(_FAILED)} 项未过')
        for f in _FAILED:
            print(f'  - {f}')
        sys.exit(1)
    print('结果:全部通过')


if __name__ == '__main__':
    main()