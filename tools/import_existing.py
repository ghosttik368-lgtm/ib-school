"""Copy an existing SQLite database and uploads into a NEW unpacked project."""
import argparse
import ast
import shutil
import sqlite3
from pathlib import Path
from dotenv import dotenv_values

def schema(path):
    def declarations(node):
        result=[]
        for item in node.body:
            if isinstance(item,ast.ClassDef): result.append((item.name,declarations(item)))
            elif isinstance(item,(ast.Assign,ast.AnnAssign)): result.append(ast.dump(item,include_attributes=False))
        return result
    return declarations(ast.parse(path.read_text(encoding='utf-8-sig')))

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--from',dest='source',required=True)
args=p.parse_args()
root=Path(__file__).resolve().parent.parent
source=Path(args.source).expanduser().resolve()
old=source/'backend' if (source/'backend/manage.py').exists() else source
new=root/'backend'
if old==new: raise SystemExit('Укажите старую папку, не папку этого обновления.')
if (new/'db.sqlite3').exists() or (root/'.env').exists() or (new/'media').exists():
    raise SystemExit('Импорт только в свежераспакованную папку ДО init_local.py и migrate. Ничего не заменено.')
for app in ('accounts','courses'):
    model=old/app/'models.py'
    if not model.exists() or schema(model)!=schema(new/app/'models.py'):
        raise SystemExit(f'Структура {app} отличается от поддерживаемой версии. Нужна сверка ваших исходников. Источник не изменён.')
    if not list((old/app/'migrations').glob('[0-9]*.py')):
        raise SystemExit(f'Нет истории миграций {app}. Восстановите её из старого проекта, не используйте --fake.')
db=old/'db.sqlite3'
if not db.exists(): raise SystemExit('Не найдена SQLite-база. PostgreSQL этим скриптом не импортируется.')
env=source/'.env'
if not env.exists():env=old/'.env'
if env.exists() and dotenv_values(env).get('DB_ENGINE','sqlite')!='sqlite':
    raise SystemExit('Источник использует другую СУБД. Автоимпорт отменён.')
with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as src, sqlite3.connect(new/'db.sqlite3') as dst:src.backup(dst)
for app in ('accounts','courses'):
    target=new/app/'migrations'
    for file in target.glob('[0-9]*.py'):file.unlink()
    for file in (old/app/'migrations').glob('*.py'):shutil.copy2(file,target/file.name)
if (old/'media').exists():shutil.copytree(old/'media',new/'media')
if env.exists():shutil.copy2(env,root/'.env')
print('Скопированы база, загрузки, история миграций и имеющийся .env. Старый проект не изменён.')
