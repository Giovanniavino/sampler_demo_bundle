# v3 Update — Installation Guide

This bundle contains all the file changes for the v3 improvements.

## What's new in v3

**Bug fixes:**
- Press-and-hold-loop double-trigger bug — sample no longer plays twice
- Noise reduction was killing 80%+ of the audio in Quality mode — now conservative
- `auto_normalize_stems` toggle didn't actually do anything — now works
- Quality mode no longer forces NR aggressiveness behind your back
- Pad mode cycle limited to OS ↔ LOOP (Hold/Gate still selectable programmatically)

**New features:**
- **Real section detection**: tries `allin1` first, falls back to a much-improved
  SSM-based detector. Vocal samples now named like "Verse 1", "Chorus 1 pt1",
  "Chorus 1 pt2", "Bridge 1" — full sections, not random cuts.
- **Drum 16th-note quantize**: drum hits snap to the nearest 16th-note grid
  if within 30ms tolerance, otherwise keep their groove offset.
- **NR user-controllable**: three levels (Off / Light / Strong) for both
  pre-separation and per-stem NR, with descriptions in the UI.
- **Inline descriptions** on every setting so they're not cryptic anymore.
- **Pad Layout tab** now has a header explaining what it does.

---

## File replacements

Copy each file to the destination listed below. Folders that don't exist
need to be created (`app/audio/analysis` and `app/audio/dsp` should already exist).

| File from bundle | Destination in your project |
|---|---|
| `section_detector.py` | `app/audio/analysis/section_detector.py`  **(NEW)** |
| `analyzer.py` | `app/audio/analysis/analyzer.py` (replace) |
| `auto_slicer.py` | `app/audio/slicing/auto_slicer.py` (replace) |
| `noise_reduction.py` | `app/audio/dsp/noise_reduction.py` (replace) |
| `settings.py` | `app/core/settings.py` (replace) |
| `pipeline.py` | `app/services/pipeline.py` (replace) |
| `sampler_controller.py` | `app/ui/controllers/sampler_controller.py` (replace) |
| `Main.qml` | `app/ui/qml/Main.qml` (replace) |
| `test_v3_fixes.py` | `tests/unit/test_v3_fixes.py` **(NEW)** |

## Optional install: allin1 (for best section detection)

```powershell
pip install allin1
```

If it installs cleanly, the detector will use it automatically (you'll see
"Using allin1 for section detection" in the logs). If madmom fails to compile
(common on Windows + Python 3.12), don't worry — the SSM fallback works fine.

## Reset settings recommended

Old `data/settings.json` doesn't have the new `nr_level_pre` / `nr_level_post`
fields. Either:

1. Delete `data/settings.json` and re-pick Fast/Quality on launch, or
2. Open it manually and add inside the `playback` block:
   ```json
   "nr_level_pre": "light",
   "nr_level_post": "off",
   "press_hold_loop": false
   ```

## How to verify it's working

After replacement, run a track through the pipeline. You should see in the log:
- `Using SSM-based section detector` (or `allin1` if installed)
- `Pipeline complete: 4 stems, N samples, M pads filled`
- Vocal samples named like `Verse 1`, `Chorus 1 pt1`, etc. instead of `Vocal phrase 1`
- No more `_nr_pre_...` files in `/tmp` — they go in `data/cache/<source_id>/`

Run the tests:
```powershell
python -m pytest tests/ -v
# Should be 17 passed
```

## What I did NOT change

- The Demucs separator itself (you already have the cleaner version)
- The QML first-launch dialog (works as before)
- The sample editor (Ctrl+click on a pad — still works)
- The press-hold-loop is now OFF by default (was causing your double-trigger).
  Re-enable in Settings → Playback if you want it.
