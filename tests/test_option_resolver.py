from src.conversation.option_resolver import (
    OptionResolver,
    build_enum_option_set,
    build_resource_option_set,
    build_router_disambiguation_option_set,
)
from src.conversation.options import OptionItem, OptionSet


def _ratio_options(now: float = 100.0) -> OptionSet:
    return OptionSet(
        id="ratio-1",
        param_name="ratio",
        source="enum",
        created_at=now,
        skill_version="v1",
        items=[
            OptionItem(index=1, label="2:3 竖版海报", value="2:3", param_name="ratio", aliases=["竖版"]),
            OptionItem(index=2, label="3:2 横版", value="3:2", param_name="ratio", aliases=["横版"]),
        ],
    )


def test_resolver_matches_numeric_choice_on_current_page():
    result = OptionResolver(now=lambda: 120.0, skill_version="v1").resolve("2", _ratio_options())

    assert result.status == "matched"
    assert result.item.value == "3:2"
    assert result.values == ["3:2"]


def test_resolver_matches_label_alias():
    result = OptionResolver(now=lambda: 120.0, skill_version="v1").resolve("横版", _ratio_options())

    assert result.status == "matched"
    assert result.item.index == 2


def test_resolver_rejects_expired_option_set_without_deleting_it():
    option_set = _ratio_options(now=100.0)

    result = OptionResolver(now=lambda: 500.0, skill_version="v1").resolve("2", option_set)

    assert result.status == "expired"
    assert result.option_set == option_set
    assert "菜单可能已更新" in result.message


def test_resolver_rejects_skill_version_mismatch():
    result = OptionResolver(now=lambda: 120.0, skill_version="v2").resolve("2", _ratio_options())

    assert result.status == "expired"
    assert "菜单可能已更新" in result.message


def test_resolver_supports_more_and_back_paging():
    option_set = OptionSet(
        id="many",
        param_name="character",
        source="resource",
        page_size=2,
        created_at=100.0,
        items=[
            OptionItem(index=1, label="A", value="a", param_name="character"),
            OptionItem(index=2, label="B", value="b", param_name="character"),
            OptionItem(index=3, label="C", value="c", param_name="character"),
        ],
    )
    resolver = OptionResolver(now=lambda: 120.0)

    more = resolver.resolve("更多", option_set)
    back = resolver.resolve("返回", more.option_set)

    assert more.status == "page"
    assert more.option_set.page == 2
    assert "3. C" in more.message
    assert back.status == "page"
    assert back.option_set.page == 1
    assert "1. A" in back.message


def test_resolver_rejects_multi_select_when_not_allowed():
    result = OptionResolver(now=lambda: 120.0, skill_version="v1").resolve("1 2", _ratio_options())

    assert result.status == "no_match"
    assert "请选择一个选项" in result.message


def test_resolver_allows_multi_select_when_enabled():
    option_set = _ratio_options()
    option_set.allow_multi = True

    result = OptionResolver(now=lambda: 120.0, skill_version="v1").resolve("1,2", option_set)

    assert result.status == "matched"
    assert result.values == ["2:3", "3:2"]


def test_resolver_rejects_multi_select_when_one_index_is_out_of_range():
    option_set = _ratio_options()
    option_set.allow_multi = True

    result = OptionResolver(now=lambda: 120.0, skill_version="v1").resolve("1 99", option_set)

    assert result.status == "out_of_range"


def test_build_enum_option_set():
    option_set = build_enum_option_set("ratio", ["2:3", "3:2"], skill_version="v1", now=100.0)

    assert option_set.scope == "skill_param"
    assert option_set.source == "enum"
    assert option_set.items[1].label == "3:2"
    assert option_set.items[1].value == "3:2"


def test_build_resource_option_set_from_character_items():
    option_set = build_resource_option_set(
        "characters",
        [
            {"key": "andrew", "name": "安德鲁", "id": "npc-1"},
            {"key": "bill", "name": "比尔"},
        ],
        skill_version="v1",
        now=100.0,
    )

    assert option_set.source == "resource"
    assert option_set.items[0].label == "安德鲁"
    assert option_set.items[0].value == ["andrew"]
    assert "npc-1" in option_set.items[0].aliases


def test_build_router_disambiguation_option_set():
    option_set = build_router_disambiguation_option_set(
        [
            {"name": "frame-bg-remover", "description": "去白底"},
            {"name": "xd-poster-gen", "description": "生成海报"},
        ],
        now=100.0,
    )

    assert option_set.scope == "system"
    assert option_set.source == "router_disambiguation"
    assert option_set.param_name == "_skill"
    assert option_set.items[1].value == "xd-poster-gen"
