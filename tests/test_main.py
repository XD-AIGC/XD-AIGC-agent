from src.main import _strip_mentions, _normalize_message, _load_lazy_resource, _is_retry
from src.skill.schema import Skill, HttpBackend, SkillOutput


def test_strip_single_mention():
    assert _strip_mentions("@_user_1 帮我去白底") == "帮我去白底"


def test_strip_multiple_mentions():
    assert _strip_mentions("@_user_1 @_user_2 抠个图") == "抠个图"


def test_strip_mentions_no_mention():
    assert _strip_mentions("帮我去白底") == "帮我去白底"


def test_strip_mentions_only_mention():
    assert _strip_mentions("@_user_1") == ""


def test_strip_mentions_trailing_whitespace():
    assert _strip_mentions("  @_user_1  你好  ") == "你好"


# ---- _normalize_message ----

def test_normalize_text():
    assert _normalize_message("text", {"text": "你好"}) == ("你好", None)


def test_normalize_text_with_mention():
    assert _normalize_message("text", {"text": "@_user_1 你好"}) == ("你好", None)


def test_normalize_image():
    assert _normalize_message("image", {"image_key": "img_xxx"}) == ("", "img_xxx")


def test_normalize_post_text_and_image():
    content = {
        "title": "",
        "content": [
            [
                {"tag": "at", "user_id": "@_user_1", "user_name": "AIGC bot"},
                {"tag": "text", "text": "  帮我去除背景"},
            ],
            [{"tag": "img", "image_key": "img_v3_xxx"}],
        ],
    }
    text, image_key = _normalize_message("post", content)
    assert text == "帮我去除背景"
    assert image_key == "img_v3_xxx"


def test_normalize_post_text_only():
    content = {"content": [[{"tag": "at", "user_id": "@_user_1"}, {"tag": "text", "text": " 抠图"}]]}
    assert _normalize_message("post", content) == ("抠图", None)


def test_normalize_post_image_only():
    content = {"content": [[{"tag": "img", "image_key": "img_x"}]]}
    assert _normalize_message("post", content) == ("", "img_x")


def test_normalize_post_first_image_wins():
    content = {
        "content": [
            [{"tag": "img", "image_key": "first"}],
            [{"tag": "img", "image_key": "second"}],
        ]
    }
    _, key = _normalize_message("post", content)
    assert key == "first"


# ---- _load_lazy_resource ----

def _make_skill_with_lazy(lazy_map: dict) -> Skill:
    return Skill(
        name="t", description="d",
        api=HttpBackend(endpoint_path="/x"),
        params=[],
        output=SkillOutput(type="image_binary", display_as="feishu_image"),
        lazy_resources=lazy_map,
    )


def test_lazy_resource_missing_config():
    s = _make_skill_with_lazy({})
    assert "没有配置" in _load_lazy_resource(s, "lookup_characters")


def test_lazy_resource_file_not_exist():
    s = _make_skill_with_lazy({"lookup_characters": "non/existent/path.tsv"})
    assert "不存在" in _load_lazy_resource(s, "lookup_characters")


def test_lazy_resource_loads_real_file(tmp_path, monkeypatch):
    # 临时在 skills 目录下造一个测试资源文件
    import src.main as main_mod
    fake_skills_dir = tmp_path / "skills"
    fake_skills_dir.mkdir()
    (fake_skills_dir / "demo.tsv").write_text("a\tb\nc\td", encoding="utf-8")
    monkeypatch.setattr(main_mod, "_SKILLS_DIR", fake_skills_dir)

    s = _make_skill_with_lazy({"lookup_characters": "demo.tsv"})
    assert _load_lazy_resource(s, "lookup_characters") == "a\tb\nc\td"


def test_is_retry_exact_phrases():
    for p in ["再来一张", "再来", "再生成", "again", "Again", "重新生成"]:
        assert _is_retry(p), f"{p} should be retry"


def test_is_retry_with_punctuation():
    assert _is_retry("再来一张！")
    assert _is_retry("再来。")
    assert _is_retry("再来 ")


def test_is_retry_negative():
    for p in ["再来一张，但是改成竖版", "换标题", "好的", "不调整", ""]:
        assert not _is_retry(p), f"{p} should NOT be retry"


# --- enum options block ---
from src.main import _enum_options_block
from src.skill.schema import SkillParam


def _skill_with_enum(values: list[str], name: str = "fmt") -> Skill:
    return Skill(
        name="test",
        description="t",
        api=HttpBackend(endpoint_path="/x"),
        params=[SkillParam(name=name, type="enum", values=values, required=True, prompt_to_user="格式")],
        output=SkillOutput(type="image_binary", display_as="feishu_image"),
    )


def test_enum_options_block_appends():
    s = _skill_with_enum(["png", "jpg", "webp"])
    block = _enum_options_block(s, "fmt")
    assert "📋 格式 可选值" in block
    assert "- png" in block and "- jpg" in block and "- webp" in block


def test_enum_options_block_skips_non_enum():
    s = Skill(
        name="t", description="t",
        api=HttpBackend(endpoint_path="/x"),
        params=[SkillParam(name="txt", type="text", required=True, prompt_to_user="自由文本")],
        output=SkillOutput(type="text", display_as="feishu_text"),
    )
    assert _enum_options_block(s, "txt") == ""


def test_enum_options_block_unknown_param():
    s = _skill_with_enum(["a", "b"])
    assert _enum_options_block(s, "no_such_param") == ""


def test_enum_options_block_none_inputs():
    assert _enum_options_block(None, "fmt") == ""
    assert _enum_options_block(_skill_with_enum(["a"]), None) == ""
