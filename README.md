# v4 — Key detection + editor strip + waveform

## File da copiare

| File | Destinazione |
|---|---|
| `key_detector.py` | `app/audio/analysis/key_detector.py` **(NEW)** |
| `waveform_peaks.py` | `app/audio/dsp/waveform_peaks.py` **(NEW)** |
| `analyzer.py` | `app/audio/analysis/analyzer.py` (replace) |
| `sampler_controller.py` | `app/ui/controllers/sampler_controller.py` (replace) |
| `Main.qml` | `app/ui/qml/Main.qml` (replace) |

## Cosa c'è ora

- Layout 800×480 (5" orizzontale)
- Top: barra compatta + striscia editor con waveform sempre visibile
- Bottom: griglia pad
- Key del brano nella top bar (es. "C minor")
- Tap su un pad → editor mostra il suo sample
- Marker S (verde) e E (arancione) trascinabili → cambia start/end live
- Modifiche non-distruttive (solo parametri del Sample, niente file riscritti)
- Settings overlay temporaneamente minimale — verrà ricostruito al prossimo step

## Cosa manca (prossimo step)

Controlli editor: gain, fade in/out, transpose, time stretch, reverse, reset, play preview, zoom waveform.
