import yaml
from pathlib import Path
from src.skill.schema import Skill

_SKILLS_DIR = Path(__file__).parent.parent.parent / "skills"
_registry: dict[str, Skill] = {}


def load_skills() -> dict[str, Skill]:
    skills: dict[str, Skill] = {}
    for path in _SKILLS_DIR.glob("*.yaml"):
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        skill = Skill.model_validate(raw)
        skills[skill.name] = skill
    return skills


def get_registry() -> dict[str, Skill]:
    global _registry
    if not _registry:
        _registry = load_skills()
    return _registry
