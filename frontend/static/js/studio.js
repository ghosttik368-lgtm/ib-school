/* M2 editor. Server owns permissions, sanitization, revisions and publication. */
document.addEventListener('DOMContentLoaded', () => {
 'use strict';
 const $=(s,root=document)=>root.querySelector(s);
 const token=$('[name=csrfmiddlewaretoken]')?.value;
 const escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const uid=()=>crypto.randomUUID().replaceAll('-','');
 async function request(url,data){
  const res=await fetch(url,{method:data===undefined?'GET':'POST',credentials:'same-origin',headers:{'X-CSRFToken':token,'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});
  let result;try{result=await res.json();}catch{throw new Error(res.status===403?'Нет доступа или истёк сеанс. Обновите страницу.':'Сервер не ответил ожидаемым образом. Проверьте соединение.');}
  if(!res.ok){const error=new Error(result.error||'Не удалось выполнить действие.');error.payload=result;throw error;}return result;
 }
 const create=$('#create-course');
 if(create){create.addEventListener('click',async()=>{create.disabled=true;try{location.href=(await request('/studio/create/',{})).url;}catch(e){$('#dashboard-error').textContent=e.message;create.disabled=false;}});return;}
 if(!$('#studio-data'))return;
 let packet=JSON.parse($('#studio-data').textContent),data=packet.data,revision=packet.revision;
 const directions=JSON.parse($('#studio-directions').textContent),base=`/studio/${packet.id}/`,assets=new Map(packet.assets.map(a=>[a.id,a]));
 const kinds={text:['Статья','Текст, изображения и блоки кода'],video:['Видеолекция','Файл MP4/WebM или внешняя ссылка'],pdf:['PDF','Документ для просмотра в уроке'],presentation:['Презентация','PPT/PPTX и PDF для просмотра'],document:['Документ','Word и PDF для просмотра'],link:['Ссылка','Внешний материал'],quiz:['Тест','Один, несколько или короткий ответ'],code:['Задача C++','Условие, код, тесты и лимиты']};
 let selected=new URLSearchParams(location.search).get('step')||'course',timer,dirty=false,generation=0,saving=null,conflicted=false,uploading=0;
 let wizard=new URLSearchParams(location.search).has('wizard')?0:null;
 const panel=$('#editor-panel'),tree=$('#course-tree'),dialog=$('#studio-dialog');
 function status(text,failed=false){$('#save-status').textContent=text;$('#save-status').classList.toggle('failed',failed);}
 function error(e){$('#studio-error').hidden=false;$('#studio-error').textContent=e.message||e; if(e.payload?.conflict){conflicted=true;$('#conflict-actions').hidden=false;}status('Не сохранено',true);}
 function clearError(){$('#studio-error').hidden=true;}
 function touch(){dirty=true;generation++;status('Есть несохранённые изменения');clearTimeout(timer);timer=setTimeout(()=>save().catch(error),900);}
 async function save(){
  clearTimeout(timer);if(conflicted)throw new Error('Сначала разрешите конфликт версий.');
  if(saving){await saving;if(dirty)return save();return;}
  if(!dirty)return;
  const sent=generation,payload=structuredClone(data);status('Сохраняем…');
  saving=request(base+'data/',{revision,data:payload});
  try{const result=await saving;revision=result.revision;if(sent===generation)dirty=false;status(dirty?'Есть новые изменения':`Сохранено в ${new Date(result.updated).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit'})}`);clearError();}
  catch(e){error(e);throw e;}finally{saving=null;}
  if(dirty)return save();
 }
 function find(id){
  if(id==='course')return {type:'course',obj:data,path:''};
  for(let si=0;si<data.sections.length;si++){const sec=data.sections[si],sp=`sections.${si}`;
   if(sec.id===id)return {type:'section',obj:sec,path:sp,list:data.sections,index:si};
   for(let li=0;li<sec.lessons.length;li++){const les=sec.lessons[li],lp=`${sp}.lessons.${li}`;
    if(les.id===id)return {type:'lesson',obj:les,path:lp,list:sec.lessons,index:li};
    for(let i=0;i<les.steps.length;i++)if(les.steps[i].id===id)return {type:'step',obj:les.steps[i],path:`${lp}.steps.${i}`,list:les.steps,index:i};
   }
  }return null;
 }
 function set(path,value){const bits=path.split('.');let obj=data;while(bits.length>1)obj=obj[bits.shift()];obj[bits[0]]=value;}
 const input=(label,path,value,opts='')=>`<div class="studio-field"><label>${escape(label)}<input data-path="${path}" value="${escape(value)}" ${opts}></label></div>`;
 const area=(label,path,value,extra='')=>`<div class="studio-field"><label>${escape(label)}<textarea data-path="${path}" ${extra}>${escape(value)}</textarea></label></div>`;
 const num=(label,path,value,min,max)=>input(label,path,value,`type="number" data-number min="${min}" max="${max}"`);
 const check=(label,path,value)=>`<div class="studio-field"><label><input type="checkbox" data-path="${path}" ${value?'checked':''}> ${escape(label)}</label></div>`;
 const select=(label,path,value,options)=>`<div class="studio-field"><label>${escape(label)}<select data-path="${path}">${options.map(([v,t])=>`<option value="${v}" ${String(v)===String(value)?'selected':''}>${escape(t)}</option>`).join('')}</select></label></div>`;
 function assetBox(path,id,label,accept){const asset=assets.get(id);return `<div class="upload-box"><strong>${label}</strong>${asset?`<a class="upload-name" href="${asset.url}" target="_blank" rel="noopener">${escape(asset.name)}</a><button class="tree-add" data-remove-file="${path}">Убрать из шага</button>`:''}<input type="file" data-upload="${path}" accept="${accept}" aria-label="${label}"><progress class="upload-progress" max="100" value="0" hidden></progress><span class="upload-name" data-upload-status></span><button class="tree-add" data-cancel-upload hidden>Отменить загрузку</button><button class="tree-add" data-retry-upload hidden>Повторить загрузку</button></div>`;}
 function metadata(which=null){
  let parts=[select('Направление','direction',data.direction,[[0,'Выберите направление'],...directions.map(d=>[d.id,d.name])]),select('Сложность','level',data.level,[['beginner','Начальный'],['basic','Базовый'],['advanced','Продвинутый']]),input('Название курса','title',data.title,'maxlength="180"'),input('Краткое описание','summary',data.summary,'maxlength="260"')+area('Чему научится студент','description',data.description,'maxlength="20000"'),assetBox('cover',data.cover,'Обложка курса (до 10 МБ)','.jpg,.jpeg,.png,.webp')+(data.cover?`<img class="wizard-cover" src="/studio/assets/${data.cover}/" alt="Обложка курса">`:'<p class="studio-caption">Обложку можно добавить позже.</p>')];
  return which===null?parts.join(''):parts[which];
 }
 function row(obj,type){return `<div class="tree-row ${selected===obj.id?'selected':''}" draggable="true" data-drag="${obj.id}"><button class="tree-title" data-select="${obj.id}">${escape(obj.title||'Без названия')}</button><span class="tree-tools"><button data-up="${obj.id}" title="Выше" aria-label="Переместить выше">↑</button><button data-down="${obj.id}" title="Ниже" aria-label="Переместить ниже">↓</button></span></div>`;}
 function renderTree(){tree.innerHTML=data.sections.map(s=>`<section class="tree-section">${row(s,'section')}${s.lessons.map(l=>`<div class="tree-lesson">${row(l,'lesson')}${l.steps.map(st=>`<div class="tree-step">${row(st,'step')}</div>`).join('')}</div>`).join('')}<button class="tree-add" data-add-lesson="${s.id}">+ Добавить урок</button></section>`).join('');$('#course-heading').textContent=data.title||'Курс без названия';}
 function controls(obj){return `<div class="studio-actions"><button class="button button--ghost" data-duplicate="${obj.id}">Создать копию</button><button class="button button--danger" data-delete="${obj.id}">Удалить</button></div>`;}
 function questions(step,path){return num('Проходной результат, %',path+'.passing',step.passing??100,1,100)+'<p class="studio-caption">За прохождение блока начисляется 1 балл.</p>'+(step.questions||[]).map((q,i)=>{
  const qp=`${path}.questions.${i}`;
  return `<section class="question-card"><div class="question-head"><strong>Вопрос ${i+1}</strong><button class="tree-add" data-delete-question="${i}">Удалить вопрос</button></div>${select('Тип вопроса',qp+'.type',q.type,[['single','Один правильный ответ'],['multiple','Несколько правильных ответов'],['short','Короткий ответ']])}${area('Условие',qp+'.text',q.text)}${q.type==='short'?area('Допустимые ответы — каждый с новой строки',qp+'.answers',(q.answers||[]).join('\n'),'data-lines')+check('Учитывать регистр букв',qp+'.case_sensitive',q.case_sensitive):`<p class="studio-caption">Отметьте правильные варианты. Для одного ответа — ровно один.</p>${q.choices.map((c,ci)=>`<div class="choice-row"><input type="checkbox" aria-label="Вариант ${ci+1} правильный" data-path="${qp}.choices.${ci}.correct" ${c.correct?'checked':''}><input type="text" aria-label="Вариант ${ci+1}" data-path="${qp}.choices.${ci}.text" value="${escape(c.text)}" maxlength="500"><button class="tree-add" data-delete-choice="${i}:${ci}" aria-label="Удалить вариант">×</button></div>`).join('')}<button class="tree-add" data-add-choice="${i}">+ Вариант ответа</button>`}${area('Объяснение после попытки',qp+'.explanation',q.explanation||'')}</section>`;
 }).join('')+`<button class="button button--ghost" id="add-question">+ Добавить вопрос</button>`;}
 function codeSettings(step,path){const c=step.code||{};const p=path+'.code';return `<div class="studio-warning">C++20. Добавьте условие и скрытые тесты. Проверка сравнивает слова и числа в выводе без учёта разделяющих пробелов.</div>`+area('Условие задачи',p+'.statement',c.statement||'')+area('Формат ввода',p+'.input_format',c.input_format||'')+area('Формат вывода',p+'.output_format',c.output_format||'')+area('Примеры ввода и вывода',p+'.examples',c.examples||'')+area('Стартовый код C++20',p+'.starter',c.starter||'','class="code-field" spellcheck="false"')+`<details><summary>Закрытая проверка — видна только преподавателю</summary>`+area('Эталонное решение',p+'.solution',c.solution||'','class="code-field" spellcheck="false"')+`<div class="field-row">${num('Лимит времени, сек.',p+'.time',c.time??2,1,10)}${num('Память, МБ',p+'.memory',c.memory??128,16,512)}</div>`+(c.tests||[]).map((t,i)=>`<div class="question-card"><div class="question-head"><strong>Скрытый тест ${i+1}</strong><button class="tree-add" data-delete-test="${i}">Удалить</button></div>${area('Ввод',`${p}.tests.${i}.input`,t.input,'class="code-field"')}${area('Ожидаемый вывод',`${p}.tests.${i}.output`,t.output,'class="code-field"')}</div>`).join('')+`<button class="button button--ghost" id="add-hidden-test">+ Скрытый тест</button></details>`+'<p class="studio-caption">За прохождение блока начисляется 1 балл.</p>';}
 function render(){
  renderTree();if(wizard!==null){renderWizard();return;}
  let item=find(selected);if(!item){selected='course';item=find(selected);}
  const {type,obj,path}=item;
  if(type==='course'){panel.innerHTML=`<span class="editor-label">Настройки</span><h2 class="editor-title">О курсе</h2>${metadata()}<p class="studio-caption">Правки попадут к новым студентам только после публикации новой версии. Текущие студенты остаются на своей программе.</p>`;return;}
  if(type==='section'){panel.innerHTML=`<span class="editor-label">Раздел</span><h2 class="editor-title">${escape(obj.title)}</h2>${input('Название раздела',path+'.title',obj.title,'maxlength="180"')}<button class="button button--primary" data-add-lesson="${obj.id}">+ Добавить урок</button>${controls(obj)}`;return;}
  if(type==='lesson'){panel.innerHTML=`<span class="editor-label">Урок</span><h2 class="editor-title">${escape(obj.title)}</h2>${input('Название урока',path+'.title',obj.title,'maxlength="180"')}${area('Краткое описание',path+'.summary',obj.summary)}${check('Урок доступен студентам',path+'.active',obj.active!==false)}<h3>Добавить шаг</h3><div class="step-types">${Object.entries(kinds).map(([k,v])=>`<button class="step-type" data-add-step="${k}"><strong>${v[0]}</strong><span>${v[1]}</span></button>`).join('')}</div>${controls(obj)}`;return;}
  let content='';
  if(obj.kind==='text')content=`<div class="editor-toolbar" role="toolbar" aria-label="Форматирование статьи"><button data-format="bold"><b>Ж</b></button><button data-format="italic"><i>К</i></button><button data-format="formatBlock" data-value="h2">Заголовок</button><button data-format="formatBlock" data-value="p">Абзац</button><button data-format="insertUnorderedList">Список</button><button data-format="formatBlock" data-value="pre">Код</button><button id="insert-link">Ссылка</button><button id="insert-image">Изображение</button></div><div class="rich-editor article-content" contenteditable="true" role="textbox" aria-multiline="true" aria-label="Текст статьи" data-rich-path="${path}.html">${obj.html||''}</div><div class="upload-box" id="article-upload" hidden><input type="file" data-upload="image" accept=".jpg,.jpeg,.png,.webp" aria-label="Изображение для статьи"><progress max="100" value="0" hidden></progress><span data-upload-status></span><button class="tree-add" data-cancel-upload hidden>Отменить</button><button class="tree-add" data-retry-upload hidden>Повторить</button></div>`;
  else if(obj.kind==='quiz')content=questions(obj,path);
  else if(obj.kind==='code')content=codeSettings(obj,path);
  else{
   if(obj.kind!=='link'){const accepts={video:'.mp4,.webm',pdf:'.pdf',presentation:'.ppt,.pptx',document:'.doc,.docx'};content+=assetBox(path+'.asset',obj.asset,'Файл материала (до 500 МБ)',accepts[obj.kind]);}
   if(['video','link'].includes(obj.kind))content+=input('Внешняя ссылка',path+'.url',obj.url,'type="url" placeholder="https://"');
   if(['presentation','document'].includes(obj.kind))content+=`<p class="studio-caption">Офисный документ доступен для скачивания. Для просмотра внутри урока прикрепите PDF.</p>`+assetBox(path+'.viewer',obj.viewer,'PDF для встроенного просмотра (необязательно)','.pdf');
  }
  panel.innerHTML=`<span class="editor-label">${kinds[obj.kind][0]}</span><h2 class="editor-title">${escape(obj.title)}</h2>${input('Название шага',path+'.title',obj.title,'maxlength="180"')}${check('Обязательный шаг',path+'.required',obj.required!==false)}${content}${controls(obj)}`;
  window.IBAutoquiz?.mount(panel,obj,path);
 }
 function renderWizard(){const titles=['Выберите направление','Определите сложность','Назовите курс','Опишите результат','Добавьте обложку','Проверьте основу курса'];panel.innerHTML=`<span class="editor-label">Создание курса · ${wizard+1} из 6</span><div class="wizard-progress">${titles.map((_,i)=>`<span class="${i<=wizard?'done':''}"></span>`).join('')}</div><h2 class="editor-title">${titles[wizard]}</h2>${wizard<5?metadata(wizard):`<h3>${escape(data.title)}</h3><p>${escape(directions.find(d=>d.id===data.direction)?.name||'Направление не выбрано')}</p><p>${escape(data.description)}</p><p class="studio-caption">Это черновик. После завершения можно добавить уроки и материалы.</p>`}<div class="studio-actions">${wizard>0?'<button class="button button--ghost" id="wizard-back">← Назад</button>':''}<button class="button button--primary" id="wizard-next">${wizard===5?'Перейти к урокам':'Далее →'}</button></div>`;}
 function newStep(kind){return {id:uid(),title:kinds[kind][0],kind,auto_quiz:kind==='video',required:true,html:'',url:'',asset:null,viewer:null,points:1,passing:100,questions:[],code:{statement:'',input_format:'',output_format:'',examples:'',starter:'#include <iostream>\n\nint main() {\n    return 0;\n}\n',solution:'',time:2,memory:128,tests:[]}};}
 function structural(action){if(uploading){error('Дождитесь загрузки или отмените её.');return;}action();touch();render();}
 function selectItem(id){if(uploading){error('Дождитесь загрузки или отмените её.');return;}wizard=null;selected=id;render();}
 function modal(html){$('#dialog-content').innerHTML=html;dialog.showModal();}
 async function confirmAction(title,message){return new Promise(resolve=>{modal(`<h2>${escape(title)}</h2><p>${escape(message)}</p><div class="studio-actions"><button class="button button--primary" id="confirm-action">Подтвердить</button><button class="button button--ghost" id="cancel-action">Отмена</button></div>`);let done=false;const finish=v=>{if(done)return;done=true;dialog.removeEventListener('close',cancel);dialog.close();resolve(v);};const cancel=()=>finish(false);dialog.addEventListener('close',cancel);$('#confirm-action').onclick=()=>finish(true);$('#cancel-action').onclick=()=>finish(false);});}
 function move(id,offset){const item=find(id);if(!item?.list)return;const dest=item.index+offset;if(dest<0||dest>=item.list.length)return;structural(()=>{[item.list[item.index],item.list[dest]]=[item.list[dest],item.list[item.index]];});}
 function clone(obj){const copy=structuredClone(obj);function ids(o){if(o&&typeof o==='object'){if('id'in o)o.id=uid();Object.values(o).forEach(ids);}}ids(copy);copy.title+=' — копия';return copy;}
 document.addEventListener('input',event=>{const el=event.target;if(!el.closest('#editor-panel'))return;
  if(el.dataset.richPath){set(el.dataset.richPath,el.innerHTML);touch();return;}
  if(!el.dataset.path)return;let value=el.type==='checkbox'?el.checked:el.value;
  if(el.hasAttribute('data-number')||el.dataset.path==='direction')value=Number(value);
  if(el.hasAttribute('data-lines'))value=value.split('\n');
  set(el.dataset.path,value);touch();renderTree();
 });
 document.addEventListener('change',event=>{if(event.target.matches('select[data-path$=".type"]'))render();});
 document.addEventListener('paste',event=>{if(event.target.closest('[contenteditable]')){event.preventDefault();document.execCommand('insertText',false,event.clipboardData.getData('text/plain'));}});
 document.addEventListener('drop',event=>{if(event.target.closest('[contenteditable]'))event.preventDefault();});
 panel.addEventListener('mousedown',event=>{if(event.target.closest('[data-format],#insert-link,#insert-image'))event.preventDefault();});
 document.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button)return;
  try{
   if(button.dataset.select){selectItem(button.dataset.select);return;}
   if(button.dataset.up){move(button.dataset.up,-1);return;}if(button.dataset.down){move(button.dataset.down,1);return;}
   if(button.dataset.addLesson){structural(()=>{const sec=find(button.dataset.addLesson).obj;const total=data.sections.reduce((n,s)=>n+s.lessons.length,0);const lesson={id:uid(),title:`Урок ${total+1}`,summary:'',steps:[]};sec.lessons.push(lesson);selected=lesson.id;wizard=null;});return;}
   if(button.dataset.addStep){structural(()=>{const step=newStep(button.dataset.addStep);find(selected).obj.steps.push(step);selected=step.id;});return;}
   if(button.dataset.duplicate){structural(()=>{const i=find(button.dataset.duplicate),copy=clone(i.obj);i.list.splice(i.index+1,0,copy);selected=copy.id;});return;}
   if(button.dataset.delete){if(await confirmAction('Удалить из черновика?','Опубликованная версия и результаты студентов сохранятся.'))structural(()=>{const i=find(button.dataset.delete);i.list.splice(i.index,1);selected='course';});return;}
   if(button.dataset.removeFile){structural(()=>set(button.dataset.removeFile,null));return;}
   if(button.dataset.format){document.execCommand(button.dataset.format,false,button.dataset.value||null);const rich=$('[contenteditable]',panel);set(rich.dataset.richPath,rich.innerHTML);touch();return;}
   if(button.id==='insert-link'){const link=prompt('Адрес ссылки (https://)');if(link){const u=new URL(link);if(!['http:','https:'].includes(u.protocol))throw new Error('Разрешены только ссылки http/https.');document.execCommand('createLink',false,u.href);const rich=$('[contenteditable]',panel);set(rich.dataset.richPath,rich.innerHTML);touch();}return;}
   if(button.id==='insert-image'){$('#article-upload').hidden=false;$('#article-upload input').click();return;}
   if(button.id==='add-question'){structural(()=>find(selected).obj.questions.push({id:uid(),type:'single',text:'',explanation:'',answers:[],case_sensitive:false,choices:[{text:'',correct:true},{text:'',correct:false}]}));return;}
   if(button.dataset.deleteQuestion!==undefined){structural(()=>find(selected).obj.questions.splice(Number(button.dataset.deleteQuestion),1));return;}
   if(button.dataset.addChoice!==undefined){structural(()=>find(selected).obj.questions[Number(button.dataset.addChoice)].choices.push({text:'',correct:false}));return;}
   if(button.dataset.deleteChoice){structural(()=>{const [q,c]=button.dataset.deleteChoice.split(':').map(Number);find(selected).obj.questions[q].choices.splice(c,1);});return;}
   if(button.id==='add-hidden-test'){structural(()=>find(selected).obj.code.tests.push({input:'',output:''}));return;}
   if(button.dataset.deleteTest!==undefined){structural(()=>find(selected).obj.code.tests.splice(Number(button.dataset.deleteTest),1));return;}
   if(button.id==='add-section'){structural(()=>{const sec={id:uid(),title:`Раздел ${data.sections.length+1}`,lessons:[]};data.sections.push(sec);selected=sec.id;wizard=null;});return;}
   if(button.id==='course-settings'){selectItem('course');return;}
   if(button.id==='wizard-back'){wizard--;render();return;}
   if(button.id==='wizard-next'){
    if(uploading)throw new Error('Дождитесь загрузки обложки.');
    if(wizard===0&&!data.direction)throw new Error('Выберите направление.');
    if(wizard===2&&!data.title.trim())throw new Error('Введите название.');
    if(wizard===3&&!data.description.trim())throw new Error('Опишите результаты обучения.');
    await save();if(wizard===5){wizard=null;history.replaceState(null,'',base);selected=data.sections[0]?.id||'course';}else wizard++;render();return;
   }
   if(button.id==='save-now'){await save();return;}
   if(button.id==='preview-course'){if(uploading)throw new Error('Дождитесь загрузки файла.');await save();location.href=base+'preview/';return;}
   if(button.id==='publish-course'){
    if(uploading)throw new Error('Дождитесь загрузки файла.');await save();const check=await request(base+'validate/',{});
    if(check.errors.length){modal('<h2>Что осталось заполнить</h2>'+check.errors.map(e=>`<button class="validation-item" data-target="${escape(e.target)}">${escape(e.message)}</button>`).join(''));return;}
    if(await confirmAction('Опубликовать новую версию?','Она появится в каталоге. Уже записанные студенты продолжат свою прежнюю программу.')){
     button.disabled=true;const result=await request(base+'publish/',{revision});revision=result.revision;packet.published_revision=revision;status('Опубликовано');modal(`<h2>Курс опубликован</h2><p>Версия доступна в каталоге.</p><a class="button button--primary" href="${escape(result.url)}">Открыть курс</a>`);
    }return;
   }
   if(button.dataset.target){dialog.close();selectItem(button.dataset.target);return;}
   if(button.id==='archive-course'){await save();if(await confirmAction(packet.archived?'Вернуть курс?':'Убрать курс в архив?','История обучения и материалы уже записанных студентов сохранятся.')){await request(base+'archive/',{revision});location.href='/management/';}return;}
   if(button.id==='export-local'){const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='course-draft-local.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);return;}
   if(button.id==='reload-server'){if(await confirmAction('Загрузить сохранённую версию?','Несохранённые правки этой вкладки будут заменены. Сначала скачайте их копию, если они нужны.')){packet=await request(base+'data/');data=packet.data;revision=packet.revision;packet.assets.forEach(a=>assets.set(a.id,a));dirty=false;conflicted=false;$('#conflict-actions').hidden=true;clearError();status('Загружена актуальная версия');render();}return;}
  }catch(e){error(e);if(e.payload?.errors)modal('<h2>Проверьте курс</h2>'+e.payload.errors.map(x=>`<button class="validation-item" data-target="${escape(x.target)}">${escape(x.message)}</button>`).join(''));}
  finally{button.disabled=false;}
 });
 let dragged=null;
 tree.addEventListener('dragstart',event=>{const row=event.target.closest('[data-drag]');if(!row||uploading){event.preventDefault();return;}dragged=row.dataset.drag;row.classList.add('dragging');event.dataTransfer.effectAllowed='move';event.dataTransfer.setData('text/plain',dragged);});
 tree.addEventListener('dragover',event=>{const row=event.target.closest('[data-drag]');if(row&&dragged&&find(row.dataset.drag)?.list===find(dragged)?.list){event.preventDefault();row.classList.add('drop-target');}});
 tree.addEventListener('dragleave',event=>event.target.closest('[data-drag]')?.classList.remove('drop-target'));
 tree.addEventListener('dragend',()=>{dragged=null;renderTree();});
 tree.addEventListener('drop',event=>{const row=event.target.closest('[data-drag]');event.preventDefault();if(!row||!dragged)return;const from=find(dragged),to=find(row.dataset.drag);if(from?.list!==to?.list)return;structural(()=>{const [item]=from.list.splice(from.index,1);from.list.splice(to.index,0,item);});dragged=null;});
 async function uploadFile(input,file){
  const box=input.closest('.upload-box'),progress=$('progress',box),message=$('[data-upload-status]',box),cancel=$('[data-cancel-upload]',box),retry=$('[data-retry-upload]',box),path=input.dataset.upload;
  const target=path==='image'?find(selected):null;
  uploading++;input.disabled=true;progress.hidden=false;retry.hidden=true;cancel.hidden=false;message.textContent='Загрузка…';
  try{const result=await new Promise((resolve,reject)=>{const xhr=new XMLHttpRequest();xhr.open('POST',base+'upload/');xhr.setRequestHeader('X-CSRFToken',token);xhr.upload.onprogress=e=>{if(e.lengthComputable){progress.value=e.loaded/e.total*100;message.textContent=Math.round(progress.value)+'% — загрузка';}};xhr.onload=()=>{let body;try{body=JSON.parse(xhr.responseText);}catch{return reject(new Error('Загрузка не завершена. Проверьте размер файла и вход в аккаунт.'));}if(xhr.status>=200&&xhr.status<300)resolve(body);else reject(new Error(body.error||'Не удалось загрузить файл.'));};xhr.onerror=()=>reject(new Error('Соединение прервано. Повторите загрузку.'));xhr.onabort=()=>reject(new Error('Загрузка отменена. Файл не прикреплён.'));cancel.onclick=()=>xhr.abort();const form=new FormData();form.append('file',file);xhr.send(form);});
   assets.set(result.id,result);
   if(path==='image'){const rich=$('[contenteditable]',panel);const image=document.createElement('img');image.src=result.url;image.alt=file.name;rich.append(image);target.obj.html=rich.innerHTML;}else set(path,result.id);
   touch();message.textContent='Файл загружен';
  }catch(e){message.textContent=e.message;retry.hidden=false;retry.onclick=()=>uploadFile(input,file);error(e);}
  finally{uploading--;input.disabled=false;cancel.hidden=true;if(retry.hidden){render();await save().catch(error);}}
 }
 document.addEventListener('change',event=>{if(event.target.matches('input[data-upload]')&&event.target.files[0])uploadFile(event.target,event.target.files[0]);});
 window.addEventListener('beforeunload',event=>{if(dirty||uploading){event.preventDefault();event.returnValue='';}});
 document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key.toLowerCase()==='s'){event.preventDefault();save().catch(error);}});
 window.IBStudio={id:packet.id,save};
 render();
});

