"""存储层:元数据入数据库,正文与图片入对象存储。

凭据一律来自环境变量(见 .env.example),不写入仓库:
  MELON_DB_URL      未设置时回退本地 SQLite(data/melon.db)
  MELON_S3_*        未设置时回退本地目录(data/objects/)
"""
import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

from collector.config import data_dir, project_root

_SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  article_key TEXT NOT NULL,
  url TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  published_at TEXT,
  title_hash TEXT NOT NULL,
  content_hash TEXT,
  content_object TEXT,
  images_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'ok',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(source, article_key)
);
CREATE INDEX IF NOT EXISTS idx_articles_source_pub
  ON articles(source, published_at DESC);
"""


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class Database:
    def __init__(self, path=None):
        if path is None:
            env_url = os.environ.get('MELON_DB_URL')
            # 目前仅支持本地 SQLite 回退;真实数据库接入时在此扩展
            if env_url and not env_url.startswith('sqlite'):
                raise SystemExit('MELON_DB_URL 指向非 SQLite 数据库,当前尚未实现该驱动,请先使用回退或扩展 collector/store.py')
            path = env_url[7:] if env_url else os.path.join(data_dir(), 'melon.db')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        # FastAPI 在线程池中调用,连接允许跨线程,写入用锁串行化
        self._lock = threading.Lock()
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # WAL:容器内定时采集与宿主机浏览器采集可能跨进程并发读写
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.executescript(_SCHEMA)

    def find(self, source, article_key):
        with self._lock:
            row = self.conn.execute(
                'SELECT * FROM articles WHERE source=? AND article_key=?',
                (source, article_key)).fetchone()
        return dict(row) if row else None

    def upsert(self, source, article_key, url, title, summary, published_at,
               title_hash, content_hash, content_object, images, status='ok'):
        now = _now()
        images_json = json.dumps(images, ensure_ascii=False)
        with self._lock:
            self.conn.execute(
                """INSERT INTO articles
                   (source, article_key, url, title, summary, published_at,
                    title_hash, content_hash, content_object, images_json, status,
                    created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(source, article_key) DO UPDATE SET
                     url=excluded.url, title=excluded.title, summary=excluded.summary,
                     published_at=excluded.published_at, title_hash=excluded.title_hash,
                     content_hash=excluded.content_hash, content_object=excluded.content_object,
                     images_json=excluded.images_json, status=excluded.status,
                     updated_at=excluded.updated_at""",
                (source, article_key, url, title, summary, published_at,
                 title_hash, content_hash, content_object, images_json, status,
                 now, now))
            self.conn.commit()

    def list_articles(self, source=None, limit=50, offset=0):
        """按发布时间倒序列出文章(供后端列表接口)。"""
        if source:
            sql = ('SELECT source, article_key, url, title, summary, published_at,'
                   ' images_json, status FROM articles WHERE source=?'
                   ' ORDER BY published_at DESC LIMIT ? OFFSET ?')
            args = (source, limit, offset)
        else:
            sql = ('SELECT source, article_key, url, title, summary, published_at,'
                   ' images_json, status FROM articles'
                   ' ORDER BY published_at DESC LIMIT ? OFFSET ?')
            args = (limit, offset)
        with self._lock:
            rows = self.conn.execute(sql, args).fetchall()
        return [dict(r) for r in rows]

    def close(self):
        self.conn.close()


class ObjectStore:
    """对象存储:S3 兼容端点(RustFS)或本地目录回退,同一套 key 规范。"""

    def __init__(self):
        self.endpoint = os.environ.get('MELON_S3_ENDPOINT')
        self.bucket = os.environ.get('MELON_S3_BUCKET')
        self.public_base = os.environ.get('MELON_S3_PUBLIC_BASE', '').rstrip('/')
        self.local_root = os.path.join(data_dir(), 'objects')
        self._s3 = None
        if self.endpoint and self.bucket:
            import boto3  # 惰性导入:本地回退时不要求安装
            self._s3 = boto3.client(
                's3', endpoint_url=self.endpoint,
                aws_access_key_id=os.environ.get('MELON_S3_ACCESS_KEY'),
                aws_secret_access_key=os.environ.get('MELON_S3_SECRET_KEY'))

    def public_url(self, key):
        if self._s3 and self.public_base:
            return f'{self.public_base}/{key}'
        return f'/objects/{key}'

    def put(self, key, data):
        if self._s3:
            self._s3.put_object(Bucket=self.bucket, Key=key, Body=data)
        else:
            path = os.path.join(self.local_root, key)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.exists(path) and os.path.getsize(path) == len(data):
                return  # 内容一致,幂等跳过
            with open(path, 'wb') as f:
                f.write(data)

    def exists(self, key):
        if self._s3:
            try:
                self._s3.head_object(Bucket=self.bucket, Key=key)
                return True
            except Exception:
                return False
        return os.path.exists(os.path.join(self.local_root, key))

    def get_bytes(self, key):
        if self._s3:
            from botocore.exceptions import ClientError
            try:
                resp = self._s3.get_object(Bucket=self.bucket, Key=key)
            except ClientError as exc:
                if exc.response['Error']['Code'] in ('404', 'NoSuchKey'):
                    raise FileNotFoundError(key)
                raise
            return resp['Body'].read()
        path = os.path.join(self.local_root, key)
        if not os.path.exists(path):
            raise FileNotFoundError(key)
        with open(path, 'rb') as f:
            return f.read()


def sha16(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]
