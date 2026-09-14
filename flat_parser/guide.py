from __future__ import annotations

import json
import re
from pathlib import Path

from .textnorm import fold


class UniversalGuide:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.data = json.loads(self.path.read_text(encoding="utf-8"))
        self.patterns = {p["id"]: p for p in self.data["patterns"]}
        self.selection_order = self.data["selection_order"]
        self.field_patterns = self.data["field_patterns"]
        self.named_attribute_keys = {
            fold(x) for x in self.data.get("named_attribute_keys", [])
        }

        self.period_forms = {
            fold(x)
            for x in self.field_patterns.get("period", {}).get("observed_forms", [])
        }
        self.qualifier_forms = {
            fold(x.rstrip(":"))
            for x in self.field_patterns.get("qualifier", {}).get("observed_forms", [])
        }

        self.period_regexes = self._compile_regexes("period")
        self.value_regexes = self._compile_regexes("value")
        self.unit_regexes = self._compile_regexes("unit")
        self.note_regexes = self._compile_regexes("note")

    def _compile_regexes(self, category: str):
        result = []
        for p in self.field_patterns.get(category, {}).get("patterns", []):
            regex = p.get("regex")
            if not regex:
                continue
            try:
                result.append((p.get("name", "unnamed"), re.compile(regex)))
            except re.error:
                pass
        return result
