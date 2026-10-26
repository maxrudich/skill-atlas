#!/usr/bin/env python3
"""Собирает docs/data.json и docs/index.html из реальных папок со скиллами и агентами
и из ручной кураторской записи catalog/curation.json.

    python3 scripts/sync.py            # собрать сайт
    python3 scripts/sync.py --check    # только проверить: чего нет в каталоге (код 1, если есть пробелы)

Только стандартная библиотека. Тела скиллов и промпты агентов на сайт не попадают:
берутся имя, описание из frontmatter и то, что написано в curation.json.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = Path(os.environ.get("ATLAS_SKILLS", Path.home() / "Documents/Claude/Skills"))
AGENTS_DIR = Path(os.environ.get("ATLAS_AGENTS", Path.home() / "Documents/Claude/Agents"))
CURATION = ROOT / "catalog" / "curation.json"
TEMPLATE = ROOT / "src" / "index.template.html"
OUT_DIR = ROOT / "docs"


def parse_frontmatter(text):
    """Минимальный разбор frontmatter: key: value, кавычки, складные блоки (> и >-, | и |-)."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*(\n|$)", text, re.S)
    if not m:
        return {}
    lines = m.group(1).split("\n")
    out, i = {}, 0
    while i < len(lines):
        line = lines[i]
        km = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not km:
            i += 1
            continue
        key, val = km.group(1), km.group(2).strip()
        if val in (">", ">-", "|", "|-", ">+", "|+"):
            block, i = [], i + 1
            while i < len(lines) and (lines[i].startswith(" ") or lines[i] == ""):
                block.append(lines[i].strip())
                i += 1
            out[key] = " ".join(b for b in block if b)
            continue
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[key] = val
        i += 1
    return out


def scan_skills():
    items = {}
    if not SKILLS_DIR.is_dir():
        return items
    for d in sorted(SKILLS_DIR.iterdir()):
        f = d / "SKILL.md"
        if not f.is_file():
            continue
        fm = parse_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
        name = fm.get("name") or d.name
        items[f"skill:{name}"] = {
            "kind": "skill",
            "name": name,
            "description": fm.get("description", ""),
        }
    return items


def scan_agents():
    items = {}
    if not AGENTS_DIR.is_dir():
        return items
    for f in sorted(AGENTS_DIR.glob("*.md")):
        fm = parse_frontmatter(f.read_text(encoding="utf-8", errors="replace"))
        name = fm.get("name") or f.stem
        items[f"agent:{name}"] = {
            "kind": "agent",
            "name": name,
            "description": fm.get("description", ""),
            "model": fm.get("model", ""),
            "tools": fm.get("tools", ""),
        }
    return items


def main():
    check_only = "--check" in sys.argv
    cur = json.loads(CURATION.read_text(encoding="utf-8"))
    found = {**scan_skills(), **scan_agents()}
    entries = cur.get("items", {})

    # встроенные команды Claude Code живут только в каталоге
    builtins = {k: v for k, v in entries.items() if k.startswith("command:")}

    missing = sorted(k for k in found if k not in entries)
    stale = sorted(k for k in entries if k not in found and not k.startswith("command:"))
    cats = {c["id"] for c in cur["categories"]}
    stacks = {s["id"] for s in cur["stacks"]}
    bad = []
    for k, e in entries.items():
        if e.get("cat") not in cats:
            bad.append(f"{k}: неизвестная категория {e.get('cat')!r}")
        for s in e.get("for", []):
            if s not in stacks:
                bad.append(f"{k}: неизвестный тип проекта {s!r}")
    all_keys = set(found) | set(builtins)
    for pb in cur.get("playbooks", []):
        for step in pb["steps"]:
            if step["ref"] not in all_keys:
                bad.append(f"плейбук {pb['id']}: нет {step['ref']}")
    for g in cur.get("compare", []):
        for row in g["rows"]:
            if row["ref"] not in all_keys:
                bad.append(f"сравнение {g['id']}: нет {row['ref']}")

    if missing:
        print("Нет в curation.json (добавь запись по образцу, потом повтори):")
        for k in missing:
            print("  +", k)
    if stale:
        print("В curation.json есть, а в папках уже нет (удали запись):")
        for k in stale:
            print("  -", k)
    for b in bad:
        print("Ошибка:", b)
    if missing or stale or bad:
        if check_only or missing or bad:
            sys.exit(1)

    if check_only:
        print(f"ок: {len(found)} в папках, {len(builtins)} встроенных команд")
        return

    items = []
    for key in sorted(all_keys):
        base = found.get(key, {"kind": "command", "name": key.split(":", 1)[1], "description": ""})
        e = entries[key]
        item = {"id": key, **base, **{k: v for k, v in e.items()}}
        items.append(item)

    data = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "categories": cur["categories"],
        "stacks": cur["stacks"],
        "playbooks": cur.get("playbooks", []),
        "compare": cur.get("compare", []),
        "items": items,
    }
    OUT_DIR.mkdir(exist_ok=True)
    payload = json.dumps(data, ensure_ascii=False, indent=1)
    (OUT_DIR / "data.json").write_text(payload, encoding="utf-8")
    html = TEMPLATE.read_text(encoding="utf-8")
    inline = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    html = html.replace("/*__DATA__*/null", inline)
    (OUT_DIR / "index.html").write_text(html, encoding="utf-8")
    (OUT_DIR / ".nojekyll").write_text("", encoding="utf-8")
    n = {k: sum(1 for i in items if i["kind"] == k) for k in ("skill", "agent", "command")}
    print(f"собрано: {n['skill']} скиллов, {n['agent']} агентов, {n['command']} команд -> docs/")


if __name__ == "__main__":
    main()
