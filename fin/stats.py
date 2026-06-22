from datetime import date, datetime
from typing import List, Dict, Optional
from collections import defaultdict

import pandas as pd

from fin.models import (
    Transaction,
    TransactionType,
    CategoryStat,
    MonthlyStat,
    CompareResult,
)
from fin.db import get_transactions_by_month, get_transactions_by_year


def _calc_category_stats(transactions: List[Transaction], trans_type: TransactionType = TransactionType.EXPENSE) -> List[CategoryStat]:
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
        result.append(CategoryStat(
            category=cat,
            total_amount=round(d["amount"], 2),
            count=d["count"],
            percentage=pct,
        ))
    result.sort(key=lambda x: x.total_amount, reverse=True)
    return result


def get_monthly_stats(month_str: str) -> MonthlyStat:
    txs = get_transactions_by_month(month_str)
    total_income = sum(t.amount for t in txs if t.trans_type == TransactionType.INCOME)
    total_expense = sum(t.amount for t in txs if t.trans_type == TransactionType.EXPENSE)
    cat_stats = _calc_category_stats(txs, TransactionType.EXPENSE)
    return MonthlyStat(
        month=month_str,
        total_income=round(total_income, 2),
        total_expense=round(total_expense, 2),
        net_saving=round(total_income - total_expense, 2),
        category_stats=cat_stats,
    )


def get_yearly_stats(year: str) -> List[MonthlyStat]:
    txs = get_transactions_by_year(year)
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
        cat_stats = _calc_category_stats(month_txs, TransactionType.EXPENSE)
        result.append(MonthlyStat(
            month=m,
            total_income=round(total_income, 2),
            total_expense=round(total_expense, 2),
            net_saving=round(total_income - total_expense, 2),
            category_stats=cat_stats,
        ))
    return result


def compare_months(month_a: str, month_b: str) -> CompareResult:
    stat_a = get_monthly_stats(month_a)
    stat_b = get_monthly_stats(month_b)

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


def get_category_trend(category: str, year: str) -> pd.DataFrame:
    txs = get_transactions_by_year(year)
    rows = []
    for tx in txs:
        if tx.category == category and tx.trans_type == TransactionType.EXPENSE:
            m = tx.trans_date.strftime("%Y-%m")
            rows.append({"month": m, "amount": tx.amount})
    if not rows:
        return pd.DataFrame(columns=["month", "amount"])
    df = pd.DataFrame(rows)
    return df.groupby("month", as_index=False).sum().sort_values("month")


def get_recent_months_trend(months_count: int) -> pd.DataFrame:
    from fin.db import get_transactions
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
    txs = get_transactions(start_date=start_date, end_date=end_date, trans_type=TransactionType.EXPENSE)
    rows = []
    for tx in txs:
        m = tx.trans_date.strftime("%Y-%m")
        rows.append({"month": m, "category": tx.category, "amount": tx.amount})
    if not rows:
        return pd.DataFrame(columns=["month", "category", "amount"])
    df = pd.DataFrame(rows)
    pivot = df.pivot_table(index="month", columns="category", values="amount", aggfunc="sum").fillna(0.0)
    return pivot.reset_index().sort_values("month")
