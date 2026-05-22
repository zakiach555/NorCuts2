import os
import json
import asyncio
import re
from pathlib import Path
from deep_translator import GoogleTranslator

# Arabic renderer — used for optimised prompts and post-processing
try:
    from scripts import renderer_arabic as _ar
except ImportError:
    try:
        import renderer_arabic as _ar   # type: ignore
    except ImportError:
        _ar = None

LANGUAGE_NAMES = {
    'ar': 'Arabic', 'en': 'English', 'fr': 'French', 'es': 'Spanish',
    'de': 'German', 'pt': 'Portuguese', 'ru': 'Russian', 'it': 'Italian',
    'ja': 'Japanese', 'ko': 'Korean', 'zh-CN': 'Chinese (Simplified)',
}

# How many segments to send per AI call
BATCH_SIZE = 25


def redistribute_timing(segment, translated_text):
    """
    Assign per-word timestamps within a segment proportional to character length.
    Keeps the original segment start/end; only the intra-word split changes.
    Longer words get more screen time — important for Arabic which can be verbose.
    """
    words = translated_text.strip().split()
    if not words:
        return

    seg_start = segment['start']
    seg_end   = segment['end']
    duration  = max(0.05, seg_end - seg_start)

    char_counts = [max(1, len(w)) for w in words]
    total_chars = sum(char_counts)

    current = seg_start
    new_words = []
    for word, chars in zip(words, char_counts):
        word_dur = duration * (chars / total_chars)
        new_words.append({
            'word':  word,
            'start': round(current, 3),
            'end':   round(current + word_dur, 3),
            'score': 1.0,
        })
        current += word_dur

    segment['words'] = new_words
    segment['text']  = translated_text


def _parse_numbered(text, expected):
    """Parse '1. line\n2. line\n...' AI response into a list."""
    results = {}
    for line in text.strip().splitlines():
        m = re.match(r'^(\d+)[.)]\s*(.+)$', line.strip())
        if m:
            results[int(m.group(1))] = m.group(2).strip()
    if len(results) == expected:
        return [results[i + 1] for i in range(expected)]
    return None


def _build_prompt(texts, target_lang):
    # Use the Arabic-optimised prompt when translating to Arabic
    if _ar is not None and target_lang == 'ar':
        return _ar.build_translation_prompt(texts)

    lang_name = LANGUAGE_NAMES.get(target_lang, target_lang)
    numbered  = '\n'.join(f'{i + 1}. {t}' for i, t in enumerate(texts))
    return f"""You are a professional subtitle translator. Translate each numbered line to {lang_name}.

Rules:
- Translate the MEANING, not word-for-word
- Keep it concise and natural for spoken {lang_name} subtitles
- Preserve the exact numbered format
- Return ONLY the numbered translations — no explanations, no quotes

Lines:
{numbered}"""


async def _try_gemini(prompt, api_key, ai_model):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(ai_model or 'gemini-1.5-flash')
    loop = asyncio.get_event_loop()
    resp = await loop.run_in_executor(None, model.generate_content, prompt)
    return resp.text.strip()


async def _try_g4f(prompt):
    import g4f
    loop = asyncio.get_event_loop()
    resp = await loop.run_in_executor(
        None,
        lambda: g4f.ChatCompletion.create(
            model='gpt-4o-mini',
            messages=[{'role': 'user', 'content': prompt}],
        ),
    )
    if isinstance(resp, str) and resp.strip():
        return resp.strip()
    raise ValueError('empty g4f response')


async def _google_translate_batch(texts, target_lang):
    results = []
    for text in texts:
        try:
            translator = GoogleTranslator(source='auto', target=target_lang)
            loop = asyncio.get_event_loop()
            t = await loop.run_in_executor(None, translator.translate, text)
            results.append(t or text)
        except Exception:
            results.append(text)
    return results


async def translate_batch(texts, target_lang, api_key=None, ai_model=None):
    """
    Translate a batch of subtitle lines using the best available AI backend.
    Falls back to Google Translate if all AI attempts fail.
    """
    prompt = _build_prompt(texts, target_lang)
    response_text = None

    # 1. Gemini
    if api_key:
        try:
            response_text = await _try_gemini(prompt, api_key, ai_model)
        except Exception as e:
            print(f'\n[Translation] Gemini failed: {e}')

    # 2. G4F
    if not response_text:
        try:
            response_text = await _try_g4f(prompt)
        except Exception as e:
            print(f'\n[Translation] G4F failed: {e}')

    # Parse structured response
    if response_text:
        parsed = _parse_numbered(response_text, len(texts))
        if parsed:
            return parsed

    # 3. Google Translate fallback
    print(f'\n[Translation] Falling back to Google Translate for {len(texts)} segments')
    return await _google_translate_batch(texts, target_lang)


async def translate_json_file(json_file_path, translated_json_path,
                              target_lang, api_key=None, ai_model=None):
    with open(json_file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    segments = data['segments']
    texts    = [seg.get('text', '').strip() for seg in segments]

    all_translated = []
    total = len(texts)
    for i in range(0, total, BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        end   = min(i + BATCH_SIZE, total)
        print(f'\r  Translating segments {i + 1}–{end} / {total}...', end='', flush=True)
        translated = await translate_batch(batch, target_lang,
                                           api_key=api_key, ai_model=ai_model)
        all_translated.extend(translated)
    print()

    use_arabic_pipeline = _ar is not None and target_lang == 'ar'
    for segment, translated_text in zip(segments, all_translated):
        if translated_text and translated_text.strip():
            text = translated_text.strip()
            if use_arabic_pipeline:
                text = _ar.post_process_translation(text)
                _ar.redistribute_timing(segment, text)
            else:
                redistribute_timing(segment, text)

    data['segments'] = segments

    os.makedirs(translated_json_path.parent, exist_ok=True)
    with open(translated_json_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return data


async def translate_project_subs(project_folder, target_lang,
                                 api_key=None, ai_model=None):
    """
    Translate all *_processed.json subtitle files in the project's subs folder.
    Creates a *_processed_original.json backup before overwriting.
    """
    subs_folder = Path(project_folder) / 'subs'
    if not subs_folder.exists():
        print(f'Subtitle folder not found: {subs_folder}')
        return

    json_files = list(subs_folder.glob('*_processed.json'))
    if not json_files:
        print('No subtitle files found to translate.')
        return

    print(f"Translating {len(json_files)} file(s) to '{target_lang}'...")

    for json_file in json_files:
        backup = json_file.with_name(json_file.stem + '_original' + json_file.suffix)

        source = json_file
        if backup.exists():
            print(f'  Using existing backup: {backup.name}')
            source = backup
        else:
            print(f'  Backing up {json_file.name} → {backup.name}')
            try:
                json_file.rename(backup)
                source = backup
            except Exception as e:
                print(f'  Error creating backup: {e}')
                continue

        print(f'  Translating {source.name} → {json_file.name}')
        try:
            await translate_json_file(source, json_file, target_lang,
                                      api_key=api_key, ai_model=ai_model)
        except Exception as e:
            print(f'  Error: {e}')
            if not json_file.exists() and backup.exists():
                print('  Restoring backup...')
                backup.rename(json_file)

    print('Translation complete.')
