"""Shared space validation and editable financial input schema."""

from copy import deepcopy
from math import isfinite
import json

from project_finance import REVENUE_FIELDS, SCENARIOS
from space_model import NO_REVENUE, validate_space_project

PROJECT_FIELDS = ("city", "background", "renewal_goal", "planning_constraints", "areas")
UNITS = {
    "demolition_cost_per_sqm": "CNY/sqm", "capex_per_sqm": "CNY/sqm",
    "annual_opex_per_sqm": "CNY/sqm/year", "discount_rate": "ratio",
    "leasable_area_sqm": "sqm", "avg_rent_per_sqm_month": "CNY/sqm/month",
    "occupancy_rate": "ratio", "base_sales_estimate_annual": "CNY/year",
    "revenue_share_ratio": "ratio", "annual_visitors": "visits/year",
    "avg_ticket_price": "CNY/visit", "annual_events": "events/year",
    "event_income_per_event": "CNY/event", "annual_venue_rentals": "rentals/year",
    "venue_rental_per_event": "CNY/rental",
}
RATIO_FIELDS = {"occupancy_rate", "revenue_share_ratio"}
USER_FIELDS = {"discount_rate", "leasable_area_sqm"}


def as_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def locked_project(project):
    """Copy the user-supplied project fields and validate a zero-allocation draft."""
    if not isinstance(project, dict):
        raise ValueError("项目输入必须是对象")
    locked = {key: deepcopy(project.get(key)) for key in PROJECT_FIELDS}
    check = validate_space_project({**locked, "status": "draft", "units": []})
    if not check["valid"]:
        raise ValueError(as_json(check["errors"]))
    return locked


def validate_finance_space(plan):
    check = validate_space_project(plan)
    units = plan.get("units") if isinstance(plan, dict) else None
    for i, unit in enumerate(units if isinstance(units, list) else []):
        if not isinstance(unit, dict) or not isinstance(unit.get("revenue_sources"), list):
            continue
        for source in unit["revenue_sources"]:
            if isinstance(source, str) and source != NO_REVENUE and source not in REVENUE_FIELDS:
                check["errors"].append({"path": f"units[{i}].revenue_sources",
                                        "message": f"本阶段财务模型不支持「{source}」"})
    check["valid"] = not check["errors"]
    return check


def parameter_catalog(project):
    """Derive finance input paths from the confirmed units and engine schema."""
    catalog = [
        {"parameter_id": "demolition_cost_per_sqm", "field": "demolition_cost_per_sqm", "unit_id": None},
        {"parameter_id": "discount_rate", "field": "discount_rate", "unit_id": None},
    ]
    for unit in project["units"]:
        unit_id = unit["unit_id"].strip()
        for field in ("capex_per_sqm", "annual_opex_per_sqm"):
            catalog.append({"parameter_id": f"units.{unit_id}.{field}", "field": field, "unit_id": unit_id})
        for source in unit["revenue_sources"]:
            for field in REVENUE_FIELDS.get(source, ()):
                catalog.append({"parameter_id": f"units.{unit_id}.revenue.{source}.{field}",
                                "unit_id": unit_id, "field": field, "revenue_source": source})
    return [{**entry, "unit": UNITS[entry["field"]]} for entry in catalog]


def _get_value(scenario, entry):
    if entry["unit_id"] is None:
        return scenario[entry["field"]]
    unit = scenario["units"][entry["unit_id"]]
    if "revenue_source" in entry:
        return unit["revenue"][entry["revenue_source"]][entry["field"]]
    return unit[entry["field"]]


def _write_value(scenario, entry, value):
    if entry["unit_id"] is None:
        scenario[entry["field"]] = value
        return
    unit = scenario["units"].setdefault(entry["unit_id"], {"revenue": {}})
    target = unit
    if "revenue_source" in entry:
        target = unit["revenue"].setdefault(entry["revenue_source"], {})
    target[entry["field"]] = value


def _empty_record(entry):
    return {**entry, "value": None, "nature": "missing", "citations": [],
            "reason": ("需要用户明确提供" if entry["field"] in USER_FIELDS else "当前缺少可靠数据"),
            "limitations": "须补录或审核后才能确认", "confirmed_by_user": False}


def empty_finance_scenarios(project):
    """Create the three scenario drafts with explicit missing values."""
    check = validate_finance_space(project)
    if not check["valid"] or project.get("status") != "confirmed":
        raise ValueError("空间方案须通过校验并由用户确认")
    catalog = {entry["parameter_id"]: entry for entry in parameter_catalog(project)}
    scenarios = {name: {"units": {}, "parameter_evidence": {
        key: _empty_record(entry) for key, entry in catalog.items()
    }} for name in SCENARIOS}
    for scenario in scenarios.values():
        for entry in catalog.values():
            _write_value(scenario, entry, None)
    return scenarios


def finance_input_issues(project, scenarios):
    """Check inputs without executing an investment calculation."""
    problems = []
    if not isinstance(scenarios, dict) or set(scenarios) != set(SCENARIOS):
        return [{"path": "scenarios", "message": "必须提供保守、基准、乐观三个情景"}]
    catalog = parameter_catalog(project)
    capacity = {unit["unit_id"].strip(): unit["area_sqm"] for unit in project["units"]}
    seen_capacity = {}
    for name in SCENARIOS:
        scenario = scenarios[name]
        prefix = f"scenarios.{name}"
        expected_units = {
            unit["unit_id"].strip(): set(unit["revenue_sources"]) - {NO_REVENUE}
            for unit in project["units"]
        }

        def check_object(value, keys, path):
            if not isinstance(value, dict) or set(value) != set(keys):
                problems.append({"path": path, "message": "字段与确认方案要求不一致"})
                return False
            return True

        required = {"discount_rate", "demolition_cost_per_sqm", "units"}
        if not isinstance(scenario, dict) or not required <= set(scenario) <= required | {"parameter_evidence"}:
            problems.append({"path": prefix, "message": "情景字段不完整或包含未启用字段"})
            continue
        if check_object(scenario["units"], expected_units, f"{prefix}.units"):
            for unit_id, sources in expected_units.items():
                unit_path = f"{prefix}.units.{unit_id}"
                unit_params = scenario["units"][unit_id]
                if check_object(unit_params, ("capex_per_sqm", "annual_opex_per_sqm", "revenue"), unit_path):
                    if check_object(unit_params["revenue"], sources, f"{unit_path}.revenue"):
                        for source in sources:
                            check_object(unit_params["revenue"][source], REVENUE_FIELDS[source],
                                         f"{unit_path}.revenue.{source}")
        for entry in catalog:
            key, field = entry["parameter_id"], entry["field"]
            path = f"scenarios.{name}.{key}"
            try:
                value = _get_value(scenario, entry)
                numeric = (type(value) in (int, float) and isfinite(value) and value >= 0)
            except (KeyError, TypeError, OverflowError):
                numeric = False
            if not numeric or (field in RATIO_FIELDS and value > 1):
                problems.append({"path": path, "message": "缺失或非法数值，请提供有效参数"})
                continue
            if field == "leasable_area_sqm":
                if value > capacity[entry["unit_id"]]:
                    problems.append({"path": path, "message": "可出租面积超过功能面积"})
                if value != seen_capacity.setdefault(key, value):
                    problems.append({"path": path, "message": "三情景的可出租面积必须相同"})
    return problems


def stamp_confirmation(project, scenarios, previous, *, simulated=False, demo=False):
    """Copy verified user inputs, replacing provenance when a value was edited."""
    catalog = parameter_catalog(project)
    # The state layer validates the finance fields before calling this helper.
    # Only program-owned evidence can carry forward to a confirmation.
    result = deepcopy(scenarios)
    for name in SCENARIOS:
        records = {}
        for entry in catalog:
            key = entry["parameter_id"]
            value = _get_value(scenarios[name], entry)
            prior = previous.get(name, {}).get("parameter_evidence", {}).get(key)
            if prior and value == prior["value"] and not demo:
                record = deepcopy(prior)
            else:
                record = {**entry, "value": value, "nature": "demo_assumption" if demo else "user_assumption",
                          "citations": [], "reason": "演示输入" if demo else "用户提供或修改",
                          "limitations": "演示假设，非市场数据" if demo else "由用户核实适用性"}
            record["confirmed_by_user"] = not (simulated or demo)
            record["confirmation"] = "simulated_user" if simulated or demo else "user"
            records[key] = record
        result[name]["parameter_evidence"] = records
    return result
