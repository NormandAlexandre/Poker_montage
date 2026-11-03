#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Étape 1 : Inspection, Remuxing sans perte et Extraction audio 16 kHz.
Vérifie la présence de FFmpeg/FFprobe, extrait les métadonnées et prépare les fichiers.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
from fractions import Fraction
from pathlib import Path


def check_ffmpeg():
    """Vérifie que ffmpeg et ffprobe sont présents dans le PATH."""
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            print(f"[ERREUR] '{tool}' est introuvable dans le PATH système.")
            print("Veuillez installer FFmpeg et l'ajouter à vos variables d'environnement.")
            sys.exit(1)


def probe_video(video_path: Path) -> dict:
    """Extrait les métadonnées vidéo et audio via ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate,nb_frames,duration",
        "-show_entries", "format=duration,size,format_name",
        "-of", "json",
        str(video_path.resolve()),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    probe = json.loads(res.stdout)

    if not probe.get("streams"):
        raise ValueError(f"Aucun flux vidéo trouvé dans {video_path}")

    v_stream = probe["streams"][0]
    fmt = probe.get("format", {})

    # Résolution et framerate
    width = int(v_stream.get("width", 1920))
    height = int(v_stream.get("height", 1080))

    r_fps_str = v_stream.get("r_frame_rate", "30/1")
    avg_fps_str = v_stream.get("avg_frame_rate", r_fps_str)
    fps_frac = Fraction(r_fps_str)
    fps = round(float(fps_frac), 3)

    # Durée
    duration_str = v_stream.get("duration") or fmt.get("duration")
    if duration_str:
        duration = float(duration_str)
    else:
        raise ValueError("Impossible de déterminer la durée de la vidéo.")

    # Nombre de frames
    nb_frames_str = v_stream.get("nb_frames")
    if nb_frames_str:
        nb_frames = int(nb_frames_str)
    else:
        nb_frames = int(round(duration * fps))

    # Pistes audio
    cmd_audio = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "a",
        "-show_entries", "stream=index,codec_name,channels,sample_rate:stream_tags=title",
        "-of", "json",
        str(video_path.resolve()),
    ]
    res_audio = subprocess.run(cmd_audio, capture_output=True, text=True)
    audio_probe = json.loads(res_audio.stdout) if res_audio.returncode == 0 else {}
    audio_streams = audio_probe.get("streams", [])

    return {
        "source_path": str(video_path.resolve()),
        "width": width,
        "height": height,
        "fps": fps,
        "fps_rational": r_fps_str,
        "avg_fps": str(avg_fps_str),
        "duration": duration,
        "nb_frames": nb_frames,
        "audio_tracks_count": len(audio_streams),
        "audio_streams": audio_streams,
    }


def extract_media(video_path: Path, output_mp4: Path, output_wav: Path, force: bool = False):
    """
    1. Remux sans perte vers MP4 (ou copie si déjà MP4).
    2. Extraction audio mono 16 kHz optimisée pour Faster-Whisper.
    """
    check_ffmpeg()
    output_mp4.parent.mkdir(parents=True, exist_ok=True)
    output_wav.parent.mkdir(parents=True, exist_ok=True)

    # 1. Remuxing vidéo sans ré-encodage
    if not output_mp4.exists() or force:
        print(f"[FFmpeg] Remuxing sans ré-encodage vers : {output_mp4}...")
        cmd_remux = [
            "ffmpeg", "-y",
            "-i", str(video_path.resolve()),
            "-map", "0",
            "-c", "copy",
            str(output_mp4.resolve())
        ]
        subprocess.run(cmd_remux, check=True)
        print("  -> Remuxing terminé avec succès.")
    else:
        print(f"[Info] Vidéo MP4 déjà existante : {output_mp4} (ignoré)")

    # 2. Extraction audio mono 16kHz WAV
    if not output_wav.exists() or force:
        print(f"[FFmpeg] Extraction audio WAV 16kHz mono vers : {output_wav}...")
        cmd_audio = [
            "ffmpeg", "-y",
            "-i", str(video_path.resolve()),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "16000",
            "-ac", "1",
            str(output_wav.resolve())
        ]
        subprocess.run(cmd_audio, check=True)
        print("  -> Extraction audio terminée avec succès.")
    else:
        print(f"[Info] Audio 16kHz déjà existant : {output_wav} (ignoré)")


def main():
    parser = argparse.ArgumentParser(description="Étape 1 : Inspection et extraction audio/vidéo.")
    parser.add_argument("--input", "-i", type=str, help="Fichier vidéo d'entrée (.mkv, .mp4, etc.)")
    parser.add_argument("--output-mp4", type=str, default="output/session_source.mp4", help="Chemin du MP4 remuxé")
    parser.add_argument("--output-wav", type=str, default="cache/audio_16k.wav", help="Chemin du WAV 16kHz")
    parser.add_argument("--meta-json", type=str, default="cache/video_meta.json", help="Chemin de sauvegarde des métadonnées")
    parser.add_argument("--force", "-f", action="store_true", help="Forcer la ré-extraction même si les fichiers existent")
    args = parser.parse_args()

    # Détection automatique du fichier vidéo si non spécifié
    if not args.input:
        candidates = list(Path(".").glob("*.mkv")) + list(Path(".").glob("*.mp4"))
        # Exclure output/session_source.mp4
        candidates = [c for c in candidates if c.name != "session_source.mp4"]
        if candidates:
            video_file = candidates[0]
            print(f"[Auto-détection] Utilisation de la vidéo source : {video_file}")
        else:
            print("[ERREUR] Aucun fichier vidéo trouvé dans le répertoire courant.")
            print("Spécifiez-en un avec --input mon_fichier.mkv")
            sys.exit(1)
    else:
        video_file = Path(args.input)
        if not video_file.exists():
            print(f"[ERREUR] Le fichier source '{video_file}' n'existe pas.")
            sys.exit(1)

    print("=" * 60)
    print("PHASE 1 : INSPECTION ET EXTRACTION AUDIO/VIDÉO")
    print("=" * 60)

    meta = probe_video(video_file)
    print(f"Fichier : {video_file.name}")
    print(f"Résolution : {meta['width']}x{meta['height']} @ {meta['fps']} fps")
    print(f"Durée : {meta['duration']:.2f}s ({meta['duration']/60:.2f} min) | Frames: {meta['nb_frames']}")
    print(f"Pistes audio détectées : {meta['audio_tracks_count']}")

    meta_path = Path(args.meta_json)
    meta_path.parent.mkdir(parents=True, exist_ok=True)
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)
    print(f"Métadonnées enregistrées dans : {meta_path}")

    extract_media(
        video_file,
        Path(args.output_mp4),
        Path(args.output_wav),
        force=args.force
    )


if __name__ == "__main__":
    main()
