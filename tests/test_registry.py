from src.skill.registry import get_registry, load_skills
from src.skill.schema import Skill


def test_frame_bg_remover_loaded():
    skills = load_skills()
    assert "frame-bg-remover" in skills


def test_skill_structure():
    skills = load_skills()
    skill = skills["frame-bg-remover"]
    assert isinstance(skill, Skill)
    assert skill.api.endpoint_path.startswith("/api/")
    assert skill.api.method == "POST"
    assert skill.api.content_type == "multipart/form-data"


def test_skill_has_image_param():
    skills = load_skills()
    skill = skills["frame-bg-remover"]
    image_params = [p for p in skill.params if p.name == "image"]
    assert len(image_params) == 1
    assert image_params[0].type == "image"
    assert image_params[0].required is True


def test_registry_singleton():
    r1 = get_registry()
    r2 = get_registry()
    assert r1 is r2
