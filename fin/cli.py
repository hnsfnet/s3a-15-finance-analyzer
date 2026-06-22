import os
import sys
from datetime import date

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.prompt import Prompt, Confirm
from rich.text import Text
from rich import box

from fin.db import (
    init_db,
    init_category_rules,
    get_uncategorized_transactions,
    get_all_categories,
    update_transaction_category,
    load_category_rules,
    CATEGORY_RULES_PATH,
    DB_PATH,
)
from fin.importer import import_csv_file, SOURCE_COLUMN_MAPPINGS
from fin.categorizer import Categorizer, recategorize_all
from fin.stats import get_monthly_stats, get_yearly_stats, compare_months
from fin.charts import (
    generate_monthly_pie_chart,
    generate_trend_line_chart,
    generate_category_yearly_bar_chart,
    CHARTS_DIR,
)

console = Console()


def _ensure_init():
    init_db()
    init_category_rules()


def _format_money(amount: float) -> str:
    color = "green" if amount >= 0 else "red"
    sign = "+" if amount > 0 else ""
    return f"[{color}]{sign}¥{amount:,.2f}[/]"


@click.group()
@click.version_option(version="0.1.0", prog_name="fin")
def cli():
    """个人财务分析工具 - 导入账单、自动分类、统计分析、生成图表"""
    _ensure_init()


@cli.command("import")
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
            f"📄 文件: [cyan]{result['filepath']}[/]",
            f"🏦 来源: [bold blue]{result['source']}[/]",
            f"📊 CSV 行数: [white]{result['total_rows']}[/]",
            f"✅ 有效交易: [green]{result['parsed']}[/]",
            f"➕ 新增导入: [bold green]{result['inserted']}[/]",
            f"🔁 重复跳过: [yellow]{result['duplicates']}[/]",
        ])
        console.print(Panel(panel_content, title="✅ 导入完成", border_style="green", expand=False))

        if result["inserted"] == 0 and result["duplicates"] == 0:
            console.print("[yellow]⚠️  未解析到任何有效交易，请检查 CSV 格式是否匹配[/yellow]")
            console.print(f"支持的来源: {', '.join(SOURCE_COLUMN_MAPPINGS.keys())}")

    except FileNotFoundError as e:
        console.print(f"[red]❌ 文件错误: {e}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]❌ 导入失败: {e}[/red]")
        import traceback
        console.print(traceback.format_exc())
        sys.exit(1)


@cli.command("categorize")
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
        console.print(f"[green]✅ 已添加规则:[/green] [cyan]{category}[/] ← [yellow]\"{keyword}\"[/yellow]")
        return

    if retry:
        with console.status("[bold green]正在按最新规则重新分类..."):
            result = recategorize_all()
        console.print(f"[green]✅ 重新分类完成:[/green] 共 [white]{result['total']}[/] 笔，更新 [bold green]{result['updated']}[/] 笔")
        return

    if interactive:
        uncategorized = get_uncategorized_transactions()
        if not uncategorized:
            console.print("[green]🎉 太棒了！没有未分类的交易~[/green]")
            return
        console.print(f"[yellow]⚠️  找到 {len(uncategorized)} 笔未分类交易，开始处理[/yellow]\n")

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
                    console.print(f"[green]✅ 已标记为: {new_cat.strip()}[/green]")
            elif ch.isdigit() and 1 <= int(ch) <= len(cat_list):
                selected = cat_list[int(ch) - 1]
                update_transaction_category(tx.id, selected)
                new_count += 1
                console.print(f"[green]✅ 已标记为: {selected}[/green]")
            else:
                if ch.strip() and ch not in choices:
                    update_transaction_category(tx.id, ch.strip())
                    new_count += 1
                    console.print(f"[green]✅ 已标记为: {ch.strip()}[/green]")

        console.print(f"\n[green]🎉 本次共补充分类 {new_count} 笔[/green]")
        remaining = len(get_uncategorized_transactions())
        if remaining > 0:
            console.print(f"[yellow]仍有 {remaining} 笔未分类，可再次运行 categorize -i 继续[/yellow]")
        return

    uncategorized = get_uncategorized_transactions()
    total = len(uncategorized)
    console.print(f"📊 [bold]未分类交易统计:[/bold] [yellow]{total}[/] 笔待分类")
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


def _print_month_stats(month_str: str):
    stat = get_monthly_stats(month_str)
    summary = Text.assemble(
        ("📅 ", "bold"), (f"{month_str} 财务总结", "bold blue"), "\n",
        ("💰 总收入: ", "white"), _format_money(stat.total_income), "    ",
        ("💸 总支出: ", "white"), _format_money(stat.total_expense), "    ",
        ("📈 结余: ", "white"), _format_money(stat.net_saving),
    )
    console.print(Panel(summary, border_style="blue", expand=False))

    if not stat.category_stats:
        console.print("[yellow]当月无支出数据[/yellow]")
        return

    table = Table(title="📊 支出分类明细", box=box.ROUNDED)
    table.add_column("排名", justify="center", style="cyan", width=5)
    table.add_column("分类", style="bold magenta")
    table.add_column("金额", justify="right", style="yellow")
    table.add_column("笔数", justify="center", style="green")
    table.add_column("占比", justify="right", style="red")
    table.add_column("进度条", style="white")

    max_pct = max(cs.percentage for cs in stat.category_stats)
    for i, cs in enumerate(stat.category_stats, 1):
        bar_len = int(cs.percentage / max_pct * 20) if max_pct > 0 else 0
        bar = "█" * bar_len + "░" * (20 - bar_len)
        table.add_row(
            str(i),
            cs.category,
            f"¥{cs.total_amount:,.2f}",
            str(cs.count),
            f"{cs.percentage:.1f}%",
            bar,
        )
    console.print(table)


def _print_year_stats(year: str):
    months = get_yearly_stats(year)
    if not months:
        console.print(f"[yellow]{year} 年无交易数据[/yellow]")
        return

    total_income = sum(m.total_income for m in months)
    total_expense = sum(m.total_expense for m in months)
    summary = Text.assemble(
        ("📅 ", "bold"), (f"{year} 年财务总结", "bold blue"), "\n",
        ("💰 年总收入: ", "white"), _format_money(total_income), "    ",
        ("💸 年总支出: ", "white"), _format_money(total_expense), "    ",
        ("📈 年结余: ", "white"), _format_money(total_income - total_expense), "\n",
        ("📆 共 ", "white"), (f"{len(months)}", "cyan"), (" 个月有交易记录", "white"),
    )
    console.print(Panel(summary, border_style="blue", expand=False))

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
        "[bold]合计",
        f"[bold]¥{total_income:,.2f}",
        f"[bold]¥{total_expense:,.2f}",
        f"[bold]¥{total_income - total_expense:,.2f}",
        end_section=True,
    )
    console.print(table)


def _print_compare(month_a: str, month_b: str):
    result = compare_months(month_a, month_b)

    def _pct_style(pct):
        if pct == float("inf"):
            return "[green]+∞%[/]"
        if pct > 0:
            return f"[red]+{pct:.1f}%[/]"
        elif pct < 0:
            return f"[green]{pct:.1f}%[/]"
        else:
            return f"[white]0.0%[/]"

    diff_abs = result.total_expense_b - result.total_expense_a
    summary = Text.assemble(
        ("🔍 ", "bold"), ("支出对比分析: ", "bold blue"),
        (f"{result.month_a}", "cyan"), (" → ", "white"), (f"{result.month_b}", "cyan"), "\n",
        (f"  {result.month_a}: ", "white"), _format_money(result.total_expense_a), "\n",
        (f"  {result.month_b}: ", "white"), _format_money(result.total_expense_b), "\n",
        ("  差异: ", "white"), _format_money(diff_abs),
        ("  环比: ", "white"), _pct_style(result.expense_change_pct),
    )
    console.print(Panel(summary, border_style="magenta", expand=False))

    table = Table(title="📊 分类对比明细", box=box.ROUNDED)
    table.add_column("分类", style="bold magenta")
    table.add_column(f"{result.month_a}", justify="right", style="cyan")
    table.add_column(f"{result.month_b}", justify="right", style="blue")
    table.add_column("差额", justify="right", style="yellow")
    table.add_column("环比", justify="right", style="red")

    for d in result.category_diffs:
        table.add_row(
            d["category"],
            f"¥{d['month_a_amount']:,.2f}" if d["month_a_amount"] > 0 else "-",
            f"¥{d['month_b_amount']:,.2f}" if d["month_b_amount"] > 0 else "-",
            (f"[red]+¥{d['diff']:,.2f}[/]" if d["diff"] > 0 else (f"[green]¥{d['diff']:,.2f}[/]" if d["diff"] < 0 else "¥0.00")),
            _pct_style(d["change_pct"]),
        )
    console.print(table)


@cli.command("stats")
@click.option("--month", "-m", "month", help="按月统计，格式: 2024-06")
@click.option("--year", "-y", "year", help="按年统计，格式: 2024")
@click.option("--compare", "-c", "compare", nargs=2, metavar="MONTH_A MONTH_B", help="对比两个月")
def stats_cmd(month: str, year: str, compare: tuple):
    """统计报表：月度/年度/对比分析"""
    if compare:
        _print_compare(compare[0], compare[1])
        return

    if year:
        _print_year_stats(year)
        return

    if month:
        _print_month_stats(month)
        return

    today = date.today()
    current_month = today.strftime("%Y-%m")
    console.print(f"[dim]未指定周期，默认显示当月: {current_month}[/dim]\n")
    _print_month_stats(current_month)


@cli.command("chart")
@click.option("--month", "-m", "month", help="生成当月支出饼图，格式: 2024-06")
@click.option("--trend", "-t", "trend_months", type=int, metavar="N", help="生成近 N 个月趋势折线图")
@click.option("--category", "-g", "category", metavar="CATEGORY", help="指定分类，配合 --year 使用")
@click.option("--year", "-y", "year", metavar="YEAR", help="指定年份，配合 --category 生成柱状图")
@click.option("--output", "-o", "output", type=click.Path(), help="自定义输出路径")
def chart_cmd(month: str, trend_months: int, category: str, year: str, output: str):
    """生成图表：饼图/折线图/柱状图，保存为 PNG"""
    try:
        generated = None

        if category and year:
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
            console.print(Panel(
                f"✅ 图表已生成\n📁 路径: [link=file://{generated}]{generated}[/link]\n📦 大小: {size_kb:.1f} KB",
                title="🎉 生成成功", border_style="green", expand=False
            ))
            if sys.platform.startswith("win"):
                console.print(f"💡 可直接打开: [cyan]explorer \"{generated}\"[/cyan]")
            elif sys.platform == "darwin":
                console.print(f"💡 可直接打开: [cyan]open \"{generated}\"[/cyan]")
            else:
                console.print(f"💡 可直接打开: [cyan]xdg-open \"{generated}\"[/cyan]")

    except ValueError as e:
        console.print(f"[yellow]⚠️  {e}[/yellow]")
    except Exception as e:
        console.print(f"[red]❌ 生成失败: {e}[/red]")
        import traceback
        console.print(traceback.format_exc())
        sys.exit(1)


@cli.command("info")
def info_cmd():
    """显示数据信息：数据库路径、配置路径、数据概览"""
    from fin.db import get_transactions

    txs = get_transactions()
    total = len(txs)
    sources = {}
    for t in txs:
        sources[t.source] = sources.get(t.source, 0) + 1

    uncat = len(get_uncategorized_transactions())
    rules = load_category_rules()

    content = "\n".join([
        f"🗄️  数据库路径: [link=file://{DB_PATH}]{DB_PATH}[/link]",
        f"⚙️  配置文件: [link=file://{CATEGORY_RULES_PATH}]{CATEGORY_RULES_PATH}[/link]",
        f"📊 图表目录: [link=file://{CHARTS_DIR}]{CHARTS_DIR}[/link]",
        "",
        f"📋 交易总数: [bold cyan]{total}[/] 笔",
        f"🏦 来源分布: " + ", ".join(f"[blue]{k}[/]: {v}" for k, v in sources.items()),
        f"📂 分类规则: [magenta]{len(rules)}[/] 个分类",
        f"❓ 未分类交易: [yellow]{uncat}[/] 笔",
    ])
    console.print(Panel(content, title="💡 财务工具信息", border_style="cyan", expand=False))


if __name__ == "__main__":
    cli()
