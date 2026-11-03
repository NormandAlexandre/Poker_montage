# 🎬 AI Video Auto-Cut Pipeline (Poker & Talk Video)

Pipeline d'automatisation de pré-montage vidéo par IA : détection fine de la voix humaine (Silero VAD + Faster-Whisper), suppression déterministe des silences et micro-pauses sans coupure abrupte, et génération d'une **timeline non-destructive** (`.fcpxml` / `.edl`) directement importable dans **DaVinci Resolve**, **Kdenlive** ou **Premiere Pro**.

---

## 🚀 Fonctionnalités Clés

- **Zéro perte de qualité (Remuxing direct)** : Convertit les flux MKV d'OBS en MP4 sans aucun ré-encodage vidéo lourd.
- **Détection vocale par réseau de neurones (Silero VAD)** : Isole la voix humaine et ignore les bruits parasites (clics de souris, bruit de jetons poker, alertes de table).
- **Précision au centième de seconde** : Transcription mot à mot horodatée (`word_timestamps`) évitant de couper les premières ou dernières syllabes.
- **Approche 100 % Non-Destructive** : Ne génère pas un fichier vidéo figé, mais une timeline éditable avec tous les cuts posés. Vous pouvez étirer ou réajuster n'importe quel clip à la souris.
- **Marqueurs automatiques d'inspection** : Place des marqueurs sur les pauses supérieures à 6 secondes pour vérification rapide.
- **Auto-détection matérielle** : Utilise le GPU NVIDIA (CUDA) si disponible (`large-v3`), ou bascule automatiquement sur les threads CPU (`small` quantifié en `int8`).
- **100 % Local & Gratuit** : Fonctionne sans aucune dépendance API payante obligatoire.

---

## 📋 Prérequis Système

1. **Python 3.10 ou supérieur** : [python.org](https://www.python.org/)
2. **FFmpeg & FFprobe** : Doivent être installés et accessibles dans le `PATH` système.
   - *Windows* : `winget install Gyan.FFmpeg` ou via [gyan.dev](https://www.gyan.dev/ffmpeg/builds/)
   - *Linux (Ubuntu/Debian)* : `sudo apt install ffmpeg`
   - *macOS* : `brew install ffmpeg`
3. *(Optionnel)* Carte graphique NVIDIA avec support CUDA pour accélérer la transcription.

---

## 🛠️ Installation sur un nouveau PC

```bash
# 1. Cloner le dépôt
git clone <URL_DU_REPO>
cd IA_Montage

# 2. Créer l'environnement virtuel Python
python -m venv .venv

# 3. Activer l'environnement virtuel
# Sur Windows (PowerShell) :
.venv\Scripts\Activate.ps1
# Sur Windows (CMD) :
.venv\Scripts\activate.bat
# Sur Linux / macOS :
source .venv/bin/activate

# 4. Installer les dépendances
pip install -r requirements.txt
```

---

## ⚡ Utilisation Rapide (En une seule commande)

Placez votre vidéo brute (`.mkv` ou `.mp4`) dans le dossier du projet ou spécifiez son chemin :

```bash
# Détection automatique de la vidéo dans le dossier :
python run_pipeline.py

# Ou en spécifiant explicitement le fichier :
python run_pipeline.py --input "chemin/vers/ma_session.mkv"
```

### Options utiles du pipeline :

| Option | Description | Valeur par défaut |
| :--- | :--- | :--- |
| `--input, -i` | Fichier vidéo source | Auto-détecté |
| `--gap-split` | Seuil de silence pour scinder en deux clips (en secondes) | `0.70` |
| `--pad` | Marge de sécurité audio avant et après chaque mot parlé | `0.15` (150 ms) |
| `--min-run` | Durée minimale d'un segment de parole conservé | `0.40` |
| `--export-format` | Format d'export (`fcpxml`, `edl`, ou `all`) | `all` |
| `--force, -f` | Force le recalcul complet (écrase le cache) | Désactivé |
| `--skip-transcribe`| Réutilise la transcription existante en cache | Désactivé |

---

## 📂 Utilisation Étape par Étape (Modulaire)

Si vous préférez exécuter ou déboguer les briques individuellement :

```bash
# 1. Inspection des pistes et extraction du son mono 16 kHz
python step1_extract.py --input "2026-10-26 15-29-46.mkv"

# 2. Transcription locale & VAD (Faster-Whisper)
python step2_transcribe.py

# 3. Découpage déterministe et calcul de la keep-list
python step3_keeplist.py --gap-split 0.70 --pad 0.15

# 4. Génération de la timeline FCPXML et de l'EDL
python step3_export.py
```

---

## 🎥 Import dans les Logiciels de Montage

### DaVinci Resolve (Recommandé)
1. Ouvrez DaVinci Resolve et créez un projet (cadence vidéo réglée sur celle de votre source, ex: 30 fps).
2. Dans le menu : **Fichier** > **Importer** > **Timeline...** (ou `Ctrl+Shift+I`).
3. Sélectionnez le fichier `output/montage_auto.fcpxml`.
4. La timeline apparaît immédiatement avec :
   - Tous les cuts déjà positionnés.
   - Les silences purgés de façon fluide.
   - Les marqueurs de couleur sur les silences majeurs (> 6 secondes).

*(Alternative : Si le FCPXML pose problème, importez `output/montage_auto.edl` via Fichier > Importer > Timeline EDL).*

### Kdenlive
1. Ouvrez Kdenlive.
2. Allez dans **Fichier** > **Ouvrir...** ou **Projet** > **Importer une timeline** (FCPXML/EDL).

---

## 🗂️ Structure du Projet

```text
IA_Montage/
├── .gitignore               # Ignore les vidéos volumineuses et le cache
├── .env.example             # Exemple de variables d'environnement
├── requirements.txt         # Dépendances Python nécessaires
├── README.md                # Documentation complète
├── run_pipeline.py          # Script d'orchestration global en une ligne
├── step1_extract.py         # Inspection, remuxing MP4 et extraction audio 16 kHz
├── step2_transcribe.py      # Transcription Whisper + Silero VAD (auto CPU/GPU)
├── step3_keeplist.py        # Calcul déterministe des silences et padding
├── step3_export.py          # Exporteur de timeline FCPXML v1.9 et CMX3600 EDL
├── cache/
│   ├── .gitkeep
│   ├── video_meta.json      # Métadonnées sondées (FPS, résolution, durée)
│   ├── audio_16k.wav        # Audio extrait pour Whisper (non tracké)
│   ├── transcript_raw.json  # Transcription brute avec timestamps mots
│   └── keep_list.json       # Intervalles temporels des clips conservés
└── output/
    ├── .gitkeep
    ├── session_source.mp4   # Fichier vidéo remuxé (non tracké)
    ├── montage_auto.fcpxml  # Timeline FCPXML finale
    └── montage_auto.edl     # Timeline EDL CMX3600 finale
```

---

## ⚙️ Réglage du Rythme de Coupe

- **Si le montage est trop rapide / haché** :
  Augmentez `--gap-split` à `0.85` ou `1.0` et `--pad` à `0.20`.
- **Si vous souhaitez un format très dynamique (type YouTube / Shorts)** :
  Diminuez `--gap-split` à `0.55` et `--pad` à `0.10`.
