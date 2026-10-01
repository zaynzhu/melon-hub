# 经验库索引

> 排坑、配置、调试类任务开始前先查本索引;条目按主题一文件,✅有现成方案 / 🔶部分可用 / ⛔仅避坑。

| 文件 | 一句话问题 | 状态 | 最近更新 |
|---|---|---|---|
| [image-cipher-static-key-decrypt.md](image-cipher-static-key-decrypt.md) | 图片密文分发站(Typecho ai 插件族)的密钥静态提取与离线批量解密,含"密文首块不能推断密钥分组"等易错点 | ✅ 有现成方案 | 2026-09-29 |
| [feature-feasibility-data-first.md](feature-feasibility-data-first.md) | 聚合/去重类视图功能先用两级量化(精确→模糊)测重合度,数据不支持就挂起 | ✅ 有现成方案 | 2026-09-29 |
| [collect-then-verify-protocol.md](collect-then-verify-protocol.md) | 采集后必校验协议:存量修复≠链路修复(一天三实例);sync 内建四道闸(解密/补缩略图/排队自动续轮消化/终检 gaps),缺口当场亮出;批量任务必须配自动续抓+可见进度 | ✅ 有现成方案 | 2026-09-30 |
| [dev-service-lifecycle-and-timezone.md](dev-service-lifecycle-and-timezone.md) | 开发环境五坑:ZCode 后台任务随会话休眠死掉(探活先行)、日志北京时间 vs settings UTC 跨轨比对必误判、MySQL 保留字 SQLite 测过仍炸(反引号包裹)、StaticFiles 无 Cache-Control 前端改版不生效(no-cache 修法)、webbridge 单 tab 会话不可并发驱动(CLI 抢 tab 致同步挂) | ✅ 有现成方案 | 2026-10-01 |
| [headless-browser-pass-cf.md](headless-browser-pass-cf.md) | 无头 Playwright 直接过 51cg/mrds 的 CF 托管挑战(实测通过,容器内自动采集可行);先查本机已有 Playwright 资产再装;CF 升级后重验;容器长期稳定性待验证 | 🔶 部分可用 | 2026-09-30 |
| [data-rewrite-safety.md](data-rewrite-safety.md) | 批量改"已入库数据"的安全护栏:RustFS 无版本控制覆盖即丢、重清洗前先抽样验证、CSS 剔除时含 img 节点不删;对象存储 ≠ 版本控制,备份层要单独 git 化 | ✅ 有现成方案 | 2026-10-01 |
