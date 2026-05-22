"""
renderer_english.py — English / LTR Subtitle Renderer for ViralCutter
═══════════════════════════════════════════════════════════════════════

Implements the subtitle rendering strategy for English (and other LTR)
content.  If English subtitle layout breaks, the fix lives entirely here
without touching renderer_arabic.py or the shared pipeline.

STRATEGY INTERFACE  (identical signature to renderer_arabic.py)
────────────────────────────────────────────────────────────────
  generate_ass(input_path, output_path, project_folder, ...) -> None
  adjust(project_folder, ...)                                -> None

WHAT THIS MODULE HANDLES
─────────────────────────
  • Left-to-right text layout (standard ASS, no \\q2 bidi override needed)
  • English-compatible font references (any Latin font works)
  • All four display modes: highlight, no_highlight, word_by_word, norz
  • Watermark and speaker-tag decorations
  • Dynamic face-mode timeline position overrides
  • Basic punctuation stripping (ASCII only — no Arabic forms)
  • Graceful handling of Hebrew/Persian RTL in the LTR path (\\q2 guard)

WHAT THIS MODULE DOES NOT HANDLE
──────────────────────────────────
  • Arabic letter reshaping — renderer_arabic.py owns that
  • RTL bidi reordering — renderer_arabic.py owns that
  • Arabic font loading / vcfonts caching — renderer_arabic.py owns that
  • Any import of arabic_handler or renderer_arabic — zero cross-dependency
"""

import json
import os
import re


# ── Canvas constants ───────────────────────────────────────────────────────────
_PLAY_RES_X = 360
_PLAY_RES_Y = 640
_CX = _PLAY_RES_X // 2   # horizontal centre (180)


# ══════════════════════════════════════════════════════════════════════════════
# INTERNAL UTILITIES
# ══════════════════════════════════════════════════════════════════════════════

def _fmt(t: float) -> str:
    """Format *t* seconds as an ASS timestamp  H:MM:SS.cs."""
    h  = int(t // 3600)
    m  = int((t % 3600) // 60)
    s  = int(t % 60)
    cs = int((t % 1) * 100)
    return f'{h:01}:{m:02}:{s:02}.{cs:02}'


def _clean_word(word: str, remove_punctuation: bool) -> str:
    """Basic English word cleaning — strip ASCII punctuation when requested."""
    if remove_punctuation:
        return re.sub(r'[.,!?;]', '', word)
    return word


def _load_timeline(base_name: str, filename: str, project_folder: str):
    """
    Locate the per-clip face-mode timeline JSON.
    Returns the parsed list or None if not found.
    """
    tl_name = base_name.replace('_processed', '') + '_timeline.json'
    tl_path = os.path.join(project_folder, 'final', tl_name)
    if os.path.exists(tl_path):
        try:
            with open(tl_path, encoding='utf-8') as fh:
                return json.load(fh)
        except Exception:
            pass

    m_out = re.search(r'output(\d+)', filename)
    m_idx = re.search(r'^(\d{3})_', filename)
    idx   = int(m_out.group(1)) if m_out else (int(m_idx.group(1)) if m_idx else None)
    if idx is not None:
        fb = os.path.join(
            project_folder, 'final',
            f'temp_video_no_audio_{idx}_timeline.json',
        )
        if os.path.exists(fb):
            try:
                with open(fb, encoding='utf-8') as fh:
                    return json.load(fh)
            except Exception:
                pass
    return None


def _face_mode_key(base_name: str, filename: str) -> tuple:
    """Return (key, idx) for face_modes dict lookup."""
    m_out = re.search(r'output(\d+)', filename)
    m_idx = re.search(r'^(\d{3})_', filename)
    idx   = int(m_out.group(1)) if m_out else (int(m_idx.group(1)) if m_idx else None)
    key   = f'output{str(idx).zfill(3)}' if idx is not None else base_name
    return key, idx


def _ass_header(font, base_size, base_color, outline_color, shadow_color,
                bold, italic, underline, strikeout,
                border_style, outline_thickness, shadow_size,
                alignment, vertical_position) -> str:
    """Build the ASS [Script Info] + [V4+ Styles] + [Events] header."""
    return (
        '[Script Info]\n'
        'Title: English Subtitles — ViralCutter\n'
        'ScriptType: v4.00+\n'
        'PlayDepth: 0\n'
        'PlayResX: 360\n'
        'PlayResY: 640\n'
        '\n'
        '[V4+ Styles]\n'
        'Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, '
        'OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, '
        'ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, '
        'Alignment, MarginL, MarginR, MarginV, Encoding\n'
        f'Style: Default,{font},{base_size},{base_color},&H00000000,'
        f'{outline_color},{shadow_color},'
        f'{bold},{italic},{underline},{strikeout},'
        f'100,100,0,0,{border_style},{outline_thickness},{shadow_size},'
        f'{alignment},-2,-2,{vertical_position},1\n'
        '\n'
        '[Events]\n'
        'Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n'
    )


# ── Line builders ──────────────────────────────────────────────────────────────

def _build_highlight(block, j, base_size, base_color, hl_size, hl_color, use_rtl):
    parts = []
    for k, wd in enumerate(block):
        w = wd['word']
        if k == j:
            parts.append(f'{{\\fs{hl_size}\\c{hl_color}}}{w}')
        else:
            parts.append(f'{{\\fs{base_size}\\c{base_color}}}{w}')
    prefix = '{\\q2}' if use_rtl else ''
    return (prefix + ' '.join(parts)).strip()


def _build_no_highlight(block, base_size, base_color, use_rtl):
    words = ' '.join(wd['word'] for wd in block).strip()
    prefix = '{\\q2}' if use_rtl else ''
    return prefix + words


def _build_word_by_word(word, base_size, base_color, use_rtl):
    prefix = '{\\q2}' if use_rtl else ''
    return prefix + word.strip()


def _build_norz(block, j, base_size, base_color, hl_size, hl_color, sub_y):
    parts = []
    for k, wd in enumerate(block):
        w = wd['word'].strip()
        if not w:
            continue
        if k == j:
            parts.append(f'{{\\fs{hl_size}\\c{hl_color}\\b1}}{w}')
        else:
            parts.append(f'{{\\fs{base_size}\\c{base_color}\\b0}}{w}')
    return (
        f'{{\\an5\\pos({_CX},{sub_y})\\shad2\\3c&H00000000&\\q2}}'
        + ' '.join(parts)
    )


def _build_two_line_emphasis(block, base_size, base_color, hl_size, hl_color, words_in_second_line=2):
    """
    Two-line emphasis mode - splits block into two lines with NO duplication.
    
    Line 1: All words EXCEPT the last N words (white, smaller, lighter)
    Line 2: ONLY the last N words (gold, larger, bolder)
    
    Returns a combined string with both lines separated by backslash-N (newline).
    Both lines are centered (alignment=2).
    
    FIX for shadow: Use smaller, more transparent shadow.
    """
    # Get all words in the block
    all_words = [wd['word'].strip() for wd in block if wd['word'].strip()]
    
    if not all_words:
        return ''
    
    # Determine how many words go on each line
    n_total = len(all_words)
    n_second = min(words_in_second_line, n_total)  # Words on line 2
    n_first = n_total - n_second  # Words on line 1 (everything else)
    
    # If we don't have enough words for both lines, put all on line 2
    if n_first <= 0:
        # All words on line 2 in gold
        emphasis_text = ' '.join(all_words)
        # Shadow with transparency: \4a&H80& = 50% transparent black shadow
        line2 = f'{{\\q2\\fs{hl_size}\\c{hl_color}\\b1\\4a&H80&}}' + emphasis_text
        return line2
    
    # Split words: first part and second part (NO overlap)
    first_part_words = all_words[:n_first]  # Everything except last N
    second_part_words = all_words[n_first:]  # Only last N words
    
    # Line 1: First part in white (base style) - WITHOUT the last N words
    # Smaller font, no bold, transparent shadow
    first_sentence = ' '.join(first_part_words)
    line1 = f'{{\\q2\\fs{base_size}\\c{base_color}\\b0\\4a&H80&}}' + first_sentence
    
    # Line 2: Last N words in gold (highlight style) - ONLY these words
    # Larger font, bold, transparent shadow
    emphasis_text = ' '.join(second_part_words)
    line2 = f'{{\\q2\\fs{hl_size}\\c{hl_color}\\b1\\4a&H80&}}' + emphasis_text
    
    # Combine with newline separator (backslash-N is ASS newline command)
    return f'{line1}\\N{line2}'


def _apply_timeline_pos(line, mid_time, timeline):
    for seg in timeline:
        if seg['start'] <= mid_time <= seg['end']:
            if seg.get('mode') == '2':
                return f'{{\\an5\\pos({_CX},{_PLAY_RES_Y // 2})}}{line}'
            break
    return line


# ── Decorations ────────────────────────────────────────────────────────────────

def _write_watermark(f, vs, ve, text, base_size, base_color):
    wm_sz = max(12, base_size - 4)
    tag   = (
        f'{{\\an2\\pos({_CX},580)\\fs{wm_sz}'
        f'\\c{base_color}\\alpha&H40&\\shad1\\3c&H00000000&}}'
    )
    f.write(f'Dialogue: 0,{_fmt(vs)},{_fmt(ve + 5.0)},Default,,0,0,0,,{tag}{text}\n')


def _write_speaker_tag(f, vs, ve, speaker_name, speaker_title,
                       base_size, base_color, highlight_color):
    sa_x = 15
    sa_y = 100  # Moved down from 80 to 100
    ts   = _fmt(vs)
    te   = _fmt(min(vs + 6.0, ve))

    if speaker_name and speaker_name.strip():
        nm_sz = max(14, base_size - 8)  # Reduced from base_size - 4 to base_size - 8
        tag   = (
            f'{{\\an7\\pos({sa_x},{sa_y})\\fs{nm_sz}'
            f'\\c{highlight_color}\\b1\\shad0\\3c&H00000000&}}'  # Changed shad1 to shad0 (no shadow)
        )
        f.write(f'Dialogue: 2,{ts},{te},Default,,0,0,0,,{tag}{speaker_name.strip()}\n')
        sa_y += nm_sz + 4  # Reduced spacing from 6 to 4

    if speaker_title and speaker_title.strip():
        tl_sz = max(10, base_size - 12)  # Reduced from base_size - 8 to base_size - 12
        tag   = (
            f'{{\\an7\\pos({sa_x},{sa_y})\\fs{tl_sz}'
            f'\\c{base_color}\\shad0\\3c&H00000000&}}'  # Already had shad0
        )
        f.write(f'Dialogue: 2,{ts},{te},Default,,0,0,0,,{tag}{speaker_title.strip()}\n')


# ══════════════════════════════════════════════════════════════════════════════
# STRATEGY INTERFACE
# ══════════════════════════════════════════════════════════════════════════════

def generate_ass(
        input_path: str,
        output_path: str,
        project_folder: str,
        base_color: str,
        base_size: int,
        highlight_size: int,
        highlight_color: str,
        words_per_block: int,
        gap_limit: float,
        mode: str,
        vertical_position: int,
        alignment: int,
        font: str,
        outline_color: str,
        shadow_color: str,
        bold,
        italic,
        underline,
        strikeout,
        border_style: int,
        outline_thickness: float,
        shadow_size: float,
        uppercase: bool = False,
        face_modes: dict = None,
        remove_punctuation: bool = True,
        speaker_name: str = '',
        speaker_title: str = '',
        watermark_text: str = '') -> None:
    """
    Generate a single English/LTR ASS subtitle file from a JSON word-timing input.

    Handles all four display modes (highlight, no_highlight, word_by_word, norz),
    watermark, speaker tag, and dynamic face-mode timeline positioning.
    Does not perform any Arabic reshaping or bidi operations.
    """
    if face_modes is None:
        face_modes = {}

    filename  = os.path.basename(input_path)
    base_name = os.path.splitext(filename)[0]

    timeline  = _load_timeline(base_name, filename, project_folder)
    key, _    = _face_mode_key(base_name, filename)

    cur_alignment       = alignment
    cur_vertical_pos    = vertical_position
    if face_modes.get(key) == '2' and not timeline:
        cur_alignment    = 5
        cur_vertical_pos = 0

    try:
        with open(input_path, encoding='utf-8-sig') as fh:
            data = json.load(fh)
        print(f'[english] {filename}: {len(data.get("segments", []))} segments')
    except Exception as exc:
        print(f'[english] ERROR loading {input_path}: {exc}')
        return

    total_written = 0

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(_ass_header(
            font, base_size, base_color, outline_color, shadow_color,
            bold, italic, underline, strikeout,
            border_style, outline_thickness, shadow_size,
            cur_alignment, cur_vertical_pos,
        ))

        all_segs = data.get('segments', [])
        last_end = 0.0

        # ── Norz persistent decorations ───────────────────────────────────────
        if mode == 'norz' and all_segs:
            vs = all_segs[0].get('start', 0.0)
            ve = all_segs[-1].get('end',   vs + 60.0)

            if watermark_text and watermark_text.strip():
                _write_watermark(f, vs, ve, watermark_text, base_size, base_color)
                total_written += 1

            if speaker_name or speaker_title:
                _write_speaker_tag(
                    f, vs, ve,
                    speaker_name, speaker_title,
                    base_size, base_color, highlight_color,
                )
                total_written += 1

        # ── Two-line emphasis persistent decorations ──────────────────────────
        if mode == 'two_line_emphasis' and all_segs:
            vs = all_segs[0].get('start', 0.0)
            ve = all_segs[-1].get('end',   vs + 60.0)

            if watermark_text and watermark_text.strip():
                _write_watermark(f, vs, ve, watermark_text, base_size, base_color)
                total_written += 1

            if speaker_name or speaker_title:
                _write_speaker_tag(
                    f, vs, ve,
                    speaker_name, speaker_title,
                    base_size, base_color, highlight_color,
                )
                total_written += 1

        # ── Main subtitle loop ────────────────────────────────────────────────
        for segment in all_segs:
            raw_words = segment.get('words', [])
            n_words   = len(raw_words)
            i         = 0

            while i < n_words:
                block = []
                while len(block) < words_per_block and i < n_words:
                    cw = raw_words[i]
                    if 'word' in cw:
                        w_text = _clean_word(cw['word'], remove_punctuation)
                        if uppercase:
                            w_text = w_text.upper()
                        entry = {**cw, 'word': w_text}

                        if i + 1 < n_words:
                            nw = raw_words[i + 1]
                            if 'start' not in nw or 'end' not in nw:
                                nw_text = _clean_word(nw.get('word', ''), remove_punctuation)
                                if uppercase:
                                    nw_text = nw_text.upper()
                                entry['word'] += ' ' + nw_text
                                i += 1

                        block.append(entry)
                    i += 1

                if not block:
                    continue

                # Detect non-Arabic RTL content (Hebrew, Persian in LTR path)
                block_text = ''.join(wd.get('word', '') for wd in block)
                has_hebrew  = any('֐' <= c <= '׿' for c in block_text)
                has_persian = any('؀' <= c <= 'ۿ' for c in block_text)
                use_rtl     = has_hebrew or has_persian

                starts = [w.get('start', 0.0) for w in block]
                ends   = [w.get('end',   0.0) for w in block]

                if not starts:
                    continue

                # ── no_highlight: single line for the whole block duration ────
                if mode in ('no_highlight', 'sem_higlight'):
                    t_start = starts[0]
                    t_end   = ends[-1]
                    if t_start - last_end < gap_limit:
                        t_start = last_end
                    if t_end <= t_start:
                        t_end = t_start + 0.1

                    line = _build_no_highlight(block, base_size, base_color, use_rtl)
                    if timeline:
                        line = _apply_timeline_pos(line, (t_start + t_end) / 2, timeline)

                    f.write(
                        f'Dialogue: 0,{_fmt(t_start)},{_fmt(t_end)},'
                        f'Default,,0,0,0,,{line}\n'
                    )
                    last_end      = t_end
                    total_written += 1
                    continue

                # ── two_line_emphasis: full sentence + emphasis on last N words ─
                if mode == 'two_line_emphasis':
                    t_start = starts[0]
                    t_end   = ends[-1]
                    
                    # Enhanced timing for better voice synchronization
                    # Calculate actual speech duration
                    actual_duration = t_end - t_start
                    
                    # Ensure minimum duration for readability (adaptive based on word count)
                    words_count = len(block)
                    min_duration = max(1.8, words_count * 0.35)  # 0.35s per word, minimum 1.8s
                    if actual_duration < min_duration:
                        t_end = t_start + min_duration
                    
                    # Smart gap handling - bridge very small gaps but respect natural pauses
                    gap_to_last = t_start - last_end
                    if gap_to_last < 0.15:  # Very small gap (<150ms), bridge it
                        t_start = last_end
                    elif gap_to_last < 0.4:  # Small gap (150-400ms), partial bridge
                        t_start = last_end + (gap_to_last * 0.3)  # Bridge 30% of gap
                    # Gaps >= 400ms are kept as natural pauses
                    
                    # Build combined two-line text with proper split (no duplication)
                    # words_per_block controls segment size, we default words_in_second_line to 2
                    words_in_second_line = 2  # Default: last 2 words in gold
                    combined_line = _build_two_line_emphasis(
                        block, base_size, base_color,
                        highlight_size, highlight_color,
                        words_in_second_line
                    )
                    
                    if not combined_line:
                        continue
                    
                    # Apply dynamic positioning if timeline available
                    if timeline:
                        combined_line = _apply_timeline_pos(combined_line, (t_start + t_end) / 2, timeline)
                    
                    # Write single dialogue event with both lines
                    f.write(
                        f'Dialogue: 0,{_fmt(t_start)},{_fmt(t_end)},'
                        f'Default,,0,0,0,,{combined_line}\n'
                    )
                    
                    last_end      = t_end
                    total_written += 1
                    continue

                # ── Per-word dialogue lines ───────────────────────────────────
                for j in range(len(block)):
                    t_start = starts[j]
                    t_end   = ends[j]

                    if t_start - last_end < gap_limit:
                        t_start = last_end
                    if t_end < t_start:
                        t_end = t_start

                    ts       = _fmt(t_start)
                    te       = _fmt(t_end)
                    last_end = t_end

                    if mode == 'norz':
                        sub_y = vertical_position if vertical_position else 400
                        line  = _build_norz(
                            block, j,
                            base_size, base_color,
                            highlight_size, highlight_color,
                            sub_y,
                        )
                    elif mode == 'highlight':
                        line = _build_highlight(
                            block, j,
                            base_size, base_color,
                            highlight_size, highlight_color,
                            use_rtl,
                        )
                    elif mode in ('palavra_por_palavra', 'word_by_word'):
                        line = _build_word_by_word(
                            block[j]['word'],
                            base_size, base_color,
                            use_rtl,
                        )
                    else:
                        line = _build_no_highlight(block, base_size, base_color, use_rtl)

                    if timeline:
                        line = _apply_timeline_pos(
                            line, (t_start + t_end) / 2, timeline,
                        )

                    f.write(
                        f'Dialogue: 0,{ts},{te},Default,,0,0,0,,{line}\n'
                    )
                    total_written += 1

    if total_written == 0:
        print(f'[english] WARN: no dialogue lines written for {filename}')
    else:
        print(f'[english] {total_written} lines -> {os.path.basename(output_path)}')


def adjust(
        base_color: str,
        base_size: int,
        highlight_size: int,
        highlight_color: str,
        words_per_block: int,
        gap_limit: float,
        mode: str,
        vertical_position: int,
        alignment: int,
        font: str,
        outline_color: str,
        shadow_color: str,
        bold,
        italic,
        underline,
        strikeout,
        border_style: int,
        outline_thickness: float,
        shadow_size: float,
        uppercase: bool = False,
        project_folder: str = 'tmp',
        **kwargs) -> None:
    """
    Batch-process every JSON subtitle file in project_folder/subs and write
    the resulting ASS files to project_folder/subs_ass.
    """
    input_dir  = os.path.join(project_folder, 'subs')
    output_dir = os.path.join(project_folder, 'subs_ass')
    os.makedirs(output_dir, exist_ok=True)

    remove_punctuation = kwargs.get('remove_punctuation', True)
    speaker_name       = kwargs.get('speaker_name',   '') or ''
    speaker_title      = kwargs.get('speaker_title',  '') or ''
    watermark_text     = kwargs.get('watermark_text', '') or ''

    face_modes = {}
    modes_file = os.path.join(project_folder, 'face_modes.json')
    if os.path.exists(modes_file):
        try:
            with open(modes_file, encoding='utf-8') as fh:
                face_modes = json.load(fh)
            print('[english] Loaded face modes for dynamic positioning.')
        except Exception as exc:
            print(f'[english] Could not load face modes: {exc}')

    if not os.path.exists(input_dir):
        raise FileNotFoundError(
            f'[english] Subtitle folder not found: {input_dir}\n'
            'Ensure transcription completed successfully before running subtitles.'
        )

    processed = 0
    for filename in sorted(os.listdir(input_dir)):
        if not filename.endswith('.json'):
            continue
        in_path  = os.path.join(input_dir, filename)
        out_name = os.path.splitext(filename)[0] + '.ass'
        out_path = os.path.join(output_dir, out_name)

        generate_ass(
            in_path, out_path, project_folder,
            base_color, base_size, highlight_size, highlight_color,
            words_per_block, gap_limit, mode, vertical_position, alignment,
            font, outline_color, shadow_color, bold, italic, underline,
            strikeout, border_style, outline_thickness, shadow_size,
            uppercase, face_modes, remove_punctuation,
            speaker_name, speaker_title, watermark_text,
        )
        print(f'[english] {filename} -> {out_name}')
        processed += 1

    print(f'[english] Complete — {processed} file(s) processed.')
