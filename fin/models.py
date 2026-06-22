from dataclasses import dataclass, field
from datetime import date
from typing import Optional, List, Dict
from enum import Enum


class TransactionType(str, Enum):
    INCOME = "收入"
    EXPENSE = "支出"
    UNKNOWN = "未知"


class BudgetPeriod(str, Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


@dataclass
class Transaction:
    trans_date: date
    amount: float
    trans_type: TransactionType
    category: str
    description: str
    source: str
    raw_description: str
    id: Optional[int] = None

    @property
    def dedup_key(self) -> str:
        return f"{self.trans_date.isoformat()}|{abs(self.amount):.2f}|{self.trans_type.value}|{self.raw_description.strip()}|{self.source}"


@dataclass
class Category:
    name: str
    keywords: List[str] = field(default_factory=list)


@dataclass
class Budget:
    category: str
    limit: float
    period: BudgetPeriod = BudgetPeriod.MONTHLY
    id: Optional[int] = None

    @property
    def is_total(self) -> bool:
        return self.category == "__total__"


@dataclass
class BudgetProgress:
    category: str
    budget: float
    spent: float
    percentage: float
    remaining: float
    status: str = "normal"


@dataclass
class CategoryStat:
    category: str
    total_amount: float
    count: int
    percentage: float = 0.0
    budget_progress: Optional[BudgetProgress] = None


@dataclass
class MonthlyStat:
    month: str
    total_income: float
    total_expense: float
    net_saving: float
    category_stats: List[CategoryStat] = field(default_factory=list)
    source_stats: "SourceAggregate | None" = None
    total_budget_progress: Optional[BudgetProgress] = None


@dataclass
class CompareResult:
    month_a: str
    month_b: str
    category_diffs: List[dict]
    total_expense_a: float
    total_expense_b: float
    expense_change_pct: float


@dataclass
class RecurringTransaction:
    description: str
    amount: float
    category: str
    occurrences: List[date]
    avg_interval_days: float
    std_interval_days: float
    estimated_period: str
    confidence: float
    next_predicted_date: Optional[date] = None
    transaction_ids: List[int] = field(default_factory=list)


@dataclass
class SourceStat:
    source: str
    total_amount: float
    count: int
    percentage: float = 0.0


@dataclass
class SourceAggregate:
    sources: List[SourceStat] = field(default_factory=list)

    def add(self, source: str, amount: float, count: int = 1):
        for s in self.sources:
            if s.source == source:
                s.total_amount += amount
                s.count += count
                return
        self.sources.append(SourceStat(source=source, total_amount=amount, count=count))

    def finalize(self):
        total = sum(s.total_amount for s in self.sources)
        for s in self.sources:
            s.percentage = round(s.total_amount / total * 100, 2) if total > 0 else 0.0
        self.sources.sort(key=lambda x: x.total_amount, reverse=True)


@dataclass
class YearlyReport:
    year: str
    total_income: float
    total_expense: float
    net_saving: float
    monthly_breakdown: List[MonthlyStat]
    top_expense_categories: List[CategoryStat]
    top_10_transactions: List[Transaction]
    previous_year_comparison: Optional[CompareResult] = None
    total_months: int = 0
    avg_monthly_expense: float = 0.0
    budget_summary: Dict[str, Dict] = field(default_factory=dict)

