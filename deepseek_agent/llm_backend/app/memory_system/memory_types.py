from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class MemoryType(StrEnum):
    CUSTOMER = "customer"
    FEEDBACK = "feedback"
    BUSINESS_RULE = "business_rule"
    REFERENCE = "reference"


@dataclass(frozen=True)
class MemoryTypeSpec:
    type: MemoryType
    directory: str
    description: str
    when_to_save: str
    how_to_use: str
    body_structure: str
    not_allowed: tuple[str, ...]


MEMORY_TYPE_SPECS: dict[MemoryType, MemoryTypeSpec] = {
    MemoryType.CUSTOMER: MemoryTypeSpec(
        type=MemoryType.CUSTOMER,
        directory="customer",
        description="客户长期偏好、稳定需求约束、服务沟通偏好。",
        when_to_save="客户明确表达稳定偏好，或多次表现出一致服务约束时保存。",
        how_to_use="调整客服回答方式，但不能替代实时订单、库存、价格、物流或售后查询。",
        body_structure="Lead with the preference, then Why and How to apply.",
        not_allowed=(
            "单次临时购买意图",
            "实时订单状态",
            "实时库存状态",
            "实时价格",
            "完整手机号、地址、支付信息等敏感身份信息",
        ),
    ),
    MemoryType.FEEDBACK: MemoryTypeSpec(
        type=MemoryType.FEEDBACK,
        directory="feedback",
        description="客户、客服或运营对回答方式、流程和体验的纠正意见。",
        when_to_save="反馈能稳定改善后续客服表现，且不是一次性情绪表达时保存。",
        how_to_use="用于避免重复错误、改善措辞和流程，但不能提升为业务规则。",
        body_structure="Lead with the correction, then Evidence and Future behavior.",
        not_allowed=(
            "未经确认的全局售后政策",
            "普通用户猜测出的业务规则",
            "实时业务系统查询结果",
        ),
    ),
    MemoryType.BUSINESS_RULE: MemoryTypeSpec(
        type=MemoryType.BUSINESS_RULE,
        directory="business_rule",
        description="经可信来源确认的售前、售后、库存、物流、活动等业务规则。",
        when_to_save="只允许来自运营或客服主管确认、官方文档、工具校验、政策导入或人工审核。",
        how_to_use="辅助回答规则类问题；遇到订单、库存、价格、物流、售后进度等实时事实必须查业务系统。",
        body_structure="Lead with the rule, then Source, Effective window, and How to apply.",
        not_allowed=(
            "从源码推断出的业务规则",
            "API 实现细节",
            "git history",
            "临时测试数据",
            "未经确认的客服猜测",
            "单个客户的个人偏好",
            "普通用户一句话提出的售后规则",
        ),
    ),
    MemoryType.REFERENCE: MemoryTypeSpec(
        type=MemoryType.REFERENCE,
        directory="reference",
        description="可复用的客服知识片段、解释模板或背景资料。",
        when_to_save="内容稳定、可复用，且不属于客户偏好或已确认业务规则时保存。",
        how_to_use="作为回答组织和解释依据，但不能覆盖实时工具证据。",
        body_structure="Lead with the reusable knowledge, then Context and Usage.",
        not_allowed=(
            "实时订单状态",
            "实时库存状态",
            "实时价格",
            "未经确认的全局政策",
        ),
    ),
}


def parse_memory_type(raw: object) -> MemoryType | None:
    if raw is None:
        return None
    try:
        return MemoryType(str(raw).strip())
    except ValueError:
        return None


def require_memory_type(raw: object) -> MemoryType:
    memory_type = parse_memory_type(raw)
    if memory_type is None:
        raise ValueError(f"invalid memory type: {raw!r}")
    return memory_type


def get_memory_type_spec(memory_type: MemoryType) -> MemoryTypeSpec:
    return MEMORY_TYPE_SPECS[memory_type]


def memory_type_directory(memory_type: MemoryType) -> str:
    return get_memory_type_spec(memory_type).directory


def list_memory_types_for_prompt() -> str:
    lines: list[str] = []
    for memory_type in MemoryType:
        spec = get_memory_type_spec(memory_type)
        lines.append(
            "\n".join(
                [
                    f"- {spec.type.value}",
                    f"  description: {spec.description}",
                    f"  when_to_save: {spec.when_to_save}",
                    f"  how_to_use: {spec.how_to_use}",
                    f"  not_allowed: {'; '.join(spec.not_allowed)}",
                ]
            )
        )
    return "\n".join(lines)
