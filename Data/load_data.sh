#!/bin/bash
# Rebuilds va_contracts_raw from the CSV files in this folder
set -e
cd "$(dirname "$0")"
python3 create_table.py
for f in *.csv; do
  echo "Loading $f"
  psql projectx -c "\copy va_contracts_raw FROM '$f' CSV HEADER"
done
psql projectx -c "SELECT action_date_fiscal_year, COUNT(*) FROM va_contracts_raw GROUP BY 1 ORDER BY 1;"
