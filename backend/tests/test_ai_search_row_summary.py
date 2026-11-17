"""ai_search 兜底展示层：设备 type/status 中英文混杂时的翻译"""
from src.services.ai_search import _row_summary


def test_device_row_translates_english_enums():
    row = {
        "name": "PEK-SW-3-4.36",
        "type": "switch",
        "brand": "Huawei",
        "status": "active",
        "location": "PEK-401",
    }
    s = _row_summary("devices", row)
    assert "交换机" in s
    assert "在线" in s
    assert "switch" not in s
    assert "active" not in s


def test_device_row_keeps_chinese_values():
    row = {"name": "cest", "type": "交换机", "status": "在线"}
    s = _row_summary("devices", row)
    assert "交换机" in s and "在线" in s


def test_device_row_unknown_values_passthrough():
    # 未识别的值原样输出，不抛错
    row = {"name": "x", "type": "MysteryBox", "status": "weird"}
    s = _row_summary("devices", row)
    assert "MysteryBox" in s and "weird" in s


def test_device_row_optional_fields_absent():
    assert _row_summary("devices", {"name": "only-name"}) == "only-name"
    assert _row_summary("devices", {}) == "-"


def test_migrate_device_type_script_is_idempotent_import():
    # 脚本可导入（路径处理无副作用），核心归一函数行为受 constants 约束
    import scripts.migrate_device_type  # noqa: F401
    from src.constants.device_type import normalize_device_type
    assert normalize_device_type("核心交换机") == "switch"
    assert normalize_device_type("switch") == "switch"
