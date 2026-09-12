"""
Person B's harness. Needs no transport and no console.

    python test_classifier.py

Green on all six fixtures means the classifier is done. Stop tuning and go help
with integration.
"""

from __future__ import annotations

import json
from pathlib import Path

from app.brain import classify
from app.state import new_negotiation

fixtures = json.loads(Path("fixtures/inbound_emails.json").read_text())
passed = 0

for case in fixtures:
    tier, reason, position = classify(new_negotiation(), case["body"])
    ok = tier.value == case["expect_tier"]
    passed += ok
    print(f"{'PASS' if ok else 'FAIL'}  expected={case['expect_tier']:<9} got={tier.value:<9} {reason[:60]}")

print(f"\n{passed}/{len(fixtures)} passed")
