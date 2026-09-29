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
  setInterval(refreshStatus, 5000);
})();