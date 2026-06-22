import os
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager

from fin.stats import (
    get_monthly_stats,
    get_recent_months_trend,
    get_category_trend,
    get_source_monthly_pivot,
    get_yearly_stats,
    compare_months,
)
from fin.models import YearlyReport

CHARTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "charts")


def _setup_chinese_font():
    candidates = [
        "Microsoft YaHei",
        "SimHei",
        "PingFang SC",
        "Noto Sans CJK SC",
        "Arial Unicode MS",
        "WenQuanYi Zen Hei",
    ]
    available = {f.name for f in font_manager.fontManager.ttflist}
    for f in candidates:
        if f in available:
            plt.rcParams["font.sans-serif"] = [f]
            break
    plt.rcParams["axes.unicode_minus"] = False


_setup_chinese_font()


def _ensure_charts_dir() -> str:
    Path(CHARTS_DIR).mkdir(parents=True, exist_ok=True)
    return CHARTS_DIR


def generate_monthly_pie_chart(month_str: str, output_path: Optional[str] = None) -> str:
    _ensure_charts_dir()
    stat = get_monthly_stats(month_str)
    cat_stats = stat.category_stats
    if not cat_stats:
        raise ValueError(f"{month_str} 无支出数据")

    labels = [cs.category for cs in cat_stats]
    sizes = [cs.total_amount for cs in cat_stats]
    total = sum(sizes)

    fig, ax = plt.subplots(figsize=(10, 7))
    colors = plt.cm.tab20.colors
    colors = colors[:len(labels)]

    def _autopct(pct):
        absolute = int(round(pct / 100. * total))
        return f"{pct:.1f}%\n¥{absolute:.0f}" if absolute >= 100 else f"{pct:.1f}%"

    wedges, texts, autotexts = ax.pie(
        sizes,
        labels=labels,
        autopct=_autopct,
        startangle=90,
        colors=colors,
        pctdistance=0.8,
        wedgeprops=dict(width=0.5, edgecolor="w"),
    )
    for t in texts:
        t.set_fontsize(11)
    for t in autotexts:
        t.set_fontsize(9)
        t.set_color("white")
        t.set_fontweight("bold")

    ax.set_title(f"{month_str} 支出分类饼图\n总支出: ¥{total:.2f}", fontsize=16, fontweight="bold", pad=20)
    plt.tight_layout()

    if output_path is None:
        output_path = os.path.join(CHARTS_DIR, f"pie_{month_str}.png")
    else:
        output_path = os.path.abspath(output_path)

    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


def generate_trend_line_chart(months_count: int, output_path: Optional[str] = None) -> str:
    _ensure_charts_dir()
    pivot = get_recent_months_trend(months_count)
    if pivot.empty or "month" not in pivot.columns:
        raise ValueError("无趋势数据")

    months = pivot["month"].tolist()
    cat_cols = [c for c in pivot.columns if c != "month"]

    if not cat_cols:
        raise ValueError("无分类支出数据")

    fig, ax = plt.subplots(figsize=(12, 7))
    colors = plt.cm.tab20.colors

    for i, cat in enumerate(cat_cols[:len(colors)]):
        ax.plot(
            months,
            pivot[cat].tolist(),
            marker="o",
            label=cat,
            linewidth=2,
            markersize=6,
            color=colors[i % len(colors)],
        )

    ax.set_xlabel("月份", fontsize=12)
    ax.set_ylabel("支出金额 (¥)", fontsize=12)
    ax.set_title(f"近{months_count}个月分类支出趋势图", fontsize=16, fontweight="bold", pad=20)
    ax.legend(loc="best", fontsize=10, framealpha=0.9, ncol=min(3, len(cat_cols)))
    ax.grid(True, linestyle="--", alpha=0.6)
    plt.xticks(rotation=45)

    totals = pivot[cat_cols].sum(axis=1).tolist()
    for i, m in enumerate(months):
        ax.annotate(
            f"¥{totals[i]:.0f}",
            xy=(i, totals[i]),
            ha="center",
            fontsize=9,
            xytext=(0, 10),
            textcoords="offset points",
        )

    plt.tight_layout()

    if output_path is None:
        output_path = os.path.join(CHARTS_DIR, f"trend_{months_count}months.png")
    else:
        output_path = os.path.abspath(output_path)

    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


def generate_category_yearly_bar_chart(category: str, year: str, output_path: Optional[str] = None) -> str:
    _ensure_charts_dir()
    trend_df = get_category_trend(category, year)
    if trend_df.empty:
        raise ValueError(f"{year}年{category}无数据")

    months_full = [f"{year}-{m:02d}" for m in range(1, 13)]
    amounts = []
    for m in months_full:
        row = trend_df[trend_df["month"] == m]
        amounts.append(round(row["amount"].iloc[0] if not row.empty else 0.0, 2))

    fig, ax = plt.subplots(figsize=(12, 7))

    bars = ax.bar(
        [m[5:] for m in months_full],
        amounts,
        color="#4C8BF5",
        edgecolor="#2E5FA1",
        width=0.6,
    )

    for bar, val in zip(bars, amounts):
        height = bar.get_height()
        if height > 0:
            ax.text(
                bar.get_x() + bar.get_width() / 2.0,
                height,
                f"¥{val:.0f}",
                ha="center",
                va="bottom",
                fontsize=10,
                fontweight="bold",
            )

    total = sum(amounts)
    ax.set_xlabel("月份", fontsize=12)
    ax.set_ylabel("支出金额 (¥)", fontsize=12)
    ax.set_title(f"{year}年 {category} 月度支出柱状图\n全年总计: ¥{total:.2f}", fontsize=16, fontweight="bold", pad=20)
    ax.grid(True, axis="y", linestyle="--", alpha=0.6)
    plt.xticks(rotation=0)
    plt.tight_layout()

    if output_path is None:
        output_path = os.path.join(CHARTS_DIR, f"bar_{category}_{year}.png")
    else:
        output_path = os.path.abspath(output_path)

    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


def generate_source_compare_stacked_chart(year: Optional[str] = None,
                                          months_count: Optional[int] = None,
                                          output_path: Optional[str] = None) -> str:
    _ensure_charts_dir()
    pivot = get_source_monthly_pivot(year=year, months_count=months_count)
    if pivot.empty or "month" not in pivot.columns:
        raise ValueError("无来源对比数据")

    months = pivot["month"].tolist()
    source_cols = [c for c in pivot.columns if c != "month"]
    if not source_cols:
        raise ValueError("无来源数据")

    fig, ax = plt.subplots(figsize=(12, 7))
    colors = plt.cm.Set2.colors + plt.cm.Paired.colors

    bottom = [0.0] * len(months)
    for i, src in enumerate(source_cols):
        values = pivot[src].tolist()
        bars = ax.bar(
            months,
            values,
            bottom=bottom,
            label=src,
            color=colors[i % len(colors)],
            edgecolor="white",
            linewidth=0.5,
        )
        for j, (bar, val) in enumerate(zip(bars, values)):
            if val > 0:
                bottom_pos = bottom[j] if isinstance(bottom[j], (int, float)) else bottom[j]
                ax.text(
                    bar.get_x() + bar.get_width() / 2.0,
                    bottom_pos + val / 2.0,
                    f"¥{val:.0f}",
                    ha="center",
                    va="center",
                    fontsize=8,
                    color="white",
                    fontweight="bold",
                )
            if isinstance(bottom[j], (int, float)):
                bottom[j] = bottom[j] + val
            else:
                bottom[j] = bottom[j] + val

    ax.set_xlabel("月份", fontsize=12)
    ax.set_ylabel("支出金额 (¥)", fontsize=12)
    title_suffix = f" ({year}年)" if year else (f" (近{months_count}个月)" if months_count else "")
    ax.set_title(f"多来源支出对比堆叠图{title_suffix}", fontsize=16, fontweight="bold", pad=20)
    ax.legend(loc="best", fontsize=10, framealpha=0.9)
    ax.grid(True, axis="y", linestyle="--", alpha=0.6)
    plt.xticks(rotation=45)

    totals = pivot[source_cols].sum(axis=1).tolist()
    for i, m in enumerate(months):
        ax.annotate(
            f"合计¥{totals[i]:.0f}",
            xy=(i, totals[i]),
            ha="center",
            fontsize=9,
            fontweight="bold",
            xytext=(0, 8),
            textcoords="offset points",
        )

    plt.tight_layout()

    if output_path is None:
        suffix = f"_{year}" if year else (f"_{months_count}m" if months_count else "")
        output_path = os.path.join(CHARTS_DIR, f"source_stacked{suffix}.png")
    else:
        output_path = os.path.abspath(output_path)

    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


def generate_yearly_category_ranking_chart(report: YearlyReport, top_n: int = 10,
                                           output_path: Optional[str] = None) -> str:
    _ensure_charts_dir()
    top_cats = report.top_expense_categories[:top_n]
    if not top_cats:
        raise ValueError(f"{report.year}年无支出分类数据")

    labels = [cs.category for cs in reversed(top_cats)]
    amounts = [cs.total_amount for cs in reversed(top_cats)]

    fig, ax = plt.subplots(figsize=(12, max(6, len(top_cats) * 0.6)))
    colors = plt.cm.RdYlGn_r([i / len(top_cats) for i in range(len(top_cats))])

    bars = ax.barh(labels, amounts, color=colors, edgecolor="#555555", height=0.7)
    for bar, val in zip(bars, amounts):
        ax.text(
            bar.get_width(),
            bar.get_y() + bar.get_height() / 2.0,
            f" ¥{val:,.0f} ({round(val/report.total_expense*100, 1)}%)",
            ha="left",
            va="center",
            fontsize=10,
            fontweight="bold",
        )

    ax.set_xlabel("年度支出金额 (¥)", fontsize=12)
    ax.set_title(f"{report.year}年 支出分类排行榜 TOP {len(top_cats)}\n全年总支出: ¥{report.total_expense:,.2f}",
                 fontsize=16, fontweight="bold", pad=20)
    ax.grid(True, axis="x", linestyle="--", alpha=0.6)
    plt.tight_layout()

    if output_path is None:
        output_path = os.path.join(CHARTS_DIR, f"ranking_categories_{report.year}.png")
    else:
        output_path = os.path.abspath(output_path)

    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


def generate_yearly_monthly_trend_chart(report: YearlyReport,
                                        output_path: Optional[str] = None) -> str:
    _ensure_charts_dir()
    if not report.monthly_breakdown:
        raise ValueError(f"{report.year}年月度数据为空")

    months = [m.month for m in report.monthly_breakdown]
    incomes = [m.total_income for m in report.monthly_breakdown]
    expenses = [m.total_expense for m in report.monthly_breakdown]
    nettings = [m.net_saving for m in report.monthly_breakdown]

    fig, ax1 = plt.subplots(figsize=(12, 7))

    x = range(len(months))
    w = 0.35
    ax1.bar([i - w / 2 for i in x], incomes, width=w, label="收入", color="#27AE60", edgecolor="#1E8449")
    ax1.bar([i + w / 2 for i in x], expenses, width=w, label="支出", color="#E74C3C", edgecolor="#B03A2E")
    ax1.set_xlabel("月份", fontsize=12)
    ax1.set_ylabel("金额 (¥)", fontsize=12)
    ax1.set_xticks(list(x))
    ax1.set_xticklabels([m[5:] for m in months], rotation=0)

    ax2 = ax1.twinx()
    ax2.plot(x, nettings, "o-", label="结余", color="#2980B9", linewidth=2.5, markersize=8)
    ax2.axhline(y=0, color="#7F8C8D", linestyle="--", alpha=0.8)
    ax2.set_ylabel("结余金额 (¥)", fontsize=12, color="#2980B9")
    ax2.tick_params(axis="y", labelcolor="#2980B9")

    for i, (inc, exp, net) in enumerate(zip(incomes, expenses, nettings)):
        ax1.text(i - w / 2, inc, f"¥{inc:,.0f}", ha="center", va="bottom", fontsize=8)
        ax1.text(i + w / 2, exp, f"¥{exp:,.0f}", ha="center", va="bottom", fontsize=8)
        ax2.text(i, net, f"¥{net:,.0f}", ha="center", va="bottom" if net >= 0 else "top", fontsize=9, fontweight="bold", color="#2980B9")

    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="best", fontsize=10, framealpha=0.9)
    ax1.grid(True, axis="y", linestyle="--", alpha=0.6)
    ax1.set_title(f"{report.year}年 月度收支趋势图\n"
                  f"年收入 ¥{report.total_income:,.2f} / 年支出 ¥{report.total_expense:,.2f} / "
                  f"年结余 ¥{report.net_saving:,.2f}",
                  fontsize=15, fontweight="bold", pad=20)
    plt.tight_layout()

    if output_path is None:
        output_path = os.path.join(CHARTS_DIR, f"yearly_trend_{report.year}.png")
    else:
        output_path = os.path.abspath(output_path)

    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path


def generate_compare_chart(month_a: str, month_b: str,
                           output_path: Optional[str] = None) -> str:
    _ensure_charts_dir()
    result = compare_months(month_a, month_b)

    cats_a = {d["category"]: d["month_a_amount"] for d in result.category_diffs}
    cats_b = {d["category"]: d["month_b_amount"] for d in result.category_diffs}
    all_cats = sorted(set(cats_a.keys()) | set(cats_b.keys()),
                      key=lambda c: max(cats_a.get(c, 0), cats_b.get(c, 0)),
                      reverse=True)

    if not all_cats:
        raise ValueError("无对比数据")

    vals_a = [cats_a.get(c, 0.0) for c in all_cats]
    vals_b = [cats_b.get(c, 0.0) for c in all_cats]

    fig, ax = plt.subplots(figsize=(max(10, len(all_cats) * 1.2), 7))
    x = range(len(all_cats))
    w = 0.35

    bars_a = ax.bar([i - w / 2 for i in x], vals_a, width=w,
                    label=month_a, color="#3498DB", edgecolor="#2471A3")
    bars_b = ax.bar([i + w / 2 for i in x], vals_b, width=w,
                    label=month_b, color="#E74C3C", edgecolor="#B03A2E")

    for bar, val in zip(bars_a, vals_a):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width() / 2.0, bar.get_height(),
                    f"¥{val:,.0f}", ha="center", va="bottom", fontsize=8, color="#2471A3")
    for bar, val in zip(bars_b, vals_b):
        if val > 0:
            ax.text(bar.get_x() + bar.get_width() / 2.0, bar.get_height(),
                    f"¥{val:,.0f}", ha="center", va="bottom", fontsize=8, color="#B03A2E")

    ax.set_xticks(list(x))
    ax.set_xticklabels(all_cats, rotation=30, ha="right")
    ax.set_ylabel("支出金额 (¥)", fontsize=12)
    ax.legend(loc="best", fontsize=10, framealpha=0.9)
    ax.grid(True, axis="y", linestyle="--", alpha=0.6)
    ax.set_title(f"{month_a} vs {month_b} 支出分类对比\n"
                 f"{month_a}: ¥{result.total_expense_a:,.2f} → "
                 f"{month_b}: ¥{result.total_expense_b:,.2f}",
                 fontsize=15, fontweight="bold", pad=20)
    plt.tight_layout()

    if output_path is None:
        output_path = os.path.join(CHARTS_DIR, f"compare_{month_a}_vs_{month_b}.png")
    else:
        output_path = os.path.abspath(output_path)

    fig.savefig(output_path, dpi=150, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return output_path
