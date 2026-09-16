/* Local quiz generation: no LLM credentials or hidden answers reach student pages. */
(() => {
 'use strict';
 const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const time=s=>`${Math.floor(s/60)}:${String(Math.floor(s%60)).padStart(2,'0')}`;
 async function api(url,payload){
  const response=await fetch(url,{method:payload===undefined?'GET':'POST',credentials:'same-origin',cache:'no-store',
   headers:{'Content-Type':'application/json','X-CSRFToken':document.querySelector('[name=csrfmiddlewaretoken]')?.value||''},
   body:payload===undefined?undefined:JSON.stringify(payload)});
  if(response.redirected)throw new Error('Сеанс закончился. Войдите на платформу снова.');
  let result;try{result=await response.json();}catch{throw new Error('Сервер недоступен. Проверьте его терминал.');}
  if(!response.ok)throw new Error(result.error||'Не удалось выполнить действие.');
  return result;
 }
 let panelRoot=null,panelStep=null,panelBusy=false,lastStatus='',lastJob=null;
 async function pollPanel(){
  const root=panelRoot,step=panelStep,studio=window.IBStudio;
  if(!root?.isConnected||!studio||panelBusy||document.hidden)return;
  panelBusy=true;
  try{
   const result=await api(`/autoquiz/draft/${studio.id}/`);
   if(root!==panelRoot)return;
   lastJob=result.jobs.find(j=>j.video===step.id&&j.asset===step.asset)||null;
   const signature=JSON.stringify([lastJob,result.worker]);if(signature===lastStatus)return;lastStatus=signature;
   const status=root.querySelector('[data-aq-status]');
   status.innerHTML=lastJob?`<span class="aq-dot ${lastJob.active?'busy':''}"></span><div class="aq-status-copy"><strong>${esc(lastJob.label)}</strong><small>${esc(lastJob.error||lastJob.phase)}</small>${lastJob.active&&!result.worker?'<small class="aq-warning">Обработчик выключен. Запустите autoquiz_worker по инструкции.</small>':''}</div><button type="button" class="button button--ghost" data-aq-open>${lastJob.state==='ready'?'Проверить вопросы':'Открыть обработку'}</button>`:`<div class="aq-status-copy"><strong>${step.asset?'Готово к обработке':'Сначала загрузите видео'}</strong><small>10 вопросов · четыре варианта · объяснения с привязкой ко времени</small></div>`;
   root.querySelector('[data-aq-queue]').hidden=!!lastJob;
   root.querySelector('[data-aq-queue]').disabled=!step.asset;
  }catch(e){if(root===panelRoot)root.querySelector('[data-aq-status]').textContent=e.message;}
  finally{panelBusy=false;}
 }
 window.IBAutoquiz={mount(panel,step,path){
  panelRoot=null;panelStep=null;lastStatus='';lastJob=null;
  if(step.kind!=='video')return;
  const root=document.createElement('section');root.className='aq-box';
  if(document.getElementById('studio-app')?.dataset.aiEnabled!=='1'){
   root.innerHTML='<h3>Тест по лекции</h3><p>Видео сохраняется и воспроизводится без автоматического анализа. Добавьте шаг «Тест» и заполните вопросы в редакторе.</p>';
   panel.append(root);return;
  }
  root.innerHTML=`<h3>Тест по этой лекции</h3><p>Загрузите видео — подготовим вопросы. Вы проверите их перед добавлением в курс.</p><div class="studio-field"><label><input type="checkbox" data-path="${esc(path)}.auto_quiz" ${step.auto_quiz?'checked':''}> Создавать тест автоматически после загрузки видео</label></div><div class="aq-state" data-aq-status role="status" aria-live="polite">Проверяем состояние…</div><button type="button" class="button button--primary" data-aq-queue>Создать 10 вопросов</button><details><summary>У меня есть субтитры или исправленная расшифровка</summary><p class="studio-caption">Загрузите SRT/VTT в UTF-8. Распознавание звука будет пропущено. Для внешних видеоссылок сначала нужен видеофайл на платформе.</p><input type="file" accept=".srt,.vtt" data-aq-subtitles aria-label="Файл субтитров"><button type="button" class="button button--ghost" data-aq-subtitle-queue>Создать тест по субтитрам</button></details><p class="aq-warning" data-aq-error role="alert" hidden></p>`;
  panel.append(root);panelRoot=root;panelStep=step;
  root.addEventListener('click',async event=>{
   const button=event.target.closest('button');if(!button)return;
   const error=root.querySelector('[data-aq-error]');error.hidden=true;
   if(!button.matches('[data-aq-queue],[data-aq-subtitle-queue],[data-aq-open]'))return;
   button.disabled=true;
   try{
    await window.IBStudio.save();
    if(button.hasAttribute('data-aq-open')){if(lastJob)location.href=lastJob.url;return;}
    const payload={video:step.id};
    if(button.hasAttribute('data-aq-subtitle-queue')){
     const file=root.querySelector('[data-aq-subtitles]').files[0];
     if(!file||file.size>1000000)throw new Error('Выберите SRT/VTT до 1 МБ.');
     payload.subtitles=await file.text();
     if(!payload.subtitles.trim())throw new Error('Файл субтитров пуст.');
    }
    const job=await api(`/autoquiz/draft/${window.IBStudio.id}/queue/`,payload);
    lastStatus='';await pollPanel();
    if(button.hasAttribute('data-aq-subtitle-queue'))location.href=job.url;
   }catch(e){error.textContent=e.message;error.hidden=false;}
   finally{button.disabled=false;}
  });
  pollPanel();
 }};
 setInterval(pollPanel,3000);
 document.addEventListener('DOMContentLoaded',()=>{
  const root=document.getElementById('autoquiz-review');if(!root)return;
  let job=JSON.parse(document.getElementById('autoquiz-data').textContent),dirty=false,busy=false,polling=false;
  const base=root.dataset.base,questions=document.getElementById('aq-questions'),status=document.getElementById('aq-work-status'),error=document.getElementById('aq-error');
  const reviewed=document.getElementById('aq-reviewed'),actions=document.getElementById('aq-review-actions');
  const video=document.getElementById('aq-video');
  function fail(e){error.textContent=e.message;error.hidden=false;}
  function renderStatus(){
   const buttons=job.active?'<button type="button" class="button button--ghost" data-aq-control="cancel">Отменить</button>':job.generation_enabled&&['failed','cancelled'].includes(job.state)?'<button type="button" class="button button--ghost" data-aq-control="retry">Повторить</button>':'';
   status.innerHTML=`<strong>${esc(job.label)}</strong> · ${esc(job.error||job.phase)}${buttons}`;
   document.getElementById('aq-transcript').hidden=!job.has_transcript;
  }
  function render(){
   renderStatus();const editable=job.state==='ready';
   questions.innerHTML=job.questions.map((q,i)=>`<fieldset class="aq-question" data-aq-question="${i}"><legend>ВОПРОС ${String(i+1).padStart(2,'0')} / 10</legend><label>Вопрос<textarea data-field="question" maxlength="2000" ${editable?'':'disabled'}>${esc(q.question)}</textarea></label><p class="studio-caption">Отметьте правильный ответ</p>${q.choices.map((c,j)=>`<label class="aq-choice"><input type="radio" name="correct-${i}" value="${j}" aria-label="Правильный вариант ${j+1}" ${q.correct===j?'checked':''} ${editable?'':'disabled'}><input type="text" data-choice="${j}" value="${esc(c)}" maxlength="500" aria-label="Вариант ${j+1}" ${editable?'':'disabled'}></label>`).join('')}<label>Объяснение<textarea data-field="explanation" maxlength="3000" ${editable?'':'disabled'}>${esc(q.explanation)}</textarea></label><blockquote>${esc(q.quote)}</blockquote><div class="aq-question-toolbar"><button type="button" class="button button--ghost" data-aq-seek="${q.start}">Посмотреть в видео · ${time(q.start)}</button>${editable&&job.generation_enabled?`<button type="button" class="tree-add" data-aq-regenerate="${i}">Создать другой вопрос</button>`:''}</div></fieldset>`).join('');
   if(!job.questions.length)questions.innerHTML='<p class="studio-caption">Вопросы появятся после обработки видео. Эту страницу можно закрыть — очередь продолжит работу.</p>';
   actions.hidden=!editable;reviewed.checked=job.reviewed;
   document.getElementById('aq-export').hidden=!job.questions.length;
  }
  function collect(){return job.questions.map((q,i)=>{const el=questions.querySelector(`[data-aq-question="${i}"]`);return {...q,question:el.querySelector('[data-field=question]').value,explanation:el.querySelector('[data-field=explanation]').value,choices:[...el.querySelectorAll('[data-choice]')].map(c=>c.value),correct:Number(el.querySelector('input[type=radio]:checked')?.value??-1)};});}
  async function save(){
   job=await api(base+'save/',{revision:job.revision,questions:collect(),reviewed:reviewed.checked});
   dirty=false;renderStatus();
  }
  root.addEventListener('input',event=>{if(event.target.closest('#aq-review-form')){dirty=true;if(event.target!==reviewed)reviewed.checked=false;}});
  root.addEventListener('click',async event=>{
   const button=event.target.closest('button');if(!button)return;
   if(button.hasAttribute('data-aq-seek')){const position=Number(button.dataset.aqSeek);const seek=()=>{video.currentTime=Number.isFinite(video.duration)?Math.min(position,Math.max(0,video.duration-.1)):position;video.play().catch(()=>{});};if(video.readyState>=1)seek();else{video.addEventListener('loadedmetadata',seek,{once:true});video.load();}video.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth',block:'center'});return;}
   if(button.id==='aq-export'){const url=URL.createObjectURL(new Blob([JSON.stringify(collect(),null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='quiz-review.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;}
   if(busy)return;busy=true;button.disabled=true;error.hidden=true;
   const frozen=[...root.querySelectorAll('#aq-review-form input:not([disabled]),#aq-review-form textarea:not([disabled]),#aq-review-form button:not([disabled])')];
   frozen.forEach(el=>el.disabled=true);
   try{
    if(button.id==='aq-save'){await save();status.textContent='Правки сохранены. '+(job.reviewed?'Тест готов к добавлению.':'Осталось проверить вопросы и отметить подтверждение.');}
    if(button.id==='aq-apply'){
     if(!reviewed.checked)throw new Error('Сначала проверьте вопросы и отметьте подтверждение.');
     await save();const result=await api(base+'apply/',{revision:job.revision,draft_revision:Number(root.dataset.draftRevision)});dirty=false;location.href=result.url;
    }
    if(button.hasAttribute('data-aq-regenerate')){
     await save();job=await api(base+'control/',{revision:job.revision,action:'regenerate',index:Number(button.dataset.aqRegenerate)});dirty=false;location.reload();
    }
    if(button.dataset.aqControl){job=await api(base+'control/',{revision:job.revision,action:button.dataset.aqControl});dirty=false;location.reload();}
   }catch(e){fail(e);}finally{busy=false;button.disabled=false;frozen.forEach(el=>el.disabled=false);}
  });
  document.getElementById('aq-review-form').addEventListener('submit',event=>event.preventDefault());
  window.addEventListener('beforeunload',event=>{if(dirty){event.preventDefault();event.returnValue='';}});
  setInterval(async()=>{
   if(!job.active||polling||busy||document.hidden)return;polling=true;
   try{const result=await api(base+'status/');if(result.state!==job.state&&!result.active){location.reload();return;}job={...job,...result};renderStatus();}catch(e){fail(e);}finally{polling=false;}
  },3000);
  render();
 });
})();
