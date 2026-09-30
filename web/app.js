// melon-hub 前端:站点 Tab + 卡片流 + 全屏阅读抽屉
(() => {
  const state = { sources: [], current: '', offset: 0, limit: 50, loading: false, view: 'cards', cache: [] };

  const $ = (id) => document.getElementById(id);
  const flow = $('card-flow'), meta = $('feed-meta'), loadMore = $('load-more');

  async function api(path, opts) {
    const resp = await fetch(path, opts);
    if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`);
    return resp.json();
  }

  function fmtDate(iso) {
    if (!iso) return '';
    return iso.slice(0, 10).replaceAll('-', '/');
  }

  function sourceName(id) {
    const s = state.sources.find((x) => x.id === id);
    return s ? s.name : id;
  }

  // ---- Tab ----
  async function initTabs() {
    state.sources = await api('/api/sources');
    state.sources.unshift({ id: '', name: '全部' });
    const tabs = $('site-tabs');
    for (const s of state.sources) {
      const btn = document.createElement('button');
      btn.className = 'site-tab';
      btn.textContent = s.name;
      btn.dataset.source = s.id;
      btn.addEventListener('click', () => switchTab(s.id));
      tabs.appendChild(btn);
    }
    // 同步面板:三站复选默认全选,开始后逐站显示状态
    initSyncPanel();
  }

  // ---- 同步面板 ----
  const syncState = { open: false, polling: null, done: false };

  function initSyncPanel() {
    const backdrop = $('sync-backdrop');
    const sitesWrap = $('sync-sites');
    for (const s of state.sources.filter((x) => x.id)) {
      const row = document.createElement('label');
      row.className = 'sync-site';
      row.dataset.source = s.id;
      const box = document.createElement('input');
      box.type = 'checkbox';
      box.checked = true;
      const name = document.createElement('span');
      name.className = 'sync-site-name';
      name.textContent = s.name;
      const status = document.createElement('span');
      status.className = 'sync-site-status';
      status.textContent = '';
      row.append(box, name, status);
      sitesWrap.appendChild(row);
    }
    $('sync-btn').addEventListener('click', () => {
      backdrop.classList.remove('hidden');
      syncState.open = true;
      refreshSyncStatus();
    });
    $('sync-close').addEventListener('click', closeSyncPanel);
    backdrop.addEventListener('click', (e) => {
      if (e.target === backdrop) closeSyncPanel();
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && syncState.open) closeSyncPanel();
    });
    $('sync-start').addEventListener('click', startSync);
  }

  function closeSyncPanel() {
    $('sync-backdrop').classList.add('hidden');
    syncState.open = false;
    clearInterval(syncState.polling);
    syncState.polling = null;
    if (syncState.done) {
      syncState.done = false;
      loadArticles(true); // 同步有产出时刷新当前列表
    }
  }

  async function refreshSyncStatus() {
    let st;
    try {
      st = await api('/api/sync/status');
    } catch (e) {
      $('sync-note').textContent = '状态查询失败:' + e.message;
      return;
    }
    const rows = document.querySelectorAll('.sync-site');
    const bySource = {};
    for (const r of st.results ? Object.entries(st.results) : []) bySource[r[0]] = r[1];
    let anyDone = false;
    for (const row of rows) {
      const src = row.dataset.source;
      const el = row.querySelector('.sync-site-status');
      const res = bySource[src];
      if (!res) {
        el.textContent = '未选';
        el.className = 'sync-site-status muted';
        continue;
      }
      if (res.status === 'running') {
        el.textContent = '⏳ 进行中…';
        el.className = 'sync-site-status running';
      } else if (res.status === 'ok') {
        const stats = res.stats || {};
        const LABELS = { new: '新增', updated: '更新', skipped: '跳过', done: '正文', failed: '失败' };
        const parts = Object.entries(stats).map(([k, v]) => {
          if (k === 'img_decrypted') {
            const d = v || {};
            return d.cipher ? `密文图解密 ${d.ok}/${d.cipher}` : null;
          }
          if (k === 'thumbs') {
            const t = v || {};
            return t.missing ? `缩略图补 ${t.ok}/${t.missing}` : null;
          }
          return `${LABELS[k] || k} ${v}`;
        }).filter(Boolean);
        const gaps = res.gaps || {};
        const GAP_LABELS = {
          pending_content: '正文排队中',
          no_thumb: '缺缩略图',
          img_failed: '图下载失败',
        };
        const gapText = Object.entries(gaps)
          .filter(([, n]) => n > 0)
          .map(([k, n]) => {
            if (k === 'pending_content') {
              return `正文排队 ${n} 篇(每轮 12 篇,再同步继续)`;
            }
            return GAP_LABELS[k] + ' ' + n;
          })
          .join(' · ');
        el.textContent = '✅ ' + (parts.join(' · ') || '成功') + (gapText ? ` · ${gapText}` : '');
        el.className = 'sync-site-status ok';
        anyDone = true;
      } else if (res.status === 'pending') {
        el.textContent = '⏸ 排队中';
        el.className = 'sync-site-status muted';
      } else {
        el.textContent = '❌ ' + res.error;
        el.className = 'sync-site-status error';
        anyDone = true;
      }
    }
    const note = $('sync-note');
    if (st.running) {
      note.textContent = st.trigger === 'schedule'
        ? '定时采集中,完成后可再手动同步…'
        : '采集进行中…浏览器站单站约需数分钟,可关闭面板后台继续';
    } else {
      note.textContent = '空闲';
    }
    syncState.done = anyDone && !st.running;
  }

  async function startSync() {
    const chosen = [...document.querySelectorAll('.sync-site input:checked')]
      .map((el) => el.closest('.sync-site').dataset.source);
    if (!chosen.length) return;
    try {
      await api('/api/sync', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ sources: chosen }),
      });
      $('sync-note').textContent = '已开始…';
    } catch (e) {
      $('sync-note').textContent = '启动失败:' + e.message;
      return;
    }
    refreshSyncStatus();
  }

  // 面板打开期间 2 秒轮询状态
  setInterval(() => {
    if (syncState.open) refreshSyncStatus();
  }, 2000);

  async function switchTab(source) {
    state.current = source;
    // 三栏总览展示全部站点,点站点 Tab 时回到该站的卡片流
    if (state.view === 'columns') {
      state.view = 'cards';
      document.querySelectorAll('.view-btn').forEach((b) => {
        b.classList.toggle('active', b.dataset.view === 'cards');
      });
    }
    document.querySelectorAll('.site-tab').forEach((b) => {
      b.classList.toggle('active', b.dataset.source === source);
    });
    state.offset = 0;
    flow.innerHTML = '<div class="card-skeleton"></div><div class="card-skeleton"></div><div class="card-skeleton"></div>';
    await loadArticles(true);
  }

  // ---- 视图切换(卡片流 / 时间线) ----
  document.querySelectorAll('.view-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.view-btn').forEach((b) => b.classList.remove('active'));
      btn.classList.add('active');
      state.view = btn.dataset.view;
      render();
    });
  });

  function render() {
    if (state.view === 'timeline') renderTimeline(state.cache);
    else if (state.view === 'columns') renderColumns();
    else renderCards(state.cache);
  }

  // ---- 三栏总览(三站并排,各取最新若干条) ----
  const COLUMN_LIMIT = 10;

  async function renderColumns() {
    flow.className = 'tri-view';
    loadMore.classList.add('hidden');
    const sources = state.sources.filter((s) => s.id);
    if (!sources.length) return;
    flow.innerHTML = sources.map(() => (
      '<div class="tri-col"><div class="card-skeleton"></div><div class="card-skeleton"></div></div>'
    )).join('');
    meta.textContent = `三栏总览 · 每站最新 ${COLUMN_LIMIT} 条 · 点卡片阅读`;
    const lists = await Promise.all(sources.map((s) =>
      api('/api/articles?' + new URLSearchParams({ source: s.id, limit: COLUMN_LIMIT, offset: 0 }))
        .then((d) => d.articles)
        .catch(() => [])
    ));
    if (state.view !== 'columns') return; // 载入期间用户已切走视图
    flow.innerHTML = '';
    sources.forEach((s, i) => {
      const col = document.createElement('div');
      col.className = 'tri-col';
      col.dataset.source = s.id;
      const head = document.createElement('div');
      head.className = 'tri-col-header';
      const name = document.createElement('span');
      name.className = 'tri-col-name';
      name.textContent = s.name;
      const count = document.createElement('span');
      count.className = 'tri-col-count';
      count.textContent = `${lists[i].length} 条`;
      head.append(name, count);
      col.appendChild(head);
      for (const a of lists[i]) col.appendChild(renderCard(a));
      flow.appendChild(col);
    });
  }

  function renderCards(articles) {
    flow.className = 'card-flow';
    flow.innerHTML = '';
    for (const a of articles) flow.appendChild(renderCard(a));
    if (!articles.length) flow.innerHTML = '';
  }

  function renderTimeline(articles) {
    flow.className = 'timeline';
    flow.innerHTML = '';
    let lastDate = '';
    for (const a of articles) {
      const date = (a.published_at || '').slice(0, 10);
      if (date !== lastDate) {
        lastDate = date;
        const marker = document.createElement('div');
        marker.className = 'tl-date';
        marker.dataset.source = a.source;
        marker.innerHTML = `<span class="tl-dot"></span><span>${fmtDate(a.published_at)}</span>`;
        flow.appendChild(marker);
      }
      const item = document.createElement('div');
      item.className = 'tl-item';
      item.dataset.source = a.source;
      const time = document.createElement('span');
      time.className = 'tl-time';
      time.textContent = (a.published_at || '').slice(11, 16) || '--:--';
      const body = document.createElement('div');
      body.className = 'tl-body';
      const title = document.createElement('div');
      title.className = 'tl-title';
      title.textContent = a.title;
      const foot = document.createElement('div');
      foot.className = 'tl-foot';
      const tag = document.createElement('span');
      tag.className = 'card-source';
      tag.textContent = sourceName(a.source);
      foot.appendChild(tag);
      body.append(title, foot);
      item.append(time, body);
      item.addEventListener('click', () => openReader(a));
      flow.appendChild(item);
    }
  }

  // ---- 卡片流 ----
  async function loadArticles(reset) {
    if (state.loading) return;
    state.loading = true;
    loadMore.classList.add('hidden');
    try {
      const q = new URLSearchParams({ limit: state.limit, offset: state.offset });
      if (state.current) q.set('source', state.current);
      const data = await api('/api/articles?' + q);
      if (reset) {
        state.cache = [];
        flow.innerHTML = '';
      }
      state.cache = state.cache.concat(data.articles);
      meta.textContent = `共 ${data.total} 条${state.current ? ' · ' + sourceName(state.current) : ''}`;
      render();
      loadMore.classList.toggle('hidden', state.cache.length >= data.total);
      if (!state.cache.length) {
        meta.textContent = '暂无数据 — 点击"刷新"拉取,或先运行采集器';
      }
    } catch (e) {
      meta.textContent = '载入失败:' + e.message;
    } finally {
      state.loading = false;
    }
  }

  function renderCard(a) {
    const card = document.createElement('div');
    card.className = 'card';
    card.dataset.source = a.source;

    let cover;
    if (a.cover) {
      cover = document.createElement('img');
      cover.className = 'card-cover';
      cover.loading = 'lazy';
      cover.src = a.cover;
      cover.addEventListener('error', () => {
        const ph = document.createElement('div');
        ph.className = 'card-cover placeholder';
        ph.textContent = '🍈';
        cover.replaceWith(ph);
      }, { once: true });
    } else {
      cover = document.createElement('div');
      cover.className = 'card-cover placeholder';
      cover.textContent = '🍈';
    }

    const body = document.createElement('div');
    body.className = 'card-body';
    const title = document.createElement('div');
    title.className = 'card-title';
    title.textContent = a.title;
    const summary = document.createElement('div');
    summary.className = 'card-summary';
    summary.textContent = a.summary || '';
    const foot = document.createElement('div');
    foot.className = 'card-foot';
    const tag = document.createElement('span');
    tag.className = 'card-source';
    tag.textContent = sourceName(a.source);
    const date = document.createElement('span');
    date.className = 'card-date';
    date.textContent = fmtDate(a.published_at);
    foot.append(tag, date);
    body.append(title, summary, foot);
    card.append(cover, body);

    card.addEventListener('click', () => openReader(a));
    return card;
  }

  // ---- 阅读抽屉 ----
  async function openReader(a) {
    const backdrop = $('reader-backdrop');
    backdrop.classList.remove('hidden');
    $('reader-source').textContent = sourceName(a.source);
    $('reader-date').textContent = fmtDate(a.published_at);
    const origin = $('reader-origin');
    if (a.source_url) {
      origin.href = a.source_url;
      origin.classList.remove('hidden');
    } else {
      origin.classList.add('hidden');
    }
    $('reader-title').textContent = a.title;
    const content = $('article-content');
    content.innerHTML = '<div class="reader-empty">载入正文中…</div>';
    $('reader-body').scrollTop = 0;
    try {
      const detail = await api(`/api/articles/${a.source}/${a.article_key}`);
      content.innerHTML = detail.html; // 后端已清洗,仅保留干净正文
    } catch (e) {
      content.innerHTML = `<div class="reader-empty">正文载入失败:${e.message}</div>`;
    }
    // 源站图片加密/失效时优雅降级:破图替换为占位块
    content.addEventListener('error', (e) => {
      if (e.target.tagName === 'IMG') {
        const ph = document.createElement('div');
        ph.className = 'img-placeholder';
        ph.textContent = '🖼 原站图片暂不可用';
        e.target.replaceWith(ph);
      }
    }, true);
  }

  function closeReader() {
    $('reader-backdrop').classList.add('hidden');
    $('article-content').innerHTML = '';
  }

  $('reader-close').addEventListener('click', closeReader);
  $('reader-backdrop').addEventListener('click', (e) => {
    if (e.target === $('reader-backdrop')) closeReader();
  });
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closeReader();
  });

  loadMore.addEventListener('click', () => {
    state.offset += state.limit;
    loadArticles(false);
  });

  // ---- 启动 ----
  // 顶栏滚动反馈:页面离开顶部后给顶栏加投影(纯表现,不影响功能)
  const topbar = document.querySelector('.topbar');
  const onScroll = () => topbar.classList.toggle('is-scrolled', window.scrollY > 8);
  onScroll();
  window.addEventListener('scroll', onScroll, { passive: true });

  initTabs().then(() => loadArticles(true)).catch((e) => {
    meta.textContent = '初始化失败(后端未启动?):' + e.message;
  });
})();
