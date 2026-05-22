"""
arabic_handler.py — Arabic Subtitle Implementation for ViralCutter
════════════════════════════════════════════════════════════════════

IMPLEMENTATION MODULE — do not call directly from the shared pipeline.
The public entry-point is renderer_arabic.py, which wraps this module
and exposes the standard renderer interface (generate_ass / adjust).

  renderer_arabic.generate_ass()  ──►  generate_arabic_ass_from_file()
  renderer_arabic.adjust()        ──►  adjust_arabic()
  renderer_arabic.*helpers*       ──►  the matching functions below

TO FIX ARABIC BUGS (disconnected letters, boxes, wrong direction):
  Edit this file.  renderer_english.py and the shared pipeline are
  completely unaffected.

MODULE STRUCTURE (11 sections):
  §1  Constants              — Unicode patterns, timing constants
  §2  Language gate          — is_arabic(), has_arabic_chars(), reshape_arabic(),
                               prepare_arabic_text() [alias — call this at ASS emit]
  §3  Font management        — ensure_arabic_fonts_cached(), resolve_arabic_font()
  §4  Text processing        — clean_word() [pure normalisation, no reshape],
                               strip_diacritics(), NFC normalisation
  §5  Timing utilities       — _fmt(), redistribute_arabic_timing()
  §6  ASS format utilities   — _ass_header()
  §7  Line builders          — one builder per display mode; each calls
                               prepare_arabic_text() before embedding text in ASS tags
  §8  Decorations            — watermark, speaker label (also call prepare_arabic_text)
  §9  Core ASS generation    — generate_arabic_ass_from_file()
  §10 Batch entry point      — adjust_arabic()
  §11 Translation helpers    — prompt building, post-processing
"""

import json
import os
import re
import shutil
import unicodedata

try:
    import arabic_reshaper as _ar_reshaper
    from bidi.algorithm import get_display as _bidi_display
    _SHAPING_AVAILABLE = True
except ImportError:
    _ar_reshaper = None
    _bidi_display = None
    _SHAPING_AVAILABLE = False
    print('[arabic] WARNING: arabic_reshaper / python-bidi not installed. '
          'Run: pip install arabic-reshaper python-bidi')

# ═══════════════════════════════════════════════════════════════════════════════
# §1  CONSTANTS
# ═══════════════════════════════════════════════════════════════════════════════

# Tatweel (kashida, U+0640) — purely decorative stretcher, no semantic value
_TATWEEL = 'ـ'

# Tashkeel / harakaat — combining short-vowel marks.  AI translators sometimes
# output them; they cause irregular spacing and unexpected glyph variants.
_DIACRITICS_RE = re.compile(
    '[ً-ٟ'   # fathatan … sukun  (core harakaat)
    'ؐ-ؚ'    # Arabic honorific signs
    'ٰ'           # superscript alef
    'ۖ-ۜ'    # Quranic annotation signs
    '۟-ۤ'    # Quranic annotation signs (continued)
    'ۧۨ'     # Quranic above / below signs
    '۪-ۭ'    # Quranic meem isolated …
    'ࣔ-ࣿ]'   # Arabic Extended-A combining marks
)

# Invisible / directional Unicode marks that libass renders as □ rectangles.
# All written as explicit \uXXXX escapes — never as literal characters —
# so the pattern is encoding-safe regardless of how this file is saved.
# Expanded to catch ALL problematic invisible characters from Whisper
_INVISIBLE_RE = re.compile(
    '[\u200B-\u200F'   # ZWSP, ZWNJ, ZWJ, LRM, RLM
    '\u202A-\u202E'    # directional embedding / override controls
    '\u2060-\u2064'    # word joiner, invisible math operators
    '\u2066-\u2069'    # bidi isolate controls (LTRI, RTLI, PDI, POP DI)
    '\uFEFF'           # BOM / ZWNBSP
    '\u00AD'           # soft hyphen (glyphless in most Arabic fonts)
    '\u061C'           # Arabic Letter Mark (invisible)
    '\u180E'           # Mongolian Vowel Separator
    '\u2000-\u200A'    # Various space characters (en quad, em quad, etc.)
    '\u2028-\u2029'    # Line/paragraph separators
    '\u205F-\u2065'    # Mathematical spaces and invisible operators
    '\uFFF0-\uFFFF]'   # Specials block (non-characters)
)

# ASCII control characters (0x00–0x1F and DEL / C1)
_CONTROL_RE = re.compile(r'[\x00-\x1F\x7F-\x9F]')

# Punctuation stripped in remove_punctuation mode (ASCII + Arabic forms)
_PUNCT_RE = re.compile(
    r'[.,!?;:'
    r'،'   # Arabic comma  ،
    r'؛'   # Arabic semicolon  ؛
    r'؟'   # Arabic question mark  ؟
    r'۔'   # Arabic full stop  ۔
    r']'
)

# Minimum per-word display duration (seconds) — Arabic needs a little more time
_MIN_WORD_DUR = 0.15

# Horizontal centre of the 360 × 640 ASS canvas
_CX = 180

# Common Arabic function/stop words to skip when using heuristic important-word detection
_ARABIC_STOP_WORDS = {
    'في', 'من', 'إلى', 'على', 'عن', 'مع', 'هو', 'هي', 'هم', 'هن', 'هما',
    'أنا', 'أنت', 'أنتِ', 'أنتم', 'نحن', 'هذا', 'هذه', 'ذلك', 'تلك',
    'التي', 'الذي', 'اللذين', 'اللتين', 'الذين', 'و', 'ف', 'ثم', 'أو',
    'لكن', 'لأن', 'إذا', 'كان', 'كانت', 'يكون', 'تكون', 'ما', 'لا', 'لم',
    'لن', 'قد', 'أن', 'إن', 'كل', 'بعض', 'كما', 'حتى', 'بل', 'لقد',
    'وقد', 'وكان', 'وكانت', 'هل', 'كيف', 'لماذا', 'متى', 'أين', 'من',
    'إذ', 'بما', 'فما', 'وما', 'ولا', 'ولم', 'ولن', 'وإن', 'فإن',
}

# ═══════════════════════════════════════════════════════════════════════════════
# §2  LANGUAGE GATE
# ═══════════════════════════════════════════════════════════════════════════════

def is_arabic(lang: str) -> bool:
    """Return True only when *lang* resolves to the Arabic language code ('ar')."""
    return bool(lang) and lang.split('-')[0].lower() == 'ar'


def has_arabic_chars(text: str) -> bool:
    """Return True if *text* contains at least one core Arabic-block character."""
    return any('؀' <= c <= 'ۿ' for c in text)


def reshape_arabic(text: str) -> str:
    """
    Connect Arabic letter forms for libass rendering.

    Single-step process applied only when the text contains Arabic characters:
      1. arabic_reshaper.reshape()  — converts isolated/initial/medial/final
         letter code-points to their contextually-joined presentation forms so
         that libass displays connected letters instead of isolated glyphs.

    IMPORTANT: We do NOT apply bidi.algorithm.get_display() here because libass
    implements the Unicode Bidirectional Algorithm (UAX #9) internally. Applying
    bidi twice (once here + once in libass) causes double-reversal, making text
    appear LTR instead of RTL.

    The correct flow is:
      - Logical order (as spoken) → arabic_reshaper → connected letters
      - libass receives connected letters in logical order → libass applies bidi → RTL display

    English and other non-Arabic strings are returned unchanged.
    """
    if not _SHAPING_AVAILABLE or not text or not has_arabic_chars(text):
        return text
    return _ar_reshaper.reshape(text)


# Alias used at every ASS text emission point — keeps call sites readable.
prepare_arabic_text = reshape_arabic

# ═══════════════════════════════════════════════════════════════════════════════
# §3  FONT MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

_SCRIPT_DIR   = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_SCRIPT_DIR)
_SOURCE_FONTS = os.path.join(_PROJECT_ROOT, 'arabic font')   # bundled OTFs
_VCFONTS_DIR  = r'C:\vcfonts'                                 # no-space path for libass

_WIN_ARABIC_FALLBACKS = (
    'arial.ttf', 'arialbd.ttf', 'arialuni.ttf',
    'tahoma.ttf', 'tahomabd.ttf',
)


def ensure_arabic_fonts_cached() -> None:
    """
    Copy Lyon Arabic Display OTFs and Windows Arabic fallback TTFs to
    C:\\vcfonts\\ (space-free path required by libass / ffmpeg).

    Idempotent — safe to call on every generation run.
    Lyon Arabic Display is copied fresh each run (to pick up any updates).
    Windows system fonts are copied only if not already present.
    """
    os.makedirs(_VCFONTS_DIR, exist_ok=True)

    # Bundled premium Arabic fonts (Lyon Arabic Display family)
    if os.path.isdir(_SOURCE_FONTS):
        for fname in os.listdir(_SOURCE_FONTS):
            if fname.lower().endswith(('.otf', '.ttf')):
                try:
                    shutil.copy2(
                        os.path.join(_SOURCE_FONTS, fname),
                        os.path.join(_VCFONTS_DIR, fname),
                    )
                except Exception as exc:
                    print(f'[arabic] Warning: could not copy font {fname}: {exc}')

    # Windows system fonts with full Arabic Unicode coverage (glyph fallbacks)
    win_fonts = r'C:\Windows\Fonts'
    for fname in _WIN_ARABIC_FALLBACKS:
        src = os.path.join(win_fonts, fname)
        dst = os.path.join(_VCFONTS_DIR, fname)
        if os.path.exists(src) and not os.path.exists(dst):
            try:
                shutil.copy2(src, dst)
            except Exception as exc:
                print(f'[arabic] Warning: could not copy system font {fname}: {exc}')


_ARABIC_CAPABLE_FONTS = {
    # fonts known to ship with full Arabic Unicode coverage
    'arial', 'arial unicode ms', 'tahoma', 'times new roman',
    'microsoft sans serif', 'segoe ui', 'calibri', 'cambria',
    'palatino linotype', 'traditional arabic', 'simplified arabic',
    'arabic typesetting', 'sakkal majalla', 'andalus', 'aldhabi',
    'scheherazade', 'amiri', 'noto naskh arabic', 'noto sans arabic',
    'lateef', 'harmattan', 'reem kufi',
    # bundled project fonts
    'lyon arabic display',
}


def resolve_arabic_font(preferred: str) -> str:
    """
    Return the best Arabic-capable font name for this ASS file.

    Selection rules (evaluated in order)
    ─────────────────────────────────────
    • Blank                   →  'Arial'
    • Contains 'lyon'         →  'Lyon Arabic Display'
    • In known-capable list   →  returned as-is (exact name preserved)
    • Anything else           →  'Arial' (safe fallback for unknown fonts
                                  such as Montserrat, Roboto, Poppins which
                                  carry no Arabic glyphs at all)
    """
    if not preferred:
        return 'Arial'
    lower = preferred.lower().strip()
    if 'lyon' in lower:
        return 'Lyon Arabic Display'
    if lower in _ARABIC_CAPABLE_FONTS:
        return preferred
    # Unknown / Latin-only font — fall back to guaranteed Arabic coverage
    return 'Arial'

# ═══════════════════════════════════════════════════════════════════════════════
# §4  TEXT PROCESSING
# ═══════════════════════════════════════════════════════════════════════════════

def _nfc(text: str) -> str:
    """
    Apply Unicode NFC normalization to *text*.

    Converts decomposed sequences to precomposed forms, e.g.:
      alef U+0627 + combining hamza above U+0654  →  alef-with-hamza U+0623

    Fonts carry glyphs for precomposed forms.  Without NFC, Whisper-transcribed
    Arabic often contains decomposed sequences whose combining variant has no
    glyph, causing libass to render □ rectangles.  This is the single most
    impactful fix for rectangle artifacts in Arabic subtitle pipelines.
    """
    return unicodedata.normalize('NFC', text)


def strip_invisible(text: str) -> str:
    """Remove invisible / directional Unicode marks and ASCII control chars."""
    return _INVISIBLE_RE.sub('', _CONTROL_RE.sub('', text))


def strip_diacritics(text: str) -> str:
    """
    Remove Arabic tashkeel (short vowel / harakaat marks).

    NFC normalization must be applied BEFORE this step so that precomposed
    letters (e.g. alef-with-hamza U+0623) are not confused with the bare
    combining hamza (U+0654) that this function would otherwise strip.
    """
    return _DIACRITICS_RE.sub('', text)


def clean_word(word: str, remove_punctuation: bool = True) -> str:
    """
    Pure normalization pipeline for a single Arabic word token.

    Does NOT reshape or apply bidi — call prepare_arabic_text() on the
    final text string just before writing it to the ASS file.

    Execution order (each step feeds into the next):
      1. Strip NULL bytes          — U+0000 (Whisper sometimes outputs these)
      2. NFC normalization         — precomposed chars eliminate combining-form □ boxes
      3. Control char strip        — ASCII 0x00–0x1F, 0x7F–0x9F
      4. Invisible mark strip      — ALL invisible Unicode marks (expanded list)
      5. Zero-width char strip     — Remove ALL zero-width characters explicitly
      6. Tatweel removal           — U+0640 kashida (purely decorative)
      7. Diacritics removal        — harakaat, shadda, sukun, and Quranic marks
      8. Punctuation removal       — ASCII + Arabic punct forms (when requested)
      9. Whitelist filter          — drops private-use, surrogates, unknown chars
                                     that would be rendered as □ by libass
    """
    # Step 1: Strip NULL bytes first (Whisper transcription artifact)
    word = word.replace('\x00', '')
    
    # Step 2: NFC normalization
    word = _nfc(word)
    
    # Step 3: Control characters
    word = _CONTROL_RE.sub('', word)
    
    # Step 4: Invisible marks
    word = _INVISIBLE_RE.sub('', word)
    
    # Step 5: Explicitly strip ALL zero-width characters (catch any missed by regex)
    zero_width_chars = [
        '\u200B',  # ZERO WIDTH SPACE
        '\u200C',  # ZERO WIDTH NON-JOINER
        '\u200D',  # ZERO WIDTH JOINER
        '\uFEFF',  # ZERO WIDTH NO-BREAK SPACE (BOM)
        '\u2060',  # WORD JOINER
        '\u2061',  # FUNCTION APPLICATION
        '\u2062',  # INVISIBLE TIMES
        '\u2063',  # INVISIBLE SEPARATOR
        '\u2064',  # INVISIBLE PLUS
    ]
    for zw_char in zero_width_chars:
        word = word.replace(zw_char, '')
    
    # Step 6: Tatweel removal
    word = word.replace(_TATWEEL, '')
    
    # Step 7: Diacritics removal
    word = strip_diacritics(word)
    
    # Step 8: Punctuation removal
    if remove_punctuation:
        word = _PUNCT_RE.sub('', word)

    # Step 9: Whitelist filter - ONLY keep valid characters
    # Everything else (private-use area, surrogates, unknown Unicode planes) is dropped.
    word = re.sub(
        r'[^ -~'              # printable ASCII  U+0020–U+007E
        r'À-ʯ'      # Latin Extended (accented characters)
        r'\u0600-\u06FF'      # Arabic (core block U+0600-U+06FF)
        r'\u0750-\u077F'      # Arabic Supplement (U+0750-U+077F)
        r'\u08A0-\u08FF'      # Arabic Extended-A (U+08A0-U+08FF)
        r'\uFB50-\uFDFF'      # Arabic Presentation Forms-A (U+FB50-U+FDFF)
        r'\uFE70-\uFEFE'      # Arabic Presentation Forms-B (U+FE70-U+FEFE, EXCLUDE U+FEFF which is BOM)
        r']', '', word
    )
    return word

# ═══════════════════════════════════════════════════════════════════════════════
# §5  TIMING UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

def _fmt(t: float) -> str:
    """Format *t* seconds as an ASS timestamp string  H:MM:SS.cs."""
    h  = int(t // 3600)
    m  = int((t % 3600) // 60)
    s  = int(t % 60)
    cs = int((t % 1) * 100)
    return f'{h:01}:{m:02}:{s:02}.{cs:02}'


def redistribute_arabic_timing(segment: dict, translated_text: str) -> None:
    """
    Redistribute per-word timestamps within a segment after Arabic translation.

    Arabic words are highly variable in length (short function words vs. long
    root-derived forms).  Proportional allocation by character count gives each
    word screen time proportional to how long it takes to read.

    Segment-level start / end boundaries are preserved; only the intra-word
    split points change.  A minimum per-word floor (_MIN_WORD_DUR) prevents
    very short words from being invisible.
    """
    words = translated_text.strip().split()
    if not words:
        return

    seg_start = segment.get('start', 0.0)
    seg_end   = segment.get('end',   seg_start + 2.0)
    duration  = max(0.05, seg_end - seg_start)

    # Enforce minimum total duration so every word is readable
    min_total = _MIN_WORD_DUR * len(words)
    if min_total > duration:
        duration = min_total

    char_counts = [max(1, len(w)) for w in words]
    total_chars = sum(char_counts)

    current   = seg_start
    new_words = []
    for word, chars in zip(words, char_counts):
        dur = max(_MIN_WORD_DUR, duration * (chars / total_chars))
        new_words.append({
            'word':  word,
            'start': round(current, 3),
            'end':   round(current + dur, 3),
            'score': 1.0,
        })
        current += dur

    segment['words'] = new_words
    segment['text']  = translated_text

# ═══════════════════════════════════════════════════════════════════════════════
# §6  ASS FORMAT UTILITIES
# ═══════════════════════════════════════════════════════════════════════════════

def _ass_header(font: str, base_size: int, base_color: str,
                outline_color: str, shadow_color: str,
                bold: str, italic: str, underline: str, strikeout: str,
                border_style: int, outline_thickness: float, shadow_size: float,
                alignment: int, vertical_position: int) -> str:
    """
    Build the complete ASS file header block.

    Canvas: 360 × 640 px (9:16 vertical video).
    ScaledBorderAndShadow: yes — keeps outlines crisp at any render resolution.
    Encoding: 1 — Arabic / Hebrew codepage; helps some libass builds with shaping.
    MarginL / MarginR are 0 (not -2) for clean edge-to-edge text placement.
    """
    return (
        '[Script Info]\n'
        'Title: Arabic Subtitles — ViralCutter\n'
        'ScriptType: v4.00+\n'
        'WrapStyle: 0\n'
        'PlayDepth: 0\n'
        'PlayResX: 360\n'
        'PlayResY: 640\n'
        'ScaledBorderAndShadow: yes\n'
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
        f'{alignment},0,0,{vertical_position},1\n'
        '\n'
        '[Events]\n'
        'Format: Layer, Start, End, Style, Name, '
        'MarginL, MarginR, MarginV, Effect, Text\n'
    )

# ═══════════════════════════════════════════════════════════════════════════════
# §7  LINE BUILDERS  (one per display mode)
# ═══════════════════════════════════════════════════════════════════════════════
#
# RTL DIRECTION
# ─────────────
# libass implements UAX #9 (Unicode Bidi Algorithm).  Arabic characters are
# strong RTL, so the bidi algorithm automatically places the first-written
# Arabic word on the visual RIGHT of the subtitle line.
#
# Words are written in spoken / logical order (word0 first).  The bidi
# algorithm then renders them right-to-left on screen:
#
#   written:   word0  word1  word2
#   on screen: [word2] [word1] [word0 ◄ rightmost, read first in Arabic]
#
# DO NOT manually reverse word order — that creates a double-reversal and
# produces LTR output.  The bidi algorithm handles everything.
#
# ASS TAG REFERENCE used below
# ─────────────────────────────
#   {\q2}           no word-wrap (extend frame beyond canvas edge)
#   {\an5}          centre-centre anchor  (norz mode)
#   {\pos(x,y)}     explicit position     (norz + timeline override)
#   {\fs N}         font-size override
#   {\c &HBBGGRR&}  primary colour override
#   {\b1} {\b0}     bold on / off
#   {\shad N}       drop-shadow depth (px)
#   {\3c &H…&}      outline colour
#   {\fad(i,o)}     fade-in (ms) / fade-out (ms)


def _build_highlight(block: list, j: int,
                     base_size: int, base_color: str,
                     hl_size: int, hl_color: str) -> str:
    """
    Highlight mode — all block words shown simultaneously.

    Word j (currently spoken) is rendered at hl_size / hl_color / bold.
    All other words use base_size / base_color / regular weight.
    
    FIX for RTL:
    1. Extract raw words and join them FIRST (before any processing)
    2. Apply arabic_reshaper ONLY (no bidi - libass handles RTL internally)
    3. Split processed line back into words
    4. Apply ASS styling tags to each word using original index j
    5. Join styled words for final output
    
    IMPORTANT: We do NOT reverse the index because:
      - arabic_reshaper only connects letters (doesn't change word order)
      - libass implements UAX #9 bidi algorithm internally
      - libass receives words in logical/spoken order
      - libass renders them RTL automatically
      - So word j=0 (first spoken) appears on RIGHT side visually
      - Karaoke naturally flows RIGHT → LEFT as j increases
    """
    # Step 1: Extract raw words (already cleaned by caller)
    raw_words = [wd['word'] for wd in block]
    
    # Step 2: Join into complete plain text line BEFORE any processing
    joined_line = ' '.join(raw_words)
    
    # Step 3: Apply reshape ONLY to complete line if it contains Arabic
    # NO bidi - libass handles RTL rendering internally
    if has_arabic_chars(joined_line):
        processed_line = prepare_arabic_text(joined_line)
        # Split back into words (order unchanged, only letter shapes changed)
        visual_words = processed_line.split(' ')
    else:
        visual_words = raw_words
    
    # Step 4: Apply ASS styling to each word using ORIGINAL index j
    # No index reversal needed - libass handles RTL display
    parts = []
    for k, word in enumerate(visual_words):
        if k == j:  # Use original j, no reversal!
            # Currently spoken word - highlighted
            parts.append(f'{{\\fs{hl_size}\\c{hl_color}\\b1}}{word}')
        else:
            # Other words - normal style
            parts.append(f'{{\\fs{base_size}\\c{base_color}\\b0}}{word}')
    
    # Step 5: Join styled words
    styled_line = ' '.join(parts)
    return '{\\q2}' + styled_line


def _build_no_highlight(block: list,
                        base_size: int, base_color: str) -> str:
    """
    No-highlight mode — all block words shown in uniform style.

    A single dialogue line covers the full block's time span (start of first
    word → end of last word), so the text remains stable on screen without
    flickering between overlapping identical lines.
    
    FIX for RTL: Join raw words first, then apply Arabic processing to complete line.
    """
    # Join raw words first
    joined = ' '.join(wd['word'] for wd in block).strip()
    # Then apply Arabic processing to the complete line
    processed = prepare_arabic_text(joined)
    return f'{{\\q2\\fs{base_size}\\c{base_color}}}‏' + processed


def _build_word_by_word(word: str,
                        base_size: int, base_color: str) -> str:
    """
    Word-by-word (palavra_por_palavra) mode — one word per dialogue line.
    
    FIX for RTL: Apply Arabic processing to the complete word.
    """
    processed = prepare_arabic_text(word)
    return f'{{\\q2\\fs{base_size}\\c{base_color}}}' + processed


_TRAILING_PUNCT = re.compile(r'([\s]*[.,:;؟،؛!?\'\"]+[\s]*)$')
_RLM = '‏'  # Right-to-Left Mark


def _reshape_rtl(text: str) -> str:
    """
    Reshape Arabic text while keeping trailing punctuation at the logical end.

    arabic_reshaper processes the full string and may push trailing neutral
    punctuation (.  :  '  ،  ؟) to the visual start of the RTL run.  We
    strip the punctuation first, reshape only the Arabic portion, then
    re-attach the punctuation so libass sees it as a trailing neutral
    character and places it at the visual LEFT (RTL phrase end).
    """
    m = _TRAILING_PUNCT.search(text)
    if m:
        punct = m.group(1).strip()
        arabic_part = text[:m.start()].rstrip()
        reshaped = prepare_arabic_text(arabic_part) if arabic_part else ''
        return reshaped + punct
    return prepare_arabic_text(text)


def _build_two_line_emphasis(block: list,
                             base_size: int, base_color: str,
                             highlight_size: int, highlight_color: str,
                             words_in_second_line: int = 2) -> tuple:
    """
    Two-line emphasis mode - splits block into two lines with NO duplication.

    Line 1: All words EXCEPT the last N words (white, smaller, lighter)
    Line 2: ONLY the last N words (gold, larger, bolder)

    Returns a tuple of (line1, line2) where both are properly formatted ASS
    dialogue lines.  Both lines are centered (alignment=2).

    RTL punctuation fix: _reshape_rtl() strips trailing punctuation before
    reshaping, then re-attaches it so libass keeps it at the visual LEFT
    (phrase end).  A trailing RLM anchors the bidi paragraph direction so
    any remaining neutral characters also stay at the RTL end.
    """
    all_words = [wd['word'] for wd in block if wd['word'].strip()]

    if not all_words:
        return ('', '')

    n_total  = len(all_words)
    n_second = min(words_in_second_line, n_total)
    n_first  = n_total - n_second

    if n_first <= 0:
        emphasis_text    = ' '.join(all_words)
        processed_line2  = _reshape_rtl(emphasis_text)
        line2 = (f'{{\\q2\\fs{highlight_size}\\c{highlight_color}\\b1\\4a&H20&}}'
                 + _RLM + processed_line2 + _RLM)
        return ('', line2)

    first_part_words  = all_words[:n_first]
    second_part_words = all_words[n_first:]

    first_sentence   = ' '.join(first_part_words)
    processed_line1  = _reshape_rtl(first_sentence)
    line1 = (f'{{\\q2\\fs{base_size}\\c{base_color}\\b0\\4a&H20&}}'
             + _RLM + processed_line1 + _RLM)

    emphasis_text    = ' '.join(second_part_words)
    processed_line2  = _reshape_rtl(emphasis_text)
    line2 = (f'{{\\q2\\fs{highlight_size}\\c{highlight_color}\\b1\\4a&H20&}}'
             + _RLM + processed_line2 + _RLM)

    return (line1, line2)


# ═══════════════════════════════════════════════════════════════════════════════
# §8  DECORATIONS  (watermark, speaker label)
# ═══════════════════════════════════════════════════════════════════════════════

def _write_watermark(f, vs: float, ve: float,
                     text: str, base_size: int, base_color: str,
                     wm_transparency: int = 25,
                     wm_outline: float = 0,
                     wm_shadow: float = 1) -> int:
    """
    Write a persistent watermark at the bottom of the video (Zone C).

    wm_transparency: 0 = fully visible, 100 = invisible. Default 25 (25% transparent).
    wm_outline:      outline/border thickness in pixels. Default 0.
    wm_shadow:       shadow depth in pixels. Default 1.
    """
    wm_sz = max(12, base_size - 4)
    cleaned = clean_word(text, remove_punctuation=False)
    processed = prepare_arabic_text(cleaned)
    alpha_hex = format(min(255, max(0, int(wm_transparency / 100 * 255))), '02X')
    tag = (
        f'{{\\an2\\pos({_CX},580)\\fs{wm_sz}'
        f'\\c{base_color}\\alpha&H{alpha_hex}&'
        f'\\bord{wm_outline}\\shad{wm_shadow}\\3c&H00000000&\\q2}}'
    )
    f.write(
        f'Dialogue: 0,{_fmt(vs)},{_fmt(ve + 5.0)},Default,,0,0,0,,{tag}{processed}\n'
    )
    return 1


def _write_speaker_tag(f, vs: float, ve: float,
                       speaker_name: str, speaker_title: str,
                       base_size: int, base_color: str,
                       highlight_color: str,
                       name_size: int = 0,
                       title_size: int = 0) -> int:
    """
    Write speaker name + title (Zone A, top-left) visible during the first 6 seconds.

    name_size / title_size: explicit font sizes; 0 = auto (base_size-relative).
    """
    written = 0
    sa_x    = 15
    sa_y    = 100
    ts      = _fmt(vs)
    te      = _fmt(min(vs + 3.0, ve))

    if speaker_name and speaker_name.strip():
        nm_sz = name_size if name_size > 0 else max(14, base_size - 8)
        cleaned_name = clean_word(speaker_name.strip(), remove_punctuation=False)
        text = prepare_arabic_text(cleaned_name)
        tag = (
            f'{{\\an7\\pos({sa_x},{sa_y})\\fs{nm_sz}'
            f'\\c{highlight_color}\\b1\\shad0\\3c&H00000000&\\q2}}'
        )
        f.write(f'Dialogue: 2,{ts},{te},Default,,0,0,0,,{tag}{text}\n')
        sa_y   += nm_sz + 4
        written += 1

    if speaker_title and speaker_title.strip():
        tl_sz = title_size if title_size > 0 else max(10, base_size - 12)
        cleaned_title = clean_word(speaker_title.strip(), remove_punctuation=False)
        text = prepare_arabic_text(cleaned_title)
        tag = (
            f'{{\\an7\\pos({sa_x},{sa_y})\\fs{tl_sz}'
            f'\\c{base_color}\\shad0\\3c&H00000000&\\q2}}'
        )
        f.write(f'Dialogue: 2,{ts},{te},Default,,0,0,0,,{tag}{text}\n')
        written += 1

    return written

# ═══════════════════════════════════════════════════════════════════════════════
# §9  CORE ASS GENERATION PIPELINE
# ═══════════════════════════════════════════════════════════════════════════════

def _load_timeline(base_name: str, filename: str, project_folder: str):
    """
    Locate and load the per-clip face-mode timeline JSON.

    Tries two naming conventions used by the ViralCutter pipeline:
      1. <base>_timeline.json           (renamed output)
      2. temp_video_no_audio_N_timeline.json  (temp output by index)

    Returns the parsed list on success, None if no timeline exists.
    """
    # Convention 1: renamed timeline
    tl_name = base_name.replace('_processed', '') + '_timeline.json'
    tl_path = os.path.join(project_folder, 'final', tl_name)
    if os.path.exists(tl_path):
        try:
            with open(tl_path, encoding='utf-8') as fh:
                return json.load(fh)
        except Exception:
            pass

    # Convention 2: temp timeline by numeric index
    m_out = re.search(r'output(\d+)', filename)
    m_idx = re.search(r'^(\d{3})_',  filename)
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


def generate_arabic_ass_from_file(
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
        bold: str,
        italic: str,
        underline: str,
        strikeout: str,
        border_style: int,
        outline_thickness: float,
        shadow_size: float,
        uppercase: bool = False,
        face_modes: dict = None,
        remove_punctuation: bool = True,
        speaker_name: str = '',
        speaker_title: str = '',
        watermark_text: str = '',
        wm_transparency: int = 25,
        wm_outline: float = 0,
        wm_shadow: float = 1,
        spk_name_size: int = 0,
        spk_title_size: int = 0) -> None:
    """
    Convert a single JSON subtitle file to an Arabic-formatted ASS file.

    This is the Arabic-only counterpart of adjust_subtitles.generate_ass_from_file().
    Called exclusively when lang == 'ar'.  The calling signature is identical to
    the main pipeline function so no argument transformation is needed in the caller.

    Processing order
    ────────────────
    1. Cache Arabic fonts to C:\\vcfonts
    2. Resolve font name (Montserrat → Arial, etc.)
    3. Load optional face-mode timeline for dynamic positioning
    4. Determine static alignment fallback from face_modes.json
    5. Load and validate the JSON subtitle file
    6. Write ASS header
    7. Write norz persistent decorations (watermark + speaker tag)
    8. For each segment → each block → each word:
         a. Clean and normalise word text
         b. Apply uppercase if requested
         c. Bridge timing gaps
         d. Build ASS line for the active display mode
         e. Apply dynamic timeline position override if applicable
         f. Write dialogue line
    """
    if face_modes is None:
        face_modes = {}

    # ── Setup ─────────────────────────────────────────────────────────────────
    ensure_arabic_fonts_cached()
    font     = resolve_arabic_font(font)
    filename = os.path.basename(input_path)
    base_nm  = os.path.splitext(filename)[0]

    # ── Timeline (dynamic face-mode positioning) ──────────────────────────────
    timeline = _load_timeline(base_nm, filename, project_folder)

    # ── Static face-mode alignment (fallback when no timeline present) ────────
    m_out = re.search(r'output(\d+)', filename)
    m_idx = re.search(r'^(\d{3})_', filename)
    idx   = int(m_out.group(1)) if m_out else (int(m_idx.group(1)) if m_idx else None)
    key   = f'output{str(idx).zfill(3)}' if idx is not None else base_nm

    cur_align    = alignment
    cur_vert_pos = vertical_position
    if face_modes.get(key) == '2' and not timeline:
        cur_align    = 5
        cur_vert_pos = 0

    # ── Load JSON subtitle file ───────────────────────────────────────────────
    try:
        with open(input_path, encoding='utf-8-sig') as fh:
            data = json.load(fh)
        print(f'[arabic] {filename}: {len(data.get("segments", []))} segments')
    except Exception as exc:
        print(f'[arabic] ERROR loading {input_path}: {exc}')
        return

    # ── Write ASS ─────────────────────────────────────────────────────────────
    total_written = 0

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(_ass_header(
            font, base_size, base_color, outline_color, shadow_color,
            bold, italic, underline, strikeout,
            border_style, outline_thickness, shadow_size,
            cur_align, cur_vert_pos,
        ))

        all_segs = data.get('segments', [])
        last_end = 0.0

        # ── Norz: removed - no longer uses AI or important words ──
        # Norz now uses simple static line display below

        # ── Norz persistent decorations (written once for the whole clip) ─────
        if mode == 'norz' and all_segs:
            vs = all_segs[0].get('start', 0.0)
            ve = all_segs[-1].get('end',   vs + 60.0)

            if watermark_text and watermark_text.strip():
                total_written += _write_watermark(
                    f, vs, ve, watermark_text, base_size, base_color,
                    wm_transparency, wm_outline, wm_shadow,
                )
            if speaker_name or speaker_title:
                total_written += _write_speaker_tag(
                    f, vs, ve,
                    speaker_name, speaker_title,
                    base_size, base_color, highlight_color,
                    spk_name_size, spk_title_size,
                )

        # ── Two-line emphasis persistent decorations ─────
        if mode == 'two_line_emphasis' and all_segs:
            vs = all_segs[0].get('start', 0.0)
            ve = all_segs[-1].get('end',   vs + 60.0)

            if watermark_text and watermark_text.strip():
                total_written += _write_watermark(
                    f, vs, ve, watermark_text, base_size, base_color,
                    wm_transparency, wm_outline, wm_shadow,
                )
            if speaker_name or speaker_title:
                total_written += _write_speaker_tag(
                    f, vs, ve,
                    speaker_name, speaker_title,
                    base_size, base_color, highlight_color,
                    spk_name_size, spk_title_size,
                )

        # ── Segment → block → word loop ───────────────────────────────────────
        for seg_idx, segment in enumerate(all_segs):
            raw_words = segment.get('words', [])
            n_words   = len(raw_words)
            i         = 0

            while i < n_words:
                # Build a block of up to words_per_block cleaned word entries
                block = []
                while len(block) < words_per_block and i < n_words:
                    cw = raw_words[i]
                    if 'word' in cw:
                        w_text = clean_word(cw['word'], remove_punctuation)
                        if uppercase:
                            w_text = w_text.upper()
                        entry = {**cw, 'word': w_text}

                        # Absorb an immediately following word with no timing
                        if i + 1 < n_words:
                            nw = raw_words[i + 1]
                            if 'start' not in nw or 'end' not in nw:
                                nw_text = clean_word(
                                    nw.get('word', ''), remove_punctuation
                                )
                                if uppercase:
                                    nw_text = nw_text.upper()
                                entry['word'] += ' ' + nw_text
                                i += 1  # Skip the absorbed word

                        block.append(entry)
                    i += 1
                    
                    # Safety check: ensure we haven't gone past the array
                    if i >= n_words:
                        break

                if not block:
                    continue

                starts = [w.get('start', 0.0) for w in block]
                ends   = [w.get('end',   0.0) for w in block]

                # ── no_highlight: single line for entire block duration ────────
                if mode in ('no_highlight', 'sem_higlight'):
                    t_start = starts[0]
                    t_end   = ends[-1]
                    if t_start - last_end < gap_limit:
                        t_start = last_end
                    if t_end <= t_start:
                        t_end = t_start + _MIN_WORD_DUR * len(block)

                    line = _build_no_highlight(block, base_size, base_color)
                    if timeline:
                        line = _apply_timeline_pos(line, (t_start + t_end) / 2, timeline)

                    f.write(
                        f'Dialogue: 0,{_fmt(t_start)},{_fmt(t_end)},'
                        f'Default,,0,0,0,,{line}\n'
                    )
                    last_end       = t_end
                    total_written += 1
                    continue

                # ── norz: enhanced simple static line with improved timing ─
                if mode == 'norz':
                    # Use full segment timing for better readability
                    t_start = starts[0]
                    t_end   = ends[-1]
                    
                    # Ensure minimum duration for readability (at least 1.5s)
                    min_duration = max(1.5, len(block) * 0.3)  # 0.3s per word minimum
                    actual_duration = t_end - t_start
                    if actual_duration < min_duration:
                        t_end = t_start + min_duration
                    
                    # Smooth gap handling - no abrupt cuts between subtitles
                    if t_start - last_end < gap_limit:
                        t_start = last_end
                    
                    # Build clean Arabic text with proper RTL support
                    raw_words = [wd['word'] for wd in block if wd['word'].strip()]
                    if not raw_words:
                        continue
                    
                    # Join words with spaces
                    joined_line = ' '.join(raw_words)
                    
                    # Apply Arabic letter shaping for connected script
                    processed_line = reshape_arabic(joined_line)
                    
                    # Add Unicode RTL mark to force right-to-left rendering
                    # This ensures libass displays text from right to left
                    line = '\u200F' + processed_line

                    # Apply dynamic positioning if timeline available
                    if timeline:
                        line = _apply_timeline_pos(line, (t_start + t_end) / 2, timeline)

                    f.write(
                        f'Dialogue: 0,{_fmt(t_start)},{_fmt(t_end)},'
                        f'Default,,0,0,0,,{line}\n'
                    )
                    last_end       = t_end
                    total_written += 1
                    continue

                # ── two_line_emphasis: full sentence + emphasis on last N words ─
                if mode == 'two_line_emphasis':
                    # Use full block timing
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
                    
                    # Build two lines with proper split (no duplication)
                    # words_per_block controls segment size, we default words_in_second_line to 2
                    words_in_second_line = 2  # Default: last 2 words in gold
                    line1, line2 = _build_two_line_emphasis(
                        block, base_size, base_color,
                        highlight_size, highlight_color,
                        words_in_second_line
                    )
                    
                    if not line1 and not line2:
                        continue
                    
                    # Combine both lines with \N (newline) separator
                    # This creates a single dialogue event with two visual lines
                    if line1 and line2:
                        combined_line = f'{line1}\\N{line2}'
                    elif line2:
                        combined_line = line2
                    else:
                        continue
                    
                    # Anchor to bottom-center at cur_vert_pos from top, above the watermark
                    pos_tag = f'{{\\an2\\pos({_CX},{cur_vert_pos})}}'
                    combined_line = pos_tag + combined_line

                    # Apply dynamic positioning if timeline available
                    if timeline:
                        combined_line = _apply_timeline_pos(combined_line, (t_start + t_end) / 2, timeline)

                    # Write single dialogue event with both lines
                    f.write(
                        f'Dialogue: 0,{_fmt(t_start)},{_fmt(t_end)},'
                        f'Default,,0,0,0,,{combined_line}\n'
                    )
                    
                    last_end       = t_end
                    total_written += 1
                    continue

                # ── Per-word dialogue lines (highlight / word-by-word) ─────────
                for j in range(len(block)):
                    t_start = starts[j]
                    t_end   = ends[j]

                    # Bridge small gaps — no invisible silence between words
                    if t_start - last_end < gap_limit:
                        t_start = last_end
                    if t_end <= t_start:
                        t_end = t_start + _MIN_WORD_DUR

                    ts       = _fmt(t_start)
                    te       = _fmt(t_end)
                    last_end = t_end

                    if mode == 'highlight':
                        line = _build_highlight(
                            block, j,
                            base_size, base_color,
                            highlight_size, highlight_color,
                        )
                    else:
                        # palavra_por_palavra and any unknown modes
                        line = _build_word_by_word(
                            block[j]['word'], base_size, base_color,
                        )

                    if timeline:
                        line = _apply_timeline_pos(
                            line, (t_start + t_end) / 2, timeline
                        )

                    f.write(
                        f'Dialogue: 0,{ts},{te},Default,,0,0,0,,{line}\n'
                    )
                    total_written += 1

    if total_written == 0:
        print(f'[arabic] WARN: no dialogue lines written for {filename}')
    else:
        print(f'[arabic] {total_written} lines -> {os.path.basename(output_path)}')


def _apply_timeline_pos(line: str, mid_time: float, timeline: list) -> str:
    """
    Prepend a \\pos override tag when the subtitle falls in a mode-2 timeline
    segment (centred face-mode).  Returns the line unchanged for mode-1 segments.
    """
    for seg in timeline:
        if seg['start'] <= mid_time <= seg['end']:
            if seg.get('mode') == '2':
                return f'{{\\an5\\pos(180,320)}}{line}'
            break
    return line

# ═══════════════════════════════════════════════════════════════════════════════
# §10  BATCH ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def adjust_arabic(
        base_color, base_size, highlight_size, highlight_color,
        words_per_block, gap_limit, mode, vertical_position, alignment,
        font, outline_color, shadow_color, bold, italic, underline,
        strikeout, border_style, outline_thickness, shadow_size,
        uppercase=False, project_folder='tmp', **kwargs) -> None:
    """
    Process all JSON subtitle files in *project_folder*/subs through the
    Arabic pipeline and write ASS output to *project_folder*/subs_ass.

    Drop-in replacement for adjust_subtitles.adjust() when lang == 'ar'.
    The calling signature is identical — no changes needed in the caller.
    Extra keyword arguments (remove_punctuation, speaker_name, etc.) are
    forwarded via **kwargs for forward-compatibility with future additions.
    """
    input_dir  = os.path.join(project_folder, 'subs')
    output_dir = os.path.join(project_folder, 'subs_ass')
    os.makedirs(output_dir, exist_ok=True)

    remove_punctuation = kwargs.get('remove_punctuation', True)
    speaker_name       = kwargs.get('speaker_name',   '') or ''
    speaker_title      = kwargs.get('speaker_title',  '') or ''
    watermark_text     = kwargs.get('watermark_text', '') or ''
    wm_transparency    = kwargs.get('wm_transparency', 25)
    wm_outline         = kwargs.get('wm_outline', 0)
    wm_shadow          = kwargs.get('wm_shadow', 1)
    spk_name_size      = kwargs.get('spk_name_size', 0)
    spk_title_size     = kwargs.get('spk_title_size', 0)

    # Load face modes for dynamic subtitle positioning
    face_modes = {}
    modes_file = os.path.join(project_folder, 'face_modes.json')
    if os.path.exists(modes_file):
        try:
            with open(modes_file, encoding='utf-8') as fh:
                face_modes = json.load(fh)
            print('[arabic] Loaded face modes for dynamic positioning.')
        except Exception as exc:
            print(f'[arabic] Could not load face modes: {exc}')

    if not os.path.exists(input_dir):
        raise FileNotFoundError(
            f'[arabic] Subtitle folder not found: {input_dir}\n'
            'Ensure transcription completed successfully before running subtitles.'
        )

    processed = 0
    for filename in sorted(os.listdir(input_dir)):
        if not filename.endswith('.json'):
            continue
        in_path  = os.path.join(input_dir, filename)
        out_name = os.path.splitext(filename)[0] + '.ass'
        out_path = os.path.join(output_dir, out_name)

        generate_arabic_ass_from_file(
            in_path, out_path, project_folder,
            base_color, base_size, highlight_size, highlight_color,
            words_per_block, gap_limit, mode, vertical_position, alignment,
            font, outline_color, shadow_color, bold, italic, underline,
            strikeout, border_style, outline_thickness, shadow_size,
            uppercase, face_modes, remove_punctuation,
            speaker_name, speaker_title, watermark_text,
            wm_transparency, wm_outline, wm_shadow,
            spk_name_size, spk_title_size,
        )
        print(f'[arabic] {filename} -> {out_name}')
        processed += 1

    print(f'[arabic] Complete — {processed} file(s) processed.')

# ═══════════════════════════════════════════════════════════════════════════════
# §11  TRANSLATION PIPELINE HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def build_arabic_translation_prompt(texts: list) -> str:
    """
    Build an Arabic-optimised numbered translation prompt for an AI backend.

    Instructs the model to:
      • Translate meaning — not word-for-word
      • Use simple Modern Standard Arabic (MSA) suitable for spoken subtitles
      • Avoid tashkeel / harakaat (diacritics) — improves visual cleanliness
      • Preserve the exact numbered format for reliable response parsing
      • Use Arabic-form punctuation (،  ؛  ؟) not Western forms
      • Keep each translated line concise (screen space is limited)

    Called by translate_json._build_prompt() when target_lang == 'ar'.
    """
    numbered = '\n'.join(f'{i + 1}. {t}' for i, t in enumerate(texts))
    return (
        'أنت مترجم محترف متخصص في ترجمة الترجمات المكتوبة (السبتايتل) '
        'إلى اللغة العربية.\n\n'
        'قواعد الترجمة:\n'
        '- ترجم المعنى والمضمون، وليس كلمة بكلمة\n'
        '- اجعل النص طبيعياً ومناسباً للمحتوى المسموع\n'
        '- استخدم اللغة العربية الفصحى البسيطة والمفهومة\n'
        '- حافظ على التسلسل المرقم بدقة تامة\n'
        '- لا تضف شرحاً أو اقتباسات — أعد الأسطر المرقمة فقط\n'
        '- تجنب التشكيل والحركات للحفاظ على النظافة البصرية للترجمة\n'
        '- استخدم علامات الترقيم العربية (، ؟ ؛) بدلاً من علامات الترقيم اللاتينية\n'
        '- اجعل كل سطر مترجم مختصراً بما يناسب مساحة الشاشة\n\n'
        f'النصوص المطلوب ترجمتها:\n{numbered}'
    )


def post_process_arabic_translation(text: str) -> str:
    """
    Clean AI-generated Arabic translation text before storing it in JSON.

    Applies the same normalization pipeline used during ASS generation:
      1. NFC normalization   — precomposed glyphs, no combining-form boxes
      2. Diacritics removal  — strip any harakaat the AI added
      3. Tatweel removal     — strip any kashida the AI added
      4. Invisible marks     — strip bidi controls, BOM, soft-hyphen

    Called by translate_json before redistribute_arabic_timing().
    """
    text = _nfc(text)
    text = strip_diacritics(text)
    text = text.replace(_TATWEEL, '')
    text = strip_invisible(text)
    return text.strip()
