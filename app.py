import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text

st.set_page_config(page_title="Talent Benchmark Matching", layout="wide")
st.title("Talent App • Connectivity Check")

# --- Credentials from Streamlit Cloud secrets ---
try:
    host = st.secrets["DB_HOST"]
    name = st.secrets["DB_NAME"]
    user = st.secrets["DB_USER"]
    pwd  = st.secrets["DB_PASSWORD"]
    port = st.secrets.get("DB_PORT", "5432")
    ssl_mode = "require"
except Exception:
    st.error("Secrets not found. Please set DB_* in Streamlit Cloud.")
    st.stop()

engine_url = f"postgresql+psycopg2://{user}:{pwd}@{host}:{port}/{name}?sslmode={ssl_mode}"

@st.cache_resource
def get_engine():
    return create_engine(engine_url)

engine = get_engine()

st.subheader("1) Quick ping to database")
try:
    with engine.connect() as con:
        version = con.execute(text("select version()")).scalar()
    st.success("Connected ✔")
    st.code(version)
except Exception as e:
    st.error(f"DB connection failed: {e}")
    st.stop()

st.subheader("2) Sample data preview")
option = st.selectbox(
    "Choose source to peek",
    ["v_benchmark_matching (if created)", "employees"]
)
sql = "SELECT * FROM employees LIMIT 10" if "employees" in option else "SELECT * FROM v_benchmark_matching LIMIT 10"

try:
    with engine.connect() as con:
        df = pd.read_sql(text(sql), con)
    st.dataframe(df, use_container_width=True)
except Exception as e:
    st.warning(f"Query failed (this is OK if the view doesn't exist yet): {e}")
