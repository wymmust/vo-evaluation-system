#!/bin/bash
# Pre-commit hook: sync static_web/py/vo_eval modules with vo_eval modules
# Ensures the Pyodide browser deployment copy stays consistent with the source.
#
# Install: ln -s ../../scripts/pre-commit-sync.sh .git/hooks/pre-commit

MODULES="data_loader.py utils.py report.py processing.py"

# Only run if one of the source modules was modified
if git diff --cached --name-only | grep -q "^vo_eval/\\(data_loader\\|utils\\|report\\|processing\\)\\.py$"; then
    mkdir -p static_web/py/vo_eval
    : > static_web/py/vo_eval/__init__.py
    for MODULE in ${MODULES}; do
        SRC="vo_eval/${MODULE}"
        DST="static_web/py/vo_eval/${MODULE}"
        echo "Syncing ${SRC} → ${DST} ..."
        cp "${SRC}" "${DST}"
        git add "${DST}"
    done
    git add static_web/py/vo_eval/__init__.py
    echo "Done: static web vo_eval modules synced and added to commit."
fi
