from app.memory_system.memory_types import (
    MemoryType,
    get_memory_type_spec,
    list_memory_types_for_prompt,
    parse_memory_type,
    require_memory_type,
)


def test_memory_types_do_not_include_project():
    assert {item.value for item in MemoryType} == {
        "customer",
        "feedback",
        "business_rule",
        "reference",
    }
    assert "project" not in {item.value for item in MemoryType}


def test_parse_memory_type_is_lenient_for_scan():
    assert parse_memory_type("customer") == MemoryType.CUSTOMER
    assert parse_memory_type("project") is None


def test_require_memory_type_is_strict_for_write():
    try:
        require_memory_type("project")
    except ValueError as exc:
        assert "invalid memory type" in str(exc)
    else:
        raise AssertionError("expected invalid memory type to raise")


def test_business_rule_spec_forbids_untrusted_sources():
    spec = get_memory_type_spec(MemoryType.BUSINESS_RULE)
    text = "\n".join(spec.not_allowed)
    assert "源码" in text
    assert "API" in text
    assert "git history" in text
    assert "单个客户的个人偏好" in text


def test_prompt_type_list_excludes_project():
    prompt_text = list_memory_types_for_prompt()
    assert "business_rule" in prompt_text
    assert "project" not in prompt_text
