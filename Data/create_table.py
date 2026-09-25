import glob, pandas as pd
from sqlalchemy import create_engine

engine = create_engine("postgresql+psycopg2://jaypanchal@localhost:5432/projectx")
files = sorted(glob.glob("*.csv"))
print("Found:", files)

# Read only the header row and create a table with every column as text
pd.read_csv(files[0], nrows=0).to_sql("va_contracts_raw", engine, if_exists="replace", index=False)
