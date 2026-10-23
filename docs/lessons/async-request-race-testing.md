# 前端请求竞态:修复模式与确定性测试构造

> 主题:`loadArticles`-式"加载中防重入"早退在高频新入口(搜索框防抖/ESC)出现后丢请求,及竞态的正确测法。

## 结论速览

- **直接可用的修法**:请求代际令牌——每次请求 `reqId = ++state.reqId`,响应落地时 `reqId !== state.reqId` 即丢弃;防重入守卫只对分页生效,reset(切站/搜索/清空)必须插队。
- **适用条件**:vanilla JS、多个交互入口共享同一列表状态的前端;竞态测试用 fetch 拦截"手动挂起+放行",不用固定延迟挤窗口。

---

## ✅ "加载中就 return"的防重入早退,在新增高频入口后丢请求(2026-10-23)

- **为何值得记**:melon-hub 顶栏加搜索功能时,对抗性 code-review 逮出;同类 `if (loading) return` 写法在前端极常见,任何"老功能没毛病、新入口把它打出原型"的场景都可能再遇。评审→修复→回归断言全流程有书面轨迹。
- **现场(根因)**:列表加载函数开头 `if (state.loading) return;` 对所有调用方一视同仁。加搜索后,防抖 300ms 发出的请求在飞时按 ESC 清空,`applySearch('')` 已更新 `state.q`,但 `loadArticles(true)` 被早退丢弃;旧 q 的响应随后落地渲染,meta 用新 `state.q` 拼装——**列表是旧过滤结果、搜索框已空、meta 无搜索后缀,三处永久错位,只能手动再触发**。原代码里快速连点站点 Tab 也会中招,搜索入口只是把毫秒级窗口放大成肉眼可见。
- **最终方案**(web/app.js,可直接抄):

```js
const state = { /* ...原字段... */ reqId: 0 };

async function loadArticles(reset) {
  // 分页连点防重入;reset(切站/搜索/清空/同步后刷新)必须插队,否则竞态错位
  if (state.loading && !reset) return;
  // 请求代际令牌:本次请求发出后若有更新的请求插队,落地即为过期,直接丢弃
  const reqId = ++state.reqId;
  state.loading = true;
  try {
    const q = new URLSearchParams({ limit: state.limit, offset: state.offset });
    if (state.current) q.set('source', state.current);
    if (state.q) q.set('q', state.q);
    const data = await api('/api/articles?' + q);
    if (reqId !== state.reqId) return; // 已有更新的请求接管这次渲染
    // ……正常走渲染(读 state.q 等 live 状态没问题,因为此时本请求就是最新的)……
  } catch (e) {
    if (reqId === state.reqId) meta.textContent = '载入失败:' + e.message;
  } finally {
    if (reqId === state.reqId) state.loading = false;
  }
}
```

- **为什么这样做**:竞态的本质不是"要互斥",而是"新意图必须抢占旧意图"。防重入守卫拦的是重复刷新(分页连点),不该拦意图变更(reset);代际令牌保证"只有最新一次落笔渲染",过期响应静默丢弃且错误文案/loading 清理都不归它管。
- **适用条件**:vanilla JS 无 AbortController 也可;用了 AbortController 的场景可以直接 abort 替代令牌,但令牌更便宜(不用管请求取消的清理分支)。框架接管数据流(React/Vue)时不适用。
- **验证证据**:回归断言 `scripts/ui_search_assert.py` 的 B12(见下条)先拿到真 RED——

```
[FAIL] B12 竞态回归 — 2nd_req_ok=False final_cards=6
reqs=['/api/articles?limit=50&offset=0&q=%E5%90%83%E7%93%9C'] meta='共 6 条'
```

(ESC 的新请求根本没发出、终态 6 卡配"共 6 条"无搜索后缀);修复后同断言转 GREEN,且 1440px/390px 双宽度全套 23 项全过,生产 ce5d0f3 已部署。
- **交叉验证**:对抗性 code-review 子会话(10 角度审查)提出 → 我核实代码路径属实 → TDD RED 复现 → 修复 → GREEN;书面轨迹在 `docs/handoffs/melon-hub.md` 2026-10-23 增量块。单代码仓库、单轮审查收敛,标的不是"多 agent 精粹"。
- **关键步骤**:① 守卫拆两态(pagination 归守卫,reset 放行)② 响应落地前统一过令牌闸 ③ finally 里 `state.loading=false` 也只允许最新请求执行,老请求的 finally 不得抢先复位。
- **易错点**:只丢渲染、忘了 finally/catch 也要判令牌,会出现"老请求把 loading 复位/写错误文案"的次级错位;URLSearchParams 的参数要在请求发出时就拍定(reqId 快照语义),渲染阶段读 live state 只在"确属最新"时安全。

---

## ✅ 竞态测试必须确定性构造:fetch 拦截"挂起-放行",不用固定延迟挤窗口(2026-10-23)

- **为何值得记**:同一 session 里我第一版测试用 `setTimeout 延迟 200ms + sleep 0.45s` 挤竞态窗口,实测**假绿**(被修前的代码也全过)——时序抖动导致 ESC 落在了请求已落地之后,race 根本没被触发。若按"测试过=没问题"交付,评审发现等于被浪费。下一轮写竞态测试时直接抄确定性构造,跳过踩坑。
- **最终方案**(headless Chrome CDP,JS 原文):

```js
// 拦截 /api/articles 的 fetch:记录请求队列,返回永挂 Promise,等人工放行
window.__origFetch = window.fetch; window.__hold = []; window.__reqs = [];
window.fetch = (u, o) => {
  if (!String(u).includes('/api/articles')) return window.__origFetch(u, o);
  window.__reqs.push(String(u));
  return new Promise(res => window.__hold.push(() => window.__origFetch(u, o).then(res)));
};
window.__release = () => { const h = window.__hold.splice(0); h.forEach(f => f()); };
```

测试序列:① 输入触发防抖 → ② 轮询直到 `__reqs` 出现带 `q=` 的请求(**此刻请求确定在飞,恒真,不吃时序**)→ ③ 触发第二次意图(ESC) → ④ 断言 `__reqs` 出现第二个请求且其查询串不带 `q=`(插队证明) → ⑤ `__release()` 放行 → ⑥ sleep ~0.5s 定置后读终态 DOM(卡数/meta)。
- **为什么这样才对**:竞态的三要素是"请求在飞→新意图发生→旧响应落地",任何靠本地服务毫秒级响应+sleep 去撞窗口的写法,窗口位置都会随机器负载漂移;手动挂起把"在飞"变成可断言的持久事实,放行顺序又确定了落地顺序,三个要素全部可控。
- **验证证据**:假绿版本(固定延迟)在 bug 未修时输出 `[ok]`,确定性版本在同一代码上立刻 `[FAIL]`,且 FAIL 详情(请求队列只有 1 条、无第二请求)直接印证根因;修后版本 5 次重跑稳定 GREEN。
- **适用条件**:能拦截 `window.fetch`/`XMLHttpRequest` 的页面环境(headless CDP、Playwright `page.route` 同理)即可;应用代码经全局名调用 fetch 时,加载后补丁仍生效(app.js 是 IIFE,`fetch` 每调用时从全局取)。
- **关键步骤**:挂起列表和请求队列必须是应用无关的独立数组;放行用 `splice(0)` 一次性排空;终态读取必须等"放行后的渲染落定"(sleep 或断言轮询),不许在放行瞬间立即读——放行前后 DOM 可能仍是旧快照,会读出没意义的值。
- **易错点**(同族坑,一并记):时间敏感断言要么做确定性,要么断言**语义阈值**而非精确墙钟。例:验证"回车能单独触发搜索"(此时刻意不发 input 事件、防抖根本没排期),阈值给 1s 区分"有响应/死无响应"完全够;给 250ms 只是在赌负载,慢机/CI 上随机 flaky。

---

## ⛔ 用"固定延迟 + sleep"挤竞态窗口——实测假绿(2026-10-23)

- **现象原文**(被修前的有 bug 代码上,第一版测试输出):

```
[ok] B12 竞态回归:在飞请求期间 ESC 后恢复全量且 meta 无"搜索"残留
```

- **第一版测试写法**(请勿再用):

```js
// fetch 拦截后延迟 200ms,然后"sleep 0.45s 后按 ESC",赌此时请求还在飞
window.fetch = (u, o) => new Promise(r => setTimeout(() => window.__origFetch(u, o).then(r), 200));
// python 侧:await type_input('吃瓜'); await asyncio.sleep(0.45); await type_input('', submit='esc')
```

- **错误原因**:竞态窗口位置 = 防抖 300ms + 延迟 200ms + 本地 RTT ≈ 固定,而"按 ESC 的时机" = sleep(0.45) + 多个 CDP 往返耗时,后者抖动大;实测 ESC 落在了 200ms 延迟之后、请求已落地,`state.loading` 已复位——**race 根本没被触发,有 bug 的代码也全过**。窗口宽度只有 50~150ms 量级,靠 sleep 不可能稳定命中。
- **为何不可再采用**:凡是"靠固定时差撞竞态"的写法在任何机器负载下都不保证命中窗口;命中与否测试自身不可观测(没断言"请求此刻确在飞"),失败时表现为假绿而不是 FAIL——最坏的测试形态。
- **替代方案**:见本文件上方 ✅ 条目(fetch 手动挂起-放行)。
- **判定时效**:基于 2026-10-23 macOS headless Chrome CDP 实测;与时序测试框架(Playwright route 等)无关,属于方法学否决,长期有效。
