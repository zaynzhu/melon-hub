"""content.json 备份:把 RustFS 里每篇文章的正文 JSON 拉到本地 git 管理目录。

背景:2026-09-30 reclean 误伤 295 篇正文(RustFS 没开版本控制,覆盖即不可恢复)。
为防止未来再次发生"代码改错 -> 数据被覆盖且没救",同步收尾加自动备份层:
每次新入库的 content.json 顺便写一份到 data/backup_content/<source>/<article_key>.json,
git commit 留痕,任何时刻 git 能回到任何一版正文。

只备份文本 JSON;图片本体已在 RustFS 里(RustFS 自己承担图持久性),不重复备份。
"""
import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from collector.config import project_root  # noqa: E402
from collector.store import Database, ObjectStore  # noqa: E402

BACKUP_DIR_NAME = 'data/backup_content'


def backup_dir():
    return Path(project_root()) / BACKUP_DIR_NAME


def backup_one(store, source, article_key, content_object):
    """备份单篇,返回 (是否新写, 文件路径);已存在且内容一致则跳过。"""
    out = backup_dir() / source / f'{article_key}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    raw = store.get_bytes(content_object)
    if out.exists() and out.read_bytes() == raw:
        return False, out
    out.write_bytes(raw)
    return True, out


def backup_scope(source=None, only_new_since_minutes=None):
    """按 source 备份全部(默认) / 或只备最近 N 分钟入库的(同步收尾用)。

    返回 stats dict 供同步面板透传。
    """
    db = Database()
    store = ObjectStore()
    sql = ("SELECT source, article_key, content_object FROM articles "
           "WHERE content_object IS NOT NULL")
    args = ()
    if source:
        sql += f" AND source={db.ph}"
        args = (source,)
    if only_new_since_minutes:
        # articles.updated_at 由 upsert 维护;只备份最近 N 分钟动过的
        from datetime import datetime, timedelta, timezone
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=only_new_since_minutes)
        sql += f" AND updated_at >= {db.ph}"
        args = args + (cutoff.strftime('%Y-%m-%d %H:%M:%S'),)
    with db._lock:
        rows = [dict(r) for r in db._exec(sql, args).fetchall()]
    stats = {'scanned': len(rows), 'written': 0, 'skipped': 0, 'failed': 0}
    for r in rows:
        try:
            wrote, _ = backup_one(store, r['source'], r['article_key'], r['content_object'])
            stats['written' if wrote else 'skipped'] += 1
        except Exception as exc:  # noqa: BLE001 单篇失败不阻断
            print(f'  [fail] {r["source"]}/{r["article_key"]}: {exc}', file=sys.stderr)
            stats['failed'] += 1
    return stats


def main():
    p = argparse.ArgumentParser(description='备份 articles 的 content.json 到 data/backup_content/')
    p.add_argument('--source', default=None, help='只备份某站(hl365/wacg51/mrds),默认全部')
    p.add_argument('--since-minutes', type=int, default=None,
                   help='只备份最近 N 分钟入库/更新过的(同步收尾用)')
    args = p.parse_args()
    stats = backup_scope(source=args.source, only_new_since_minutes=args.since_minutes)
    print(f'backup_content: 扫描 {stats["scanned"]} 篇,'
          f'新写 {stats["written"]} 篇,跳过 {stats["skipped"]} 篇,失败 {stats["failed"]} 篇')
    print(f'输出目录: {backup_dir()}')


if __name__ == '__main__':
    main()
