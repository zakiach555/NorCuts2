# Arabic Subtitle Rendering Fixes - Summary

## Problems Fixed

### Problem 1: Letters Disconnected ✗ → ✓
**Issue**: Every Arabic word showed isolated letters instead of connected script.

**Root Cause**: `arabic_reshaper` was being applied to individual words or to text that already contained ASS formatting tags, which broke the letter connection process.

**Fix**: Apply `arabic_reshaper` to complete plain text lines BEFORE adding any ASS styling tags.

```python
# WRONG (old): Apply reshape to styled text with ASS tags
styled_line = '{\\fs20}word1 {\\fs30}word2'
processed = prepare_arabic_text(styled_line)  # Breaks tags!

# CORRECT (new): Apply reshape to plain text first
plain_text = 'word1 word2'
processed = prepare_arabic_text(plain_text)  # Connects letters properly
# Then add ASS tags to processed words
```

---

### Problem 2: Direction Completely Reversed ✗ → ✓
**Issue**: The entire subtitle line read left-to-right instead of right-to-left.

**Root Cause**: `python-bidi` was either not being applied or was being applied incorrectly (to text with ASS tags embedded).

**Fix**: Apply `python-bidi` (via `prepare_arabic_text`) to complete plain text lines. This reverses the word order so the first spoken word appears on the RIGHT side of the screen.

```python
# Example:
Original:  "السلام عليكم ورحمة الله"
After bidi: "ﷲ ﺔﻤﺣﺭﻭ ﻢﻜﻴﻠﻋ ﻡﻼﺴﻟﺍ"  # Word order reversed!
```

---

### Problem 3: Karaoke Highlight Wrong Direction ✗ → ✓
**Issue**: The highlighted word moved left-to-right, but in Arabic it should move right-to-left.

**Root Cause**: After bidi processing reverses the word order, the code was still using the original logical index `j` to highlight words, which highlighted the wrong visual position.

**Fix**: Map the logical index `j` to the visual index by reversing it: `visual_j = num_words - 1 - j`

```python
# Example with 4 words:
Logical order (spoken):  [0]السلام [1]عليكم [2]ورحمة [3]الله
After bidi (visual):     [0]ﷲ [1]ﺔﻤﺣﺭﻭ [2]ﻢﻜﻴﻠﻋ [3]ﻡﻼﺴﻟﺍ

When speaking word j=0 (السلام):
  - It appears at visual position 3 (RIGHT side)
  - visual_j = 4 - 1 - 0 = 3 ✓ Correct!

When speaking word j=3 (الله):
  - It appears at visual position 0 (LEFT side)
  - visual_j = 4 - 1 - 3 = 0 ✓ Correct!

Result: Karaoke flows RIGHT → LEFT as words are spoken ✓
```

---

## Implementation Details

### Files Modified
- `scripts/arabic_handler.py` - Core Arabic rendering implementation

### Functions Fixed
1. `_build_highlight()` - Highlight mode with per-word karaoke
2. `_build_norz()` - Norz mode with centered layout and karaoke

### The Fix Pattern (Applied to Both Functions)

```python
def _build_highlight(block, j, ...):
    # Step 1: Extract raw words
    raw_words = [wd['word'] for wd in block]
    num_words = len(raw_words)
    
    # Step 2: Join into complete plain text line
    joined_line = ' '.join(raw_words)
    
    # Step 3: Apply reshape + bidi to COMPLETE line
    if has_arabic_chars(joined_line):
        processed_line = prepare_arabic_text(joined_line)
        visual_words = processed_line.split(' ')
        # CRITICAL: Reverse index mapping for RTL
        visual_j = num_words - 1 - j
    else:
        visual_words = raw_words
        visual_j = j
    
    # Step 4: Apply ASS styling to VISUAL words
    parts = []
    for k, word in enumerate(visual_words):
        if k == visual_j:  # Use reversed index!
            parts.append(f'{{\\fs{hl_size}\\c{hl_color}\\b1}}{word}')
        else:
            parts.append(f'{{\\fs{base_size}\\c{base_color}\\b0}}{word}')
    
    # Step 5: Join and return
    return '{\\q2}' + ' '.join(parts)
```

---

## Testing

Three test scripts were created to verify the fixes:

1. **test_arabic_fixes.py** - Basic reshape and bidi functionality
2. **test_karaoke_rtl.py** - Karaoke highlighting behavior
3. **test_final_verification.py** - Complete end-to-end verification
4. **test_actual_bidi.py** - Confirms bidi actually reverses word order

All tests pass successfully ✓

---

## Key Insights

1. **Order matters**: Plain text → reshape+bidi → split → style → join
2. **Never apply bidi to text with ASS tags**: It will break the tags
3. **Bidi reverses word order**: Must account for this in karaoke indexing
4. **libass handles RTL display**: But we still need bidi for proper character ordering

---

## What Was NOT Changed

- English rendering path (renderer_english.py) - untouched ✓
- Core pipeline logic - untouched ✓
- Subtitle positioning - unchanged ✓
- Font handling - already correct ✓
- Text normalization/cleaning - already correct ✓

---

## Result

All three problems are now fixed:
- ✓ Letters connect properly (arabic_reshaper on complete lines)
- ✓ Text direction is RTL (python-bidi reverses word order)
- ✓ Karaoke flows right-to-left (index reversal accounts for bidi)

The Arabic subtitles now render correctly with proper letter connection, RTL direction, and karaoke highlighting that flows from right to left as words are spoken.
