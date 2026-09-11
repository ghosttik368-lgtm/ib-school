"""No model output is executable. Grounding and timestamps are checked in Python."""
import difflib
import math
import re
import unicodedata
from django.core.exceptions import ValidationError

MAX_SECONDS = 7200
MAX_TEXT = 500000


def folded(value):
    return ' '.join(unicodedata.normalize('NFKC', value).casefold().split())


def string(value, limit, label):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValidationError(f'{label}: заполните текст (до {limit} символов).')
    return value.strip()


def segments_checked(rows):
    if not isinstance(rows, list) or not rows or len(rows) > 20000:
        raise ValidationError('Не найдена расшифровка с временными отметками.')
    result, previous, total = [], -1, 0
    for i, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValidationError('Неверный фрагмент расшифровки.')
        start, end = row.get('start'), row.get('end')
        if any(isinstance(t, bool) or not isinstance(t, (int, float)) or not math.isfinite(t) for t in (start, end)):
            raise ValidationError('Неверная временная отметка.')
        if not 0 <= start < end <= MAX_SECONDS or start < previous:
            raise ValidationError('Временные отметки должны идти по порядку; видео — до двух часов.')
        text = string(row.get('text'), 6000, 'Фрагмент')
        previous = start
        total += len(text)
        if total > MAX_TEXT:
            raise ValidationError('Расшифровка слишком большая. Разделите лекцию на несколько видео.')
        result.append({'id': i, 'start': round(start, 3), 'end': round(end, 3), 'text': text})
    return result


def parse_subtitles(value):
    if not isinstance(value, str) or len(value) > 1000000:
        raise ValidationError('Субтитры должны быть файлом SRT/VTT до 1 МБ в UTF-8.')
    def seconds(s):
        parts = s.replace(',', '.').split(':')
        if len(parts) not in (2, 3):
            raise ValidationError('Неверное время в субтитрах.')
        values = [float(x) for x in parts]
        if not 0 <= values[-1] < 60 or not 0 <= values[-2] < 60:
            raise ValidationError('Неверное время в субтитрах.')
        return sum(v * 60 ** i for i, v in enumerate(reversed(values)))
    rows = []
    for cue in re.split(r'\n\s*\n', value.replace('\r\n', '\n').strip('\ufeff\n ')):
        lines = cue.splitlines()
        for i, line in enumerate(lines):
            if '-->' not in line:
                continue
            try:
                a, b = line.split('-->')
                start, end = seconds(a.strip()), seconds(b.strip().split()[0])
            except (ValueError, IndexError):
                raise ValidationError('Не удалось разобрать время в SRT/VTT.')
            text = re.sub(r'<[^>]*>', '', ' '.join(lines[i+1:])).strip()
            if text:
                rows.append({'start': start, 'end': end, 'text': text})
            break
    return segments_checked(rows)


def similar(a, b):
    a, b = folded(a), folded(b)
    return a == b or difflib.SequenceMatcher(None, a, b).ratio() >= .9


def candidate_checked(raw, segments, previous=()):
    if not isinstance(raw, dict):
        raise ValidationError('Неверный формат вопроса.')
    question = string(raw.get('question'), 2000, 'Вопрос')
    choices = raw.get('choices')
    if not isinstance(choices, list) or len(choices) != 4:
        raise ValidationError('У вопроса должно быть четыре варианта.')
    choices = [string(c, 500, 'Вариант ответа') for c in choices]
    if len({folded(c) for c in choices}) != 4:
        raise ValidationError('Варианты ответа повторяются.')
    correct = raw.get('correct')
    if isinstance(correct, bool) or not isinstance(correct, int) or not 0 <= correct <= 3:
        raise ValidationError('Выберите один правильный ответ.')
    explanation = string(raw.get('explanation'), 3000, 'Объяснение')
    sid = raw.get('segment')
    if isinstance(sid, bool) or not isinstance(sid, int):
        raise ValidationError('Вопрос не связан с фрагментом лекции.')
    source = next((s for s in segments if s['id'] == sid), None)
    quote = string(raw.get('quote'), 1500, 'Цитата')
    if not source or len(quote) < 12 or folded(quote) not in folded(source['text']):
        raise ValidationError('Цитата не найдена в указанном фрагменте лекции.')
    if any(similar(question, q['question']) for q in previous):
        raise ValidationError('Вопрос повторяет уже добавленный.')
    return {'question': question, 'choices': choices, 'correct': correct,
            'explanation': explanation, 'segment': sid, 'quote': quote,
            'start': source['start'], 'end': source['end']}


def questions_checked(raw, segments, expected=10):
    if not isinstance(raw, list) or len(raw) != expected:
        raise ValidationError(f'Нужно ровно {expected} вопросов.')
    result = []
    for q in raw:
        result.append(candidate_checked(q, segments, result))
    return result
