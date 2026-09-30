# 无头浏览器过 Cloudflare 托管挑战:51吃瓜/每日大赛容器内自动采集可行

## 结论速览

- **方案**:Playwright 无头 Chromium(`launch(headless=True)` + 常规 Chrome UA)直接访问 51cg1.com / mrds66.com,CF 托管挑战自动放行(2026-09-30 实测 45/46 张列表卡片,零挑战残留);容器内自动采集可行,无需 stealth 补丁。
- **适用条件**:仅 CF 托管挑战(JS 质询)级别站点、低频采集(≥2s 频控,12h 一次);**CF 升级 Turnstile/无头检测后此结论作废,重跑本实验验证**;遇真验证码墙仍按红线即停。

## ✅ 无头 Playwright 过两站 CF 挑战(2026-09-30)

- **环境**:macOS(darwin 25.6.0 arm64)、playwright 1.5x(vdl 项目 .venv, Python 3.12)、chromium-1234 现有缓存(包要求 1243,`executable_path` 指定旧版可执行文件可用)
- **为何值得记**:决定「Docker 容器内自动采集 wacg51/mrds」是否立项的关键前提;此前两站只能借宿主机 kimi-webbridge 真实浏览器,Mac 合盖即断,用户明确要容器自治。
- **最终方案**(实验原文,可直接复制):
  ```python
  from playwright.sync_api import sync_playwright
  CHROME = '<ms-playwright>/chromium-1234/chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing'
  with sync_playwright() as p:
      browser = p.chromium.launch(headless=True, executable_path=CHROME)
      ctx = browser.new_context(
          user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                     'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
          viewport={'width': 1280, 'height': 800})
      page = ctx.new_page()
      page.goto('https://51cg1.com/', timeout=45000, wait_until='domcontentloaded')
      page.wait_for_timeout(8000)  # 留 CF 质询放行时间
      # 判据:.post-card 列表卡片 > 0 = 过盾;#challenge-running/.cf-turnstile 残留 = 被拦
  ```
- **为什么这样做**:CF 托管挑战是无交互 JS 质询,真浏览器内核(Playwright 的 Chromium 就是完整 Chrome for Testing)执行质询即放行,与是否 headless 无关——本项目两站历史上也无验证码墙记录(遇验证码即停是红线)。
- **验证证据**(2026-09-30):
  ```
  wacg51(51吃瓜): title='51吃瓜网 - 今日吃瓜爆料资讯平台,热门黑料内幕每日更新' | post-card=45 | 挑战残留=0 => 过盾成功
  mrds(每日大赛): title='每日大赛 - 实时吃瓜爆料平台 | 黑料每日更新...' | post-card=46 | 挑战残留=0 => 过盾成功
  ```
- **交叉验证**:单 agent 单次实验;一次访问/站,样本 n=1,**建议容器化落地时先连续跑 2-3 天观察稳定性再宣称生产可用**;证据入口:本条目 + 2026-09-30 会话实验输出。
- **关键步骤**:launch(headless=True) → 常规 UA(无 HeadlessChrome 字样)→ domcontentloaded 后**等 8 秒**给质询放行时间 → 查 `.post-card` 与挑战节点判据。
- **易错点**:
  - playwright 包版本与 ms-playwright 浏览器缓存差一版会报 Executable doesn't exist → `executable_path` 指定现有版本即可,不必重下;
  - macOS 无 `timeout` 命令(zsh 报 command not found),脚本内自带超时即可;
  - 判据别用 HTTP 状态码:挑战页也是 200/403 混杂,必须查 DOM 特征。

## ✅ 本机 Playwright 资产:先查再装,别重复安装(2026-09-30)

- **环境**:macOS(darwin 25.6.0 arm64)
- **为何值得记**:做无头实验前用户一句"先别装,我怀疑 Mac 上有"——全查一遍后**零安装完成实验**;下次任何要 Playwright 的实验直接复用,省 ~百 MB 下载与依赖排错。
- **最终方案**(查资产命令,可直接复制):
  ```bash
  # 1) 浏览器缓存(Playwright 装过就会留在这)
  ls ~/Library/Caches/ms-playwright/          # chromium-*/chromium_headless_shell-*/ffmpeg-*
  # 2) Python 包(常见于其他项目 venv,本机 vdl/douyin-downloader 各有一份)
  for d in <项目根>/*/.venv/lib/python*/site-packages; do [ -d "$d/playwright" ] && echo "FOUND: $d/playwright"; done
  # 3) 用别的 venv 跑实验
  cd <有 playwright 的项目> && .venv/bin/python <实验脚本>
  ```
- **为什么这样做**:Playwright 的浏览器是全局缓存共享(~/Library/Caches/ms-playwright),包是项目级——只要任何 venv 有包、缓存有浏览器,就能跑,无需在当前项目装。
- **适用条件**:仅 macOS 本机;查不到再走正常安装,别硬绕。
- **验证证据**:2026-09-30 查得 chromium-1223/1234 + headless_shell 两版本缓存;`vdl`/`douyin-downloader` 的 .venv(Python 3.12)各含 playwright 包;用 vdl venv 完成两站 CF 实验,零安装。
- **交叉验证**:单 agent 单次;用户先验提醒(用户是资产位置的第一信息源,先问一句能省整轮探索)。
- **易错点**:
  - venv 包版本与缓存浏览器版本会错位(包要 1243,缓存是 1234)→ `launch(executable_path=<现有 chrome 路径>)` 指定即可,别为对齐版本重新下载;
  - `mdfind`/全盘 `find ~/` 查包巨慢(跑了一轮近 2 分钟未完成),用**定点查项目 venv**的 for 循环秒出。

## 🔶 容器内长期稳定性待验证(2026-09-30)

- **当前推断**(事实与推断分写):过盾本身已验证;但**容器环境**(数据中心/家庭内网 IP、Linux 特征、无 GUI)与 Mac 实验环境不同,CF 对 IP 信誉的加权可能不同——nas 内网出口 IP 与 Mac 相同(同一家庭宽带),此风险低但未实测。
- **已到哪一步**:Mac 无头实验两站通过;容器化改造(镜像 + browser_fetch 后端抽象)未动工。
- **下一步验证动作**:Docker 镜像内跑同款单页实验(容器起 → 无头访问两站 → 查 .post-card),通过后再接采集链路;连续观察 2-3 天定时采集成功率。
- **为何值得继续**:用户最终目标"容器自己拉自己排队",这是两站全自动的唯一路径。

## 镜像与部署要点(容器化时用)

- 基础镜像:`python:3.12-slim` + `pip install playwright` + `playwright install --with-deps chromium`(约 +400MB);
- 部署目标为极空间 Z4S(x86_64,内存有限):Chromium 常驻约 +300-500MB 内存,建议采集完释放(非常驻 browser 进程);
- 失败兜底:CF 升级把无头拦了 → 该站自动跳过、面板如实报错,队列留待下次,终检闸门亮缺口,不在容器内重试撞盾。