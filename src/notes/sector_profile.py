from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .sectionizer import fold_text


@dataclass(frozen=True)
class TopicRule:
    topic: str
    aliases: tuple[str, ...]
    possible_targets: tuple[str, ...] = ()


ENTERPRISE_RULES = (
    TopicRule("cash", ("tien va cac khoan tuong duong tien", "tien va tuong duong tien"), ("ASSET.CASH_EQUIV",)),
    TopicRule("receivables", ("cac khoan phai thu", "phai thu khach hang"), ("ASSET.RECEIVABLES",)),
    TopicRule("inventory", ("hang ton kho",), ("ASSET.INVENTORY",)),
    TopicRule("fixed_assets", ("tai san co dinh huu hinh", "tai san co dinh"), ("ASSET.FIXED_ASSETS",)),
    TopicRule("investment_property", ("bat dong san dau tu",), ("ASSET.INVESTMENT_PROPERTY",)),
    TopicRule("borrowings", ("vay", "vay va no thue tai chinh"), ("LIABILITY.BORROWINGS",)),
    TopicRule("equity", ("von chu so huu",), ("EQUITY",)),
    TopicRule("revenue", ("doanh thu",), ("INCOME.ENTERPRISE.REVENUE_GROSS", "INCOME.ENTERPRISE.REVENUE_NET")),
    TopicRule("cost_of_sales", ("gia von",), ("INCOME.ENTERPRISE.COGS",)),
    TopicRule("tax", ("thue thu nhap doanh nghiep",), ("INCOME.ENTERPRISE.CURRENT_TAX_EXPENSE", "INCOME.ENTERPRISE.DEFERRED_TAX_EXPENSE")),
)

BANK_RULES = (
    TopicRule("cash", ("tien va cac khoan tuong duong tien", "tien mat"), ("ASSET.CASH_EQUIV",)),
    TopicRule("central_bank", ("tien gui tai ngan hang nha nuoc",), ("ASSET.CENTRAL_BANK_BALANCES",)),
    TopicRule("interbank", ("tien gui tai va cho vay cac tctd", "to chuc tin dung khac"), ("ASSET.INTERBANK",)),
    TopicRule("customer_loans", ("cho vay khach hang", "phan loai no"), ("ASSET.CUSTOMER_LOANS",)),
    TopicRule("customer_deposits", ("tien gui cua khach hang",), ("LIABILITY.CUSTOMER_DEPOSITS",)),
    TopicRule("credit_risk", ("du phong rui ro tin dung", "chat luong tin dung", "no xau"), ()),
    TopicRule("off_balance", ("bao lanh", "cam ket", "ngoai bang"), ("OFF_BALANCE",)),
    TopicRule("interest_income", ("thu nhap lai",), ("INCOME.BANK.INTEREST_INCOME",)),
)


def rules_for_sector(sector: str):
    if sector == "bank":
        return BANK_RULES
    return ENTERPRISE_RULES


def classify_topic(title: str, sector: str) -> str | None:
    f = fold_text(title)
    best = None
    best_len = 0
    for rule in rules_for_sector(sector):
        for alias in rule.aliases:
            if alias in f and len(alias) > best_len:
                best = rule.topic
                best_len = len(alias)
    return best


def possible_targets(title: str, sector: str) -> tuple[str, ...]:
    topic = classify_topic(title, sector)
    for rule in rules_for_sector(sector):
        if rule.topic == topic:
            return rule.possible_targets
    return ()
