# Arabic Subtitle Module — Architecture & Usage Guide

## Overview

The `arabic_handler.py` module is the **single source of truth** for all Arabic subtitle functionality in ViralCutter/NorCuts. This module ensures complete isolation of Arabic-specific code from the rest of the codebase.

## Key Principles

### 1. Complete Isolation
- **All** Arabic-specific logic lives in `scripts/arabic_handler.py`
- **No** Arabic code is scattered across other files
- Other modules **delegate** to this module when `lang == 'ar'`
- Non-Arabic languages are **completely unaffected** by this module

### 2. Clean Delegation Pattern
Other modules check if the language is Arabic and delegate all processing:

```python
# Example from adjust_subtitles.py
if _arabic is not None and lang == 'ar':
    _arabic.adjust_arabic(...)  # Delegate everything
    return
```

### 3. Centralized Font Management
All font caching, selection, and fallback logic is centralized in one place:
- `ensure_arabic_fonts_cached()` - Copies fonts to C:\vcfonts
- `resolve_arabic_font()` - Selects best Arabic-capable font

## Module Structure

The module is organized into 11 logical sections:

### §1 Constants
- Unicode patterns for Arabic characters
- Diacritics removal regex
- Invisible character patterns
- Punctuation normalization
- Timing constants

### §2 Language Gate
Functions to detect Arabic content:
- `is_arabic(lang)` - Check if language code is Arabic
- `has_arabic_chars(text)` - Detect Arabic characters in text

### §3 Font Management
Complete font handling system:
- `ensure_arabic_fonts_cached()` - Cache fonts to C:\vcfonts
- `resolve_arabic_font(preferred)` - Select best Arabic font
- Automatic fallback chain: Lyon Arabic Display → Arial → System fonts

### §4 Text Processing
Comprehensive text normalization pipeline:
- `_nfc(text)` - Unicode NFC normalization
- `strip_invisible(text)` - Remove invisible Unicode marks
- `strip_diacritics(text)` - Remove Arabic tashkeel/harakaat
- `normalise_punctuation(text)` - Convert to Arabic punctuation forms
- `clean_word(word, remove_punctuation)` - Full normalization pipeline

### §5 Timing Utilities
Timing adjustment functions:
- `_fmt(t)` - Format seconds as ASS timestamp
- `redistribute_arabic_timing(segment, translated_text)` - Proportional timing allocation

### §6 ASS Format Utilities
ASS file structure generation:
- `_ass_header(...)` - Build complete ASS header with proper encoding

### §7 Line Builders
One builder per display mode:
- `_build_highlight(block, j, ...)` - Highlight mode (current word emphasized)
- `_build_no_highlight(block, ...)` - Uniform style for entire block
- `_build_word_by_word(word, ...)` - Single word per line
- `_build_norz(block, j, ...)` - Norz motivational layout with fade effects

### §8 Decorations
Zone-based layout elements:
- `_write_watermark(f, vs, ve, text, ...)` - Zone C: Persistent bottom watermark
- `_write_speaker_tag(f, vs, ve, name, title, ...)` - Zone A: Top-left speaker info

### §9 Core ASS Generation
Main subtitle file generation:
- `generate_arabic_ass_from_file(...)` - Convert JSON to ASS with full Arabic support
- Timeline integration for dynamic face-mode positioning
- Gap bridging and overlap prevention

### §10 Batch Entry Point
Process multiple files:
- `adjust_arabic(...)` - Process all JSON files in project folder

### §11 Translation Helpers
AI translation optimization:
- `build_arabic_translation_prompt(texts)` - Arabic-optimized prompt
- `post_process_arabic_translation(text)` - Clean AI output (NFC, diacritics, etc.)

## RTL Text Direction

### How RTL Works in libass

libass implements the Unicode Bidirectional Algorithm (UAX #9). Arabic characters are "strong RTL," so the algorithm automatically renders them right-to-left on screen.

**Important:** Words are written in spoken/logical order. The bidi algorithm handles visual rendering:

```
Written order:   word0  word1  word2
On screen:       [word2] [word1] [word0] ← Rightmost is read first in Arabic
```

**Never manually reverse word order** — this creates double-reversal and produces incorrect LTR output.

## Font System

### Font Selection Rules

1. **Blank or Montserrat** → Arial (Montserrat has zero Arabic glyphs)
2. **Contains "lyon"** → Lyon Arabic Display (premium bundled font)
3. **Anything else** → Use as-is (caller's explicit choice)

### Fallback Chain

libass automatically tries fallback fonts if the primary font lacks glyphs:
1. Lyon Arabic Display (primary)
2. Arial Unicode MS (full Unicode coverage)
3. Noto Sans Arabic (Google's comprehensive Arabic font)
4. Arial (Windows system font)
5. Tahoma (Windows system font)

### Font Caching

Fonts are copied to `C:\vcfonts` (no spaces required by libass):
- Bundled fonts from `arabic font/` folder
- Windows system fonts with Arabic coverage
- Always fresh copy for bundled fonts (picks up updates)
- One-time copy for system fonts (performance optimization)

## Text Normalization Pipeline

When processing Arabic text, the following steps are applied in order:

1. **NFC Normalization** - Converts decomposed sequences to precomposed forms
   - Example: alef + combining hamza → alef-with-hamza (U+0623)
   - Prevents □ rectangles from missing combining glyph variants

2. **Control Character Removal** - ASCII 0x00–0x1F, 0x7F–0x9F

3. **Invisible Mark Removal** - U+200B–U+200F, U+202A–U+202E, BOM, soft-hyphen
   - These have no glyphs in display fonts and render as □ rectangles

4. **Tatweel Removal** - U+0640 kashida (purely decorative stretcher)

5. **Diacritics Removal** - Harakaat, shadda, sukun, Quranic marks
   - Improves visual cleanliness for subtitles

6. **Punctuation Removal** - ASCII + Arabic forms (when requested)

7. **Whitelist Filtering** - Keep only valid Arabic/Latin characters
   - Drops private-use area, surrogates, unknown Unicode planes

## Integration Points

### adjust_subtitles.py
Delegates to arabic_handler when lang == 'ar':
```python
if _arabic is not None and lang and lang.split('-')[0].lower() == 'ar':
    _arabic.generate_arabic_ass_from_file(...)
    return
```

### translate_json.py
Uses arabic_handler for translation optimization:
```python
if _arabic is not None and target_lang == 'ar':
    return _arabic.build_arabic_translation_prompt(texts)

# Post-processing after translation
if use_arabic_pipeline:
    text = _arabic.post_process_arabic_translation(text)
    _arabic.redistribute_arabic_timing(segment, text)
```

### burn_subtitles.py
Delegates font caching to arabic_handler:
```python
if _arabic is not None:
    _arabic.ensure_arabic_fonts_cached()
```

## Common Issues & Solutions

### Issue: Rectangular Boxes (□) in Arabic Text

**Cause:** Missing glyphs in the selected font or invisible Unicode characters.

**Solution:** 
- Run `install_fonts.bat` to install Lyon Arabic Display fonts
- The module automatically applies NFC normalization
- Invisible characters are stripped during cleaning
- Font fallback chain ensures glyph availability

### Issue: Arabic Text Appears Left-to-Right

**Cause:** Manual word order reversal (double-reversal bug).

**Solution:** 
- Never reverse word order manually
- Let libass bidi algorithm handle RTL rendering
- Words should be in spoken/logical order

### Issue: Speaker Labels Not Appearing

**Cause:** Empty strings or positioning issues.

**Solution:**
- Module validates speaker_name and speaker_title with `.strip()`
- Positioning optimized at (15, 50) for top-left corner
- Debug logging shows what's being rendered

### Issue: Diacritics Causing Irregular Spacing

**Cause:** AI translators sometimes add harakaat marks.

**Solution:**
- `post_process_arabic_translation()` strips all diacritics
- `strip_diacritics()` removes tashkeel consistently
- Results in cleaner, more readable subtitles

## Maintenance Guidelines

### Adding New Arabic Features

1. **Add to arabic_handler.py ONLY**
2. Create a new function in the appropriate section
3. Update the delegation call in the calling module
4. Document the feature in this README

### NEVER Do This

- ❌ Don't add Arabic-specific logic to other modules
- ❌ Don't duplicate font management code
- ❌ Don't hardcode Arabic Unicode ranges outside arabic_handler
- ❌ Don't implement separate RTL handling in other files

### DO This

- ✅ Delegate all Arabic processing to arabic_handler
- ✅ Add new Arabic features to the appropriate section
- ✅ Update documentation when adding features
- ✅ Use the existing text normalization pipeline

## Testing

To verify Arabic subtitle functionality:

1. Run `install_fonts.bat` to ensure fonts are cached
2. Select Arabic ('ar') as the subtitle language
3. Process a video with Arabic audio/content
4. Check output in `VIRALS/<project>/subs_ass/`
5. Verify:
   - No rectangular boxes (□)
   - Proper RTL text direction
   - Speaker labels appear (if configured)
   - Watermark appears (if configured)
   - Smooth fade animations in Norz mode

## Performance Considerations

- Font caching is idempotent (safe to call every run)
- System fonts copied once, bundled fonts copied each run
- Text normalization is fast (regex-based operations)
- No performance impact on non-Arabic languages (module not loaded)

## Future Enhancements

Potential areas for improvement:
- Support for additional Arabic fonts
- Advanced ligature handling
- Dialect-specific translation prompts
- Quranic text support (preserve diacritics option)
- Bi-directional text mixing (Arabic + English)

## References

- Unicode Bidirectional Algorithm (UAX #9): https://unicode.org/reports/tr9/
- ASS Format Specification: http://www.tcax.org/docs/ass-specs.htm
- Arabic Unicode Block: U+0600–U+06FF
- libass Documentation: https://github.com/libass/libass

---

**Last Updated:** May 2026  
**Module Version:** 1.0  
**Maintainer:** NorCuts Development Team
