# 图片密文分发站:密钥静态提取与离线批量解密

> **结论速览**:站内解密 JS 未重混淆时(字符码串 `cc("数字_数字_...")` 模式),AES 密钥/IV 可正则静态提取,密文对象已在自有存储时纯 Python 离线批量解密——比浏览器逐张注入快约 20 倍。
> **适用条件**:站点用 Typecho `ai` 插件族(`usr/plugins/ai/common/image.*.js`);密文字节已采集入库(无需再访问 CDN);仓库公开时密钥值必须运行时提取、绝不硬编码。

## ✅ 站内 JS 混淆轻度时,AES 密钥可直接从 JS 静态提取,批量解密不需要浏览器(2026-09-29)

- **为何值得记**:浏览器逐张注入解密路线(`decryptImage` 喂密文、40KB 分块)对 2788 张图估 4-7 小时;静态提取 + pycryptodome 离线解密全程约 20 分钟,且不碰外站、不依赖用户浏览器在线。识别"JS 未重混淆"只花了 2 轮探查(grep 字符串模式 + 看 IIFE 参数),复用后零探索成本。
- **最终方案**:固化脚本 `scripts/article_img_decrypt.py`(三阶段:盘点→备份硬闸门→解密),完整原理与操作序列见 `docs/image-decrypt-playbook.md` 第 8 节(权威源,不在此复制)。核心提取模式:

  ```python
  candidates = re.findall(r'cc\("([0-9_]+)"\)', js_text)
  decoded = [''.join(chr(int(x)) for x in c.split('_')) for c in candidates]
  # 过滤 len==16 且 printable,必须恰好 2 个(key+IV,代码顺序 key 在前),多了少了都人工确认不猜
  pt = AES.new(key, AES.MODE_CBC, iv).decrypt(cipher)  # PKCS7 手工去填充,填充不合法判失败
  ```

- **为什么这样做**:该插件族把密钥/IV 以字符码下划线串形式存在 Web Worker 的 `decryptjs` 函数里(规避明文 grep,但没做真混淆);`decryptImage(b64)` 页面路线的本质就是 CryptoJS AES-128-CBC,Keys/IV 均为 16 字节 ASCII。三站(hl365/mrds/wacg51)JS 文件字节有差异但提取结果同组(共用插件模板)。
- **适用条件**:JS 字符码串模式存在(站方换版改名 `cc` 后回退模式:在 `AES.decrypt` 调用点 ±800 字符窗口内找任意 `"数字_数字_..."` 串);密文对象已在本地/自有对象存储;Python 需 pycryptodome(项目 requirements 已含)。站方真重混淆或换非 AES 算法时此路失效,回退页面 `decryptImage` 路线(playbook 第 2 节)。
- **验证证据**:① openssl 命令行与 pycryptodome 双路线解密三站样例全过(PKCS7 填充校验 + JPEG 魔数 `ffd8ffdb`/`ffd8ffe0`);② 小批量 12/12(备份完好 + RustFS 直链真图);③ 全量 2788/2788 零失败,库存复查零密文残留,三站直链抽查 6/6(2774 JPEG + 14 PNG)。
- **交叉验证**:单 agent + 1 轮红队审查(adversarial-review)收敛,吸收两条硬闸门入方案(备份先行、密钥不入库);证据入口:`docs/image-decrypt-playbook.md` 第 8 节、`docs/handoffs/melon-hub.md` 2026-09-29 增量块。
- **关键步骤**:① 盘点(全量读对象验魔数分类,幂等基础)→ ② 密文全量备份并逐一校验大小,**未 100% 通过不进覆盖阶段** → ③ 首张试解即失败判定密钥错误整体中止(防几千张白跑),通过后单篇失败保留密文计数。
- **易错点**:
  - **密文首块模式不能推断密钥分组**——实测 hl365/wacg51 样例首块 `4fe8…`、mrds `3eaa…`,据此误推"两个密钥组",实际三站同一组:首块 = 加密(明文首块),明文头部 JFIF/Exif 差异就会造成首块不同。分组判定以实际解密 + 魔数为准。
  - **密钥值绝不硬编码进任何被 git 跟踪的文件**(仓库推 GitHub = 公开站方保护机制);脚本运行时从 JS 提取,站方换版(curl 新 JS 重跑)自动自适应。
  - `.jpg` 对象 key 下解出 PNG:浏览器按字节嗅探渲染,不必改 key、不必动 DB(14 张实测);同 key 原地覆盖使 images_json/content 零改动。
  - 浏览器自动化依赖(webbridge)瞬断(`no extension connected`,daemon 活着但扩展没连)不阻塞此路线——这恰是静态路线的衍生优势。

## ⛔ 无失败路线记录

本条目沉淀时无已确认失败的尝试。注意:浏览器逐张注入路线(本文件主题的旧方案)不是失败而是慢,且已在 playbook 第 2 节完整记录,仍是无浏览器备选的对偶路线。
