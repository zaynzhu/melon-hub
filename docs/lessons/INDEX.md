# 经验库索引

> 排坑、配置、调试类任务开始前先查本索引;条目按主题一文件,✅有现成方案 / 🔶部分可用 / ⛔仅避坑。

| 文件 | 一句话问题 | 状态 | 最近更新 |
|---|---|---|---|
| [image-cipher-static-key-decrypt.md](image-cipher-static-key-decrypt.md) | 图片密文分发站(Typecho ai 插件族)的密钥静态提取与离线批量解密,含"密文首块不能推断密钥分组"等易错点 | ✅ 有现成方案 | 2026-09-29 |
| [feature-feasibility-data-first.md](feature-feasibility-data-first.md) | 聚合/去重类视图功能先用两级量化(精确→模糊)测重合度,数据不支持就挂起 | ✅ 有现成方案 | 2026-09-29 |
| [collect-then-verify-protocol.md](collect-then-verify-protocol.md) | 采集后必校验协议:存量修复≠链路修复(一天三实例);sync 内建四道闸(解密/补缩略图/排队自动续轮消化/终检 gaps),缺口当场亮出;批量任务必须配自动续抓+可见进度 | ✅ 有现成方案 | 2026-09-30 |
| [dev-service-lifecycle-and-timezone.md](dev-service-lifecycle-and-timezone.md) | 开发环境五坑:ZCode 后台任务随会话休眠死掉(探活先行)、日志北京时间 vs settings UTC 跨轨比对必误判、MySQL 保留字 SQLite 测过仍炸(反引号包裹)、StaticFiles 无 Cache-Control 前端改版不生效(no-cache 修法)、webbridge 单 tab 会话不可并发驱动(CLI 抢 tab 致同步挂) | ✅ 有现成方案 | 2026-10-01 |
| [headless-browser-pass-cf.md](headless-browser-pass-cf.md) | 无头 Playwright 直接过 51cg/mrds 的 CF 托管挑战(实测通过,容器化已落地);先查本机已有 Playwright 资产再装;CF 升级后重验 | ✅ 有现成方案 | 2026-10-08 |
| [docker-cloud-compose-deliver.md](docker-cloud-compose-deliver.md) | Docker 化交付完整闭环:云端 Buildx QEMU 跨架构构建、离线 tar 包、NAS 部署排坑(网络池/shm/mem_limit)、browser_fetch 双后端切换、NAS 链路掐 MySQL 长连接→断线自愈、共享 MySQL buffer pool sizing(1G+512M redo,窗口内延迟 24.5s→0.79s) | ✅ 有现成方案 | 2026-10-22 |
| [data-rewrite-safety.md](data-rewrite-safety.md) | 批量改"已入库数据"的安全护栏:RustFS 无版本控制覆盖即丢、重清洗前先抽样验证、CSS 剔除时含 img 节点不删、吃瓜站通用广告词黑名单会误伤正文、改完 Python 必须手动重启 uvicorn | ✅ 有现成方案 | 2026-10-01 |
| [ui-contract-assert.md](ui-contract-assert.md) | 前端改版时 JS 契约核对:id/class/data-* 是暗契约,改 HTML 前先列 JS 用到的全部 selector,改完跑 headless CDP 断言(含行为切换断言,不止 id 存在性) | ✅ 有现成方案 | 2026-10-01 |
| [async-request-race-testing.md](async-request-race-testing.md) | 前端请求竞态:"加载中就 return"的防重入早退在新入口出现后丢请求(修法=请求代际令牌);竞态测试要 fetch 手动挂起-放行的确定性构造,固定延迟挤窗口实测假绿(⛔ 条目) | ✅ 有现成方案 + ⛔ 避坑 | 2026-10-23 |
| [verify-script-safety.md](verify-script-safety.md) | 自写验证脚本两类自伤雷:写数据的脚本缺隔离护栏会经 .env 写死生产(入口硬查三件套缺一拒绝);断言脚本失败分支的 return 跳过尾部退出码逻辑,RED 态 exit 0 骗过 CI | ✅ 有现成方案 | 2026-10-23 |
