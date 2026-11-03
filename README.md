# 🎬 AI Video Auto-Cut Pipeline (Poker & Talk Video)

Pipeline d'automatisation de pré-montage vidéo par IA : détection fine de la voix humaine (Silero VAD + Faster-Whisper), suppression déterministe des silences et micro-pauses sans coupure abrupte, et génération d'une **timeline non-destructive** (`.fcpxml` / `.kdenlive` / `.edl`) directement importable dans **DaVinci Resolve**, **Kdenlive** ou **Premiere Pro**.

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
cd Poker_montage

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
| `--merge-gap` | Fusionne deux clips séparés de moins de X secondes (après padding) | `0.10` |
| `--model` | Modèle Whisper (`small`, `medium`, `large-v3`) | Auto (selon GPU/CPU) |
| `--device` | Matériel de calcul (`cpu` ou `cuda`) | Auto |
| `--export-format` | Format d'export (`fcpxml`, `kdenlive`, `edl`, ou `all`) | `all` |
| `--force, -f` | Force le recalcul complet (écrase le cache) | Désactivé |
| `--skip-extract` | Saute l'extraction si la vidéo remuxée et le WAV existent déjà | Désactivé |
| `--skip-transcribe`| Saute la transcription (réutilise celle en cache) | Désactivé |
| `--semantic` | Lance la phase 4 (montage sémantique, voir plus bas) | Désactivé |

> La détection automatique cherche un `.mkv` ou `.mp4` dans le dossier courant et prend le premier trouvé (hors `session_source.mp4`).

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

# 4. Génération des timelines FCPXML, Kdenlive et EDL
python step3_export.py
```

---

## 🧠 Phase 4 : Montage Sémantique (optionnel)

Les étapes 1 à 3 coupent les **silences**. La phase 4 coupe selon le **sens** : une IA lit la transcription et décide quoi retirer (hésitations, phrases répétées, lecture du timer du replay, fin tronquée), découpe la vidéo en chapitres (un par spot) et marque les passages sensibles à vérifier avant YouTube.

Aucune clé API n'est nécessaire : n'importe quelle IA peut écrire le fichier de décisions (Claude Code, ChatGPT, DeepSeek...).

```bash
# 1. Préparer le texte à donner à l'IA (consignes + transcription)
python step4_semantic.py --make-prompt
# -> cache/semantic_prompt.md

# 2. Faire écrire cache/semantic_decisions.json par l'IA
#    (ex. dans Claude Code : « fais la phase 4 à partir de cache/semantic_prompt.md »)

# 3. Appliquer les décisions
python step4_semantic.py
```

Fichiers produits (les fichiers `montage_auto.*` de l'étape 3 ne sont pas modifiés) :

- `output/montage_ia.fcpxml` / `.kdenlive` / `.edl` : timeline avec les coupes IA appliquées
- Marqueurs dans la timeline : `CHAPITRE : ...`, `COUPE IA : ...` (au point de raccord) et `À VÉRIFIER : ...`
- `output/chapitres_youtube.txt` : chapitres prêts à coller dans la description YouTube
- `cache/keep_list_ia.json` : la nouvelle liste de clips

Pour annuler une coupe, retirez-la de `cache/semantic_decisions.json` et relancez `python step4_semantic.py`.

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
2. Allez dans **Fichier** > **Ouvrir...** et sélectionnez directement le projet natif `output/montage_auto.kdenlive`.

*(Alternative : **Fichier** > **Importer** pour charger le `.fcpxml` ou l'`.edl`.)*

---

## 🗂️ Structure du Projet

```text
Poker_montage/
├── .gitignore               # Ignore les vidéos volumineuses et le cache
├── .env.example             # Exemple de variables d'environnement
├── requirements.txt         # Dépendances Python nécessaires
├── README.md                # Documentation complète
├── run_pipeline.py          # Script d'orchestration global en une ligne
├── step1_extract.py         # Inspection, remuxing MP4 et extraction audio 16 kHz
├── step2_transcribe.py      # Transcription Whisper + Silero VAD (auto CPU/GPU)
├── step3_keeplist.py        # Calcul déterministe des silences et padding
├── step3_export.py          # Exporteur FCPXML v1.9, projet Kdenlive et EDL CMX3600
├── step4_semantic.py        # Phase 4 : applique les décisions de l'IA (coupes, chapitres, marqueurs)
├── cache/
│   ├── .gitkeep
│   ├── video_meta.json      # Métadonnées sondées (FPS, résolution, durée)
│   ├── audio_16k.wav        # Audio extrait pour Whisper (non tracké)
│   ├── transcript_raw.json  # Transcription brute avec timestamps mots
│   ├── compact_payload.txt  # Transcription compacte ID|DÉBUT-FIN|TEXTE
│   ├── keep_list.json       # Intervalles temporels des clips conservés
│   ├── review_flags.json    # Points à vérifier (gros silences, segments douteux)
│   ├── semantic_prompt.md   # Phase 4 : consignes + transcription pour l'IA
│   ├── semantic_decisions.json # Phase 4 : décisions de l'IA
│   └── keep_list_ia.json    # Phase 4 : clips après coupes sémantiques
└── output/
    ├── .gitkeep
    ├── session_source.mp4   # Fichier vidéo remuxé (non tracké)
    ├── montage_auto.fcpxml  # Timeline FCPXML finale
    ├── montage_auto.kdenlive # Projet Kdenlive natif
    ├── montage_auto.edl     # Timeline EDL CMX3600 finale
    ├── montage_ia.*         # Phase 4 : timelines avec coupes et marqueurs IA
    └── chapitres_youtube.txt # Phase 4 : chapitres pour la description YouTube
```

---

## ⚙️ Réglage du Rythme de Coupe

- **Si le montage est trop rapide / haché** :
  Augmentez `--gap-split` à `0.85` ou `1.0` et `--pad` à `0.20`.
- **Si vous souhaitez un format très dynamique (type YouTube / Shorts)** :
  Diminuez `--gap-split` à `0.55` et `--pad` à `0.10`.
