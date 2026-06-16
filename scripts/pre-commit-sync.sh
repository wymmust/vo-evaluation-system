#!/bin/bash
# Pre-commit hook: sync static_web/py/evaluator.py with vo_eval/evaluator.py
# Ensures the Pyodide browser deployment copy stays consistent with the source.
#
# Install: ln -s ../../scripts/pre-commit-sync.sh .git/hooks/pre-commit

SRC="vo_eval/evaluator.py"
DST="static_web/py/evaluator.py"

# Only run if the source evaluator was modified
if git diff --cached --name-only | grep -q "^${SRC}$"; then
    echo "Syncing ${SRC} → ${DST} ..."
    cp "${SRC}" "${DST}"
    git add "${DST}"
    echo "Done: ${DST} synced and added to commit."
fi