"""
renderer_arabic.py — Arabic Subtitle Renderer for ViralCutter
══════════════════════════════════════════════════════════════

This is the single entry-point for every Arabic-specific rendering concern.
Swapping or fixing Arabic subtitle behaviour means editing this file (and the
implementation it wraps in arabic_handler.py) — renderer_english.py and the
shared pipeline are never touched.

STRATEGY INTERFACE  (identical signature to renderer_english.py)
─────────────────────────────────────────────────────────────────
  generate_ass(input_path, output_path, project_folder, ...) -> None
  adjust(project_folder, ...)                                -> None

ARABIC-ONLY HELPERS  (for shared-pipeline callers)
───────────────────────────────────────────────────
  ensure_fonts_cached()              Copy Lyon Arabic + Windows fallback fonts to
                                     C:\\vcfonts (space-free path for libass).
  build_translation_prompt(texts)    Arabic-optimised AI translation prompt.
  post_process_translation(text)     Clean AI output before saving to JSON.
  redistribute_timing(segment, text) Char-proportional word timing after translation.
  clean_word(word, ...)              Pure normalisation for one token (no reshape).
  prepare_arabic_text(text)          reshape_arabic alias — call this at ASS emit.
  reshape_arabic(text)               arabic_reshaper → bidi visual reorder.
  is_arabic(lang)                    True when lang resolves to 'ar'.
  has_arabic_chars(text)             True when text contains Arabic characters.

WHAT LIVES HERE vs arabic_handler.py
─────────────────────────────────────
  • This file owns the *interface* — it defines the names that the rest of the
    codebase calls and documents the contract for each.
  • arabic_handler.py owns the *implementation* — all the rendering logic,
    text-processing pipelines, font management, and ASS generation details.
  • When a bug needs fixing (disconnected letters, wrong RTL order, box
    glyphs), open arabic_handler.py.  When the calling convention changes,
    update this file.  Neither change ever requires touching renderer_english.py.
"""

try:
    from scripts import arabic_handler as _impl
except ImportError:
    import arabic_handler as _impl  # type: ignore


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
        watermark_text: str = '',
        **kwargs) -> None:
    """
    Generate a single Arabic ASS subtitle file from a JSON word-timing input.

    Delegates to arabic_handler.generate_arabic_ass_from_file(), which handles:
      • Font caching and resolution (Arabic-capable fonts only)
      • Letter reshaping via arabic_reshaper (connected glyph forms)
      • RTL visual ordering via python-bidi
      • ASS header with ScaledBorderAndShadow and Encoding=1
      • All display modes: highlight, no_highlight, word_by_word, norz, two_line_emphasis
      • Watermark and speaker-tag decorations (Zone A / Zone C layout)
      • Dynamic face-mode timeline position overrides
    Extra kwargs (wm_transparency, wm_outline, wm_shadow, spk_name_size,
    spk_title_size) are forwarded verbatim.
    """
    _impl.generate_arabic_ass_from_file(
        input_path, output_path, project_folder,
        base_color, base_size, highlight_size, highlight_color,
        words_per_block, gap_limit, mode, vertical_position, alignment,
        font, outline_color, shadow_color, bold, italic, underline,
        strikeout, border_style, outline_thickness, shadow_size,
        uppercase, face_modes if face_modes is not None else {},
        remove_punctuation, speaker_name, speaker_title, watermark_text,
        **kwargs,
    )


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

    Accepts the same **kwargs as the shared pipeline passes (remove_punctuation,
    speaker_name, speaker_title, watermark_text) and forwards them verbatim.
    """
    _impl.adjust_arabic(
        base_color, base_size, highlight_size, highlight_color,
        words_per_block, gap_limit, mode, vertical_position, alignment,
        font, outline_color, shadow_color, bold, italic, underline,
        strikeout, border_style, outline_thickness, shadow_size,
        uppercase=uppercase, project_folder=project_folder,
        **kwargs,
    )


# ══════════════════════════════════════════════════════════════════════════════
# ARABIC-ONLY HELPERS  (shared pipeline callers import these from here)
# ══════════════════════════════════════════════════════════════════════════════

def ensure_fonts_cached() -> None:
    """
    Copy Lyon Arabic Display OTFs and Windows Arabic fallback TTFs to
    C:\\vcfonts\\ so libass / ffmpeg can locate them without path-space issues.
    Safe to call repeatedly — idempotent.
    """
    _impl.ensure_arabic_fonts_cached()


def build_translation_prompt(texts: list) -> str:
    """
    Return an Arabic-optimised numbered translation prompt for the AI backend.
    Uses Modern Standard Arabic instructions; avoids diacritics; enforces
    Arabic-form punctuation (، ؛ ؟).
    """
    return _impl.build_arabic_translation_prompt(texts)


def post_process_translation(text: str) -> str:
    """
    Clean AI-generated Arabic text before it is written to the subtitle JSON.
    Applies NFC normalisation, strips diacritics, tatweel, and invisible marks.
    """
    return _impl.post_process_arabic_translation(text)


def redistribute_timing(segment: dict, translated_text: str) -> None:
    """
    Redistribute per-word timestamps inside *segment* after Arabic translation.
    Allocates time proportionally by character count; enforces a minimum floor
    so every word stays on screen long enough to read.
    """
    _impl.redistribute_arabic_timing(segment, translated_text)


def clean_word(word: str, remove_punctuation: bool = True) -> str:
    """
    Full normalisation + reshaping pipeline for one Arabic word token.
    Steps: NFC → control strips → invisible mark removal → tatweel removal →
    diacritics removal → optional punctuation removal → whitelist filter →
    arabic_reshaper (connected forms) → bidi reorder.
    English tokens pass through unchanged.
    """
    return _impl.clean_word(word, remove_punctuation)


def reshape_arabic(text: str) -> str:
    """
    Connect Arabic letter forms and apply RTL visual ordering.
    Uses arabic_reshaper for glyph joining and python-bidi for UAX #9 reorder.
    Non-Arabic strings are returned unchanged.
    """
    return _impl.reshape_arabic(text)


def prepare_arabic_text(text: str) -> str:
    """Alias for reshape_arabic — call this just before writing Arabic text to ASS."""
    return _impl.prepare_arabic_text(text)


def is_arabic(lang: str) -> bool:
    """Return True when *lang* resolves to the Arabic language code ('ar')."""
    return _impl.is_arabic(lang)


def has_arabic_chars(text: str) -> bool:
    """Return True if *text* contains at least one core Arabic-block character."""
    return _impl.has_arabic_chars(text)
