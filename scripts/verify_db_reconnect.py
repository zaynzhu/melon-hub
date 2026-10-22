"""验证 MySQL 长连接被服务端断开后 Database 能自动重连。

复现线上故障(NAS 极空间 docker 容器间链路掐长连接):连接被 KILL 后
_exec 抛 2006/2013,全部碰 DB 的接口 500,直到手动重启容器。
修复后 _exec 每次执行前 ping(reconnect=True),断了自动重连。

用法:.venv/bin/python -I scripts/verify_db_reconnect.py
只读验证(KILL 的是本脚本自己建立的连接,不碰数据)。
"""
import os
import sys
from urllib.parse import urlparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
os.chdir(_ROOT)

from dotenv import load_dotenv

load_dotenv(os.path.join(_ROOT, '.env'))

from collector.store import Database


def main():
    db = Database()
    if not getattr(db, '_mysql', None):
        print('[exit] 未配置 mysql://(当前 SQLite 回退),不涉及断连重连场景')
        return

    before = db.count_articles()
    print(f'[1/4] 基线查询正常:articles={before}')

    url = os.environ['MELON_DB_URL']
    parsed = urlparse(url)
    import pymysql

    # 旁路连接:用来 KILL 掉 Database 的专属连接,模拟服务端断连
    killer = pymysql.connect(host=parsed.hostname, port=parsed.port or 3306,
                             user=parsed.username, password=parsed.password or '')
    with killer.cursor() as c:
        victim_id = next(iter(db._exec('SELECT CONNECTION_ID() AS cid').fetchone().values()))
        c.execute(f'KILL {victim_id}')
    killer.close()
    print(f'[2/4] 已 KILL Database 连接(id={victim_id}),模拟服务端断连')

    after = db.count_articles()
    print(f'[3/4] KILL 后查询:articles={after}')
    if after < before:
        raise SystemExit('[fail] 重连后发现数据变少')
    print('[4/4] 通过:断连后自动重连成功,接口无需重启即可恢复')


if __name__ == '__main__':
    main()