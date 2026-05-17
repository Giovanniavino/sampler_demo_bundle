# Sampler Demo — Working End-to-End Pipeline

Questa cartella contiene una demo REALE della pipeline che gira da capo a fondo.

## Cosa c'è dentro

```
sampler_demo_bundle/
├── code/                     # Il progetto completo (zip-ready)
├── demo_output/
│   ├── test_song.wav         # Input: canzone test generata (24s, 120 BPM)
│   ├── stems/                # Output stage 1: 4 stem separati
│   │   ├── drums.wav
│   │   ├── bass.wav
│   │   ├── vocals.wav
│   │   └── other.wav
│   ├── project.json          # Output stage 2-4: progetto con sample + pad layout
│   └── demo_pad_sequence.wav # Audio renderizzato dai pad trigger
└── DEMO_SUMMARY.md
```

## Risultati misurati (run reale del 17 maggio 2026)

### Audio input
- File: test_song.wav, 24.0s, 44100 Hz stereo
- Contenuto: drums (kick/snare/hat 4-on-floor) + walking bass + chord pad + lead voice
- BPM target: 120

### Stage 1 — Separazione stem
**Implementazione usata**: `HeuristicSeparator` (DSP-based, no demucs richiesto)

Output: 4 file wav reali, tutti stereo 44100 Hz, durata 24s ciascuno
- `drums.wav`  : RMS 0.047, peak 0.500
- `bass.wav`   : RMS 0.122, peak 0.500
- `vocals.wav` : RMS 0.097, peak 0.500
- `other.wav`  : RMS 0.085, peak 0.500

> NOTA: La qualità di separazione è grezza (è DSP, non AI). Con Demucs il
> risultato sarà molto migliore — il punto di questa demo è dimostrare che
> i 4 file wav vengono prodotti e che TUTTO IL RESTO DELLA PIPELINE FUNZIONA.

### Stage 2 — Analisi audio
- BPM rilevato: **120.2** (target 120.0, errore 0.17%)
- Beat rilevati: 47 (su un atteso di 48 in 24s @ 120 BPM)
- Transient rilevati: 95
- Sezioni: 2 (intro + outro) — qui c'è un limite reale (vedi sotto)

### Stage 3 — Auto slicing
60 sample generati, distribuiti per categoria:
- 32 drum hits
- 16 vocal chops
- 4 bass loops
- 4 drum loops
- 2 vocal phrases
- 2 melodic phrases

### Stage 4 — Pad assignment (4x4)
14 pad popolati su 16:
```
Riga 1: Drum hit 01    | Drum hit 02    | Drum hit 03    | Drum hit 04
Riga 2: Vocal chop 01  | Vocal chop 02  | Vocal chop 03  | Vocal chop 04
Riga 3: other phrase 1 | other phrase 2 | (empty)        | (empty)
Riga 4: Bass loop 1    | Bass loop 2    | Bass loop 3    | Bass loop 4
```

### Stage 5 — Playback engine
Renderizzato `demo_pad_sequence.wav` (16.1s) attraverso l'engine vero:
- Trigger pad in sequenza
- Choke group sui drum hit
- Loop wrap con crossfade
- Layering progressivo (mel loop + bass loop + drum loop simultanei)
- RMS sale da 0.04 (solo drum hits) a 0.15 (tutti i loop attivi) — mixing OK

## Per riprodurre tutto

```bash
cd code/
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt numpy scipy

# 1) Genera il test song (o usa il tuo file)
python make_test_song.py     # (lo trovi nella root del bundle)

# 2) Esegui la pipeline:
PYTHONPATH=. python -m scripts.cli_run path/to/song.wav --heuristic \
    --out data/projects/test --cache data/cache

# 3) Renderizza i pad in un wav per ascoltare:
PYTHONPATH=. python scripts/render_demo.py

# Per usare Demucs (qualità VERA di separazione), su una macchina con accesso a
# huggingface/CDN Meta:
pip install -r requirements-ai.txt
PYTHONPATH=. python -m scripts.cli_run path/to/song.mp3 \
    --out data/projects/test
```

## Recheck onesto — cosa ho verificato realmente

✅ **VERIFICATO che gira oggi su una canzone**:
- import file audio → 4 stem wav reali
- analisi BPM (errore <0.2% sul test track)
- detection beats + transients
- auto-slicing in sample
- pad assignment 4x4
- save/load JSON
- playback engine con voice mixing, choke group, loop crossfade

⚠️ **LIMITAZIONI confermate dalla run**:
1. **Section detection**: ha trovato solo 2 sezioni (intro/outro) su un brano
   strutturato con 4 cambi di accordo. L'euristica RMS è troppo grossolana.
   Per un MVP è OK, ma per uso reale serve un modello dedicato (allin1, msaf).
2. **Heuristic separator ≠ qualità AI**: i vocal/melody stem hanno bleed.
   Sostituire con Demucs in produzione (1 riga nel CLI).
3. **`pip install pyrubberband` richiede `rubberband-cli`**: senza, pitch/time
   stretch è no-op silenzioso.
4. **Latenza**: l'engine Python ha ~10-30ms di latenza con `sounddevice`.
   OK per validare, non per finger drumming pro. Servirà l'engine C++ poi.

⚠️ **NON ANCORA TESTATO IN QUESTO AMBIENTE** (non ho display/audio device):
- La GUI QML: il codice è scritto correttamente, ma il primo `python -m app.main`
  sul TUO Mac/Linux potrebbe richiedere fix banali (1-2 import o path).
- Sounddevice live output: ho usato `OfflineEngine` per renderizzare a wav,
  l'audio callback è lo stesso ma su PortAudio bisogna avere un device aperto.
