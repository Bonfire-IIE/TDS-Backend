"""TDS 标识码生成器单元测试。

覆盖：
- MOD 37-2 校验算法的正确性（公开向量交叉验证 + ISO 定义式 Σ a_i·r^(i-1) ≡ 1 mod 37）
- generate -> verify 往返、篡改任一位后 verify 失败
- 各生成函数的长度、类型码正确
- 非法入参抛 ValueError
"""
import re

import pytest

from app.core.identifier import (
    gen_connector_code,
    gen_data_code,
    gen_node_code,
    mod37_2_check_char,
    verify_check_char,
)

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ*"


def _weighted_sum_mod37(full: str) -> int:
    """ISO/IEC 7064 纯系统定义式：Σ a_i·r^(i-1) (mod 37)，最右为权重 r^0。"""
    total = 0
    for i, ch in enumerate(reversed(full)):
        total += _ALPHABET.index(ch) * (2 ** i)
    return total % 37


# ---------------------------------------------------------------------------
# 校验算法正确性
# ---------------------------------------------------------------------------
def test_mod37_2_known_vectors():
    # 由 ISO 纯系统定义式独立验证（非依赖被测实现的写法）
    assert mod37_2_check_char("G123456789") == "H"
    assert mod37_2_check_char("079") == "T"


def test_mod37_2_satisfies_iso_definition():
    """生成的完整串必须满足 Σ a_i·r^(i-1) ≡ 1 (mod 37)。"""
    for payload in ["G123456789", "079", "ABCDEF", "0", "ZZZZZZZZ", "5911010000ABC12345"]:
        check = mod37_2_check_char(payload)
        assert _weighted_sum_mod37(payload + check) == 1


def test_check_char_in_alphabet():
    for payload in ["A", "B", "10", "36", "HELLO42"]:
        assert mod37_2_check_char(payload) in _ALPHABET


def test_mod37_2_invalid_payload():
    with pytest.raises(ValueError):
        mod37_2_check_char("")
    with pytest.raises(ValueError):
        mod37_2_check_char("abc")  # 小写非法
    with pytest.raises(ValueError):
        mod37_2_check_char("12*45")  # '*' 不允许出现在载荷


# ---------------------------------------------------------------------------
# verify 往返与篡改检测
# ---------------------------------------------------------------------------
def test_generate_verify_roundtrip():
    code = gen_connector_code("91110000100000000X", "1101")
    assert verify_check_char(code) is True


def test_tamper_any_position_fails():
    code = gen_connector_code("91110000100000000X", "1101")
    assert verify_check_char(code) is True
    for i in range(len(code)):
        orig = code[i]
        # 换成另一个合法字符
        repl = "1" if orig != "1" else "2"
        tampered = code[:i] + repl + code[i + 1:]
        assert verify_check_char(tampered) is False, f"位置 {i} 篡改未被检出"


def test_verify_bad_input_returns_false():
    assert verify_check_char("") is False
    assert verify_check_char("A") is False
    assert verify_check_char("abc9") is False  # 载荷非法字符


# ---------------------------------------------------------------------------
# 生成函数：长度、类型码
# ---------------------------------------------------------------------------
SUBJECT = "91110000100000000X"
REGION = "1101"


def test_connector_code_shape():
    code = gen_connector_code(SUBJECT, REGION)
    assert len(code) == 32
    assert code[0] == "5"
    assert code[1:19] == SUBJECT
    assert code[19:23] == REGION
    assert verify_check_char(code)


@pytest.mark.parametrize("node_type", ["1", "2", "3", "4"])
def test_node_code_shape(node_type):
    code = gen_node_code(node_type, SUBJECT, REGION)
    assert len(code) == 32
    assert code[0] == node_type
    assert verify_check_char(code)


def test_node_code_invalid_type():
    with pytest.raises(ValueError):
        gen_node_code("5", SUBJECT, REGION)
    with pytest.raises(ValueError):
        gen_node_code("9", SUBJECT, REGION)


@pytest.mark.parametrize("kind,expect_type", [("product", "6"), ("resource", "7")])
def test_data_code_shape(kind, expect_type):
    code = gen_data_code(kind, SUBJECT, REGION)
    assert len(code) == 32
    assert code[0] == expect_type
    assert verify_check_char(code)


def test_data_code_with_extension():
    ext = "V1"
    code = gen_data_code("resource", SUBJECT, REGION, extension=ext)
    assert code[0] == "7"
    assert "•" in code
    base, extension = code.split("•", 1)
    assert extension == ext
    assert len(base) == 32
    # 扩展码不参与校验，去掉扩展后主体码仍自洽
    assert verify_check_char(base)
    assert len(code) == 32 + 1 + len(ext)


def test_data_code_max_extension_length():
    code = gen_data_code("product", SUBJECT, REGION, extension="A" * 32)
    assert len(code) == 65  # 32 + '•' + 32


def test_data_code_invalid_extension():
    with pytest.raises(ValueError):
        gen_data_code("product", SUBJECT, REGION, extension="A" * 33)  # 超长
    with pytest.raises(ValueError):
        gen_data_code("product", SUBJECT, REGION, extension="")  # 空串
    with pytest.raises(ValueError):
        gen_data_code("product", SUBJECT, REGION, extension="a1")  # 非法字符


def test_data_code_invalid_kind():
    with pytest.raises(ValueError):
        gen_data_code("dataset", SUBJECT, REGION)


# ---------------------------------------------------------------------------
# 字段长度校验
# ---------------------------------------------------------------------------
def test_invalid_subject_length():
    with pytest.raises(ValueError):
        gen_connector_code("123", REGION)  # 主体码非 18 位


def test_invalid_region_length():
    with pytest.raises(ValueError):
        gen_connector_code(SUBJECT, "11")  # 区域码非 4 位


def test_invalid_field_chars():
    with pytest.raises(ValueError):
        gen_connector_code("9111000010000000ax", REGION)  # 主体码含小写


def test_random_code_uniqueness():
    codes = {gen_connector_code(SUBJECT, REGION) for _ in range(200)}
    # 8 位 36 进制随机码，200 次几乎不可能碰撞
    assert len(codes) == 200
    assert all(re.fullmatch(r"[0-9A-Z*]{32}", c) for c in codes)
