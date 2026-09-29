"""melon-hub 轻后端:列表、详情、手动同步、定时配置接口 + 静态资源。

启动:.venv/bin/python -m uvicorn server.app:app --port 8787
"""
import json
import os
import re
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from collector.config import data_dir, load_config, project_root
from collector.store import Database, ObjectStore
from server import sync

db = Database()
store = ObjectStore()

_DAILY_AT_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')


@asynccontextmanager
async def lifespan(_app):
    sync.start_scheduler(db)
    yield


app = FastAPI(title='melon-hub', docs_url=None, redoc_url=None, lifespan=lifespan)


def _source_url(row):
    """源站原文链接:用当前配置的 home 域名拼文章路径——镜像换域名时
    改 sites.yaml 即可让旧文章的原文链接跟着更新,不受采集时域名失效影响。"""
    try:
        site = load_config()['sites'].get(row['source'])
        if not site:
            return row['url']
        return site['home'].rstrip('/') + urlparse(row['url']).path
    except Exception:
        return row['url']


def _cover(row):
    """列表封面:只用服务端直出的明文缩略图;正文密文图不可渲染,不作为封面。"""
    if row.get('thumb_object'):
        return store.public_url(row['thumb_object'])
    return ''


@app.get('/api/sources')
def sources():
    cfg = load_config()['sites']
    return [{'id': sid, 'name': site['name'], 'home': site['home']}
            for sid, site in cfg.items()]


@app.get('/api/articles')
def articles(source: str = None, limit: int = Query(50, le=200), offset: int = 0):
    if source and source not in load_config()['sites']:
        raise HTTPException(404, f'未知站点:{source}')
    rows = db.list_articles(source, limit, offset)
    for r in rows:
        r['cover'] = _cover(r)
        r.pop('images_json', None)
        r['source_url'] = _source_url(r)
    return {'total': len(rows), 'articles': rows}


@app.get('/api/articles/{source}/{article_key}')
def article_detail(source: str, article_key: str):
    row = db.find(source, article_key)
    if not row or not row.get('content_object'):
        raise HTTPException(404, '条目不存在或正文未采集')
    try:
        payload = json.loads(store.get_bytes(row['content_object']))
    except FileNotFoundError:
        raise HTTPException(404, '正文对象缺失,请重新采集')
    # 正文内图片 key → 可访问 URL(本地回退 /objects/<key>,S3 为公网地址)
    base = store.public_url('').rstrip('/')
    payload['html'] = payload['html'].replace('src="', f'src="{base}/')
    payload.pop('images', None)
    payload['source_url'] = _source_url(row)
    payload['thumb'] = store.public_url(row['thumb_object']) if row.get('thumb_object') else ''
    return payload


@app.post('/api/sync')
def manual_sync(sources: list[str] = Body(..., embed=True)):
    valid = sync.valid_sources()
    bad = [s for s in sources if s not in valid]
    if bad:
        raise HTTPException(400, f'未知站点:{",".join(bad)}')
    if not sources:
        raise HTTPException(400, 'sources 不能为空')
    ok, message = sync.start_manual_sync(sources)
    if not ok:
        raise HTTPException(409, message)
    return {'status': 'started', 'sources': sources}


@app.get('/api/sync/status')
def sync_status():
    return sync.get_status(db)


@app.get('/api/settings')
def get_settings():
    return sync.read_schedule_config(db)


@app.post('/api/settings')
def save_settings(interval_hours: int = Body(..., embed=True),
                 daily_at: str = Body(..., embed=True)):
    if interval_hours < 0 or interval_hours > 24:
        raise HTTPException(400, 'interval_hours 需在 0-24 之间(0 表示关闭)')
    if daily_at and not _DAILY_AT_RE.match(daily_at):
        raise HTTPException(400, 'daily_at 需为 HH:MM 格式(24 小时制),留空表示关闭')
    db.set_setting(sync.KEY_INTERVAL, str(interval_hours))
    db.set_setting(sync.KEY_DAILY, daily_at)
    sync.reset_timers_after_save(db)
    return sync.read_schedule_config(db)


# 本地对象存储回退:图片与正文 JSON 由 /objects/<key> 提供
_objects_dir = os.path.join(data_dir(), 'objects')
os.makedirs(_objects_dir, exist_ok=True)
app.mount('/objects', StaticFiles(directory=_objects_dir), name='objects')

# 前端静态站(web/),放在 API 之后兜底
_web_dir = os.path.join(project_root(), 'web')
os.makedirs(_web_dir, exist_ok=True)
app.mount('/', StaticFiles(directory=_web_dir, html=True), name='web')
