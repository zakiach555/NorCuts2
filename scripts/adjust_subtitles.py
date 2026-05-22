"""
adjust_subtitles.py — Subtitle Renderer Dispatcher for ViralCutter
════════════════════════════════════════════════════════════════════

This module is the single call-site for subtitle generation in the shared
pipeline.  It inspects the *lang* parameter and forwards the call to the
appropriate renderer — no rendering logic lives here.

  lang == 'ar'  →  renderer_arabic.generate_ass() / renderer_arabic.adjust()
  everything else  →  renderer_english.generate_ass() / renderer_english.adjust()

Adding a new language renderer:
  1. Create scripts/renderer_<lang>.py with generate_ass() and adjust().
  2. Add an elif branch below.
  3. Nothing else changes in the pipeline.
"""

try:
    from scripts import renderer_arabic  as _ar
    from scripts import renderer_english as _en
except ImportError:
    import renderer_arabic  as _ar   # type: ignore
    import renderer_english as _en   # type: ignore


def _is_arabic(lang: str) -> bool:
    return bool(lang) and lang.split('-')[0].lower() == 'ar'


# ── Public helpers kept for any callers that still use them directly ──────────

def format_time_ass(time_seconds: float) -> str:
    """Format *time_seconds* as an ASS timestamp  H:MM:SS.cs."""
    h  = int(time_seconds // 3600)
    m  = int((time_seconds % 3600) // 60)
    s  = int(time_seconds % 60)
    cs = int((time_seconds % 1) * 100)
    return f'{h:01}:{m:02}:{s:02}.{cs:02}'


# ══════════════════════════════════════════════════════════════════════════════
# DISPATCHER
# ══════════════════════════════════════════════════════════════════════════════

def generate_ass_from_file(
        input_path, output_path, project_folder,
        base_color, base_size, highlight_size, highlight_color,
        words_per_block, gap_limit, mode, vertical_position, alignment,
        font, outline_color, shadow_color, bold, italic, underline,
        strikeout, border_style, outline_thickness, shadow_size, uppercase,
        face_modes=None, remove_punctuation=True, lang='en',
        speaker_name='', speaker_title='', watermark_text='', **kwargs):
    """
    Generate a single ASS subtitle file from a JSON word-timing input.

    Routes to renderer_arabic or renderer_english based on *lang*.
    Extra kwargs (wm_transparency, wm_outline, wm_shadow, spk_name_size,
    spk_title_size) are forwarded to the Arabic renderer verbatim.
    """
    if face_modes is None:
        face_modes = {}

    renderer = _ar if _is_arabic(lang) else _en

    renderer.generate_ass(
        input_path, output_path, project_folder,
        base_color, base_size, highlight_size, highlight_color,
        words_per_block, gap_limit, mode, vertical_position, alignment,
        font, outline_color, shadow_color, bold, italic, underline,
        strikeout, border_style, outline_thickness, shadow_size,
        uppercase, face_modes, remove_punctuation,
        speaker_name, speaker_title, watermark_text,
        **kwargs,
    )


def adjust(
        base_color, base_size, highlight_size, highlight_color,
        words_per_block, gap_limit, mode, vertical_position, alignment,
        font, outline_color, shadow_color, bold, italic, underline,
        strikeout, border_style, outline_thickness, shadow_size,
        uppercase=False, project_folder='tmp', lang='en', **kwargs):
    """
    Batch-process every JSON subtitle file in the project and write ASS output.

    Routes to renderer_arabic.adjust() or renderer_english.adjust() based on
    *lang*.  Both renderers expose the same signature and honour the same
    **kwargs (remove_punctuation, speaker_name, speaker_title, watermark_text).
    """
    renderer = _ar if _is_arabic(lang) else _en

    renderer.adjust(
        base_color, base_size, highlight_size, highlight_color,
        words_per_block, gap_limit, mode, vertical_position, alignment,
        font, outline_color, shadow_color, bold, italic, underline,
        strikeout, border_style, outline_thickness, shadow_size,
        uppercase=uppercase, project_folder=project_folder,
        **kwargs,
    )
