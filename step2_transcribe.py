#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Étape 2 : Transcription Speech-to-Text avec Faster-Whisper + Silero VAD.
Détection automatique CPU / GPU (CUDA), timestamps au mot près, prompt spécialisé poker.
"""

import argparse
import json
import os
import sys
import time
from pathlib import Path

import tiktoken
from faster_whisper import WhisperModel


def detect_hardware():
    """Détecte la présence d'un GPU NVIDIA (CUDA) ou configure le CPU."""
    try:
        import torch
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            print(f"[Matériel] GPU NVIDIA détecté : {gpu_name} ({vram_gb:.1f} Go VRAM)")
            if vram_gb >= 6.0:
                return "cuda", "large-v3", "float16", 1
            else:
                return "cuda", "small", "float16", 1
    except Exception:
        pass

    cpu_cores = os.cpu_count() or 4
    threads = min(cpu_cores, 12)
    print(f"[Matériel] Exécution CPU détectée ({cpu_cores} cœurs, allocation: {threads} threads)")
    return "cpu", "small", "int8", threads


def main():
    parser = argparse.ArgumentParser(description="Étape 2 : Transcription Faster-Whisper + Silero VAD.")
    parser.add_argument("--audio", "-a", type=str, default="cache/audio_16k.wav", help="Chemin du fichier WAV 16kHz")
    parser.add_argument("--meta", "-m", type=str, default="cache/video_meta.json", help="Chemin des métadonnées vidéo")
    parser.add_argument("--model", type=str, default=None, help="Modèle Whisper (small, medium, large-v3, ou auto)")
    parser.add_argument("--device", type=str, default=None, help="Device (cpu, cuda, ou auto)")
    parser.add_argument("--compute-type", type=str, default=None, help="Quantification (int8, float16, etc.)")
    parser.add_argument("--threads", type=int, default=None, help="Nombre de threads CPU")
    parser.add_argument("--output-raw", type=str, default="cache/transcript_raw.json", help="JSON brut avec timestamps mots")
    parser.add_argument("--output-compact", type=str, default="cache/compact_payload.txt", help="Payload compact ID|START-END|TEXT")
    parser.add_argument("--force", "-f", action="store_true", help="Forcer la re-transcription même si le cache existe")
    args = parser.parse_args()

    audio_path = Path(args.audio).resolve()
    raw_json_path = Path(args.output_raw).resolve()
    compact_txt_path = Path(args.output_compact).resolve()
    meta_path = Path(args.meta).resolve()

    if not audio_path.exists():
        print(f"[ERREUR] Le fichier audio {audio_path} est introuvable !")
        print("Veuillez d'abord exécuter l'étape 1 (step1_extract.py).")
        sys.exit(1)

    # Réutilisation du cache si disponible
    if raw_json_path.exists() and compact_txt_path.exists() and not args.force:
        print(f"[Info] Transcription déjà existante en cache : {raw_json_path}")
        print("Pour régénérer la transcription, utilisez l'option --force.")
        # Affichage rapide du nombre de tokens
        with open(compact_txt_path, "r", encoding="utf-8") as f:
            lines = f.read()
        enc = tiktoken.get_encoding("cl100k_base")
        tokens = len(enc.encode(lines))
        print(f"[Info] Volume du payload compact : {tokens:,} tokens (cl100k_base)")
        return

    # Durée totale estimée pour la barre de progression
    total_video_duration = 0.0
    if meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                total_video_duration = float(meta.get("duration", 0.0))
        except Exception:
            pass

    auto_device, auto_model, auto_compute, auto_threads = detect_hardware()
    device = args.device or auto_device
    model_name = args.model or auto_model
    compute_type = args.compute_type or auto_compute
    cpu_threads = args.threads or auto_threads

    print("=" * 60)
    print("PHASE 2 : TRANSCRIPTION FASTER-WHISPER + SILERO VAD")
    print(f"Audio source : {audio_path.name}")
    print(f"Modèle : {model_name} | Device : {device} | Compute : {compute_type} | Threads : {cpu_threads}")
    print("=" * 60)

    start_time = time.time()

    model = WhisperModel(
        model_name,
        device=device,
        compute_type=compute_type,
        cpu_threads=cpu_threads
    )

    initial_prompt = (
        "Coaching poker NLHE MTT Cash Game. Preflop, flop, turn, river, "
        "3-bet, 4-bet, c-bet, check-raise, sizing, pot, all-in, range, équité, EV, "
        "GTO, exploit, blindes, UTG, MP, CO, BTN, SB, BB, vilain, hero, tracker, "
        "HUD, board, overbet, bluff, value."
    )

    vad_params = dict(
        min_silence_duration_ms=400,
        speech_pad_ms=200
    )

    print("Transcription en cours (analyse de la voix humaine)...")
    segments_generator, info = model.transcribe(
        str(audio_path),
        language="fr",
        word_timestamps=True,
        vad_filter=True,
        vad_parameters=vad_params,
        condition_on_previous_text=False,
        initial_prompt=initial_prompt
    )

    raw_segments = []
    compact_lines = []
    total_speech_duration = 0.0

    for i, seg in enumerate(segments_generator):
        seg_id = i
        start_rounded = round(float(seg.start), 2)
        end_rounded = round(float(seg.end), 2)
        cleaned_text = seg.text.strip().replace("\n", " ")

        words_data = []
        if seg.words:
            for w in seg.words:
                words_data.append({
                    "word": w.word,
                    "start": round(float(w.start), 2),
                    "end": round(float(w.end), 2),
                    "prob": round(float(w.probability), 3)
                })

        raw_segments.append({
            "id": seg_id,
            "start": start_rounded,
            "end": end_rounded,
            "text": cleaned_text,
            "words": words_data
        })

        compact_lines.append(f"{seg_id}|{start_rounded:.2f}-{end_rounded:.2f}|{cleaned_text}")
        total_speech_duration += max(0.0, end_rounded - start_rounded)

        if (i + 1) % 50 == 0:
            if total_video_duration > 0:
                pct = (end_rounded / total_video_duration) * 100
                print(f"  -> {i + 1} segments traités (temps audio: {end_rounded:.1f}s / {total_video_duration:.1f}s - {pct:.1f}%)...")
            else:
                print(f"  -> {i + 1} segments traités (temps audio: {end_rounded:.1f}s)...")

    elapsed_time = time.time() - start_time
    print(f"\nTranscription terminée en {elapsed_time:.1f}s ({elapsed_time/60:.1f} min)")

    # Sauvegarde des résultats
    raw_json_path.parent.mkdir(parents=True, exist_ok=True)
    with open(raw_json_path, "w", encoding="utf-8") as f:
        json.dump(raw_segments, f, ensure_ascii=False, indent=2)
    print(f"Sauvegardé : {raw_json_path} ({len(raw_segments)} segments)")

    with open(compact_txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(compact_lines))
    print(f"Sauvegardé : {compact_txt_path}")

    # Comptage des tokens
    enc = tiktoken.get_encoding("cl100k_base")
    tokens = len(enc.encode("\n".join(compact_lines)))
    print(f"Comptage tokens : {tokens:,} tokens (cl100k_base)")


if __name__ == "__main__":
    main()
