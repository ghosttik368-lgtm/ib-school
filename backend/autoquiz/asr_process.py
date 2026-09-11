"""Private subprocess: releases all recognition memory when it exits. No Django."""
import argparse
import json
import os
from pathlib import Path
import sys


def transcribe(path, model_path, threads):
    import av
    import numpy as np
    from faster_whisper import WhisperModel
    fmt = 'mov' if Path(path).suffix.lower() in {'.mp4', '.mov'} else 'matroska'
    samples, count = [], 0
    with open(path, 'rb') as source, av.open(source, format=fmt, options={'protocol_whitelist': 'file,pipe'}) as container:
        if not container.streams.audio:
            raise ValueError('В видео нет звуковой дорожки. Загрузите видео с речью или SRT/VTT.')
        resampler = av.AudioResampler(format='s16', layout='mono', rate=16000)
        for frame in container.decode(audio=0):
            for audio in resampler.resample(frame):
                value = audio.to_ndarray().reshape(-1)
                count += value.size
                if count > 7200*16000:
                    raise ValueError('Видео длиннее двух часов. Разделите лекцию.')
                samples.append(value)
        for audio in resampler.resample(None):
            samples.append(audio.to_ndarray().reshape(-1))
    if not samples:
        raise ValueError('В видео не найден звук.')
    waveform = np.concatenate(samples).astype(np.float32) / 32768.0
    del samples
    model = WhisperModel(model_path, device='cpu', compute_type='int8', cpu_threads=threads,
                         num_workers=1, local_files_only=True)
    segments, info = model.transcribe(waveform, language='ru', beam_size=5, vad_filter=True,
                                     condition_on_previous_text=False)
    rows, total = [], 0
    for segment in segments:
        text = segment.text.strip()
        if not text or segment.end <= segment.start:
            continue
        total += len(text)
        if total > 500000 or len(rows) >= 20000:
            raise ValueError('Расшифровка слишком большая. Разделите лекцию.')
        rows.append({'start': segment.start, 'end': segment.end, 'text': text})
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--video', required=True)
    parser.add_argument('--model', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--threads', type=int, default=4)
    args = parser.parse_args()
    os.environ['HF_HUB_OFFLINE'] = '1'
    try:
        result = {'segments': transcribe(args.video, args.model, args.threads)}
    except ImportError:
        result = {'error': 'Не установлены зависимости распознавания. Установите requirements-autoquiz.txt.'}
    except ValueError as exc:
        result = {'error': str(exc)[:500]}
    except Exception:
        result = {'error': 'Не удалось распознать видео. Проверьте файл, модель Whisper (autoquiz_prepare), свободную память и Microsoft Visual C++ Redistributable x64.'}
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    return 1 if 'error' in result else 0


if __name__ == '__main__':
    sys.exit(main())
