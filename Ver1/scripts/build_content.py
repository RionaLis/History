#!/usr/bin/env python3
"""Build the static site's content-index.json from Obsidian-friendly Markdown notes.

Frontmatter uses a small, predictable YAML subset; JSON-quoted strings and JSON
flow arrays/maps are valid YAML and keep parsing dependency-free.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTENT = ROOT / "content"
OUTPUT = ROOT / "content-index.json"
EVENT_TYPES = {"states": "events", "science": "scienceEvents", "arts": "artEvents"}
ALLOWED_LEVELS = {"major", "regional", "minor"}
ALLOWED_MARKERS = {
    "society", "city", "state", "monument", "law", "war", "politics", "trade",
    "religion", "contact", "industry", "disaster", "treaty", "invention", "discovery",
    "text", "painting", "music", "event"
}


def parse_value(raw: str) -> Any:
    raw = raw.strip()
    if raw == "":
        return ""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        if len(raw) >= 2 and raw[0] == raw[-1] == "'":
            return raw[1:-1].replace("''", "'")
        if raw.startswith("#"):
            return ""
        return raw


def parse_note(path: Path) -> tuple[dict[str, Any], str] | None:
    text = path.read_text(encoding="utf-8-sig")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    try:
        end = next(i for i in range(1, len(lines)) if lines[i].strip() == "---")
    except StopIteration as exc:
        raise ValueError(f"{path.relative_to(ROOT)}: frontmatter is missing its closing ---") from exc
    metadata: dict[str, Any] = {}
    i = 1
    while i < end:
        line = lines[i]
        line_no = i + 1
        if not line.strip() or line.lstrip().startswith("#"):
            i += 1
            continue
        if line[:1].isspace():
            raise ValueError(f"{path.relative_to(ROOT)}:{line_no}: unexpected indented frontmatter line")
        key, sep, raw = line.partition(":")
        if not sep or not key.strip():
            raise ValueError(f"{path.relative_to(ROOT)}:{line_no}: expected key: value")
        key = key.strip()
        raw = raw.strip()
        i += 1
        if raw in {"|", "|-", ">", ">-", "|+", ">+"}:
            parts: list[str] = []
            while i < end and (not lines[i].strip() or lines[i][:1].isspace()):
                parts.append(lines[i].strip())
                i += 1
            metadata[key] = "\n".join(parts).strip() if raw.startswith("|") else " ".join(part for part in parts if part).strip()
            continue
        if raw == "":
            values: list[Any] = []
            lookahead = i
            while lookahead < end and not lines[lookahead].strip():
                lookahead += 1
            if lookahead < end and lines[lookahead].lstrip().startswith("-"):
                while i < end and (not lines[i].strip() or lines[i][:1].isspace()):
                    value_line = lines[i].strip()
                    if value_line.startswith("-"):
                        values.append(parse_value(value_line[1:].strip()))
                    elif value_line:
                        raise ValueError(f"{path.relative_to(ROOT)}:{i + 1}: block sequences may contain only scalar values")
                    i += 1
                metadata[key] = values
            else:
                metadata[key] = ""
            continue
        metadata[key] = parse_value(raw)
    body = "\n".join(lines[end + 1:]).strip()
    return metadata, body


def require(meta: dict[str, Any], key: str, note: Path) -> Any:
    value = meta.get(key)
    if value is None or value == "":
        raise ValueError(f"{note.relative_to(ROOT)}: required field '{key}' is missing")
    return value


def collect() -> dict[str, Any]:
    if not CONTENT.exists():
        raise ValueError("content/ folder is missing")
    parsed: list[tuple[Path, dict[str, Any], str]] = []
    for path in sorted(CONTENT.rglob("*.md")):
        if "templates" in path.relative_to(CONTENT).parts:
            continue
        parsed_note = parse_note(path)
        if parsed_note is None:
            # Allows ordinary Obsidian notes in content/ that are not site records.
            continue
        metadata, body = parsed_note
        if "type" not in metadata:
            continue
        parsed.append((path, metadata, body))

    settings_notes = [(p, m, b) for p, m, b in parsed if m.get("type") == "settings"]
    if len(settings_notes) != 1:
        raise ValueError(f"Expected exactly one settings note, found {len(settings_notes)}")
    _, settings, _ = settings_notes[0]

    data: dict[str, Any] = {
        "meta": {"start": int(require(settings, "timelineStart", settings_notes[0][0])), "end": int(require(settings, "timelineEnd", settings_notes[0][0]))},
        "stateTrackOrder": settings.get("stateTrackOrder", []),
        "rulerTrackOrder": settings.get("rulerTrackOrder", []),
        "personGroups": settings.get("personGroups", []),
        "personPalettes": settings.get("personPalettes", {}),
        "eras": [], "stateTracks": [], "scienceTracks": [], "artTracks": [], "rulerTracks": [],
        "events": [], "scienceEvents": [], "artEvents": [], "rulers": [], "persons": []
    }
    type_map = {
        "era": "eras", "stateTrack": "stateTracks", "scienceTrack": "scienceTracks",
        "artTrack": "artTracks", "rulerTrack": "rulerTracks", "ruler": "rulers", "person": "persons"
    }
    seen_ids: set[tuple[str, str]] = set()
    for path, original, body in parsed:
        note_type = original.get("type")
        if note_type in {"settings", None}:
            continue
        metadata = dict(original)
        metadata.pop("type", None)
        metadata["body"] = body
        if note_type == "event":
            require(metadata, "title", path)
            require(metadata, "summary", path)
            branch = require(metadata, "branch", path)
            if branch not in EVENT_TYPES:
                raise ValueError(f"{path.relative_to(ROOT)}: branch must be states, science, or arts")
            metadata["level"] = metadata.get("level", "major")
            if metadata["level"] not in ALLOWED_LEVELS:
                raise ValueError(f"{path.relative_to(ROOT)}: level must be one of {sorted(ALLOWED_LEVELS)}")
            metadata["kind"] = metadata.pop("display", metadata.get("kind", "event"))
            if metadata["kind"] not in ALLOWED_MARKERS:
                raise ValueError(f"{path.relative_to(ROOT)}: unsupported display marker '{metadata['kind']}'")
            metadata["year"] = int(require(metadata, "year", path))
            metadata["tags"] = metadata.get("tags", [])
            bucket = EVENT_TYPES[branch]
            object_id = str(require(metadata, "id", path))
        else:
            bucket = type_map.get(note_type)
            if bucket is None:
                raise ValueError(f"{path.relative_to(ROOT)}: unknown note type '{note_type}'")
            object_id = str(require(metadata, "id", path))
            if bucket == "rulers":
                require(metadata, "name", path)
                require(metadata, "title", path)
                require(metadata, "summary", path)
                metadata["start"] = int(require(metadata, "start", path))
                metadata["end"] = int(require(metadata, "end", path))
                if metadata["start"] > metadata["end"]:
                    raise ValueError(f"{path.relative_to(ROOT)}: ruler start must be <= end")
            if bucket == "persons":
                require(metadata, "name", path)
                require(metadata, "summary", path)
                require(metadata, "group", path)
                require(metadata, "polityKey", path)
                metadata["born"] = int(require(metadata, "born", path))
                metadata["died"] = int(require(metadata, "died", path))
                if metadata["born"] > metadata["died"]:
                    raise ValueError(f"{path.relative_to(ROOT)}: person born must be <= died")
                metadata["tags"] = metadata.get("tags", [])
            if bucket == "eras":
                require(metadata, "name", path)
                require(metadata, "summary", path)
                metadata["from"] = int(require(metadata, "from", path))
                metadata["to"] = int(require(metadata, "to", path))
                if metadata["from"] >= metadata["to"]:
                    raise ValueError(f"{path.relative_to(ROOT)}: era 'from' must be before 'to'")
            if bucket in {"stateTracks", "scienceTracks", "artTracks", "rulerTracks"}:
                require(metadata, "name", path)
                metadata["color"] = metadata.get("color", "#789084")
            if bucket == "stateTracks":
                metadata["periods"] = metadata.get("periods", [])
                if not isinstance(metadata["periods"], list):
                    raise ValueError(f"{path.relative_to(ROOT)}: periods must be a list")
                for period in metadata["periods"]:
                    if not isinstance(period, dict) or not period.get("name") or "from" not in period or "to" not in period:
                        raise ValueError(f"{path.relative_to(ROOT)}: each state period needs name, from, and to")
                    if int(period["from"]) >= int(period["to"]):
                        raise ValueError(f"{path.relative_to(ROOT)}: period 'from' must be before 'to'")
        if bucket in {"eras", "stateTracks", "scienceTracks", "artTracks", "rulerTracks", "rulers", "persons"}:
            unique_bucket = "all-event-branches" if note_type == "event" else bucket
            key = (unique_bucket, object_id)
            if key in seen_ids:
                raise ValueError(f"Duplicate {unique_bucket} id: {object_id}")
            seen_ids.add(key)
        data[bucket].append(metadata)

    # Keep chronological navigation predictable and validate every track reference.
    data["eras"].sort(key=lambda item: item["from"])
    state_track_ids = {item["id"] for item in data["stateTracks"]}
    science_track_ids = {item["id"] for item in data["scienceTracks"]}
    art_track_ids = {item["id"] for item in data["artTracks"]}
    ruler_track_ids = {item["id"] for item in data["rulerTracks"]}
    if set(data["stateTrackOrder"]) != state_track_ids:
        raise ValueError("settings.stateTrackOrder must list every state track ID exactly once")
    if set(data["rulerTrackOrder"]) != ruler_track_ids:
        raise ValueError("settings.rulerTrackOrder must list every ruler track ID exactly once")
    for bucket, allowed in (("events", state_track_ids), ("scienceEvents", science_track_ids), ("artEvents", art_track_ids)):
        for item in data[bucket]:
            if item.get("track") not in allowed:
                raise ValueError(f"{bucket}/{item.get('id')}: unknown track '{item.get('track')}'")
            if not data["meta"]["start"] <= item["year"] <= data["meta"]["end"]:
                raise ValueError(f"{bucket}/{item.get('id')}: year falls outside the timeline")
    for item in data["rulers"]:
        if item.get("track") not in ruler_track_ids:
            raise ValueError(f"rulers/{item.get('id')}: unknown ruler track '{item.get('track')}'")
    group_ids = {item.get("id") for item in data["personGroups"]}
    for item in data["persons"]:
        if item.get("group") not in group_ids:
            raise ValueError(f"persons/{item.get('id')}: unknown person group '{item.get('group')}'")

    if not data["stateTracks"] or not data["events"]:
        raise ValueError("At least one state track and one state event are required")
    return data


def main() -> int:
    try:
        data = collect()
        output = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        OUTPUT.write_text(output, encoding="utf-8")
        counts = {key: len(data[key]) for key in ("eras", "stateTracks", "events", "scienceEvents", "artEvents", "rulers", "persons")}
        print("Built content-index.json:", ", ".join(f"{key}={value}" for key, value in counts.items()))
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Content build failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
