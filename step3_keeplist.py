#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Étape 3 : Calcul déterministe de la Keep-List et des Review Flags.
Découpe les runs de parole sur les micro-blancs, applique le padding et aligne sur la grille des frames.
"""

import argparse
import json
import math
import subprocess
from fractions import Fraction
from pathlib import Path


def get_video_specs(meta_path: Path, video_path: Path = None):
    """Récupère fps, total_frames et duration depuis le cache meta ou via ffprobe."""
    if meta_path and meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                fps = float(meta.get("fps", 30.0))
                duration = float(meta.get("duration", 3854.233))
                nb_frames = int(meta.get("nb_frames", round(duration * fps)))
                return fps, nb_frames, duration
        except Exception:
            pass

    if video_path and video_path.exists():
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=r_frame_rate,nb_frames,duration:format=duration",
                "-of", "json",
                str(video_path.resolve())
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(res.stdout)
            st = data.get("streams", [{}])[0]
            fmt = data.get("format", {})
            r_fps = st.get("r_frame_rate", "30/1")
            fps = float(Fraction(r_fps))
            dur_str = st.get("duration") or fmt.get("duration")
            duration = float(dur_str) if dur_str else 3854.233
            nb_frames = int(st.get("nb_frames", round(duration * fps)))
            return fps, nb_frames, duration
        except Exception:
            pass

    # Valeurs par défaut de secours
    return 30.0, 115627, 3854.233


def get_closest_segment_text(segments, target_time, mode="before"):
    """Trouve le texte du segment le plus proche avant ou après un timestamp."""
    best_text = ""
    min_dist = float("inf")
    for s in segments:
        if mode == "before":
            dist = abs(target_time - s["end"])
            if s["end"] <= target_time + 0.5 and dist < min_dist:
                min_dist = dist
                best_text = s["text"]
        else:
            dist = abs(s["start"] - target_time)
            if s["start"] >= target_time - 0.5 and dist < min_dist:
                min_dist = dist
                best_text = s["text"]
    if not best_text and segments:
        closest = min(segments, key=lambda s: abs((s["start"] + s["end"]) / 2 - target_time))
        best_text = closest["text"]
    return best_text


def compute_keep_list(raw_segments, fps: float, total_frames: int, video_duration: float,
                      gap_split: float = 0.70, pad: float = 0.15, min_run: float = 0.40,
                      min_prob_for_short: float = 0.60, merge_gap: float = 0.10):
    """Calcule la liste des clips à conserver."""
    # 1. Extraction et mise à plat de tous les mots horodatés
    all_words = []
    for s in raw_segments:
        for w in s.get("words", []):
            all_words.append(w)

    all_words.sort(key=lambda w: w["start"])
    if not all_words:
        print("[Attention] Aucun mot horodaté trouvé dans la transcription.")
        return [], []

    print(f"Total mots analysés : {len(all_words)}")

    # 2. Découpage en "runs" basé sur gap_split
    runs = []
    current_run = [all_words[0]]
    for w in all_words[1:]:
        gap = w["start"] - current_run[-1]["end"]
        if gap > gap_split:
            runs.append(current_run)
            current_run = [w]
        else:
            current_run.append(w)
    if current_run:
        runs.append(current_run)

    print(f"Runs initiaux détectés : {len(runs)}")

    # 3. Filtrage min_run et application du PADDING
    padded_runs = []
    dropped_short_runs = 0
    for r in runs:
        raw_dur = r[-1]["end"] - r[0]["start"]
        mean_prob = sum(w["prob"] for w in r) / len(r)

        if raw_dur < min_run and mean_prob < min_prob_for_short:
            dropped_short_runs += 1
            continue

        p_start = max(0.0, r[0]["start"] - pad)
        p_end = min(video_duration, r[-1]["end"] + pad)
        padded_runs.append({
            "start": p_start,
            "end": p_end,
            "mean_prob": mean_prob,
            "words_count": len(r)
        })

    print(f"Runs filtrés (< {min_run}s & prob < {min_prob_for_short}) : {dropped_short_runs}")
    print(f"Runs conservés avant fusion : {len(padded_runs)}")

    # 4. Fusion des runs séparés après padding par moins de merge_gap
    merged_runs = []
    for r in padded_runs:
        if not merged_runs:
            merged_runs.append(dict(r))
        else:
            prev = merged_runs[-1]
            if r["start"] - prev["end"] < merge_gap:
                prev["end"] = max(prev["end"], r["end"])
                prev["words_count"] += r["words_count"]
            else:
                merged_runs.append(dict(r))

    print(f"Runs après fusion (< {merge_gap}s) : {len(merged_runs)}")

    # 5. Alignement sur la grille des frames (start floor, end ceil)
    snapped_clips = []
    for r in merged_runs:
        start_frame = max(0, math.floor(r["start"] * fps))
        end_frame = min(total_frames, math.ceil(r["end"] * fps))

        if not snapped_clips:
            snapped_clips.append({"start_frame": start_frame, "end_frame": end_frame})
        else:
            prev = snapped_clips[-1]
            if start_frame <= prev["end_frame"]:
                prev["end_frame"] = max(prev["end_frame"], end_frame)
            else:
                snapped_clips.append({"start_frame": start_frame, "end_frame": end_frame})

    # Construction de la keep_list finale
    keep_list = []
    for idx, c in enumerate(snapped_clips):
        s_sec = c["start_frame"] / fps
        e_sec = c["end_frame"] / fps
        dur_sec = (c["end_frame"] - c["start_frame"]) / fps
        keep_list.append({
            "id": idx,
            "start": round(s_sec, 4),
            "end": round(e_sec, 4),
            "start_frame": c["start_frame"],
            "end_frame": c["end_frame"],
            "duration": round(dur_sec, 4),
            "duration_frames": c["end_frame"] - c["start_frame"]
        })

    return keep_list, all_words


def compute_review_flags(keep_list, raw_segments, fps: float, total_frames: int, video_duration: float):
    """Génère le diagnostic de vérification (gros trous, probabilités faibles, boucles)."""
    # a) Trous coupés >= 6s
    gaps_gt_6s = []
    if keep_list and keep_list[0]["start_frame"] > 0:
        gap_dur = keep_list[0]["start_frame"] / fps
        if gap_dur >= 6.0:
            gaps_gt_6s.append({
                "type": "lead",
                "clip_id_after": 0,
                "start": 0.0,
                "end": round(keep_list[0]["start"], 3),
                "duration": round(gap_dur, 2),
                "prev_text": "[DÉBUT VIDÉO]",
                "next_text": get_closest_segment_text(raw_segments, keep_list[0]["start"], mode="after")
            })

    for i in range(len(keep_list) - 1):
        g_start = keep_list[i]["end"]
        g_end = keep_list[i + 1]["start"]
        dur = round(g_end - g_start, 3)
        if dur >= 6.0:
            prev_t = get_closest_segment_text(raw_segments, g_start, mode="before")
            next_t = get_closest_segment_text(raw_segments, g_end, mode="after")
            gaps_gt_6s.append({
                "type": "internal",
                "clip_id_before": keep_list[i]["id"],
                "clip_id_after": keep_list[i + 1]["id"],
                "start": g_start,
                "end": g_end,
                "duration": round(dur, 2),
                "prev_text": prev_t,
                "next_text": next_t
            })

    if keep_list and keep_list[-1]["end_frame"] < total_frames:
        gap_dur = (total_frames - keep_list[-1]["end_frame"]) / fps
        if gap_dur >= 6.0:
            gaps_gt_6s.append({
                "type": "trail",
                "clip_id_before": keep_list[-1]["id"],
                "clip_id_after": None,
                "start": round(keep_list[-1]["end"], 3),
                "end": round(video_duration, 3),
                "duration": round(gap_dur, 2),
                "prev_text": get_closest_segment_text(raw_segments, keep_list[-1]["end"], mode="before"),
                "next_text": "[FIN VIDÉO]"
            })

    # b) Segments dont prob moyenne des mots < 0.45
    low_prob_segments = []
    for s in raw_segments:
        w_list = s.get("words", [])
        if w_list:
            avg_p = sum(w["prob"] for w in w_list) / len(w_list)
            if avg_p < 0.45:
                low_prob_segments.append({
                    "segment_id": s["id"],
                    "start": s["start"],
                    "end": s["end"],
                    "avg_prob": round(avg_p, 3),
                    "text": s["text"]
                })

    # c) Boucles suspectes d'hallucination (même texte 3 fois consécutives ou plus)
    hallucination_loops = []
    i = 0
    while i < len(raw_segments):
        txt_clean = raw_segments[i]["text"].strip().lower()
        if not txt_clean:
            i += 1
            continue
        j = i + 1
        while j < len(raw_segments) and raw_segments[j]["text"].strip().lower() == txt_clean:
            j += 1
        if j - i >= 3:
            hallucination_loops.append({
                "text": raw_segments[i]["text"],
                "count": j - i,
                "start_segment_id": raw_segments[i]["id"],
                "end_segment_id": raw_segments[j - 1]["id"],
                "start": raw_segments[i]["start"],
                "end": raw_segments[j - 1]["end"]
            })
        i = j

    return {
        "large_gaps_gt_6s": gaps_gt_6s,
        "low_probability_segments": low_prob_segments,
        "hallucination_loops": hallucination_loops
    }


def main():
    parser = argparse.ArgumentParser(description="Étape 3 : Calcul déterministe de la Keep-List.")
    parser.add_argument("--transcript", "-t", type=str, default="cache/transcript_raw.json", help="Chemin de transcript_raw.json")
    parser.add_argument("--meta", "-m", type=str, default="cache/video_meta.json", help="Chemin des métadonnées vidéo")
    parser.add_argument("--video", "-v", type=str, default="output/session_source.mp4", help="Vidéo source pour sonder si meta absent")
    parser.add_argument("--output-keeplist", type=str, default="cache/keep_list.json", help="Fichier JSON keep_list en sortie")
    parser.add_argument("--output-review", type=str, default="cache/review_flags.json", help="Fichier JSON review_flags en sortie")
    parser.add_argument("--gap-split", type=float, default=0.70, help="Seuil de coupure silence (secondes)")
    parser.add_argument("--pad", type=float, default=0.15, help="Marge de sécurité padding audio (secondes)")
    parser.add_argument("--min-run", type=float, default=0.40, help="Durée minimum d'un segment conservé (secondes)")
    parser.add_argument("--merge-gap", type=float, default=0.10, help="Fusionne les clips espacés de moins de X secondes après padding")
    args = parser.parse_args()

    raw_path = Path(args.transcript).resolve()
    meta_path = Path(args.meta).resolve()
    video_path = Path(args.video).resolve()
    keeplist_path = Path(args.output_keeplist).resolve()
    review_path = Path(args.output_review).resolve()

    if not raw_path.exists():
        print(f"[ERREUR] {raw_path} est introuvable. Exécutez d'abord step2_transcribe.py.")
        return

    with open(raw_path, "r", encoding="utf-8") as f:
        raw_segments = json.load(f)

    fps, total_frames, video_duration = get_video_specs(meta_path, video_path)
    print("=" * 60)
    print("PHASE 3A : CALCUL DE LA KEEP-LIST & PADDING")
    print(f"Paramètres : GAP_SPLIT={args.gap_split}s | PAD={args.pad}s | MIN_RUN={args.min_run}s | MERGE={args.merge_gap}s")
    print(f"Vidéo : {video_duration:.2f}s | FPS={fps} | Frames={total_frames}")
    print("=" * 60)

    keep_list, _ = compute_keep_list(
        raw_segments,
        fps=fps,
        total_frames=total_frames,
        video_duration=video_duration,
        gap_split=args.gap_split,
        pad=args.pad,
        min_run=args.min_run,
        merge_gap=args.merge_gap
    )

    keeplist_path.parent.mkdir(parents=True, exist_ok=True)
    with open(keeplist_path, "w", encoding="utf-8") as f:
        json.dump(keep_list, f, indent=2, ensure_ascii=False)
    print(f"Keep-list enregistrée : {keeplist_path} ({len(keep_list)} clips)")

    total_kept_frames = sum(c["duration_frames"] for c in keep_list)
    total_kept_sec = total_kept_frames / fps
    pct = (total_kept_sec / video_duration) * 100 if video_duration else 0
    print(f"Durée conservée : {total_kept_sec:.2f}s ({total_kept_sec/60:.2f} min) [{pct:.1f}%]")

    review_flags = compute_review_flags(keep_list, raw_segments, fps, total_frames, video_duration)
    with open(review_path, "w", encoding="utf-8") as f:
        json.dump(review_flags, f, indent=2, ensure_ascii=False)
    print(f"Review flags enregistrés : {review_path}")
    print(f"  - Trous >= 6s : {len(review_flags['large_gaps_gt_6s'])}")
    print(f"  - Segments prob < 0.45 : {len(review_flags['low_probability_segments'])}")
    print(f"  - Boucles d'hallucination : {len(review_flags['hallucination_loops'])}")


if __name__ == "__main__":
    main()
