from __future__ import annotations

import pandas as pd


def apply_scenario_defaults(
    space_units: pd.DataFrame,
    parameter_lookup: pd.DataFrame,
    scenario_name: str,
) -> pd.DataFrame:
    """
    根据 scenario_name，从 parameter_lookup 中为未填写或为 0 的字段补默认值。

    conservative -> low
    base_case    -> mid
    aggressive   -> high
    """
    df = space_units.copy()

    scenario_map = {
        "conservative": "low",
        "base_case": "mid",
        "aggressive": "high",
    }
    level = scenario_map.get(scenario_name, "mid")

    lookup = parameter_lookup.set_index("function_type")

    # 新版可自动补全的字段映射
    field_map = {
        "capex_per_sqm": f"capex_{level}",
        "annual_opex_per_sqm": f"opex_{level}",
        "avg_rent_per_sqm_month": f"rent_{level}",
        "occupancy_rate": f"occupancy_{level}",
        "base_sales_estimate_annual": f"base_sales_{level}",
        "revenue_share_ratio": f"revenue_share_{level}",
        "annual_visitors": f"visitors_{level}",
        "avg_ticket_price": f"avg_ticket_{level}",
        "annual_events": f"events_{level}",
        "event_income_per_event": f"event_income_{level}",
        "venue_rental_per_event": f"venue_rental_{level}",
        "sale_price_per_sqm": f"sale_price_{level}",
    }

    for idx, row in df.iterrows():
        ftype = row.get("function_type")
        if ftype not in lookup.index:
            continue

        ref = lookup.loc[ftype]

        # 默认 revenue_model
        if pd.isna(row.get("revenue_model")) or str(row.get("revenue_model")).strip() == "":
            df.at[idx, "revenue_model"] = ref["default_revenue_model"]

        # 自动补数值字段
        for target_col, source_col in field_map.items():
            current_val = row.get(target_col, 0)

            # 空值或 0 都视为需要补默认值
            if pd.isna(current_val) or current_val == 0:
                if source_col in ref.index:
                    df.at[idx, target_col] = ref[source_col]

    return df


def calc_capex(unit: pd.Series) -> float:
    """
    CAPEX 先按 gross_area_sqm 计算。
    """
    gross_area = unit.get("gross_area_sqm", 0) or 0
    capex_per_sqm = unit.get("capex_per_sqm", 0) or 0
    return gross_area * capex_per_sqm


def calc_annual_opex(unit: pd.Series) -> float:
    """
    OPEX 先按 gross_area_sqm 计算。
    """
    gross_area = unit.get("gross_area_sqm", 0) or 0
    annual_opex_per_sqm = unit.get("annual_opex_per_sqm", 0) or 0
    return gross_area * annual_opex_per_sqm


def calc_annual_rental_income(unit: pd.Series) -> float:
    """
    出租收入 = 可出租面积 × 月租金 × 12 × 出租率
    """
    leasable_area = unit.get("leasable_area_sqm", 0) or 0
    rent = unit.get("avg_rent_per_sqm_month", 0) or 0
    occ = unit.get("occupancy_rate", 0) or 0
    return leasable_area * rent * 12 * occ


def calc_annual_revenue_share_income(unit: pd.Series) -> float:
    """
    分账收入 = 年销售额估算 × 分账比例
    """
    sales = unit.get("base_sales_estimate_annual", 0) or 0
    share = unit.get("revenue_share_ratio", 0) or 0
    return sales * share


def calc_annual_ticket_income(unit: pd.Series) -> float:
    """
    票务收入 = 年访客量 × 平均票价
    """
    visitors = unit.get("annual_visitors", 0) or 0
    ticket = unit.get("avg_ticket_price", 0) or 0
    return visitors * ticket


def calc_annual_event_income(unit: pd.Series) -> float:
    """
    活动收入 = 年活动次数 × 单场活动收入
    """
    events = unit.get("annual_events", 0) or 0
    income_per_event = unit.get("event_income_per_event", 0) or 0
    return events * income_per_event


def calc_annual_venue_rental_income(unit: pd.Series) -> float:
    """
    场地出租收入 = 年活动次数 × 单次场租收入
    """
    events = unit.get("annual_events", 0) or 0
    venue_rent = unit.get("venue_rental_per_event", 0) or 0
    return events * venue_rent


def calc_sales_revenue_total(unit: pd.Series) -> float:
    """
    总销售回款 = 可销售面积 × 销售单价
    """
    saleable_area = unit.get("saleable_area_sqm", 0) or 0
    sale_price = unit.get("sale_price_per_sqm", 0) or 0
    return saleable_area * sale_price


def calc_annualized_sales_revenue(unit: pd.Series) -> float:
    """
    年化销售回款 = 总销售回款 / 销售周期（年）
    若未填写销售周期，则默认为 1 年。
    """
    total_sales = calc_sales_revenue_total(unit)
    sales_period_years = unit.get("sales_period_years", 1) or 1

    if sales_period_years <= 0:
        sales_period_years = 1

    return total_sales / sales_period_years


def calc_unit_revenues(unit: pd.Series) -> dict:
    """
    根据 revenue_model 生成分项收入。
    """
    model = str(unit.get("revenue_model", "")).strip().lower()

    rental_income = 0.0
    revenue_share_income = 0.0
    ticket_income = 0.0
    event_income = 0.0
    venue_rental_income = 0.0
    sales_revenue_total = 0.0
    annualized_sales_revenue = 0.0

    if model == "rental":
        rental_income = calc_annual_rental_income(unit)

    elif model == "sale":
        sales_revenue_total = calc_sales_revenue_total(unit)
        annualized_sales_revenue = calc_annualized_sales_revenue(unit)

    elif model == "ticketed_experience":
        ticket_income = calc_annual_ticket_income(unit)
        venue_rental_income = calc_annual_venue_rental_income(unit)

    elif model == "event":
        event_income = calc_annual_event_income(unit)
        venue_rental_income = calc_annual_venue_rental_income(unit)

    elif model == "mixed":
        rental_income = calc_annual_rental_income(unit)
        revenue_share_income = calc_annual_revenue_share_income(unit)
        ticket_income = calc_annual_ticket_income(unit)
        event_income = calc_annual_event_income(unit)
        venue_rental_income = calc_annual_venue_rental_income(unit)

    elif model == "public_service":
        # 可低收费：允许票务 / 活动 / 场租，但不默认租金和分账
        ticket_income = calc_annual_ticket_income(unit)
        event_income = calc_annual_event_income(unit)
        venue_rental_income = calc_annual_venue_rental_income(unit)

    elif model == "public_non_revenue":
        # 不直接创收
        pass

    else:
        # 未识别时，尽量按 0 处理
        pass

    annual_operating_revenue = (
        rental_income
        + revenue_share_income
        + ticket_income
        + event_income
        + venue_rental_income
    )

    annual_total_cash_inflow = annual_operating_revenue + annualized_sales_revenue

    return {
        "annual_rental_income": rental_income,
        "annual_revenue_share_income": revenue_share_income,
        "annual_ticket_income": ticket_income,
        "annual_event_income": event_income,
        "annual_venue_rental_income": venue_rental_income,
        "annual_operating_revenue": annual_operating_revenue,
        "sales_revenue_total": sales_revenue_total,
        "annualized_sales_revenue": annualized_sales_revenue,
        "annual_total_cash_inflow": annual_total_cash_inflow,
    }


def calc_unit_results(space_units: pd.DataFrame) -> pd.DataFrame:
    """
    对每个 unit 计算：
    - CAPEX
    - OPEX
    - 各类收入
    - 年经营净现金流
    - 年总现金流（含销售年化）
    """
    df = space_units.copy()

    # 基础成本
    df["capex_total"] = df.apply(calc_capex, axis=1)
    df["annual_opex"] = df.apply(calc_annual_opex, axis=1)

    # 分项收入
    revenue_details = df.apply(calc_unit_revenues, axis=1, result_type="expand")
    df = pd.concat([df, revenue_details], axis=1)

    # 净现金流
    df["annual_operating_net_cashflow"] = df["annual_operating_revenue"] - df["annual_opex"]
    df["annual_total_net_cashflow"] = df["annual_total_cash_inflow"] - df["annual_opex"]

    return df


def aggregate_by_zone(unit_results: pd.DataFrame) -> pd.DataFrame:
    """
    按 zone_name 汇总
    """
    summary_cols = [
        "capex_total",
        "annual_opex",
        "annual_rental_income",
        "annual_revenue_share_income",
        "annual_ticket_income",
        "annual_event_income",
        "annual_venue_rental_income",
        "annual_operating_revenue",
        "sales_revenue_total",
        "annualized_sales_revenue",
        "annual_total_cash_inflow",
        "annual_operating_net_cashflow",
        "annual_total_net_cashflow",
    ]

    zone_summary = (
        unit_results.groupby("zone_name", as_index=False)[summary_cols]
        .sum()
        .sort_values("annual_total_net_cashflow", ascending=False)
    )
    return zone_summary


def aggregate_project_total(unit_results: pd.DataFrame) -> pd.DataFrame:
    """
    项目总表
    """
    total = pd.DataFrame(
        {
            "metric": [
                "total_capex",
                "total_annual_opex",
                "total_annual_rental_income",
                "total_annual_revenue_share_income",
                "total_annual_ticket_income",
                "total_annual_event_income",
                "total_annual_venue_rental_income",
                "total_annual_operating_revenue",
                "total_sales_revenue",
                "total_annualized_sales_revenue",
                "total_annual_cash_inflow",
                "total_annual_operating_net_cashflow",
                "total_annual_total_net_cashflow",
            ],
            "value": [
                unit_results["capex_total"].sum(),
                unit_results["annual_opex"].sum(),
                unit_results["annual_rental_income"].sum(),
                unit_results["annual_revenue_share_income"].sum(),
                unit_results["annual_ticket_income"].sum(),
                unit_results["annual_event_income"].sum(),
                unit_results["annual_venue_rental_income"].sum(),
                unit_results["annual_operating_revenue"].sum(),
                unit_results["sales_revenue_total"].sum(),
                unit_results["annualized_sales_revenue"].sum(),
                unit_results["annual_total_cash_inflow"].sum(),
                unit_results["annual_operating_net_cashflow"].sum(),
                unit_results["annual_total_net_cashflow"].sum(),
            ],
        }
    )
    return total