/* 툴 UI. 빌드 없음. */
const App = (() => {
  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];

  // ---------- 업로드 ----------
  function initUpload() {
    const drop = $('#drop'), input = $('#fileInput'), form = $('#uploadForm');
    if (!drop) return;
    const submit = (file) => {
      if (!file) return;
      if (!/\.png$/i.test(file.name)) { alert('PNG 파일만 올릴 수 있습니다.'); return; }
      const dt = new DataTransfer(); dt.items.add(file); input.files = dt.files;
      drop.classList.add('busy');
      $('.drop-title', drop).textContent = '올리는 중…';
      form.submit();
    };
    input.addEventListener('change', () => submit(input.files[0]));
    ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
    ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
    drop.addEventListener('drop', e => submit(e.dataTransfer.files[0]));
  }

  // ---------- 다중 등록 ----------
  function initBatch(maxFiles) {
    const drop = $('#drop'), input = $('#fileInput'), list = $('#fileList'), actions = $('#batchActions'), sub = $('#dropSub');
    if (!drop) return;
    let files = [];
    const render = () => {
      list.innerHTML = files.map(f => `<li>${f.name} <span class="sz">${(f.size / 1024).toFixed(0)}KB</span></li>`).join('');
      list.hidden = files.length === 0; actions.hidden = files.length === 0;
      sub.textContent = files.length ? `${files.length}장 선택됨 (최대 ${maxFiles}장)` : '폴더에서 여러 파일을 한꺼번에 선택할 수 있습니다.';
      $('#startBtn').textContent = files.length ? `${files.length}장 일괄 처리 시작` : '일괄 처리 시작';
    };
    const addFiles = (fl) => {
      for (const f of fl) {
        if (!/\.png$/i.test(f.name)) continue;
        if (files.some(x => x.name === f.name && x.size === f.size)) continue;
        files.push(f);
      }
      if (files.length > maxFiles) { alert(`한 번에 ${maxFiles}장까지 올릴 수 있습니다. 앞의 ${maxFiles}장만 남깁니다.`); files = files.slice(0, maxFiles); }
      const dt = new DataTransfer(); files.forEach(f => dt.items.add(f)); input.files = dt.files;
      render();
    };
    input.addEventListener('change', () => addFiles(input.files));
    ['dragenter', 'dragover'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.add('over'); }));
    ['dragleave', 'drop'].forEach(ev => drop.addEventListener(ev, e => { e.preventDefault(); drop.classList.remove('over'); }));
    drop.addEventListener('drop', e => addFiles(e.dataTransfer.files));
    $('#clearBtn').addEventListener('click', () => { files = []; input.value = ''; render(); });
    $('#batchForm').addEventListener('submit', () => { $('#startBtn').disabled = true; $('#startBtn').textContent = '올리는 중…'; drop.classList.add('busy'); });
  }

  // ---------- 목록: 처리 중인 카드가 있으면 자동 갱신 ----------
  function initList() {
    const root = $('#list'); if (!root) return;
    const tab = root.dataset.tab;
    const rows = $$('tbody tr');
    if (tab !== 'all') { const vis = rows.filter(r => !r.hidden).length; if (rows.length && !vis) $('#tabEmpty').hidden = false; }
    if (!rows.some(r => r.dataset.status === 'processing')) return;
    const snapshot = JSON.stringify(rows.map(r => r.dataset.status));
    const tick = async () => {
      try {
        const j = await (await fetch('/cards/summary', { cache: 'no-store' })).json();
        const now = JSON.stringify(rows.map(r => {
          const href = r.querySelector('a').getAttribute('href'); const id = href.split('/').pop();
          const st = j.statuses[id]; return (st === 'extracting' || st === 'verifying') ? 'processing' : st;
        }));
        const proc = Object.entries(j.counts).filter(([k]) => k === 'extracting' || k === 'verifying').reduce((a, [, v]) => a + v, 0);
        const pc = $('#procCount'); if (pc) pc.textContent = proc;
        if (now !== snapshot) {
          // 처리 중 탭에서 모두 끝났으면 검수 대기 탭으로 넘어간다 (빈 탭에 남지 않게)
          if (tab === 'processing' && proc === 0) { location.href = '/?tab=review'; return; }
          location.reload(); return;
        }
        if (proc === 0) return;
      } catch (e) { /* 다음 폴링에서 회복 */ }
      setTimeout(tick, 4000);
    };
    setTimeout(tick, 4000);
  }

  // ---------- 진행 폴링 ----------
  function poll(cardId) {
    const titles = { extracting: '초안을 읽는 중입니다', verifying: '이미지의 문구를 다시 읽어 대조하는 중입니다' };
    const order = ['prepare', 'extracting', 'verifying', 'done'];
    let state = null;        // 마지막 status 응답
    let stateAt = 0;         // 응답 받은 시각 (ms)
    const fmt = (sec) => sec < 60 ? `${Math.max(0, Math.round(sec))}초` : `${Math.floor(sec / 60)}분 ${Math.round(sec % 60)}초`;
    const render = () => {
      if (!state) return;
      const st = state.status;
      const idx = order.indexOf(st);
      $$('#steps li').forEach((li, i) => {
        li.classList.toggle('done', i < idx);
        li.classList.toggle('active', i === idx);
      });
      $('#progressTitle').textContent = titles[st] || $('#progressTitle').textContent;
      const elapsed = (state.elapsed || 0) + (Date.now() - stateAt) / 1000;
      const exp = state.expected || { extract: 75, verify: 45 };
      const total = exp.extract + exp.verify;
      // 전체 진행률: 단계별 예상 시간의 비율로 합산. 끝나기 전에는 96% 에서 멈춘다.
      let doneBefore = st === 'verifying' ? exp.extract : 0;
      let cur = Math.min(elapsed, (st === 'verifying' ? exp.verify : exp.extract) * 1.15);
      const pct = Math.min(96, Math.round(((doneBefore + cur) / total) * 100));
      $('#barFill').style.width = pct + '%';
      const remainStage = (st === 'verifying' ? exp.verify : exp.extract) - elapsed;
      const remainTotal = remainStage + (st === 'extracting' ? exp.verify : 0);
      $('#eta').textContent = remainTotal > 0
        ? `이 단계 약 ${fmt(Math.max(remainStage, 0))} · 검수 시작까지 약 ${fmt(remainTotal)} 남음 (최근 처리 평균 기준)`
        : '거의 다 됐습니다. 평소보다 조금 오래 걸리고 있습니다…';
    };
    const tick = async () => {
      try {
        const r = await fetch(`/cards/${cardId}/status`, { cache: 'no-store' });
        const j = await r.json();
        if (j.status === 'review' || j.status === 'done' || j.status === 'failed') {
          $('#barFill').style.width = '100%';
          $$('#steps li').forEach(li => li.classList.add('done'));
          $('#eta').textContent = '완료. 검수 화면으로 이동합니다…';
          setTimeout(() => location.reload(), 600);
          return;
        }
        state = j; stateAt = Date.now(); render();
      } catch (e) { /* 네트워크 일시 오류는 다음 폴링에서 회복 */ }
      setTimeout(tick, 2000);
    };
    setInterval(render, 1000);
    tick();
  }

  // ---------- 검수 ----------
  function initReview(cardId) {
    const root = $('#review'); if (!root) return;
    const img = $('#original'), scroll = $('#imgScroll');
    let zoom = 1;
    const applyZoom = () => { img.style.width = (zoom * 100) + '%'; };
    $('#zoomIn').addEventListener('click', () => { zoom = Math.min(3, zoom + 0.25); applyZoom(); });
    $('#zoomOut').addEventListener('click', () => { zoom = Math.max(1, zoom - 0.25); applyZoom(); });

    // 필드 클릭 → 원본의 대략적 위치로 스크롤
    const fields = $$('.field');
    const focusField = (f) => {
      fields.forEach(x => x.classList.remove('active'));
      f.classList.add('active');
      const a = parseFloat(f.dataset.anchor || '0');
      const y = Math.max(0, a * img.offsetHeight - scroll.clientHeight * 0.3);
      scroll.scrollTo({ top: y, behavior: 'smooth' });
    };
    fields.forEach(f => {
      const ctl = $('input, textarea', f);
      ctl.addEventListener('focus', () => focusField(f));
      f.addEventListener('click', e => { if (e.target === f || e.target.tagName === 'LABEL') { ctl.focus(); } });

      // 강조가 들어간 값은 아래에 굵게 렌더한 미리보기를 보여준다 (태그를 몰라도 결과를 알 수 있게)
      const pv = document.createElement('div'); pv.className = 'em-preview'; f.appendChild(pv);
      const esc = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
      const renderPv = () => {
        const v = ctl.value;
        if (!/<em>/i.test(v)) { pv.hidden = true; return; }
        pv.hidden = false;
        pv.innerHTML = esc(v).replace(/&lt;em&gt;/gi, '<em>').replace(/&lt;\/em&gt;/gi, '</em>');
      };
      renderPv();
      ctl.addEventListener('input', renderPv);

      // 자동 저장 (디바운스 800ms)
      let timer = null, last = ctl.value;
      const state = $('.save-state', f);
      const save = async () => {
        const value = ctl.value;
        if (value === last) return;
        state.textContent = '저장 중…'; state.className = 'save-state saving';
        try {
          const r = await fetch(`/cards/${cardId}/field`, {
            method: 'PATCH', headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ path: f.dataset.path, value })
          });
          const j = await r.json();
          if (!r.ok || !j.ok) throw new Error(j.detail || '저장 실패');
          last = value;
          state.textContent = '저장됨'; state.className = 'save-state saved';
          setTimeout(() => { if (state.textContent === '저장됨') state.textContent = ''; }, 1500);
        } catch (e) {
          state.textContent = e.message || '저장 실패'; state.className = 'save-state error';
        }
      };
      ctl.addEventListener('input', () => { clearTimeout(timer); state.textContent = '수정 중'; state.className = 'save-state'; timer = setTimeout(save, 800); });
      ctl.addEventListener('blur', () => { clearTimeout(timer); save(); });

      // 굵게: 선택 영역을 <em>…</em> 로 감싼다 (이미 감싸져 있으면 벗긴다)
      $('.em-btn', f).addEventListener('mousedown', e => e.preventDefault());
      $('.em-btn', f).addEventListener('click', () => {
        const s = ctl.selectionStart, en = ctl.selectionEnd;
        if (s === en) { alert('강조할 글자를 먼저 드래그해서 선택하세요.'); ctl.focus(); return; }
        const v = ctl.value, sel = v.slice(s, en);
        let out, caret;
        if (/^<em>[\s\S]*<\/em>$/.test(sel)) {
          out = v.slice(0, s) + sel.slice(4, -5) + v.slice(en); caret = en - 9;
        } else {
          out = v.slice(0, s) + '<em>' + sel + '</em>' + v.slice(en); caret = en + 9;
        }
        ctl.value = out; ctl.focus(); ctl.setSelectionRange(s, caret);
        ctl.dispatchEvent(new Event('input'));
      });
    });

    // 미리보기
    const modal = $('#previewModal'), frame = $('#previewFrame');
    $('#previewBtn').addEventListener('click', () => { frame.src = `/cards/${cardId}/preview?t=${Date.now()}`; modal.hidden = false; });
    $('#previewClose').addEventListener('click', () => { modal.hidden = true; frame.src = 'about:blank'; });
    modal.addEventListener('click', e => { if (e.target === modal) { modal.hidden = true; frame.src = 'about:blank'; } });

    // 저장(등록)
    const saveBtn = $('#saveBtn'), dup = $('#dupModal');
    const doSave = async (body) => {
      saveBtn.disabled = true; saveBtn.textContent = '저장 중…';
      try {
        const r = await fetch(`/cards/${cardId}/save`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body || {}) });
        const j = await r.json();
        if (r.status === 409 && j.duplicate) {
          $('#dupName').textContent = (j.duplicate.product_name || '') + (j.duplicate.form || '');
          $('#dupWhen').textContent = '등록일 ' + (j.duplicate.registered_at || '').slice(0, 16).replace('T', ' ');
          $('#dupOpen').dataset.href = `/cards/${j.duplicate.id}`;
          $('#dupRenameBox').hidden = true; $('#dupNewName').value = '';
          dup.hidden = false;
          return;
        }
        if (!r.ok || !j.ok) throw new Error(j.detail || '저장 실패');
        $('#regBadge').textContent = '등록됨 · ' + j.registered_at.slice(0, 16).replace('T', ' ');
        $('#regBadge').className = 'st st-done';
        saveBtn.textContent = '저장됨 ✓';
        setTimeout(() => { saveBtn.textContent = '저장 (수정 반영)'; }, 1500);
      } catch (e) {
        alert(e.message || '저장에 실패했습니다.');
        saveBtn.textContent = '저장';
      } finally { saveBtn.disabled = false; }
    };
    saveBtn.addEventListener('click', () => doSave({}));
    $('#dupCancel').addEventListener('click', () => { dup.hidden = true; saveBtn.textContent = '저장'; });
    // 기존 항목 열기 = 이 초안을 삭제하고 기존 항목으로 이동 (같은 카드가 검수 중으로 남지 않게)
    $('#dupOpen').addEventListener('click', async () => {
      const target = $('#dupOpen').dataset.href;
      $('#dupOpen').disabled = true; $('#dupOpen').textContent = '삭제 중…';
      try {
        const r = await fetch(`/cards/${cardId}/delete`, { method: 'POST', redirect: 'manual' });
        if (!(r.ok || r.type === 'opaqueredirect')) throw new Error('초안 삭제에 실패했습니다.');
        window.onbeforeunload = null;
        location.href = target;
      } catch (e) { alert(e.message); $('#dupOpen').disabled = false; $('#dupOpen').textContent = '기존 항목 열기 (이 초안 삭제)'; }
    });
    $('#dupRename').addEventListener('click', () => { $('#dupRenameBox').hidden = false; $('#dupNewName').focus(); });
    $('#dupRenameSave').addEventListener('click', () => {
      const name = $('#dupNewName').value.trim();
      if (!name) { alert('새 제품명을 입력하세요.'); return; }
      dup.hidden = true;
      doSave({ product_name: name }).then(() => {
        const f = $('.field[data-path="header.product_name"] input'); if (f) f.value = name;
        const h = $('.summary h1'); if (h) h.childNodes[0].textContent = name + ' ';
      });
    });

    // 저장 안 된 수정이 있으면 이탈 경고
    window.addEventListener('beforeunload', e => {
      if ($$('.save-state.saving').length) { e.preventDefault(); e.returnValue = ''; }
    });
  }

  return { initUpload, initBatch, initList, poll, initReview };
})();
