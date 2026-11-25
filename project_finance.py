"""Deterministic, pre-tax and unlevered ten-year project finance model."""

import json
from math import exp, expm1, fsum, isclose, isfinite, log

from calc_engine import (
    calc_annual_event_income,
    calc_annual_rental_income,
    calc_annual_revenue_share_income,
    calc_annual_ticket_income,
    calc_annual_venue_rental_income,
)
from space_model import ALLOCATION_CAPACITY, NO_REVENUE, SpaceProject, validate_space_project


SCENARIOS = ("conservative", "base", "optimistic")
OPERATING_YEARS = 10
REVENUE_FIELDS = {
    "租金": ("leasable_area_sqm", "avg_rent_per_sqm_month", "occupancy_rate"),
    "分账": ("base_sales_estimate_annual", "revenue_share_ratio"),
    "门票": ("annual_visitors", "avg_ticket_price"),
    "活动收入": ("annual_events", "event_income_per_event"),
    "场租": ("annual_venue_rentals", "venue_rental_per_event"),
}
REVENUE_FORMULAS = {
    "租金": calc_annual_rental_income,
    "分账": calc_annual_revenue_share_income,
    "门票": calc_annual_ticket_income,
    "活动收入": calc_annual_event_income,
    "场租": calc_annual_venue_rental_income,
}
MODEL_LIMITS = [
    "人民币项目现金流，建设投资全部发生在第0年，第1至10年经营参数固定。",
    "综合运营成本及经营收入按项目投资运营主体承担或取得的口径输入。",
    "不含土地购置、融资、税费、分期建设、追加投资、期末残值和其他未列开发成本。",
]


class _InputError(ValueError):
    def __init__(self, path: str, message: str):
        self.issue = {"path": path, "message": message}
        super().__init__(message)


def _check_fields(value: object, path: str, required, optional=()) -> None:
    if not isinstance(value, dict):
        raise _InputError(path, "必须是对象")
    for field in required:
        if field not in value:
            raise _InputError(f"{path}.{field}", "缺少必填字段，零值须显式提供")
    for field in value:
        if field not in required and field not in optional:
            raise _InputError(f"{path}.{field}", "未知或未启用的字段")


def _number(value: object, path: str, *, ratio: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _InputError(path, "必须为有限且非负的数值")
    try:
        number = float(value)
    except OverflowError:
        raise _InputError(path, "数值超出有限范围") from None
    if not isfinite(number) or number < 0:
        raise _InputError(path, "必须为有限且非负的数值")
    if ratio and number > 1:
        raise _InputError(path, "必须为0至1之间的小数")
    return number


def _read_scenario(raw: dict, path: str, units: list) -> dict:
    _check_fields(raw, path, ("demolition_cost_per_sqm", "discount_rate", "units"),
                  ("parameter_evidence",))
    result = {
        field: _number(raw[field], f"{path}.{field}")
        for field in ("demolition_cost_per_sqm", "discount_rate")
    }
    if "parameter_evidence" in raw:
        evidence = raw["parameter_evidence"]
        if not isinstance(evidence, dict):
            raise _InputError(f"{path}.parameter_evidence", "必须是 JSON 对象")
        try:
            result["parameter_evidence"] = json.loads(json.dumps(evidence, allow_nan=False))
        except (TypeError, ValueError, OverflowError, RecursionError):
            raise _InputError(f"{path}.parameter_evidence", "必须可序列化为有限值 JSON") from None

    ids = [unit["unit_id"].strip() for unit in units]
    _check_fields(raw["units"], f"{path}.units", ids)
    result["units"] = {}
    for unit, unit_id in zip(units, ids):
        unit_path = f"{path}.units.{unit_id}"
        params = raw["units"][unit_id]
        _check_fields(params, unit_path, ("capex_per_sqm", "annual_opex_per_sqm", "revenue"))
        normalized = {
            field: _number(params[field], f"{unit_path}.{field}")
            for field in ("capex_per_sqm", "annual_opex_per_sqm")
        }
        sources = [source for source in unit["revenue_sources"] if source != NO_REVENUE]
        revenue_path = f"{unit_path}.revenue"
        _check_fields(params["revenue"], revenue_path, sources)
        normalized["revenue"] = {}
        for source in sources:
            source_path = f"{revenue_path}.{source}"
            fields = REVENUE_FIELDS[source]
            values = params["revenue"][source]
            _check_fields(values, source_path, fields)
            numbers = {
                field: _number(values[field], f"{source_path}.{field}",
                               ratio=field in ("occupancy_rate", "revenue_share_ratio"))
                for field in fields
            }
            if source == "租金":
                leasable = numbers["leasable_area_sqm"]
                area = unit["area_sqm"]
                if leasable > area:
                    raise _InputError(f"{source_path}.leasable_area_sqm", "可出租面积超过功能面积")
            normalized["revenue"][source] = numbers
        result["units"][unit_id] = normalized
    return result


def _irr(capex: float, annual_net: float) -> tuple[float | None, str | None]:
    """Solve the unique IRR for one initial outflow and ten equal inflows."""
    if capex == 0:
        reason = "all_cashflows_zero" if annual_net == 0 else "no_initial_investment"
        return None, reason
    if annual_net <= 0:
        return None, "no_positive_operating_cashflow"

    # Solve in x = log(1+r). Log-sum-exp keeps evaluations finite close
    # to r=-1 and at very high positive rates. The sum decreases with x.
    target = log(capex) - log(annual_net)
    bound = abs(target) + log(OPERATING_YEARS) + 1
    low, high = -bound, bound
    for _ in range(80):
        mid = (low + high) / 2
        exponents = [-year * mid for year in range(1, OPERATING_YEARS + 1)]
        peak = max(exponents)
        log_discount_sum = peak + log(fsum(exp(value - peak) for value in exponents))
        if log_discount_sum > target:
            low = mid
        else:
            high = mid
    try:
        rate = expm1((low + high) / 2)
    except OverflowError:
        return None, "irr_outside_numeric_range"
    if not isfinite(rate) or rate <= -1:
        return None, "irr_outside_numeric_range"
    return rate, None


def _cashflow_metrics(capex: float, revenue: float, opex: float, rate: float) -> dict:
    annual_net = revenue - opex
    cashflows = [-capex] + [annual_net] * OPERATING_YEARS
    discount_factor = 1 / (1 + rate)
    npv = fsum(cashflow * discount_factor**year for year, cashflow in enumerate(cashflows))
    irr, reason = _irr(capex, annual_net)
    years = [
        {
            "year": year,
            "capex": capex if year == 0 else 0.0,
            "revenue": revenue if year else 0.0,
            "opex": opex if year else 0.0,
            "net_cashflow": cashflow,
            "cumulative_cashflow": fsum(cashflows[:year + 1]),
        }
        for year, cashflow in enumerate(cashflows)
    ]
    return {
        "discount_rate": rate,
        "cashflows": years,
        "npv": npv,
        "irr": irr,
        "irr_reason": reason,
        "cumulative_undiscounted_net_cashflow": years[-1]["cumulative_cashflow"],
    }


def _calculate_scenario(params: dict, units: list, demolished_area: float) -> dict:
    unit_results = []
    investment_by_method = {method: [] for method in ALLOCATION_CAPACITY}
    project_revenue = {}
    for unit in units:
        unit_id = unit["unit_id"].strip()
        values = params["units"][unit_id]
        area = float(unit["area_sqm"])
        method = unit["construction_method"]
        capex = area * values["capex_per_sqm"]
        opex = area * values["annual_opex_per_sqm"]
        income = {}
        for source, numbers in values["revenue"].items():
            if source == "场租":
                # The legacy formula's count key is shared with event income.
                # Supply the independent venue count only to this invocation.
                numbers = {**numbers, "annual_events": numbers["annual_venue_rentals"]}
            income[source] = float(REVENUE_FORMULAS[source](numbers))
        revenue = fsum(income.values())
        investment_by_method[method].append(capex)
        for source, amount in income.items():
            project_revenue.setdefault(source, []).append(amount)
        unit_results.append({
            "unit_id": unit_id,
            "function": unit["function"],
            "space_type": unit["space_type"],
            "construction_method": method,
            "operating_method": unit["operating_method"],
            "revenue_sources": list(unit["revenue_sources"]),
            "area_sqm": area,
            "area_basis": "building_floor_area" if unit["space_type"] == "indoor" else "outdoor_ground_area",
            "capex": capex,
            "annual_opex": opex,
            "annual_revenue_by_source": income,
            "annual_revenue": revenue,
            "annual_operating_net_cashflow": revenue - opex,
        })
    by_method = {method: fsum(amounts) for method, amounts in investment_by_method.items()}
    demolition_rate = params["demolition_cost_per_sqm"]
    demolition = demolished_area * demolition_rate
    total_capex = fsum([demolition, *by_method.values()])
    total_revenue = fsum(unit["annual_revenue"] for unit in unit_results)
    total_opex = fsum(unit["annual_opex"] for unit in unit_results)
    result = {
        "capex": {
            "demolition": {
                "area_sqm": demolished_area, "area_basis": "building_floor_area",
                "cost_per_sqm": demolition_rate, "capex": demolition,
            },
            "by_construction_method": by_method,
            "total": total_capex,
        },
        "units": unit_results,
        "annual_operations": {
            "revenue_by_source": {source: fsum(amounts) for source, amounts in project_revenue.items()},
            "revenue": total_revenue,
            "opex": total_opex,
            "net_cashflow": total_revenue - total_opex,
        },
        **_cashflow_metrics(total_capex, total_revenue, total_opex, params["discount_rate"]),
    }
    if "parameter_evidence" in params:
        result["parameter_evidence"] = params["parameter_evidence"]
    return result


def calculate_project_finance(project: SpaceProject, scenarios: dict) -> dict:
    """Measure one confirmed space plan under three sets of financial inputs.

    See docs/product_spec.md for the parameter schema and examples. Returns a
    JSON-safe dict with status, scenarios, warnings and field-level errors.
    """
    result = {
        "status": "error",
        "currency": "CNY",
        "operating_years": OPERATING_YEARS,
        "scenarios": {},
        "model_limits": list(MODEL_LIMITS),
        "warnings": [],
        "errors": [],
    }
    space = validate_space_project(project)
    if not space["valid"] or space["status"] != "confirmed":
        result["errors"].extend(
            {
                "path": "project" if issue["path"] == "project" else f"project.{issue['path']}",
                "message": issue["message"],
            }
            for issue in space["errors"]
        )
        if space["status"] != "confirmed":
            result["errors"].append({"path": "project.status", "message": "空间方案须正式确认"})
        return result

    for index, unit in enumerate(project["units"]):
        for source in unit["revenue_sources"]:
            if source != NO_REVENUE and source not in REVENUE_FIELDS:
                result["errors"].append({
                    "path": f"project.units[{index}].revenue_sources",
                    "message": f"财务模型暂不支持「{source}」",
                })
    if result["errors"]:
        return result

    try:
        _check_fields(scenarios, "scenarios", SCENARIOS)
    except _InputError as exc:
        result["errors"].append(exc.issue)
        return result
    calculated = {}
    for name in SCENARIOS:
        path = f"scenarios.{name}"
        try:
            params = _read_scenario(scenarios[name], path, project["units"])
            scenario = _calculate_scenario(
                params, project["units"], space["areas"]["demolished_building_area_sqm"]
            )
            json.dumps(scenario, allow_nan=False)
            calculated[name] = scenario
        except _InputError as exc:
            result["errors"].append(exc.issue)
        except (OverflowError, ValueError):
            result["errors"].append({"path": path, "message": "计算结果超出有限数值范围"})
    if result["errors"]:
        return result

    for metric in ("npv", "irr", "cumulative_undiscounted_net_cashflow"):
        values = [calculated[name][metric] for name in SCENARIOS]
        if all(value is not None for value in values) and any(
            left > right and not isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)
            for left, right in zip(values, values[1:])
        ):
            result["warnings"].append({
                "code": "scenario_order", "metric": metric,
                "message": "结果未按保守、基准、乐观顺序递增，请检查参数口径和假设。",
            })
    result["status"] = "ok"
    result["scenarios"] = calculated
    return result
