from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from flat_parser.guide_compiler import write_compiled_guide

write_compiled_guide(
    ROOT / 'resources/guides',
    ROOT / 'resources/universal_structural_guide_a1_a5.json',
)
print(ROOT / 'resources/universal_structural_guide_a1_a5.json')
