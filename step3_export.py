#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Étape 3B : Export de la Timeline non-destructive vers FCPXML v1.9 et EDL CMX3600.
Compatible DaVinci Resolve, Kdenlive, Premiere Pro, Final Cut Pro.
"""

import argparse
import json
import subprocess
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from xml.dom import minidom
from xml.sax.saxutils import escape as xml_escape


def get_video_specs(meta_path: Path, video_path: Path = None):
    """Récupère fps, total_frames, duration, width, height."""
    width, height = 1920, 1080
    fps = 30.0
    duration = 3854.233
    nb_frames = 115627

    if meta_path and meta_path.exists():
        try:
            with open(meta_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
                width = int(meta.get("width", 1920))
                height = int(meta.get("height", 1080))
                fps = float(meta.get("fps", 30.0))
                duration = float(meta.get("duration", 3854.233))
                nb_frames = int(meta.get("nb_frames", round(duration * fps)))
                return width, height, fps, nb_frames, duration
        except Exception:
            pass

    if video_path and video_path.exists():
        try:
            cmd = [
                "ffprobe", "-v", "error",
                "-select_streams", "v:0",
                "-show_entries", "stream=width,height,r_frame_rate,nb_frames,duration:format=duration",
                "-of", "json",
                str(video_path.resolve())
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            data = json.loads(res.stdout)
            st = data.get("streams", [{}])[0]
            fmt = data.get("format", {})
            width = int(st.get("width", 1920))
            height = int(st.get("height", 1080))
            r_fps = st.get("r_frame_rate", "30/1")
            fps = float(Fraction(r_fps))
            dur_str = st.get("duration") or fmt.get("duration")
            duration = float(dur_str) if dur_str else 3854.233
            nb_frames = int(st.get("nb_frames", round(duration * fps)))
            return width, height, fps, nb_frames, duration
        except Exception:
            pass

    return width, height, fps, nb_frames, duration


def frames_to_tc(frames: int, fps: float = 30.0) -> str:
    """Convertit un nombre de frames en timecode Non-Drop Frame HH:MM:SS:FF."""
    int_fps = int(round(fps))
    f = int(frames)
    ff = f % int_fps
    total_seconds = f // int_fps
    ss = total_seconds % 60
    total_minutes = total_seconds // 60
    mm = total_minutes % 60
    hh = total_minutes // 60
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def generate_fcpxml(keep_list, review_flags, source_path: Path, output_path: Path,
                    width: int = 1920, height: int = 1080, fps: float = 30.0, total_source_frames: int = 115627,
                    extra_markers=None):
    """Génère un export FCPXML v1.9 valide et non-destructif.

    extra_markers : liste optionnelle de {"clip_id", "frame", "label"} (frame = temps source),
    utilisée par la phase 4 pour poser chapitres, coupes IA et points à vérifier.
    """
    int_fps = int(round(fps))
    total_kept_frames = sum(clip["duration_frames"] for clip in keep_list)
    media_uri = source_path.resolve().as_uri()

    # Mapping clip_id -> list of gap markers to insert
    gap_markers_by_clip = {}
    for gap in review_flags.get("large_gaps_gt_6s", []):
        clip_after = gap.get("clip_id_after")
        if clip_after is not None:
            gap_markers_by_clip.setdefault(clip_after, []).append(gap)

    extra_by_clip = {}
    for m in extra_markers or []:
        extra_by_clip.setdefault(m["clip_id"], []).append(m)

    fcpxml = ET.Element("fcpxml", version="1.9")

    # <resources>
    resources = ET.SubElement(fcpxml, "resources")
    ET.SubElement(
        resources,
        "format",
        id="r1",
        name=f"FFVideoFormat{height}p{int_fps}",
        frameDuration=f"1/{int_fps}s",
        width=str(width),
        height=str(height),
    )
    asset = ET.SubElement(
        resources,
        "asset",
        id="r2",
        name=source_path.name,
        uid=f"{source_path.stem}_asset",
        src=media_uri,
        start="0s",
        duration=f"{total_source_frames}/{int_fps}s",
        hasVideo="1",
        format="r1",
        hasAudio="1",
        audioSources="1",
        audioChannels="2",
        audioRate="48000",
    )
    ET.SubElement(asset, "media-rep", kind="original-media", src=media_uri)

    # <library> -> <event> -> <project> -> <sequence> -> <spine>
    library = ET.SubElement(fcpxml, "library")
    event = ET.SubElement(library, "event", name="Montage Poker")
    project = ET.SubElement(event, "project", name="Montage Auto")
    sequence = ET.SubElement(
        project,
        "sequence",
        format="r1",
        duration=f"{total_kept_frames}/{int_fps}s",
        tcStart="0s",
        tcFormat="NDF",
    )
    spine = ET.SubElement(sequence, "spine")

    cumulative_offset_frames = 0

    for clip in keep_list:
        c_id = clip["id"]
        start_f = clip["start_frame"]
        dur_f = clip["duration_frames"]

        asset_clip = ET.SubElement(
            spine,
            "asset-clip",
            ref="r2",
            offset=f"{cumulative_offset_frames}/{int_fps}s",
            name=source_path.stem,
            start=f"{start_f}/{int_fps}s",
            duration=f"{dur_f}/{int_fps}s",
            format="r1",
            tcFormat="NDF",
        )

        # Insertion des marqueurs si ce clip fait suite à un trou >= 6s
        if c_id in gap_markers_by_clip:
            for g in gap_markers_by_clip[c_id]:
                ET.SubElement(
                    asset_clip,
                    "marker",
                    start=f"{start_f}/{int_fps}s",
                    duration=f"1/{int_fps}s",
                    value=f"GAP {g['duration']}s coupé",
                )

        for m in extra_by_clip.get(c_id, []):
            ET.SubElement(
                asset_clip,
                "marker",
                start=f"{m['frame']}/{int_fps}s",
                duration=f"1/{int_fps}s",
                value=m["label"],
            )

        cumulative_offset_frames += dur_f

    # Pretty-print
    xml_str = ET.tostring(fcpxml, encoding="utf-8")
    dom = minidom.parseString(xml_str)
    pretty_lines = dom.toprettyxml(indent="  ", encoding="utf-8").decode("utf-8").splitlines()
    final_lines = [
        pretty_lines[0],
        '<!DOCTYPE fcpxml>',
    ]
    final_lines.extend([line for line in pretty_lines[1:] if line.strip()])
    final_xml = "\n".join(final_lines) + "\n"

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_xml)

    # Validation
    parsed_tree = ET.parse(output_path)
    seq_elem = parsed_tree.find(".//sequence")
    assert seq_elem is not None, "Élément <sequence> introuvable dans FCPXML !"
    assert seq_elem.get("duration") == f"{total_kept_frames}/{int_fps}s", "Durée séquence incohérente !"
    print(f"FCPXML validé avec succès : {output_path} ({total_kept_frames} frames / {total_kept_frames/int_fps:.2f}s)")


def generate_kdenlive(keep_list, source_path: Path, output_path: Path,
                      width: int = 1920, height: int = 1080, fps: float = 30.0, total_source_frames: int = 115627,
                      guides=None):
    """Génère un projet XML Kdenlive (.kdenlive) natif basé sur le moteur MLT.

    guides : liste optionnelle de {"pos": frame_timeline, "comment": str, "type": int}
    affichés comme guides dans la timeline Kdenlive.
    """
    int_fps = int(round(fps))
    source_mp4 = str(source_path.resolve()).replace("\\", "/")
    root_dir = str(output_path.parent.resolve()).replace("\\", "/")
    total_kept_frames = sum(c["duration_frames"] for c in keep_list)
    guides_json = xml_escape(json.dumps(guides or [], ensure_ascii=False), {'"': "&quot;"})

    xml_lines = [
        '<?xml version="1.0" encoding="utf-8"?>',
        f'<mlt LC_NUMERIC="C" version="7.26.0" root="{root_dir}" title="Montage Auto Poker">',
        '  <property name="kdenlive:docproperties.version">1.1</property>',
        '  <property name="kdenlive:docproperties.kdenliveversion">24.08.0</property>',
        f'  <property name="kdenlive:docproperties.profile">atsc_{height}p_{int_fps}</property>',
        '  <property name="kdenlive:docproperties.decimalPoint">.</property>',
        '  <property name="kdenlive:docproperties.audioChannels">2</property>',
        '  <property name="kdenlive:docproperties.audioFreq">48000</property>',
        '  <property name="kdenlive:docproperties.groups">[]</property>',
        f'  <property name="kdenlive:docproperties.guides">{guides_json}</property>',
        f'  <profile description="{height}p {int_fps} fps" width="{width}" height="{height}" progressive="1" sample_aspect_num="1" sample_aspect_den="1" display_aspect_num="16" display_aspect_den="9" frame_rate_num="{int_fps}" frame_rate_den="1" colorspace="709"/>',
        f'  <producer id="producer0" in="0" out="{total_source_frames - 1}">',
        f'    <property name="length">{total_source_frames}</property>',
        '    <property name="eof">pause</property>',
        f'    <property name="resource">{source_mp4}</property>',
        '    <property name="audio_index">1</property>',
        '    <property name="video_index">0</property>',
        '    <property name="mute_on_pause">0</property>',
        '    <property name="mlt_service">avformat</property>',
        '  </producer>',
        '  <playlist id="playlist0">'
    ]

    for c in keep_list:
        s_f = c["start_frame"]
        e_f = c["end_frame"] - 1
        xml_lines.append(f'    <entry producer="producer0" in="{s_f}" out="{e_f}"/>')

    xml_lines.extend([
        '  </playlist>',
        f'  <tractor id="tractor0" title="Montage Auto" in="0" out="{total_kept_frames - 1}">',
        f'    <property name="kdenlive:sequenceproperties.guides">{guides_json}</property>',
        '    <track producer="playlist0"/>',
        '  </tractor>',
        '</mlt>'
    ])

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(xml_lines) + "\n")
    print(f"Projet Kdenlive généré avec succès : {output_path} ({len(keep_list)} clips)")


def generate_edl(keep_list, source_filename: str, output_path: Path, fps: float = 30.0):
    """Génère une EDL CMX3600 standard Non-Drop Frame avec AA/V."""
    lines = [
        "TITLE: Montage Auto",
        "FCM: NON-DROP FRAME",
        "",
    ]

    record_in_frames = 0

    for idx, clip in enumerate(keep_list, start=1):
        src_in = clip["start_frame"]
        src_out = clip["end_frame"]
        dur = clip["duration_frames"]
        rec_in = record_in_frames
        rec_out = record_in_frames + dur

        src_in_tc = frames_to_tc(src_in, fps)
        src_out_tc = frames_to_tc(src_out, fps)
        rec_in_tc = frames_to_tc(rec_in, fps)
        rec_out_tc = frames_to_tc(rec_out, fps)

        event_line = f"{idx:03d}  SESSION  AA/V  C        {src_in_tc} {src_out_tc} {rec_in_tc} {rec_out_tc}"
        clip_name_line = f"* FROM CLIP NAME: {source_filename}"

        lines.append(event_line)
        lines.append(clip_name_line)
        lines.append("")

        record_in_frames = rec_out

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"EDL générée avec succès : {output_path} ({len(keep_list)} événements)")


def compute_statistics(keep_list, review_flags, video_duration_sec: float):
    """Calcule toutes les métriques requises par le protocole."""
    total_kept_sec = sum(c["duration"] for c in keep_list)
    total_cut_sec = max(0.0, video_duration_sec - total_kept_sec)
    kept_pct = (total_kept_sec / video_duration_sec) * 100 if video_duration_sec else 0
    cut_pct = (total_cut_sec / video_duration_sec) * 100 if video_duration_sec else 0

    gaps = []
    if keep_list and keep_list[0]["start"] > 0:
        gaps.append({"start": 0.0, "end": keep_list[0]["start"], "duration": keep_list[0]["start"]})
    for i in range(len(keep_list) - 1):
        g_dur = keep_list[i + 1]["start"] - keep_list[i]["end"]
        if g_dur > 0:
            gaps.append({
                "start": keep_list[i]["end"],
                "end": keep_list[i + 1]["start"],
                "duration": round(g_dur, 4),
            })
    if keep_list and keep_list[-1]["end"] < video_duration_sec:
        gaps.append({
            "start": keep_list[-1]["end"],
            "end": video_duration_sec,
            "duration": round(video_duration_sec - keep_list[-1]["end"], 4),
        })

    lt_1 = sum(1 for g in gaps if g["duration"] < 1.0)
    b_1_3 = sum(1 for g in gaps if 1.0 <= g["duration"] < 3.0)
    b_3_6 = sum(1 for g in gaps if 3.0 <= g["duration"] < 6.0)
    gt_6 = sum(1 for g in gaps if g["duration"] >= 6.0)

    longest_gaps = sorted(gaps, key=lambda x: x["duration"], reverse=True)[:10]

    return {
        "video_duration_sec": video_duration_sec,
        "total_kept_sec": total_kept_sec,
        "total_cut_sec": total_cut_sec,
        "kept_pct": kept_pct,
        "cut_pct": cut_pct,
        "gaps_count": len(gaps),
        "distrib": {"<1s": lt_1, "1-3s": b_1_3, "3-6s": b_3_6, ">=6s": gt_6},
        "longest_gaps": longest_gaps,
    }


def main():
    parser = argparse.ArgumentParser(description="Étape 3B : Export FCPXML et EDL.")
    parser.add_argument("--keeplist", "-k", type=str, default="cache/keep_list.json", help="Chemin du keep_list.json")
    parser.add_argument("--review", "-r", type=str, default="cache/review_flags.json", help="Chemin du review_flags.json")
    parser.add_argument("--meta", "-m", type=str, default="cache/video_meta.json", help="Chemin des métadonnées vidéo")
    parser.add_argument("--video", "-v", type=str, default="output/session_source.mp4", help="Chemin de la vidéo source")
    parser.add_argument("--output-fcpxml", type=str, default="output/montage_auto.fcpxml", help="Chemin du fichier FCPXML")
    parser.add_argument("--output-kdenlive", type=str, default="output/montage_auto.kdenlive", help="Chemin du fichier projet Kdenlive")
    parser.add_argument("--output-edl", type=str, default="output/montage_auto.edl", help="Chemin du fichier EDL")
    parser.add_argument("--format", choices=["fcpxml", "kdenlive", "edl", "all"], default="all", help="Format(s) d'export")
    args = parser.parse_args()

    keeplist_path = Path(args.keeplist).resolve()
    review_path = Path(args.review).resolve()
    meta_path = Path(args.meta).resolve()
    video_path = Path(args.video).resolve()
    fcpxml_path = Path(args.output_fcpxml).resolve()
    kdenlive_path = Path(args.output_kdenlive).resolve()
    edl_path = Path(args.output_edl).resolve()

    if not keeplist_path.exists():
        print(f"[ERREUR] {keeplist_path} est introuvable. Exécutez d'abord step3_keeplist.py.")
        return

    with open(keeplist_path, "r", encoding="utf-8") as f:
        keep_list = json.load(f)

    review_flags = {}
    if review_path.exists():
        with open(review_path, "r", encoding="utf-8") as f:
            review_flags = json.load(f)

    width, height, fps, nb_frames, duration = get_video_specs(meta_path, video_path)

    print("=" * 60)
    print("PHASE 3B : EXPORT DE LA TIMELINE NON-DESTRUCTIVE")
    print(f"Vidéo cible : {video_path.name}")
    print(f"Dimensions : {width}x{height} | FPS : {fps} | Clés frames : {nb_frames}")
    print("=" * 60)

    if args.format in ("fcpxml", "all"):
        generate_fcpxml(
            keep_list, review_flags,
            source_path=video_path,
            output_path=fcpxml_path,
            width=width, height=height, fps=fps, total_source_frames=nb_frames
        )

    if args.format in ("kdenlive", "all"):
        generate_kdenlive(
            keep_list,
            source_path=video_path,
            output_path=kdenlive_path,
            width=width, height=height, fps=fps, total_source_frames=nb_frames
        )

    if args.format in ("edl", "all"):
        generate_edl(
            keep_list,
            source_filename=video_path.name,
            output_path=edl_path,
            fps=fps
        )

    stats = compute_statistics(keep_list, review_flags, duration)
    kept_m = int(stats["total_kept_sec"] // 60)
    kept_s = int(stats["total_kept_sec"] % 60)
    cut_m = int(stats["total_cut_sec"] // 60)
    cut_s = int(stats["total_cut_sec"] % 60)

    print("\n--- STATISTIQUES FINALES DU DÉCOUPAGE ---")
    print(f"Total clips : {len(keep_list)}")
    print(f"Durée conservée : {kept_m:02d}m{kept_s:02d}s ({stats['total_kept_sec']:.2f}s, {stats['kept_pct']:.2f}%)")
    print(f"Durée purgée    : {cut_m:02d}m{cut_s:02d}s ({stats['total_cut_sec']:.2f}s, {stats['cut_pct']:.2f}%)")
    print(f"Distribution des trous retirés ({stats['gaps_count']} coupures) :")
    for k, v in stats["distrib"].items():
        print(f"  {k} : {v}")

    print("\nTop 10 des plus longs silences purgés :")
    for idx, g in enumerate(stats["longest_gaps"], start=1):
        print(f"  {idx:02d}. {g['start']:.2f}s -> {g['end']:.2f}s (durée: {g['duration']:.2f}s)")


if __name__ == "__main__":
    main()
