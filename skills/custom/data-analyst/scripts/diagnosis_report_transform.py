#!/usr/bin/env python3
"""多设备诊断报告聚合脚本

将多个设备的诊断结果聚合为统一的报告特征数据。

输入：
- per-device 的 diagnosis_features.json 文件列表
- 设备 ID 和名称映射
- capability_tier 等级

输出：
- diagnosis_report_features.json（聚合后的报告数据）
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> dict:
    """加载 JSON 文件"""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def extract_device_summary(
    diagnosis_features: dict,
    equipment_id: str,
    equipment_name: str,
) -> dict:
    """提取单个设备的诊断摘要"""
    evidence_chain = diagnosis_features.get("evidence_chain", [])
    rule_matches = diagnosis_features.get("rule_matches", [])
    recommendations = diagnosis_features.get("recommendations", [])

    # 提取异常发现
    key_findings = []
    for evidence in evidence_chain:
        if evidence.get("verdict") in ("exceed", "marginal"):
            key_findings.append({
                "point": evidence.get("point", ""),
                "feature": evidence.get("feature", ""),
                "value": evidence.get("value"),
                "threshold": evidence.get("threshold"),
                "verdict": evidence.get("verdict"),
                "severity": evidence.get("severity", "medium"),
            })

    # 提取根因匹配
    root_causes = []
    for match in rule_matches:
        root_causes.append({
            "rule_id": match.get("rule_id", ""),
            "root_cause_id": match.get("root_cause_id", match.get("rule_id", "")),
            "root_cause_label": match.get("label", match.get("description", "")),
            "confidence": match.get("confidence", "low"),
            "likelihood": match.get("likelihood", "low"),
            "severity": match.get("severity", "medium"),
            "supporting_evidence_count": match.get("supporting_evidence_count", 0),
            "rationale": match.get("rationale", ""),
        })

    return {
        "equipment_id": equipment_id,
        "equipment_name": equipment_name,
        "key_findings": key_findings,
        "evidence_chain": evidence_chain,
        "rule_matches": rule_matches,
        "root_causes": root_causes,
        "recommendations": recommendations,
        "data_quality": diagnosis_features.get("warnings", []),
        "model_fallback": diagnosis_features.get("model_fallback", False),
    }


def build_cross_device_correlation(per_device: list[dict]) -> dict:
    """构建跨设备根因关联"""
    # 按 root_cause_id 聚合
    root_cause_map: dict[str, dict] = {}

    for device in per_device:
        equipment_id = device["equipment_id"]
        equipment_name = device["equipment_name"]

        for root_cause in device.get("root_causes", []):
            rc_id = root_cause["root_cause_id"]

            if rc_id not in root_cause_map:
                root_cause_map[rc_id] = {
                    "root_cause_id": rc_id,
                    "root_cause_label": root_cause["root_cause_label"],
                    "affected_devices": [],
                    "max_severity": "low",
                    "max_likelihood": "low",
                }

            # 添加受影响的设备
            root_cause_map[rc_id]["affected_devices"].append({
                "equipment_id": equipment_id,
                "equipment_name": equipment_name,
                "confidence": root_cause.get("confidence", "low"),
            })

            # 更新最大严重度和可能性
            severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
            likelihood_order = {"low": 0, "medium": 1, "high": 2}

            current_severity = root_cause.get("severity", "low")
            if severity_order.get(current_severity, 0) > severity_order.get(
                root_cause_map[rc_id]["max_severity"], 0
            ):
                root_cause_map[rc_id]["max_severity"] = current_severity

            current_likelihood = root_cause.get("likelihood", "low")
            if likelihood_order.get(current_likelihood, 0) > likelihood_order.get(
                root_cause_map[rc_id]["max_likelihood"], 0
            ):
                root_cause_map[rc_id]["max_likelihood"] = current_likelihood

    # 计算关联强度
    correlated_root_causes = []
    for rc_id, rc_data in root_cause_map.items():
        affected_count = len(rc_data["affected_devices"])

        # 关联强度：影响 3+ 设备为 high，2 设备为 medium，1 设备为 low
        if affected_count >= 3:
            correlation_strength = "high"
        elif affected_count == 2:
            correlation_strength = "medium"
        else:
            correlation_strength = "low"

        correlated_root_causes.append({
            **rc_data,
            "correlation_strength": correlation_strength,
        })

    # 按关联强度排序
    strength_order = {"low": 0, "medium": 1, "high": 2}
    correlated_root_causes.sort(
        key=lambda x: (
            strength_order.get(x["correlation_strength"], 0),
            len(x["affected_devices"]),
        ),
        reverse=True,
    )

    return {
        "correlated_root_causes": correlated_root_causes,
        "shared_evidence": [],  # 预留：可以添加共享证据分析
    }


def build_impact_assessment(per_device: list[dict]) -> dict:
    """构建影响评估"""
    affected_equipment_count = len(per_device)

    # 统计严重度分布
    severity_counts = {"low": 0, "medium": 0, "high": 0, "critical": 0}
    for device in per_device:
        for root_cause in device.get("root_causes", []):
            severity = root_cause.get("severity", "low")
            if severity in severity_counts:
                severity_counts[severity] += 1

    # 估算停机时间（简化规则）
    estimated_downtime_hours = 0
    if severity_counts["critical"] > 0:
        estimated_downtime_hours = 24  # 严重故障
    elif severity_counts["high"] > 0:
        estimated_downtime_hours = 8  # 高度故障
    elif severity_counts["medium"] > 0:
        estimated_downtime_hours = 4  # 中度故障

    # 业务影响描述
    if severity_counts["critical"] > 0:
        business_impact = "严重影响生产，建议立即停机检修"
    elif severity_counts["high"] > 0:
        business_impact = "较大影响，建议尽快安排检修"
    elif severity_counts["medium"] > 0:
        business_impact = "中等影响，可安排计划检修"
    else:
        business_impact = "影响较小，可继续运行并加强监测"

    return {
        "affected_equipment_count": affected_equipment_count,
        "severity_distribution": severity_counts,
        "estimated_downtime_hours": estimated_downtime_hours,
        "business_impact": business_impact,
    }


def build_root_cause_ranking(per_device: list[dict]) -> list[dict]:
    """构建根因排序列表"""
    all_root_causes = []

    for device in per_device:
        equipment_id = device["equipment_id"]
        equipment_name = device["equipment_name"]

        for root_cause in device.get("root_causes", []):
            all_root_causes.append({
                "equipment_id": equipment_id,
                "equipment_name": equipment_name,
                "root_cause_id": root_cause["root_cause_id"],
                "root_cause_label": root_cause["root_cause_label"],
                "confidence": root_cause.get("confidence", "low"),
                "likelihood": root_cause.get("likelihood", "low"),
                "severity": root_cause.get("severity", "medium"),
                "rationale": root_cause.get("rationale", ""),
            })

    # 按 likelihood × severity 排序
    severity_order = {"low": 1, "medium": 2, "high": 3, "critical": 4}
    likelihood_order = {"low": 1, "medium": 2, "high": 3}

    all_root_causes.sort(
        key=lambda x: (
            likelihood_order.get(x["likelihood"], 1) * severity_order.get(x["severity"], 1)
        ),
        reverse=True,
    )

    # 标记主要根因（排名第一的）
    if all_root_causes:
        all_root_causes[0]["is_primary"] = True

    # 添加排名
    for i, rc in enumerate(all_root_causes, 1):
        rc["rank"] = i

    return all_root_causes


def build_prioritized_recommendations(per_device: list[dict]) -> list[dict]:
    """构建优先级排序的维护建议"""
    all_recommendations = []

    for device in per_device:
        equipment_id = device["equipment_id"]
        equipment_name = device["equipment_name"]

        for rec in device.get("recommendations", []):
            all_recommendations.append({
                "equipment_id": equipment_id,
                "equipment_name": equipment_name,
                "priority": rec.get("priority", "routine"),
                "action": rec.get("action", ""),
                "rationale": rec.get("rationale", ""),
                "timeframe": rec.get("timeframe", ""),
            })

    # 按优先级排序
    priority_order = {"urgent": 0, "important": 1, "routine": 2}
    all_recommendations.sort(
        key=lambda x: priority_order.get(x["priority"], 2)
    )

    return all_recommendations


def aggregate_diagnosis_reports(
    inputs: list[Path],
    equipment_ids: list[str],
    equipment_names: list[str],
    capability_tier: str,
) -> dict:
    """聚合多设备诊断结果为统一报告。

    Args:
        inputs: 各设备 diagnosis_features.json 文件路径列表
        equipment_ids: 设备 ID 列表
        equipment_names: 设备名称列表
        capability_tier: 能力等级 (basic/pro/ultra)

    Returns:
        聚合后的诊断报告字典
    """
    if len(inputs) != len(equipment_ids):
        raise ValueError(f"设备 ID 数量 ({len(equipment_ids)}) 与输入文件数量 ({len(inputs)}) 不匹配")

    if len(inputs) != len(equipment_names):
        raise ValueError(f"设备名称数量 ({len(equipment_names)}) 与输入文件数量 ({len(inputs)}) 不匹配")

    # 加载所有设备的诊断结果
    per_device = []
    for input_path, eq_id, eq_name in zip(inputs, equipment_ids, equipment_names):
        if not input_path.exists():
            print(f"警告：文件不存在 {input_path}，跳过", file=sys.stderr)
            continue

        diagnosis_features = load_json(input_path)
        device_summary = extract_device_summary(diagnosis_features, eq_id, eq_name)
        per_device.append(device_summary)

    if not per_device:
        raise ValueError("没有有效的诊断结果")

    # 构建聚合报告
    cross_device_correlation = build_cross_device_correlation(per_device)
    impact_assessment = build_impact_assessment(per_device)
    root_cause_ranking = build_root_cause_ranking(per_device)
    recommendations = build_prioritized_recommendations(per_device)

    # 聚合数据质量警告
    data_quality_warnings = []
    for device in per_device:
        warnings = device.get("data_quality", [])
        if warnings:
            data_quality_warnings.extend(warnings)

    # 检查模型回退标志
    model_fallback = any(device.get("model_fallback", False) for device in per_device)

    # 构建报告元数据
    report_meta = {
        "total_devices": len(per_device),
        "capability_tier": capability_tier,
        "generated_at": "auto",  # 由导出脚本设置
    }

    # 构建最终聚合报告
    report = {
        "analysis_type": "diagnosis",
        "report_meta": report_meta,
        "per_device": per_device,
        "cross_device_correlation": cross_device_correlation,
        "impact_assessment": impact_assessment,
        "root_cause_ranking": root_cause_ranking,
        "recommendations": recommendations,
        "data_quality": data_quality_warnings,
    }

    # 如果有设备使用了模型回退，添加标志
    if model_fallback:
        report["model_fallback"] = True

    return report


def main():
    parser = argparse.ArgumentParser(description="多设备诊断报告聚合")
    parser.add_argument(
        "--inputs",
        type=Path,
        nargs="+",
        required=True,
        help="per-device diagnosis_features.json 文件路径列表",
    )
    parser.add_argument(
        "--equipment-ids",
        type=str,
        required=True,
        help="设备 ID 列表（逗号分隔）",
    )
    parser.add_argument(
        "--equipment-names",
        type=str,
        required=True,
        help="设备名称列表（逗号分隔）",
    )
    parser.add_argument(
        "--capability-tier",
        type=str,
        default=None,
        help="能力等级（auto/basic/pro/ultra），默认 auto",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("diagnosis_report_features.json"),
        help="输出文件路径",
    )

    args = parser.parse_args()

    # 解析设备 ID 和名称
    equipment_ids = [eid.strip() for eid in args.equipment_ids.split(",")]
    equipment_names = [ename.strip() for ename in args.equipment_names.split(",")]

    if len(equipment_ids) != len(args.inputs):
        print(
            f"错误：设备 ID 数量 ({len(equipment_ids)}) 与输入文件数量 ({len(args.inputs)}) 不匹配",
            file=sys.stderr,
        )
        sys.exit(1)

    if len(equipment_names) != len(args.inputs):
        print(
            f"错误：设备名称数量 ({len(equipment_names)}) 与输入文件数量 ({len(args.inputs)}) 不匹配",
            file=sys.stderr,
        )
        sys.exit(1)

    # 确定能力等级（必须提供）
    if not args.capability_tier:
        print("错误：必须通过 --capability-tier 指定能力等级 (basic/pro/ultra)", file=sys.stderr)
        sys.exit(1)

    # 调用聚合函数
    try:
        report = aggregate_diagnosis_reports(
            inputs=args.inputs,
            equipment_ids=equipment_ids,
            equipment_names=equipment_names,
            capability_tier=args.capability_tier,
        )
    except ValueError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)

    # 写入输出文件
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"✓ 生成诊断报告特征文件：{args.output}")
    print(f"  - 设备数量：{len(report['per_device'])}")
    print(f"  - 根因数量：{len(report['root_cause_ranking'])}")
    print(f"  - 建议数量：{len(report['recommendations'])}")


if __name__ == "__main__":
    main()
