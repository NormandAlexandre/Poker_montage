#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Pipeline Maître : Découpage Automatique Non-Destructif par IA
Orchestre les phases 1, 2, 3A et 3B de A à Z.
Usage simple :
    python run_pipeline.py --input "ma_video.mkv"
"""

import argparse
import sys
import time
from pathlib import Path

import step1_extract
import step2_transcribe
import step3_keeplist
import step3_export
import step4_semantic


def main():
    parser = argparse.ArgumentParser(
        description="Pipeline IA de montage vidéo automatisé (VAD + Faster-Whisper + FCPXML/EDL)"
    )
    parser.add_argument("--input", "-i", type=str, help="Chemin du fichier vidéo d'entrée (.mkv, .mp4, etc.)")
    parser.add_argument("--model", type=str, default=None, help="Modèle Whisper (small, medium, large-v3, ou auto)")
    parser.add_argument("--device", type=str, default=None, help="Device (cpu, cuda, ou auto)")
    parser.add_argument("--gap-split", type=float, default=0.70, help="Seuil de silence pour scinder en deux runs (secondes)")
    parser.add_argument("--pad", type=float, default=0.15, help="Marge de sécurité padding audio avant/après (secondes)")
    parser.add_argument("--min-run", type=float, default=0.40, help="Durée minimum d'un segment de parole conservé (secondes)")
    parser.add_argument("--merge-gap", type=float, default=0.10, help="Fusionne les clips espacés de moins de X secondes après padding")
    parser.add_argument("--export-format", choices=["fcpxml", "kdenlive", "edl", "all"], default="all", help="Format de timeline à exporter")
    parser.add_argument("--skip-extract", action="store_true", help="Passer l'étape d'extraction si les fichiers existent")
    parser.add_argument("--skip-transcribe", action="store_true", help="Passer l'étape de transcription si le cache existe")
    parser.add_argument("--force", "-f", action="store_true", help="Forcer le recalcul complet de toutes les étapes")
    parser.add_argument("--semantic", action="store_true", help="Phase 4 : applique cache/semantic_decisions.json (ou prépare le prompt pour l'IA)")
    args = parser.parse_args()

    # 1. Sélection du fichier vidéo source
    if not args.input:
        candidates = list(Path(".").glob("*.mkv")) + list(Path(".").glob("*.mp4"))
        candidates = [c for c in candidates if c.name != "session_source.mp4"]
        if candidates:
            video_file = candidates[0]
            print(f"[*] Vidéo auto-détectée : {video_file}")
        else:
            print("[ERREUR] Aucun fichier vidéo trouvé dans le dossier.")
            print("Usage : python run_pipeline.py --input \"chemin/vers/video.mkv\"")
            sys.exit(1)
    else:
        video_file = Path(args.input)
        if not video_file.exists():
            print(f"[ERREUR] Le fichier '{video_file}' n'existe pas.")
            sys.exit(1)

    t_global_start = time.time()

    # Chemins standards
    cache_dir = Path("cache")
    output_dir = Path("output")
    cache_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    meta_path = cache_dir / "video_meta.json"
    audio_wav_path = cache_dir / "audio_16k.wav"
    output_mp4_path = output_dir / "session_source.mp4"
    transcript_raw_path = cache_dir / "transcript_raw.json"
    compact_payload_path = cache_dir / "compact_payload.txt"
    keeplist_path = cache_dir / "keep_list.json"
    review_path = cache_dir / "review_flags.json"
    fcpxml_path = output_dir / "montage_auto.fcpxml"
    kdenlive_path = output_dir / "montage_auto.kdenlive"
    edl_path = output_dir / "montage_auto.edl"

    print("\n" + "=" * 65)
    print("      PIPELINE DE MONTAGE VIDÉO AUTOMATISÉ PAR IA")
    print("=" * 65)

    # -------------------------------------------------------------
    # ÉTAPE 1 : EXTRACTION & SONDAGE MÉDIA
    # -------------------------------------------------------------
    print("\n>>> ÉTAPE 1 : Sondage et Extraction")
    step1_extract.check_ffmpeg()
    meta = step1_extract.probe_video(video_file)
    with open(meta_path, "w", encoding="utf-8") as f:
        step1_extract.json.dump(meta, f, indent=2, ensure_ascii=False)

    print(f"  Fichier     : {video_file.name}")
    print(f"  Résolution  : {meta['width']}x{meta['height']} @ {meta['fps']} fps")
    print(f"  Durée       : {meta['duration']:.2f}s ({meta['duration']/60:.2f} min) | Frames: {meta['nb_frames']}")
    print(f"  Pistes son  : {meta['audio_tracks_count']}")

    if not args.skip_extract or args.force or not output_mp4_path.exists() or not audio_wav_path.exists():
        step1_extract.extract_media(video_file, output_mp4_path, audio_wav_path, force=args.force)
    else:
        print("  [Passé] Vidéo remuxée et audio WAV déjà existants.")

    # -------------------------------------------------------------
    # ÉTAPE 2 : TRANSCRIPTION WHISPER + SILERO VAD
    # -------------------------------------------------------------
    print("\n>>> ÉTAPE 2 : Transcription et Détection Vocale (Silero VAD)")
    if transcript_raw_path.exists() and compact_payload_path.exists() and not args.force and not args.skip_transcribe:
        print(f"  [Cache] Transcription existante réutilisée : {transcript_raw_path}")
    elif args.skip_transcribe:
        print("  [Passé] Option --skip-transcribe activée.")
    else:
        # Appel du runner de transcription
        cmd_args = ["--audio", str(audio_wav_path), "--meta", str(meta_path)]
        if args.model:
            cmd_args.extend(["--model", args.model])
        if args.device:
            cmd_args.extend(["--device", args.device])
        if args.force:
            cmd_args.append("--force")
        # Exécution directe
        import sys
        old_argv = sys.argv
        sys.argv = ["step2_transcribe.py"] + cmd_args
        step2_transcribe.main()
        sys.argv = old_argv

    # -------------------------------------------------------------
    # ÉTAPE 3A : CALCUL DE LA KEEP-LIST DÉTERMINISTE
    # -------------------------------------------------------------
    print("\n>>> ÉTAPE 3A : Découpage des silences et calcul de la Keep-List")
    with open(transcript_raw_path, "r", encoding="utf-8") as f:
        raw_segments = step3_keeplist.json.load(f)

    fps, total_frames, video_duration = step3_keeplist.get_video_specs(meta_path, output_mp4_path)

    keep_list, _ = step3_keeplist.compute_keep_list(
        raw_segments,
        fps=fps,
        total_frames=total_frames,
        video_duration=video_duration,
        gap_split=args.gap_split,
        pad=args.pad,
        min_run=args.min_run,
        merge_gap=args.merge_gap
    )
    with open(keeplist_path, "w", encoding="utf-8") as f:
        step3_keeplist.json.dump(keep_list, f, indent=2, ensure_ascii=False)

    review_flags = step3_keeplist.compute_review_flags(
        keep_list, raw_segments, fps, total_frames, video_duration
    )
    with open(review_path, "w", encoding="utf-8") as f:
        step3_keeplist.json.dump(review_flags, f, indent=2, ensure_ascii=False)

    total_kept_sec = sum(c["duration"] for c in keep_list)
    print(f"  Clips conservés : {len(keep_list)}")
    print(f"  Durée conservée : {total_kept_sec:.2f}s ({total_kept_sec/60:.2f} min) [{(total_kept_sec/video_duration)*100:.1f}%]")

    # -------------------------------------------------------------
    # ÉTAPE 3B : EXPORT FCPXML / EDL
    # -------------------------------------------------------------
    print("\n>>> ÉTAPE 3B : Génération de la timeline non-destructive")
    width, height, fps, nb_frames, duration = step3_export.get_video_specs(meta_path, output_mp4_path)

    if args.export_format in ("fcpxml", "all"):
        step3_export.generate_fcpxml(
            keep_list, review_flags,
            source_path=output_mp4_path,
            output_path=fcpxml_path,
            width=width, height=height, fps=fps, total_source_frames=nb_frames
        )

    if args.export_format in ("kdenlive", "all"):
        step3_export.generate_kdenlive(
            keep_list,
            source_path=output_mp4_path,
            output_path=kdenlive_path,
            width=width, height=height, fps=fps, total_source_frames=nb_frames
        )

    if args.export_format in ("edl", "all"):
        step3_export.generate_edl(
            keep_list,
            source_filename=output_mp4_path.name,
            output_path=edl_path,
            fps=fps
        )

    stats = step3_export.compute_statistics(keep_list, review_flags, duration)

    t_total = time.time() - t_global_start
    print("\n" + "=" * 65)
    print("                 TRAITEMENT TERMINÉ AVEC SUCCÈS")
    print(f"               Durée totale du pipeline : {t_total:.1f}s")
    print("=" * 65)
    print(f"Clips finaux  : {len(keep_list)}")
    print(f"Durée gardée  : {int(stats['total_kept_sec']//60)}m{int(stats['total_kept_sec']%60)}s ({stats['kept_pct']:.1f}%)")
    print(f"Durée coupée  : {int(stats['total_cut_sec']//60)}m{int(stats['total_cut_sec']%60)}s ({stats['cut_pct']:.1f}%)")
    print("\nFichiers générés :")
    if args.export_format in ("fcpxml", "all"):
        print(f"  -> Timeline FCPXML    : {fcpxml_path}")
    if args.export_format in ("kdenlive", "all"):
        print(f"  -> Projet Kdenlive    : {kdenlive_path}")
    if args.export_format in ("edl", "all"):
        print(f"  -> Timeline EDL       : {edl_path}")

    # -------------------------------------------------------------
    # ÉTAPE 4 (OPTIONNELLE) : MONTAGE SÉMANTIQUE
    # -------------------------------------------------------------
    if args.semantic:
        print("\n>>> ÉTAPE 4 : Montage sémantique")
        decisions_path = cache_dir / "semantic_decisions.json"
        if decisions_path.exists():
            step4_semantic.run(
                decisions_path=decisions_path,
                transcript_path=transcript_raw_path,
                keeplist_path=keeplist_path,
                review_path=review_path,
                meta_path=meta_path,
                video_path=output_mp4_path.resolve(),
                output_dir=output_dir,
                export_format=args.export_format,
            )
        else:
            step4_semantic.make_prompt(compact_payload_path, cache_dir / "semantic_prompt.md")
            print("  Pas encore de décisions : fais remplir cache/semantic_decisions.json par une IA, puis relance avec --semantic.")

    name = "montage_ia" if args.semantic and (cache_dir / "semantic_decisions.json").exists() else "montage_auto"
    print("\nProchaine action :")
    print(f"1. DaVinci Resolve : Fichier -> Importer -> Timeline -> Sélectionnez {name}.fcpxml")
    print(f"2. Kdenlive        : Ouvrez directement le fichier output/{name}.kdenlive")


if __name__ == "__main__":
    main()
