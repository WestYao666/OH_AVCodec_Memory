#!/usr/bin/env python3
"""
validate_memory.py — 记忆工厂门禁校验脚本

检查一条 memory entry YAML 是否通过 8 条门禁：
1. 有 summary
2. 有 evidence
3. 标注了 scope
4. 区分 stable knowledge / temporary state
5. 关联四类场景之一
6. 无猜测性语言（禁止 "应该是 / 可能是 / 大概是"）
7. 有 owner
8. 有 update_trigger

用法：python3 validate_memory.py <yaml_file>
返回：0=pass, 1=fail
"""

import sys
import yaml
import re

FORBIDDEN_PATTERNS = [
    r"应该是", r"可能是", r"大概是", r"应该是吧", r"可能是吧",
    r"应该可以", r"大概可以", r"估计是", r"推测是", r"看起来像",
    r"probably", r"maybe", r"perhaps", r"seems like", r"should be"
]

SCENES = ["newcomer", "integrator", "feature_dev", "debug"]

def validate_field_exists(data, field, name):
    if field not in data or not data[field]:
        return False, f"缺少或为空：{name}"
    return True, ""

def validate_summary(data):
    if "summary" not in data or not data["summary"]:
        return False, "缺少 summary"
    if len(str(data["summary"]).strip()) < 10:
        return False, "summary 太短（<10字符）"
    return True, ""

def validate_evidence(data):
    if "evidence" not in data or not isinstance(data["evidence"], list):
        return False, "evidence 缺失或非列表"
    if len(data["evidence"]) == 0:
        return False, "evidence 为空"
    for i, ev in enumerate(data["evidence"]):
        if "kind" not in ev or "ref" not in ev:
            return False, f"evidence[{i}] 缺少 kind 或 ref"
        valid_kinds = ["code", "doc", "build", "commit", "user", "run"]
        if ev["kind"] not in valid_kinds:
            return False, f"evidence[{i}] kind='{ev['kind']}' 不在允许列表中"
    return True, ""

def validate_scope(data):
    if "scope" not in data or not isinstance(data["scope"], list) or len(data["scope"]) == 0:
        return False, "scope 缺失或为空列表"
    return True, ""

def validate_status_classification(data):
    if "status" not in data:
        return False, "缺少 status"
    valid_statuses = ["draft", "pending_review", "approved", "rejected", "stale"]
    if data["status"] not in valid_statuses:
        return False, f"status='{data['status']}' 不在允许列表中"
    return True, ""

def validate_scene_association(data):
    if "why_it_matters" in data and isinstance(data["why_it_matters"], list):
        text = " ".join(str(x) for x in data["why_it_matters"]).lower()
        for scene in SCENES:
            if scene in text:
                return True, ""
    if "scope" in data:
        return True, ""
    return False, "未关联四类场景（newcomer/integrator/feature_dev/debug）"

def validate_no_guess_language(data):
    text = yaml.dump(data).lower()
    for pattern in FORBIDDEN_PATTERNS:
        if re.search(pattern, text):
            return False, f"发现猜测性语言：'{pattern}'"
    return True, ""

def validate_owner(data):
    if "owner" not in data or not data["owner"]:
        return False, "缺少 owner"
    return True, ""

def validate_update_trigger(data):
    if "update_trigger" not in data or not data["update_trigger"]:
        return False, "缺少 update_trigger"
    return True, ""

def validate_memory_entry(yaml_path):
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"FAIL: 无法读取文件: {e}")
        return 1

    checks = [
        ("summary", validate_summary),
        ("evidence", validate_evidence),
        ("scope", validate_scope),
        ("status + classification", validate_status_classification),
        ("scene association", validate_scene_association),
        ("no guess language", validate_no_guess_language),
        ("owner", validate_owner),
        ("update_trigger", validate_update_trigger),
    ]

    failed = []
    for name, fn in checks:
        ok, msg = fn(data)
        if not ok:
            failed.append(f"  FAIL [{name}]: {msg}")

    if failed:
        print(f"VALIDATION FAILED: {yaml_path}")
        for f in failed:
            print(f)
        return 1
    else:
        print(f"PASS: {yaml_path}")
        return 0

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python3 validate_memory.py <yaml_file>")
        sys.exit(1)
    sys.exit(validate_memory_entry(sys.argv[1]))
