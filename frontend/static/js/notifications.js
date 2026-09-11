(() => {
  const $=id=>document.getElementById(id);if(!$('notifications-open'))return;
  let shown=[],busy=false;
  async function update(){if(busy||document.hidden)return;busy=true;try{
    const r=await fetch('/notifications/data/',{credentials:'same-origin'});if(!r.ok||r.redirected)return;const d=await r.json();
    for(const [id,n] of [['chat-unread',d.chat_count],['notice-unread',d.notice_count]]){const badge=$(id);if(badge){badge.hidden=!n;badge.textContent=n>99?'99+':n;}}
    if($('notifications-dialog').open){shown=d.notices.map(x=>x.id);const frag=document.createDocumentFragment();for(const n of d.notices){const a=document.createElement('a');a.href=n.url;a.className='notice-item'+(n.read?' read':'');a.textContent=n.text;frag.append(a);}$('notifications-list').replaceChildren(frag);$('notifications-status').textContent=d.notices.length?'Последние 20 уведомлений.':'Новых назначений пока нет.';$('notifications-read').disabled=!d.notices.some(x=>!x.read);}
  }catch(_){if($('notifications-dialog').open)$('notifications-status').textContent='Нет связи с сервером. Попробуйте позже.';}finally{busy=false;}}
  $('notifications-open').onclick=()=>{$('notifications-dialog').showModal();update();};$('notifications-close').onclick=()=>$('notifications-dialog').close();
  $('notifications-read').onclick=async()=>{const b=new URLSearchParams();shown.forEach(x=>b.append('ids',x));try{const r=await fetch('/notifications/read/',{method:'POST',body:b,credentials:'same-origin',headers:{'X-CSRFToken':$('notifications-csrf').querySelector('[name=csrfmiddlewaretoken]').value}});if(!r.ok||r.redirected)throw Error();await update();}catch(_){$('notifications-status').textContent='Не удалось сохранить. Попробуйте ещё раз.';}};
  async function tick(){await update();setTimeout(tick,5000);}tick();
})();
