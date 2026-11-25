"""Validate a project and its indoor/outdoor functional area allocation in sqm."""

from math import isclose, isfinite
from typing import Literal, NotRequired, TypedDict


Space = Literal["indoor", "outdoor"]
Construction = Literal["renovate", "new_build", "outdoor_build"]
AREA_TOLERANCE_SQM = 1e-8  # Absolute tolerance for floating-point rounding only.
CONSTRUCTION_BY_SPACE = {
    "indoor": ("renovate", "new_build"),
    "outdoor": ("outdoor_build",),
}
ALLOCATION_CAPACITY = {
    "renovate": "retained_building_area_sqm",
    "new_build": "new_building_area_sqm",
    "outdoor_build": "allocatable_outdoor_area_sqm",
}
NO_REVENUE = "无直接收入"
HOUSING_TYPES = ("长租公寓", "保障性租赁住房", "商品住宅")


class ProjectAreas(TypedDict):
    site_area_sqm: float
    existing_building_area_sqm: float
    existing_footprint_sqm: float
    demolished_building_area_sqm: float
    demolished_footprint_sqm: float
    new_building_area_sqm: float
    new_footprint_sqm: float


class FunctionalUnit(TypedDict):
    unit_id: str
    space_type: Space
    construction_method: Construction
    function: str
    area_sqm: float
    operating_method: str
    revenue_sources: list[str]
    housing_type: NotRequired[str]
    planning_confirmed: NotRequired[bool]
    sale_conditions_confirmed: NotRequired[bool]


class SpaceProject(TypedDict):
    city: str
    background: str
    renewal_goal: str
    planning_constraints: list[str]
    areas: ProjectAreas
    units: list[FunctionalUnit]
    status: NotRequired[Literal["draft", "confirmed"]]


class ValidationIssue(TypedDict):
    path: str
    message: str


class AreaValidationError(ValueError):
    """Invalid input to calculate_project_areas(), with field-level errors."""

    def __init__(self, issues: list[ValidationIssue]):
        self.issues = issues
        super().__init__("，".join(f"{issue['path']} {issue['message']}" for issue in issues))


def _rule(spaces, operating_methods, revenue_sources):
    return {
        "spaces": spaces,
        "construction_methods": tuple(
            method for space in spaces for method in CONSTRUCTION_BY_SPACE[space]
        ),
        "operating_methods": operating_methods,
        "revenue_sources": revenue_sources,
    }


INDOOR = ("indoor",)
OUTDOOR = ("outdoor",)
BOTH = ("indoor", "outdoor")
COMMERCIAL = ("出租", "自营", "委托")
PUBLIC_MAINTENANCE = ("公益", "委托维护")
FUNCTION_CONFIG = {
    "生产": _rule(INDOOR, COMMERCIAL, ("租金", "生产销售", "加工服务")),
    "研发": _rule(INDOOR, COMMERCIAL, ("租金", "研发服务")),
    "办公与工作室": _rule(INDOOR, COMMERCIAL, ("租金", "工位费", "服务费")),
    "仓储": _rule(INDOOR, COMMERCIAL, ("租金", "仓储服务")),
    "零售": _rule(BOTH, COMMERCIAL, ("租金", "分账", "商品销售")),
    "餐饮": _rule(BOTH, COMMERCIAL, ("租金", "分账", "餐饮销售")),
    "生活服务": _rule(INDOOR, COMMERCIAL, ("租金", "服务收费")),
    "住宿": _rule(INDOOR, COMMERCIAL, ("客房收入", "服务收入", "租金")),
    "展览": _rule(BOTH, ("自营", "委托", "公益"), ("门票", "体验收费", "场租")),
    "活动与演艺": _rule(BOTH, COMMERCIAL, ("门票", "活动收入", "场租")),
    "娱乐体验": _rule(BOTH, COMMERCIAL, ("体验收费", "会员费", "场租")),
    "体育": _rule(BOTH, (*COMMERCIAL, "公益"), ("场地收费", "会员费", "课程费")),
    "教育培训": _rule(BOTH, (*COMMERCIAL, "公益"), ("培训费", "课程费", "场租")),
    "居住": _rule(INDOOR, ("持有出租", "委托", "开发销售"), ("租金", "服务费", "房屋销售")),
    "公共服务": _rule(BOTH, ("公益", "自营", "委托"), (NO_REVENUE, "服务收费")),
    "广场": _rule(OUTDOOR, ("公益", "自营", "委托"), (NO_REVENUE, "活动收入", "场租")),
    "绿地": _rule(OUTDOOR, PUBLIC_MAINTENANCE, (NO_REVENUE,)),
    "停车": _rule(BOTH, COMMERCIAL, ("停车费", "租金", "充电服务费")),
    "道路": _rule(OUTDOOR, PUBLIC_MAINTENANCE, (NO_REVENUE,)),
    "后勤设施": _rule(BOTH, ("自营", "委托维护"), (NO_REVENUE,)),
}


def _issue(issues: list[ValidationIssue], path: str, message: str) -> None:
    issues.append({"path": path, "message": message})


def _area(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        number = float(value)
    except OverflowError:
        return None
    return number if isfinite(number) and number >= 0 else None


def _text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _same_area(first: float, second: float) -> bool:
    return isclose(first, second, rel_tol=0, abs_tol=AREA_TOLERANCE_SQM)


def calculate_project_areas(areas: ProjectAreas) -> dict[str, float]:
    """Return submitted and derived areas, or raise AreaValidationError."""
    if not isinstance(areas, dict):
        raise AreaValidationError([{"path": "areas", "message": "必须是对象"}])

    issues: list[ValidationIssue] = []
    values: dict[str, float] = {}
    for field in ProjectAreas.__annotations__:
        value = _area(areas.get(field))
        if value is None:
            _issue(issues, f"areas.{field}", "必须填写有限且非负的数值（平方米）")
        else:
            values[field] = value
    if issues:
        raise AreaValidationError(issues)

    site = values["site_area_sqm"]
    existing = values["existing_building_area_sqm"]
    existing_footprint = values["existing_footprint_sqm"]
    demolished = values["demolished_building_area_sqm"]
    demolished_footprint = values["demolished_footprint_sqm"]
    new = values["new_building_area_sqm"]
    new_footprint = values["new_footprint_sqm"]

    if demolished > existing:
        _issue(issues, "areas.demolished_building_area_sqm", "拆除建筑面积超过原有建筑面积")
    if demolished_footprint > existing_footprint:
        _issue(issues, "areas.demolished_footprint_sqm", "拆除基底面积超过原有基底面积")
    if existing_footprint > site:
        _issue(issues, "areas.existing_footprint_sqm", "原有建筑基底超过地块面积")
    if issues:
        raise AreaValidationError(issues)

    retained = existing - demolished
    retained_footprint = existing_footprint - demolished_footprint
    for label, field, building, footprint in (
        ("原有", "existing_footprint_sqm", existing, existing_footprint),
        ("拆除", "demolished_footprint_sqm", demolished, demolished_footprint),
        ("新建", "new_footprint_sqm", new, new_footprint),
        ("保留", "retained_footprint_sqm", retained, retained_footprint),
    ):
        if footprint > building and not _same_area(footprint, building):
            _issue(issues, f"areas.{field}", f"{label}建筑基底不能大于对应建筑面积")
    post_building = retained + new
    post_footprint = retained_footprint + new_footprint
    if not isfinite(post_building):
        _issue(issues, "areas.post_renewal_building_area_sqm", "改造后建筑面积超出有限数值范围")
    if post_footprint > site and not _same_area(post_footprint, site):
        _issue(issues, "areas.post_renewal_footprint_sqm", "改造后建筑基底超过地块面积")
    if issues:
        raise AreaValidationError(issues)

    return {
        **values,
        "retained_building_area_sqm": retained,
        "retained_footprint_sqm": retained_footprint,
        "post_renewal_building_area_sqm": post_building,
        "post_renewal_footprint_sqm": post_footprint,
        "allocatable_outdoor_area_sqm": max(0.0, site - post_footprint),
    }


def _validate_unit(unit: FunctionalUnit, path: str, issues: list[ValidationIssue]) -> None:
    if not _text(unit.get("unit_id")):
        _issue(issues, f"{path}.unit_id", "必须填写非空字符串")
    amount = _area(unit.get("area_sqm"))
    if amount is None or amount == 0:
        _issue(issues, f"{path}.area_sqm", "必须填写有限且大于零的功能面积")

    space = unit.get("space_type")
    construction = unit.get("construction_method")
    function = unit.get("function")
    operating = unit.get("operating_method")
    if space not in BOTH:
        _issue(issues, f"{path}.space_type", "必须为 indoor 或 outdoor")
    elif construction not in CONSTRUCTION_BY_SPACE[space]:
        _issue(issues, f"{path}.construction_method", "建设方式与室内外类型不匹配")

    rule = FUNCTION_CONFIG.get(function) if isinstance(function, str) else None
    if rule is None:
        _issue(issues, f"{path}.function", "必须使用已配置的功能")
    else:
        if space in BOTH and space not in rule["spaces"]:
            _issue(issues, f"{path}.space_type", f"{function}不适用于此室内外类型")
        if operating not in rule["operating_methods"]:
            _issue(issues, f"{path}.operating_method", f"{function}不支持此经营方式")

    sources = unit.get("revenue_sources")
    if not isinstance(sources, list) or not sources or any(not _text(item) for item in sources):
        _issue(issues, f"{path}.revenue_sources", "必须填写一个或多个收入项，无收入时使用「无直接收入」")
        sources = []
    if len(set(sources)) != len(sources):
        _issue(issues, f"{path}.revenue_sources", "收入项不能重复")
    if NO_REVENUE in sources and len(sources) > 1:
        _issue(issues, f"{path}.revenue_sources", "「无直接收入」必须单独使用")
    if rule:
        for index, source in enumerate(sources):
            if source != NO_REVENUE and source not in rule["revenue_sources"]:
                _issue(issues, f"{path}.revenue_sources[{index}]", f"{function}未配置此收入项")
            if operating in ("出租", "持有出租") and source in ("生产销售", "商品销售", "餐饮销售", "客房收入"):
                _issue(issues, f"{path}.revenue_sources[{index}]", "出租空间不能把租户营业收入计为园区收入")

    if function == "居住":
        if "housing_type" in unit and unit["housing_type"] not in HOUSING_TYPES:
            _issue(issues, f"{path}.housing_type", "必须为长租公寓、保障性租赁住房或商品住宅")
        if operating == "开发销售" or "房屋销售" in sources:
            if operating != "开发销售" or sources != ["房屋销售"]:
                _issue(issues, f"{path}.revenue_sources", "住宅开发销售必须单独使用「房屋销售」")
            if unit.get("housing_type") != "商品住宅":
                _issue(issues, f"{path}.housing_type", "仅商品住宅可按开发销售登记")
            for field in ("planning_confirmed", "sale_conditions_confirmed"):
                if unit.get(field) is not True:
                    _issue(issues, f"{path}.{field}", "住宅开发销售须确认此条件")


def validate_space_project(project: SpaceProject) -> dict:
    """Return validation issues and the draft/confirmed allocation balances.

    An invalid area model or unit list yields allocation=None. With valid units,
    over-allocation is reported separately from unused capacity in each bucket.
    """
    issues: list[ValidationIssue] = []
    result = {"status": None, "valid": False, "areas": None, "allocation": None, "errors": issues}
    if not isinstance(project, dict):
        _issue(issues, "project", "必须是对象")
        return result

    status = project.get("status", "draft")
    if status in ("draft", "confirmed"):
        result["status"] = status
    else:
        _issue(issues, "status", "必须为 draft 或 confirmed")
    for field in ("city", "background", "renewal_goal"):
        if not _text(project.get(field)):
            _issue(issues, field, "必须填写非空字符串")
    constraints = project.get("planning_constraints")
    if not isinstance(constraints, list) or any(not _text(item) for item in constraints):
        _issue(issues, "planning_constraints", "必须为字符串列表，可用空列表表示暂无约束记录")

    try:
        result["areas"] = calculate_project_areas(project.get("areas"))
    except AreaValidationError as exc:
        issues.extend(exc.issues)

    units = project.get("units")
    if not isinstance(units, list):
        _issue(issues, "units", "必须是列表，空草稿可传 []")
        return result

    allocated = dict.fromkeys(ALLOCATION_CAPACITY, 0.0)
    seen_ids: set[str] = set()
    unit_issues_start = len(issues)
    for index, unit in enumerate(units):
        path = f"units[{index}]"
        if not isinstance(unit, dict):
            _issue(issues, path, "必须是对象")
            continue
        before = len(issues)
        _validate_unit(unit, path, issues)
        unit_id = unit.get("unit_id")
        if _text(unit_id):
            normalized_id = unit_id.strip()
            if normalized_id in seen_ids:
                _issue(issues, f"{path}.unit_id", "单元 ID 重复")
            seen_ids.add(normalized_id)
        if len(issues) == before:
            method = unit["construction_method"]
            allocated[method] += float(unit["area_sqm"])
            if not isfinite(allocated[method]):
                _issue(issues, f"allocation.{method}", "功能面积合计超出有限数值范围")

    if result["areas"] is None or len(issues) != unit_issues_start:
        return result

    allocation = {}
    for method, capacity_field in ALLOCATION_CAPACITY.items():
        capacity = result["areas"][capacity_field]
        used = allocated[method]
        difference = 0.0 if _same_area(capacity, used) else capacity - used
        allocation[method] = {
            "available_area_sqm": capacity,
            "allocated_area_sqm": used,
            "remaining_area_sqm": max(0.0, difference),
            "overallocated_area_sqm": max(0.0, -difference),
        }
        if difference < 0:
            _issue(issues, f"allocation.{method}", "分配面积超过本类可用面积")
        elif difference > 0 and status == "confirmed":
            _issue(issues, f"allocation.{method}", "正式确认前必须分配完本类剩余面积")
    result["allocation"] = allocation
    result["valid"] = not issues
    return result
