#!/usr/bin/env bash
# Пересобрать каталог из папок со скиллами и агентами, закоммитить и выложить.
set -euo pipefail
cd "$(dirname "$0")"
python3 scripts/sync.py
git add -A
if git diff --cached --quiet; then echo "Без изменений"; exit 0; fi
git commit -q -m "Обновить каталог: $(date +%F)"
if git remote get-url origin >/dev/null 2>&1; then git push -q && echo "Выложено"; else echo "Коммит сделан локально, origin не настроен"; fi
