import copy
import re
import uuid
from pathlib import Path
from urllib.parse import urlsplit
import bleach
from django.core.exceptions import ValidationError
from django.utils.html import escape, strip_tags
from courses.models import Direction

KINDS = {'text','video','pdf','presentation','document','link','quiz','code'}


def uid(): return uuid.uuid4().hex


def clean_html(value):
    def attr(tag, name, value):
        if tag == 'a' and name == 'href':
            return urlsplit(value).scheme in {'http','https'}
        if tag == 'img' and name == 'src': return bool(re.fullmatch(r'/studio/assets/\d+/', value))
        return (tag == 'img' and name == 'alt') or (tag == 'a' and name == 'title')
    return bleach.clean(value, tags={'p','br','strong','b','em','i','u','h2','h3','ul','ol','li','blockquote','pre','code','a','img'}, attributes=attr, protocols={'http','https'}, strip=True)


def plain_html(value): return '<p>' + str(escape(value)).replace('\n','<br>') + '</p>'


def blank():
    return {'title':'Новый курс','direction':0,'level':'beginner','summary':'','description':'','cover':None,'sections':[{'id':uid(),'title':'Основная программа','lessons':[]}]}


def normalize(raw, draft, strict_asset_types=True):
    if not isinstance(raw, dict): raise ValidationError('Неверный формат курса.')
    def text(obj, key, limit, default=''):
        val=obj.get(key, default)
        if not isinstance(val,str) or len(val)>limit: raise ValidationError(f'Поле {key}: превышена длина или неверный тип.')
        return val
    def integer(obj,key,lo,hi,default):
        val=obj.get(key,default)
        if isinstance(val,bool) or not isinstance(val,int) or not lo<=val<=hi: raise ValidationError(f'Поле {key}: допустимо {lo}–{hi}.')
        return val
    def boolean(obj,key,default):
        v=obj.get(key,default)
        if not isinstance(v,bool):raise ValidationError(f'Поле {key}: ожидается да/нет.')
        return v
    ids=set()
    def identity(obj):
        value=text(obj,'id',40)
        if not re.fullmatch('[a-zA-Z0-9_-]{1,40}',value) or value in ids:raise ValidationError('Повторяющийся или неверный идентификатор шага.')
        ids.add(value);return value
    assets={x.pk:x for x in draft.assets.all()}
    def asset(value):
        if value is None:return None
        if isinstance(value,bool) or not isinstance(value,int) or value not in assets:raise ValidationError('Файл не принадлежит этому курсу. Загрузите его через редактор.')
        return value
    def url(value):
        if value and (urlsplit(value).scheme not in {'https','http'} or not urlsplit(value).netloc):raise ValidationError('Ссылка должна начинаться с https:// или http://.')
        return value
    data={'title':text(raw,'title',180),'direction':integer(raw,'direction',0,2147483647,0),'level':text(raw,'level',20,'beginner'),'summary':text(raw,'summary',260),'description':text(raw,'description',20000),'cover':asset(raw.get('cover')),'sections':[]}
    if data['level'] not in {'beginner','basic','advanced'}:raise ValidationError('Неизвестная сложность.')
    if strict_asset_types and data['cover'] and Path(assets[data['cover']].name).suffix.lower() not in {'.jpg','.jpeg','.png','.webp'}:raise ValidationError('Для обложки нужно изображение JPG/PNG/WebP.')
    sections=raw.get('sections',[])
    if not isinstance(sections,list) or len(sections)>100:raise ValidationError('Не больше 100 разделов.')
    for section in sections:
        if not isinstance(section,dict):raise ValidationError('Неверный раздел.')
        sec={'id':identity(section),'title':text(section,'title',180),'lessons':[]}
        lessons=section.get('lessons',[])
        if not isinstance(lessons,list) or len(lessons)>200:raise ValidationError('Не больше 200 уроков в разделе.')
        for lesson in lessons:
            les={'id':identity(lesson),'title':text(lesson,'title',180),'summary':text(lesson,'summary',5000),'active':boolean(lesson,'active',True),'steps':[]}
            steps=lesson.get('steps',[])
            if not isinstance(steps,list) or len(steps)>200:raise ValidationError('Не больше 200 шагов в уроке.')
            for step in steps:
                kind=text(step,'kind',20,'text')
                if kind not in KINDS:raise ValidationError('Неизвестный тип материала.')
                st={'id':identity(step),'title':text(step,'title',180),'kind':kind,'required':boolean(step,'required',True),'html':clean_html(text(step,'html',200000)),'url':url(text(step,'url',2000)),'asset':asset(step.get('asset')),'viewer':asset(step.get('viewer')),'points':integer(step,'points',0,1000,5),'passing':integer(step,'passing',1,100,100),'questions':[]}
                if st['viewer'] and Path(assets[st['viewer']].name).suffix.lower()!='.pdf':raise ValidationError('Для встроенного просмотра прикрепите PDF.')
                st['auto_quiz'] = boolean(step, 'auto_quiz', False) if kind == 'video' else False
                allowed={'video':{'.mp4','.webm','.mov','.mkv'},'pdf':{'.pdf'},'document':{'.doc','.docx'},'presentation':{'.ppt','.pptx'}}
                if strict_asset_types and st['asset'] and kind in allowed and Path(assets[st['asset']].name).suffix.lower() not in allowed[kind]:raise ValidationError(f'Файл не подходит для материала {kind}.')
                for ref in re.findall(r'/studio/assets/(\d+)/',st['html']):
                    aid=asset(int(ref))
                    if Path(assets[aid].name).suffix.lower() not in {'.jpg','.jpeg','.png','.webp'}:raise ValidationError('В статью можно вставить только изображение.')
                qs=step.get('questions',[])
                if not isinstance(qs,list) or len(qs)>100:raise ValidationError('Не больше 100 вопросов в тесте.')
                for q in qs:
                    typ=text(q,'type',12,'single')
                    if typ not in {'single','multiple','short'}:raise ValidationError('Неизвестный тип вопроса.')
                    answers=q.get('answers',[]); choices=q.get('choices',[])
                    if not isinstance(answers,list) or len(answers)>50 or any(not isinstance(x,str) or len(x)>500 for x in answers):raise ValidationError('Неверный список допустимых ответов.')
                    if not isinstance(choices,list) or len(choices)>20:raise ValidationError('Не больше 20 вариантов ответа.')
                    st['questions'].append({'id':identity(q),'type':typ,'text':text(q,'text',10000),'explanation':text(q,'explanation',10000),'case_sensitive':boolean(q,'case_sensitive',False),'answers':answers,'choices':[{'text':text(c,'text',500),'correct':boolean(c,'correct',False)} for c in choices]})
                code=step.get('code',{})
                if not isinstance(code,dict):raise ValidationError('Неверные настройки задачи.')
                st['code']={k:text(code,k,100000) for k in ['statement','input_format','output_format','examples','starter','solution']}
                st['code']['time']=integer(code,'time',1,10,2);st['code']['memory']=integer(code,'memory',16,512,128)
                tests=code.get('tests',[])
                if not isinstance(tests,list) or len(tests)>100:raise ValidationError('Не больше 100 скрытых тестов.')
                st['code']['tests']=[{'input':text(t,'input',10000),'output':text(t,'output',10000)} for t in tests]
                les['steps'].append(st)
            sec['lessons'].append(les)
        data['sections'].append(sec)
    return data


def problems(data):
    errors=[]
    def add(message, target='course'):errors.append({'message':message,'target':target})
    if not data['title'].strip():add('Введите название курса.')
    if not Direction.objects.filter(pk=data['direction'],is_active=True).exists():add('Выберите направление.')
    if not data['description'].strip():add('Опишите результаты обучения.')
    lessons=[l for s in data['sections'] for l in s['lessons'] if l.get('active',True)]
    if not lessons:add('Добавьте хотя бы один урок.')
    for sec in data['sections']:
        if not sec['title'].strip():add('Назовите раздел.',sec['id'])
    for lesson in lessons:
        if not lesson['title'].strip():add('Назовите урок.',lesson['id'])
        if not lesson['steps']:add(f'{lesson["title"]}: добавьте материалы.',lesson['id'])
        for st in lesson['steps']:
            label=st['title'] or 'Шаг без названия'; target=st['id']
            if not st['title'].strip():add('Назовите шаг.',target)
            if st['kind']=='text' and not strip_tags(st['html']).strip() and '<img' not in st['html']:add(f'{label}: напишите статью.',target)
            if st['kind']=='video' and not(st['asset'] or st['url']):add(f'{label}: загрузите видео или укажите ссылку.',target)
            if st['kind'] in {'pdf','document','presentation'} and not st['asset']:add(f'{label}: прикрепите файл.',target)
            if st['kind']=='link' and not st['url']:add(f'{label}: укажите ссылку.',target)
            if st['kind']=='code':
                if not st['code']['statement'].strip():add(f'{label}: введите условие задачи.',target)
                if not st['code']['tests']:add(f'{label}: добавьте хотя бы один скрытый тест.',target)
            if st['kind']=='quiz':
                if not st['questions']:add(f'{label}: добавьте вопросы.',target)
                for i,q in enumerate(st['questions'],1):
                    if not q['text'].strip():add(f'{label}, вопрос {i}: введите условие.',target)
                    if q['type']=='short':
                        if not any(a.strip() for a in q['answers']):add(f'{label}, вопрос {i}: задайте допустимые ответы.',target)
                    else:
                        correct=sum(c['correct'] for c in q['choices'])
                        if len(q['choices'])<2 or any(not c['text'].strip() for c in q['choices']):add(f'{label}, вопрос {i}: заполните хотя бы два варианта.',target)
                        if (q['type']=='single' and correct!=1) or (q['type']=='multiple' and correct<1):add(f'{label}, вопрос {i}: отметьте правильные ответы.',target)
    return errors
