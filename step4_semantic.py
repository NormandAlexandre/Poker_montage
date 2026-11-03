#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Étape 4 : Montage sémantique (le sens de ce qui est dit, pas seulement les silences).

L'analyse est faite par une IA (Claude Code, ChatGPT, DeepSeek...) qui lit la transcription
et écrit cache/semantic_decisions.json. Ce script ne dépend d'aucune IA : il applique ce fichier.

  1. python step4_semantic.py --make-prompt   -> écrit cache/semantic_prompt.md à donner à l'IA
  2. l'IA écrit cache/semantic_decisions.json (coupes, chapitres, points à vérifier)
  3. python step4_semantic.py                 -> applique les décisions et exporte output/montage_ia.*

Les fichiers de l'étape 3 (montage_auto.*) ne sont jamais modifiés.
"""

import argparse
import json
import math
import sys
from pathlib import Path

import step3_export

PROMPT_HEADER = """# Analyse sémantique d'une session de coaching poker

Tu reçois la transcription d'une vidéo (une ligne par segment : `ID|DÉBUT-FIN|TEXTE`, temps en secondes).
La transcription automatique fait des erreurs de mots : juge sur le sens global, pas sur un mot isolé.
Les silences sont déjà coupés. Ton rôle est d'améliorer le montage selon le SENS de ce qui est dit.

Écris un fichier JSON `cache/semantic_decisions.json` avec ce format :

```json
{
  "version": 1,
  "cuts": [
    {"segments": [12], "start": 41.48, "end": 50.04, "reason": "pourquoi on coupe"}
  ],
  "chapters": [
    {"start": 0.0, "segment": 0, "title": "Titre court du chapitre"}
  ],
  "review": [
    {"start": 100.0, "end": 110.0, "segments": [30], "note": "ce qu'il faut vérifier à l'écoute"}
  ]
}
```

Règles :
- `cuts` : uniquement ce qui n'apporte rien au spectateur (hésitations « euh », phrases répétées
  ou recommencées en gardant la dernière version, lecture du timer du replay, fin tronquée).
  Sois prudent : c'est un dialogue, ne coupe jamais une explication ni une réponse.
  `start`/`end` peuvent couvrir une partie d'un segment si tu connais les temps des mots.
- `chapters` : un chapitre par spot / main analysée et par leçon générale, titres courts en français.
- `review` : passages sensibles pour une publication YouTube (propos limites, mention de concurrents,
  apartés privés) ou passages confus. On ne coupe pas, on marque.

## Transcription

"""


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def make_prompt(compact_path: Path, out_path: Path):
    text = compact_path.read_text(encoding="utf-8")
    out_path.write_text(PROMPT_HEADER + text + "\n", encoding="utf-8")
    print(f"Prompt écrit : {out_path}")
    print("Donne ce fichier à ton IA (ex. dans Claude Code : « fais la phase 4 à partir de cache/semantic_prompt.md »).")


def segment_range(raw_segments, seg_ids):
    """Début du premier mot et fin du dernier mot des segments donnés."""
    by_id = {s["id"]: s for s in raw_segments}
    starts, ends = [], []
    for sid in seg_ids:
        s = by_id.get(sid)
        if not s:
            raise ValueError(f"Segment {sid} introuvable dans la transcription")
        words = s.get("words") or [{"start": s["start"], "end": s["end"]}]
        starts.append(words[0]["start"])
        ends.append(words[-1]["end"])
    return min(starts), max(ends)


def resolve_ranges(items, raw_segments):
    """Complète start/end à partir des segments quand ils manquent."""
    out = []
    for it in items:
        it = dict(it)
        if "start" not in it or "end" not in it:
            s, e = segment_range(raw_segments, it["segments"])
            it.setdefault("start", s)
            it.setdefault("end", e)
        if it["end"] <= it["start"]:
            raise ValueError(f"Intervalle invalide : {it}")
        out.append(it)
    return sorted(out, key=lambda x: x["start"])


def apply_cuts(keep_list, cuts, fps: float, min_piece_sec: float = 0.30):
    """Retire les intervalles coupés de la keep-list (en frames).

    Un morceau de clip qui reste après une coupe et qui fait moins de min_piece_sec est supprimé
    (sinon on garde des micro-clips de quelques frames).
    """
    cut_frames = [(math.floor(c["start"] * fps), math.ceil(c["end"] * fps)) for c in cuts]
    min_piece = max(1, round(min_piece_sec * fps))

    result = []
    for clip in keep_list:
        pieces = [(clip["start_frame"], clip["end_frame"])]
        for cs, ce in cut_frames:
            nxt = []
            for ps, pe in pieces:
                if ce <= ps or cs >= pe:
                    nxt.append((ps, pe))
                    continue
                if cs > ps:
                    nxt.append((ps, cs))
                if ce < pe:
                    nxt.append((ce, pe))
            pieces = nxt

        was_cut = pieces != [(clip["start_frame"], clip["end_frame"])]
        for ps, pe in pieces:
            if was_cut and pe - ps < min_piece:
                continue
            result.append((ps, pe))

    new_list = []
    for idx, (s, e) in enumerate(result):
        new_list.append({
            "id": idx,
            "start": round(s / fps, 4),
            "end": round(e / fps, 4),
            "start_frame": s,
            "end_frame": e,
            "duration": round((e - s) / fps, 4),
            "duration_frames": e - s,
        })
    return new_list


def locate(keep_list, t_sec: float, fps: float):
    """Trouve où tombe un temps source dans la timeline montée.

    Renvoie (clip, frame_source, frame_timeline). Si le temps tombe dans une partie coupée,
    on prend le début du clip suivant.
    """
    f = round(t_sec * fps)
    offset = 0
    for clip in keep_list:
        if f < clip["start_frame"]:
            return clip, clip["start_frame"], offset
        if f < clip["end_frame"]:
            return clip, f, offset + (f - clip["start_frame"])
        offset += clip["duration_frames"]
    last = keep_list[-1]
    return last, last["end_frame"] - 1, offset - 1


def fmt_chapter_time(frames: int, fps: float) -> str:
    total = int(frames // fps)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def build_markers(keep_list, decisions, fps: float):
    """Prépare les marqueurs FCPXML, les guides Kdenlive et les chapitres YouTube."""
    fcp_markers, guides, chapters_out = [], [], []

    def add(t_sec, label, guide_type):
        clip, src_f, tl_f = locate(keep_list, t_sec, fps)
        fcp_markers.append({"clip_id": clip["id"], "frame": src_f, "label": label})
        guides.append({"pos": tl_f, "comment": label, "type": guide_type})
        return tl_f

    for ch in decisions["chapters"]:
        tl_f = add(ch["start"], f"CHAPITRE : {ch['title']}", 0)
        chapters_out.append((tl_f, ch["title"]))
    for c in decisions["cuts"]:
        # Le marqueur tombe au point de raccord, juste après la coupe
        add(c["end"], f"COUPE IA : {c['reason']}", 2)
    for r in decisions["review"]:
        add(r["start"], f"À VÉRIFIER : {r['note']}", 1)

    guides.sort(key=lambda g: g["pos"])
    return fcp_markers, guides, sorted(chapters_out)


def write_youtube_chapters(chapters, fps: float, out_path: Path):
    lines = []
    for i, (tl_f, title) in enumerate(chapters):
        if i == 0:
            tl_f = 0  # YouTube exige que le premier chapitre commence à 0:00
        lines.append(f"{fmt_chapter_time(tl_f, fps)} {title}")
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    too_short = [
        chapters[i][1] for i in range(len(chapters) - 1)
        if (chapters[i + 1][0] - chapters[i][0]) / fps < 10
    ]
    if too_short:
        print(f"[Attention] Chapitres de moins de 10 s (refusés par YouTube) : {too_short}")


def run(decisions_path: Path, transcript_path: Path, keeplist_path: Path, review_path: Path,
        meta_path: Path, video_path: Path, output_dir: Path, export_format: str = "all",
        min_piece_sec: float = 0.30):
    decisions = load_json(decisions_path)
    raw_segments = load_json(transcript_path)
    keep_list = load_json(keeplist_path)
    review_flags = load_json(review_path) if review_path.exists() else {}
    width, height, fps, nb_frames, duration = step3_export.get_video_specs(meta_path, video_path)

    decisions["cuts"] = resolve_ranges(decisions.get("cuts", []), raw_segments)
    decisions["review"] = resolve_ranges(decisions.get("review", []), raw_segments)
    decisions["chapters"] = sorted(decisions.get("chapters", []), key=lambda c: c["start"])

    print("=" * 60)
    print("PHASE 4 : MONTAGE SÉMANTIQUE")
    print(f"Décisions : {len(decisions['cuts'])} coupes | {len(decisions['chapters'])} chapitres | "
          f"{len(decisions['review'])} points à vérifier")
    print("=" * 60)

    new_list = apply_cuts(keep_list, decisions["cuts"], fps, min_piece_sec)

    # Les gros silences de l'étape 3 gardent leur marqueur : on les replace sur les nouveaux clips
    gap_flags = []
    for g in review_flags.get("large_gaps_gt_6s", []):
        clip, _, _ = locate(new_list, g["end"], fps)
        gap_flags.append(dict(g, clip_id_after=clip["id"]))
    review_ia = dict(review_flags, large_gaps_gt_6s=gap_flags)

    fcp_markers, guides, chapters = build_markers(new_list, decisions, fps)

    output_dir.mkdir(parents=True, exist_ok=True)
    keeplist_ia = keeplist_path.with_name("keep_list_ia.json")
    keeplist_ia.write_text(json.dumps(new_list, indent=2, ensure_ascii=False), encoding="utf-8")

    if export_format in ("fcpxml", "all"):
        step3_export.generate_fcpxml(
            new_list, review_ia, source_path=video_path, output_path=output_dir / "montage_ia.fcpxml",
            width=width, height=height, fps=fps, total_source_frames=nb_frames, extra_markers=fcp_markers,
        )
    if export_format in ("kdenlive", "all"):
        step3_export.generate_kdenlive(
            new_list, source_path=video_path, output_path=output_dir / "montage_ia.kdenlive",
            width=width, height=height, fps=fps, total_source_frames=nb_frames, guides=guides,
        )
    if export_format in ("edl", "all"):
        step3_export.generate_edl(
            new_list, source_filename=video_path.name, output_path=output_dir / "montage_ia.edl", fps=fps,
        )

    yt_path = output_dir / "chapitres_youtube.txt"
    write_youtube_chapters(chapters, fps, yt_path)

    old_sec = sum(c["duration_frames"] for c in keep_list) / fps
    new_sec = sum(c["duration_frames"] for c in new_list) / fps
    print("\n--- RÉSULTAT PHASE 4 ---")
    print(f"Clips : {len(keep_list)} -> {len(new_list)}")
    print(f"Durée : {old_sec/60:.2f} min -> {new_sec/60:.2f} min ({old_sec - new_sec:.1f} s retirées)")
    print(f"Chapitres YouTube : {yt_path}")
    print(f"Keep-list IA      : {keeplist_ia}")
    return new_list


def main():
    parser = argparse.ArgumentParser(description="Étape 4 : montage sémantique à partir des décisions d'une IA.")
    parser.add_argument("--make-prompt", action="store_true", help="Écrit cache/semantic_prompt.md à donner à l'IA, puis s'arrête")
    parser.add_argument("--decisions", type=str, default="cache/semantic_decisions.json")
    parser.add_argument("--transcript", type=str, default="cache/transcript_raw.json")
    parser.add_argument("--compact", type=str, default="cache/compact_payload.txt")
    parser.add_argument("--keeplist", type=str, default="cache/keep_list.json")
    parser.add_argument("--review", type=str, default="cache/review_flags.json")
    parser.add_argument("--meta", type=str, default="cache/video_meta.json")
    parser.add_argument("--video", type=str, default="output/session_source.mp4")
    parser.add_argument("--output-dir", type=str, default="output")
    parser.add_argument("--format", choices=["fcpxml", "kdenlive", "edl", "all"], default="all")
    parser.add_argument("--min-piece", type=float, default=0.30, help="Supprime les restes de clip plus courts que X s après une coupe")
    args = parser.parse_args()

    if args.make_prompt:
        make_prompt(Path(args.compact), Path(args.compact).with_name("semantic_prompt.md"))
        return

    decisions_path = Path(args.decisions)
    if not decisions_path.exists():
        print(f"[ERREUR] {decisions_path} introuvable.")
        print("Lance d'abord : python step4_semantic.py --make-prompt, puis fais remplir ce fichier par une IA.")
        sys.exit(1)

    run(
        decisions_path=decisions_path,
        transcript_path=Path(args.transcript),
        keeplist_path=Path(args.keeplist),
        review_path=Path(args.review),
        meta_path=Path(args.meta),
        video_path=Path(args.video).resolve(),
        output_dir=Path(args.output_dir),
        export_format=args.format,
        min_piece_sec=args.min_piece,
    )


if __name__ == "__main__":
    main()
