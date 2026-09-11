(() => {
  'use strict';
  const root = document.getElementById('live-rating');
  if (!root) return;
  const privateView = root.dataset.private === 'true';
  const rows = document.getElementById('rating-rows');
  const status = document.getElementById('rating-status');
  const dialog = document.getElementById('rating-detail');
  const body = document.getElementById('detail-body');
  const course = document.getElementById('rating-course');
  const direction = document.getElementById('rating-direction');
  const csrf = document.querySelector('#rating-csrf input').value;
  let page = 1, pages = 1, selected = null, blockPage = 1, busy = false, dirty = false;
  let generation = 0, lastRows = '', lastDetail = '', detailGeneration = 0;
  const names = {positive: 'Положительная', negative: 'Отрицательная', unknown: 'Нет данных'};
  const zones = {green: 'Зелёная', orange: 'Оранжевая', red: 'Красная', unknown: 'Нет данных'};
  function node(tag, text, cls) {
    const el = document.createElement(tag);
    if (text !== undefined) el.textContent = text;
    if (cls) el.className = cls;
    return el;
  }
  function params() {
    return new URLSearchParams({course: course.value, direction: direction.value, page: String(page), blocks_page: String(blockPage)});
  }
  async function get(url, options = {}) {
    const response = await fetch(url, {...options, credentials: 'same-origin', cache: 'no-store', headers: {'Accept': 'application/json', ...options.headers}});
    if (!response.ok || response.redirected) throw new Error(response.status === 403 || response.redirected ? 'Проверьте вход и права доступа.' : 'Не удалось загрузить данные. Повторим запрос.');
    return response.json();
  }
  function percent(value) { return value === null ? '—' : value.toLocaleString('ru-RU', {minimumFractionDigits: 2, maximumFractionDigits: 2}) + '%'; }
  function renderRows(data) {
    pages = data.pages; page = data.page;
    document.getElementById('rating-page').textContent = `${page} / ${pages} · студентов: ${data.count}`;
    document.getElementById('rating-prev').disabled = page <= 1;
    document.getElementById('rating-next').disabled = page >= pages;
    const encoded = JSON.stringify(data);
    if (encoded === lastRows) return;
    lastRows = encoded;
    const focused = document.activeElement?.dataset.student;
    rows.replaceChildren();
    for (const row of data.rows) {
      const tr = node('tr');
      tr.append(node('td', row.rank));
      const td = node('td');
      const button = node('button', '@' + row.username, 'learning-student' + (privateView ? ' zone-' + row.zone : ''));
      button.type = 'button'; button.dataset.student = row.id;
      button.addEventListener('click', () => openStudent(row.id));
      td.append(button); tr.append(td, node('td', row.points));
      if (privateView) tr.append(node('td', row.positive), node('td', row.negative), node('td', row.unknown), node('td', percent(row.percent) + ' · ' + zones[row.zone]));
      else tr.append(node('td', row.year ? row.year + ' курс' : '—'));
      rows.append(tr);
    }
    if (!data.rows.length) {
      const tr = node('tr'), td = node('td', 'Пока нет студентов в выбранных курсах.');
      td.colSpan = privateView ? 7 : 4; tr.append(td); rows.append(tr);
    }
    if (focused) rows.querySelector(`[data-student="${Number(focused)}"]`)?.focus({preventScroll: true});
  }
  function metrics(data) {
    const el = node('div', undefined, 'learning-metrics');
    el.append(node('span', `Положительные: ${data.positive}`), node('span', `Отрицательные: ${data.negative}`), node('span', `Нет данных: ${data.unknown}`), node('span', `${percent(data.percent)} · ${zones[data.zone]}`, 'zone-' + data.zone));
    return el;
  }
  function renderDetail(data) {
    const encoded = JSON.stringify(data);
    if (encoded === lastDetail) return;
    lastDetail = encoded;
    const expanded = new Set([...body.querySelectorAll('details[data-block][open]')].map(x => x.dataset.block));
    body.replaceChildren();
    document.getElementById('detail-title').textContent = '@' + data.username;
    body.append(node('p', `Пройдено блоков: ${data.points} · баллы: ${data.points}`));
    if (privateView) body.append(metrics(data.summary));
    body.append(node('h3', 'Курсы и прогресс'));
    for (const c of data.courses) {
      const card = node('section', undefined, 'learning-course-result');
      card.append(node('strong', c.title), node('p', `${c.completed} / ${c.total} блоков · ${c.progress}% курса · ${c.points} баллов`));
      if (privateView) card.append(metrics(c));
      body.append(card);
    }
    if (!data.courses.length) body.append(node('p', 'Пока нет курсов.'));
    if (!privateView) return;
    body.append(node('h3', 'Результаты по блокам'));
    for (const block of data.blocks) {
      const detail = node('details', undefined, 'learning-result');
      detail.dataset.block = block.id; detail.open = expanded.has(String(block.id));
      detail.append(node('summary', `${block.title} · ${names[block.verdict]}`));
      detail.append(node('p', `${block.course} / ${block.lesson}`));
      detail.append(node('p', `Время: ${block.seconds === null ? 'неизвестно' : block.seconds + ' с'} · попыток до зачёта: ${block.attempts}`));
      if (block.opened) detail.append(node('p', `Открыт: ${new Date(block.opened).toLocaleString('ru-RU')}. Отправлен: ${new Date(block.submitted).toLocaleString('ru-RU')}.`));
      detail.append(node('p', `Автоматическая отметка: ${names[block.automatic]}${block.rule ? ' · ' + block.rule : ''}`));
      for (const reason of block.reasons) detail.append(node('p', reason));
      if (block.imported) detail.append(node('p', 'Перенесён из M2. Историческое время неизвестно.'));
      if (block.review) detail.append(node('p', `Проверил ${block.review.by}: ${block.review.note}`));
      const form = node('form', undefined, 'learning-review');
      const label = node('label', 'Результат проверки');
      const select = node('select'); select.name = 'verdict';
      for (const [value, text] of Object.entries({...names, reset: 'Вернуть автоматическую отметку'})) {
        const option = node('option', text); option.value = value; option.selected = value === block.verdict; select.append(option);
      }
      label.append(select);
      const noteLabel = node('label', 'Комментарий преподавателя');
      const note = node('textarea'); note.name = 'note'; note.required = true; note.maxLength = 2000;
      noteLabel.append(note);
      const button = node('button', 'Сохранить проверку', 'button button--primary'); button.type = 'submit';
      const feedback = node('p'); feedback.setAttribute('role', 'status');
      form.append(label, noteLabel, button, feedback);
      form.addEventListener('input', () => {dirty = true;});
      form.addEventListener('submit', async event => {
        event.preventDefault(); button.disabled = true;
        try {
          await get(`/analytics/blocks/${block.id}/review/`, {method: 'POST', headers: {'X-CSRFToken': csrf}, body: new FormData(form)});
          dirty = false; lastDetail = ''; await refreshDetail(); lastRows = ''; await refresh();
        } catch (error) {feedback.textContent = error.message;}
        finally {button.disabled = false;}
      });
      detail.append(form); body.append(detail);
    }
    if (!data.blocks.length) body.append(node('p', 'Завершённых блоков пока нет.'));
    const nav = node('div', undefined, 'learning-pagination');
    for (const [text, target, disabled] of [['← Назад', data.blocks_page - 1, data.blocks_page <= 1], ['Далее →', data.blocks_page + 1, data.blocks_page >= data.blocks_pages]]) {
      const button = node('button', text, 'button button--ghost'); button.type = 'button'; button.disabled = disabled;
      button.addEventListener('click', () => {if (dirty && !confirm('Не сохранять комментарий и перейти?')) return; dirty = false; blockPage = target; lastDetail = ''; refreshDetail();});
      nav.append(button);
    }
    nav.append(node('span', `Блоки: страница ${data.blocks_page} / ${data.blocks_pages}`)); body.append(nav);
  }
  async function refreshDetail() {
    if (!selected || !dialog.open || dirty) return;
    const id = selected, token = ++detailGeneration;
    try {
      const data = await get(`${privateView ? '/analytics' : '/rating'}/students/${id}/?${params()}`);
      if (token === detailGeneration && selected === id && dialog.open && !dirty) renderDetail(data);
    } catch (error) {if (token === detailGeneration) status.textContent = error.message;}
  }
  function openStudent(id) {
    selected = id; blockPage = 1; dirty = false; lastDetail = '';
    body.replaceChildren(node('p', 'Загружаем результаты…'));
    dialog.showModal(); refreshDetail();
  }
  document.getElementById('detail-close').addEventListener('click', () => {
    if (dirty && !confirm('Закрыть без сохранения комментария?')) return;
    dialog.close();
  });
  dialog.addEventListener('cancel', event => {if (dirty && !confirm('Закрыть без сохранения комментария?')) event.preventDefault();});
  dialog.addEventListener('close', () => {selected = null; dirty = false; detailGeneration++;});
  async function refresh() {
    if (busy || document.hidden) return;
    busy = true; const token = generation;
    try {
      const data = await get(root.dataset.endpoint + '?' + params());
      if (token === generation) {
        renderRows(data);
        status.textContent = 'Обновлено ' + new Date().toLocaleTimeString('ru-RU');
        await refreshDetail();
      }
    } catch (error) {status.textContent = error.message;}
    finally {busy = false;}
  }
  function change() {page = 1; generation++; lastRows = ''; dialog.close(); refresh();}
  direction.addEventListener('change', () => {
    course.value = '';
    for (const option of course.options) option.hidden = !!option.value && !!direction.value && option.dataset.direction !== direction.value;
    change();
  });
  course.addEventListener('change', change);
  document.getElementById('rating-prev').addEventListener('click', () => {if (page > 1) {page--; generation++; refresh();}});
  document.getElementById('rating-next').addEventListener('click', () => {if (page < pages) {page++; generation++; refresh();}});
  document.addEventListener('visibilitychange', () => {if (!document.hidden) refresh();});
  window.addEventListener('beforeunload', event => {if (dirty) {event.preventDefault(); event.returnValue = '';}});
  refresh(); setInterval(refresh, 2000);
})();
