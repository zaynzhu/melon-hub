"""一次性迁移:本地回退数据(SQLite + data/objects)→ MySQL + RustFS。

用法:.venv/bin/python scripts/migrate_local_to_remote.py [--objects-only] [--db-only]
前提:.env 已配置 MELON_DB_URL(mysql)与 MELON_S3_*。
幂等:MySQL 走 upsert;S3 直接覆盖上传(同 key 同内容)。
"""
import argparse
import os
import sqlite3
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from collector.store import Database, ObjectStore  # noqa: E402


def migrate_db():
    local = sqlite3.connect(os.path.join(_ROOT, 'data', 'melon.db'))
    local.row_factory = sqlite3.Row
    rows = local.execute('SELECT * FROM articles').fetchall()
    remote = Database()  # 读 .env 指向 MySQL
    if remote._mysql is None:
        raise SystemExit('MELON_DB_URL 未指向 MySQL,中止(避免误写本地)')
    print(f'库迁移:SQLite {len(rows)} 行 → MySQL')
    for r in rows:
        remote.upsert(
            source=r['source'], article_key=r['article_key'], url=r['url'],
            title=r['title'], summary=r['summary'],
            published_at=r['published_at'], title_hash=r['title_hash'],
            content_hash=r['content_hash'], content_object=r['content_object'],
            images=json.loads(r['images_json']), status=r['status'])
    print('库迁移完成')


def migrate_objects():
    store = ObjectStore()
    if store._s3 is None:
        raise SystemExit('MELON_S3_* 未配置,中止(避免误留在本地)')
    root = os.path.join(_ROOT, 'data', 'objects')
    count = 0
    for dirpath, _, files in os.walk(root):
        for name in files:
            path = os.path.join(dirpath, name)
            key = os.path.relpath(path, root)
            with open(path, 'rb') as f:
                store.put(key, f.read())
            count += 1
            if count % 50 == 0:
                print(f'  已上传 {count} 个对象...')
    print(f'对象迁移完成:共 {count} 个 → {store.endpoint}/{store.bucket}')


import json  # noqa: E402

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--objects-only', action='store_true')
    parser.add_argument('--db-only', action='store_true')
    args = parser.parse_args()
    if not args.objects_only:
        migrate_db()
    if not args.db_only:
        migrate_objects()
