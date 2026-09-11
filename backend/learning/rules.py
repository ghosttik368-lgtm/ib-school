"""Heuristic flags, NOT calibrated probabilities or proof of misconduct."""
import re

RULE_VERSION = 'M2.5-v1'
THRESHOLDS_MS = {'quiz': 7000, 'code': 20000}


def cpp_comment_count(source):
    # C++ line splicing occurs before comment recognition. Skip quoted/raw literals.
    source = re.sub(r'\\\r?\n', '', source)
    raw_pattern = re.compile(r'(?:u8|u|U|L)?R"([^ ()\\\t\r\n]{0,16})\(')
    i = count = 0
    while i < len(source):
        raw = raw_pattern.match(source, i)
        if raw:
            end = source.find(')' + raw[1] + '"', raw.end())
            i = len(source) if end < 0 else end + len(raw[1]) + 2
        elif source.startswith('//', i):
            count += 1
            end = source.find('\n', i + 2)
            i = len(source) if end < 0 else end + 1
        elif source.startswith('/*', i):
            count += 1
            end = source.find('*/', i + 2)
            i = len(source) if end < 0 else end + 2
        elif source[i] in '\"\'':
            # Apostrophes between numeric digits are C++ digit separators.
            if source[i] == "'" and re.search(r"\b[0-9][0-9A-Fa-fxXbB']*$", source[:i]) and i+1 < len(source) and source[i+1].isalnum():
                i += 1
                continue
            quote = source[i]
            i += 1
            while i < len(source):
                if source[i] == '\\':
                    i += 2
                elif source[i] == quote:
                    i += 1
                    break
                else:
                    i += 1
        else:
            i += 1
    return count


def evaluate(kind, elapsed_ms, source_code=None):
    if elapsed_ms is None or elapsed_ms < 0:
        return 'unknown', ['Время прохождения не зафиксировано'], None
    reasons = []
    threshold = THRESHOLDS_MS.get(kind, 10000)
    if elapsed_ms <= threshold:
        reasons.append(f'Успешная отправка за {elapsed_ms / 1000:.3f} с; порог ≤ {threshold // 1000} с')
    count = None
    if kind == 'code':
        if source_code is None:
            return 'unknown', ['Нет кода принятой отправки'], None
        count = cpp_comment_count(source_code)
        if count:
            reasons.append(f'Обнаружены комментарии в коде: {count}')
    return ('negative' if reasons else 'positive'), reasons, count


def zone(negative, assessed):
    if not assessed:
        return None, 'unknown'
    # Choose zone before rounding: 33.004% is orange, even if displayed as 33.00%.
    color = 'green' if negative * 100 <= assessed * 33 else 'orange' if negative * 100 <= assessed * 66 else 'red'
    return round(negative * 100 / assessed, 2), color
