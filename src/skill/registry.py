"""Skill registry：从 SKILLS_DIR 扫描，每个 skill 一个目录 + manifest.yaml。

新结构（与 https://github.com/XD-AIGC/XD-AIGC-skills 对齐）：

    SKILLS_DIR/
    ├── xd-poster-gen/
    │   ├── manifest.yaml       ← 必有，agent 加载凭这个
    │   ├── SKILL.md            ← 可选，complex skill 用
    │   ├── references/         ← 可选，lazy_resources 引用
    │   └── assets/             ← 可选，agent 不读
    └── frame-bg-remover/
        └── manifest.yaml       ← simple skill，没 SKILL.md

manifest 内所有路径（skill_md_path / lazy_resources.*）都相对 manifest 所在目录。

无 manifest.yaml 的目录（如同事的 Claude Code skill）被跳过，agent 看不到。
"""
import logging
from pathlib import Path

import yaml

from src.config import SKILLS_DIR
from src.skill.schema import Skill

log = logging.getLogger(__name__)

_registry: dict[str, Skill] = {}


def _ensure_api_type(raw: dict) -> dict:
    """向后兼容：YAML 没写 api.type 默认 'http'。"""
    if "api" in raw and "type" not in raw["api"]:
        raw["api"]["type"] = "http"
    return raw


def _load_skill_dir(skill_dir: Path) -> Skill | None:
    """从一个 skill 目录加载 manifest.yaml + 同目录 SKILL.md（可选）+ 解析路径。"""
    manifest = skill_dir / "manifest.yaml"
    if not manifest.exists():
        return None  # 无 manifest 的目录跳过（如 Claude Code skill）
    raw = yaml.safe_load(manifest.read_text(encoding="utf-8"))

    skill_md_relpath = raw.pop("skill_md_path", None)
    if skill_md_relpath:
        skill_md = (skill_dir / skill_md_relpath).read_text(encoding="utf-8")
        raw["system_prompt_core"] = skill_md

    # lazy_resources 路径转成绝对路径（agent 加载时直接 read_text）
    if "lazy_resources" in raw:
        raw["lazy_resources"] = {
            k: str(skill_dir / v) for k, v in raw["lazy_resources"].items()
        }

    return Skill.model_validate(_ensure_api_type(raw))


def load_skills() -> dict[str, Skill]:
    """扫 SKILLS_DIR 所有子目录，找到 manifest.yaml 就加载。"""
    skills: dict[str, Skill] = {}
    skills_root = Path(SKILLS_DIR)
    if not skills_root.exists():
        log.warning(f"SKILLS_DIR 不存在: {skills_root}")
        return skills
    for skill_dir in sorted(skills_root.iterdir()):
        if not skill_dir.is_dir():
            continue
        try:
            skill = _load_skill_dir(skill_dir)
        except Exception as e:
            log.warning(f"skill {skill_dir.name} 加载失败: {e}")
            continue
        if skill is not None:
            skills[skill.name] = skill
            log.info(f"[REGISTRY] loaded skill={skill.name} from {skill_dir}")
    return skills


def get_registry() -> dict[str, Skill]:
    global _registry
    if not _registry:
        _registry = load_skills()
    return _registry


def reload_registry() -> dict[str, Skill]:
    """强制重新扫描 + 重建 registry（给文件 watcher hot-reload 用）。"""
    global _registry
    _registry = load_skills()
    log.info(f"[REGISTRY] reloaded, {len(_registry)} skills: {list(_registry.keys())}")
    return _registry


def reset_registry() -> None:
    """测试用：清空 registry 让下次 get_registry() 重新加载。"""
    global _registry
    _registry = {}
