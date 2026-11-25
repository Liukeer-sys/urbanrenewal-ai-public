"""State and presentation data for the UrbanRenewal workbench."""

from copy import deepcopy
from functools import partial
from math import isfinite
from pathlib import Path
import json
import os

from demo_runtime import public_demo_enabled
from project_finance import SCENARIOS
from workbench_finance_inputs import (
    PROJECT_FIELDS, _get_value, _write_value, empty_finance_scenarios, finance_input_issues,
    locked_project, parameter_catalog, validate_finance_space,
)
from workbench_session import Stage, WorkbenchSession, WorkflowError

ROOT = Path(__file__).resolve().parent
EXAMPLES = ROOT / "examples"
DEMO_NAME = "上海旧工业园活化示范"
DEMO_MODE = "内置演示"
LIVE_MODE = "实时 AI"
CORE_UNIT_FIELDS = ("unit_id", "space_type", "construction_method", "function", "area_sqm",
                    "operating_method", "revenue_sources", "housing_type",
                    "planning_confirmed", "sale_conditions_confirmed")


def load_example(name):
    return json.loads((EXAMPLES / name).read_text(encoding="utf-8"))


def core_units(units):
    return [{key: deepcopy(unit[key]) for key in CORE_UNIT_FIELDS if key in unit} for unit in units]


def open_live_agent(project):
    """Use the same public-only request and evidence guards as the CLI demo."""
    if public_demo_enabled():
        raise WorkflowError("公开演示版仅使用离线测算")
    from chromadb.config import Settings
    from dotenv import load_dotenv
    from langchain_openai import OpenAIEmbeddings

    from public_demo_policy import PublicEvidence, check_openai_endpoint, guarded_openai_http
    from renewal_agent import RenewalAgent
    from structured_rag import RAG_ROOT, make_model, retrieve_chunks

    load_dotenv(RAG_ROOT / ".env")
    http = guarded_openai_http()
    evidence = PublicEvidence()
    try:
        model = make_model(http_client=http)
        embed = OpenAIEmbeddings(model=os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small"),
                                 http_client=http, max_retries=0, request_timeout=75)
        check_openai_endpoint(model.root_client.base_url)
        check_openai_endpoint(embed.client._client.base_url)
        agent = RenewalAgent(model, project,
                             retriever=partial(retrieve_chunks, embeddings=embed,
                                               client_settings=Settings(anonymized_telemetry=False)),
                             evidence_filter=evidence.filter)
    except Exception:
        http.close()
        raise
    return agent, http, evidence


def blank_parameters(project):
    return empty_finance_scenarios(project)


def _read(scenario, entry):
    try:
        return _get_value(scenario, entry)
    except (KeyError, TypeError):
        return None


def _valid_number(value):
    return isinstance(value, (float, int)) and not isinstance(value, bool) and isfinite(value) and value >= 0


# Alternative operations with an explicitly defined demo cost adjustment.
OPS_FACTORS = {
    "办公与工作室": {"出租": 1, "委托": 1, "自营": 1.3},
    "零售": {"出租": 1, "委托": 1, "自营": 1.4},
    "展览": {"自营": 1, "委托": 0.85, "公益": 0.9},
    "活动与演艺": {"自营": 1, "委托": 0.85, "出租": 0.75},
    "广场": {"公益": 1, "自营": 1.2, "委托": 1},
    "绿地": {"委托维护": 1, "公益": 1},
}
CONSTRUCTION_FACTORS = {("renovate", "new_build"): 1.35, ("new_build", "renovate"): 0.8}


def _demo_revenue(unit, template, sample, name):
    function = unit["function"]
    operation = unit["operating_method"]
    area = unit["area_sqm"]
    ratio = area / template["area_sqm"]
    revenue = {}
    if function in ("办公与工作室", "零售") and operation in ("出租", "委托"):
        revenue["租金"] = {**sample["revenue"]["租金"],
                            "leasable_area_sqm": min(area, round(sample["revenue"]["租金"]["leasable_area_sqm"] * ratio, 2))}
        if function == "零售":
            sales_per_sqm, share = dict(zip(SCENARIOS, ((7000, 0.03), (8500, 0.04), (10000, 0.05))))[name]
            revenue["分账"] = {"base_sales_estimate_annual": area * sales_per_sqm, "revenue_share_ratio": share}
    if function in ("展览", "活动与演艺") and operation in OPS_FACTORS[function]:
        tickets = sample["revenue"].get("门票")
        if tickets:
            revenue["门票"] = {**tickets, "annual_visitors": round(tickets["annual_visitors"] * ratio)}
    if function in ("展览", "活动与演艺", "广场"):
        count, price = dict(zip(SCENARIOS, ((12, 2000), (18, 3000), (24, 4000))))[name]
        venue = sample["revenue"].get("场租", {"annual_venue_rentals": count, "venue_rental_per_event": price})
        revenue["场租"] = {**venue, "annual_venue_rentals": round(venue["annual_venue_rentals"] * ratio)}
    if function in ("活动与演艺", "广场"):
        count, price = dict(zip(SCENARIOS, ((8, 3000), (14, 4500), (20, 6000))))[name]
        revenue["活动收入"] = {"annual_events": round(count * ratio), "event_income_per_event": price}
    return revenue


def fill_demo_parameters(project, scenarios):
    """Fill only missing fields with compatible, explicitly synthetic assumptions."""
    result = deepcopy(scenarios)
    fixture = load_example("space_project_demo.json")
    templates = {(unit["function"], unit["space_type"]): unit for unit in fixture["units"]}
    demo = load_example("project_finance_demo_scenarios.json")
    units = {unit["unit_id"].strip(): unit for unit in project["units"]}
    catalog = parameter_catalog(project)
    # Preserve an existing physical lease area across all scenarios. Do not
    # fill that field if user-provided areas conflict or exceed its unit.
    capacities = {}
    for entry in catalog:
        if entry["field"] == "leasable_area_sqm":
            values = [_read(scenarios[name], entry) for name in SCENARIOS]
            provided = {value for value in values if _valid_number(value)}
            limit = units[entry["unit_id"]]["area_sqm"]
            capacities[entry["parameter_id"]] = (next(iter(provided)) if len(provided) == 1 and max(provided) <= limit
                                                 else None if provided else "derived")
    filled = {name: {} for name in SCENARIOS}
    for name in SCENARIOS:
        for entry in catalog:
            if _read(result[name], entry) is not None:
                continue
            key, field = entry["parameter_id"], entry["field"]
            unit_id = entry["unit_id"]
            value = None
            if unit_id is None:
                value = demo[name][field]
                if field == "demolition_cost_per_sqm" and not project["areas"]["demolished_building_area_sqm"]:
                    value = 0
            else:
                unit = units[unit_id]
                template = templates.get((unit["function"], unit["space_type"]))
                if template is None or unit["operating_method"] not in OPS_FACTORS.get(unit["function"], {}):
                    continue
                # Use the fixture ID only to locate the matched template's rates.
                # Incoming unit IDs are never used to select a template.
                sample = demo[name]["units"][template["unit_id"]]
                if field == "capex_per_sqm":
                    before, after = template["construction_method"], unit["construction_method"]
                    factor = 1 if before == after else CONSTRUCTION_FACTORS.get((before, after))
                    value = round(sample[field] * factor, 2) if factor is not None else None
                elif field == "annual_opex_per_sqm":
                    value = round(sample[field] * OPS_FACTORS[unit["function"]][unit["operating_method"]], 2)
                else:
                    value = _demo_revenue(unit, template, sample, name).get(entry["revenue_source"], {}).get(field)
                    if field == "leasable_area_sqm" and capacities[key] != "derived":
                        value = capacities[key]
            if value is not None:
                _write_value(result[name], entry, value)
                filled[name][key] = value
    return result, filled


class Workbench:
    def __init__(self, *, live_factory=open_live_agent):
        self.live_factory = live_factory
        self.public_demo = public_demo_enabled()
        self.mode = DEMO_MODE
        self.project_name = DEMO_NAME
        self.project = {key: deepcopy(value) for key, value in load_example("space_project_demo.json").items()
                        if key in PROJECT_FIELDS}
        self.step = 1
        self.project_revision = self.space_revision = self.finance_revision = 0
        self.agent = self.http = self.public = None
        self.space_origin = None
        self.space_seed = []
        self.annotations = []
        self.space_issues = []
        self.scenarios = self.result = self.analysis = self.analysis_issue = None
        self.finance_warnings = []

    def _clear_finance(self):
        self.finance_revision += 1
        self.scenarios = self.result = self.analysis = self.analysis_issue = None
        self.finance_warnings = []

    def _clear_project(self):
        if self.http is not None:
            self.http.close()
        self.agent = self.http = self.public = None
        self.space_seed, self.annotations, self.space_issues = [], [], []
        self.space_origin = None
        self.space_revision += 1
        self._clear_finance()

    def update_project(self, project):
        if project != self.project:
            self._clear_project()
            self.project = deepcopy(project)
            self.step = 1

    def set_mode(self, mode):
        if mode == LIVE_MODE and self.public_demo:
            raise WorkflowError("公开演示版仅使用离线测算")
        if mode != self.mode:
            self._clear_project()
            self.mode = mode
            self.step = 1

    def reset_project(self):
        self._clear_project()
        self.project_name = ""
        self.project = {"city": "", "background": "", "renewal_goal": "", "planning_constraints": [],
                        "areas": dict.fromkeys(self.project["areas"], 0.0)}
        self.project_revision += 1
        self.step = 1

    def _accept_plan(self, plan, origin, issues=()):
        self.space_seed = core_units(plan["units"])
        self.annotations = deepcopy(plan["units"])
        self.space_origin = origin
        self.space_issues = list(issues)
        self.space_revision += 1
        self._clear_finance()
        self.step = 2

    def load_demo(self):
        self._clear_project()
        self.mode = DEMO_MODE
        self.project_name = DEMO_NAME
        fixture = load_example("space_project_demo.json")
        self.project = locked_project(fixture)
        self.project_revision += 1
        self.agent = WorkbenchSession(self.project)
        self.agent.edit_space_plan(fixture["units"])
        self._accept_plan(self.agent.space_plan, "内置演示方案")

    def start_manual_space(self):
        if self.mode != DEMO_MODE:
            raise WorkflowError("实时 AI 模式需先生成空间方案")
        self.agent = WorkbenchSession(self.project)
        self.agent.edit_space_plan([])
        self._accept_plan(self.agent.space_plan, "手动空间草稿")

    def recommend_space(self, progress=None):
        if self.public_demo:
            raise WorkflowError("公开演示版仅使用离线测算")
        if self.mode != LIVE_MODE:
            raise WorkflowError("请切换到实时 AI 模式")
        locked_project(self.project)
        # A failed retry does not revive stale state or a previous live report.
        self._clear_project()
        self.agent, self.http, self.public = self.live_factory(self.project)
        self.agent.progress = progress
        try:
            response = self.agent.recommend_space_plan()
        finally:
            self.agent.progress = None
        if response["plan"] is None:
            raise WorkflowError("模型未生成可编辑的结构化方案", response["validation"]["errors"])
        self._accept_plan(response["plan"], "本次 AI 生成", response["validation"]["errors"])

    @property
    def plan(self):
        return self.agent.space_plan if self.agent else None

    def update_space(self, units):
        if self.plan is None or units == core_units(self.plan["units"]):
            return
        self.agent.edit_space_plan(units)
        self.space_issues = []
        self._clear_finance()

    def space_validation(self, *, confirm=False):
        plan = self.plan
        plan["status"] = "confirmed" if confirm else "draft"
        output = validate_finance_space(plan)
        for issue in self.space_issues:
            if issue not in output["errors"]:
                output["errors"].append(issue)
        output["valid"] = not output["errors"]
        return output

    def confirm_space(self, *, simulated=False):
        check = self.space_validation(confirm=True)
        if not check["valid"]:
            raise WorkflowError("请先修正空间方案", check["errors"])
        self.agent.confirm_space_plan(simulated=simulated)
        if self.space_origin == "内置演示方案" and core_units(self.plan["units"]) == core_units(
            load_example("space_project_demo.json")["units"]
        ):
            self.scenarios = load_example("project_finance_demo_scenarios.json")
            self.agent.edit_finance_parameters(self.scenarios)
            self.agent.register_demo_values({
                name: {entry["parameter_id"]: _get_value(self.scenarios[name], entry)
                       for entry in parameter_catalog(self.plan)} for name in SCENARIOS
            })
        else:
            self.scenarios = blank_parameters(self.plan)
        self.finance_revision += 1
        self.step = 3

    def recommend_finance(self, progress=None):
        if self.public_demo:
            raise WorkflowError("公开演示版仅使用离线测算")
        if self.mode != LIVE_MODE:
            raise WorkflowError("请切换到实时 AI 模式")
        self.agent.progress = progress
        try:
            response = self.agent.recommend_finance_parameters()
        finally:
            self.agent.progress = None
        self.scenarios = response["scenarios"]
        self.finance_warnings = response["warnings"]
        self.finance_revision += 1

    def update_finance(self, scenarios):
        if scenarios == self.scenarios:
            return
        self.agent.edit_finance_parameters(scenarios)
        self.scenarios = deepcopy(scenarios)
        self.result = self.analysis = self.analysis_issue = None

    def fill_assumptions(self):
        scenarios, keys = fill_demo_parameters(self.plan, self.scenarios)
        count = sum(map(len, keys.values()))
        if count:
            self.update_finance(scenarios)
            self.agent.register_demo_values(keys)
            self.finance_revision += 1
        return count

    def finance_issues(self):
        return finance_input_issues(self.plan, self.scenarios)

    def parameters(self, scenario):
        provenance = self.agent.finance_provenance().get(scenario, {}).get("parameter_evidence", {})
        rows = []
        for entry in parameter_catalog(self.plan):
            value = _read(self.scenarios[scenario], entry)
            original = provenance.get(entry["parameter_id"], {})
            if value is None:
                info = {"nature": "missing", "citations": [], "limitations": "暂无可采用的数值，请填写或补录演示假设。"}
            elif original.get("value") == value:
                info = original
            else:
                info = {"nature": "user_assumption", "citations": [], "limitations": "由用户提供，适用性由用户核实。"}
            rows.append({**entry, **info, "value": value})
        return rows

    def confirm_finance(self, *, simulated=False):
        if self.agent.stage == Stage.SPACE_CONFIRMED:
            self.agent.edit_finance_parameters(self.scenarios)
        self.agent.confirm_finance_parameters(simulated=simulated)
        self.step = 4

    def calculate(self, progress=None):
        if self.mode == LIVE_MODE and not self.public_demo:
            self.agent.progress = progress
            try:
                output = self.agent.analyze_investment()
            finally:
                self.agent.progress = None
            self.analysis = output["analysis"]
            self.analysis_issue = output["analysis_issue"]
            result = output["calculation"]
        else:
            result = self.agent.calculate_locally()
        if result["status"] != "ok":
            raise WorkflowError("财务测算未完成", result["errors"])
        self.result = result

    @property
    def space_confirmed(self):
        return self.agent is not None and self.agent.stage in (
            Stage.SPACE_CONFIRMED, Stage.FINANCE_DRAFT, Stage.FINANCE_CONFIRMED, Stage.CALCULATED,
        )

    @property
    def finance_confirmed(self):
        return self.agent is not None and self.agent.stage in (Stage.FINANCE_CONFIRMED, Stage.CALCULATED)
