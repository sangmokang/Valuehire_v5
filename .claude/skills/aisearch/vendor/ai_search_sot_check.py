#!/usr/bin/env python3
"""Check Valuehire AI Search SOT files and report stage/dependency status."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

EXPECTED_CLICKUP_LIST_ID = "901818680208"
EXPECTED_CLICKUP_LIST_NAME = "FY26AI_Search"
EXPECTED_CLICKUP_LIST_URL = "https://app.clickup.com/9018789656/v/li/901818680208"
EXPECTED_CLICKUP_STRUCTURE = "position_parent_task + candidate_subtasks"
EXPECTED_PROFILE_SAVE_EVIDENCE_FIELDS = ("evidence",)
REQUIRED_CLICKUP_FAIL_CLOSED = {
    "wrong_list_id",
    "duplicate_check_missing",
    "profile_save_evidence_missing",
    "invalid_profile_url",
    "missing_profile_url",
    "missing_required_output_field",
}
REQUIRED_CLICKUP_OUTPUT_FIELDS = {
    "profile_url",
    "score",
    "why_fit",
    "profile_summary",
    "saved_profile_evidence",
}


REQUIRED_FILES = (
    "CLAUDE.md",
    "docs/sot/22-talent-search-filters.json",
    "docs/sot/22-talent-search-filters.md",
    "docs/sot/24-position-jd-sot.json",
    "docs/sot/25-ai-search-execution-process.json",
    "docs/sot/25-ai-search-execution-process.md",
    "docs/sot/26-portal-login-spec.json",
    "skills/humansearch/humansearch.config.json",
    "tools/multi_position_sourcing/models.py",
    "tools/multi_position_sourcing/humansearch_register.py",
    "tools/multi_position_sourcing/scoring.py",
    "tools/multi_position_sourcing/channel_search_render.py",
    "tools/multi_position_sourcing/queue_runner.py",
    "tools/multi_position_sourcing/portal_autologin.py",
    "tools/multi_position_sourcing/portal_live_check.py",
    "scripts/run_portal_search.py",
)


def load_json(path: Path) -> dict[str, object]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a JSON object")
    return data


def load_python_constant(path: Path, name: str) -> object:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id == name:
                return ast.literal_eval(node.value)
    raise ValueError(f"{name} not found in {path}")


def require_equal(errors: list[str], source: str, key: str, actual: object, expected: object) -> None:
    if actual != expected:
        errors.append(f"{source}.{key}: expected {expected!r}, got {actual!r}")


def require_true(errors: list[str], source: str, key: str, actual: object) -> None:
    if actual is not True:
        errors.append(f"{source}.{key}: expected True, got {actual!r}")


def require_contains_all(
    errors: list[str],
    source: str,
    key: str,
    actual: object,
    expected: set[str],
) -> None:
    if not isinstance(actual, list):
        errors.append(f"{source}.{key}: expected list, got {type(actual).__name__}")
        return
    missing = sorted(expected - {str(item) for item in actual})
    if missing:
        errors.append(f"{source}.{key}: missing {missing}")


def check_clickup_registration_contract(
    repo: Path,
    process: dict[str, object],
) -> list[str]:
    errors: list[str] = []

    contract = process.get("clickup_registration_contract")
    if not isinstance(contract, dict):
        return ["docs/sot/25-ai-search-execution-process.json.clickup_registration_contract missing"]

    require_equal(errors, "sot25.clickup_registration_contract", "list_id", contract.get("list_id"), EXPECTED_CLICKUP_LIST_ID)
    require_equal(errors, "sot25.clickup_registration_contract", "list_name", contract.get("list_name"), EXPECTED_CLICKUP_LIST_NAME)
    require_equal(errors, "sot25.clickup_registration_contract", "list_url", contract.get("list_url"), EXPECTED_CLICKUP_LIST_URL)
    require_equal(errors, "sot25.clickup_registration_contract", "structure", contract.get("structure"), EXPECTED_CLICKUP_STRUCTURE)
    require_true(errors, "sot25.clickup_registration_contract", "target_list_required", contract.get("target_list_required"))
    require_true(errors, "sot25.clickup_registration_contract", "kanban_record_required", contract.get("kanban_record_required"))
    require_true(errors, "sot25.clickup_registration_contract", "duplicate_check_required", contract.get("duplicate_check_required"))
    require_true(
        errors,
        "sot25.clickup_registration_contract",
        "profile_save_evidence_required",
        contract.get("profile_save_evidence_required"),
    )
    require_contains_all(errors, "sot25.clickup_registration_contract", "applies_to", contract.get("applies_to"), {"ai_search", "humansearch"})
    require_contains_all(
        errors,
        "sot25.clickup_registration_contract",
        "duplicate_scope",
        contract.get("duplicate_scope"),
        {"position_parent_task", "candidate_profile_url_subtask"},
    )
    require_contains_all(
        errors,
        "sot25.clickup_registration_contract",
        "candidate_subtask_required_fields",
        contract.get("candidate_subtask_required_fields"),
        REQUIRED_CLICKUP_OUTPUT_FIELDS,
    )
    require_contains_all(
        errors,
        "sot25.clickup_registration_contract",
        "fail_closed_on",
        contract.get("fail_closed_on"),
        REQUIRED_CLICKUP_FAIL_CLOSED,
    )
    require_equal(
        errors,
        "sot25.clickup_registration_contract",
        "profile_save_evidence_fields",
        tuple(contract.get("profile_save_evidence_fields", ())),
        EXPECTED_PROFILE_SAVE_EVIDENCE_FIELDS,
    )

    cfg_path = repo / "skills/humansearch/humansearch.config.json"
    try:
        config = load_json(cfg_path)
        reg = config.get("clickup_registration")
        if not isinstance(reg, dict):
            errors.append("skills/humansearch/humansearch.config.json.clickup_registration missing")
        else:
            require_equal(errors, "humansearch.config.clickup_registration", "list_id", reg.get("list_id"), EXPECTED_CLICKUP_LIST_ID)
            require_equal(errors, "humansearch.config.clickup_registration", "list_name", reg.get("list_name"), EXPECTED_CLICKUP_LIST_NAME)
            require_equal(errors, "humansearch.config.clickup_registration", "list_url", reg.get("list_url"), EXPECTED_CLICKUP_LIST_URL)
            require_equal(errors, "humansearch.config.clickup_registration", "structure", reg.get("structure"), EXPECTED_CLICKUP_STRUCTURE)
            require_true(errors, "humansearch.config.clickup_registration", "target_list_required", reg.get("target_list_required"))
            require_true(errors, "humansearch.config.clickup_registration", "kanban_record_required", reg.get("kanban_record_required"))
            require_true(errors, "humansearch.config.clickup_registration", "duplicate_check_required", reg.get("duplicate_check_required"))
            require_true(
                errors,
                "humansearch.config.clickup_registration",
                "profile_save_evidence_required",
                reg.get("profile_save_evidence_required"),
            )
            require_contains_all(errors, "humansearch.config.clickup_registration", "applies_to", reg.get("applies_to"), {"ai_search", "humansearch"})
            require_contains_all(
                errors,
                "humansearch.config.clickup_registration",
                "duplicate_scope",
                reg.get("duplicate_scope"),
                {"position_parent_task", "candidate_profile_url_subtask"},
            )
            require_contains_all(
                errors,
                "humansearch.config.clickup_registration",
                "subtask_requires",
                reg.get("subtask_requires"),
                REQUIRED_CLICKUP_OUTPUT_FIELDS,
            )
            require_contains_all(
                errors,
                "humansearch.config.clickup_registration",
                "fail_closed_on",
                reg.get("fail_closed_on"),
                REQUIRED_CLICKUP_FAIL_CLOSED,
            )
            require_equal(
                errors,
                "humansearch.config.clickup_registration",
                "profile_save_evidence_fields",
                tuple(reg.get("profile_save_evidence_fields", ())),
                EXPECTED_PROFILE_SAVE_EVIDENCE_FIELDS,
            )
    except Exception as exc:  # noqa: BLE001 - diagnostics script
        errors.append(f"humansearch.config: {exc}")

    register_path = repo / "tools/multi_position_sourcing/humansearch_register.py"
    try:
        require_equal(
            errors,
            "humansearch_register",
            "FY26_AI_SEARCH_LIST_ID",
            load_python_constant(register_path, "FY26_AI_SEARCH_LIST_ID"),
            EXPECTED_CLICKUP_LIST_ID,
        )
        require_equal(
            errors,
            "humansearch_register",
            "FY26_AI_SEARCH_LIST_URL",
            load_python_constant(register_path, "FY26_AI_SEARCH_LIST_URL"),
            EXPECTED_CLICKUP_LIST_URL,
        )
        require_equal(
            errors,
            "humansearch_register",
            "PROFILE_SAVE_EVIDENCE_FIELDS",
            tuple(load_python_constant(register_path, "PROFILE_SAVE_EVIDENCE_FIELDS")),
            EXPECTED_PROFILE_SAVE_EVIDENCE_FIELDS,
        )
    except Exception as exc:  # noqa: BLE001 - diagnostics script
        errors.append(f"humansearch_register constants: {exc}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="/Users/kangsangmo/Valuehire_v5")
    args = parser.parse_args()

    repo = Path(args.repo).expanduser().resolve()
    print(f"repo={repo}")

    missing: list[str] = []
    for relative in REQUIRED_FILES:
        path = repo / relative
        print(f"{'OK' if path.exists() else 'MISSING'} {relative}")
        if not path.exists():
            missing.append(relative)

    json_errors: list[str] = []
    specs: dict[str, dict[str, object]] = {}
    for relative in (
        "docs/sot/22-talent-search-filters.json",
        "docs/sot/24-position-jd-sot.json",
        "docs/sot/25-ai-search-execution-process.json",
        "docs/sot/26-portal-login-spec.json",
    ):
        path = repo / relative
        if not path.exists():
            continue
        try:
            specs[relative] = load_json(path)
            print(f"JSON_OK {relative}")
        except Exception as exc:  # noqa: BLE001 - diagnostics script
            json_errors.append(f"{relative}: {exc}")
            print(f"JSON_ERROR {relative}: {exc}")

    process = specs.get("docs/sot/25-ai-search-execution-process.json", {})
    stages = process.get("stages", [])
    if isinstance(stages, list):
        stage_ids = [
            str(stage.get("id"))
            for stage in stages
            if isinstance(stage, dict) and stage.get("id")
        ]
        print("stage_ids=" + ",".join(stage_ids))

    depends_on = process.get("depends_on", [])
    dead_refs: list[str] = []
    if isinstance(depends_on, list):
        for item in depends_on:
            if not isinstance(item, str):
                continue
            if item.startswith(".env"):
                continue
            if not (repo / item).exists():
                dead_refs.append(item)
        if dead_refs:
            print("DEAD_REFS " + ",".join(dead_refs))

    clickup_errors = check_clickup_registration_contract(repo, process) if process else []
    for error in clickup_errors:
        print(f"CLICKUP_CONTRACT_ERROR {error}")
    if not clickup_errors:
        print(f"CLICKUP_CONTRACT_OK list_id={EXPECTED_CLICKUP_LIST_ID} url={EXPECTED_CLICKUP_LIST_URL}")

    if missing or json_errors or clickup_errors:
        print("status=FAIL")
        return 1

    print("status=OK")
    if dead_refs:
        print("note=Some SOT dependencies are missing but the practical contract remains embedded in SOT 24/25.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
