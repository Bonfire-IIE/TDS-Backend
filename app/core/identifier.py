"""TDS 标识码生成器。

依据《数据基础设施 标识要求》国标实现主体/平台/连接器/数据产品与资源的标识码，
校验码采用 GB/T 17710（等同 ISO/IEC 7064）的 **MOD 37-2（纯系统, pure system）** 算法。

标识码结构（本模块负责的 32/32~65 位码）：
    平台/连接器码(32位) = 类型码(1) + 主体标识码(18) + 区域/行业代码(4) + 随机码(8) + 校验码(1)
    数据产品/资源码(32~65位) = 上述 32 位 + 可选扩展码(≤32位, 以 '•' 分隔)

类型码：
    1=全域节点  2=区域节点  3=行业节点  4=业务节点  5=接入连接器  6=数据产品  7=数据资源

ISO/IEC 7064 MOD 37-2（纯系统）算法说明
----------------------------------------
- 模数 M=37，基数 r=2；字符集（含校验码）为 "0-9" + "A-Z" + "*"（共 37 个符号）。
- 字符到数值映射：'0'..'9' -> 0..9；'A'..'Z' -> 10..35；'*' -> 36（'*' 仅作校验码出现）。
- 纯系统的定义式：对完整串 a_n a_{n-1} ... a_1（a_1 为最右侧校验位，权重 r^0），
  满足   Σ a_i · r^(i-1) ≡ 1 (mod M)。
- 递归计算（Horner）：对去掉校验位的载荷自左向右
      p := ((p + value(c)) * r) mod M      （初值 p=0）
  处理完毕后 p 恰为 Σ_{i≥2} a_i·r^(i-1) (mod M)，故校验位数值
      check := (1 - p) mod M
  使整串加权和 ≡ 1 (mod M)。

正确性依据：上式为 ISO/IEC 7064 纯系统的定义式；本实现对已公开的
MOD 11-2 向量 "079"->"X" 复现一致，且生成串满足 Σ a_i·r^(i-1) ≡ 1 (mod 37)
（见 tests/test_identifier.py）。参考：ISO/IEC 7064:2003；GB/T 17710；
Wikipedia "ISO/IEC 7064"。
"""
from __future__ import annotations

import secrets
from datetime import datetime

# 校验码/数据字符集：索引即字符数值（'*' -> 36，仅作校验码）
_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ*"
# 载荷（非校验位）允许的字符集：不含 '*'
_PAYLOAD_CHARS = frozenset(_ALPHABET[:36])
_MODULUS = 37
_RADIX = 2

# 各字段长度
_SUBJECT_LEN = 18
_REGION_INDUSTRY_LEN = 4
_RANDOM_LEN = 8
_EXTENSION_MAX = 32
_EXTENSION_SEP = "•"

# 类型码
_NODE_TYPES = {"1", "2", "3", "4"}
_CONNECTOR_TYPE = "5"
_DATA_TYPES = {"product": "6", "resource": "7"}

# 数字合约码
_CONTRACT_TYPE = "C"          # 合约类型码（1 位，占位取 'C'）
_CONTRACT_NODE_TYPE = "4"     # 业务节点类型码（1 位，合约在业务节点上成立）
_TIME_LEN = 14                # 时间码：%Y%m%d%H%M%S


def mod37_2_check_char(payload: str) -> str:
    """按 ISO/IEC 7064 MOD 37-2（纯系统）计算 1 位校验字符。

    参数:
        payload: 去除校验位的载荷串，仅允许 0-9、A-Z（不含 '*'）。
    返回:
        1 位校验字符（0-9、A-Z 或 '*'）。
    异常:
        ValueError: payload 为空或含非法字符。
    """
    if not payload:
        raise ValueError("payload 不能为空")
    p = 0
    for ch in payload:
        if ch not in _PAYLOAD_CHARS:
            raise ValueError(f"载荷含非法字符 {ch!r}（仅允许 0-9A-Z）")
        p = ((p + _ALPHABET.index(ch)) * _RADIX) % _MODULUS
    check_value = (1 - p) % _MODULUS
    return _ALPHABET[check_value]


def verify_check_char(code_with_check: str) -> bool:
    """校验带校验位的完整码是否自洽。

    末位视为校验位，其余为载荷；重新计算校验位并比对。
    对空串、载荷含非法字符或校验位不在字符集内的情况返回 False（不抛错）。
    """
    if not code_with_check or len(code_with_check) < 2:
        return False
    payload, check = code_with_check[:-1], code_with_check[-1]
    if check not in _ALPHABET:
        return False
    try:
        return mod37_2_check_char(payload) == check
    except ValueError:
        return False


def _validate_field(value: str, length: int, name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} 必须为字符串")
    if len(value) != length:
        raise ValueError(f"{name} 长度必须为 {length}，实际 {len(value)}")
    for ch in value:
        if ch not in _PAYLOAD_CHARS:
            raise ValueError(f"{name} 含非法字符 {ch!r}（仅允许 0-9A-Z）")
    return value


def _random_code(length: int = _RANDOM_LEN) -> str:
    """生成 length 位随机码（0-9A-Z），使用 secrets 保证不可预测。"""
    return "".join(secrets.choice(_ALPHABET[:36]) for _ in range(length))


def _assemble(type_code: str, subject_code18: str, region_industry4: str) -> str:
    """拼装 类型码 + 主体码(18) + 区域/行业(4) + 随机码(8) 并附校验码，返回 32 位码。"""
    _validate_field(subject_code18, _SUBJECT_LEN, "主体标识码")
    _validate_field(region_industry4, _REGION_INDUSTRY_LEN, "区域/行业代码")
    payload = type_code + subject_code18 + region_industry4 + _random_code()
    return payload + mod37_2_check_char(payload)


def gen_connector_code(subject_code18: str, region_industry4: str) -> str:
    """生成接入连接器标识码（类型码=5，共 32 位）。"""
    return _assemble(_CONNECTOR_TYPE, subject_code18, region_industry4)


def gen_node_code(node_type: str, subject_code18: str, region_industry4: str) -> str:
    """生成节点标识码（类型码 1/2/3/4，共 32 位）。

    node_type: '1'全域 / '2'区域 / '3'行业 / '4'业务 节点。
    """
    if node_type not in _NODE_TYPES:
        raise ValueError(f"node_type 必须为 {sorted(_NODE_TYPES)} 之一，实际 {node_type!r}")
    return _assemble(node_type, subject_code18, region_industry4)


def gen_data_code(
    kind: str,
    subject_code18: str,
    region_industry4: str,
    extension: str | None = None,
) -> str:
    """生成数据产品/资源标识码（类型码 6/7，32~65 位）。

    kind: 'product'(=6) 或 'resource'(=7)。
    extension: 可选扩展码，长度 1~32 且仅 0-9A-Z；以 '•' 分隔追加于校验位之后
               （不参与校验位计算）。
    """
    if kind not in _DATA_TYPES:
        raise ValueError(f"kind 必须为 'product' 或 'resource'，实际 {kind!r}")
    code = _assemble(_DATA_TYPES[kind], subject_code18, region_industry4)
    if extension is not None:
        if not extension:
            raise ValueError("扩展码不能为空串（无扩展请传 None）")
        if len(extension) > _EXTENSION_MAX:
            raise ValueError(f"扩展码长度不能超过 {_EXTENSION_MAX}，实际 {len(extension)}")
        for ch in extension:
            if ch not in _PAYLOAD_CHARS:
                raise ValueError(f"扩展码含非法字符 {ch!r}（仅允许 0-9A-Z）")
        code = code + _EXTENSION_SEP + extension
    return code


def gen_contract_code(subject_code18: str, region_industry4: str) -> str:
    """生成数字合约标识码（共 47 位）。

    结构：合约类型码(1='C') + 业务节点类型码(1='4') + 主体标识码(18) +
          区域/行业代码(4) + 时间码(14, UTC %Y%m%d%H%M%S) + 随机码(8) + 校验码(1)。
    校验码沿用 ISO/IEC 7064 MOD 37-2（对前 46 位载荷计算）。
    """
    _validate_field(subject_code18, _SUBJECT_LEN, "主体标识码")
    _validate_field(region_industry4, _REGION_INDUSTRY_LEN, "区域/行业代码")
    time_code = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    payload = (
        _CONTRACT_TYPE + _CONTRACT_NODE_TYPE + subject_code18
        + region_industry4 + time_code + _random_code()
    )
    return payload + mod37_2_check_char(payload)
