/* 열체크 화면 동작: 토스트, 바텀시트, 시간 휠, 차트, 설정 자동 저장, 푸시 알림 */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const pad = n => String(n).padStart(2, '0');
  const hm = d => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const f1 = n => (Math.round(n * 10) / 10).toFixed(1);
  const csrf = document.body.dataset.csrf;
  const level = v => v >= 38 ? 'hot' : v >= 37.5 ? 'warn' : 'ok';
  const LEVEL_TEXT = { hot: '열이 있어요', warn: '미열이에요', ok: '정상 체온이에요' };

  /* ---------- toast ---------- */
  const toastEl = $('#toast');
  function toast(msg) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    clearTimeout(toast.t);
    toast.t = setTimeout(() => toastEl.classList.remove('show'), 2200);
  }
  $$('#flash li').forEach((li, i) => setTimeout(() => toast(li.textContent), 150 + i * 2400));

  const post = (url, body) => fetch(url, { method: 'POST', headers: { 'X-CSRFToken': csrf }, body, credentials: 'same-origin' });

  /* ---------- chart ---------- */
  function drawChart(el, data) {
    const W = 342, Hh = 176, L = 30, R = 10, Tp = 10, B = 44, HOUR = 3600e3;
    const start = +new Date(data.start), end = +new Date(data.end);
    const x = t => L + (t - start) / (end - start) * (W - L - R);
    const y = v => Tp + (40 - Math.max(36, Math.min(40, v))) / 4 * (Hh - Tp - B);
    let s = `<svg viewBox="0 0 ${W} ${Hh}" class="w-full h-auto" role="img" aria-label="최근 24시간 체온 차트">
      <defs><linearGradient id="ar" x1="0" y1="0" x2="0" y2="1"><stop offset="0" style="stop-color:var(--accent);stop-opacity:.22"/><stop offset="1" style="stop-color:var(--accent);stop-opacity:0"/></linearGradient></defs>
      <rect x="${L}" y="${y(40)}" width="${W - L - R}" height="${y(38) - y(40)}" style="fill:var(--hot-soft)" rx="6"/>`;
    [36, 37, 38, 39, 40].forEach(v => {
      s += `<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}" style="stroke:var(--line)"/>
        <text x="${L - 6}" y="${y(v) + 3.5}" text-anchor="end" font-size="10" style="fill:var(--fg-3)">${v}</text>`;
    });
    s += `<line x1="${L}" x2="${W - R}" y1="${y(37.5)}" y2="${y(37.5)}" style="stroke:var(--warn)" stroke-dasharray="3 4" stroke-width="1.2"/>
      <text x="${L + 5}" y="${y(38) - 4}" font-size="9.5" font-weight="600" style="fill:var(--hot)">38.0 열</text>`;
    const first = new Date(start); first.setMinutes(0, 0, 0);
    for (let t = +first + HOUR; t <= end; t += HOUR) {
      const d = new Date(t); if (d.getHours() % 6) continue;
      s += `<text x="${x(t)}" y="${Hh - 4}" text-anchor="middle" font-size="10" style="fill:var(--fg-3)">${d.getHours()}시</text>`;
    }
    data.meds.forEach(([iso, initial, cls]) => {
      const X = x(+new Date(iso));
      s += `<line x1="${X}" x2="${X}" y1="${Tp}" y2="${Hh - B + 6}" style="stroke:var(--${cls})" stroke-dasharray="2 3" opacity=".7"/>
        <rect x="${X - 9}" y="${Hh - B + 8}" width="18" height="15" rx="7.5" style="fill:var(--${cls})"/>
        <text x="${X}" y="${Hh - B + 18.5}" text-anchor="middle" font-size="9" font-weight="700" fill="#fff">${initial}</text>`;
    });
    const pts = data.temps.map(([iso, v]) => [+new Date(iso), v]);
    if (pts.length) {
      const line = pts.map(([t, v], i) => `${i ? 'L' : 'M'}${x(t).toFixed(1)},${y(v).toFixed(1)}`).join(' ');
      const base = y(36);
      s += `<path d="${line} L${x(pts.at(-1)[0]).toFixed(1)},${base} L${x(pts[0][0]).toFixed(1)},${base} Z" fill="url(#ar)"/>
        <path d="${line}" fill="none" style="stroke:var(--accent)" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>`;
      pts.forEach(([t, v], i) => {
        s += `<circle cx="${x(t)}" cy="${y(v)}" r="${i === pts.length - 1 ? 5.5 : 3.6}" style="fill:var(--${level(v)});stroke:var(--surface)" stroke-width="2"/>`;
      });
      const [lt, lv] = pts.at(-1);
      s += `<text x="${Math.min(x(lt), W - R - 20)}" y="${y(lv) - 10}" text-anchor="middle" font-size="11" font-weight="700" style="fill:var(--fg)">${f1(lv)}</text>`;
    } else {
      s += `<text x="${(W + L) / 2}" y="${(Hh - B) / 2 + 10}" text-anchor="middle" font-size="12" style="fill:var(--fg-3)">최근 24시간 체온 기록이 없어요</text>`;
    }
    el.innerHTML = s + '</svg>';
  }
  const chartData = $('#chart-data');
  if (chartData) $$('[data-chart]').forEach(el => drawChart(el, JSON.parse(chartData.textContent)));

  /* ---------- bottom sheets ---------- */
  let openSheet = null;
  function showSheet(name) {
    const sheet = $(`#sheet-${name}`); if (!sheet) return;
    resetTime(sheet);
    if (name === 'med') renderMed();
    openSheet = sheet;
    document.body.classList.add('sheet-open');
    requestAnimationFrame(() => sheet.classList.add('open'));
  }
  function hideSheet() {
    closePicker();
    if (openSheet) openSheet.classList.remove('open');
    document.body.classList.remove('sheet-open');
    openSheet = null;
  }
  document.addEventListener('keydown', e => { if (e.key === 'Escape') { if (picker) closePicker(); else hideSheet(); } });

  /* temperature sheet */
  const tempRange = $('#temp-range');
  function renderTemp() {
    if (!tempRange) return;
    const v = +tempRange.value, l = level(v);
    $('[data-temp-value]').textContent = f1(v);
    $('[data-temp-color]').className = `leading-none text-${l}`;
    const label = $('[data-temp-label]');
    label.textContent = LEVEL_TEXT[l];
    label.className = `text-[13px] font-semibold mt-2 text-${l}`;
  }
  if (tempRange) { tempRange.addEventListener('input', renderTemp); renderTemp(); }

  /* medication sheet */
  const sheetDataEl = $('#sheet-data');
  const SD = sheetDataEl ? JSON.parse(sheetDataEl.textContent) : null;
  let ml = null;
  function selectedDrug() { const r = $('[data-drug-radio]:checked'); return r ? r.value : 'tylenol'; }
  function renderMed(resetAmount = true) {
    if (!SD) return;
    const key = selectedDrug(), d = SD.drugs[key], cls = SD.classes[d.cls];
    if (resetAmount || ml === null) ml = d.suggested;
    $$('[data-drug-card]').forEach(card => {
      const on = card.dataset.drugCard === key, c = SD.drugs[card.dataset.drugCard].cls;
      card.className = `press rounded-2xl p-3 flex flex-col items-start gap-1.5 border-2 cursor-pointer ${on ? `border-${c} bg-${c}soft` : 'border-transparent bg-surface2'}`;
    });
    $('[data-ml-value]').textContent = f1(ml);
    $('[data-ml-value]').className = `text-[40px] font-bold num text-${d.cls}`;
    $('[data-mg-value]').textContent = `${Math.round(ml * d.conc)}mg`;
    $('[data-ml-input]').value = f1(ml);
    $('[data-ml-range]').innerHTML = `${f1(SD.weight)}kg 권장 <b class="text-fg">${f1(d.mlMin)}–${f1(d.mlMax)}mL</b>`;
    const at = cls.availableAt ? new Date(cls.availableAt) : null, now = new Date();
    const note = $('[data-med-note]');
    if (at && at > now) {
      const mins = Math.ceil((at - now) / 60e3), wait = mins < 60 ? `${mins}분 후` : `${Math.floor(mins / 60)}시간${mins % 60 ? ` ${mins % 60}분` : ''} 후`;
      note.innerHTML = `<div class="rounded-2xl bg-hotsoft p-3.5 text-[13px] leading-relaxed"><b class="num">${hm(at)}부터</b> 먹일 수 있어요 (${wait}). ${cls.reason === 'cross' ? '다른 계열 해열제를 먹인 지 2시간이 지나지 않았어요.' : `같은 계열은 ${cls.gapHours}시간 간격을 지켜 주세요.`}</div>`;
    } else if (SD.lastTemp !== null && SD.lastTemp < 38) {
      note.innerHTML = `<div class="rounded-2xl bg-oksoft p-3.5 text-[13px] leading-relaxed">지금 먹일 수 있어요. 다만 마지막 체온이 <b class="num">${f1(SD.lastTemp)}℃</b>로 높지 않아 먹이지 않아도 괜찮아요.</div>`;
    } else {
      note.innerHTML = '';
    }
  }
  $$('[data-drug-radio]').forEach(r => r.addEventListener('change', () => renderMed(true)));

  /* ---------- time picker (wheel) ---------- */
  function setTime(sheet, date) {
    const now = new Date(), yesterday = date.toDateString() !== now.toDateString();
    sheet._time = date;
    $('[data-time-text]', sheet).textContent = hm(date);
    $('[data-time-day]', sheet).hidden = !yesterday;
    $('[data-time-input]', sheet).value = sheet._custom
      ? `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${hm(date)}` : '';
  }
  function resetTime(sheet) { sheet._custom = false; setTime(sheet, new Date()); }

  let picker = null;
  const wheel = (id, items) => `<div class="wheel" id="${id}" tabindex="0"><div class="wh-pad"></div>${items.map((t, i) => `<div class="wh-item" data-i="${i}">${t}</div>`).join('')}<div class="wh-pad"></div></div>`;
  const range = n => Array.from({ length: n }, (_, i) => pad(i));
  function pickerDate() {
    const d = new Date(); d.setDate(d.getDate() - (picker.day ? 0 : 1)); d.setHours(picker.h, picker.m, 0, 0); return d;
  }
  function syncPicker() {
    const d = pickerDate(), bad = d > new Date(), ok = $('#pk-ok');
    $('#pk-preview').textContent = `${picker.day ? '오늘' : '어제'} ${hm(d)}`;
    $('#pk-err').textContent = bad ? '아직 오지 않은 시간이에요' : '';
    ok.disabled = bad; ok.style.opacity = bad ? .4 : 1;
  }
  function openPicker(sheet) {
    const base = sheet._time || new Date();
    picker = { sheet, day: base.toDateString() === new Date().toDateString() ? 1 : 0, h: base.getHours(), m: base.getMinutes() };
    const root = document.createElement('div');
    root.id = 'picker-root';
    root.innerHTML = `<div class="pk-back" data-pk-cancel></div>
      <div class="pk" role="dialog" aria-modal="true" aria-label="시간 선택">
        <div class="flex items-center justify-between mb-3"><h4 class="text-[17px] font-bold">${sheet.id === 'sheet-temp' ? '잰 시간' : '먹인 시간'}</h4><span class="text-[15px] font-semibold num text-accent" id="pk-preview"></span></div>
        <div class="relative flex items-stretch gap-1">
          <div class="absolute left-0 right-0 top-[80px] h-10 rounded-xl bg-surface2 pointer-events-none"></div>
          ${wheel('pk-day', ['어제', '오늘'])}${wheel('pk-h', range(24))}<div class="relative self-center text-[22px] font-semibold">:</div>${wheel('pk-m', range(60))}
        </div>
        <p class="text-[12px] text-hot h-4 mt-2" id="pk-err"></p>
        <div class="grid grid-cols-2 gap-2 mt-2"><button type="button" class="press py-3.5 rounded-2xl bg-surface2 font-semibold" data-pk-cancel>취소</button>
          <button type="button" class="press py-3.5 rounded-2xl bg-accent text-onaccent font-semibold" id="pk-ok">확인</button></div>
      </div>`;
    document.body.appendChild(root);
    [['pk-day', picker.day], ['pk-h', picker.h], ['pk-m', picker.m]].forEach(([id, i]) => {
      const w = $(`#${id}`); w.scrollTop = i * 40; w.children[i + 1].classList.add('on');
      w.addEventListener('scroll', () => {
        const items = $$('.wh-item', w), idx = Math.max(0, Math.min(items.length - 1, Math.round(w.scrollTop / 40)));
        items.forEach((el, j) => el.classList.toggle('on', j === idx));
        picker[{ 'pk-day': 'day', 'pk-h': 'h', 'pk-m': 'm' }[id]] = idx;
        syncPicker();
      });
    });
    syncPicker();
  }
  function closePicker() { const r = $('#picker-root'); if (r) r.remove(); picker = null; }
  function confirmPicker() {
    const d = pickerDate(); if (d > new Date()) return;
    picker.sheet._custom = true; setTime(picker.sheet, d); closePicker();
  }

  /* ---------- click delegation ---------- */
  document.addEventListener('click', e => {
    const t = e.target.closest('button, [data-close-sheet], .wh-item, [data-pk-cancel]');
    if (!t) return;
    if (t.matches('[data-pk-cancel]')) return closePicker();
    if (t.id === 'pk-ok') return confirmPicker();
    if (t.matches('.wh-item')) return t.parentElement.scrollTo({ top: +t.dataset.i * 40, behavior: 'smooth' });
    if (t.matches('[data-open-sheet]')) return showSheet(t.dataset.openSheet);
    if (t.matches('[data-close-sheet]')) return hideSheet();
    if (t.matches('[data-time-button]')) return openPicker(t.closest('.sheet'));
    if (t.matches('[data-temp-step]')) {
      tempRange.value = Math.min(41, Math.max(35, Math.round((+tempRange.value + +t.dataset.tempStep) * 10) / 10));
      return renderTemp();
    }
    if (t.matches('[data-ml-step]')) { ml = Math.max(0.5, Math.round((ml + +t.dataset.mlStep) * 10) / 10); return renderMed(false); }
    if (t.matches('[data-weight-step]')) return stepWeight(+t.dataset.weightStep);
    if (t.matches('[data-delete-open]')) { $(`[data-delete-box="${t.dataset.deleteOpen}"]`).hidden = false; return; }
    if (t.matches('[data-delete-cancel]')) { $(`[data-delete-box="${t.dataset.deleteCancel}"]`).hidden = true; return; }
    if (t.matches('[data-add-open]')) { $('[data-add-form]').hidden = false; t.hidden = true; $('#nu-name').focus(); return; }
    if (t.matches('[data-add-close]')) { $('[data-add-form]').hidden = true; $('[data-add-open]').hidden = false; return; }
    if (t.matches('[data-guardian-add]')) return addGuardian();
    if (t.matches('[data-guardian-remove]')) return t.closest('[data-guardian-row]').remove();
    if (t.matches('[data-push-toggle]')) return togglePush();
  });

  /* ---------- baby weight ---------- */
  function stepWeight(step) {
    const input = $('[data-weight-input]'), save = $('[data-weight-save]');
    const v = Math.max(1, Math.min(60, Math.round((+input.value + step) * 10) / 10));
    input.value = f1(v);
    $('[data-weight-text]').textContent = f1(v);
    const changed = f1(v) !== f1(+input.dataset.original);
    save.disabled = !changed;
    save.className = `press py-3 rounded-2xl font-semibold ${changed ? 'bg-accent text-onaccent' : 'bg-surface2 text-fg3'}`;
  }

  /* ---------- guardian picker (baby registration) ---------- */
  const gp = $('[data-guardian-picker]');
  async function addGuardian() {
    const input = $('#guardian-id'), err = $('[data-guardian-error]', gp);
    const username = input.value.trim().toLowerCase(); if (!username) return;
    const fail = msg => { err.textContent = msg; err.hidden = false; };
    if ($(`[data-guardian-row="${CSS.escape(username)}"]`, gp)) return fail('이미 추가된 보호자예요.');
    const res = await fetch(`${gp.dataset.lookup}?username=${encodeURIComponent(username)}`, { credentials: 'same-origin' });
    const data = await res.json();
    if (!data.ok) return fail(data.error);
    if (data.me) return fail('이미 추가된 보호자예요.');
    const row = $('#guardian-row').content.firstElementChild.cloneNode(true);
    row.dataset.guardianRow = data.username;
    const av = $('[data-avatar]', row);
    av.textContent = data.relation[0];
    av.classList.add(`bg-${data.color}soft`, `text-${data.color}`);
    $('[data-name]', row).textContent = data.name;
    $('[data-meta]', row).textContent = `${data.relation} · ${data.username}`;
    $('input', row).value = data.username;
    $('[data-guardian-list]', gp).appendChild(row);
    input.value = ''; err.hidden = true;
  }
  if (gp) $('#guardian-id').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); addGuardian(); } });

  /* ---------- settings: autosave + theme ---------- */
  $$('form[data-autosave]').forEach(form => form.addEventListener('change', async () => {
    const row = $('[data-interval-row]', form), on = form.elements.notify_temperature.checked;
    if (row) { row.style.opacity = on ? '' : .4; row.style.pointerEvents = on ? '' : 'none'; }
    const res = await post(form.action, new FormData(form));
    toast(res.ok ? '알림 설정을 저장했어요' : '저장하지 못했어요. 다시 시도해 주세요');
  }));
  const themeForm = $('[data-theme-form]');
  if (themeForm) themeForm.addEventListener('change', async () => {
    const theme = themeForm.elements.theme.value;
    if (theme === 'system') delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
    await post(themeForm.action, new FormData(themeForm));
  });

  /* ---------- push notifications ---------- */
  const pushRow = $('[data-push-row]');
  const vapid = document.body.dataset.vapid;
  const b64 = s => { const p = '='.repeat((4 - s.length % 4) % 4), b = atob((s + p).replace(/-/g, '+').replace(/_/g, '/')); return Uint8Array.from(b, c => c.charCodeAt(0)); };
  async function pushState() {
    const status = $('[data-push-status]'), btn = $('[data-push-toggle]');
    if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
      status.textContent = 'iPhone은 홈 화면에 추가한 앱에서 켤 수 있어요'; return;
    }
    if (pushRow.dataset.enabled !== '1' || !vapid) { status.textContent = '서버에 알림 키가 아직 설정되지 않았어요'; return; }
    if (Notification.permission === 'denied') { status.textContent = '브라우저 설정에서 알림이 꺼져 있어요'; return; }
    const reg = await navigator.serviceWorker.getRegistration('/');
    if (!reg) { status.textContent = '이 브라우저에서는 알림을 켤 수 없어요 (https 필요)'; return; }
    const sub = await reg.pushManager.getSubscription();
    status.textContent = sub ? '이 기기로 알림을 받고 있어요' : '알림을 받으려면 켜 주세요';
    btn.textContent = sub ? '끄기' : '켜기';
    btn.className = `press px-3.5 py-2 rounded-xl text-[13px] font-semibold flex-none ${sub ? 'bg-surface2 text-fg2' : 'bg-accentsoft text-accent'}`;
    btn.hidden = false;
  }
  async function togglePush() {
    const reg = await navigator.serviceWorker.getRegistration('/');
    if (!reg) return;
    const sub = await reg.pushManager.getSubscription();
    try {
      if (sub) {
        await post('/push/unsubscribe/', JSON.stringify({ endpoint: sub.endpoint }));
        await sub.unsubscribe();
        toast('이 기기 알림을 껐어요');
      } else {
        if (await Notification.requestPermission() !== 'granted') { toast('알림 권한이 필요해요'); return pushState(); }
        const created = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(vapid) });
        const res = await post('/push/subscribe/', JSON.stringify(created.toJSON()));
        toast(res.ok ? '이 기기로 알림을 받아요' : '알림을 켜지 못했어요');
      }
    } catch (err) {
      toast('알림을 설정하지 못했어요');
    }
    pushState();
  }

  /* ---------- service worker + 홈 자동 새로고침 ---------- */
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {}).finally(() => { if (pushRow) pushState(); });
  } else if (pushRow) pushState();

  if (chartData) {
    // 다른 보호자가 남긴 기록과 교차복용 시간을 반영하려고 1분마다 새로 불러온다.
    setInterval(() => { if (!openSheet && document.visibilityState === 'visible') location.reload(); }, 60e3);
  }
})();
