(() => {
  'use strict';
  const $ = id => document.getElementById(id), root = $('messenger'); if (!root) return;
  const csrf = document.querySelector('#chat-compose [name=csrfmiddlewaretoken]').value;
  let room = null, version = 0, data = null, page = 1, pages = 1, roomRequest = 0, peopleRequest = 0;
  let pending = false, reply = null, editing = null, selected = new Map(), picking = 'new', key = null, lastPayload = null;
  let messages = new Map(), nodes = new Map(), drafts = new Map(), lastRead = 0;
  const node = (tag, text, cls) => { const n = document.createElement(tag); if (text !== undefined) n.textContent = text; if (cls) n.className = cls; return n; };
  const button = (text, fn) => { const b=node('button',text,'chat-action'); b.type='button'; b.onclick=fn; return b; };
  const status = text => { $('chat-status').textContent = text; };
  async function api(url, fields) {
    const body = fields instanceof FormData ? fields : new URLSearchParams(fields || {});
    const r = await fetch(url, fields === undefined ? {credentials:'same-origin'} : {method:'POST',body,credentials:'same-origin',headers:{'X-CSRFToken':csrf}});
    if (r.redirected || !r.headers.get('content-type')?.includes('application/json')) throw Error('Сессия закончилась или сервер недоступен. Обновите страницу.');
    const result = await r.json(); if (!r.ok) throw Error(result.error || 'Действие недоступно. Возможно, состав чата изменился.'); return result;
  }
  const atBottom = () => $('chat-feed').scrollHeight - $('chat-feed').scrollTop - $('chat-feed').clientHeight < 70;
  const bottom = () => { $('chat-feed').scrollTop=$('chat-feed').scrollHeight; $('chat-latest').hidden=true; markRead(); };
  async function markRead() {
    if (!room || !data || !root.classList.contains('has-room') || document.hidden || !document.hasFocus() || !atBottom()) return;
    const id = Math.max(0,...messages.keys()); if (!id || id<=lastRead) return;
    const target=room; lastRead=id;
    try { await api(`/chat/api/rooms/${target}/read/`, {last:id}); }
    catch (_) { if (target===room) lastRead=0; }
  }
  function renderMessage(m) {
    const box=node('article',undefined,`chat-message${m.mine?' mine':''}${m.deleted?' deleted':''}`); box.id=`message-${m.id}`;
    if (m.deleted) {box.append(node('p','Сообщение удалено')); return box;}
    box.append(node('span',m.sender,'chat-author'));
    if (m.reply) box.append(node('div',`${m.reply.sender}: ${m.reply.text}`,'chat-reply'));
    if (m.text) box.append(node('p',m.text,'chat-body'));
    if (m.file) { const a=node('a',`↓ ${m.file.name} · ${Math.ceil(m.file.size/1024)} КБ`,'chat-file-link'); a.href=m.file.url; box.append(a); }
    const foot=node('footer'); foot.append(node('span',new Date(m.created).toLocaleString('ru-RU',{day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})+(m.edited?' · изменено':'')));
    foot.append(button('Ответить',()=>{reply=m; $('reply-bar').hidden=false; $('reply-label').textContent=`${m.sender}: ${(m.text||m.file?.name||'').slice(0,100)}`; $('chat-text').focus();}));
    if(m.mine){
      if (data?.kind==='direct' && data.members.some(x=>x.name!==m.sender && x.read>=m.id)) foot.append(node('span','Прочитано'));
      foot.append(button('Изменить',()=>{editing=m; $('edit-text').value=m.text; $('edit-error').textContent=''; $('chat-edit-dialog').showModal();}));
      foot.append(button('Удалить',async()=>{if(!confirm('Удалить это сообщение и вложение у всех участников?'))return;try{await api(`/chat/api/messages/${m.id}/edit/`,{revision:m.revision,delete:'1'});await loadHistory();}catch(e){status(e.message);}}));
    }
    box.append(foot);return box;
  }
  async function loadRooms() {
    const generation=++roomRequest;
    try {
      const r=await api(`/chat/api/rooms/?page=${page}&q=${encodeURIComponent($('chat-search').value)}`); if(generation!==roomRequest)return;
      pages=r.pages; page=r.page; const frag=document.createDocumentFragment();
      for(const chat of r.rooms){const b=node('button',undefined,`chat-room${chat.id===room?' is-selected':''}`); b.type='button'; b.append(node('span',chat.title.slice(0,1).toUpperCase(),'avatar')); const info=node('span');info.append(node('strong',chat.title),node('small',chat.preview));b.append(info);if(chat.unread)b.append(node('span',`${chat.muted?'· ':''}${chat.unread}`,'chat-count'));b.onclick=()=>openRoom(chat.id);frag.append(b);}
      if(!r.rooms.length)frag.append(node('p','Чаты не найдены.','chat-meta'));
      $('chat-rooms').replaceChildren(frag);$('rooms-page').textContent=`${page} / ${pages}`;$('rooms-prev').disabled=page<=1;$('rooms-next').disabled=page>=pages;
    } catch(e){status(e.message);}
  }
  async function openRoom(id) {
    if(pending)return;
    if(room)drafts.set(room,$('chat-text').value);
    if($('chat-file').files.length && !confirm('Перейти в другой чат? Выбранный файл придётся прикрепить заново.'))return;
    room=Number(id);version=0;data=null;messages=new Map();nodes=new Map();lastRead=0;key=null;lastPayload=null;
    $('chat-messages').replaceChildren();$('chat-text').value=drafts.get(room)||'';$('chat-file').value='';fileChanged();clearReply();
    root.classList.add('has-room');$('chat-welcome').hidden=true;$('chat-open').hidden=false;status('Загрузка…');
    history.replaceState(null,'',`/chat/?room=${room}`);await loadHistory();loadRooms();
  }
  async function loadHistory(older=false) {
    if(!room)return;const target=room, first=!version, min=Math.min(...messages.keys());
    const url=`/chat/api/rooms/${target}/?${older?`before=${min}`:`since=${version}`}`;
    try {
      const r=await api(url);if(target!==room)return;
      const pinned=atBottom(), height=$('chat-feed').scrollHeight, scroll=$('chat-feed').scrollTop;
      const readsChanged=JSON.stringify(data?.members)!==JSON.stringify(r.members);
      data=r;$('chat-title').textContent=r.title;$('chat-info').textContent=`${r.kind==='direct'?'Личный чат':r.kind==='common'?'Общий чат':'Группа'} · ${r.members.length} участников`;
      if(!older)version=r.version;
      if(r.reset){messages.clear();nodes.clear();$('chat-messages').replaceChildren();}
      for(const m of r.messages){messages.set(m.id,m);const n=renderMessage(m);if(nodes.has(m.id))nodes.get(m.id).replaceWith(n);else $('chat-messages').append(n);nodes.set(m.id,n);}
      if(readsChanged)for(const m of messages.values())if(m.mine){const n=renderMessage(m);nodes.get(m.id)?.replaceWith(n);nodes.set(m.id,n);}
      // Order by immutable server ID, including pages loaded from history.
      for(const id of [...nodes.keys()].sort((a,b)=>a-b))$('chat-messages').append(nodes.get(id));
      if(first||older||r.reset)$('chat-older').hidden=!r.has_older;
      if(older)$('chat-feed').scrollTop=scroll+$('chat-feed').scrollHeight-height;
      else if(first||pinned)bottom();else if(r.messages.some(x=>!x.mine))$('chat-latest').hidden=false;
      status('');markRead();
    }catch(e){if(target===room)status(e.message);}
  }
  function clearReply(){reply=null;$('reply-bar').hidden=true;}
  function fileChanged(){const f=$('chat-file').files[0];$('chat-filename').textContent=f?f.name:'До 10 МБ';$('file-clear').hidden=!f;}
  $('chat-file').onchange=fileChanged;$('file-clear').onclick=()=>{$('chat-file').value='';fileChanged();};$('reply-clear').onclick=clearReply;
  $('chat-compose').onsubmit=async e=>{
    e.preventDefault();if(pending||!room)return;const target=room,f=$('chat-file').files[0],text=$('chat-text').value;
    if(f&&f.size>10*1024*1024){status('Файл больше 10 МБ.');return;}
    const signature=JSON.stringify([room,text,reply?.id,f?.name,f?.size,f?.lastModified]);if(signature!==lastPayload){key=crypto.randomUUID();lastPayload=signature;}
    const body=new FormData();body.set('text',text);body.set('key',key);if(reply)body.set('reply',reply.id);if(f)body.set('file',f);
    pending=true;for(const id of ['chat-send','chat-text','chat-file','file-clear'])$(id).disabled=true;status('Отправляем…');
    try{await api(`/chat/api/rooms/${target}/send/`,body);if(room===target){if($('chat-text').value===text)$('chat-text').value='';drafts.set(target,$('chat-text').value);$('chat-file').value='';fileChanged();clearReply();key=null;lastPayload=null;await loadHistory();bottom();}loadRooms();}
    catch(err){status(err.message+' Сообщение осталось в поле ввода.');}
    finally{pending=false;for(const id of ['chat-send','chat-text','chat-file','file-clear'])$(id).disabled=false;}
  };
  $('chat-text').onkeydown=e=>{if((e.ctrlKey||e.metaKey)&&e.key==='Enter'){e.preventDefault();$('chat-compose').requestSubmit();}};
  async function people(){const generation=++peopleRequest;try{const r=await api('/chat/api/people/?q='+encodeURIComponent($('people-search').value));if(generation!==peopleRequest)return;const frag=document.createDocumentFragment();for(const p of r.users){const label=node('label');const input=node('input');input.type='checkbox';input.checked=selected.has(p.id);input.onchange=()=>{if(input.checked)selected.set(p.id,p.name);else selected.delete(p.id);$('people-selected').textContent=[...selected.values()].join(', ');};label.append(input,node('span',`${p.name} · ${p.role}`));frag.append(label);}if(!r.users.length)frag.append(node('p','Пользователи не найдены'));$('people-results').replaceChildren(frag);}catch(e){$('new-error').textContent=e.message;}}
  function picker(mode){picking=mode;selected.clear();$('new-error').textContent='';$('people-selected').textContent='';$('people-search').value='';$('new-title').textContent=mode==='add'?'Добавить участников':'Новый разговор';$('kind-label').hidden=mode==='add';$('new-name-label').hidden=mode==='add'||$('new-kind').value!=='group';$('chat-new-dialog').showModal();people();}
  $('new-chat').onclick=()=>picker('new');$('new-kind').onchange=()=>{$('new-name-label').hidden=$('new-kind').value!=='group';};
  $('chat-new-form').onsubmit=async e=>{e.preventDefault();const submit=e.submitter;submit.disabled=true;try{if(picking==='add'){for(const id of selected.keys())await api(`/chat/api/rooms/${room}/members/`,{action:'add',user:id});$('chat-new-dialog').close();await loadHistory();showMembers();}else{const form=new FormData();form.set('kind',$('new-kind').value);form.set('title',$('new-name').value);for(const id of selected.keys())form.append('users',id);const r=await api('/chat/api/create/',form);$('chat-new-dialog').close();await openRoom(r.id);}}catch(err){$('new-error').textContent=err.message;}finally{submit.disabled=false;}};
  async function memberAction(action,user){try{await api(`/chat/api/rooms/${room}/members/`,{action,user:user||''});if(action==='leave'){location.href='/chat/';return;}await loadHistory();showMembers();loadRooms();}catch(e){$('members-error').textContent=e.message;}}
  function showMembers(){if(!data)return;const frag=document.createDocumentFragment();for(const m of data.members){const row=node('div',undefined,'member-row');row.append(node('span',m.name+(m.owner?' · владелец':'')));if(data.owner&&!m.owner&&data.kind==='group'){row.append(button('Передать управление',()=>{if(confirm(`Передать управление чатом пользователю ${m.name}?`))memberAction('transfer',m.id);}),button('Убрать',()=>memberAction('remove',m.id)));}frag.append(row);}$('members-list').replaceChildren(frag);$('members-add').hidden=!data.owner||data.kind!=='group';$('members-leave').hidden=data.kind!=='group'||data.owner;$('rename-form').hidden=!data.owner||data.kind!=='group';$('rename-title').value=data.title;$('members-mute').textContent=data.muted?'Включить уведомления':'Без уведомлений';$('members-error').textContent='';if(!$('chat-members-dialog').open)$('chat-members-dialog').showModal();}
  $('chat-members').onclick=showMembers;$('members-add').onclick=()=>{$('chat-members-dialog').close();picker('add');};$('members-mute').onclick=()=>memberAction('mute');$('members-leave').onclick=()=>memberAction('leave');
  $('rename-form').onsubmit=async e=>{e.preventDefault();try{await api(`/chat/api/rooms/${room}/members/`,{action:'rename',title:$('rename-title').value});await loadHistory();showMembers();loadRooms();}catch(err){$('members-error').textContent=err.message;}};
  $('edit-form').onsubmit=async e=>{e.preventDefault();try{await api(`/chat/api/messages/${editing.id}/edit/`,{revision:editing.revision,text:$('edit-text').value});$('chat-edit-dialog').close();await loadHistory();}catch(err){$('edit-error').textContent=err.message;}};
  document.querySelectorAll('.work-dialog [data-close]').forEach(b=>b.onclick=()=>b.closest('dialog').close());
  const debounce=(fn,ms)=>{let t;return()=>{clearTimeout(t);t=setTimeout(fn,ms);};};
  $('people-search').oninput=debounce(people,250);$('chat-search').oninput=debounce(()=>{page=1;loadRooms();},250);
  $('rooms-prev').onclick=()=>{page--;loadRooms();};$('rooms-next').onclick=()=>{page++;loadRooms();};$('chat-older').onclick=()=>loadHistory(true);$('chat-latest').onclick=bottom;
  $('chat-back').onclick=()=>root.classList.remove('has-room');$('chat-feed').onscroll=debounce(markRead,200);window.addEventListener('focus',markRead);
  window.addEventListener('beforeunload',e=>{if(pending||$('chat-text').value.trim()||[...drafts.values()].some(x=>x.trim())){e.preventDefault();e.returnValue='';}});
  loadRooms();const initial=Number(new URLSearchParams(location.search).get('room'));if(initial>0)openRoom(initial);
  async function tick(){if(!document.hidden){await loadHistory();}setTimeout(tick,2000);}setTimeout(tick,2000);
  async function roomTick(){if(!document.hidden)await loadRooms();setTimeout(roomTick,8000);}setTimeout(roomTick,8000);
})();
