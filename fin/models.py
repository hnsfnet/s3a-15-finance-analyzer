from dataclasses import dataclass, field
from datetime import date
from typing import Optional, List
from enum import Enum


class TransactionType(str, Enum):
    INCOME = "收入"
    EXPENSE = "支出"
    UNKNOWN = "未知"


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
class CategoryStat:
    category: str
    total_amount: float
    count: int
    percentage: float = 0.0


@dataclass
class MonthlyStat:
    month: str
    total_income: float
    total_expense: float
    net_saving: float
    category_stats: List[CategoryStat] = field(default_factory=list)


@dataclass
class CompareResult:
    month_a: str
    month_b: str
    category_diffs: List[dict]
    total_expense_a: float
    total_expense_b: float
    expense_change_pct: float
