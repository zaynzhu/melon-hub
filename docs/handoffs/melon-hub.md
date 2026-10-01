# melon-hub：个人多源吃瓜阅读仪表盘 · 当前交接

## 立即接手

- **目标**：一个界面同时浏览三个内容站的最新内容（黑料不打烊 / 51吃瓜 / 每日大赛），点开条目进"去广告的阅读视图"。完成后可观察结果：本地起服务后，切换 tab 看到三站各自最新列表，点卡片能读到清洗后的正文，重启后数据仍在（DB + RustFS）。
- **下一位角色**：执行（用户已授权启动并按本方案推进）。
- **范围与非目标**：允许做——采集器（配置驱动 + 镜像自动发现）、DB/RustFS 存储、轻后端 API、聚合前端（Tab + 阅读抽屉）。非目标（一期明确不做）——**跨站去重**（用户 2026-09-19 确认"暂时不去重也没事"，数据表预留指纹字段即可）、**登录系统、管理后台**、公开部署（个人自用起步）、绕过站点安全机制的非常规手段。
- **当前状态与第一步**：一期/二期主体已完成（2026-09-30 快照）：三站采集阅读链路、同步面板+应用内定时调度（`server/sync.py`）、采集收尾三道闸（密文图自动解密/hl365 缩略图补/终检 gaps 盘点）全部上线;剩余待办仅 Docker 构建验证（本机无 docker）与挂起的跨站去重。接手第一步：按文末「接手顺序」探活服务并核对 `gaps` 状态,再按任务靶点进对应模块。
- **完成标准（建议，未经用户逐条确认）**：① 三站最新列表在 UI 内可切换浏览；② 点开条目可读去广告正文（缓存命中秒开，未命中现场抓取入库）；③ 服务重启后数据完好（DB + RustFS）；④ 任一站镜像域名变更时，改配置或回家路自动发现即可继续采集。

## 定位与必读

- **项目根**：`/Users/zaynzhu/code/claude code/project/melon-hub/`（本文档相对此根目录）。快照 2026-09-19，目录为空，无 git。
- **上游站点侦察结论（2026-09-19 实测 + Tavily 交叉验证，关键事实已内嵌）**：
  - **hl365.com**＝"黑料不打烊"线路之一；源头主域名 **heiliao.com**（官方 X：@heiliao0；另有 heiliao.su、hlbdy1.com 线路页）。**可直连、无 CF 盾**；WordPress 架构，**RSS `/feed` 已实测**：每页 10 条，含 title/link/pubDate/约 112 字符摘要，**无 content:encoded 全文**（全文需抓文章页 `/archives/<id>.html`）。首页 249KB、61 个 script（广告，不进数据层即可）、列表为 `li.item`。
  - **51cg1.com** = "51吃瓜"的"回家的路"导航页（`/homeway.html`），**Cloudflare 403**，curl 拿不到内容。源头：**51cg.fun**（自称永久地址、需 VPN）+ **wacg4.com**（国内最新入口）；官方 TG：@chiguaa51。可达性未验证。
  - **www.mrds66.com** = "每日大赛"66 号镜像，**CF challenge**。首页 HTML 含 Vue 模板语法（`{{u.username}}`）→ **SPA，必须真实浏览器渲染**。源头候选 **mrds.fun**（自称官网，未验证）；官方 X：@mrds_9527；回家路页 `/ybml.html`（内含最新地址列表 + 邮箱自动推送）——**这就是镜像自动发现的数据源**。
  - 三站互相转载、大量重复内容（用户观察）→ 一期不去重，仅预留指纹字段。
- **姊妹项目（可复用脚本模式，按需阅读）**：`../pixiu-gallery/`——同流派已验证实现：
- **上游侦察原始档案**：`docs/recon-upstream-2026-09-19.md`——三站的完整实测数据、**防丢失地址簿（所有域名/TG/X/回家路页）**、复现命令；本文档引用的关键事实在那里有完整出处，动手前先按第 5 节命令核验时效。
  - `../pixiu-gallery/download_media.py`——图片抓取模板：每主机 2 秒频控、断点续传、失败清单、`R2_BASE` 环境变量。
  - `../pixiu-gallery/sync_data.py`——增量合并 + 上游探测 + 安检拦截（`is_junk_entry`：载荷正则 + id 必须纯数字——上游被注入过的真实教训，采集层建议沿用同款安检）。
  - `../pixiu-gallery/build_image_versions.py`——git 留档生成时间线（本项目暂不需要，列出备查）。
  - `../pixiu-gallery/` 的前端（index.html/app.js/style.css）——Tab、卡片流、抽屉、视图切换、暗色主题的设计语言直接照搬改造。
- **关键约束及规则来源**：
  - 用户全局 CLAUDE.md（接收会话自动加载）：交流用中文；commit 格式 `type: 中文描述`、原子提交；**外部请求间隔 ≥2 秒**；搜索用 `enhanced-tavily-search` skill；真实浏览器任务用 `kimi-webbridge`（**必须先健康检查 → 页面语义操作 → 结束关 session**）。
  - 主模型 GLM 支持读图（用户 2026-09-15 确认），不要调用 TMPI / model-router 绕路。
  - 内容性质：三站均为成人吃瓜/爆料内容农场，涉及真实个人爆料。个人聚合自用 OK；若将来公开部署，需上免责口径并自查法律边界。
  - 凭据红线：**DB 连接串与 RustFS/S3 端点、密钥不写入本仓库**，一律环境变量或本地 `.env`（`.gitignore`），接入时向用户索取。

## 决策与依据

| 决策 | 状态及来源 | 理由／否决方案 | 重新考虑的条件 |
|------|------------|---------------|----------------|
| 一期不做跨站去重（数据表预留指纹字段） | 用户已确认（2026-09-19："暂时不去重也没事"） | 三站重复内容多，但用户优先"能同时浏览" | 用户日后想要"汇总·去重"视图时启用 |
| 混合形态：列表卡片流 + 点开阅读抽屉（正文缓存优先，未命中现场抓） | 用户已确认（2026-09-19："阅读器形式没问题…列表聚合+摘要卡片也挺好，能不能结合一下"） | 浏览快、阅读干净，两边兼得 | 无 |
| 存储 = 数据库（元数据）+ RustFS/S3（图片与清洗正文） | 用户已确认（"我有s3+数据库…数据库+rustfs里"） | 用户自有基建，不堆本地文件；MVP 亦可先 SQLite+docker 卷跑通、后切正式基建（接口层收口存储操作即可平滑切换） | RustFS 不可用时降级本地目录（保留同一套 key 规范） |
| 部署形态 = 每项目一个独立 docker 容器（melon-hub：单容器跑 FastAPI + 前端 + 采集器定时任务，外部连接用户的 DB/RustFS），个人自用 | 用户已确认（2026-09-19："部署一个docker"、"一个项目一个docker"） | 单容器单机自托管，无 compose 编排需求 | 公开部署需求出现时重议（需先过免责与法律自查） |
| 一期视图 = Tab 切换三站；三栏总览与汇总视图二期 | 用户已确认核心目标（"三个站我同时能浏览每个站"），布局形态为模型建议 | 貔貅阁视图切换模式现成 | 用户点名要三栏 Dashboard 时提前 |
| 采集配置驱动 + 回家路页/TG 镜像自动发现 | 用户已确认方向（"后续抓的时候肯定是可配置的"），自动发现为模型建议 | 三站域名常轮换，回家路页/TG 即官方地址发布渠道 | 自动发现不稳定时退回纯手动配置 |
| hl365 数据源 = RSS feed 优先 + 文章页补全文 | 模型建议（RSS 已实测） | feed 字段干净；全文抓取量大但有频控兜底 | feed 摘要足够用时可省文章页抓取 |
| 轻后端 = Python FastAPI 单文件起步 | 模型建议 | 一个 API 文件够起步；采集与后端同语言复用代码 | 用户偏好其他栈时（如 Rust），记录理由即可 |
| 数据库选型 | 待定 | 用户称已有数据库但未说明类型；SQLite 可起步 | 用户告知实际基建时定 |

## 进度与证据

> 2026-09-19 晚更新:MySQL + RustFS 已接入;图片问题已定位(源站加密链路自身失效),详见"图片加密问题"。
>
> **2026-09-19 深夜增量(按用户新要求)**:① 详情页图片停止抓取;② 首页缩略图已解决——51cg/mrds 列表卡自带服务端 base64 明文缩略图,`collect_thumbs`(canvas 压 360px)各采集 40 张入 RustFS,`thumb_object` 列(MySQL/SQLite 自动迁移)+ `_cover` 只用有效缩略图;hl365 无缩略图来源(RSS/首页无图),显示占位;③ 原文链接:`source_url` 用**当前配置域名**拼文章路径,镜像换域名改 sites.yaml 即全站链接自愈,详情抽屉"查看原文 ↗";④ 时间线视图(顶栏 ▦/☰ 切换,日期分组+轴线)+ 三站来源配色(卡片左色条与徽章:hl365 玫红/wacg51 金/mrds 天蓝)。缩略图仅覆盖首页当前渲染条目(约 80%),随每日采集轮换逐步补齐;全部截图验证通过(用户 Chrome 实渲染)。
>
> **2026-09-19 深夜增量(二,接 sess_52a05b97 收尾)**:① `collector/hl365.py --backfill` 历史文章翻页补齐落地并跑通(修复函数内缺 `ObjectStore` 实例的 NameError):列表翻页解析入库 121 篇,正文 curl 逐篇抓**纯文字**(图片为 CDN 密文不入库,前端占位);② 缩略图终态:mrds 118/118 全覆盖、wacg51 96 篇缺 3(275398/275615/275783,不在当前首页卡片,随轮换补齐)、hl365 121 篇全占位(无缩略图来源,设计内);③ **NSFW 内容位置审计(用户 2026-09-19 关切)**:git 仓库 0 图片文件(纯代码/文档/配置),本地 `data/objects/` 344 文件中三站 `img-*.jpg` 抽查全为 CDN 密文头部(`4fe8…`/`093d…`,非 JPEG 魔数,不渲染出内容),真实明文缩略图仅存 RustFS(设计内存储位);④ 热链补图方案确认否决(CORS),真图补齐唯一路线仍是源站恢复后跑 `scripts/fix_images_browser.py`。
>
> **2026-09-19 深夜增量(三,接 sess_2dcea3e7)**:① **hl365 `published_at` 缺陷修复**:根因是列表页时间在 `<span itemprop="datePublished" content="ISO8601">`(Mirages 主题无 `<time>` 元素),原选择器注定取空;`parse_list_html` 改用卡片内微数据提取(`419cdcf`)+ `store.set_published` 窄更新接口(`7c3e828`),111 篇回填完成(列表页 4+5 页 + 3 篇文章页兜底),**全库 published_at 空值清零**;② 知识库 sync:README 补齐命令/时间线/存储现状(`b0c2ab6`),记忆层 upstream-corrections 尾部过期定性已修正(Chrome 图片正常为历史观测、ndhixj 已验证同族、修法已定);③ wacg51/mrds 正文 pending 全量补齐(193 篇,浏览器路线 `--limit 200`)后台进行中,单篇约 40-50 秒,预计 2 小时量级,完成后核对 DB ok/pending 终态;④ 遗留未动:点开未采集条目"现场抓取"、51cg/mrds 定时自动化(launchd)、Docker 构建验证(本机无 docker)、二期三项。
>
> **2026-09-19 深夜增量(四)**:① 双语 README 重写为开源门面版(中文主+英文副,徽章/Roadmap/FAQ/免责声明,`9ed7d7a`),顺带修复 requirements 缺 PyMySQL(`993c04d`)与采集单篇容错缺口(ReadTimeout 击穿循环,`524a7b5`);8787 服务经用户确认停掉(采集不依赖它);② **wacg51/mrds 正文补齐被 CF 拦截,暂停**:首轮跑了 62(wacg51)/9(mrds) 篇后 webbridge daemon evaluate 45s 读超时击穿(已修容错);daemon 重启后 example.com 通路正常,但 51cg1.com 导航"成功"后连 `document.title` 求值也全部挂起——特征为 CF 挑战页反复重建 JS 上下文吞掉扩展求值,判定为今日高频采集后 CF 升级挑战(项目红线:遇验证码即停请示)。**当前终态:wacg51 62/100 ok、mrds 17/125 ok、hl365 121/121 全量完成**;续跑方式:人工过一次挑战/换网络/次日重试,`--limit 200` 增量幂等随时可续。
>
> **2026-09-19 深夜增量(五,补齐全部完成)**:① CF 拦截实际自解(daemon 重启拿新会话后托管挑战自动放行,无需人工),wacg51/mrds 补齐**全部跑完:全库 356 篇三站全 ok、零 pending、零异常**(ok 均有正文对象与发布时间);② 过程中修复三个真实故障并已推送:webbridge daemon 长跑假死(重启+example.com 小样本验证可解)、`fetch_rendered` 分块提取被 CF 过盾后页面重载清空窗口变量(整体重试 `27f83a7`)、51cg 列表页广告 JS 跳转到 mrds 帖子页(navigate 内检测跳走自动拉回 `c131a46`);③ 缩略图终态:mrds 135 篇缺 17、wacg51 100 篇缺 4(均已滚出首页卡片的历史文章,随轮换/`--backfill` 补齐),hl365 全占位(无来源);④ 经验:TaskStop 停串行 shell 链可能留下孤儿 python 继续干活(本次孤儿反而干完了 24 篇),监控时先 `pgrep -f collector.` 查孤儿再启动新任务,避免双进程抢标签页。
>
> **2026-09-20 凌晨增量(二期开工)**:① **三栏总览视图上线**(`298f0cf`):顶栏视图切换新增 ⊞,三站并排各取最新 10 条(站点色标头),点卡片进阅读抽屉;点站点 Tab 自动回到卡片流;窄屏(≤980px)单栏堆叠。IAB 隔离浏览器 DOM 断言验证通过(仅结构断言,不截图不看内容)。② **回家路页镜像自动发现**(`0c88ba8`):`collector/discover.py` 抓 homeway 页 → href 提取候选(TLD 白名单+资源后缀过滤,防 JS 标识符误判)→ 指纹验证(标题标识词+主题结构标记,防蹭名站)→ 默认报告 / `--apply` 时 home 失效才写入(home 自检两次失败才算失效,防 CF 摩擦误报)。实测:**hl365 回家路挖出 3 个真镜像 bury/born/camp.imjurncw.cc 全部指纹通过**(黑料子域名轮换池,经 RSS/文章页/速度复核后已入 mirrors 池 `e6aae8c`,比主站快 2-3 倍,home 保持 hl365.com);51cg/mrds 回家路候选均验证失败(线路池/蹭名站),当前 home 均健康无需变更。首版曾把 JS 标识符当域名、把 CF 摩擦误判为 home 失效,均已修复。**二期剩余:跨站去重视图、Docker 构建验证;launchd 定时待用户确认**。

> **2026-09-20 增量(图片解密突破,三站缩略图 356/356 全覆盖)**:① **推翻"图片真图依赖源站解密链路恢复"旧结论**(上文"受阻"段作废):站内 `decryptImage()` 是 window 全局函数(AES-CBC,密钥硬编码在 `usr/plugins/ai/common/image.*.js` 混淆代码),服务端 requests 取完整密文字节(偶发 200 空体,重试即可)+ 注入页面调该函数 = 真图,**不依赖源站恢复、不依赖年龄门**。列表页解密"失效"实为 IntersectionObserver 未命中(图不在视口),非链路坏。② **成果**:hl365 121/121(列表翻 12 页建卡片图映射 111 篇批量解密 + 文章页头图兜底 1 篇 221515)、mrds 135/135(`--thumbs` 补 54 + 文章页首图补 17)、wacg51 100/100(文章页首图补 4);全部魔数校验,首页 50 篇 cover 接口抽查零空值。③ **固化**:`docs/image-decrypt-playbook.md`(完整原理+踩坑 10 条+复用流程,**换人/换 agent 必读**)+ `docs/webbridge-playbook.md`(工具层陷阱手册:navigate 清窗变量/evaluate 分块 40KB/session 残留)+ `scripts/thumbs_backfill.py`(幂等补抓脚本,清缺单篇实测跑通,PNG 魔数正确)+ `collector/typecho_collector.py` 文档串接。④ mrds/wacg51 文章页正文首图是明文 data:URI(与密文 CDN 不同源),文章页兜底缩略图不用解密;mrds 文章页无 `.post-card`,wait 用 `.post-content`。⑤ **待做**:同一路线可复活 `scripts/fix_images_browser.py` 批量修正文密文图(images_json 里 1800+ 张密文对象)。

> **2026-09-21 复盘(方法论补记,换人/换 agent 接手前必读)**:① **推结论前必查魔数/字节,别信界面**——这次最关键的反转是"curl 200 + content-type image/jpeg 不代表是图"(CDN 加密字节),此前 09-19 交接里"原站正文 JPEG 在用户 Chrome 里也渲染失败"的结论也建立在 nw=0 实测上;每次发现"界面没图"先跑 `head -c 4 file | xxd` 或魔数校验,能排掉一半误判。② **样本量 n=1 的"规律"要警惕**——hl365 列表页解密"不跑"是基于一次实测(过年龄门后 106 张 JPEG 仍 nw=0)推的"链路失效",实际原因是 IntersectionObserver 未命中(图不在视口),与链路无关;**对站点行为的结论至少要两次独立样本验证或用代码机制佐证**。③ **工具层坑与业务层坑分开记**——`webbridge-playbook.md` 管浏览器驱动的坑(navigate/evaluate/session),`image-decrypt-playbook.md` 管站点内容的坑(解密/密文/魔数);混记会导致工具坑被业务现象掩盖,反之亦然。④ **复盘时补漏的坑清单已增到 14 条**(image-decrypt)+ 4 条(webbridge),新增 11 本地库非真相源、12 空体判断、13 正则要 re.S、14 密钥版本会变。

> **2026-09-29 增量(同步面板 + 应用内定时采集上线)**:① **手动同步面板**——顶栏「同步」按钮弹三站复选面板(默认全选),逐站实时状态轮询(`POST /api/sync` + `GET /api/sync/status` 2s 轮询),浏览器站在 daemon 不通时 TCP 预探测快速降级提示,「全部」视图也可用(旧 refresh 接口与"须先选站"限制一并移除)。② **应用内定时调度**(`server/sync.py`,取代 entrypoint shell 循环与 launchd 方案)——FastAPI lifespan 起 daemon 线程 30s tick,双模式独立开关:间隔 N 小时(`sync.interval_hours`,0=关)/每日 HH:MM(`sync.daily_at`,空=关,时区 `MELON_TZ` 默认 Asia/Shanghai),配置存 MySQL settings 表(`get_setting`/`set_setting`,settings.html 设置页可视化修改);定时只调度 hl365;手动与定时共用模块级运行锁(冲突 409/跳过 tick);**首启无 `sync.initialized` 键时采一次并一次写入三计时键防双跑**;保存配置重置计时(间隔=now,每日=清空当日键)。③ **约束**:uvicorn 必须单 worker(多 worker 重复调度);wacg51/mrds 浏览器采集与宿主机 CLI 采集共用同一浏览器 tab,**别同时跑**;Dockerfile 加 `TZ=Asia/Shanghai` + tzdata 依赖。④ 验证:隔离实例(临时 SQLite+8788)首启三键写入、daily_at 设 1 分钟后 tick 精确触发、409/400 校验全过、三站手动同步浏览器路线真跑通。**launchd 待办正式关闭(方案改为应用内调度,Docker 与本地行为一致)。**

> **2026-09-29 增量(密文图回归 + 采集后自动解密根治)**:① 用户报"黑料的图片没了"——根因:09-29 上午批量解密只处理存量 2788 张,当天下午新采文章又落 196 张密文图(`download_images` 只认 HTTP 200 不校验字节)。**存量修复 ≠ 链路修复**,详见 `docs/lessons/collect-then-verify-protocol.md`(采集后必校验协议)。② 存量重跑解密脚本 196/196 零失败;**根治**:`article_img_decrypt.py` 抽出 `auto_decrypt_new()`,sync 采集收尾(hl365 与浏览器站两路线)自动全库魔数盘点(幂等,明文秒过)→密文自动解密→统计 `img_decrypted` 透传状态接口与前端面板("密文图解密 N/M");密钥 JS 用 `MELON_DECRYPT_JS` 环境变量配置(留档 `~/.local/share/melon-hub/`),未配置时密文保留并显式告警。③ 顺带修复:MySQL 保留字 `key` 在 `get_setting` 缺反引号(SQLite 测试漏过的真 bug,用户"hl365咋能没数据"一问拦住,生产 MySQL 读 settings 必炸)。④ 验证:真实链路再采 2 篇新文落 24 张密文,自动解密 24/24 零失败,最近 20 篇 200 张图全明文。

> **2026-09-29 增量(缩略图第二实例 + 缓存坑, sess_f36fadf7 深夜)**:① 用户再报"卡片缩略图没有,正文里有图"——hl365 缩略图 09-20 一次性脚本补齐后新采的 13 篇没人补(RSS 无图),**同一"存量修复≠链路修复"模式第二实例**;存量纯 Python 离线路线补上 13/13(列表映射/文章页兜底+静态密钥解密,不依赖浏览器),根治固化 `thumbs_backfill.backfill_hl365_offline()` + sync 收尾 `_backfill_hl365_thumbs()` 自动补缺(幂等零开销,`thumbs` 统计透传前端)。② **浏览器强缓存坑**:FastAPI StaticFiles 默认无 Cache-Control,前端改版后用户浏览器一直拿旧页面(旧 JS 配新数据导致"看不到图"误报),`NoCacheFiles` 加 `Cache-Control: no-cache`(ETag 协商保留,未变 304)。③ IAB 隔离浏览器对页面 JS 有怪癖(initTabs 抛 null addEventListener,元素全在),与"不渲染 img"同族——**前端页面级验证以 headless Chrome 为准**,IAB 报错先换 headless 复现再定性。④ 验证:hl365 列表 50/50 有封面、cover 直链 200 真 JPEG;headless 全页渲染 50 卡片零报错。

- **存储接入(已完成)**:`.env`(不入库)配置 MELON_DB_URL(mysql://…13306/melon_hub,自动建库)+ MELON_S3_*(RustFS 192.168.50.233:59100,桶 melon-hub 已建并设匿名读)。本地数据已迁移:`scripts/migrate_local_to_remote.py`(57 行→MySQL 零重复,344 对象→RustFS)。采集器/后端已全链路跑通 MySQL+RustFS(列表/详情/图片直链 200 实测)。
- **图片加密问题(2026-09-29 全部解决——缩略图 356/356 + 正文图 2788/2788,见 09-20/09-29 增量块与 `docs/image-decrypt-playbook.md`)**:
  - 三站图片 CDN(hdhwqx/ndhixj)对所有 HTTP 客户端返回**加密字节**(非图片),仅站内 z-image-loader JS 解密;GIF 明文例外。
  - **2026-09-20 突破**:页面全局 `decryptImage(b64)` 函数 + 服务端取密文注入 = 直接解密,详见 `docs/image-decrypt-playbook.md`(原理/踩坑/复用流程),缩略图已三站全覆盖。
  - 站内解密链路依赖:年龄门确认 → IndexedDB 缓存 → Web Worker 下载;实测 worker 下载被 CORS 拦截、缓存库为空——**原站正文 JPEG 在用户 Chrome 里也渲染失败**(106 张仅 12 张 GIF 成功,nw=0 实测),即源站当前对所有人图片也是坏的。
  - 曾成功抓到 1 张真图(过年龄门后视口图,277KB 真 JPEG,FF D8 魔数验证),证明"原站恢复正常时,`scripts/fix_images_browser.py`(借浏览器 blob 取图)路线可用;当前重跑无效(源站链路失效)。
  - 已做前端优雅降级:封面/正文破图替换为占位,界面不受影响(截图确认)。
  - ~~待验证假设:CDN 可能对本 IP 风控(当日数百次采集请求)。建议次日换网络(手机热点)开 hl365.com 看图片是否正常;若正常则换网络重跑修复脚本批量取真图。~~ → 假设已无意义:09-20 起解密不依赖源站链路,09-29 起正文图已全量修复。
- **前端验证**:headless Chrome 截图,列表/卡片/来源/日期正常,占位降级生效(用户 Chrome 中建议直接看,内置浏览器不渲染位图)。
- ~~**受阻**:图片真图获取依赖源站解密链路恢复,非本项目代码问题~~ → **2026-09-20 已突破**,见上方增量记录与 `docs/image-decrypt-playbook.md`。

- **已产出**（git `8cc19c8`→`b138c5b`）：
  - 步骤 1 骨架：目录、`config/sites.yaml`（三站完整配置）、venv、`.env.example`。
  - 步骤 2 hl365 采集器：`collector/hl365.py`（RSS 全文路线,**无需文章页抓取**,见侦察档案第 9.1 节修正）；`collector/fetch.py`（host 级 2s 频控）、`collector/clean.py`、`collector/store.py`（MySQL + RustFS 双驱动,本地 SQLite/目录回退,2026-09-29 加 settings 键值表）。
  - 步骤 3 双站采集器：`collector/typecho.py`（51cg/mrds 共用解析器,两站同套 Typecho 主题）、`collector/browser_fetch.py`（kimi-webbridge 驱动,独立会话 melon-hub-imgfix）、`collector/wacg51.py` / `collector/mrds.py` 入口。
  - 步骤 4 后端：`server/app.py`（FastAPI：sources / articles 列表 / 详情 / 同步与定时配置接口 + `/objects` 静态对象服务 + web 静态托管；同步调度逻辑在 `server/sync.py`,语义表见 09-29 增量块）。
  - 步骤 5 前端：`web/`（Tab 三站切换 + 卡片流 + 全屏阅读抽屉,OLED 暗色,取 pixiu 设计语言;破图优雅降级;同步面板 + settings.html 设置页,2026-09-29）。
  - 迁移/修复脚本：`scripts/migrate_local_to_remote.py`、`scripts/fix_images_browser.py`。
  - Docker：`Dockerfile`/`docker-entrypoint.sh`/`.dockerignore`（每小时 hl365 定时采集 + API,数据全落 `/data` 卷）——本机无 docker,**构建未验证**。
- **已验证**：
  - hl365：首轮入库 10 篇/148 对象；连跑两遍幂等；清洗后零广告残留。51cg 列表 20/正文 13；每日大赛列表 27/正文 8,`--list-only` 幂等。全程无登录墙/验证码。
  - MySQL：melon_hub 库 57 行零重复,采集器直写 MySQL 幂等。RustFS：344 对象上传,匿名读直链 200。后端三接口 + 图片全链路 curl 实测（现读 MySQL/RustFS）。
  - 数据规模：`hl365 10/10、wacg51 20/13、mrds 27/8`（列表/正文,正文 pending 可增量补抓）。
- **实施中发现并修正**：对象 key 前缀 bug（复用 `download_images` 时误用 hl365 前缀）,已修代码并迁移 175 个对象文件 + DB 记录；浏览路线 evaluate/navigate 偶发超时,已加 3 次重试 + 单篇容错；webbridge 会话与用户浏览器抢 tab 导致状态错乱,已改为专用会话 + 专用标签页（新会话首个 navigate 自动 newTab）。
- **二期项(2026-09-30 更新)**：三栏总览(298f0cf)与回家路页定时自动发现(0c88ba8)已完成;跨站去重实测真重复仅 2-3 组,挂起(见 09-29 增量块);同步面板+应用内定时+采集收尾四道闸+排队自动续轮已完成(见 09-29/09-30 各增量块,launchd 方案关闭);Docker 构建验证待办(容器化改造含浏览器方案已立项,见下方 09-30 第三增量块)。

> **2026-09-30 增量(服务生命周期定位 + 排队续轮 + CF 无头实验, sess_f36fadf7)**:① **服务探活协议**——用户报"51吃瓜卡住/状态查询失败"真因是 ZCode 后台任务随会话休眠被收(08:44 优雅退出);"卡住"实为浏览器站正常耗时。**经验入 lessons**(dev-service 四坑文件):探活先行、时间戳双轨(日志北京 vs settings UTC,跨轨比对必误判)、MySQL 保留字、StaticFiles 缓存。macOS 是开发环境**不装 launchd(用户明令)**,Docker 常驻是生产归宿。② **排队消化续轮**(2d56d95):浏览器站同步收尾查 `_has_pending` 自动续抓至清零(每轮 12 篇/上限 6 轮/失败≥2 停),终检 gaps 加 `pending_content` 字段(5a04154,面板显示"正文排队 N 篇")——一次同步=队列清零,回应用户"不要每次弄一半"。③ **CF 无头实验**(lessons/headless-browser-pass-cf.md):Playwright 无头 Chromium 直接过 51cg/mrds 托管挑战(实测 45/46 卡片零拦截)——**容器内塞浏览器让两站全自动的方案前提已验证**,改造范围已向用户交代(镜像 +400MB/内存 +300-500MB/browser_fetch 后端抽象/CF 升级降级路径),待用户拍板动工。④ 当日三站积压全清(pending/缺缩略图/缺正文全零),thumbs_backfill 兜底补 11 篇。

> **2026-10-01 增量(UI v2 + 镜像面板 + 备份层 + 一次大事故的完整处置, sess_01e5796c)**:
> ① **UI 视觉 v2 上线**(1e3e99f / dc4b06e / b9fd2d6):暗色 editorial 阅读向——近黑暖底+衬线中文标题+绿宝石单一主色+三站来源色只留内容层;**首页从"一锅卡片流"改成按日期分章的杂志流**(每天一章节,大日期数字+今天/周三+篇数);首屏第一张自动 featured hero;时间线大字锚点;三栏列头加"今日 +N";全站交互(hover/按下/焦点/reduced-motion)成体系;JS 暗契约(id/class/data-)一条未破。
> ② **设置页新增"站点与镜像"卡片**(1c52c03):`/api/sites/detail` 透传每站 home/mirrors/homeway_pages/origin(只读),前端可视化;**同步失败时 `_collect_source` 自动调 `_discover_advice` 跑一次 discover,把"主站挂了+候选+切换指引"透传到 `/api/sync/status` 显示在面板,不自动改 yaml**(项目红线守住——改采集入口始终人工)。
> ③ **mrds/wacg51 同步收尾自动补漏网缩略图**(933ebcf):`_collect_browser_site` 末尾加 `_backfill_browser_site_thumbs`,扫该站 `thumb_object` 为空的行,复用 `thumbs_backfill.backfill_article_firstimg` 走文章页首图明文路线;9 月 30 日新发现的 mrds 6 篇缺缩略图当场自动补齐。
> ④ **2026-09-30 正文批量重清洗事故(完整处置)**:**根因**——`parse_article` 老 `_SEO_HINTS` 含 `'福利'`/`'直播'` 等词,这些是吃瓜站正文正常关键词,词命中时整段(含 `<img>`)被 decompose,8 张图连带销毁;**用户触发发现**——用户报"详情页图都没了";**处置**——`git reset --hard 1c52c03` 代码回滚到上一稳定状态,**RustFS 无版本控制无法回滚数据**,295 篇 content.json 只能**让采集器跑 `_has_pending` 全部重置后重抓**恢复(wacg51 122/122, mrds 190/193,3 篇是滚动新增);**沉淀**:`docs/lessons/data-rewrite-safety.md` 新增 4 条护栏(RustFS 备份层/重清洗先抽样/CSS 剔除含 img 不删/通用广告词黑名单反模式),`docs/lessons/ui-contract-assert.md` 新建(JS 契约核对),`dev-service` 加第 5 坑(webbridge 单 tab 会话不可并发驱动)。
> ⑤ **正文备份层入库**(a2a53ae):`scripts/backup_content.py` + `data/backup_content/<source>/<article_key>.json` 453 篇首次快照入 git(约 10MB 纯文本);`.gitignore` 从 `data/` 一刀切改列具体子目录,保留 `data/backup_content/` 入库;**任何会覆盖 content.json 的脚本前必须先跑一次备份脚本**,git revert 即回滚。
> ⑥ 当前 commit HEAD=a2a53ae(共 30 余个 commit 未推送);**Docker 化下次做,镜像方案(含浏览器与否)待用户拍板**;webbridge 当前会话干净。

## 剩余步骤与验收

1. **初始化**：`git init`、目录骨架、`config/sites.yaml`（每站：源头、镜像列表、回家路页 URL、解析器名、UA）→ 完成标准：配置能描述三站且域名可换。
2. **hl365 采集器**：RSS 增量拉取（≥2s 频控）→ 文章页抓正文（正文清洗：去 script/iframe/广告节点，保留标题/正文/图）→ 图片下载入 RustFS、元数据入 DB → 完成标准：连续跑两遍增量幂等（无重复行/重复对象）。
3. **51吃瓜 / 每日大赛采集器**：kimi-webbridge 真实浏览器过盾（健康检查 → 打开"回家路"页解析最新域名 → 语义滚动/读取列表 → 保存渲染后 HTML → 离线解析同 schema）→ 完成标准：两站各产出一份清洗后的列表 JSON 入库；遇登录墙/验证码即停并向用户请示。
4. **轻后端**：FastAPI（列表接口按 source 过滤、详情接口读 DB/RustFS、未命中正文触发按需抓取）→ 完成标准：本地起服务，`curl` 三接口返回真实数据。
5. **前端**：pixiu 骨架改造——Tab 三站切换 + 卡片流 + 全屏阅读抽屉（正文优先 DB/RustFS 命中，渲染时图片指向 RustFS 公共地址）→ 完成标准：`http.server`/后端起站，三站可切换浏览、点开可读、无广告元素。
6. **（二期）** 三栏总览模式、跨站去重视图、回家路页定时自动发现（一期先手动改配置即可用）。
- 每步验证：采集脚本幂等跑两遍对比；`git diff --check`；后端接口 curl 抽查；前端 Playwright 快照验证（数值/文本断言，不用截图）。
- 可选技能：`kimi-webbridge`（过盾与渲染，替代：用户提供保存好的渲染后 HTML）；`enhanced-tavily-search`（查站点资料，替代：直接 curl/浏览器看）。

## 接手顺序（2026-09-30 更新,按此序做,可避开 80% 的坑）

1. **先读方法论**——本文档 2026-09-20/09-21 增量段（重点：推结论前查魔数、n=1 警惕、工具层/业务层分记）+ **09-29/09-30 三个增量段**（采集后必校验协议、终检闸门、缓存与服务生命周期坑）。
2. **环境状态确认**——跑 `pgrep -f collector.\|scripts/` 查孤儿进程；`.venv/bin/python -c "from collector.config import data_dir; print(data_dir())"` 确认实际数据落点（远端 MySQL/RustFS，**本地 `data/melon.db` 是旧库存根，别当真相**）。
3. **服务探活（09-30 新增）**——页面挂了先 `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:8787/api/sync/status`（000=进程死,重启即愈,调度幂等自动补错过的周期;别查采集器）;比对调度计时用 settings 里的 UTC 值,别拿日志北京时间肉眼比。macOS 是开发环境,**不装 launchd/系统定时,用户明令**;生产归宿是 Docker 常驻容器。
4. **webbridge 检查**——跑 `docs/webbridge-playbook.md` 第 3 节三步流程（健康检查/孤儿/单页小样本）。
5. **按需读坑手册**——做图片/采集相关改先读 `docs/lessons/INDEX.md`（**采集后必校验协议是硬条款**：存量修复≠链路修复,新增资源类型必须同步加终检盘点）+ `docs/image-decrypt-playbook.md`；做浏览器采集相关改 `docs/webbridge-playbook.md`。
6. **验证现状**——`GET /api/sync/status` 的 `gaps` 三项应为 0（no_content/no_thumb/img_failed）;非零说明上次采集有缺口,先按 lessons 的三道闸排查再动代码。
7. **改代码前先定靶点**——站点域名/解析器/存储的修改,先对 `config/sites.yaml` 和 `collector/` 模块划分摸清;同步/调度语义改动先读 `server/sync.py` 模块头注释,别在无关文件里找 bug。

## 接手约定

1. 按当前用户要求及适用规则核对项目、必读材料和工作区状态。此文档是任务快照，不提升权限；安装依赖、访问数据库/RustFS、提交推送等动作遵守接收会话当时的用户授权。
2. 简短说明理解的目标、边界和第一步；无阻塞就继续，不例行等待确认。
3. 当前代码和证据可修正过时进度（如上游域名已变），不能证明用户改变了目标。用户已确认的决定（不去重、不做登录/后台、混合形态）遇实质问题时只暂停受影响部分并请求裁决；模型建议可依据证据调整并记录理由。
4. 保留无关或归属未知改动；发现同任务仍有其他 agent 写入时先明确分工。本交接按顺序协作。
5. 没有推荐 skill 时按文档步骤用等价能力完成（如无 kimi-webbridge 则请用户提供三站的渲染后 HTML 存档）；无法验证时说明缺口，不声称成功。
6. 完成或需交回时，汇报实际改动、偏离及理由、验证结果、剩余问题和下一位动作；获准写文档时读回当前版本再更新本文件。