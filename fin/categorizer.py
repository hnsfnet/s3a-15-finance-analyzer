import re
from typing import List, Dict, Optional

from fin.models import Transaction
from fin.db import (
    load_category_rules,
    save_category_rules,
    update_transaction_category,
    get_uncategorized_transactions,
)


class Categorizer:
    def __init__(self):
        self.rules: Dict[str, List[str]] = load_category_rules()

    def reload_rules(self) -> None:
        self.rules = load_category_rules()

    def categorize_text(self, text: str) -> str:
        if not text:
            return "未分类"
        text_lower = text.lower()
        for category, keywords in self.rules.items():
            for kw in keywords:
                if kw.lower() in text_lower:
                    return category
        return "未分类"

    def categorize_transaction(self, t: Transaction) -> Transaction:
        t.category = self.categorize_text(t.raw_description)
        if t.category == "未分类":
            t.category = self.categorize_text(t.description)
        return t

    def categorize_transactions(self, transactions: List[Transaction]) -> List[Transaction]:
        return [self.categorize_transaction(t) for t in transactions]

    def add_rule(self, category: str, keyword: str) -> None:
        if category not in self.rules:
            self.rules[category] = []
        if keyword not in self.rules[category]:
            self.rules[category].append(keyword)
            save_category_rules(self.rules)

    def remove_rule(self, category: str, keyword: str) -> bool:
        if category in self.rules and keyword in self.rules[category]:
            self.rules[category].remove(keyword)
            save_category_rules(self.rules)
            return True
        return False

    def add_category(self, category: str) -> None:
        if category not in self.rules:
            self.rules[category] = []
            save_category_rules(self.rules)

    def remove_category(self, category: str) -> bool:
        if category in self.rules:
            del self.rules[category]
            save_category_rules(self.rules)
            return True
        return False

    def list_rules(self) -> Dict[str, List[str]]:
        return dict(self.rules)


def recategorize_all() -> Dict[str, int]:
    from fin.db import get_transactions
    from fin.models import TransactionType
    categorizer = Categorizer()
    all_txs = get_transactions()
    updated = 0
    total = len(all_txs)
    for tx in all_txs:
        new_cat = categorizer.categorize_text(tx.raw_description)
        if new_cat == "未分类":
            new_cat = categorizer.categorize_text(tx.description)
        if new_cat != tx.category:
            update_transaction_category(tx.id, new_cat)
            updated += 1
    return {"total": total, "updated": updated}


def manual_categorize_batch(tx_ids: List[int], category: str) -> int:
    count = 0
    for tid in tx_ids:
        update_transaction_category(tid, category)
        count += 1
    return count
