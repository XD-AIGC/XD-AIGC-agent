from src.main import _strip_mentions


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
