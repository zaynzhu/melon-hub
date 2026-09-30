// melon-hub 设置页:定时采集配置 + 运行状态
(() => {
  const $ = (id) => document.getElementById(id);

  async function api(path, opts) {
    const resp = await fetch(path, opts);
    if (!resp.ok) throw new Error(`${resp.status} ${await resp.text()}`);
    return resp.json();
  }

  function fmt(iso) {
    if (!iso) return '从未';
    return iso.replace('T', ' ').replace('Z', ' UTC');
  }

  async function load() {
    let cfg;
    try {
      cfg = await api('/api/settings');
    } catch (e) {
      $('settings-status').textContent = '配置载入失败:' + e.message;
      return;
    }
    $('interval-enabled').checked = cfg.interval_hours > 0;
    $('interval-hours').value = cfg.interval_hours > 0 ? cfg.interval_hours : '';
    $('daily-enabled').checked = !!cfg.daily_at;
    $('daily-at').value = cfg.daily_at || '03:00';
    refreshStatus();
  }

  async function save() {
    const err = $('settings-error');
    err.classList.add('hidden');
    let intervalHours = 0;
    if ($('interval-enabled').checked) {
      intervalHours = parseInt($('interval-hours').value, 10);
      if (!intervalHours || intervalHours < 1 || intervalHours > 24) {
        err.textContent = '间隔小时需为 1-24 的整数';
        err.classList.remove('hidden');
        return;
      }
    }
    let dailyAt = '';
    if ($('daily-enabled').checked) {
      dailyAt = $('daily-at').value;
      if (!dailyAt) {
        err.textContent = '请选择每日采集时间';
        err.classList.remove('hidden');
        return;
      }
    }
    try {
      await api('/api/settings', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ interval_hours: intervalHours, daily_at: dailyAt }),
      });
    } catch (e) {
      err.textContent = '保存失败:' + e.message;
      err.classList.remove('hidden');
      return;
    }
    const saved = $('settings-saved');
    saved.classList.remove('hidden');
    setTimeout(() => saved.classList.add('hidden'), 1800);
    refreshStatus();
  }

  async function refreshStatus() {
    let st;
    try {
      st = await api('/api/sync/status');
    } catch (e) {
      $('settings-status').textContent = '状态查询失败:' + e.message;
      return;
    }
    const lines = [];
    lines.push(st.running
      ? `采集中(${st.trigger === 'schedule' ? '定时' : '手动'}:${st.current || '准备中'})`
      : '空闲(未在采集)');
    lines.push(`上次间隔采集:${fmt(st.last_interval_run)}`);
    lines.push(`每日采集已完成日期:${st.last_daily_date || '无'}`);
    $('settings-status').textContent = lines.join(' · ');
  }

  async function loadSitesDetail() {
    const wrap = $('sites-detail-list');
    try {
      const sites = await api('/api/sites/detail');
      wrap.innerHTML = '';
      for (const s of sites) {
        const box = document.createElement('div');
        box.className = 'site-detail';
        box.dataset.source = s.id;
        box.innerHTML = `
          <div class="site-detail-head">
            <span class="site-detail-name"></span>
            <span class="site-detail-id"></span>
          </div>
          <div class="site-detail-row site-detail-home">
            <span class="site-detail-label">当前 home</span>
            <a class="site-detail-home-url" target="_blank" rel="noopener noreferrer"></a>
          </div>
          <div class="site-detail-row">
            <span class="site-detail-label">镜像池</span>
            <div class="site-detail-mirrors"></div>
          </div>
          <div class="site-detail-row">
            <span class="site-detail-label">回家路</span>
            <div class="site-detail-homeway"></div>
          </div>`;
        box.querySelector('.site-detail-name').textContent = s.name;
        box.querySelector('.site-detail-id').textContent = s.id;
        const homeA = box.querySelector('.site-detail-home-url');
        homeA.href = s.home;
        homeA.textContent = s.home;
        const mirrorsBox = box.querySelector('.site-detail-mirrors');
        if (s.mirrors.length === 0) {
          mirrorsBox.innerHTML = '<span class="site-detail-empty">无备用(主站挂了需人工跑 discover)</span>';
        } else {
          for (const m of s.mirrors) {
            const chip = document.createElement('a');
            chip.className = 'site-detail-mirror' + (m === s.home ? ' is-home' : '');
            chip.href = m;
            chip.target = '_blank';
            chip.rel = 'noopener noreferrer';
            chip.textContent = m;
            mirrorsBox.appendChild(chip);
          }
        }
        const homeBox = box.querySelector('.site-detail-homeway');
        if (s.homeway_pages.length === 0) {
          homeBox.innerHTML = '<span class="site-detail-empty">无</span>';
        } else {
          for (const h of s.homeway_pages) {
            const a = document.createElement('a');
            a.className = 'site-detail-homeway-link';
            a.href = h;
            a.target = '_blank';
            a.rel = 'noopener noreferrer';
            a.textContent = h;
            homeBox.appendChild(a);
          }
        }
        wrap.appendChild(box);
      }
    } catch (e) {
      wrap.innerHTML = `<div class="settings-hint" style="color:hsl(6,80%,64%)">镜像配置载入失败: ${e.message}</div>`;
    }
  }

  $('settings-save').addEventListener('click', save);
  // 输入框改动即校验开关:间隔关掉时小时框禁用,每日关掉时时间框禁用
  const intervalBox = $('interval-enabled'), intervalHours = $('interval-hours');
  const dailyBox = $('daily-enabled'), dailyAt = $('daily-at');
  const syncDisabled = () => {
    intervalHours.disabled = !intervalBox.checked;
    dailyAt.disabled = !dailyBox.checked;
  };
  intervalBox.addEventListener('change', syncDisabled);
  dailyBox.addEventListener('change', syncDisabled);
  syncDisabled();

  load();
  loadSitesDetail();
  setInterval(refreshStatus, 5000);
})();