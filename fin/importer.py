import os
import csv
import io
from datetime import date, datetime
from typing import List, Dict, Tuple, Optional, Callable
import pandas as pd

from fin.models import Transaction, TransactionType
from fin.categorizer import Categorizer
from fin.db import batch_insert_transactions


SOURCE_COLUMN_MAPPINGS: Dict[str, Dict[str, List[str]]] = {
    "招商银行": {
        "date": ["交易日期", "记账日期", "日期"],
        "amount": ["交易金额", "金额"],
        "income": ["收入金额", "收入"],
        "expense": ["支出金额", "支出"],
        "description": ["交易摘要", "摘要", "交易说明", "商品说明"],
        "type": ["交易类型", "收支类型"],
        "balance": ["余额"],
        "raw": [],
    },
    "工商银行": {
        "date": ["交易日期", "日期", "记账日期"],
        "amount": ["交易金额", "金额"],
        "income": ["收入金额", "贷方发生额"],
        "expense": ["支出金额", "借方发生额"],
        "description": ["交易摘要", "摘要", "备注", "对方户名"],
        "type": ["交易类型", "收支标志"],
        "balance": ["余额"],
        "raw": [],
    },
    "建设银行": {
        "date": ["交易日期", "日期"],
        "amount": ["交易金额", "金额"],
        "income": ["收入金额", "贷方发生额"],
        "expense": ["支出金额", "借方发生额"],
        "description": ["摘要", "交易摘要", "用途", "对方账户名"],
        "type": ["交易类型", "借贷标志"],
        "balance": ["账户余额", "余额"],
        "raw": [],
    },
    "支付宝": {
        "date": ["交易创建时间", "付款时间", "交易时间", "日期"],
        "amount": ["金额", "交易金额"],
        "income": ["收入金额", "收/支金额(元)"],
        "expense": ["支出金额"],
        "description": ["商品名称", "商品说明", "交易分类", "摘要"],
        "type": ["收/支", "收支", "资金状态"],
        "balance": ["当前余额"],
        "raw": ["交易对方", "对方", "交易号", "订单号", "交易来源地"],
    },
    "微信": {
        "date": ["交易时间", "日期"],
        "amount": ["金额(元)", "金额", "交易金额"],
        "income": [],
        "expense": [],
        "description": ["商品", "交易描述", "备注", "摘要"],
        "type": ["收/支", "收支类型", "交易类型"],
        "balance": ["当前状态"],
        "raw": ["交易对方", "支付方式", "交易单号", "商户单号"],
    },
    "通用": {
        "date": ["日期", "date", "交易日期", "记账日期"],
        "amount": ["金额", "amount", "交易金额"],
        "income": ["收入", "income", "贷方", "credit"],
        "expense": ["支出", "expense", "借方", "debit"],
        "description": ["描述", "description", "摘要", "备注"],
        "type": ["类型", "type", "收支类型", "交易类型"],
        "balance": ["余额", "balance"],
        "raw": [],
    },
}


def _parse_date(date_str: str) -> Optional[date]:
    if not date_str or pd.isna(date_str) or str(date_str).strip() == "":
        return None
    s = str(date_str).strip().replace("/", "-").replace(".", "-").replace("年", "-").replace("月", "-").replace("日", "")
    s = s.split(" ")[0]
    for fmt in ("%Y-%m-%d", "%Y-%m", "%y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return pd.to_datetime(s, errors="coerce").date()
    except Exception:
        return None


def _parse_amount(amount_str) -> float:
    if amount_str is None or pd.isna(amount_str):
        return 0.0
    s = str(amount_str).strip()
    if s == "" or s == "-" or s == "--":
        return 0.0
    s = s.replace(",", "").replace("¥", "").replace("￥", "").replace("元", "").replace(" ", "")
    s = s.replace("，", "")
    try:
        val = float(s)
        return round(val, 2)
    except ValueError:
        return 0.0


def _detect_encoding(filepath: str) -> str:
    encodings = ["utf-8-sig", "utf-8", "gbk", "gb18030", "utf-16"]
    for enc in encodings:
        try:
            with open(filepath, "r", encoding=enc) as f:
                f.read(4096)
            return enc
        except (UnicodeDecodeError, UnicodeError):
            continue
    return "utf-8"


def _detect_skiprows(filepath: str, encoding: str) -> int:
    try:
        with open(filepath, "r", encoding=encoding, newline="") as f:
            reader = csv.reader(f)
            for i, row in enumerate(reader):
                if i > 20:
                    break
                if not row:
                    continue
                joined = ",".join(str(c).strip() for c in row if c is not None)
                if any(k in joined for k in ["日期", "交易", "金额", "date", "amount", "摘要", "收/支"]):
                    return i
    except Exception:
        pass
    return 0


def _find_column(columns: List[str], candidates: List[str]) -> Optional[str]:
    cols_lower = {str(c).strip(): c for c in columns}
    for cand in candidates:
        if cand in cols_lower:
            return cols_lower[cand]
    for cand in candidates:
        for cl in cols_lower:
            if cand in cl:
                return cols_lower[cl]
    return None


def _auto_detect_source(columns: List[str]) -> str:
    joined = "|".join(str(c) for c in columns)
    if "收/支" in joined and ("商品" in joined or "交易对方" in joined):
        return "微信"
    if ("交易创建时间" in joined or "付款时间" in joined) and "商品名称" in joined:
        return "支付宝"
    if "记账日期" in joined or ("交易日期" in joined and "交易摘要" in joined):
        return "招商银行"
    if "借贷标志" in joined or ("借方发生额" in joined and "贷方发生额" in joined):
        return "建设银行"
    return "通用"


def parse_csv_to_dataframe(filepath: str, source: Optional[str] = None) -> Tuple[pd.DataFrame, str]:
    encoding = _detect_encoding(filepath)
    skiprows = _detect_skiprows(filepath, encoding)
    df = pd.read_csv(filepath, encoding=encoding, skiprows=skiprows, dtype=str, on_bad_lines="skip")
    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(how="all")

    if source is None or source == "自动识别":
        source = _auto_detect_source(list(df.columns))
    return df, source


def dataframe_to_transactions(df: pd.DataFrame, source: str) -> List[Transaction]:
    mapping = SOURCE_COLUMN_MAPPINGS.get(source, SOURCE_COLUMN_MAPPINGS["通用"])
    columns = list(df.columns)

    date_col = _find_column(columns, mapping["date"])
    amount_col = _find_column(columns, mapping["amount"])
    income_col = _find_column(columns, mapping["income"]) if mapping["income"] else None
    expense_col = _find_column(columns, mapping["expense"]) if mapping["expense"] else None
    desc_col = _find_column(columns, mapping["description"])
    type_col = _find_column(columns, mapping["type"]) if mapping["type"] else None

    transactions: List[Transaction] = []
    categorizer = Categorizer()

    for idx, row in df.iterrows():
        trans_date = _parse_date(row[date_col]) if date_col else None
        if trans_date is None:
            continue

        income_val = _parse_amount(row[income_col]) if income_col else 0.0
        expense_val = _parse_amount(row[expense_col]) if expense_col else 0.0
        amount_val = _parse_amount(row[amount_col]) if amount_col else 0.0

        trans_type = TransactionType.UNKNOWN
        final_amount = 0.0

        type_val = str(row[type_col]).strip() if type_col else ""

        if income_val > 0 and expense_val == 0:
            trans_type = TransactionType.INCOME
            final_amount = income_val
        elif expense_val > 0 and income_val == 0:
            trans_type = TransactionType.EXPENSE
            final_amount = expense_val
        elif amount_val != 0:
            if type_val:
                if any(k in type_val for k in ["收入", "收", "credit", "贷", "转入", "退款"]):
                    trans_type = TransactionType.INCOME
                    final_amount = abs(amount_val)
                elif any(k in type_val for k in ["支出", "支", "debit", "借", "消费", "转出"]):
                    trans_type = TransactionType.EXPENSE
                    final_amount = abs(amount_val)
                else:
                    if amount_val > 0:
                        trans_type = TransactionType.EXPENSE
                        final_amount = amount_val
                    else:
                        trans_type = TransactionType.INCOME
                        final_amount = abs(amount_val)
            else:
                if amount_val > 0:
                    trans_type = TransactionType.EXPENSE
                    final_amount = amount_val
                else:
                    trans_type = TransactionType.INCOME
                    final_amount = abs(amount_val)
        else:
            continue

        if final_amount <= 0:
            continue

        description = str(row[desc_col]).strip() if desc_col and pd.notna(row[desc_col]) else ""
        raw_parts = [description]
        for raw_cand in mapping["raw"]:
            rc = _find_column(columns, [raw_cand])
            if rc and pd.notna(row[rc]):
                raw_parts.append(str(row[rc]).strip())
        raw_description = " | ".join([p for p in raw_parts if p])

        tx = Transaction(
            trans_date=trans_date,
            amount=final_amount,
            trans_type=trans_type,
            category="未分类",
            description=description if description else raw_description[:100],
            source=source,
            raw_description=raw_description if raw_description else description,
        )
        tx = categorizer.categorize_transaction(tx)
        transactions.append(tx)

    return transactions


def import_csv_file(filepath: str, source: Optional[str] = None) -> Dict:
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"文件不存在: {filepath}")

    df, detected_source = parse_csv_to_dataframe(filepath, source)
    actual_source = source if source else detected_source
    transactions = dataframe_to_transactions(df, actual_source)
    result = batch_insert_transactions(transactions)

    return {
        "source": actual_source,
        "total_rows": len(df),
        "parsed": len(transactions),
        "inserted": result["inserted"],
        "duplicates": result["duplicates"],
        "filepath": filepath,
    }
