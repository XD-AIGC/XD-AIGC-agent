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

    # lazy_resources：字符串当文件路径转绝对；dict 是 HttpResource 配置，原样传
    # HTTP 类型的 URL 自动加入 agent HTTP 白名单（注册时一次性）
    if "lazy_resources" in raw:
        transformed = {}
        for k, v in raw["lazy_resources"].items():
            if isinstance(v, str):
                transformed[k] = str(skill_dir / v)
            elif isinstance(v, dict):
                transformed[k] = v
                if v.get("type") == "http" and "url" in v:
                    _register_http_resource_url(v["url"])
            else:
                log.warning(f"skill {skill_dir.name} lazy_resources[{k}] 未知类型: {type(v).__name__}")
        raw["lazy_resources"] = transformed

    # api.base_url：每个 skill 可指定独立后端地址（如 toolbox 子工具的专属端口）
    # 必须也加入 HTTP 白名单，否则 executor 调 submit/poll 会被 allowlist 拦截
    api_section = raw.get("api") or {}
    if isinstance(api_section, dict) and api_section.get("base_url"):
        _register_http_resource_url(api_section["base_url"])

    return Skill.model_validate(_ensure_api_type(raw))


def _register_http_resource_url(url: str) -> None:
    """把 HTTP 资源的 host+port 加入 agent 出站白名单。"""
    from urllib.parse import urlparse
    from src.http_client.allowlist import register_allowed_prefix

    parsed = urlparse(url)
    if parsed.scheme and parsed.netloc:
        register_allowed_prefix(f"{parsed.scheme}://{parsed.netloc}")


def load_skills() -> dict[str, Skill]:
    """递归扫 SKILLS_DIR 所有 manifest.yaml（支持 <project>/<skill>/manifest.yaml 多级结构）。"""
    skills: dict[str, Skill] = {}
    skills_root = Path(SKILLS_DIR)
    if not skills_root.exists():
        log.warning(f"SKILLS_DIR 不存在: {skills_root}")
        return skills
    for manifest_path in sorted(skills_root.rglob("manifest.yaml")):
        # 跳过 .git 等隐藏目录
        if any(part.startswith(".") for part in manifest_path.parts):
            continue
        skill_dir = manifest_path.parent
        try:
            skill = _load_skill_dir(skill_dir)
        except Exception as e:
            log.warning(f"skill {skill_dir} 加载失败: {e}")
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
