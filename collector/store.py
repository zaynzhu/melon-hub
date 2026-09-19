"""存储层:元数据入数据库,正文与图片入对象存储。

凭据一律来自环境变量(见 .env.example),不写入仓库:
  MELON_DB_URL      mysql://user:pass@host:port/db 或 sqlite 路径;不设时回退本地 SQLite
  MELON_S3_*        RustFS/S3 兼容端点;不设时回退本地目录(data/objects/)
"""
import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from urllib.parse import urlparse

from collector.config import data_dir, project_root

_SCHEMA_MYSQL = """
CREATE TABLE IF NOT EXISTS articles (
  id BIGINT AUTO_INCREMENT PRIMARY KEY,
  source VARCHAR(32) NOT NULL,
  article_key VARCHAR(64) NOT NULL,
  url VARCHAR(512) NOT NULL,
  title TEXT NOT NULL,
  summary TEXT,
  published_at VARCHAR(32) DEFAULT NULL,
  title_hash VARCHAR(64) NOT NULL,
  content_hash VARCHAR(64) DEFAULT NULL,
  content_object VARCHAR(255) DEFAULT NULL,
  images_json LONGTEXT,
  thumb_object VARCHAR(255) DEFAULT NULL,
  status VARCHAR(16) NOT NULL DEFAULT 'ok',
  created_at VARCHAR(32) NOT NULL,
  updated_at VARCHAR(32) NOT NULL,
  UNIQUE KEY uk_source_key (source, article_key),
  KEY idx_source_pub (source, published_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
"""

_SCHEMA_SQLITE = """
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
  thumb_object TEXT,
  status TEXT NOT NULL DEFAULT 'ok',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(source, article_key)
);
CREATE INDEX IF NOT EXISTS idx_articles_source_pub
  ON articles(source, published_at DESC);
"""

# 已存在的旧库补列(列已存在时报错忽略)
_ALTER_THUMB = {
    'mysql': 'ALTER TABLE articles ADD COLUMN thumb_object VARCHAR(255) DEFAULT NULL',
    'sqlite': 'ALTER TABLE articles ADD COLUMN thumb_object TEXT',
}


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


class Database:
    """articles 表访问;MySQL(MELON_DB_URL)或 SQLite 回退,接口一致。"""

    def __init__(self, path=None):
        url = os.environ.get('MELON_DB_URL', '')
        self._mysql = None
        self._lock = threading.Lock()
        if url.startswith('mysql://'):
            self._init_mysql(url)
        else:
            self._init_sqlite(path)

    def _init_sqlite(self, path):
        if path is None:
            env_url = os.environ.get('MELON_DB_URL')
            if env_url and not env_url.startswith('sqlite'):
                raise SystemExit('MELON_DB_URL 仅支持 mysql:// 或 sqlite;请检查配置')
            path = env_url[7:] if env_url else os.path.join(data_dir(), 'melon.db')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.ph = '?'
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        # WAL:容器内定时采集与宿主机浏览器采集可能跨进程并发读写
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.executescript(_SCHEMA_SQLITE)
        try:
            self.conn.execute(_ALTER_THUMB['sqlite'])
            self.conn.commit()
        except sqlite3.OperationalError:
            pass  # 列已存在

    def _init_mysql(self, url):
        import pymysql
        self._mysql = True
        parsed = urlparse(url)
        dbname = parsed.path.lstrip('/') or 'melon_hub'
        common = dict(host=parsed.hostname, port=parsed.port or 3306,
                      user=parsed.username, password=parsed.password or '',
                      charset='utf8mb4', autocommit=True)
        server = pymysql.connect(**common)
        with server.cursor() as c:
            c.execute(f'CREATE DATABASE IF NOT EXISTS `{dbname}` '
                      'CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
        server.close()
        self.ph = '%s'
        self.conn = pymysql.connect(database=dbname, cursorclass=pymysql.cursors.DictCursor, **common)
        with self.conn.cursor() as c:
            c.execute(_SCHEMA_MYSQL)
            try:
                c.execute(_ALTER_THUMB['mysql'])
            except Exception:
                pass  # 列已存在

    def _exec(self, sql, args=()):
        """统一执行:pymysql 走 cursor,sqlite3 直接 execute,均返回可 fetch 的游标。"""
        if self._mysql:
            cur = self.conn.cursor()
            cur.execute(sql, args)
            return cur
        return self.conn.execute(sql, args)

    def find(self, source, article_key):
        with self._lock:
            row = self._exec(
                f'SELECT * FROM articles WHERE source={self.ph} AND article_key={self.ph}',
                (source, article_key)).fetchone()
        return dict(row) if row else None

    def upsert(self, source, article_key, url, title, summary, published_at,
               title_hash, content_hash, content_object, images, status='ok'):
        now = _now()
        images_json = json.dumps(images, ensure_ascii=False)
        args = (source, article_key, url, title, summary, published_at,
                title_hash, content_hash, content_object, images_json, status,
                now, now)
        with self._lock:
            if self._mysql:
                self._exec(
                    """INSERT INTO articles
                       (source, article_key, url, title, summary, published_at,
                        title_hash, content_hash, content_object, images_json, status,
                        created_at, updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON DUPLICATE KEY UPDATE
                         url=VALUES(url), title=VALUES(title), summary=VALUES(summary),
                         published_at=VALUES(published_at), title_hash=VALUES(title_hash),
                         content_hash=VALUES(content_hash), content_object=VALUES(content_object),
                         images_json=VALUES(images_json), status=VALUES(status),
                         updated_at=VALUES(updated_at)""", args)
            else:
                self._exec(
                    f"""INSERT INTO articles
                       (source, article_key, url, title, summary, published_at,
                        title_hash, content_hash, content_object, images_json, status,
                        created_at, updated_at)
                       VALUES ({','.join([self.ph] * 13)})
                       ON CONFLICT(source, article_key) DO UPDATE SET
                         url=excluded.url, title=excluded.title, summary=excluded.summary,
                         published_at=excluded.published_at, title_hash=excluded.title_hash,
                         content_hash=excluded.content_hash, content_object=excluded.content_object,
                         images_json=excluded.images_json, status=excluded.status,
                         updated_at=excluded.updated_at""", args)
                self.conn.commit()

    def set_thumb(self, source, article_key, thumb_object):
        """仅更新缩略图对象 key(列表缩略图补抓用)。"""
        with self._lock:
            self._exec(
                f'UPDATE articles SET thumb_object={self.ph} '
                f'WHERE source={self.ph} AND article_key={self.ph}',
                (thumb_object, source, article_key))
            if not self._mysql:
                self.conn.commit()

    def list_articles(self, source=None, limit=50, offset=0):
        """按发布时间倒序列出文章(供后端列表接口)。"""
        cols = ('SELECT source, article_key, url, title, summary, published_at,'
                ' images_json, thumb_object, status FROM articles')
        if source:
            sql = cols + f' WHERE source={self.ph}'
            args = (source,)
        else:
            sql, args = cols, ()
        sql += f' ORDER BY published_at DESC LIMIT {self.ph} OFFSET {self.ph}'
        args = tuple(args) + (limit, offset)
        with self._lock:
            rows = self._exec(sql, args).fetchall()
        return [dict(r) for r in rows]

    def all_articles(self):
        """全量行(迁移用)。"""
        with self._lock:
            rows = self._exec('SELECT * FROM articles').fetchall()
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
            from botocore.client import Config
            self._s3 = boto3.client(
                's3', endpoint_url=self.endpoint,
                aws_access_key_id=os.environ.get('MELON_S3_ACCESS_KEY'),
                aws_secret_access_key=os.environ.get('MELON_S3_SECRET_KEY'),
                region_name='us-east-1',
                config=Config(signature_version='s3v4'))
            self._ensure_bucket()

    def _ensure_bucket(self):
        from botocore.exceptions import ClientError
        try:
            self._s3.head_bucket(Bucket=self.bucket)
        except ClientError as exc:
            if exc.response['Error']['Code'] in ('404', 'NoSuchBucket'):
                self._s3.create_bucket(Bucket=self.bucket)
            else:
                raise

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
