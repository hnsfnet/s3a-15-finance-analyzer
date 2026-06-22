import sqlite3
import os
import json
from contextlib import contextmanager
from datetime import date
from typing import List, Optional, Dict, Any, Tuple
from pathlib import Path

from fin.models import (
    Transaction,
    TransactionType,
    Category,
    CategoryStat,
    MonthlyStat,
    CompareResult,
    Budget,
    BudgetPeriod,
)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "finance.db")
CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config")
CATEGORY_RULES_PATH = os.path.join(CONFIG_DIR, "category_rules.json")

DEFAULT_CATEGORY_RULES = {
    "餐饮": ["美团", "饿了么", "外卖", "麦当劳", "肯德基", "星巴克", "海底捞", "餐厅", "饭店", "火锅", "烧烤", "奶茶", "咖啡", "食堂", "餐饮"],
    "交通": ["滴滴", "地铁", "公交", "加油", "中石化", "中石油", "停车", "高速", "过路费", "火车票", "机票", "航空", "高铁", "打车", "出租", "ETC"],
    "购物": ["淘宝", "天猫", "京东", "拼多多", "唯品会", "苏宁", "超市", "便利店", "沃尔玛", "家乐福", "永辉", "盒马", "购物", "百货"],
    "娱乐": ["电影", "游戏", "KTV", "健身", "旅游", "景点", "门票", "演出", "音乐", "视频", "会员", "爱奇艺", "腾讯视频", "优酷", "哔哩哔哩", "B站", "Steam", "PlayStation"],
    "居家": ["房租", "水电", "燃气", "物业", "快递", "搬家", "装修", "家具", "家电", "宜家", "淘宝-家居", "京东-家电"],
    "通讯": ["话费", "流量", "宽带", "中国移动", "中国联通", "中国电信", "网费"],
    "医疗": ["医院", "药店", "门诊", "挂号", "体检", "药", "医疗", "健康"],
    "教育": ["学费", "培训", "课程", "书籍", "图书", "当当", "亚马逊", "Kindle", "教育", "学习"],
    "理财": ["基金", "股票", "理财", "余额宝", "零钱通", "利息", "分红", "转入", "转出", "还款", "信用卡"],
    "工资": ["工资", "薪资", "奖金", "年终奖", "绩效", "补贴", "津贴"],
    "红包": ["红包", "转账-红包", "压岁钱"],
    "转账": ["转账", "提现", "充值", "汇款"],
}


@contextmanager
def get_connection():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trans_date DATE NOT NULL,
                amount REAL NOT NULL,
                trans_type TEXT NOT NULL,
                category TEXT NOT NULL,
                description TEXT NOT NULL,
                source TEXT NOT NULL,
                raw_description TEXT NOT NULL,
                dedup_key TEXT NOT NULL UNIQUE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                keywords TEXT NOT NULL DEFAULT '[]'
            )
        """)
        cur.execute("""
            CREATE TABLE IF NOT EXISTS budgets (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL,
                limit_amount REAL NOT NULL,
                period TEXT NOT NULL DEFAULT 'monthly',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(category, period)
            )
        """)
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trans_date ON transactions(trans_date)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trans_category ON transactions(category)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trans_type ON transactions(trans_type)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_trans_source ON transactions(source)")


def init_category_rules() -> None:
    Path(CONFIG_DIR).mkdir(parents=True, exist_ok=True)
    if not os.path.exists(CATEGORY_RULES_PATH):
        with open(CATEGORY_RULES_PATH, "w", encoding="utf-8") as f:
            json.dump(DEFAULT_CATEGORY_RULES, f, ensure_ascii=False, indent=2)


def load_category_rules() -> Dict[str, List[str]]:
    if not os.path.exists(CATEGORY_RULES_PATH):
        init_category_rules()
    with open(CATEGORY_RULES_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def save_category_rules(rules: Dict[str, List[str]]) -> None:
    Path(CONFIG_DIR).mkdir(parents=True, exist_ok=True)
    with open(CATEGORY_RULES_PATH, "w", encoding="utf-8") as f:
        json.dump(rules, f, ensure_ascii=False, indent=2)


def transaction_exists(dedup_key: str) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM transactions WHERE dedup_key = ?", (dedup_key,))
        return cur.fetchone() is not None


def insert_transaction(t: Transaction) -> Tuple[bool, Optional[int]]:
    if transaction_exists(t.dedup_key):
        return False, None
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO transactions (trans_date, amount, trans_type, category, description, source, raw_description, dedup_key)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            t.trans_date.isoformat(),
            t.amount,
            t.trans_type.value,
            t.category,
            t.description,
            t.source,
            t.raw_description,
            t.dedup_key,
        ))
        return True, cur.lastrowid


def batch_insert_transactions(transactions: List[Transaction]) -> Dict[str, int]:
    inserted = 0
    duplicates = 0
    with get_connection() as conn:
        cur = conn.cursor()
        for t in transactions:
            if transaction_exists(t.dedup_key):
                duplicates += 1
                continue
            cur.execute("""
                INSERT INTO transactions (trans_date, amount, trans_type, category, description, source, raw_description, dedup_key)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                t.trans_date.isoformat(),
                t.amount,
                t.trans_type.value,
                t.category,
                t.description,
                t.source,
                t.raw_description,
                t.dedup_key,
            ))
            inserted += 1
    return {"inserted": inserted, "duplicates": duplicates}


def get_transactions(start_date: Optional[date] = None, end_date: Optional[date] = None,
                     category: Optional[str] = None, trans_type: Optional[TransactionType] = None,
                     source: Optional[str] = None) -> List[Transaction]:
    sql = "SELECT * FROM transactions WHERE 1=1"
    params: List[Any] = []
    if start_date:
        sql += " AND trans_date >= ?"
        params.append(start_date.isoformat())
    if end_date:
        sql += " AND trans_date <= ?"
        params.append(end_date.isoformat())
    if category:
        sql += " AND category = ?"
        params.append(category)
    if trans_type:
        sql += " AND trans_type = ?"
        params.append(trans_type.value)
    if source:
        sql += " AND source = ?"
        params.append(source)
    sql += " ORDER BY trans_date DESC"
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
    result = []
    for r in rows:
        result.append(Transaction(
            id=r["id"],
            trans_date=date.fromisoformat(r["trans_date"]),
            amount=r["amount"],
            trans_type=TransactionType(r["trans_type"]),
            category=r["category"],
            description=r["description"],
            source=r["source"],
            raw_description=r["raw_description"],
        ))
    return result


def get_transactions_by_month(month_str: str, source: Optional[str] = None) -> List[Transaction]:
    parts = month_str.split("-")
    year = int(parts[0])
    month = int(parts[1])
    if month == 12:
        next_month_start = date(year + 1, 1, 1)
    else:
        next_month_start = date(year, month + 1, 1)
    sql = "SELECT * FROM transactions WHERE trans_date >= ? AND trans_date < ?"
    params: List[Any] = [f"{month_str}-01", next_month_start.isoformat()]
    if source:
        sql += " AND source = ?"
        params.append(source)
    sql += " ORDER BY trans_date"
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
    result = []
    for r in rows:
        result.append(Transaction(
            id=r["id"],
            trans_date=date.fromisoformat(r["trans_date"]),
            amount=r["amount"],
            trans_type=TransactionType(r["trans_type"]),
            category=r["category"],
            description=r["description"],
            source=r["source"],
            raw_description=r["raw_description"],
        ))
    return result


def get_transactions_by_year(year: str, source: Optional[str] = None) -> List[Transaction]:
    sql = "SELECT * FROM transactions WHERE trans_date >= ? AND trans_date < ?"
    params: List[Any] = [f"{year}-01-01", f"{int(year) + 1}-01-01"]
    if source:
        sql += " AND source = ?"
        params.append(source)
    sql += " ORDER BY trans_date"
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
    result = []
    for r in rows:
        result.append(Transaction(
            id=r["id"],
            trans_date=date.fromisoformat(r["trans_date"]),
            amount=r["amount"],
            trans_type=TransactionType(r["trans_type"]),
            category=r["category"],
            description=r["description"],
            source=r["source"],
            raw_description=r["raw_description"],
        ))
    return result


def get_uncategorized_transactions() -> List[Transaction]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM transactions WHERE category = '未分类' ORDER BY trans_date DESC")
        rows = cur.fetchall()
    result = []
    for r in rows:
        result.append(Transaction(
            id=r["id"],
            trans_date=date.fromisoformat(r["trans_date"]),
            amount=r["amount"],
            trans_type=TransactionType(r["trans_type"]),
            category=r["category"],
            description=r["description"],
            source=r["source"],
            raw_description=r["raw_description"],
        ))
    return result


def update_transaction_category(tid: int, category: str) -> None:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE transactions SET category = ? WHERE id = ?", (category, tid))


def get_all_categories() -> List[str]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT category FROM transactions ORDER BY category")
        rows = cur.fetchall()
    return [r["category"] for r in rows]


def get_all_sources() -> List[str]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT source FROM transactions ORDER BY source")
        rows = cur.fetchall()
    return [r["source"] for r in rows]


def set_budget(category: str, limit: float, period: BudgetPeriod = BudgetPeriod.MONTHLY) -> Budget:
    period_val = period.value if isinstance(period, BudgetPeriod) else period
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO budgets (category, limit_amount, period)
            VALUES (?, ?, ?)
            ON CONFLICT(category, period) DO UPDATE SET limit_amount = excluded.limit_amount
        """, (category, limit, period_val))
        cur.execute("SELECT * FROM budgets WHERE category = ? AND period = ?", (category, period_val))
        row = cur.fetchone()
    return Budget(
        id=row["id"],
        category=row["category"],
        limit=row["limit_amount"],
        period=BudgetPeriod(row["period"]),
    )


def get_budgets(period: Optional[BudgetPeriod] = None) -> List[Budget]:
    sql = "SELECT * FROM budgets WHERE 1=1"
    params: List[Any] = []
    if period:
        sql += " AND period = ?"
        params.append(period.value)
    sql += " ORDER BY category"
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute(sql, params)
        rows = cur.fetchall()
    result = []
    for r in rows:
        result.append(Budget(
            id=r["id"],
            category=r["category"],
            limit=r["limit_amount"],
            period=BudgetPeriod(r["period"]),
        ))
    return result


def get_budget_by_category(category: str, period: BudgetPeriod = BudgetPeriod.MONTHLY) -> Optional[Budget]:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM budgets WHERE category = ? AND period = ?", (category, period.value))
        row = cur.fetchone()
    if not row:
        return None
    return Budget(
        id=row["id"],
        category=row["category"],
        limit=row["limit_amount"],
        period=BudgetPeriod(row["period"]),
    )


def delete_budget(category: str, period: BudgetPeriod = BudgetPeriod.MONTHLY) -> bool:
    with get_connection() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM budgets WHERE category = ? AND period = ?", (category, period.value))
        return cur.rowcount > 0
