(() => {
 'use strict';
 const root=document.getElementById('study-block'); if(!root)return;
 const initial=JSON.parse(document.getElementById('workspace-data').textContent);
 const csrf=document.querySelector('#workspace-csrf input').value;
 async function api(url,options={}){
   const response=await fetch(url,{credentials:'same-origin',cache:'no-store',...options,headers:{'X-CSRFToken':csrf,...options.headers}});
   if(response.redirected)throw new Error('Сессия закончилась. Сохраните код в файл и войдите снова.');
   let data;try{data=await response.json();}catch{throw new Error('Сервер недоступен. Ваш код остаётся в редакторе.');}
   if(!response.ok){const error=new Error(data.error||'Запрос не выполнен.');error.conflict=response.status===409;throw error;}
   return data;
 }
 const post=(url,data,options={})=>api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data),...options});
 const video=root.querySelector('video');
 if(video){
   let rev=initial.video_revision, stopped=false, inFlight=false, last=initial.position;
   const label=document.createElement('small');label.className='video-save-status';video.after(label);
   const restorePosition=()=>{const position=initial.seek??initial.position;if(position>=0&&Number.isFinite(video.duration))video.currentTime=Math.min(position,Math.max(0,video.duration-.1));};
   video.addEventListener('loadedmetadata',restorePosition,{once:true});
   if(video.readyState>=1)restorePosition();
   async function saveVideo(keepalive=false){
     if(stopped||inFlight||!Number.isFinite(video.currentTime)||Math.abs(video.currentTime-last)<.5)return;
     inFlight=true;const position=video.currentTime;
     try{const result=await post(root.dataset.save,{type:'video',position,revision:rev},{keepalive});rev=result.revision;last=position;label.textContent='Позиция видео сохранена';}
     catch(error){label.textContent=error.message;if(error.conflict)stopped=true;}
     finally{inFlight=false;}
   }
   setInterval(()=>{if(!video.paused)saveVideo();},5000);
   video.addEventListener('pause',()=>saveVideo());video.addEventListener('seeked',()=>saveVideo());
   window.addEventListener('pagehide',()=>saveVideo(true));
 }
 const editor=document.getElementById('practice-editor');if(!editor)return;
 const code=document.getElementById('source-code'),stdin=document.getElementById('program-input'),status=document.getElementById('code-status');
 const run=document.getElementById('code-run'),check=document.getElementById('code-check');
 code.value=initial.code;stdin.value=initial.stdin;
 let revision=initial.revision,generation=0,saved=0,savePromise=null,conflict=false,timer=null,busy=false,page=1,pages=1,pending=null,historyBusy=false,lastHistory='';
 const labels={queued:'В очереди',running:'Проверяется',accepted:'Решение принято',wrong_answer:'Неверный ответ',compile_error:'Ошибка компиляции',runtime_error:'Ошибка выполнения',time_limit:'Превышено время',output_limit:'Слишком большой вывод',run_ok:'Запуск завершён',error:'Ошибка проверки',cancelled:'Отменено'};
 function changed(){generation++;status.textContent='Есть несохранённые изменения';clearTimeout(timer);timer=setTimeout(()=>save().catch(()=>{}),900);}
 code.addEventListener('input',changed);stdin.addEventListener('input',changed);
 code.addEventListener('keydown',event=>{if(event.key==='Tab'){event.preventDefault();code.setRangeText('    ',code.selectionStart,code.selectionEnd,'end');changed();}});
 async function save(){
   if(conflict)throw new Error('Конфликт вкладок: скачайте код и обновите страницу.');
   if(savePromise){await savePromise;if(saved<generation)return save();return;}
   if(saved===generation)return;
   const current=generation;const value={type:'code',code:code.value,stdin:stdin.value,revision};
   status.textContent='Сохраняем…';
   savePromise=post(root.dataset.save,value).then(data=>{revision=data.revision;saved=current;status.textContent=saved===generation?'Сохранено':'Есть несохранённые изменения';}).catch(error=>{if(error.conflict)conflict=true;status.textContent=error.message;throw error;});
   try{await savePromise;}finally{savePromise=null;}
   if(saved<generation)return save();
 }
 document.getElementById('code-save').addEventListener('click',()=>save().catch(()=>{}));
 document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();save().catch(()=>{});}});
 document.getElementById('code-download').addEventListener('click',()=>{const url=URL.createObjectURL(new Blob([code.value],{type:'text/plain;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='solution.cpp';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
 window.addEventListener('beforeunload',event=>{if(saved<generation){event.preventDefault();event.returnValue='';}});
 async function send(mode){
   if(busy)return;busy=true;run.disabled=check.disabled=true;
   try{
     await save();
     const snapshot={mode,code:code.value,stdin:stdin.value};
     const signature=JSON.stringify(snapshot);
     if(!pending||pending.signature!==signature)pending={signature,key:crypto.randomUUID()};
     const result=await post(editor.dataset.submit,{...snapshot,key:pending.key});pending=null;
     document.getElementById('practice-result').textContent=labels[result.status]||result.status;
     page=1;lastHistory='';await poll();
   }catch(error){document.getElementById('practice-result').textContent=error.message;}
   finally{busy=false;run.disabled=check.disabled=false;}
 }
 run.addEventListener('click',()=>send('run'));check.addEventListener('click',()=>send('check'));
 function node(tag,text,cls){const el=document.createElement(tag);el.textContent=text;if(cls)el.className=cls;return el;}
 async function showSource(id){
   try{const data=await api(`/submissions/${id}/source/`);if(!confirm('Заменить код редактора этой отправкой? Текущий код можно предварительно скачать.'))return;code.value=data.code;stdin.value=data.stdin;changed();}
   catch(error){status.textContent=error.message;}
 }
 async function cancel(id){try{await post(`/submissions/${id}/cancel/`,{});lastHistory='';await poll();}catch(error){status.textContent=error.message;}}
 async function poll(){
   if(historyBusy||document.hidden)return;historyBusy=true;const requested=page;
   try{
     const data=await api(editor.dataset.history+'?page='+page);if(requested!==page)return;
     document.getElementById('runner-state').textContent=data.available?'Проверка доступна':'Обработчик выключен';
     if(data.done){document.getElementById('practice-result').textContent='✓ Блок пройден. За него начислен 1 балл.';document.getElementById('practice-result').className='practice-success';}
     document.querySelectorAll('[data-course-percent]').forEach(el=>el.textContent=`Пройдено ${data.progress}% курса`);
     pages=data.pages;page=data.page;
     document.getElementById('history-page').textContent=`${page} / ${pages}`;
     document.getElementById('history-prev').disabled=page<=1;document.getElementById('history-next').disabled=page>=pages;
     const encoded=JSON.stringify(data.items);if(encoded===lastHistory)return;lastHistory=encoded;
     const list=document.getElementById('submission-list');list.replaceChildren();
     for(const item of data.items){
       const row=node('div','','submission-row');row.append(node('small',new Date(item.submitted).toLocaleString('ru-RU')),node('strong',(item.mode==='run'?'Запуск · ':'Проверка · ')+(labels[item.status]||item.status)),node('span',item.total?`${item.passed}/${item.total}`:''));
       const src=node('button','Открыть код','button button--ghost');src.type='button';src.addEventListener('click',()=>showSource(item.id));row.append(src);
       if(['queued','running'].includes(item.status)){const b=node('button','Отменить','button button--ghost');b.type='button';b.addEventListener('click',()=>cancel(item.id));row.append(b);}
       const details=node('details','');details.append(node('summary','Вывод и сообщения'));details.append(node('pre',(item.stdout||'')+(item.diagnostic?'\n'+item.diagnostic:''),'task-output'));row.append(details);list.append(row);
     }
     if(!data.items.length)list.append(node('p','Отправок пока нет.'));
   }catch(error){document.getElementById('runner-state').textContent=error.message;}
   finally{historyBusy=false;}
 }
 document.getElementById('history-prev').addEventListener('click',()=>{page=Math.max(1,page-1);lastHistory='';poll();});
 document.getElementById('history-next').addEventListener('click',()=>{page=Math.min(pages,page+1);lastHistory='';poll();});
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll();});
 poll();setInterval(poll,2000);
})();
