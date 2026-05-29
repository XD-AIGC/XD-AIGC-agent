"""测试 registry 从 SKILLS_DIR 扫描的行为。

不依赖真实 skills 文件（已迁到独立仓库），用 tmp_path 造 fixture。
"""
from pathlib import Path

from src.skill.registry import load_skills, reload_registry, reset_registry
from src.skill.schema import Skill


def _make_skill_dir(parent, name: str, manifest_content: str, skill_md: str = None):
    skill_dir = parent / name
    skill_dir.mkdir()
    (skill_dir / "manifest.yaml").write_text(manifest_content, encoding="utf-8")
    if skill_md:
        (skill_dir / "SKILL.md").write_text(skill_md, encoding="utf-8")
    return skill_dir


SIMPLE_MANIFEST = """\
name: test-simple
description: simple test skill
api:
  type: http
  endpoint_path: /api/x
  method: POST
  content_type: multipart/form-data
params:
  - name: image
    type: image
    required: true
    prompt_to_user: 请上传
output:
  type: image_binary
  display_as: feishu_image
"""

COMPLEX_MANIFEST = """\
name: test-complex
description: complex test skill
skill_md_path: SKILL.md
api:
  type: poll
  submit_path: /api/submit
  poll_path_template: /api/poll/{job_id}
  result_path: images[0].url
params: []
output:
  type: image_url
  display_as: feishu_image
lazy_resources:
  lookup_x: references/x.tsv
"""

ACTION_SCHEMA_MANIFEST = """\
name: test-action-schema
description: action schema test skill
skill_md_path: SKILL.md
api:
  type: http
  endpoint_path: /api/submit
  method: POST
  content_type: application/json
params: []
output:
  type: text
  display_as: feishu_text
actions:
  - name: get_styles
    data_schema_id: poster.styles
"""


def test_load_skills_finds_skill_with_manifest(tmp_path, monkeypatch):
    import src.skill.registry as reg
    _make_skill_dir(tmp_path, "test-simple", SIMPLE_MANIFEST)
    monkeypatch.setattr(reg, "SKILLS_DIR", str(tmp_path))
    skills = load_skills()
    assert "test-simple" in skills
    assert isinstance(skills["test-simple"], Skill)


def test_load_skills_skips_dirs_without_manifest(tmp_path, monkeypatch):
    import src.skill.registry as reg
    _make_skill_dir(tmp_path, "with-manifest", SIMPLE_MANIFEST)
    (tmp_path / "no-manifest").mkdir()
    (tmp_path / "no-manifest" / "SKILL.md").write_text("hi", encoding="utf-8")
    monkeypatch.setattr(reg, "SKILLS_DIR", str(tmp_path))
    skills = load_skills()
    assert "test-simple" in skills
    assert "no-manifest" not in skills  # Claude Code skill 被跳过


def test_load_complex_skill_loads_skill_md(tmp_path, monkeypatch):
    import src.skill.registry as reg
    _make_skill_dir(tmp_path, "test-complex", COMPLEX_MANIFEST, skill_md="### Core rule\nbla")
    monkeypatch.setattr(reg, "SKILLS_DIR", str(tmp_path))
    skills = load_skills()
    assert skills["test-complex"].system_prompt_core.startswith("### Core rule")


def test_load_skill_resolves_lazy_resources_to_abspath(tmp_path, monkeypatch):
    import src.skill.registry as reg
    skill_dir = _make_skill_dir(tmp_path, "test-complex", COMPLEX_MANIFEST, skill_md="x")
    (skill_dir / "references").mkdir()
    (skill_dir / "references" / "x.tsv").write_text("data", encoding="utf-8")
    monkeypatch.setattr(reg, "SKILLS_DIR", str(tmp_path))
    skills = load_skills()
    resource_path = skills["test-complex"].lazy_resources["lookup_x"]
    assert Path(resource_path).is_absolute()
    assert Path(resource_path).read_text() == "data"


def test_load_skill_preserves_action_data_schema_metadata(tmp_path, monkeypatch):
    import src.skill.registry as reg

    _make_skill_dir(
        tmp_path,
        "test-action-schema",
        ACTION_SCHEMA_MANIFEST,
        skill_md="```http\nGET /api/styles\n```",
    )
    monkeypatch.setattr(reg, "SKILLS_DIR", str(tmp_path))

    skills = load_skills()

    assert skills["test-action-schema"].actions[0].name == "get_styles"
    assert skills["test-action-schema"].actions[0].data_schema_id == "poster.styles"


def test_load_skills_skips_broken_manifest(tmp_path, monkeypatch):
    import src.skill.registry as reg
    _make_skill_dir(tmp_path, "good", SIMPLE_MANIFEST)
    _make_skill_dir(tmp_path, "broken", "not: valid: yaml: at all: [")
    monkeypatch.setattr(reg, "SKILLS_DIR", str(tmp_path))
    skills = load_skills()
    assert "test-simple" in skills  # broken 被跳过，good 仍加载


def test_reload_registry_picks_up_new_skill(tmp_path, monkeypatch):
    import src.skill.registry as reg
    monkeypatch.setattr(reg, "SKILLS_DIR", str(tmp_path))
    reset_registry()
    assert reg.get_registry() == {}

    _make_skill_dir(tmp_path, "test-simple", SIMPLE_MANIFEST)
    reloaded = reload_registry()
    assert "test-simple" in reloaded


def test_reload_registry_drops_removed_skill(tmp_path, monkeypatch):
    import src.skill.registry as reg
    skill_dir = _make_skill_dir(tmp_path, "test-simple", SIMPLE_MANIFEST)
    monkeypatch.setattr(reg, "SKILLS_DIR", str(tmp_path))
    reset_registry()
    reload_registry()
    assert "test-simple" in reg.get_registry()

    (skill_dir / "manifest.yaml").unlink()
    reload_registry()
    assert "test-simple" not in reg.get_registry()
