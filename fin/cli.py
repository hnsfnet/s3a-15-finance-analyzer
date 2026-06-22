import os
import sys
from datetime import date, timedelta

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich import box
from rich.columns import Columns
from rich.padding import Padding

from fin.db import (
    init_db,
    init_category_rules,
    get_uncategorized_transactions,
    get_all_categories,
    get_all_sources,
    update_transaction_category,
    load_category_rules,
    set_budget,
    get_budgets,
    get_budget_by_category,
    delete_budget,
    CATEGORY_RULES_PATH,
    DB_PATH,
)
from fin.importer import import_csv_file, SOURCE_COLUMN_MAPPINGS
from fin.categorizer import Categorizer, recategorize_all
from fin.models import BudgetPeriod, BudgetProgress
from fin.stats import (
    get_monthly_stats,
    get_yearly_stats,
    compare_months,
    check_month_budget,
    detect_recurring_transactions,
    generate_yearly_report,
)
from fin.charts import (
    generate_monthly_pie_chart,
    generate_trend_line_chart,
    generate_category_yearly_bar_chart,
    generate_source_compare_stacked_chart,
    generate_yearly_category_ranking_chart,
    generate_yearly_monthly_trend_chart,
    CHARTS_DIR,
)

console = Console()


class InitGroup(click.Group):
    def invoke(self, ctx):
        _ensure_init()
        return super().invoke(ctx)


def _ensure_init():
    init_db()
    init_category_rules()


def _format_money(amount: float) -> str:
    color = "green" if amount >= 0 else "red"
    sign = "+" if amount > 0 else ""
    return f"[{color}]{sign}¥{amount:,.2f}[/]"


def _budget_bar(progress: BudgetProgress, width: int = 20) -> str:
    filled = int(min(progress.percentage / 100.0, 1.0) * width)
    if progress.status == "over":
        fill_char, bar_color = "█", "[bold red]"
    elif progress.status == "warning":
        fill_char, bar_color = "█", "[bold yellow]"
    else:
        fill_char, bar_color = "█", "[bold green]"
    bar = fill_char * filled + "░" * (width - filled)
    return f"{bar_color}{bar}[/] {progress.percentage:.1f}%"


def _budget_legend() -> str:
    return ("[green]█<80% 正常[/] | [yellow]█80-100% 警戒[/] | [red]█>100% 超支[/]")


cli = InitGroup(help="个人财务分析工具 - 导入账单、自动分类、统计分析、生成图表")
cli.params = []
cli.help = "个人财务分析工具 - 导入账单、自动分类、统计分析、生成图表"


@cli.command("import", short_help="导入银行/支付平台账单 CSV")
@click.argument("filepath", type=click.Path(exists=True, readable=True))
@click.option(
    "--source", "-s",
    type=click.Choice(list(SOURCE_COLUMN_MAPPINGS.keys()) + ["自动识别"]),
    default="自动识别",
    help="账单来源，默认自动识别",
)
def import_cmd(filepath: str, source: str):
    """导入银行/支付平台账单 CSV 文件"""
    source_param = None if source == "自动识别" else source
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            transient=False,
            console=console,
        ) as progress:
            task = progress.add_task("解析账单文件中...", total=None)
            result = import_csv_file(filepath, source_param)
            progress.update(task, completed=True)

        panel_content = "\n".join([
            f"[cyan]文件:[/cyan] {result['filepath']}",
            f"[bold blue]来源:[/bold blue] {result['source']}",
            f"CSV 行数: [white]{result['total_rows']}[/white]",
            f"有效交易: [green]{result['parsed']}[/green]",
            f"[bold green]新增导入:[/bold green] {result['inserted']}",
            f"[yellow]重复跳过:[/yellow] {result['duplicates']}",
        ])
        console.print(Panel(panel_content, title="导入完成", border_style="green", expand=False))
        if result["inserted"] == 0 and result["duplicates"] == 0:
            console.print("[yellow]未解析到任何有效交易，请检查 CSV 格式是否匹配[/yellow]")
    except FileNotFoundError as e:
        console.print(f"[red]文件错误: {e}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]导入失败: {e}[/red]")
        import traceback
        console.print(traceback.format_exc())
        sys.exit(1)


@cli.group("budget", short_help="预算管理：set/show/delete")
def budget_cmd():
    """预算管理 - 设定分类预算、查看设置、删除预算"""
    pass


@budget_cmd.command("set", short_help="设定月/年度预算")
@click.argument("category", required=False)
@click.option("--limit", "-l", type=float, help="分类预算金额（设置分类预算时使用）")
@click.option("--total", "-t", type=float, default=None, help="设定总预算金额，如 --total 10000")
@click.option("--period", "-p", type=click.Choice(["monthly", "yearly"]), default="monthly", help="预算周期")
def budget_set_cmd(category: str, limit: float, total: float, period: str):
    """设定预算：fin budget set 餐饮 --limit 3000 或 fin budget set --total 10000"""
    use_total = total is not None and total > 0
    if not use_total and not category:
        console.print("[red]错误: 请指定分类，或用 --total <金额> 设定总预算[/red]")
        console.print("示例:")
        console.print("  fin budget set 餐饮 --limit 3000")
        console.print("  fin budget set --total 10000")
        sys.exit(1)
    if use_total:
        amount = total
    else:
        if limit is None or limit <= 0:
            console.print("[red]错误: --limit 必须为正数[/red]")
            sys.exit(1)
        amount = limit

    cat_key = "__total__" if use_total else category
    budget = set_budget(cat_key, amount, BudgetPeriod(period))
    label = "总预算" if use_total else f"分类 [{cat_key}]"
    period_label = "月" if period == "monthly" else "年"
    console.print(
        Panel(
            f"[green]已设定{period_label}度预算[/green]\n"
            f"{label}: [bold yellow]¥{amount:,.2f}[/bold yellow]",
            title=f"预算设定成功 ({period})", border_style="green", expand=False
        )
    )


@budget_cmd.command("show", short_help="查看所有预算设定")
@click.option("--period", "-p", type=click.Choice(["monthly", "yearly", "all"]), default="all", help="按周期筛选")
def budget_show_cmd(period: str):
    """查看所有预算设定"""
    filter_period = None if period == "all" else BudgetPeriod(period)
    budgets = get_budgets(filter_period)

    if not budgets:
        console.print("[yellow]尚未设定任何预算[/yellow]")
        console.print("使用 fin budget set <分类> --limit <金额> 来设定")
        return

    table = Table(title="预算设定", box=box.ROUNDED)
    table.add_column("ID", style="cyan", justify="right")
    table.add_column("类型", style="magenta")
    table.add_column("预算对象", style="bold")
    table.add_column("周期", style="yellow")
    table.add_column("金额", style="green", justify="right")

    for b in budgets:
        label = "[bold]总预算[/bold]" if b.category == "__total__" else b.category
        type_label = "总体" if b.category == "__total__" else "分类"
        period_label = "月度" if b.period == BudgetPeriod.MONTHLY else "年度"
        table.add_row(str(b.id), type_label, label, period_label, f"¥{b.limit:,.2f}")

    console.print(table)


@budget_cmd.command("delete", short_help="删除预算")
@click.argument("category")
@click.option("--period", "-p", type=click.Choice(["monthly", "yearly"]), default="monthly", help="预算周期")
@click.option("--total", "-t", is_flag=True, help="删除总预算（无需 category，但参数占位仍需传值如 total）")
def budget_delete_cmd(category: str, period: str, total: bool):
    """删除预算：fin budget delete 餐饮 或 fin budget delete total --total"""
    cat_key = "__total__" if total else category
    if delete_budget(cat_key, BudgetPeriod(period)):
        console.print(f"[green]已删除 {period} 预算: {cat_key}[/green]")
    else:
        console.print(f"[yellow]未找到该预算设定: {cat_key} ({period})[/yellow]")


@cli.command("check", short_help="检查当月预算使用情况")
@click.option("--month", "-m", "month", help="检查指定月份，格式 2024-06，默认当月")
def check_cmd(month: str):
    """快速检查预算使用情况，找出超支或接近超支的分类"""
    if not month:
        month = date.today().strftime("%Y-%m")

    with console.status("[bold green]检查预算中..."):
        result = check_month_budget(month)

    if result["budgets_count"] == 0:
        console.print(Panel(
            f"[yellow]{month} 未设定任何预算[/yellow]\n"
            "使用 fin budget set 来设定预算后再检查",
            title="预算检查", border_style="yellow", expand=False
        ))
        return

    tp = result["total_progress"]
    title_extra = ""
    if tp:
        icon = "✅" if tp.status == "normal" else ("⚠️" if tp.status == "warning" else "🚨")
        title_extra = f" {icon} 总支出 ¥{tp.spent:,.0f}/¥{tp.budget:,.0f} ({tp.percentage:.1f}%)"

    over = result["over"]
    warn = result["warning"]
    normal = result["normal"]

    def _prog_row(bp: BudgetProgress, tag: str, tag_color: str):
        remaining = f"超支¥{-bp.remaining:,.0f}" if bp.remaining < 0 else f"剩余¥{bp.remaining:,.0f}"
        return [tag, bp.category, f"¥{bp.spent:,.0f}/¥{bp.budget:,.0f}", f"{bp.percentage:.1f}%", remaining, _budget_bar(bp, 18)]

    table = Table(title=f"{month} 预算使用检查{title_extra}", box=box.ROUNDED, show_lines=False)
    table.add_column("状态", no_wrap=True)
    table.add_column("分类", style="bold")
    table.add_column("花费/预算", justify="right")
    table.add_column("使用%", justify="right")
    table.add_column("余额", justify="right")
    table.add_column("进度条")

    for bp in over:
        table.add_row(*_prog_row(bp, "[red]🚨超支[/red]", "red"))
    for bp in warn:
        table.add_row(*_prog_row(bp, "[yellow]⚠️警戒[/yellow]", "yellow"))
    for bp in normal:
        table.add_row(*_prog_row(bp, "[green]✅正常[/green]", "green"))

    console.print(table)
    console.print("图例: " + _budget_legend())

    if over:
        console.print(f"\n[red]🚨 有 {len(over)} 项已经超预算！请关注消费。[/red]")
    if warn:
        console.print(f"[yellow]⚠️  有 {len(warn)} 项已超过 80%，即将超支。[/yellow]")
    if not over and not warn:
        console.print(f"\n[green]🎉 所有预算使用情况均在正常范围内~[/green]")


@cli.command("detect", short_help="自动检测周期性固定支出")
@click.option("--min-occurrences", "-n", type=int, default=3, help="最小重复次数，默认 3 次")
@click.option("--tolerance", "-t", type=float, default=10.0, help="周期变异系数容差(%)，默认10%")
def detect_cmd(min_occurrences: int, tolerance: float):
    """扫描所有支出，识别金额+描述相同且时间间隔规律的周期性固定支出"""
    with console.status("[bold green]扫描周期性支出中..."):
        recs = detect_recurring_transactions(
            min_occurrences=min_occurrences,
            std_tolerance=tolerance,
        )

    if not recs:
        console.print(Panel(
            f"[yellow]未检测到满足条件的周期性支出[/yellow]\n"
            f"条件：重复至少 {min_occurrences} 次，且周期变异系数 <= {tolerance}%\n"
            "可以尝试降低 --min-occurrences 或提高 --tolerance",
            title="周期性支出检测", border_style="yellow", expand=False
        ))
        return

    table = Table(title=f"检测到 {len(recs)} 项疑似周期性固定支出", box=box.ROUNDED)
    table.add_column("#", style="cyan", justify="right")
    table.add_column("描述", style="bold", overflow="fold")
    table.add_column("分类", style="magenta")
    table.add_column("金额", style="yellow", justify="right")
    table.add_column("次数", justify="right")
    table.add_column("周期", style="green")
    table.add_column("平均间隔", justify="right")
    table.add_column("置信度", justify="right")
    table.add_column("下次预计日期", style="cyan")

    for i, r in enumerate(recs, 1):
        next_date = str(r.next_predicted_date) if r.next_predicted_date else "-"
        conf_color = "green" if r.confidence >= 90 else ("yellow" if r.confidence >= 70 else "red")
        table.add_row(
            str(i),
            (r.description[:40] + "…") if len(r.description) > 40 else r.description,
            r.category,
            f"¥{r.amount:,.2f}",
            str(len(r.occurrences)),
            r.estimated_period,
            f"{r.avg_interval_days:.0f}天",
            f"[{conf_color}]{r.confidence:.0f}%[/{conf_color}]",
            next_date,
        )

    console.print(table)
    console.print(f"\n[dim]💡 算法说明：按【相同描述归一化 + 相同金额取整】分组，时间间隔变异系数 CV <= {tolerance}% 视为周期稳定[/dim]")
    console.print(f"[dim]💡 共扫描全部交易记录，重复次数 >= {min_occurrences} 才会列入[/dim]")


def _render_monthly_stats(month_str: str, source: str | None = None):
    stat = get_monthly_stats(month_str, source=source, calc_budget=True)

    title_parts = [f"[bold blue]{month_str}[/bold blue]"]
    if source:
        title_parts.append(f"[magenta](来源: {source})[/magenta]")
    title = " ".join(title_parts)

    tp = stat.total_budget_progress
    budget_line = ""
    if tp:
        status_color = "green" if tp.status == "normal" else ("yellow" if tp.status == "warning" else "red")
        budget_line = f"  |  总预算进度: [{status_color}]{_budget_bar(tp, 16)}[/{status_color}]"

    summary_lines = [
        f"[bold white]💰 总收入:[/bold white] {_format_money(stat.total_income)}    ",
        f"[bold white]💸 总支出:[/bold white] {_format_money(stat.total_expense)}    ",
        f"[bold white]📈 结余:[/bold white] {_format_money(stat.net_saving)}",
        budget_line,
    ]
    summary = Text.from_markup("\n".join(summary_lines))
    console.print(Panel(summary, title="📅 " + title, border_style="blue", expand=False))

    if not stat.category_stats:
        console.print("[yellow]当月无支出数据[/yellow]")
        return

    table = Table(title=f"📊 支出分类明细 (共 {len(stat.category_stats)} 类)", box=box.ROUNDED)
    table.add_column("排名", justify="center", style="cyan", width=5)
    table.add_column("分类", style="bold magenta")
    table.add_column("金额", justify="right", style="yellow")
    table.add_column("笔数", justify="center", style="green")
    table.add_column("占比", justify="right", style="red")
    table.add_column("预算进度", style="white")

    for i, cs in enumerate(stat.category_stats, 1):
        budget_cell = ""
        if cs.budget_progress:
            budget_cell = _budget_bar(cs.budget_progress, 16)
        table.add_row(
            str(i),
            cs.category,
            f"¥{cs.total_amount:,.2f}",
            str(cs.count),
            f"{cs.percentage:.1f}%",
            budget_cell,
        )
    console.print(table)
    if any(cs.budget_progress is not None for cs in stat.category_stats):
        console.print("图例: " + _budget_legend())

    if stat.source_stats and stat.source_stats.sources:
        src_table = Table(title="🏦 来源分布", box=box.ROUNDED, width=70)
        src_table.add_column("来源", style="bold blue")
        src_table.add_column("金额", justify="right", style="green")
        src_table.add_column("笔数", justify="center", style="cyan")
        src_table.add_column("占比", justify="right", style="magenta")
        src_table.add_column("占比条", style="white")
        max_pct = max(s.percentage for s in stat.source_stats.sources) or 1.0
        for s in stat.source_stats.sources:
            bar_len = int(s.percentage / max_pct * 20)
            bar = "▓" * bar_len + "░" * (20 - bar_len)
            src_table.add_row(
                s.source,
                f"¥{s.total_amount:,.2f}",
                str(s.count),
                f"{s.percentage:.1f}%",
                bar,
            )
        console.print(src_table)


def _render_yearly_stats(year: str, source: str | None = None):
    months = get_yearly_stats(year, source=source, calc_budget=False)
    if not months:
        console.print(f"[yellow]{year} 年无交易数据[/yellow]")
        return

    total_income = sum(m.total_income for m in months)
    total_expense = sum(m.total_expense for m in months)
    title = f"📅 [bold blue]{year}[/bold blue] 年财务总结"
    if source:
        title += f" [magenta](来源: {source})[/magenta]"

    summary = Text.from_markup("\n".join([
        f"💰 年总收入: {_format_money(total_income)}    💸 年总支出: {_format_money(total_expense)}    📈 年结余: {_format_money(total_income - total_expense)}",
        f"📆 共 [cyan]{len(months)}[/cyan] 个月有交易记录    📊 月均支出: [yellow]¥{total_expense / len(months):,.2f}[/yellow]",
    ]))
    console.print(Panel(summary, title=title, border_style="blue", expand=False))

    table = Table(title=f"📊 {year} 年月度汇总", box=box.ROUNDED)
    table.add_column("月份", style="bold cyan", justify="center")
    table.add_column("收入", justify="right", style="green")
    table.add_column("支出", justify="right", style="red")
    table.add_column("结余", justify="right", style="yellow")

    for m in months:
        table.add_row(
            m.month,
            f"¥{m.total_income:,.2f}",
            f"¥{m.total_expense:,.2f}",
            f"¥{m.net_saving:,.2f}",
        )
    table.add_row(
        "[bold]合计[/bold]",
        f"[bold]¥{total_income:,.2f}[/bold]",
        f"[bold]¥{total_expense:,.2f}[/bold]",
        f"[bold]¥{total_income - total_expense:,.2f}[/bold]",
        end_section=True,
    )
    console.print(table)


def _render_compare(month_a: str, month_b: str, source: str | None = None):
    result = compare_months(month_a, month_b, source=source)

    def _pct_style(pct):
        if pct == float("inf"):
            return "[green]+∞%[/]"
        if pct > 0:
            return f"[red]+{pct:.1f}%[/]"
        elif pct < 0:
            return f"[green]{pct:.1f}%[/]"
        else:
            return "[white]0.0%[/]"

    diff_abs = result.total_expense_b - result.total_expense_a
    title = f"🔍 [bold blue]{result.month_a}[/bold blue] → [bold blue]{result.month_b}[/bold blue] 支出对比"
    if source:
        title += f" [magenta]({source})[/magenta]"

    summary = Text.from_markup("\n".join([
        f"  {result.month_a}: {_format_money(result.total_expense_a)}",
        f"  {result.month_b}: {_format_money(result.total_expense_b)}",
        f"  差异: {_format_money(diff_abs)}    环比: {_pct_style(result.expense_change_pct)}",
    ]))
    console.print(Panel(summary, title=title, border_style="magenta", expand=False))

    table = Table(title="📊 分类对比明细", box=box.ROUNDED)
    table.add_column("分类", style="bold magenta")
    table.add_column(f"{result.month_a}", justify="right", style="cyan")
    table.add_column(f"{result.month_b}", justify="right", style="blue")
    table.add_column("差额", justify="right", style="yellow")
    table.add_column("环比", justify="right", style="red")

    for d in result.category_diffs:
        diff_text = (f"[red]+¥{d['diff']:,.2f}[/]" if d["diff"] > 0
                     else (f"[green]¥{d['diff']:,.2f}[/]" if d["diff"] < 0 else "¥0.00"))
        table.add_row(
            d["category"],
            f"¥{d['month_a_amount']:,.2f}" if d["month_a_amount"] > 0 else "-",
            f"¥{d['month_b_amount']:,.2f}" if d["month_b_amount"] > 0 else "-",
            diff_text,
            _pct_style(d["change_pct"]),
        )
    console.print(table)


@cli.command("stats", short_help="统计报表：月度/年度/对比/多来源")
@click.option("--month", "-m", "month", help="按月统计，格式 2024-06")
@click.option("--year", "-y", "year", help="按年统计，格式 2024")
@click.option("--compare", "-c", "compare", nargs=2, metavar="MONTH_A MONTH_B", help="对比两个月")
@click.option("--all", "all_sources", is_flag=True, help="跨所有来源汇总统计（默认行为，显示来源分布）")
@click.option("--source", "-S", "source", type=str, help="仅统计单个来源，如：招商银行 / 微信 / 支付宝")
def stats_cmd(month: str, year: str, compare: tuple, all_sources: bool, source: str | None):
    """统计报表：月度/年度/对比分析，支持按来源筛选"""
    if compare:
        _render_compare(compare[0], compare[1], source=source)
        return

    if year:
        _render_yearly_stats(year, source=source)
        return

    if month:
        _render_monthly_stats(month, source=source)
        return

    today = date.today()
    current_month = today.strftime("%Y-%m")
    console.print(f"[dim]未指定周期，默认显示当月: {current_month}[/dim]\n")
    _render_monthly_stats(current_month, source=source)


def _render_yearly_report_markdown(report, charts_paths: dict) -> str:
    lines: list[str] = []
    lines.append(f"# {report.year} 年度财务报告\n")
    lines.append(f"> 生成时间：{date.today().isoformat()}  \n")

    lines.append("## 一、全年收支概览\n")
    lines.append("| 指标 | 金额 (¥) |")
    lines.append("| --- | ---: |")
    lines.append(f"| 全年总收入 | {report.total_income:,.2f} |")
    lines.append(f"| 全年总支出 | {report.total_expense:,.2f} |")
    lines.append(f"| **年度结余** | **{report.net_saving:,.2f}** |")
    lines.append(f"| 交易月份数 | {report.total_months} |")
    lines.append(f"| 月均支出 | {report.avg_monthly_expense:,.2f} |")
    lines.append("")

    if report.previous_year_comparison:
        prev = report.previous_year_comparison
        lines.append("## 二、同比上一年对比\n")
        pct = prev.expense_change_pct
        sign = "+" if pct >= 0 else ""
        arrow = "📈" if pct > 0 else "📉"
        lines.append(f"{arrow} {prev.month_b} 对比 {prev.month_a}：支出 **{prev.total_expense_b:,.2f}** vs **{prev.total_expense_a:,.2f}**，**{sign}{pct:.1f}%**  \n")
        lines.append("| 分类 | 上一年 (¥) | 本年 (¥) | 差额 (¥) | 同比 |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for d in prev.category_diffs[:15]:
            dp = d["change_pct"]
            dp_text = "+∞%" if dp == float("inf") else f"{dp:+.1f}%"
            lines.append(f"| {d['category']} | {d['month_a_amount']:,.2f} | {d['month_b_amount']:,.2f} | {d['diff']:+,.2f} | {dp_text} |")
        lines.append("")

    if "yearly_trend" in charts_paths:
        lines.append("## 三、月度收支趋势\n")
        lines.append(f"![月度收支趋势]({charts_paths['yearly_trend']})\n")

    if "ranking" in charts_paths:
        lines.append("## 四、分类支出排行榜 TOP 10\n")
        lines.append(f"![分类支出排行]({charts_paths['ranking']})\n")

    lines.append("| 排名 | 分类 | 金额 (¥) | 笔数 | 占比 |")
    lines.append("| ---: | --- | ---: | ---: | ---: |")
    for i, cs in enumerate(report.top_expense_categories[:15], 1):
        lines.append(f"| {i} | {cs.category} | {cs.total_amount:,.2f} | {cs.count} | {cs.percentage:.1f}% |")
    lines.append("")

    if report.budget_summary:
        lines.append("## 五、预算执行情况\n")
        lines.append("| 分类 | 月预算 (¥) | 年实际支出 (¥) | 月均 (¥) | 年预算使用 |")
        lines.append("| --- | ---: | ---: | ---: | ---: |")
        for cat, data in report.budget_summary.items():
            label = "总预算" if cat == "__total__" else cat
            yearly_budget = data["limit"] * (12 if cat != "__total__" else 1)
            pct = data["spent"] / yearly_budget * 100 if yearly_budget > 0 else 0
            lines.append(f"| {label} | {data['limit']:,.2f} | {data['spent']:,.2f} | {data['avg_monthly']:,.2f} | {pct:.1f}% |")
        lines.append("")

    lines.append("## 六、消费最高的 10 笔交易\n")
    lines.append("| 排名 | 日期 | 分类 | 金额 (¥) | 描述 | 来源 |")
    lines.append("| ---: | --- | --- | ---: | --- | --- |")
    for i, tx in enumerate(report.top_10_transactions, 1):
        desc = (tx.raw_description[:40] + "…") if len(tx.raw_description) > 40 else tx.raw_description
        lines.append(f"| {i} | {tx.trans_date.isoformat()} | {tx.category} | {tx.amount:,.2f} | {desc.replace('|', ' ')} | {tx.source} |")
    lines.append("")

    if "source_stacked" in charts_paths:
        lines.append("## 七、月度来源分布\n")
        lines.append(f"![多来源堆叠图]({charts_paths['source_stacked']})\n")

    lines.append("---\n")
    lines.append("*本报告由 fin 财务分析工具自动生成*\n")
    return "\n".join(lines)


@cli.command("report", short_help="生成年度财务报告（Markdown + 图表）")
@click.option("--year", "-y", "year", help="指定年份，默认当前年")
@click.option("--output", "-o", "output_path", type=click.Path(), help="自定义输出的 .md 文件路径")
def report_cmd(year: str, output_path: str):
    """生成完整年度财务报告：Markdown 格式，内嵌图表链接"""
    if not year:
        year = str(date.today().year)

    with console.status(f"[bold green]生成 {year} 年度报告数据..."):
        report = generate_yearly_report(year)

    if report.total_months == 0:
        console.print(Panel(
            f"[yellow]{year} 年无交易记录，无法生成报告[/yellow]",
            title="年度报告", border_style="yellow", expand=False
        ))
        return

    charts_paths: dict = {}
    try:
        with console.status("[bold green]生成年度趋势图..."):
            charts_paths["yearly_trend"] = os.path.relpath(
                generate_yearly_monthly_trend_chart(report),
                os.getcwd()
            ).replace("\\", "/")
    except Exception as e:
        console.print(f"[dim]趋势图生成跳过: {e}[/dim]")

    try:
        with console.status("[bold green]生成分类排行图..."):
            charts_paths["ranking"] = os.path.relpath(
                generate_yearly_category_ranking_chart(report),
                os.getcwd()
            ).replace("\\", "/")
    except Exception as e:
        console.print(f"[dim]排行图生成跳过: {e}[/dim]")

    try:
        with console.status("[bold green]生成多来源堆叠图..."):
            charts_paths["source_stacked"] = os.path.relpath(
                generate_source_compare_stacked_chart(year=year),
                os.getcwd()
            ).replace("\\", "/")
    except Exception as e:
        console.print(f"[dim]堆叠图生成跳过: {e}[/dim]")

    with console.status("[bold green]渲染 Markdown..."):
        md = _render_yearly_report_markdown(report, charts_paths)

    if not output_path:
        output_path = f"report_{year}.md"
    output_path = os.path.abspath(output_path)
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(md)

    size_kb = os.path.getsize(output_path) / 1024
    content = "\n".join([
        f"[bold green]年度报告已生成[/bold green]",
        f"📄 Markdown 文件: [link=file://{output_path}]{output_path}[/link] ({size_kb:.1f} KB)",
        f"📊 嵌入图表: {len(charts_paths)} 张",
        f"📆 覆盖月份: {report.total_months}",
        f"💸 全年支出: ¥{report.total_expense:,.2f}  /  月均: ¥{report.avg_monthly_expense:,.2f}",
    ])
    console.print(Panel(content, title=f"🎉 {year} 年度报告生成成功", border_style="green", expand=False))
    console.print(f"💡 打开方式: [cyan]start \"{output_path}\"[/cyan]  或用 VS Code / Typora / 浏览器打开查看")


@cli.command("categorize", short_help="分类管理：规则/重新分类/交互式补充分类")
@click.option("--retry", "-r", is_flag=True, help="按最新规则重新分类所有交易")
@click.option("--interactive", "-i", is_flag=True, help="交互式手动补充分类")
@click.option("--add-rule", "-a", nargs=2, metavar="CATEGORY KEYWORD", help="添加分类规则")
@click.option("--list-rules", "-l", is_flag=True, help="查看所有分类规则")
def categorize_cmd(retry: bool, interactive: bool, add_rule: tuple, list_rules: bool):
    """管理交易分类：添加规则、重新分类、交互式手动补充分类"""
    categorizer = Categorizer()

    if list_rules:
        rules = categorizer.list_rules()
        table = Table(title="📋 分类规则列表", box=box.ROUNDED, show_lines=False)
        table.add_column("分类", style="bold cyan", no_wrap=True)
        table.add_column("关键词数量", style="magenta", justify="center")
        table.add_column("关键词列表", style="white")
        for cat, kws in sorted(rules.items()):
            table.add_row(cat, str(len(kws)), ", ".join(kws[:10]) + ("..." if len(kws) > 10 else ""))
        console.print(table)
        console.print(f"\n💡 配置文件位置: [link=file://{CATEGORY_RULES_PATH}]{CATEGORY_RULES_PATH}[/link]")
        return

    if add_rule:
        category, keyword = add_rule
        categorizer.add_rule(category, keyword)
        console.print(f"[green]已添加规则:[/green] [cyan]{category}[/] ← [yellow]\"{keyword}\"[/yellow]")
        return

    if retry:
        with console.status("[bold green]正在按最新规则重新分类..."):
            result = recategorize_all()
        console.print(f"[green]重新分类完成:[/green] 共 [white]{result['total']}[/] 笔，更新 [bold green]{result['updated']}[/] 笔")
        return

    if interactive:
        uncategorized = get_uncategorized_transactions()
        if not uncategorized:
            console.print("[green]没有未分类的交易[/green]")
            return
        console.print(f"[yellow]找到 {len(uncategorized)} 笔未分类交易，开始处理[/yellow]\n")

        all_cats = get_all_categories()
        cat_list = sorted([c for c in all_cats if c != "未分类"])
        new_count = 0
        for tx in uncategorized[:200]:
            console.print("\n" + "─" * 60)
            console.print(f"[bold]日期:[/bold] {tx.trans_date} | [bold]金额:[/bold] {_format_money(tx.amount)} | [bold]类型:[/bold] {tx.trans_type.value}")
            console.print(f"[bold]来源:[/bold] {tx.source}")
            console.print(f"[bold]描述:[/bold] [white]{tx.raw_description}[/white]")

            choices = [str(i + 1) for i in range(len(cat_list))] + ["n", "s", "q"]
            for i, c in enumerate(cat_list[:9]):
                console.print(f"  {i + 1}. {c}")
            if len(cat_list) > 9:
                console.print(f"  ... (更多分类请输入自定义名称)")
            console.print("  n. 新建分类  s. 跳过  q. 退出")

            ch = Prompt.ask("选择分类", choices=choices, show_choices=False, default="s")
            if ch == "q":
                break
            if ch == "s":
                continue
            if ch == "n":
                new_cat = Prompt.ask("请输入新分类名称")
                if new_cat.strip():
                    categorizer.add_category(new_cat.strip())
                    update_transaction_category(tx.id, new_cat.strip())
                    cat_list = sorted(get_all_categories())
                    cat_list = [c for c in cat_list if c != "未分类"]
                    new_count += 1
                    console.print(f"[green]已标记为: {new_cat.strip()}[/green]")
            elif ch.isdigit() and 1 <= int(ch) <= len(cat_list):
                selected = cat_list[int(ch) - 1]
                update_transaction_category(tx.id, selected)
                new_count += 1
                console.print(f"[green]已标记为: {selected}[/green]")
            else:
                if ch.strip() and ch not in choices:
                    update_transaction_category(tx.id, ch.strip())
                    new_count += 1
                    console.print(f"[green]已标记为: {ch.strip()}[/green]")

        console.print(f"\n[green]本次共补充分类 {new_count} 笔[/green]")
        remaining = len(get_uncategorized_transactions())
        if remaining > 0:
            console.print(f"[yellow]仍有 {remaining} 笔未分类，可再次运行 categorize -i 继续[/yellow]")
        return

    uncategorized = get_uncategorized_transactions()
    total = len(uncategorized)
    console.print(f"[bold]未分类交易统计:[/bold] [yellow]{total}[/] 笔待分类")
    if total > 0:
        table = Table(title=f"前 {min(20, total)} 笔未分类交易", box=box.ROUNDED)
        table.add_column("日期", style="cyan")
        table.add_column("金额", justify="right", style="yellow")
        table.add_column("来源", style="magenta")
        table.add_column("原始描述", style="white", overflow="fold")
        for tx in uncategorized[:20]:
            table.add_row(
                str(tx.trans_date),
                f"¥{tx.amount:,.2f}",
                tx.source,
                tx.raw_description[:80] + ("..." if len(tx.raw_description) > 80 else ""),
            )
        console.print(table)
    console.print("\n💡 用法:")
    console.print("  [green]fin categorize -i[/]  交互式补充分类")
    console.print("  [green]fin categorize -r[/]  按最新规则重新分类所有交易")
    console.print("  [green]fin categorize -a 餐饮 沙县小吃[/]  添加分类规则")
    console.print("  [green]fin categorize -l[/]  查看所有分类规则")


@cli.command("chart", short_help="生成图表：饼图/趋势/柱状/堆叠")
@click.option("--month", "-m", "month", help="生成当月支出饼图，格式 2024-06")
@click.option("--trend", "-t", "trend_months", type=int, metavar="N", help="生成近 N 个月趋势折线图")
@click.option("--category", "-g", "category", metavar="CATEGORY", help="指定分类，配合 --year 使用")
@click.option("--year", "-y", "year", metavar="YEAR", help="指定年份，配合 --category 生成柱状图")
@click.option("--source-compare", "source_compare", is_flag=True, help="生成多来源对比堆叠柱状图，配合 --year 或 --trend 使用")
@click.option("--output", "-o", "output", type=click.Path(), help="自定义输出路径")
def chart_cmd(month: str, trend_months: int, category: str, year: str, source_compare: bool, output: str):
    """生成图表：饼图/折线图/柱状图/多来源堆叠图，保存为 PNG"""
    try:
        generated = None

        if source_compare:
            with console.status("[bold green]生成多来源对比堆叠柱状图..."):
                generated = generate_source_compare_stacked_chart(
                    year=year,
                    months_count=trend_months if trend_months else None,
                    output_path=output,
                )
        elif category and year:
            with console.status(f"[bold green]生成 {year}年 {category} 柱状图..."):
                generated = generate_category_yearly_bar_chart(category, year, output)
        elif trend_months:
            with console.status(f"[bold green]生成近 {trend_months} 个月趋势图..."):
                generated = generate_trend_line_chart(trend_months, output)
        elif month:
            with console.status(f"[bold green]生成 {month} 饼图..."):
                generated = generate_monthly_pie_chart(month, output)
        else:
            today = date.today()
            current_month = today.strftime("%Y-%m")
            console.print(f"[dim]未指定图表类型，默认生成当月 {current_month} 饼图[/dim]")
            with console.status(f"[bold green]生成 {current_month} 饼图..."):
                generated = generate_monthly_pie_chart(current_month, output)

        if generated:
            size_kb = os.path.getsize(generated) / 1024
            content = "\n".join([
                f"[green]图表已生成[/green]",
                f"📁 路径: [link=file://{generated}]{generated}[/link]",
                f"📦 大小: {size_kb:.1f} KB",
            ])
            console.print(Panel(content, title="生成成功", border_style="green", expand=False))
            if sys.platform.startswith("win"):
                console.print(f"💡 直接打开: [cyan]explorer \"\"{generated}\"\"[/cyan]")
            elif sys.platform == "darwin":
                console.print(f"💡 直接打开: [cyan]open \"{generated}\"[/cyan]")
            else:
                console.print(f"💡 直接打开: [cyan]xdg-open \"{generated}\"[/cyan]")

    except ValueError as e:
        console.print(f"[yellow]⚠️  {e}[/yellow]")
    except Exception as e:
        console.print(f"[red]生成失败: {e}[/red]")
        import traceback
        console.print(traceback.format_exc())
        sys.exit(1)


@cli.command("info", short_help="显示数据与配置信息")
def info_cmd():
    """显示数据信息：数据库路径、配置路径、数据概览"""
    from fin.db import get_transactions
    from fin.models import TransactionType

    txs = get_transactions()
    total = len(txs)
    sources = {}
    for t in txs:
        sources[t.source] = sources.get(t.source, 0) + 1

    uncat = len(get_uncategorized_transactions())
    rules = load_category_rules()
    budgets = get_budgets()

    lines = [
        f"🗄️  数据库: [link=file://{DB_PATH}]{DB_PATH}[/link]",
        f"⚙️  配置文件: [link=file://{CATEGORY_RULES_PATH}]{CATEGORY_RULES_PATH}[/link]",
        f"📊 图表目录: [link=file://{CHARTS_DIR}]{CHARTS_DIR}[/link]",
        "",
        f"📋 交易总数: [bold cyan]{total}[/] 笔",
        f"🏦 来源分布: " + ", ".join(f"[blue]{k}[/]: {v}" for k, v in sources.items()),
        f"📂 分类规则: [magenta]{len(rules)}[/] 个分类",
        f"💰 预算设定: [yellow]{len(budgets)}[/] 项",
        f"❓ 未分类交易: [yellow]{uncat}[/] 笔",
    ]

    if total > 0:
        income_total = sum(t.amount for t in txs if t.trans_type == TransactionType.INCOME)
        expense_total = sum(t.amount for t in txs if t.trans_type == TransactionType.EXPENSE)
        lines.append("")
        lines.append(f"💰 历史总收入: [green]¥{income_total:,.2f}[/green]")
        lines.append(f"💸 历史总支出: [red]¥{expense_total:,.2f}[/red]")
        lines.append(f"📈 累计结余: {_format_money(income_total - expense_total)}")

    console.print(Panel("\n".join(lines), title="💡 财务工具信息", border_style="cyan", expand=False))


def _main():
    _ensure_init()
    return cli(standalone_mode=False)


if __name__ == "__main__":
    _ensure_init()
    cli()
