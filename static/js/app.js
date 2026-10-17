/* 아파요 화면 동작: 화면 전환(새로고침 없이), 토스트, 바텀시트, 시간 휠, 차트, 설정 자동 저장, 푸시 알림

   화면을 옮길 때 페이지를 새로 불러오지 않고 fetch로 받아 <body>만 바꿔 끼운다(load).
   그래서 화면마다 필요한 준비는 initPage()에서 하고, 클릭·제출 같은 이벤트는 document에 한 번만 건다. */
(() => {
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const pad = n => String(n).padStart(2, '0');
  const hm = d => `${pad(d.getHours())}:${pad(d.getMinutes())}`;
  const f1 = n => (Math.round(n * 10) / 10).toFixed(1);
  const csrf = () => document.body.dataset.csrf;  // 로그인하면 바뀌므로 매번 읽는다
  const level = v => v >= 38 ? 'hot' : v >= 37.5 ? 'warn' : 'ok';
  const LEVEL_TEXT = { hot: '열이 있어요', warn: '미열이에요', ok: '정상 체온이에요' };

  /* ---------- 슬라이더 채움 표시 ---------- */
  function paintRange(el) {
    const p = (+el.value - +el.min) / (+el.max - +el.min) * 100;
    el.style.setProperty('--p', `${Math.max(0, Math.min(100, p))}%`);
  }

  /* ---------- toast ---------- */
  function toast(msg) {
    const toastEl = $('#toast');
    if (!toastEl || !msg) return;
    toastEl.textContent = msg;
    toastEl.classList.add('show');
    clearTimeout(toast.t);
    toast.t = setTimeout(() => toastEl.classList.remove('show'), 2200);
  }
  const post = (url, body) => fetch(url, { method: 'POST', headers: { 'X-CSRFToken': csrf() }, body, credentials: 'same-origin' });

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
      <text x="${W - R - 4}" y="${y(40) + 12}" text-anchor="end" font-size="9.5" font-weight="600" style="fill:var(--hot)">38.0 이상 열</text>`;
    const first = new Date(start); first.setMinutes(0, 0, 0);
    const span = (end - start) / HOUR;
    // 하루 안쪽은 6시간마다 'n시', 더 긴 기간은 자정마다 'n/j'
    const every = span <= 36 ? 6 : 24 * Math.ceil(span / 24 / 6);
    for (let t = +first + HOUR; t <= end; t += HOUR) {
      const d = new Date(t); if (d.getHours() % Math.min(every, 24) || (every > 24 && Math.round((t - +first) / HOUR / 24) % (every / 24))) continue;
      const label = every <= 6 ? `${d.getHours()}시` : `${d.getMonth() + 1}/${d.getDate()}`;
      s += `<text x="${x(t)}" y="${Hh - 4}" text-anchor="middle" font-size="10" style="fill:var(--fg-3)">${label}</text>`;
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

  /* ---------- bottom sheets ---------- */
  let openSheet = null;
  function showSheet(name) {
    const sheet = $(`#sheet-${name}`); if (!sheet) return;
    $$('[data-time-field]', sheet).forEach(resetTime);
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
  let tempRange = null;
  function renderTemp() {
    if (!tempRange) return;
    const v = +tempRange.value, l = level(v);
    $('[data-temp-value]').textContent = f1(v);
    $('[data-temp-color]').className = `leading-none text-${l}`;
    const label = $('[data-temp-label]');
    label.textContent = LEVEL_TEXT[l];
    label.className = `text-[13px] font-semibold mt-2 text-${l}`;
  }

  /* medication sheet */
  let SD = null, ml = null;
  function selectedDrug() { const r = $('[data-drug-radio]:checked'); return r ? r.value : 'tylenol'; }
  function renderMed(resetAmount = true) {
    if (!SD) return;
    const key = selectedDrug(), d = SD.drugs[key], cls = SD.classes[d.cls];
    if (resetAmount || ml === null) ml = d.lastMl ?? d.suggested;  // 같은 약을 마지막에 먹인 양
    const slider = $('[data-ml-slider]');
    slider.max = Math.max(10, Math.ceil(d.mlMax * 1.6));
    slider.value = ml;
    slider.style.setProperty('--rc', `var(--${d.cls})`);
    paintRange(slider);
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
    if (!note) return;  // 기록 고치기 화면에는 안내가 없다
    if (at && at > now) {
      const mins = Math.ceil((at - now) / 60e3), wait = mins < 60 ? `${mins}분 후` : `${Math.floor(mins / 60)}시간${mins % 60 ? ` ${mins % 60}분` : ''} 후`;
      note.innerHTML = `<div class="rounded-2xl bg-hotsoft p-3.5 text-[13px] leading-relaxed"><b class="num">${hm(at)}부터</b> 먹일 수 있어요 (${wait}). ${cls.reason === 'cross' ? '다른 계열 해열제를 먹인 지 2시간이 지나지 않았어요.' : `같은 계열은 ${cls.gapHours}시간 간격을 지켜 주세요.`}</div>`;
    } else if (SD.lastTemp !== null && SD.lastTemp < 38) {
      note.innerHTML = `<div class="rounded-2xl bg-oksoft p-3.5 text-[13px] leading-relaxed">지금 먹일 수 있어요. 다만 마지막 체온이 <b class="num">${f1(SD.lastTemp)}℃</b>로 높지 않아 먹이지 않아도 괜찮아요.</div>`;
    } else {
      note.innerHTML = '';
    }
  }

  /* ---------- time picker (wheel) ----------
     [data-time-field data-days="N"]: 버튼에 시각을 보여 주고, 누르면 날짜·시·분 휠을 연다.
     직접 고르지 않으면 hidden input은 비워 두어 서버가 '지금'으로 저장한다. */
  const DOW = '일월화수목금토';
  const startOfDay = d => { const x = new Date(d); x.setHours(0, 0, 0, 0); return x; };
  const daysAgo = d => Math.round((startOfDay(new Date()) - startOfDay(d)) / 864e5);
  const dayLabel = n => { const d = new Date(); d.setDate(d.getDate() - n); return n === 0 ? '오늘' : n === 1 ? '어제' : `${d.getMonth() + 1}/${d.getDate()} (${DOW[d.getDay()]})`; };
  const ymd = d => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
  const isDateMode = field => field.dataset.mode === 'date';
  const isHalfMode = field => field.dataset.mode === 'half';
  const halfLabel = d => `${d.getMonth() + 1}월 ${d.getDate()}일 ${d.getHours() >= 12 ? '오후' : '오전'}`;
  function setTime(field, date, custom) {
    field._time = date; field._custom = custom;
    const ago = daysAgo(date), day = $('[data-time-day]', field);
    if (isHalfMode(field)) {  // 날짜와 오전/오후만: '5월 12일 오후'
      $('[data-time-text]', field).textContent = halfLabel(date);
      day.hidden = true;
      $('[data-time-input]', field).value = custom ? `${ymd(date)} ${date.getHours() >= 12 ? 'pm' : 'am'}` : '';
      return;
    }
    if (isDateMode(field)) {
      $('[data-time-text]', field).textContent = `${date.getMonth() + 1}월 ${date.getDate()}일 (${DOW[date.getDay()]})`;
      day.hidden = ago > 1;
      day.textContent = ago === 0 ? '오늘' : '어제';
      $('[data-time-input]', field).value = custom ? ymd(date) : '';
      return;
    }
    $('[data-time-text]', field).textContent = hm(date);
    day.hidden = ago === 0;
    day.textContent = dayLabel(ago).replace(/ \(.\)$/, '');
    $('[data-time-input]', field).value = custom ? `${ymd(date)}T${hm(date)}` : '';
  }
  function resetTime(field) {
    const initial = field.dataset.initial;
    if (!initial) return setTime(field, new Date(), false);
    const m = initial.match(/^(\d{4})-(\d{2})-(\d{2})$/);
    setTime(field, m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date(initial), true);
  }
  let picker = null;
  const wheel = (id, items) => `<div class="wheel" id="${id}" tabindex="0"><div class="wh-pad"></div>${items.map((t, i) => `<div class="wh-item" data-i="${i}">${t}</div>`).join('')}<div class="wh-pad"></div></div>`;
  const range = n => Array.from({ length: n }, (_, i) => pad(i));
  function pickerDate() {
    const d = new Date(); d.setDate(d.getDate() - (picker.days - 1 - picker.day));
    if (picker.halfOnly) {
      const now = new Date(), pm = picker.h === 1;  // h: 0 오전, 1 오후
      if (d.toDateString() === now.toDateString() && pm === now.getHours() >= 12) return now;  // 지금 반나절
      d.setHours(pm ? 15 : 9, 0, 0, 0); return d;
    }
    d.setHours(picker.h, picker.m, 0, 0); return d;
  }
  function syncPicker() {
    const d = pickerDate(), bad = d > new Date(), ok = $('#pk-ok');
    $('#pk-preview').textContent = picker.halfOnly ? halfLabel(d) : picker.dateOnly
      ? `${d.getMonth() + 1}월 ${d.getDate()}일 (${DOW[d.getDay()]})`
      : `${dayLabel(picker.days - 1 - picker.day).replace(/ \(.\)$/, '')} ${hm(d)}`;
    $('#pk-err').textContent = bad ? (picker.halfOnly ? '아직 오지 않은 때예요' : '아직 오지 않은 시간이에요') : '';
    ok.disabled = bad; ok.style.opacity = bad ? .4 : 1;
  }
  // 고를 수 없는 때는 아예 보여주지 않는다: data-min(아픔 시작)보다 앞선 날·반나절, 아직 오지 않은 오늘 오후
  function allowedHalves(ago) {
    const halves = [0, 1];
    if (ago === 0 && new Date().getHours() < 12) halves.pop();
    if (picker.min && ago === daysAgo(picker.min) && picker.min.getHours() >= 12) halves.shift();
    return halves.length ? halves : [ago === 0 ? 0 : 1];
  }
  function fillHalfWheel(keep) {
    const w = $('#pk-h');
    picker.halves = allowedHalves(picker.days - 1 - picker.day);
    const idx = Math.max(0, picker.halves.indexOf(keep));
    picker.h = picker.halves[idx];
    w.innerHTML = `<div class="wh-pad"></div>${picker.halves.map((h, i) => `<div class="wh-item${i === idx ? ' on' : ''}" data-i="${i}">${h ? '오후' : '오전'}</div>`).join('')}<div class="wh-pad"></div>`;
    w.scrollTop = idx * 40;
  }
  function openPicker(field) {
    const min = field.dataset.min ? new Date(field.dataset.min) : null;
    let days = Math.max(1, +field.dataset.days || 2);
    if (min) days = Math.max(1, Math.min(days, daysAgo(min) + 1));
    const base = field._time || new Date();
    const dateOnly = isDateMode(field), halfOnly = isHalfMode(field);
    picker = { field, days, dateOnly, halfOnly, min, day: Math.max(0, days - 1 - Math.min(daysAgo(base), days - 1)),
               h: dateOnly ? 0 : halfOnly ? (base.getHours() >= 12 ? 1 : 0) : base.getHours(), m: dateOnly || halfOnly ? 0 : base.getMinutes() };
    const dayItems = Array.from({ length: days }, (_, i) => dayLabel(days - 1 - i));
    const root = document.createElement('div');
    root.id = 'picker-root';
    root.innerHTML = `<div class="pk-back" data-pk-cancel></div>
      <div class="pk" role="dialog" aria-modal="true" aria-label="시간 선택">
        <div class="flex items-center justify-between mb-3"><h4 class="text-[17px] font-bold">${field.dataset.title || '시간'}</h4><span class="text-[15px] font-semibold num text-accent" id="pk-preview"></span></div>
        <div class="relative flex items-stretch gap-1">
          <div class="absolute left-0 right-0 top-[80px] h-10 rounded-xl bg-surface2 pointer-events-none"></div>
          <div class="flex-[1.6] flex">${wheel('pk-day', dayItems)}</div>${dateOnly ? '' : halfOnly ? wheel('pk-h', ['오전', '오후']) : `${wheel('pk-h', range(24))}<div class="relative self-center text-[22px] font-semibold">:</div>${wheel('pk-m', range(60))}`}
        </div>
        <p class="text-[12px] text-hot h-4 mt-2" id="pk-err"></p>
        <div class="grid grid-cols-2 gap-2 mt-2"><button type="button" class="press py-3.5 rounded-2xl bg-surface2 font-semibold" data-pk-cancel>취소</button>
          <button type="button" class="press py-3.5 rounded-2xl bg-accent text-onaccent font-semibold" id="pk-ok">확인</button></div>
      </div>`;
    document.body.appendChild(root);
    const wheels = dateOnly ? [['pk-day', picker.day]] : halfOnly ? [['pk-day', picker.day], ['pk-h', null]]
      : [['pk-day', picker.day], ['pk-h', picker.h], ['pk-m', picker.m]];
    if (halfOnly) fillHalfWheel(picker.h);
    wheels.forEach(([id, i]) => {
      const w = $(`#${id}`);
      if (i !== null) { w.scrollTop = i * 40; w.children[i + 1].classList.add('on'); }
      w.addEventListener('scroll', () => {
        const items = $$('.wh-item', w), idx = Math.max(0, Math.min(items.length - 1, Math.round(w.scrollTop / 40)));
        items.forEach((el, j) => el.classList.toggle('on', j === idx));
        if (halfOnly && id === 'pk-h') picker.h = picker.halves[idx];
        else {
          const changed = id === 'pk-day' && picker.day !== idx;
          picker[{ 'pk-day': 'day', 'pk-h': 'h', 'pk-m': 'm' }[id]] = idx;
          if (halfOnly && changed) fillHalfWheel(picker.h);  // 날마다 고를 수 있는 오전·오후가 다르다
        }
        syncPicker();
      });
    });
    if (!dateOnly) $$('#pk-day .wh-item').forEach(el => { el.style.fontSize = '17px'; });
    syncPicker();
  }
  function closePicker() { const r = $('#picker-root'); if (r) r.remove(); picker = null; }
  function confirmPicker() {
    const d = pickerDate(); if (d > new Date()) return;
    setTime(picker.field, d, true); closePicker();
  }

  /* ---------- illness form: 이름 고르기, 증상 직접 추가 ---------- */
  let titleInput = null;
  function syncTitleChips() {
    $$('[data-title-preset]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.titlePreset === titleInput.value.trim())));
  }
  function addSymptom() {
    const input = $('[data-symptom-input]'), value = input.value.trim();
    if (!value) return;
    const existing = $$('[data-symptom-list] input').find(i => i.value === value);
    if (existing) { existing.checked = true; input.value = ''; return; }
    const label = document.createElement('label');
    label.innerHTML = '<input type="checkbox" class="peer sr-only" name="symptoms" checked><span class="chip press px-3.5 py-2 text-[14px]"></span>';
    label.firstChild.value = value;
    label.lastChild.textContent = value;
    $('[data-symptom-list]').appendChild(label);
    input.value = '';
  }

  /* ---------- visit form: 약 사진 줄여서 올리기 ---------- */
  let photoInput = null, photoStore = null;
  function resizeImage(file, max = 1600) {
    return new Promise(resolve => {
      const url = URL.createObjectURL(file), img = new Image();
      img.onload = () => {
        const scale = Math.min(1, max / Math.max(img.width, img.height));
        const canvas = document.createElement('canvas');
        canvas.width = Math.round(img.width * scale); canvas.height = Math.round(img.height * scale);
        const ctx = canvas.getContext('2d');
        ctx.fillStyle = '#fff'; ctx.fillRect(0, 0, canvas.width, canvas.height);  // 투명한 부분이 검게 나오지 않도록
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
        canvas.toBlob(blob => { URL.revokeObjectURL(url); resolve(new File([blob], file.name.replace(/\.\w+$/, '') + '.jpg', { type: 'image/jpeg' })); }, 'image/jpeg', .82);
      };
      img.onerror = () => { URL.revokeObjectURL(url); resolve(file); };
      img.src = url;
    });
  }
  async function addPhotos() {
    const grid = $('[data-photo-grid]'), add = $('[data-photo-add]');
    for (const file of [...photoInput.files]) {
      const resized = await resizeImage(file);
      photoStore.items.add(resized);
      const tile = document.createElement('div');
      tile.className = 'relative aspect-square rounded-xl overflow-hidden bg-surface2';
      tile.innerHTML = `<img alt="새 사진" class="w-full h-full object-cover"><button type="button" class="absolute top-1 right-1 w-5 h-5 rounded-full bg-[var(--scrim)] text-white text-[11px]" data-photo-remove aria-label="사진 빼기">✕</button>`;
      tile.firstChild.src = URL.createObjectURL(resized);
      tile.dataset.name = resized.name + photoStore.files.length;
      tile._file = resized;
      grid.insertBefore(tile, add);
    }
    photoInput.files = photoStore.files;
  }
  function removeNewPhoto(tile) {
    const keep = new DataTransfer();
    [...photoStore.files].forEach(f => { if (f !== tile._file) keep.items.add(f); });
    photoStore.items.clear();
    [...keep.files].forEach(f => photoStore.items.add(f));
    photoInput.files = photoStore.files;
    tile.remove();
  }

  /* ---------- 약 봉지 사진 갤러리 ---------- */
  function openGallery(grid, start) {
    const srcs = $$('img', grid).map(img => img.src);
    const root = document.createElement('div');
    root.id = 'gallery';
    root.className = 'fixed inset-0 z-[70] bg-black flex flex-col';
    root.setAttribute('role', 'dialog'); root.setAttribute('aria-modal', 'true'); root.setAttribute('aria-label', '사진 보기');
    const navBtn = (dir, label, path) => `<button type="button" class="absolute top-1/2 -translate-y-1/2 ${dir === -1 ? 'left-3' : 'right-3'} w-11 h-11 rounded-full bg-white/15 text-white flex items-center justify-center" data-gallery-step="${dir}" aria-label="${label}"><svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="${path}"/></svg></button>`;
    root.innerHTML = `<div class="flex items-center justify-between px-4 text-white" style="padding-top: max(12px, env(safe-area-inset-top, 0px))">
        <span class="text-[15px] font-semibold num" data-gallery-count></span>
        <button type="button" class="w-10 h-10 rounded-full bg-white/15 flex items-center justify-center text-[18px]" data-gallery-close aria-label="닫기">✕</button></div>
      <div class="relative flex-1 min-h-0">
        <div class="absolute inset-0 flex overflow-x-auto snap-x snap-mandatory" style="scrollbar-width:none" data-gallery-track>
          ${srcs.map((src, i) => `<div class="w-full h-full flex-none snap-center flex items-center justify-center p-2"><img src="${src}" alt="약 봉지 사진 ${i + 1}" class="max-w-full max-h-full object-contain"></div>`).join('')}
        </div>
        ${srcs.length > 1 ? navBtn(-1, '이전 사진', 'm15 18-6-6 6-6') + navBtn(1, '다음 사진', 'm9 18 6-6-6-6') : ''}
      </div>
      ${srcs.length > 1 ? `<div class="flex gap-2 overflow-x-auto px-4 pt-3 justify-center" style="scrollbar-width:none" data-gallery-thumbs>
        ${srcs.map((src, i) => `<button type="button" class="w-14 h-14 rounded-lg overflow-hidden flex-none border-2 border-transparent opacity-60" data-gallery-go="${i}" aria-label="${i + 1}번째 사진"><img src="${src}" alt="" class="w-full h-full object-cover"></button>`).join('')}
      </div>` : ''}
      <div style="height: max(16px, env(safe-area-inset-bottom, 0px))"></div>`;
    document.body.appendChild(root);
    document.body.style.overflow = 'hidden';
    const track = $('[data-gallery-track]', root), count = $('[data-gallery-count]', root);
    const update = () => {
      const i = Math.round(track.scrollLeft / track.clientWidth);
      count.textContent = `${i + 1} / ${srcs.length}`;
      $$('[data-gallery-go]', root).forEach((b, j) => {
        b.classList.toggle('border-white', j === i); b.classList.toggle('opacity-60', j !== i);
        if (j === i) b.scrollIntoView({ block: 'nearest', inline: 'nearest' });
      });
      const prev = $('[data-gallery-step="-1"]', root), next = $('[data-gallery-step="1"]', root);
      if (prev) { prev.style.visibility = i === 0 ? 'hidden' : ''; next.style.visibility = i === srcs.length - 1 ? 'hidden' : ''; }
    };
    track.scrollLeft = start * track.clientWidth; update();
    track.addEventListener('scroll', update);
  }
  function galleryGo(index) {
    const track = $('#gallery [data-gallery-track]'); if (!track) return;
    track.scrollTo({ left: index * track.clientWidth, behavior: 'smooth' });
  }
  function galleryStep(dir) {
    const track = $('#gallery [data-gallery-track]'); if (!track) return;
    galleryGo(Math.round(track.scrollLeft / track.clientWidth) + dir);
  }
  function closeGallery() { const g = $('#gallery'); if (g) { g.remove(); document.body.style.overflow = ''; } }
  document.addEventListener('keydown', e => {
    if (!$('#gallery')) return;
    if (e.key === 'Escape') closeGallery();
    if (e.key === 'ArrowRight') galleryStep(1);
    if (e.key === 'ArrowLeft') galleryStep(-1);
  });

  /* ---------- 하단 버튼을 키보드 바로 위에 (iOS는 visualViewport로 계산) ---------- */
  const vv = window.visualViewport;
  function updateKeyboard() {
    if (!vv || !$('.action-bar')) return;
    const kb = Math.max(0, Math.round(window.innerHeight - vv.height - vv.offsetTop));
    document.documentElement.style.setProperty('--kb', `${kb}px`);
    document.body.classList.toggle('kb-open', kb > 80);
  }
  if (vv) { vv.addEventListener('resize', updateKeyboard); vv.addEventListener('scroll', updateKeyboard); }

  /* ---------- click delegation ---------- */
  document.addEventListener('click', e => {
    const t = e.target.closest('button, [data-close-sheet], .wh-item, [data-pk-cancel]');
    if (!t) return;
    if (t.matches('[data-gallery-open]')) return openGallery(t.closest('[data-gallery]'), +t.dataset.galleryOpen);
    if (t.matches('[data-gallery-close]')) return closeGallery();
    if (t.matches('[data-gallery-step]')) return galleryStep(+t.dataset.galleryStep);
    if (t.matches('[data-gallery-go]')) return galleryGo(+t.dataset.galleryGo);
    if (t.matches('[data-pk-cancel]')) return closePicker();
    if (t.id === 'pk-ok') return confirmPicker();
    if (t.matches('.wh-item')) return t.parentElement.scrollTo({ top: +t.dataset.i * 40, behavior: 'smooth' });
    if (t.matches('[data-open-sheet]')) return showSheet(t.dataset.openSheet);
    if (t.matches('[data-close-sheet]')) return hideSheet();
    if (t.matches('[data-time-button]')) return openPicker(t.closest('[data-time-field]'));
    if (t.matches('[data-title-preset]')) { titleInput.value = t.dataset.titlePreset; return syncTitleChips(); }
    if (t.matches('[data-symptom-add]')) return addSymptom();
    if (t.matches('[data-hospital]')) { $('#visit-name').value = t.dataset.hospital; if (t.dataset.location) $('#visit-location').value = t.dataset.location; return; }
    if (t.matches('[data-photo-remove]')) return removeNewPhoto(t.closest('div'));
    if (t.matches('[data-delete-ask]')) { t.hidden = true; $('[data-delete-confirm]').hidden = false; return; }
    if (t.matches('[data-delete-no]')) { $('[data-delete-confirm]').hidden = true; $('[data-delete-ask]').hidden = false; return; }
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
  function stepWeight(step, absolute) {
    const input = $('[data-weight-input]'), save = $('[data-weight-save]'), slider = $('[data-weight-slider]');
    const v = Math.max(1, Math.min(60, Math.round((absolute ?? +input.value + step) * 10) / 10));
    if (slider) { slider.value = v; paintRange(slider); }
    input.value = f1(v);
    const text = $('[data-weight-text]');
    if (document.activeElement !== text) text.value = f1(v);
    $('[data-weight-label]').textContent = f1(v);
    const changed = f1(v) !== f1(+input.dataset.original);
    save.disabled = !changed;
    save.className = `press py-3 rounded-2xl font-semibold ${changed ? 'bg-accent text-onaccent' : 'bg-surface2 text-fg3'}`;
  }

  /* ---------- guardian picker (baby registration) ---------- */
  let gp = null;
  async function addGuardian() {
    const input = $('#guardian-id'), err = $('[data-guardian-error]', gp);
    const username = input.value.trim().toLowerCase(); if (!username) return;
    const fail = msg => { err.textContent = msg; err.hidden = false; };
    if ($(`[data-guardian-row="${CSS.escape(username)}"]`, gp)) return fail('이미 추가된 보호자예요.');
    const btn = $('[data-guardian-add]', gp);
    busy([btn], true);
    let data;
    try {
      const res = await fetch(`${gp.dataset.lookup}?username=${encodeURIComponent(username)}`, { credentials: 'same-origin' });
      data = await res.json();
    } catch (_) { data = { ok: false, error: '연결이 불안정해요. 다시 시도해 주세요' }; }
    busy([btn], false);
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

  /* ---------- settings: autosave + theme ---------- */
  /* ---------- push notifications ---------- */
  let pushRow = null;
  const b64 = s => { const p = '='.repeat((4 - s.length % 4) % 4), b = atob((s + p).replace(/-/g, '+').replace(/_/g, '/')); return Uint8Array.from(b, c => c.charCodeAt(0)); };
  async function pushState() {
    const status = $('[data-push-status]'), btn = $('[data-push-toggle]');
    if (!('serviceWorker' in navigator) || !('PushManager' in window) || !('Notification' in window)) {
      status.textContent = 'iPhone은 홈 화면에 추가한 앱에서 켤 수 있어요'; return;
    }
    const vapid = document.body.dataset.vapid;
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
    busy([$('[data-push-toggle]')], true);
    const sub = await reg.pushManager.getSubscription();
    try {
      if (sub) {
        await post('/push/unsubscribe/', JSON.stringify({ endpoint: sub.endpoint }));
        await sub.unsubscribe();
        toast('이 기기 알림을 껐어요');
      } else {
        if (await Notification.requestPermission() !== 'granted') { toast('알림 권한이 필요해요'); busy([$('[data-push-toggle]')], false); return pushState(); }
        const created = await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64(document.body.dataset.vapid) });
        const res = await post('/push/subscribe/', JSON.stringify(created.toJSON()));
        toast(res.ok ? '이 기기로 알림을 받아요' : '알림을 켜지 못했어요');
      }
    } catch (err) {
      toast('알림을 설정하지 못했어요');
    }
    busy([$('[data-push-toggle]')], false);
    pushState();
  }

  /* ---------- 로딩 표시 ---------- */
  // 화면 맨 위 진행 막대: 150ms 넘게 걸릴 때만 보인다 (body를 바꿔도 남도록 <html>에 붙인다)
  const bar = document.createElement('div');
  bar.className = 'nav-progress';
  document.documentElement.appendChild(bar);
  let barTimer = null;
  function progress(on) {
    clearTimeout(barTimer);
    if (on) { barTimer = setTimeout(() => { bar.className = 'nav-progress'; void bar.offsetWidth; bar.className = 'nav-progress on'; }, 150); }
    else if (bar.classList.contains('on')) { bar.className = 'nav-progress done'; }
  }
  // 버튼 안 스피너: 글자를 숨기고 같은 색으로 돈다
  function busy(buttons, on) {
    buttons.forEach(b => {
      if (on) { b.style.setProperty('--spin', getComputedStyle(b).color); b.classList.add('is-loading'); b.disabled = true; }
      else { b.classList.remove('is-loading'); b.disabled = false; }
    });
  }
  const submitButtons = form => [...form.querySelectorAll('button:not([type="button"])'), ...(form.id ? $$(`button[form="${form.id}"]`) : [])];

  /* ---------- 화면 전환: 새로고침 없이 <body>만 바꿔 끼운다 ---------- */
  let pendingToast = '', navToken = 0, swRegistered = false;
  history.scrollRestoration = 'manual';
  if (!history.state || history.state.idx === undefined) history.replaceState({ idx: 0, scroll: 0 }, '', location.href);
  const canGoBack = () => (history.state?.idx || 0) > 0;

  async function load(url, { push = false, scroll = 0, method = 'GET', body = null, quiet = false } = {}) {
    const token = ++navToken;
    if (push) history.replaceState({ ...history.state, scroll: window.scrollY }, '');
    if (!quiet) progress(true);
    let res;
    try {
      res = await fetch(url, { method, body, credentials: 'same-origin',
        headers: { 'X-Requested-With': 'nav', ...(method === 'POST' ? { 'X-CSRFToken': csrf() } : {}) } });
    } catch (_) { progress(false); location.href = url; return; }  // 연결이 끊기면 원래 방식으로(오프라인 안내)
    if (token !== navToken) return;  // 더 나중에 누른 이동이 이긴다
    progress(false);
    if (!(res.headers.get('content-type') || '').includes('text/html')) { location.href = res.url; return; }
    const doc = new DOMParser().parseFromString(await res.text(), 'text/html');
    const finalUrl = res.url;
    // 다른 화면으로 가면 기록을 남기고, 같은 화면(저장 후 새로 고침, 입력 오류)이나 로그인 화면이면 바꿔 쓴다
    const samePage = new URL(finalUrl).pathname === location.pathname && new URL(finalUrl).search === location.search;
    const pushEntry = push || (method === 'POST' && !samePage && !finalUrl.includes('/login/'));
    const apply = () => {
      closePicker(); closeGallery(); openSheet = null;
      document.title = doc.title;
      const theme = doc.documentElement.dataset.theme;
      if (theme) document.documentElement.dataset.theme = theme; else delete document.documentElement.dataset.theme;
      document.body.replaceWith(document.adoptNode(doc.body));
      if (pushEntry) history.pushState({ idx: (history.state?.idx || 0) + 1, scroll: 0 }, '', finalUrl);
      else history.replaceState({ ...history.state, scroll }, '', finalUrl);
      window.scrollTo(0, pushEntry ? 0 : scroll);
      initPage();
    };
    // 다른 화면으로 넘어갈 때만 전환 효과. 같은 화면을 새로 그릴 때는 그 자리에서 조용히 바꾼다
    if (pushEntry && document.startViewTransition && !matchMedia('(prefers-reduced-motion: reduce)').matches) document.startViewTransition(apply);
    else apply();
  }

  // 탭처럼 화면 일부만 바뀌는 링크(data-swap="영역 id"): 그 영역만 바꾸고 스크롤은 그대로 둔다
  async function swapPart(url, id) {
    const token = ++navToken;
    const area = document.getElementById(id);
    if (area) area.classList.add('is-swapping');
    let res;
    try { res = await fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'nav' } }); }
    catch (_) { location.href = url; return; }
    if (token !== navToken) return;
    const doc = new DOMParser().parseFromString(await res.text(), 'text/html');
    const next = doc.getElementById(id), current = document.getElementById(id);
    if (!next || !current) return load(url, { push: true });
    current.replaceWith(document.adoptNode(next));
    history.replaceState({ ...history.state, scroll: window.scrollY }, '', res.url);
  }
  const reloadHere = () => load(location.href, { scroll: window.scrollY });

  window.addEventListener('popstate', e => load(location.href, { scroll: e.state?.scroll || 0 }));

  document.addEventListener('click', e => {
    if (e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
    const a = e.target.closest('a[href]');
    if (!a || (a.target && a.target !== '_self') || a.hasAttribute('download') || 'native' in a.dataset) return;
    const url = new URL(a.href, location.href);
    if (url.origin !== location.origin || /^\/(static|visits\/photos|django-admin|sw\.js|manifest)/.test(url.pathname)) return;
    if (url.hash && url.pathname === location.pathname) return;
    e.preventDefault();
    if ('back' in a.dataset && canGoBack()) return history.back();  // 들어왔던 화면으로
    if (a.dataset.swap) return swapPart(url.href, a.dataset.swap);
    load(url.href, { push: true });
  });

  /* 저장 폼
     data-ajax="back"  : 저장하고 들어왔던 화면으로 돌아간다 (data-back-steps 만큼)
     data-ajax="reload": 저장하고 지금 화면을 새로 그린다
     그 밖의 POST 폼     : 결과 화면으로 바꿔 끼운다 (입력 오류면 같은 화면에 오류가 보인다) */
  document.addEventListener('submit', async e => {
    const form = e.target;
    // form.method 는 이름이 method인 입력칸(측정 부위)에 가려지므로 속성으로 읽는다
    if ((form.getAttribute('method') || 'get').toLowerCase() !== 'post' || 'native' in form.dataset) return;
    e.preventDefault();
    const mode = form.dataset.ajax;
    const buttons = submitButtons(form);
    const body = new FormData(form);  // 버튼을 막기 전에 값을 모은다
    busy(buttons, true);
    if (!mode) return load(form.getAttribute('action') || location.href, { method: 'POST', body, scroll: window.scrollY });
    let data = {};
    try {
      const res = await fetch(form.getAttribute('action') || location.href, { method: 'POST', body,
        headers: { 'X-Requested-With': 'fetch', 'X-CSRFToken': csrf() }, credentials: 'same-origin' });
      data = await res.json();
    } catch (_) { data = { ok: false, error: '연결이 불안정해요. 다시 시도해 주세요' }; }
    if (!data.ok) {
      busy(buttons, false);
      return toast(data.error);
    }
    pendingToast = data.message || '';
    if (mode === 'reload') return reloadHere();
    if (canGoBack()) history.go(-(+form.dataset.backSteps || 1));  // popstate가 그 화면을 새로 받아 온다
    else load(data.next || '/', { push: true });
  });

  /* ---------- 화면마다 준비 ---------- */
  function initPage() {
    $$('.range').forEach(el => { paintRange(el); el.addEventListener('input', () => paintRange(el)); });
    const chartData = $('#chart-data');
    if (chartData) $$('[data-chart]').forEach(el => drawChart(el, JSON.parse(chartData.textContent)));

    tempRange = $('#temp-range');
    if (tempRange) { tempRange.addEventListener('input', renderTemp); renderTemp(); }
    const sheetDataEl = $('#sheet-data');
    SD = sheetDataEl ? JSON.parse(sheetDataEl.textContent) : null;
    ml = null;
    $$('[data-drug-radio]').forEach(r => r.addEventListener('change', () => renderMed(true)));
    if ($('[data-med-page]')) { ml = +$('[data-ml-input]').dataset.initialMl; renderMed(false); }
    const mlSlider = $('[data-ml-slider]');
    if (mlSlider) mlSlider.addEventListener('input', () => { ml = Math.round(+mlSlider.value * 10) / 10; renderMed(false); });

    $$('[data-time-field]').forEach(resetTime);

    titleInput = $('#illness-title');
    if (titleInput) titleInput.addEventListener('input', syncTitleChips);
    const symptomInput = $('[data-symptom-input]');
    if (symptomInput) symptomInput.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); addSymptom(); } });

    photoInput = $('[data-photo-input]');
    photoStore = photoInput ? new DataTransfer() : null;
    if (photoInput) photoInput.addEventListener('change', addPhotos);
    const medToggle = $('[data-medicine-toggle]');
    if (medToggle) medToggle.addEventListener('change', () => { $('[data-medicine-fields]').hidden = !medToggle.checked; });

    const weightText = $('[data-weight-text]');
    if (weightText) {
      weightText.addEventListener('focus', () => weightText.select());
      weightText.addEventListener('input', () => {
        weightText.value = weightText.value.replace(/[^0-9.]/g, '');
        const v = parseFloat(weightText.value);
        if (v >= 1 && v <= 60) stepWeight(0, v);
      });
      // 평소에는 가운데 정렬된 버튼, 누르면 입력칸으로 바뀌고 포커스가 빠지면 다시 버튼으로
      const editBtn = $('[data-weight-edit]'), editor = $('[data-weight-editor]');
      editBtn.addEventListener('click', () => {
        editBtn.hidden = true; editor.hidden = false;
        weightText.value = f1(+$('[data-weight-input]').value);
        weightText.focus();
      });
      weightText.addEventListener('blur', () => {
        weightText.value = f1(+$('[data-weight-input]').value);
        editor.hidden = true; editBtn.hidden = false;
      });
      weightText.addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); weightText.blur(); } });
    }
    const weightSlider = $('[data-weight-slider]');
    if (weightSlider) weightSlider.addEventListener('input', () => stepWeight(0, +weightSlider.value));
    // 아기 등록: 숫자 칸과 슬라이더를 서로 맞춘다
    $$('[data-weight-mirror]').forEach(slider => {
      const input = document.getElementById(slider.dataset.weightMirror);
      slider.addEventListener('input', () => { input.value = f1(+slider.value); });
      input.addEventListener('input', () => { if (input.value) { slider.value = input.value; paintRange(slider); } });
    });

    gp = $('[data-guardian-picker]');
    if (gp) $('#guardian-id').addEventListener('keydown', e => { if (e.key === 'Enter') { e.preventDefault(); addGuardian(); } });

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

    pushRow = $('[data-push-row]');
    if (pushRow && swRegistered) pushState();
    updateKeyboard();

    $$('#flash li').forEach((li, i) => setTimeout(() => toast(li.textContent), 150 + i * 2400));
    if (pendingToast) { const msg = pendingToast; pendingToast = ''; setTimeout(() => toast(msg), 150); }
  }

  /* ---------- service worker + 홈은 1분마다 조용히 새로 고침 ---------- */
  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('/sw.js', { scope: '/' }).catch(() => {})
      .finally(() => { swRegistered = true; if (pushRow) pushState(); });
  } else swRegistered = true;

  // 다른 보호자가 남긴 기록과 교차복용 시간을 반영한다. 입력 중이거나 시트·휠이 열려 있으면 건너뛴다.
  setInterval(() => {
    const typing = document.activeElement && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
    if (location.pathname === '/' && $('#chart-data') && !openSheet && !picker && !$('#gallery') && !typing
        && document.visibilityState === 'visible') load(location.href, { scroll: window.scrollY, quiet: true });
  }, 60e3);

  initPage();
})();
