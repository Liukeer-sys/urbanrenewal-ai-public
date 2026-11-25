"""Streamlit entry point for the UrbanRenewal AI competition MVP."""

from copy import deepcopy
from html import escape
from urllib.parse import urlsplit

import altair as alt
import pandas as pd
import streamlit as st

from demo_runtime import PublicDemoError
from project_finance import REVENUE_FIELDS, SCENARIOS
from space_model import AreaValidationError, FUNCTION_CONFIG, NO_REVENUE, calculate_project_areas
from urbanrenewal_visuals import area_schematic, function_color
from urbanrenewal_workbench import DEMO_MODE, LIVE_MODE, Workbench, load_example
from workbench_finance_inputs import _write_value
from workbench_session import Stage, WorkflowError, safe_failure

STEPS = ("项目输入", "空间方案", "经营参数", "投资分析")
STEP_HINT = ("项目资料与面积基线", "功能组合与面积分配", "三情景参数及证据", "投资、收支与现金流")
METHODS = {"renovate": "保留改造", "new_build": "新建", "outdoor_build": "室外建设"}
SPACES = {"indoor": "室内", "outdoor": "室外"}
SCENARIO_LABELS = {"conservative": "保守", "base": "基准", "optimistic": "乐观"}
SCENARIO_COLORS = {"保守": "#8793a8", "基准": "#246654", "乐观": "#b48a54"}
AREA_LABELS = {
    "site_area_sqm": "地块总面积", "existing_building_area_sqm": "原有建筑面积",
    "existing_footprint_sqm": "原有建筑基底", "demolished_building_area_sqm": "拆除建筑面积",
    "demolished_footprint_sqm": "拆除建筑基底", "new_building_area_sqm": "新建建筑面积",
    "new_footprint_sqm": "新建建筑基底",
}
RESULT_AREAS = {
    "retained_building_area_sqm": "保留建筑面积", "post_renewal_building_area_sqm": "改造后建筑面积",
    "post_renewal_footprint_sqm": "改造后建筑基底", "allocatable_outdoor_area_sqm": "室外可分配地面",
}
UNIT_COLUMNS = {
    "unit_id": "单元 ID", "function": "空间功能", "space_type": "室内 / 室外", "construction_method": "建设方式",
    "area_sqm": "面积（㎡）", "operating_method": "经营方式", "revenue_sources": "收入来源",
}
PARAM_NAMES = {
    "demolition_cost_per_sqm": "拆除单价", "discount_rate": "折现率", "capex_per_sqm": "建设或改造单价",
    "annual_opex_per_sqm": "年运营成本单价", "leasable_area_sqm": "可出租面积",
    "avg_rent_per_sqm_month": "月租金单价", "occupancy_rate": "出租率",
    "base_sales_estimate_annual": "承租方年营业额", "revenue_share_ratio": "收入分账比例",
    "annual_visitors": "年付费客流", "avg_ticket_price": "平均票价", "annual_events": "年活动次数",
    "event_income_per_event": "单场活动收入", "annual_venue_rentals": "年场租次数",
    "venue_rental_per_event": "单次场租收入",
}
UNIT_LABELS = {
    "CNY/sqm": "元 / ㎡", "CNY/sqm/year": "元 / ㎡ / 年", "CNY/sqm/month": "元 / ㎡ / 月",
    "ratio": "小数（如 0.08）", "sqm": "㎡", "CNY/year": "元 / 年",
    "visits/year": "人次 / 年", "CNY/visit": "元 / 人次", "events/year": "场 / 年",
    "CNY/event": "元 / 场", "rentals/year": "次 / 年", "CNY/rental": "元 / 次",
}
NATURES = {
    "direct_reference": "直接参考", "proxy_estimate": "代理估计", "user_assumption": "用户填写",
    "demo_assumption": "演示假设", "missing": "缺少可靠数据",
}
TOOL_NAMES = {
    "search_cases": "公开案例检索", "validate_space_plan": "空间规则与面积校验",
    "search_benchmarks": "公开经营参数检索", "calculate_finance": "三情景财务工具",
}
CSS = """
<style>
:root { --ur-ink:#183c33; --ur-soft:#667b70; --ur-line:#dce5de; --ur-green:#246451; }
[data-testid="stAppViewContainer"] { background:#f7f9f5; color:#203c34; }
[data-testid="stHeader"] {background:transparent;pointer-events:none}
[data-testid="stHeader"] button {pointer-events:auto}
[data-testid="stAppDeployButton"] {display:none}
[data-testid="stSidebar"] {background:#eef3ee; border-right:1px solid #dae5dc}
[data-testid="stSidebar"] [data-testid="stSidebarContent"] {padding-top:1.1rem}
.block-container {max-width:1510px; padding:1.65rem 3.3rem 3rem}
[data-testid="stMain"] [data-testid="stVerticalBlock"] {gap:.75rem}
.ur-brand {display:flex;gap:12px;align-items:center;margin:0 0 21px;color:var(--ur-ink)}
.ur-mark {width:38px;height:38px;border-radius:10px;background:#1e5647;display:grid;place-items:center;color:#f4f9f4;font-weight:800;font-size:1.25rem}
.ur-brand b {display:block;font-size:1.03rem;line-height:1.25}
.ur-brand span {font-size:.75rem;color:#64796c}
.ur-banner {position:relative;overflow:hidden;padding:18px 30px 20px;background:linear-gradient(110deg,#173d33,#245748);border-radius:14px;color:#f5faf5;margin:0 0 8px;isolation:isolate}
.ur-banner::after {content:"";position:absolute;inset:-35% -7% -25% 60%; transform:skewX(-24deg);background:repeating-linear-gradient(0deg,transparent 0 30px,#daeada18 31px 32px),repeating-linear-gradient(90deg,transparent 0 47px,#daeada20 48px 49px);z-index:-1}
.ur-banner h1 {color:#f5faf5;font-size:clamp(1.75rem,3vw,2.65rem);letter-spacing:-.035em;line-height:1.1;margin:6px 0 7px;padding:0}
.ur-banner p {color:#d4e5db;line-height:1.25;margin:4px 0;font-size:.93rem}
.ur-banner .ur-en {font-size:.78rem;letter-spacing:.035em;color:#b9d2c4}
.ur-tag {display:inline-block;border:1px solid #d3e5dc55;border-radius:100px;padding:4px 9px;color:#e0eee3;font-size:.73rem}
.ur-steps {display:flex;gap:7px;margin:0 0 7px;padding:0;flex-wrap:wrap}
.ur-step {display:flex;align-items:center;gap:9px;padding:9px 12px;border-radius:8px;flex:1;min-width:125px;background:#edf2ed;color:#5a6b62;font-size:.85rem}
.ur-step b {font-variant-numeric:tabular-nums;font-size:.75rem;color:#557467}
.ur-step.active {background:#dcebe2;color:#144a39;font-weight:700;box-shadow:inset 0 -2px #3e7b64}
.ur-step.active b {color:#245d49}
.ur-section {margin:0 0 9px}
.ur-section h2 {margin:0;padding:0;font-size:1.58rem;color:var(--ur-ink);letter-spacing:-.03em}
.ur-section p {margin:3px 0 7px;color:var(--ur-soft);font-size:.86rem}
.ur-panel-title {border-top:1px solid #d9e5dc;padding-top:12px;margin:2px 0 0;color:#24493c;font-size:1rem;font-weight:700}
.ur-metrics {display:grid;grid-template-columns:repeat(auto-fit,minmax(128px,1fr));gap:0;margin:5px 0 10px;border-top:1px solid var(--ur-line);border-bottom:1px solid var(--ur-line);background:#eff4ee;border-radius:8px}
.ur-metric {padding:10px 12px;border-right:1px solid var(--ur-line);min-width:0}
.ur-metric span {display:block;font-size:.75rem;color:#64796b}
.ur-metric strong {display:block;font-size:clamp(.98rem,1.65vw,1.45rem);font-variant-numeric:tabular-nums;color:#204d3d;white-space:nowrap}
.ur-metric.negative strong {color:#a64741}
.ur-caption {color:#65786d;font-size:.75rem;line-height:1.4;margin:4px 0 10px}
.ur-legend {display:flex;flex-wrap:wrap;gap:7px 14px;margin:5px 0;padding-left:8px;color:#456054;font-size:.76rem}
.ur-dot {display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px}
[data-testid="stText"] {white-space:pre-wrap;overflow-wrap:anywhere}
[data-testid="stBaseButton-primary"] {background:#225f4d!important;border-color:#225f4d!important;color:white!important}
[data-testid="stBaseButton-primary"]:hover {background:#194738!important}
[data-testid="stSidebar"] [data-testid="stBaseButton-secondary"] {text-align:left}
@media(max-width:900px){.block-container{padding:1.4rem 1.2rem 2rem}.ur-banner{padding:18px}.ur-metrics{grid-template-columns:repeat(2,minmax(0,1fr))}}
</style>
"""


def header(w):
    mode_label = "公开演示版" if w.public_demo else w.mode
    st.html(f'<div class="ur-banner"><span class="ur-tag">{escape(mode_label)}</span>'
            '<h1>UrbanRenewal AI</h1><p>城市更新空间与资产运营决策智能体</p>'
            '<p class="ur-en">AI Agent for Urban Regeneration and Investment Feasibility</p></div>')
    st.html('<div class="ur-steps">' + "".join(
        f'<div class="ur-step{" active" if w.step == i else ""}"><b>{i:02}</b>{label}</div>'
        for i, label in enumerate(STEPS, 1)) + '</div>')


def section(w):
    st.html(f'<div class="ur-section"><h2>{STEPS[w.step-1]}</h2><p>{STEP_HINT[w.step-1]}</p></div>')


def panel_title(label):
    st.html(f'<div class="ur-panel-title">{escape(label)}</div>')


def metrics(rows):
    html = "".join(f'<div class="ur-metric{" negative" if negative else ""}"><span>{escape(label)}</span>'
                   f'<strong>{escape(value)}</strong></div>' for label, value, negative in rows)
    st.html(f'<div class="ur-metrics">{html}</div>')


def sidebar(w):
    with st.sidebar:
        st.html('<div class="ur-brand"><div class="ur-mark">U</div><div><b>UrbanRenewal AI</b>'
                '<span>城市更新决策工作台</span></div></div>')
        st.caption("运行模式")
        if w.public_demo:
            st.markdown("**公开演示 · 离线测算**")
            st.caption("内置方案与参数为已保存的演示假设。")
        else:
            modes = st.columns(2)
            for col, mode in zip(modes, (DEMO_MODE, LIVE_MODE)):
                col.button(mode, type="primary" if w.mode == mode else "secondary", width="stretch",
                           on_click=w.set_mode, args=(mode,))
        st.caption("当前项目")
        st.markdown(f"**{escape(w.project_name or '未命名项目')}**")
        st.divider()
        allowed = (True, w.plan is not None, w.space_confirmed, w.finance_confirmed)
        for i, (label, enabled) in enumerate(zip(STEPS, allowed), 1):
            st.button(f"{i:02}　{label}", key=f"nav-{i}", disabled=not enabled,
                      type="primary" if w.step == i else "secondary", width="stretch",
                      on_click=setattr, args=(w, "step", i))
        st.divider()
        st.caption("离线可演示完整测算" if w.mode == DEMO_MODE else "实时调用使用经审核的公开检索资料")


def _amount(value):
    return "—" if value is None else f"{value / 10000:,.2f} 万元"


def issue_table(issues):
    if issues:
        st.dataframe(pd.DataFrame([{"字段": item["path"], "说明": item["message"]} for item in issues]),
                     hide_index=True, width="stretch", height=min(240, 38 + 35 * len(issues)))


def show_error(exc):
    if isinstance(exc, WorkflowError):
        st.error(str(exc))
        issue_table([item for item in exc.issues if isinstance(item, dict) and "path" in item])
        other = [item for item in exc.issues if isinstance(item, dict) and "type" in item]
        if other:
            st.caption("服务原因 " + " / ".join(str(item["type"]) for item in other))
    elif isinstance(exc, PublicDemoError):
        st.error("实时连接未通过公开模式检查，可检查官方 API 地址或切换内置演示。")
        st.caption(str(exc))
    else:
        detail = safe_failure(exc)
        kind = detail["type"]
        if kind in ("OpenAIConnectionError", "APIConnectionError", "APITimeoutError", "TimeoutError"):
            st.error("无法连接 OpenAI 官方服务。可检查网络后重试，或主动切换内置演示。")
        elif kind == "configuration":
            st.error("实时 AI 尚未配置。可继续使用内置演示。")
        elif kind == "AuthenticationError":
            st.error("OpenAI 拒绝了认证请求。请在本机检查已配置的 API 凭据。")
        elif kind == "RateLimitError":
            st.error("OpenAI 限额或配额不足。可稍后重试或切换内置演示。")
        else:
            st.error(f"本次操作未完成（{kind}）。")


def run_action(label, action, *, rerun=True):
    with st.status(label, expanded=True) as progress:
        try:
            action(lambda message: progress.update(label=message))
        except Exception as exc:
            progress.update(label="本次操作未完成", state="error")
            show_error(exc)
            return False
        progress.update(label="操作已完成", state="complete", expanded=False)
    if rerun:
        st.rerun()
    return True


def diagram(units, *, stacked=False):
    st.image(area_schematic(units, stacked=stacked), width="stretch")
    names = dict.fromkeys(unit["function"] for unit in units if unit.get("function"))
    if names:
        st.html('<div class="ur-legend">' + "".join(
            f'<span><i class="ur-dot" style="background:{function_color(name)}"></i>{escape(name)}</span>'
            for name in names) + '</div>')
    st.html('<p class="ur-caption">功能面积示意，非实际建筑布局。室内建筑面积与室外地面面积分别按比例展示。</p>')


def project_page(w):
    left, right = st.columns([1.55, 1], gap="large")
    prefix = f"project-{w.project_revision}"
    with left:
        tools = st.columns([1.4, 1])
        if tools[0].button("一键加载内置演示", type="primary" if w.mode == DEMO_MODE else "secondary"):
            w.load_demo()
            st.rerun()
        if tools[1].button("新建空白项目"):
            w.reset_project()
            st.rerun()
        w.project_name = st.text_input("项目名称", w.project_name, key=f"{prefix}-name")
        x, y = st.columns(2)
        city = x.text_input("所在城市", w.project["city"], key=f"{prefix}-city")
        goal = y.text_input("更新目标", w.project["renewal_goal"], key=f"{prefix}-goal")
        bg = st.text_area("项目背景", w.project["background"], height=76, key=f"{prefix}-background")
        constraints = st.text_area("规划约束（每行一项）", "\n".join(w.project["planning_constraints"]),
                                   height=76, key=f"{prefix}-constraints")
        panel_title("项目面积 · ㎡")
        areas = {}
        for index, (field, label) in enumerate(AREA_LABELS.items()):
            if index % 2 == 0:
                cols = st.columns(2)
            areas[field] = cols[index % 2].number_input(
                label, min_value=0.0, value=float(w.project["areas"][field]),
                step=100.0, format="%.2f", key=f"{prefix}-{field}")
        project = {"city": city, "background": bg, "renewal_goal": goal,
                   "planning_constraints": [line.strip() for line in constraints.splitlines() if line.strip()],
                   "areas": areas}
        w.update_project(project)
        try:
            calc = calculate_project_areas(areas)
        except AreaValidationError as exc:
            calc = None
            st.error("请修正项目面积")
            issue_table([{"path": AREA_LABELS.get(item["path"].split(".")[-1], item["path"]),
                          "message": item["message"]} for item in exc.issues])
        ready = bool(calc and city.strip() and goal.strip() and bg.strip() and w.project_name.strip())
        if w.mode == LIVE_MODE:
            consent = st.checkbox("允许将本项目资料和测算结果发送至 OpenAI 官方 API，仅检索公开资料",
                                  key=f"live-consent-{prefix}")
            if st.button("AI推荐空间方案", type="primary", disabled=not ready or not consent):
                run_action("正在请求模型规划检索", w.recommend_space)
        elif st.button("手动配置空间方案", disabled=not ready):
            w.start_manual_space()
            st.rerun()
    with right:
        panel_title("面积摘要")
        if calc:
            metrics([(label, f"{calc[key]:,.0f} ㎡", False) for key, label in RESULT_AREAS.items()])
            diagram([
                {"function": "保留建筑", "space_type": "indoor", "area_sqm": calc["retained_building_area_sqm"]},
                {"function": "新建建筑", "space_type": "indoor", "area_sqm": areas["new_building_area_sqm"]},
                {"function": "室外地面", "space_type": "outdoor", "area_sqm": calc["allocatable_outdoor_area_sqm"]},
            ], stacked=True)
        else:
            st.info("修正面积后显示可分配空间。")


def _editor_rows(units):
    rows = pd.DataFrame([{key: unit.get(key) for key in UNIT_COLUMNS} for unit in units], columns=list(UNIT_COLUMNS))
    rows["space_type"] = rows["space_type"].map(SPACES)
    rows["construction_method"] = rows["construction_method"].map(METHODS)
    return rows.assign(area_sqm=pd.to_numeric(rows["area_sqm"], errors="coerce")).rename(columns=UNIT_COLUMNS)


def _edited_units(frame, plan):
    lookup = {unit["unit_id"]: unit for unit in plan["units"]}
    reverse_sp = {v: k for k, v in SPACES.items()}
    reverse_method = {v: k for k, v in METHODS.items()}
    result = []
    for row in frame.rename(columns={v: k for k, v in UNIT_COLUMNS.items()}).to_dict("records"):
        income = row.pop("revenue_sources")
        unit = {key: None if pd.isna(value) else value for key, value in row.items()}
        unit["revenue_sources"] = list(income) if isinstance(income, (list, tuple)) else (
            income.tolist() if getattr(income, "ndim", 0) == 1 else []
        )
        unit["space_type"] = reverse_sp.get(unit["space_type"], unit["space_type"])
        unit["construction_method"] = reverse_method.get(unit["construction_method"], unit["construction_method"])
        if isinstance(unit["unit_id"], str):
            previous = lookup.get(unit["unit_id"], {})
            for key in ("housing_type", "planning_confirmed", "sale_conditions_confirmed"):
                if key in previous and previous["function"] == unit["function"]:
                    unit[key] = previous[key]
        result.append(unit)
    return result


def _source_links(citations):
    for citation in citations:
        url = citation.get("url") or ""
        link = urlsplit(url)
        title = citation.get("title") or citation.get("source_id") or "公开来源"
        st.caption(" · ".join(str(bit) for bit in (title, citation.get("city"), citation.get("year")) if bit))
        if link.scheme == "https" and link.netloc:
            st.link_button("查看来源", url)
        st.text(citation["quote"])


def space_page(w):
    st.caption(f"方案来源 · {w.space_origin}　|　{'已确认' if w.space_confirmed else '待确认草稿'}")
    plan = w.plan
    diagram(plan["units"])
    with st.form(key=f"space-{w.space_revision}"):
        functions = list(FUNCTION_CONFIG)
        operating = sorted({value for rule in FUNCTION_CONFIG.values() for value in rule["operating_methods"]})
        revenues = [NO_REVENUE, *REVENUE_FIELDS, *sorted({item for rule in FUNCTION_CONFIG.values()
                    for item in rule["revenue_sources"] if item not in REVENUE_FIELDS and item != NO_REVENUE})]
        editor = st.data_editor(_editor_rows(w.space_seed), hide_index=True, width="stretch", num_rows="dynamic", height=282,
                                column_config={
            "单元 ID": st.column_config.TextColumn(required=True),
            "空间功能": st.column_config.SelectboxColumn(options=functions, required=True),
            "室内 / 室外": st.column_config.SelectboxColumn(options=list(SPACES.values()), required=True),
            "建设方式": st.column_config.SelectboxColumn(options=list(METHODS.values()), required=True),
            "面积（㎡）": st.column_config.NumberColumn(min_value=0, format="%.2f", required=True),
            "经营方式": st.column_config.SelectboxColumn(options=operating, required=True),
            "收入来源": st.column_config.MultiselectColumn(options=revenues),
        })
        st.caption("在表格底部添加单元，或选中行后删除。应用修改后重新校验并更新示意。")
        if st.form_submit_button("应用空间修改"):
            units = _edited_units(editor, plan)
            w.update_space(units)
            w.space_seed = deepcopy(units)
            w.space_revision += 1
            st.rerun()

    check = w.space_validation(confirm=True)
    if check["allocation"]:
        allocation = check["allocation"]
        st.dataframe(pd.DataFrame([{
            "建设方式": METHODS[method], "可分配（㎡）": row["available_area_sqm"],
            "已分配（㎡）": row["allocated_area_sqm"], "剩余（㎡）": row["remaining_area_sqm"],
            "超出（㎡）": row["overallocated_area_sqm"],
        } for method, row in allocation.items()]), hide_index=True, width="stretch")
    if not check["valid"]:
        st.warning("当前配置尚不能确认。财务未支持的收入项也会在下方标出。")
        issue_table(check["errors"])
    with st.expander("推荐理由与公开依据"):
        found = False
        for unit in plan["units"]:
            match = next((item for item in w.annotations
                          if all(item.get(key) == unit.get(key) for key in UNIT_COLUMNS)), None)
            if not match or not match.get("reason"):
                continue
            found = True
            st.markdown(f"**{escape(match['function'])} · {escape(match['unit_id'])}**")
            st.write(match["reason"])
            _source_links(match.get("evidence", []))
        if not found:
            st.caption("当前单元没有可对应的实时推荐理由。")
    if w.space_confirmed:
        if st.button("进入经营参数", type="primary"):
            w.step = 3
            st.rerun()
    elif st.button("确认空间方案", type="primary", disabled=not check["valid"]):
        run_action("正在校验并保存确认", lambda progress: w.confirm_space())


def _parameter_group(title, rows, edits, editor_prefix):
    if not rows:
        return
    st.caption(title)
    frame = pd.DataFrame([{
        "参数": (row.get("revenue_source", "") + " · " if row.get("revenue_source") else "") + PARAM_NAMES[row["field"]],
        "值": row["value"], "单位": UNIT_LABELS.get(row["unit"], row["unit"]),
        "数据性质": NATURES[row["nature"]],
        "来源": "、".join(dict.fromkeys(c.get("title") or c.get("source_id") or "公开来源" for c in row["citations"])),
        "适用说明": row.get("limitations", ""),
    } for row in rows])
    frame["值"] = pd.to_numeric(frame["值"], errors="coerce").astype(float)
    changed = st.data_editor(frame, hide_index=True, width="stretch", disabled=["参数", "单位", "数据性质", "来源", "适用说明"],
                             column_config={"值": st.column_config.NumberColumn(min_value=0, format="%.4f", width=105)},
                             key=f"{editor_prefix}-{rows[0]['parameter_id']}-{title}")
    for entry, value in zip(rows, changed["值"]):
        edits.append((entry, None if pd.isna(value) else float(value)))


def finance_page(w):
    panel_title("参数准备")
    fill_column = st
    if not w.public_demo:
        live_column, fill_column = st.columns([1.15, 1.85])
        if live_column.button("AI推荐财务参数", disabled=w.mode != LIVE_MODE or w.agent.stage != Stage.SPACE_CONFIRMED):
            run_action("正在请求财务检索工具", w.recommend_finance)
    if fill_column.button("填充演示假设", help="仅补兼容的空值，保留现有输入。"):
        filled = w.fill_assumptions()
        if not filled:
            st.info("没有可安全补录的空值。")
        else:
            st.session_state["ur_notice"] = f"已补录 {filled} 项演示假设。"
            st.rerun()
    if notice := st.session_state.pop("ur_notice", None):
        st.success(notice)
    st.caption("演示假设未经市场核验。未匹配项保持为空。")
    all_rows = [(name, row) for name in SCENARIOS for row in w.parameters(name)]
    missing = [(name, row) for name, row in all_rows if row["value"] is None]
    count = len(all_rows)
    metrics([("参数完整度", f"{count-len(missing)} / {count}", False),
             ("待补充", str(len(missing)), bool(missing)),
             ("演示假设", str(sum(row["nature"] == "demo_assumption" for _, row in all_rows)), False)])
    if missing:
        with st.expander(f"待补充参数 · {len(missing)} 项"):
            st.dataframe(pd.DataFrame([{"情景": SCENARIO_LABELS[name], "单元": row["unit_id"] or "项目",
                                       "参数": PARAM_NAMES[row["field"]]} for name, row in missing]),
                         hide_index=True, width="stretch", height=230)
    if w.finance_warnings:
        with st.expander("模型推荐校验提示"):
            issue_table(w.finance_warnings)

    name = st.radio("情景", list(SCENARIOS), format_func=SCENARIO_LABELS.get, horizontal=True, index=1, key="ur-scenario")
    rows = w.parameters(name)
    edits = []
    editor_prefix = f"finance-{name}-{w.finance_revision}"
    with st.form(key=editor_prefix):
        _parameter_group("项目级参数", [row for row in rows if row["unit_id"] is None], edits, editor_prefix)
        for unit in w.plan["units"]:
            unit_id = unit["unit_id"].strip()
            with st.expander(f'{unit["function"]} · {unit_id} · {unit["area_sqm"]:,.0f} ㎡'):
                unit_rows = [row for row in rows if row["unit_id"] == unit_id]
                _parameter_group("建设与运营成本", [row for row in unit_rows if "revenue_source" not in row],
                                 edits, editor_prefix)
                _parameter_group("收入与经营量", [row for row in unit_rows if "revenue_source" in row],
                                 edits, editor_prefix)
        if st.form_submit_button("保存本情景参数"):
            # The widget key includes the form's revision for navigation, and
            # the data is updated only after the user submits changes.
            scenarios = deepcopy(w.scenarios)
            for entry, value in edits:
                _write_value(scenarios[name], entry, value)
            w.update_finance(scenarios)
            w.finance_revision += 1
            st.rerun()
    cited = [row for row in rows if row["citations"]]
    if cited:
        with st.expander("参数来源原文与适用性"):
            for row in cited:
                st.markdown(f"**{escape(row['unit_id'] or '项目')} · {PARAM_NAMES[row['field']]}**")
                st.write(row.get("limitations", ""))
                _source_links(row["citations"])
    issues = w.finance_issues()
    missing_paths = {f"scenarios.{name}.{row['parameter_id']}" for name, row in missing}
    other = [item for item in issues if item["path"] not in missing_paths]
    if other:
        st.error("需要修正的参数")
        issue_table(other)
    if w.finance_confirmed:
        st.button("进入投资分析", type="primary", on_click=setattr, args=(w, "step", 4))
    else:
        st.button("确认全部情景参数", type="primary", disabled=bool(issues),
                  on_click=confirm_finance_action, args=(w,))
        if error := st.session_state.pop("ur_confirmation_error", None):
            show_error(error)


def confirm_finance_action(w):
    try:
        w.confirm_finance()
    except WorkflowError as exc:
        st.session_state["ur_confirmation_error"] = exc


def _cashflow_chart(scenarios):
    rows = [{"情景": SCENARIO_LABELS[name], "年份": row["year"],
             "累计现金流（万元）": row["cumulative_cashflow"] / 10000}
            for name, scenario in scenarios.items() for row in scenario["cashflows"]]
    colors = list(SCENARIO_COLORS)
    chart = alt.Chart(pd.DataFrame(rows)).mark_line(point=True, strokeWidth=2.7).encode(
        x=alt.X("年份:Q", axis=alt.Axis(values=list(range(11)), grid=False)),
        y=alt.Y("累计现金流（万元）:Q", axis=alt.Axis(format=",.0f", gridColor="#dfe9e1")),
        color=alt.Color("情景:N", scale=alt.Scale(domain=colors, range=list(SCENARIO_COLORS.values())),
                        legend=alt.Legend(orient="top", title=None)),
        tooltip=["情景:N", "年份:Q", alt.Tooltip("累计现金流（万元）:Q", format=",.2f")],
    ).properties(height=260)
    st.altair_chart(chart, width="stretch", theme=None)


def _safe_analysis(text):
    # Scenario arithmetic and sign claims are rendered from calculation in
    # the adjacent report, while model prose contributes risk and design advice.
    import re
    sentences = re.split(r"(?<=[。！？])|\n", text or "")
    forbidden = ("盈亏平衡", "折现", "达到投资回报", "收回投资", "收益达标", "收益要求",
                 "投资可行", "净现值", "内部收益率", "npv", "irr", "累计现金流")
    return "".join(sentence.strip() for sentence in sentences
                   if sentence.strip() and not any(fragment in sentence.casefold() for fragment in forbidden))


def results_page(w):
    if not w.result:
        st.info("空间及三情景参数已确认，可以执行财务测算。")
        if st.button("执行十年投资测算", type="primary"):
            run_action("正在启动财务测算", w.calculate)
        return
    scenarios = w.result["scenarios"]
    name = st.radio("查看情景", list(SCENARIOS), format_func=SCENARIO_LABELS.get, index=1,
                    horizontal=True, key="ur-result-scenario")
    s = scenarios[name]
    ops = s["annual_operations"]
    rows = [("总建设投资", s["capex"]["total"]), ("年经营收入", ops["revenue"]),
            ("年运营成本", ops["opex"]), ("年经营净现金流", ops["net_cashflow"]),
            ("NPV", s["npv"]), ("十年累计未折现净现金流", s["cumulative_undiscounted_net_cashflow"])]
    cards = [(key, _amount(value), value < 0) for key, value in rows]
    cards.insert(5, ("IRR", "未定义" if s["irr"] is None else f'{s["irr"]:.2%}', (s["irr"] or 0) < 0))
    metrics(cards)
    if s["npv"] < 0:
        st.warning("当前情景 NPV 为负，未达给定折现率的收益要求。未折现累计现金流是另一项指标。")
    elif s["npv"] > 0:
        st.success("当前情景 NPV 为正，达到本模型给定的折现率要求。")
    else:
        st.info("当前情景 NPV 为零，恰好达到给定折现率。")
    a, b = st.columns([1, 1.8], gap="large")
    with a:
        panel_title("建设投资构成")
        construction = {"拆除": s["capex"]["demolition"]["capex"],
                        **{METHODS[k]: v for k, v in s["capex"]["by_construction_method"].items()}}
        st.dataframe(pd.DataFrame([{"类别": k, "投资（万元）": round(v/10000, 2)} for k, v in construction.items()]),
                     hide_index=True, width="stretch")
    with b:
        panel_title("三情景累计现金流")
        _cashflow_chart(scenarios)
    panel_title("三情景指标对比")
    st.dataframe(pd.DataFrame([{"情景": SCENARIO_LABELS[k], "总投资": _amount(v["capex"]["total"]),
                               "年经营收入": _amount(v["annual_operations"]["revenue"]),
                               "年OPEX": _amount(v["annual_operations"]["opex"]),
                               "折现率": f'{v["discount_rate"]:.2%}', "NPV": _amount(v["npv"]),
                               "IRR": "未定义" if v["irr"] is None else f'{v["irr"]:.2%}',
                               "十年累计未折现": _amount(v["cumulative_undiscounted_net_cashflow"])}
                              for k, v in scenarios.items()]), hide_index=True, width="stretch")
    panel_title("各单元年度经营收支")
    st.dataframe(pd.DataFrame([{"功能单元": unit["function"], "ID": unit["unit_id"],
                               "年营收（万元）": round(unit["annual_revenue"]/10000, 2),
                               "年运营成本（万元）": round(unit["annual_opex"]/10000, 2)}
                              for unit in s["units"]]), hide_index=True, width="stretch", height=245)
    panel_title("投资解读")
    signs = "；".join(f'{SCENARIO_LABELS[k]}情景 NPV {"为正" if v["npv"] > 0 else "为负" if v["npv"] < 0 else "为零"}'
                     for k, v in scenarios.items())
    st.write(signs + "。折现判断以上表 NPV 为准。")
    if w.mode == LIVE_MODE and (text := _safe_analysis(w.analysis)):
        st.caption("本次模型生成 · 风险与优化建议")
        st.write(text)
    elif w.mode == LIVE_MODE:
        st.info("本次未生成可展示的定性解读，财务计算结果可用。")
    else:
        st.caption("内置演示使用离线投资解读。")
        st.write("优先核实出租率、票务客流和改造单价，评估公益空间的运营补贴及分期投运安排。")
    for warning in w.result["warnings"]:
        st.warning(warning["message"])
    st.caption("模型边界：税前、无融资，第 0 年集中投入，后续 10 年参数固定。未计入土地购置、税费、融资、期末残值及追加投资。")


def tool_panel(w):
    if w.public_demo:
        with st.expander("历史真实 Agent 执行记录（脱敏）"):
            st.caption("来自第四阶段的真实 OpenAI 工具调用。两次用户确认由测试模拟。当前页面使用本地财务引擎。")
            for order, record in enumerate(load_example("public_agent_history.json"), 1):
                status = "已执行" if record["status"] == "ok" else "失败"
                st.markdown(f'**{order:02d} · {record["tool"]} · {status}**')
                st.caption(record["summary"])
        return
    with st.expander("Agent 执行过程"):
        records = w.agent.tool_trace if w.agent else []
        if not records:
            st.caption("内置演示使用本地校验与财务引擎，无实时工具调用。" if w.mode == DEMO_MODE
                       else "本次会话尚无工具执行记录。")
            return
        evidence = w.agent.tool_evidence
        for index, record in enumerate(records, 1):
            name = record["tool"]
            summary = record["summary"]
            st.markdown(f'**{index:02d} · {escape(TOOL_NAMES.get(name, name))}**')
            st.caption(f'{name} · {"已执行" if record["status"] == "ok" else "失败"}'
                       f' · {"结果已回传" if record.get("result_returned_to_model") else "结果未回传"}')
            if record["call_id"] in evidence and "hits" in summary:
                st.caption(f'已发送 {summary["hits"]} 条审核通过的公开资料')
                for item in evidence[record["call_id"]]:
                    md = item["metadata"]
                    with st.expander(md.get("title") or md.get("source_id") or "公开资料"):
                        _source_links([{"title": md.get("title"), "url": md.get("source_url"),
                                        "year": md.get("data_year"), "quote": item["text"]}])
            elif name == "calculate_finance" and w.result:
                base = w.result["scenarios"]["base"]
                st.write(f'基准总投资 {_amount(base["capex"]["total"])}，NPV {_amount(base["npv"])}。')
            elif "valid" in summary:
                st.caption("空间校验通过" if summary["valid"] else "空间校验发现待修正项")
                issue_table(summary.get("errors", []))
            elif record["status"] != "ok":
                st.caption(str(summary.get("type") or summary.get("message") or "工具未完成"))
        if w.public and w.public.excluded:
            st.caption(f"本会话公开资料检查排除 {len(w.public.excluded)} 条命中，排除项未发送。")


def main():
    st.set_page_config(page_title="UrbanRenewal AI · 城市更新工作台", page_icon="▦", layout="wide")
    st.html(CSS)
    if "workbench" not in st.session_state:
        st.session_state.workbench = Workbench()
    w = st.session_state.workbench
    sidebar(w)
    header(w)
    section(w)
    (project_page, space_page, finance_page, results_page)[w.step - 1](w)
    tool_panel(w)


if __name__ == "__main__":
    main()
