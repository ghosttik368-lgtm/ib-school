import copy
import re
from pathlib import Path
from django.db import transaction
from django.db.models import F, Max
from django.utils import timezone
from courses.models import Course, Module, Lesson, Material, Quiz, Question, AnswerChoice
from .models import Draft, Asset, Release, PublishedAsset
from .content import blank, uid, plain_html, normalize, problems


@transaction.atomic
def import_course(course):
    if hasattr(course,'studio_release'):return course.studio_release.draft
    existing=Draft.objects.filter(source_course=course).first()
    if existing:return existing
    draft=Draft.objects.create(source_course=course,owner=course.created_by,title=course.title,latest_course=course if course.status=='published' else None)
    def imported(file,visible=True):
        if not file:return None
        a=Asset.objects.create(draft=draft,file=file.name,name=Path(file.name).name)
        if course.status=='published' and visible:PublishedAsset.objects.get_or_create(asset=a,course=course)
        return a.pk
    data=blank();data.update(title=course.title,direction=course.direction_id,level=course.level,summary=course.short_description,description=course.description,cover=imported(course.cover),sections=[])
    if data['cover'] and course.status=='published':PublishedAsset.objects.filter(asset_id=data['cover'],course=course).update(is_cover=True)
    for module in course.modules.order_by('order','id'):
        sec={'id':uid(),'title':module.title,'lessons':[]}
        for lesson in module.lessons.order_by('order','id'):
            les={'id':uid(),'title':lesson.title,'summary':lesson.summary,'active':lesson.is_active,'steps':[]}
            for material in lesson.materials.order_by('order','id'):
                st={'id':uid(),'title':material.title,'kind':material.kind,'required':material.required,'html':material.text if material.rich_text else plain_html(material.text),'asset':imported(material.file,lesson.is_active),'url':material.external_url,'points':course.points_per_test,'passing':100,'questions':[]}
                quiz=Quiz.objects.filter(material=material).first()
                if quiz:
                    st.update(points=quiz.points,passing=quiz.passing_score)
                    for q in quiz.questions.order_by('order','id'):
                        st['questions'].append({'id':uid(),'type':q.kind,'text':q.text,'explanation':q.explanation,'answers':q.accepted_answers,'case_sensitive':q.case_sensitive,'choices':[{'text':c.text,'correct':c.is_correct} for c in q.choices.order_by('order','id')]})
                les['steps'].append(st)
            sec['lessons'].append(les)
        data['sections'].append(sec)
    if not data['sections']:data['sections']=blank()['sections']
    # Legacy upload types are preserved. Publication validation reports incomplete content.
    draft.data=normalize(data,draft,strict_asset_types=False)
    if course.status=='published':
        draft.published_revision=1
        Release.objects.create(draft=draft,course=course,number=1,snapshot=draft.data)
    draft.save()
    return draft


def import_legacy(user=None):
    courses=Course.objects.filter(studio_source__isnull=True,studio_release__isnull=True)
    if user and not user.is_platform_admin:courses=courses.filter(created_by=user)
    for course in courses:import_course(course)


def referenced_assets(data):
    ids=set()
    if data.get('cover'):ids.add(data['cover'])
    for s in data['sections']:
        for l in s['lessons']:
            if not l.get('active',True):continue
            for st in l['steps']:
                for key in ['asset','viewer']:
                    if st.get(key):ids.add(st[key])
                ids.update(int(x) for x in re.findall(r'/studio/assets/(\d+)/',st['html']))
    return ids


def publish(draft):
    """Caller owns the draft write lock. Always create a new immutable Course tree."""
    data=draft.data
    assets={a.pk:a for a in draft.assets.all()}
    course=Course.objects.create(direction_id=data['direction'],title=data['title'],level=data['level'],short_description=data['summary'],description=data['description'],created_by=draft.owner,status='published',is_listed=not draft.archived,published_at=timezone.now(),cover=assets[data['cover']].file.name if data['cover'] else '')
    lesson_number=0
    material_map, question_map = {}, {}
    for si,sec in enumerate(data['sections'],1):
        module=Module.objects.create(course=course,title=sec['title'],order=si)
        for li,les in enumerate(sec['lessons'],1):
            lesson_number+=1
            lesson=Lesson.objects.create(module=module,title=les['title'],summary=les['summary'],order=lesson_number,is_active=les.get('active',True))
            for i,step in enumerate(les['steps'],1):
                material=Material.objects.create(lesson=lesson,title=step['title'],kind=step['kind'],text=step['html'],rich_text=True,required=step['required'],external_url=step['url'],file=assets[step['asset']].file.name if step['asset'] else '',order=i*2)
                material_map[step['id']] = material
                if step['kind']=='code':
                    from practice.models import Task
                    c=step['code']
                    Task.objects.create(material=material,statement=c['statement'],input_format=c['input_format'],output_format=c['output_format'],examples=c['examples'],starter=c['starter'],solution=c['solution'],tests=c['tests'],time_limit=c['time'],memory_limit=c['memory'])
                if step['viewer']:
                    Material.objects.create(lesson=lesson,title=step['title']+' — просмотр PDF',kind='pdf',file=assets[step['viewer']].file.name,required=False,order=i*2+1,attachment_of=material)
                if step['kind']=='quiz':
                    quiz=Quiz.objects.create(material=material,passing_score=step['passing'],points=step['points'])
                    for qi,q in enumerate(step['questions'],1):
                        question=Question.objects.create(quiz=quiz,text=q['text'],kind=q['type'],accepted_answers=q['answers'],case_sensitive=q['case_sensitive'],explanation=q['explanation'],order=qi)
                        question_map[q['id']] = question
                        AnswerChoice.objects.bulk_create([AnswerChoice(question=question,text=c['text'],is_correct=c['correct'],order=ci) for ci,c in enumerate(q['choices'],1)])
    from autoquiz.services import publish_sources
    publish_sources(draft, material_map, question_map)
    for aid in referenced_assets(data):PublishedAsset.objects.create(asset_id=aid,course=course,is_cover=aid==data['cover'])
    if draft.latest_course_id:Course.objects.filter(pk=draft.latest_course_id).update(is_listed=False)
    number=(draft.releases.aggregate(n=Max('number'))['n'] or 0)+1
    Release.objects.create(draft=draft,course=course,number=number,snapshot=copy.deepcopy(data))
    draft.latest_course=course;draft.published_revision=draft.revision;draft.save(update_fields=['latest_course','published_revision','updated_at'])
    return course
