import os
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
from matplotlib import font_manager

from fin.stats import get_monthly_stats, get_recent_months_trend, get_category_trend

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
    Path(CHARTS_DIR).parent.mkdir(parents=True, exist_ok=True)
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
