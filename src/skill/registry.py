"""Skill registry：两种格式都支持。

格式 1：单文件 YAML
    skills/foo.yaml                              # 简单 skill，frame-bg-remover 用

格式 2：manifest + 外部 SKILL.md（同事维护 SKILL.md，我们不动）
    src/skill_manifests/foo.yaml                 # 我们维护的 manifest（含 API 契约 + skill_md_path）
    skills/foo-skill/SKILL.md                    # 同事维护的对话规则
    skills/foo-skill/references/*                # 同事维护的资源

加载流程：
  - 扫 skills/*.yaml → 简单 skill
  - 扫 src/skill_manifests/*.yaml → 复杂 skill，按 manifest 里的 skill_md_path 加载 SKILL.md 作 system_prompt_core
"""
import yaml
from pathlib import Path
from src.skill.schema import Skill

_PROJECT_ROOT = Path(__file__).parent.parent.parent
_SIMPLE_SKILLS_DIR = _PROJECT_ROOT / "skills"
_MANIFESTS_DIR = _PROJECT_ROOT / "src" / "skill_manifests"
_registry: dict[str, Skill] = {}


def _ensure_api_type(raw: dict) -> dict:
    """向后兼容：YAML 没写 api.type 默认 'http'。"""
    if "api" in raw and "type" not in raw["api"]:
        raw["api"]["type"] = "http"
    return raw


def _load_simple_skill(path: Path) -> Skill:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Skill.model_validate(_ensure_api_type(raw))


def _load_manifest_skill(manifest_path: Path) -> Skill:
    raw = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    skill_md_relpath = raw.pop("skill_md_path", None)
    if skill_md_relpath:
        skill_md = (_PROJECT_ROOT / skill_md_relpath).read_text(encoding="utf-8")
        raw["system_prompt_core"] = skill_md
    return Skill.model_validate(_ensure_api_type(raw))


def load_skills() -> dict[str, Skill]:
    skills: dict[str, Skill] = {}

    if _SIMPLE_SKILLS_DIR.exists():
        for path in _SIMPLE_SKILLS_DIR.glob("*.yaml"):
            skill = _load_simple_skill(path)
            skills[skill.name] = skill

    if _MANIFESTS_DIR.exists():
        for path in _MANIFESTS_DIR.glob("*.yaml"):
            skill = _load_manifest_skill(path)
            skills[skill.name] = skill

    return skills


def get_registry() -> dict[str, Skill]:
    global _registry
    if not _registry:
        _registry = load_skills()
    return _registry


def reset_registry() -> None:
    global _registry
    _registry = {}
