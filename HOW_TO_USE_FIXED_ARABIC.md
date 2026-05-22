# How to Use the Fixed Arabic Subtitle Rendering

## Quick Start

When processing Arabic subtitles, simply ensure `lang='ar'` is set in your configuration. The system will automatically use the NEW fixed logic.

### Example Usage

```python
from scripts.adjust_subtitles import adjust

# For Arabic subtitles - uses NEW fixed logic automatically
adjust(
    base_color='&H00FFFFFF',
    base_size=24,
    highlight_size=32,
    highlight_color='&H00FFD700',  # Gold
    words_per_block=4,
    gap_limit=0.3,
    mode='highlight',  # or 'norz', 'no_highlight', 'word_by_word'
    vertical_position=500,
    alignment=2,
    font='Lyon Arabic Display',
    outline_color='&H00000000',
    shadow_color='&H80000000',
    bold='0',
    italic='0',
    underline='0',
    strikeout='0',
    border_style=1,
    outline_thickness=2.0,
    shadow_size=3.0,
    uppercase=False,
    project_folder='VIRALS/my_arabic_video',
    lang='ar',  # ← THIS IS THE KEY: Set to 'ar' for Arabic
    remove_punctuation=True,
    speaker_name='المتحدث',
    speaker_title='عنوان المتحدث',
    watermark_text='علامتي المائية',
)
```

## What Happens When `lang='ar'`

1. **Entry Point** (`adjust_subtitles.py`):
   ```python
   renderer = _ar if _is_arabic(lang) else _en
   # Since lang='ar', routes to renderer_arabic
   ```

2. **Delegation** (`renderer_arabic.py`):
   ```python
   _impl.generate_arabic_ass_from_file(...)
   # Delegates to arabic_handler.py
   ```

3. **Processing** (`arabic_handler.py`):
   - Joins all words into complete lines FIRST
   - Applies `arabic_reshaper` to connect letters
   - Applies `python-bidi` for RTL direction
   - Reverses index mapping for correct karaoke flow
   - Applies ASS styling to visual words

## Supported Modes

All four display modes work correctly with the fixes:

### 1. Highlight Mode
- All words shown simultaneously
- Currently spoken word highlighted in gold
- Karaoke flows RIGHT → LEFT ✓

### 2. Norz Mode
- Centered motivational layout
- Large highlighted word with shadow
- Karaoke flows RIGHT → LEFT ✓

### 3. No Highlight Mode
- Uniform style for all words
- Stable text display
- Correct RTL direction ✓

### 4. Word-by-Word Mode
- One word at a time
- Each word properly shaped and directed ✓

## Verification

To verify the fixes are working, check the generated `.ass` files:

1. **Letters should be connected** (not isolated glyphs)
2. **First word should appear on the RIGHT** side of the line
3. **Highlighting should move from RIGHT to LEFT** as words are spoken

You can also run the verification script:
```bash
python verify_new_arabic_logic.py
```

## Important Notes

✅ **English subtitles**: Use `lang='en'` - completely unaffected by Arabic fixes

✅ **Font selection**: Use Arabic-capable fonts like:
- `'Lyon Arabic Display'` (bundled)
- `'Arial'` (fallback)
- `'Tahoma'`
- `'Noto Sans Arabic'`

✅ **Text encoding**: JSON input files must be UTF-8 or UTF-8-SIG encoded

✅ **No manual intervention needed**: The fixes are automatic when `lang='ar'`

## Troubleshooting

If you see issues:

1. **Check language setting**: Ensure `lang='ar'` is set
2. **Verify dependencies**: 
   ```bash
   pip install arabic-reshaper python-bidi
   ```
3. **Check font availability**: Ensure Arabic fonts are installed
4. **Run verification**: 
   ```bash
   python verify_new_arabic_logic.py
   ```

## Summary

Just set `lang='ar'` and the NEW fixed logic handles everything automatically:
- ✓ Connected letters
- ✓ Correct RTL direction
- ✓ Right-to-left karaoke flow

No other changes needed!
