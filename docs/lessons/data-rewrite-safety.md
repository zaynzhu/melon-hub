# 批量改数据 / 对象存储覆盖 安全护栏

> 清洗/迁移/重跑等"对已入库数据再加工"的高危动作的通用护栏。  
> 教训来源:2026-09-30 用 295 篇 content.json 覆盖原数据,详情页图全没;RustFS 没开版本控制,无法回滚。

## 结论速览

- **任何对 RustFS/MySQL(非 git 跟踪) 数据的批量覆盖操作前,先把原对象备份到 git 跟踪目录**(`data/backup_*/`),git commit,再动手
- **新清洗规则先在 1-2 篇真实数据上跑给你看效果**(截屏/导出 diff),用户点头才上全量
- **CSS 剔除规则**:能用 selector 白名单剔就不要用文本命中剔;文本命中(如 SEO 词)必须加"含 `<img>` 节点一律不删"护栏

**适用条件**:写脚本/解析器/清洗器/迁移工具的 agent;项目用 RustFS/S3 当数据仓。

---

## ✅ 数据被覆盖前的备份层(2026-10-01 验证)

- **为何值得记**:RustFS 默认**没开版本控制**——`put_object` 覆盖旧对象即丢历史,I-Error 不可逆;`s3.list_object_versions()` 实测返回单版本 `null IsLatest=True`。这次 295 篇 content.json 被我直接覆盖,只能靠 re-run采集器从源站恢复正文(图本身在 RustFS 里没动,否则彻底丢)。
- **最终方案**(写入 `docs/handoffs/melon-hub.md` 同步规则清单,未来 Docker/脚本都按这个做):

```bash
# 步骤1:把要改的所有对象先拉到本地 git 目录
.venv/bin/python scripts/backup_content.py  # (本次未写,留给下一步Docker 启动前补)

# 步骤2:git add data/backup_content/ + git commit 留档
# 步骤3:再跑覆盖性脚本
```

- **为什么这样做**:git 提供版本历史 + diff 视图 + 单机可读;RustFS/S3 是数据库备份层,不提供 git 那种"回到任意一版"的细粒度控制。**"对象存储 ≠ 版本控制",要分开管**。
- **适用条件**:任何会产生 `store.put()`、`db.upsert()` 的批量脚本/同步收尾。
- **验证证据**:
  - `s3.get_bucket_versioning(Bucket='melon-hub')` → `{'Status': 'Disabled'}`(默认没开)
  - `list_object_versions(Prefix='mrds/195120/content.json')` → 只有 1 个 version id `null`(被覆盖后)
  - 恢复 295 篇全靠 MySQL 里的 `images_json`(还在) + 重抓正文(text)

---

## ⛔ 批量重清洗时不再"只读"原数据 直接覆盖(2026-09-30 真实事故)

- **错误原文(操作)**:
  ```bash
  # scripts/reclean_articles.py(我写的,这次已回滚删除)
  # 把 db 全量 content_object 拉回,跑新 parse_article 规则,然后:
  store.put(r['content_object'], cleaned.encode('utf-8'))  # 一次 295 篇
  ```
- **错误原因**:
  1. 我以为"老规则只删 SEO 广告词,不会动正文图"——**错**:老 `_SEO_HINTS` 含 `'福利'`/`'直播'`,mrds/wacg51 正文里常用这两个词("福利合集"、"直播回放"),含 `<img>` 的段落被整段 decompose,图全没
  2. 我以为"覆盖前 RustFS 至少有旧版本可回"——**错**:RustFS 默认无版本控制
  3. 我没有先抽 1-2 篇验证"清洗后还有没有图",直接干 295 篇全量
- **为何不可再采用**:任何"重清洗已入库数据"的动作都必须**先抽样 1-2 篇跑给你看效果**(`api/articles/<src>/<key>` 拿到 html 数 `<img>` 个数),用户点头再批量;且**覆盖前必须备份原数据**到 git(见上面 ✅ 条目)
- **替代方案**:下次再改 `parse_article` 时,先在本地用 `parse_article(老 html)` 试,把 `<img>` 数打印出来,确认没少再覆盖
- **判定时效**:2026-09-30 实测教训;不随版本失效(是安全护栏,不是 API 兼容)

---

## ⛔ 用 CSS selector 剔除时把含 `<img>` 的父节点也删了(2026-09-30 同事故根因)

- **错误代码**(老 collector/typecho.py `_SEO_HINTS` 命中循环,现已回滚原状):
  ```python
  for node in box.find_all(['blockquote', 'p', 'div']):
      text = node.get_text(' ', strip=True)
      hits = sum(1 for h in _SEO_HINTS if h in text)
      if hits >= 2: node.decompose()  # 整段删除,img 一并没
  ```
- **错误原因**:`_SEO_HINTS = ('福利', '直播', ...)` 是"广告词黑名单"思路,但吃瓜站正文**本身就大量含"福利合集""直播回放"**——词命中会删正常正文段,段内的 `<img>` 连带销毁。BeautifulSoup 的 `node.decompose()` 把节点和其全部子树一起删,**没有"只删文本不删 img"的部分删除**。
- **为何不可再采用**:CSS selector 剔除时,节点内部是否含 `<img>` 必须先 check;文本命中类剔除要加白名单(含 `<img>` 则跳过)
- **替代方案**:本次教训后的安全写法(如果要再写一次剔除):
  ```python
  for node in box.find_all(['blockquote', 'p', 'div']):
      if node.find('img'):  # 含 img 一律不动
          continue
      # ...再做 selector/文本命中剔除
  ```
  或者**干脆只用 selector 白名单剔**,不用文本命中(本次用户拍板的路线)
- **判定时效**:永不过期(规则逻辑而非依赖)

---

## ⛔ 吃瓜/内容农场站用"通用广告词黑名单"做剔除会误伤正文(2026-10-01 同事故深层原因)

- **错误代码**:`_SEO_HINTS = ('约炮','包养','棋牌','直播','免费看','黄片','杏吧','蜜桃','偷拍','福利','破解','暗网','免费AI','抖阴','魔改短剧')`
- **错误原因**:这套词在普通内容站确实是广告特征,但**在吃瓜/爆料/UGC 内容农场**,这些词就是正文本身的高频关键词——"某网红福利合集"、"直播回放"、"偷拍门"是正常标题/正文,不是广告
- **为何不可再采用**:**按内容性质分类词表**——聚合工具/成人/内容农场不能用同一套黑名单;每个项目的 SEO_HINTS 必须用"该站真实广告样本"喂出来,不能凭感觉拍脑袋
- **替代方案**:
  1. 用词命中剔除时,先抓 100 篇真实正文跑 dry-run,统计每词命中率,>5% 的词直接删出词表
  2. 更稳的做法:**只用 DOM 结构剔除**(selector 白名单),不用文本内容判断
  3. 必须用词命中时,加「含 `<img>` 一律跳过」的硬护栏
- **判定时效**:2026-10-01 实测;吃瓜/内容农场类项目通用

---

## ⛔ 改完 Python 代码忘记 uvicorn 不会自动 reload,跑了半小时才发现(2026-10-01)

- **现象**:19:04 改了 `collector/typecho.py`,但 uvicorn 是 16:21 启动的,`--reload` 没开——后续跑同步用的是**旧规则**,跑完才发现新规则没生效。
- **报错原文**:无报错,是"静默用旧代码"的行为问题(更难发现)
- **错误原因**:uvicorn 默认不监听文件变化;只有 `--reload` 或 watchfiles 才会重启。**改完代码必须显式重启服务**,不能假设它会自动生效
- **为何不可再采用**:
  - 开发时:起 uvicorn 加 `--reload`,或约定"改完 server/collector/ 任何 .py 必须 pkill + 重启"
  - 调试时:改完规则先用 `python -c "from collector import typecho; ..."` 直接调一次,确认行为对了再让服务跑
- **替代方案**:无替代,这是流程纪律
- **判定时效**:uvicorn 默认行为,跨版本通用


---

## 🔶 待验证:同步收尾自动挂备份层(Docker 化前必备)

- **当前推断**:`server/sync.py` 的 `_collect_one_site` 完成后(三站任意一站),调用 `scripts/backup_content.py --source <site> --since-minutes 10`,git commit,可以在不改业务逻辑的前提下建立"每次同步后必有正文备份"的兜底
- **已到哪一步**:思路成型(`scripts/backup_content.py` 模板未写,但参数和路径已想清楚:`data/backup_content/<source>/<article_key>.json`,与 `data/objects/` 同结构)
- **下一步验证动作**:
  1. 写脚本(模板见上文 ✅)
  2. `set -a; . ./.env; set +a; .venv/bin/python scripts/backup_content.py --source mrds --since-minutes 10` 跑一次,`git status` 看新增文件
  3. 接入 `_collect_one_site` 末尾,在 `_audit_gaps()` 之前调用
  4. Docker 启动前必备,否则容器一崩/规则再错又没救
- **为何值得继续**:这次 295 篇正文救回了是因为 MySQL 元数据没动 + 图本体在 RustFS 里独立存;**如果哪天 MySQL 的 images_json 也丢了,救都救不回**。备份层是"代码错了数据还在"的最后一道闸
