"""Shared confirmation state for offline and live workbench sessions."""

from copy import deepcopy
from enum import Enum
import sys

from project_finance import calculate_project_finance
from workbench_finance_inputs import (
    _empty_record, _get_value, finance_input_issues, locked_project, parameter_catalog,
    stamp_confirmation, validate_finance_space,
)


class Stage(str, Enum):
    PROJECT_INPUT = "project_input"
    SPACE_DRAFT = "space_draft"
    SPACE_CONFIRMED = "space_confirmed"
    FINANCE_DRAFT = "finance_draft"
    FINANCE_CONFIRMED = "finance_confirmed"
    CALCULATED = "calculated"


class WorkflowError(ValueError):
    def __init__(self, message, issues=None):
        self.issues = issues or []
        super().__init__(message)


def safe_failure(exc):
    """Expose actionable failure categories without request bodies or secrets."""
    if isinstance(exc, WorkflowError):
        return {"type": type(exc).__name__, "message": str(exc), "issues": exc.issues}
    openai_error = getattr(sys.modules.get("openai"), "OpenAIError", None)
    if openai_error is not None and isinstance(exc, openai_error):
        details = {"type": type(exc).__name__}
        status = getattr(exc, "status_code", None)
        if isinstance(status, int):
            details["http_status"] = status
        code = getattr(exc, "code", None)
        if code in ("invalid_api_key", "insufficient_quota", "rate_limit_exceeded",
                    "model_not_found", "unsupported_value", "context_length_exceeded"):
            details["code"] = code
        causes = []
        cause = exc.__cause__
        while cause and len(causes) < 5:
            entry = {"type": type(cause).__name__}
            if isinstance(cause, OSError) and isinstance(cause.errno, int):
                entry["errno"] = cause.errno
            causes.append(entry)
            cause = cause.__cause__
        if causes:
            details["causes"] = causes
        return details
    if type(exc) is RuntimeError and str(exc) == "未配置 OPENAI_API_KEY":
        return {"type": "configuration", "message": "未配置 OPENAI_API_KEY"}
    return {"type": type(exc).__name__}


class WorkbenchSession:
    def __init__(self, project):
        self.progress = None
        self._project = locked_project(project)
        self._stage = Stage.PROJECT_INPUT
        self._plan = None
        self._plan_validation = None
        self._draft_finance = None
        self._recommendation = {}
        self._confirmed_finance = None
        self._result = None
        self._trace = []
        self._trace_evidence = {}
        self._confirmations = []

    @property
    def stage(self):
        return self._stage

    @property
    def tool_trace(self):
        return deepcopy(self._trace)

    @property
    def confirmation_log(self):
        return deepcopy(self._confirmations)

    @property
    def space_plan(self):
        return deepcopy(self._plan)

    @property
    def financial_result(self):
        return deepcopy(self._result)

    @property
    def tool_evidence(self):
        return deepcopy(self._trace_evidence)

    def _notify(self, message):
        if self.progress is not None:
            self.progress(message)

    def _invalidate_finance(self):
        self._draft_finance = None
        self._recommendation = {}
        self._confirmed_finance = None
        self._result = None

    def edit_space_plan(self, units):
        """User replaces units. Prior citations and all financial state expire."""
        if not isinstance(units, list):
            raise WorkflowError("空间单元须为列表")
        edited = deepcopy(units)
        for unit in edited:
            if isinstance(unit, dict):
                unit.pop("evidence", None)
                unit.pop("citations", None)
        self._plan = {**deepcopy(self._project), "status": "draft", "units": edited}
        self._plan_validation = validate_finance_space(self._plan)
        self._invalidate_finance()
        self._stage = Stage.SPACE_DRAFT
        return deepcopy(self._plan_validation)

    def confirm_space_plan(self, *, simulated=False):
        """Explicit caller action. This method is absent from the tool registry."""
        if self.stage != Stage.SPACE_DRAFT or not self._plan:
            raise WorkflowError("当前没有待确认的空间草稿")
        if self._plan_validation and not self._plan_validation["valid"]:
            raise WorkflowError("请先修正空间草稿", self._plan_validation["errors"])
        confirmed = {**self._plan, "status": "confirmed"}
        check = validate_finance_space(confirmed)
        if not check["valid"]:
            raise WorkflowError("空间未通过确认校验", check["errors"])
        self._plan = confirmed
        self._stage = Stage.SPACE_CONFIRMED
        self._confirmations.append({"action": "confirm_space_plan", "simulated": simulated})

    def edit_finance_parameters(self, scenarios):
        if self.stage not in (Stage.SPACE_CONFIRMED, Stage.FINANCE_DRAFT,
                              Stage.FINANCE_CONFIRMED, Stage.CALCULATED):
            raise WorkflowError("须先确认空间方案")
        self._draft_finance = deepcopy(scenarios)
        self._confirmed_finance = None
        self._result = None
        self._stage = Stage.FINANCE_DRAFT
        return finance_input_issues(self._plan, self._draft_finance)

    def register_demo_values(self, filled):
        """Mark application-generated assumptions in a financial draft."""
        if self.stage != Stage.FINANCE_DRAFT:
            raise WorkflowError("当前没有可补录的财务草稿")
        for name, entries in filled.items():
            records = self._recommendation.setdefault(name, {}).setdefault("parameter_evidence", {})
            for entry in parameter_catalog(self._plan):
                key = entry["parameter_id"]
                if key in entries and entries[key] == _get_value(self._draft_finance[name], entry):
                    records[key] = {**_empty_record(entry), "value": entries[key],
                                    "nature": "demo_assumption", "reason": "演示参数补录",
                                    "limitations": "演示假设，未作市场核验"}

    def finance_provenance(self):
        return deepcopy(self._recommendation)

    def calculate_locally(self):
        """Execute the same engine against confirmed inputs without an API call."""
        return deepcopy(self._calculate_finance(calculate_project_finance))

    def confirm_finance_parameters(self, *, simulated=False, demo_assumptions=False):
        if self.stage != Stage.FINANCE_DRAFT:
            raise WorkflowError("当前没有待确认的财务参数")
        if demo_assumptions and not simulated:
            raise WorkflowError("演示假设只能用明确的模拟确认事件")
        errors = finance_input_issues(self._plan, self._draft_finance)
        if errors:
            raise WorkflowError("财务参数缺失或非法", errors)
        self._confirmed_finance = stamp_confirmation(
            self._plan, self._draft_finance, self._recommendation,
            simulated=simulated, demo=demo_assumptions,
        )
        self._stage = Stage.FINANCE_CONFIRMED
        self._confirmations.append({"action": "confirm_finance_parameters", "simulated": simulated,
                                    "demo_assumptions": demo_assumptions})

    def _calculate_finance(self, calculator):
        if self.stage != Stage.FINANCE_CONFIRMED or self._confirmed_finance is None:
            raise WorkflowError("须先确认完整的财务参数")
        self._notify("正在执行已确认数据的三情景财务计算")
        result = calculator(deepcopy(self._plan), deepcopy(self._confirmed_finance))
        if result["status"] == "ok":
            self._result = result
            self._stage = Stage.CALCULATED
        return result
