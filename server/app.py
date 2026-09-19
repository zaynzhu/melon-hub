"""melon-hub 轻后端:列表、详情、手动刷新三个接口 + 静态资源。

启动:.venv/bin/python -m uvicorn server.app:app --port 8787
"""
import json
import os

from fastapi import FastAPI, HTTPException, Query
from fastapi.staticfiles import StaticFiles

from collector.config import data_dir, load_config, project_root
from collector.store import Database, ObjectStore

app = FastAPI(title='melon-hub', docs_url=None, redoc_url=None)
db = Database()
store = ObjectStore()


def _cover(images_json):
    try:
        images = json.loads(images_json or '[]')
    except ValueError:
        return ''
    for img in images:
        if img.get('key'):
            return store.public_url(img['key'])
    return ''


@app.get('/api/sources')
def sources():
    cfg = load_config()['sites']
    return [{'id': sid, 'name': site['name']} for sid, site in cfg.items()]


@app.get('/api/articles')
def articles(source: str = None, limit: int = Query(50, le=200), offset: int = 0):
    if source and source not in load_config()['sites']:
        raise HTTPException(404, f'未知站点:{source}')
    rows = db.list_articles(source, limit, offset)
    for r in rows:
        r['cover'] = _cover(r.pop('images_json'))
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
    return payload


@app.post('/api/refresh/{source}')
def refresh(source: str):
    if source == 'hl365':
        from collector import hl365
        stats = hl365.collect(pages=1)
        return {'status': 'ok', 'stats': stats}
    raise HTTPException(400, f'站点 {source} 的采集器尚未接入(需浏览器路线)')


# 本地对象存储回退:图片与正文 JSON 由 /objects/<key> 提供
_objects_dir = os.path.join(data_dir(), 'objects')
os.makedirs(_objects_dir, exist_ok=True)
app.mount('/objects', StaticFiles(directory=_objects_dir), name='objects')

# 前端静态站(web/),放在 API 之后兜底
_web_dir = os.path.join(project_root(), 'web')
os.makedirs(_web_dir, exist_ok=True)
app.mount('/', StaticFiles(directory=_web_dir, html=True), name='web')
