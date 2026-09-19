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
    // 刷新按钮只对已接入采集器的站点可用
    $('refresh-btn').addEventListener('click', async () => {
      if (!state.current) return alert('请先选择单个站点再刷新');
      const btn = $('refresh-btn');
      btn.disabled = true;
      try {
        await api(`/api/refresh/${state.current}`, { method: 'POST' });
        await switchTab(state.current);
      } catch (e) {
        alert('刷新失败:' + e.message);
      } finally {
        btn.disabled = false;
      }
    });
  }

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
      loadMore.classList.toggle('hidden', data.total < state.limit);
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
  initTabs().then(() => loadArticles(true)).catch((e) => {
    meta.textContent = '初始化失败(后端未启动?):' + e.message;
  });
})();
