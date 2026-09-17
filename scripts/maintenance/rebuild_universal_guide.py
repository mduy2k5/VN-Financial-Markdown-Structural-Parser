from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from flat_parser.guide_compiler import write_compiled_guide

write_compiled_guide(
    ROOT / 'resources/guides',
    ROOT / 'resources/guides/compiled/structural_guide.json',
)
print(ROOT / 'resources/guides/compiled/structural_guide.json')
