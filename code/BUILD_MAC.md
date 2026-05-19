# SamplerDemo — Build per macOS

## Prerequisiti

- **macOS 12 (Monterey) o superiore**
- **Python 3.11 o 3.12** — installa con [Homebrew](https://brew.sh):
  ```bash
  brew install python@3.11
  ```
- **Homebrew** (per le librerie di sistema):
  ```bash
  /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
  ```
- **Librerie audio di sistema** (necessarie per sounddevice/rtmidi):
  ```bash
  brew install portaudio rtmidi libsndfile
  ```

---

## Build base (senza AI/Demucs)

```bash
cd sampler_demo_bundle/code
chmod +x build_mac.sh create_dmg.sh
./build_mac.sh
```

L'app viene creata in: `dist/SamplerDemo.app`

Per aprirla subito:
```bash
open dist/SamplerDemo.app
```

---

## Build con AI (Demucs / stem separation)

```bash
./build_mac.sh --with-ai
```

> ⚠️ Richiede ~3 GB di spazio aggiuntivo e impiega più tempo.

---

## Creare il DMG distribuibile

```bash
./build_mac.sh --dmg
# oppure solo il DMG (se hai già buildato):
./create_dmg.sh
```

Il file `dist/SamplerDemo.dmg` è quello da condividere.
L'utente lo apre, trascina l'app in `/Applications` e il gioco è fatto.

---

## Build + firma + DMG (tutto insieme)

Se hai un **Apple Developer Account** (necessario per distribuire fuori dall'App Store):

1. Imposta la tua identità in `build_mac.sh`:
   ```bash
   SIGN_IDENTITY="Developer ID Application: Il Tuo Nome (TEAMID)"
   ```
2. Lancia:
   ```bash
   ./build_mac.sh --sign --dmg
   ```

---

## Struttura file generati

```
code/
├── build_mac.sh          ← script di build principale
├── create_dmg.sh         ← crea il .dmg
├── sampler_mac.spec      ← configurazione PyInstaller
├── entitlements.plist    ← permessi macOS (microfono, rete, file)
├── resources/
│   ├── AppIcon.icns      ← icona app (formato Mac)
│   └── app_icon.png      ← icona originale PNG
└── dist/
    ├── SamplerDemo.app   ← l'app (dopo il build)
    └── SamplerDemo.dmg   ← installer (dopo --dmg)
```

---

## Problemi comuni

| Problema | Soluzione |
|---|---|
| `portaudio not found` | `brew install portaudio` |
| `rtmidi build error` | `brew install rtmidi` |
| `App danneggiata` al primo avvio | `xattr -rd com.apple.quarantine dist/SamplerDemo.app` |
| QML non caricato | Verifica che `Main.qml` sia nel bundle: `open dist/SamplerDemo.app/Contents/Resources/app/ui/qml/` |
| Nessun audio | Vai in *Impostazioni di Sistema → Privacy → Microfono* e abilita SamplerDemo |
