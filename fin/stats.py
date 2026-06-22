from datetime import date, datetime, timedelta
from typing import List, Dict, Optional, Tuple
from collections import defaultdict
import statistics
import math

import pandas as pd

from fin.models import (
    Transaction,
    TransactionType,
    CategoryStat,
    MonthlyStat,
    CompareResult,
    Budget,
    BudgetPeriod,
    BudgetProgress,
    RecurringTransaction,
    SourceAggregate,
    YearlyReport,
)
from fin.db import (
    get_transactions_by_month,
    get_transactions_by_year,
    get_transactions,
    get_budget_by_category,
    get_budgets,
)


def _calc_category_stats(transactions: List[Transaction],
                         trans_type: TransactionType = TransactionType.EXPENSE,
                         calc_budget: bool = True,
                         period: str = "month",
                         period_key: Optional[str] = None) -> List[CategoryStat]:
    cat_data: Dict[str, Dict] = defaultdict(lambda: {"amount": 0.0, "count": 0})
    for tx in transactions:
        if tx.trans_type != trans_type:
            continue
        cat_data[tx.category]["amount"] += tx.amount
        cat_data[tx.category]["count"] += 1

    total = sum(d["amount"] for d in cat_data.values())
    result = []
    for cat, d in cat_data.items():
        pct = round((d["amount"] / total * 100), 2) if total > 0 else 0.0
        progress = None
        if calc_budget:
            if period == "month":
                budget = get_budget_by_category(cat, BudgetPeriod.MONTHLY)
            elif period == "year":
                budget = get_budget_by_category(cat, BudgetPeriod.YEARLY)
            else:
                budget = None
            if budget and budget.limit > 0:
                progress = _calc_progress(cat, d["amount"], budget.limit)
        result.append(CategoryStat(
            category=cat,
            total_amount=round(d["amount"], 2),
            count=d["count"],
            percentage=pct,
            budget_progress=progress,
        ))
    result.sort(key=lambda x: x.total_amount, reverse=True)
    return result


def _calc_progress(category: str, spent: float, budget: float) -> BudgetProgress:
    pct = round(spent / budget * 100, 2) if budget > 0 else 0.0
    remaining = round(budget - spent, 2)
    if pct >= 100:
        status = "over"
    elif pct >= 80:
        status = "warning"
    else:
        status = "normal"
    return BudgetProgress(
        category=category,
        budget=budget,
        spent=round(spent, 2),
        percentage=pct,
        remaining=remaining,
        status=status,
    )


def _calc_source_stats(transactions: List[Transaction],
                       trans_type: TransactionType = TransactionType.EXPENSE) -> Optional[SourceAggregate]:
    agg = SourceAggregate()
    for tx in transactions:
        if tx.trans_type != trans_type:
            continue
        agg.add(tx.source, tx.amount)
    if not agg.sources:
        return None
    agg.finalize()
    return agg


def get_monthly_stats(month_str: str, source: Optional[str] = None,
                      calc_budget: bool = True) -> MonthlyStat:
    txs = get_transactions_by_month(month_str, source=source)
    total_income = sum(t.amount for t in txs if t.trans_type == TransactionType.INCOME)
    total_expense = sum(t.amount for t in txs if t.trans_type == TransactionType.EXPENSE)
    cat_stats = _calc_category_stats(txs, TransactionType.EXPENSE,
                                     calc_budget=calc_budget, period="month", period_key=month_str)
    source_stats = _calc_source_stats(txs, TransactionType.EXPENSE) if source is None else None

    total_progress = None
    if calc_budget:
        total_budget = get_budget_by_category("__total__", BudgetPeriod.MONTHLY)
        if total_budget and total_budget.limit > 0:
            total_progress = _calc_progress("__total__", total_expense, total_budget.limit)

    return MonthlyStat(
        month=month_str,
        total_income=round(total_income, 2),
        total_expense=round(total_expense, 2),
        net_saving=round(total_income - total_expense, 2),
        category_stats=cat_stats,
        source_stats=source_stats,
        total_budget_progress=total_progress,
    )


def get_yearly_stats(year: str, source: Optional[str] = None,
                     calc_budget: bool = True) -> List[MonthlyStat]:
    txs = get_transactions_by_year(year, source=source)
    monthly_data: Dict[str, List[Transaction]] = defaultdict(list)
    for tx in txs:
        m = tx.trans_date.strftime("%Y-%m")
        monthly_data[m].append(tx)

    months_sorted = sorted(monthly_data.keys())
    result = []
    for m in months_sorted:
        month_txs = monthly_data[m]
        total_income = sum(t.amount for t in month_txs if t.trans_type == TransactionType.INCOME)
        total_expense = sum(t.amount for t in month_txs if t.trans_type == TransactionType.EXPENSE)
        cat_stats = _calc_category_stats(month_txs, TransactionType.EXPENSE,
                                         calc_budget=calc_budget, period="month", period_key=m)
        source_stats = _calc_source_stats(month_txs, TransactionType.EXPENSE) if source is None else None
        result.append(MonthlyStat(
            month=m,
            total_income=round(total_income, 2),
            total_expense=round(total_expense, 2),
            net_saving=round(total_income - total_expense, 2),
            category_stats=cat_stats,
            source_stats=source_stats,
        ))
    return result


def compare_months(month_a: str, month_b: str, source: Optional[str] = None) -> CompareResult:
    stat_a = get_monthly_stats(month_a, source=source, calc_budget=False)
    stat_b = get_monthly_stats(month_b, source=source, calc_budget=False)

    cats_a = {cs.category: cs for cs in stat_a.category_stats}
    cats_b = {cs.category: cs for cs in stat_b.category_stats}
    all_cats = set(cats_a.keys()) | set(cats_b.keys())

    category_diffs = []
    for cat in sorted(all_cats, key=lambda c: max(
        cats_a.get(c, CategoryStat(c, 0, 0, 0)).total_amount,
        cats_b.get(c, CategoryStat(c, 0, 0, 0)).total_amount
    ), reverse=True):
        a_amount = cats_a[cat].total_amount if cat in cats_a else 0.0
        b_amount = cats_b[cat].total_amount if cat in cats_b else 0.0
        diff = round(b_amount - a_amount, 2)
        change_pct = round(((b_amount - a_amount) / a_amount * 100), 2) if a_amount > 0 else (float("inf") if b_amount > 0 else 0.0)
        category_diffs.append({
            "category": cat,
            "month_a_amount": a_amount,
            "month_b_amount": b_amount,
            "diff": diff,
            "change_pct": change_pct,
        })

    total_a = stat_a.total_expense
    total_b = stat_b.total_expense
    overall_pct = round((total_b - total_a) / total_a * 100, 2) if total_a > 0 else 0.0

    return CompareResult(
        month_a=month_a,
        month_b=month_b,
        category_diffs=category_diffs,
        total_expense_a=total_a,
        total_expense_b=total_b,
        expense_change_pct=overall_pct,
    )


def get_category_trend(category: str, year: str, source: Optional[str] = None) -> pd.DataFrame:
    txs = get_transactions_by_year(year, source=source)
    rows = []
    for tx in txs:
        if tx.category == category and tx.trans_type == TransactionType.EXPENSE:
            m = tx.trans_date.strftime("%Y-%m")
            rows.append({"month": m, "amount": tx.amount})
    if not rows:
        return pd.DataFrame(columns=["month", "amount"])
    df = pd.DataFrame(rows)
    return df.groupby("month", as_index=False).sum().sort_values("month")


def get_recent_months_trend(months_count: int, source: Optional[str] = None) -> pd.DataFrame:
    today = date.today()
    end_date = today
    year = end_date.year
    month = end_date.month
    start_month = month - months_count + 1
    start_year = year
    if start_month <= 0:
        start_year += start_month // 12
        start_month = start_month % 12 or 12
    start_date = date(start_year, start_month, 1)
    txs = get_transactions(start_date=start_date, end_date=end_date,
                           trans_type=TransactionType.EXPENSE, source=source)
    rows = []
    for tx in txs:
        m = tx.trans_date.strftime("%Y-%m")
        rows.append({"month": m, "category": tx.category, "amount": tx.amount})
    if not rows:
        return pd.DataFrame(columns=["month", "category", "amount"])
    df = pd.DataFrame(rows)
    pivot = df.pivot_table(index="month", columns="category", values="amount", aggfunc="sum").fillna(0.0)
    return pivot.reset_index().sort_values("month")


def get_source_monthly_pivot(year: Optional[str] = None,
                             months_count: Optional[int] = None) -> pd.DataFrame:
    if year:
        txs = get_transactions_by_year(year)
    elif months_count:
        today = date.today()
        end_date = today
        y = end_date.year
        m = end_date.month
        start_month = m - months_count + 1
        start_year = y
        if start_month <= 0:
            start_year += start_month // 12
            start_month = start_month % 12 or 12
        start_date = date(start_year, start_month, 1)
        txs = get_transactions(start_date=start_date, end_date=end_date,
                               trans_type=TransactionType.EXPENSE)
    else:
        txs = get_transactions(trans_type=TransactionType.EXPENSE)

    rows = []
    for tx in txs:
        if tx.trans_type != TransactionType.EXPENSE:
            continue
        m = tx.trans_date.strftime("%Y-%m")
        rows.append({"month": m, "source": tx.source, "amount": tx.amount})
    if not rows:
        return pd.DataFrame(columns=["month", "source", "amount"])
    df = pd.DataFrame(rows)
    pivot = df.pivot_table(index="month", columns="source", values="amount", aggfunc="sum").fillna(0.0)
    return pivot.reset_index().sort_values("month")


def _normalize_desc(desc: str) -> str:
    if not desc:
        return ""
    import re
    s = re.sub(r"\d+\.?\d*", "", desc)
    s = re.sub(r"[\s\-_·•|()（）【】\[\]《》,，.。:：;；!！?？/\\]+", " ", s)
    s = s.strip()
    return s if s else desc.strip()


def _estimate_period(avg_days: float) -> Tuple[str, int]:
    if avg_days <= 0:
        return "不定期", 0
    if 25 <= avg_days <= 35:
        return "每月", 30
    if 13 <= avg_days <= 17:
        return "每两周", 14
    if 6 <= avg_days <= 8:
        return "每周", 7
    if 85 <= avg_days <= 95:
        return "每季度", 90
    if 175 <= avg_days <= 185:
        return "每半年", 180
    if 350 <= avg_days <= 370:
        return "每年", 365
    if avg_days < 6:
        return f"约{int(avg_days)}天", int(avg_days)
    if avg_days < 25:
        return f"约{int(avg_days)}天", int(avg_days)
    return f"约{int(avg_days)}天", int(avg_days)


def detect_recurring_transactions(min_occurrences: int = 3,
                                  std_tolerance: float = 10.0,
                                  amount_tolerance_pct: float = 5.0) -> List[RecurringTransaction]:
    txs = get_transactions(trans_type=TransactionType.EXPENSE)
    if not txs:
        return []

    grouped: Dict[Tuple[str, int], List[Transaction]] = defaultdict(list)
    for t in txs:
        norm_desc = _normalize_desc(t.raw_description)
        if not norm_desc:
            norm_desc = _normalize_desc(t.description)
        amount_key = round(t.amount, 0)
        grouped[(norm_desc, amount_key)].append(t)

    results: List[RecurringTransaction] = []

    for (desc, amt), items in grouped.items():
        if len(items) < min_occurrences:
            continue

        items_sorted = sorted(items, key=lambda x: x.trans_date)
        occurrences = [t.trans_date for t in items_sorted]
        amounts = [t.amount for t in items_sorted]
        ids = [t.id for t in items_sorted if t.id is not None]

        avg_amount = statistics.mean(amounts)
        max_diff_amount = max(amounts) - min(amounts)
        if avg_amount > 0 and (max_diff_amount / avg_amount * 100) > amount_tolerance_pct:
            continue

        intervals = []
        for i in range(1, len(occurrences)):
            delta = (occurrences[i] - occurrences[i - 1]).days
            intervals.append(delta)

        if not intervals:
            continue

        avg_interval = statistics.mean(intervals)
        std_interval = statistics.pstdev(intervals) if len(intervals) > 1 else 0.0

        if avg_interval <= 0:
            continue

        cv = std_interval / avg_interval * 100 if avg_interval > 0 else 999
        if cv > std_tolerance and std_interval > 3:
            continue

        confidence = max(0.0, 100.0 - cv)
        period_str, period_days = _estimate_period(avg_interval)

        last_date = occurrences[-1]
        next_predicted = None
        if period_days > 0:
            next_predicted = last_date + timedelta(days=period_days)

        category = items_sorted[0].category

        results.append(RecurringTransaction(
            description=desc if desc else items_sorted[0].raw_description,
            amount=round(avg_amount, 2),
            category=category,
            occurrences=occurrences,
            avg_interval_days=round(avg_interval, 1),
            std_interval_days=round(std_interval, 1),
            estimated_period=period_str,
            confidence=round(confidence, 1),
            next_predicted_date=next_predicted,
            transaction_ids=ids,
        ))

    results.sort(key=lambda r: (-r.confidence, -len(r.occurrences)))
    return results


def check_month_budget(month_str: str) -> Dict:
    stat = get_monthly_stats(month_str, calc_budget=True)
    over: List[BudgetProgress] = []
    warning: List[BudgetProgress] = []
    normal: List[BudgetProgress] = []
    total_progress = stat.total_budget_progress

    for cs in stat.category_stats:
        bp = cs.budget_progress
        if not bp:
            continue
        if bp.status == "over":
            over.append(bp)
        elif bp.status == "warning":
            warning.append(bp)
        else:
            normal.append(bp)

    total_status = None
    if total_progress:
        if total_progress.status == "over":
            total_status = "over"
        elif total_progress.status == "warning":
            total_status = "warning"
        else:
            total_status = "normal"

    budgets_available = len(over) + len(warning) + len(normal) + (1 if total_progress else 0)

    return {
        "month": month_str,
        "total_expense": stat.total_expense,
        "total_progress": total_progress,
        "total_status": total_status,
        "over": over,
        "warning": warning,
        "normal": normal,
        "budgets_count": budgets_available,
    }


def generate_yearly_report(year: str) -> YearlyReport:
    monthly_breakdown = get_yearly_stats(year, calc_budget=False)
    if not monthly_breakdown:
        return YearlyReport(
            year=year,
            total_income=0.0,
            total_expense=0.0,
            net_saving=0.0,
            monthly_breakdown=[],
            top_expense_categories=[],
            top_10_transactions=[],
        )

    total_income = sum(m.total_income for m in monthly_breakdown)
    total_expense = sum(m.total_expense for m in monthly_breakdown)

    all_year_txs = get_transactions_by_year(year)
    expense_txs = [t for t in all_year_txs if t.trans_type == TransactionType.EXPENSE]

    cat_agg: Dict[str, Dict] = defaultdict(lambda: {"amount": 0.0, "count": 0})
    for t in expense_txs:
        cat_agg[t.category]["amount"] += t.amount
        cat_agg[t.category]["count"] += 1

    top_cats = []
    cat_total = sum(v["amount"] for v in cat_agg.values())
    for cat, d in sorted(cat_agg.items(), key=lambda x: -x[1]["amount"]):
        pct = round(d["amount"] / cat_total * 100, 2) if cat_total > 0 else 0.0
        top_cats.append(CategoryStat(
            category=cat,
            total_amount=round(d["amount"], 2),
            count=d["count"],
            percentage=pct,
        ))

    top_10 = sorted(expense_txs, key=lambda t: -t.amount)[:10]

    previous_year_compare = None
    prev_year = str(int(year) - 1)
    prev_txs = get_transactions_by_year(prev_year)
    if prev_txs:
        previous_year_compare = CompareResult(
            month_a=prev_year,
            month_b=year,
            category_diffs=[],
            total_expense_a=round(sum(t.amount for t in prev_txs if t.trans_type == TransactionType.EXPENSE), 2),
            total_expense_b=round(total_expense, 2),
            expense_change_pct=0.0,
        )
        a_total = previous_year_compare.total_expense_a
        b_total = previous_year_compare.total_expense_b
        if a_total > 0:
            previous_year_compare.expense_change_pct = round((b_total - a_total) / a_total * 100, 2)

        cats_prev: Dict[str, float] = defaultdict(float)
        for t in prev_txs:
            if t.trans_type == TransactionType.EXPENSE:
                cats_prev[t.category] += t.amount
        diffs = []
        all_cats = set(cat_agg.keys()) | set(cats_prev.keys())
        for cat in sorted(all_cats, key=lambda c: -max(cat_agg.get(c, {}).get("amount", 0), cats_prev.get(c, 0))):
            a_amt = round(cats_prev.get(cat, 0.0), 2)
            b_amt = round(cat_agg.get(cat, {}).get("amount", 0.0), 2)
            diff = round(b_amt - a_amt, 2)
            change = round((b_amt - a_amt) / a_amt * 100, 2) if a_amt > 0 else (float("inf") if b_amt > 0 else 0.0)
            diffs.append({
                "category": cat,
                "month_a_amount": a_amt,
                "month_b_amount": b_amt,
                "diff": diff,
                "change_pct": change,
            })
        previous_year_compare.category_diffs = diffs

    total_months = len(monthly_breakdown)
    avg_expense = round(total_expense / total_months, 2) if total_months > 0 else 0.0

    budget_summary = {}
    budgets = get_budgets(BudgetPeriod.MONTHLY)
    for b in budgets:
        spent = cat_agg.get(b.category, {}).get("amount", 0.0) if b.category != "__total__" else total_expense
        if b.limit > 0:
            budget_summary[b.category] = {
                "limit": b.limit,
                "spent": round(spent, 2),
                "avg_monthly": round(spent / total_months, 2) if total_months > 0 else 0.0,
                "pct": round(spent / (b.limit * total_months if b.period == BudgetPeriod.MONTHLY and b.category != "__total__" else b.limit) * 100, 2) if (b.limit * total_months) > 0 else 0.0,
            }

    return YearlyReport(
        year=year,
        total_income=round(total_income, 2),
        total_expense=round(total_expense, 2),
        net_saving=round(total_income - total_expense, 2),
        monthly_breakdown=monthly_breakdown,
        top_expense_categories=top_cats,
        top_10_transactions=top_10,
        previous_year_comparison=previous_year_compare,
        total_months=total_months,
        avg_monthly_expense=avg_expense,
        budget_summary=budget_summary,
    )
