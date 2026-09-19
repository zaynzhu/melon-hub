// melon-hub 前端:站点 Tab + 卡片流 + 全屏阅读抽屉
(() => {
  const state = { sources: [], current: '', offset: 0, limit: 50, loading: false };

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
    document.querySelectorAll('.site-tab').forEach((b) => {
      b.classList.toggle('active', b.dataset.source === source);
    });
    state.offset = 0;
    flow.innerHTML = '<div class="card-skeleton"></div><div class="card-skeleton"></div><div class="card-skeleton"></div>';
    await loadArticles(true);
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
      if (reset) flow.innerHTML = '';
      meta.textContent = `共 ${data.total} 条${state.current ? ' · ' + sourceName(state.current) : ''}`;
      for (const a of data.articles) flow.appendChild(renderCard(a));
      loadMore.classList.toggle('hidden', data.total < state.limit);
      if (!flow.children.length) {
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
