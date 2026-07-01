"""Shared fake-data constants, reused by every seed_*.py so IDs line up across dbs."""
import random
from datetime import date, timedelta

random.seed(42)  # reproducible runs

PRODUCTS  = [f"P{str(i).zfill(4)}" for i in range(1, 201)]      # 200 products
STORES    = [f"S{str(i).zfill(3)}" for i in range(1, 51)]       # 50 stores
SUPPLIERS = [f"SUP{str(i).zfill(2)}" for i in range(1, 21)]     # 20 suppliers

START_DATE = date(2025, 1, 1)
END_DATE   = date(2026, 6, 30)

def random_date(start=START_DATE, end=END_DATE):
    delta = (end - start).days
    return (start + timedelta(days=random.randint(0, delta))).isoformat()

def daterange(start=START_DATE, end=END_DATE):
    days = (end - start).days
    for i in range(days + 1):
        yield start + timedelta(days=i)