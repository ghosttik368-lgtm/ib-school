document.querySelectorAll('.teach-review').forEach(form => {
  form.addEventListener('submit',async event=>{
    event.preventDefault();const button=form.querySelector('button[type=submit]'),label=form.querySelector('[role=status]');button.disabled=true;
    try{const response=await fetch(form.action,{method:'POST',body:new FormData(form),headers:{'X-CSRFToken':form.querySelector('[name=csrfmiddlewaretoken]').value},credentials:'same-origin'});
      if(response.redirected||!response.headers.get('content-type')?.includes('application/json'))throw Error('Сессия закончилась. Скопируйте комментарий и войдите снова.');
      const data=await response.json();if(!response.ok)throw Error(data.error||'Нет доступа к проверке.');
      label.textContent='Проверка сохранена. Обновляем результаты…';location.reload();
    }catch(error){label.textContent=error.message;button.disabled=false;}
  });
});
