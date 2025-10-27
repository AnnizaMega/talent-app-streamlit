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
# ---------------------------
# 3) Create & run a new benchmark
# ---------------------------
import json
from sqlalchemy import text

st.header("3) Create a new Job Benchmark")
# --- 3A) Re-run an existing benchmark (saved) ---
st.header("🔎 Re-run an existing benchmark")

recent_bm = pd.read_sql(
    """
    SELECT job_vacancy_id, role_name, job_level, created_at
    FROM talent_benchmarks
    ORDER BY job_vacancy_id DESC
    LIMIT 25
    """,
    engine,
)
if recent_bm.empty:
    st.info("No saved benchmarks yet. Create one below.")
else:
    st.dataframe(recent_bm, use_container_width=True, height=220)
    pick_id = st.selectbox(
        "Pick a job_vacancy_id to re-run",
        recent_bm["job_vacancy_id"].tolist(),
        index=0,
        key="pick_existing_bm",
    )

    if st.button("Run matching for selected benchmark"):
        try:
            sql_rank_saved = text("""
                SELECT
                  v.employee_id,
                  e.fullname,
                  dir.name  AS directorate,
                  pos.name  AS role,
                  grd.name  AS grade,
                  v.tgv_name,
                  v.tv_name,
                  v.baseline_score,
                  v.user_score,
                  v.tv_match_rate,
                  v.tgv_match_rate,
                  v.final_match_rate
                FROM v_benchmark_matching v
                LEFT JOIN employees         e   ON e.employee_id      = v.employee_id
                LEFT JOIN dim_directorates  dir ON dir.directorate_id = e.directorate_id
                LEFT JOIN dim_positions     pos ON pos.position_id    = e.position_id
                LEFT JOIN dim_grades        grd ON grd.grade_id       = e.grade_id
                WHERE v.job_vacancy_id = :bench_id
                ORDER BY v.final_match_rate DESC, v.employee_id
                LIMIT 500;
            """)
            ranked_df_saved = pd.read_sql(sql_rank_saved, engine, params={"bench_id": pick_id})
            if ranked_df_saved.empty:
                st.warning("No results for this benchmark. Ensure selected IDs have data.")
            else:
                st.session_state["latest_ranked_df"] = ranked_df_saved
                st.session_state["latest_bench_id"] = pick_id
                st.success(f"Loaded benchmark id = {pick_id}")
        except Exception as e:
            st.error(f"Failed to load benchmark {pick_id}: {e}")

# 3.1 ambil daftar karyawan untuk opsi benchmark
employees_df = pd.read_sql(
    "SELECT employee_id, fullname FROM employees ORDER BY fullname",
    engine
)
emp_options = {
    f"{row['fullname']} ({row['employee_id']})": row['employee_id']
    for _, row in employees_df.iterrows()
}

with st.form("benchmark_form", clear_on_submit=False):
    col1, col2 = st.columns(2)
    role_name = col1.text_input("Role name", placeholder="e.g., Brand Executive")
    job_level = col2.text_input("Job level / grade", placeholder="e.g., V")
    role_purpose = st.text_area("Role purpose (1–2 sentences)")

    selected_people = st.multiselect(
        "Select up to 3 benchmark employees",
        options=list(emp_options.keys()),
        max_selections=3
    )
    submitted = st.form_submit_button("Save benchmark & run matching")

if submitted:
    if not role_name or not job_level or not role_purpose or len(selected_people) == 0:
        st.error("Please fill all fields and select at least 1 benchmark employee.")
    else:
        # --- Build list for text[] column (NOT JSON) ---
        selected_ids = [emp_options[k] for k in selected_people]

        # --- Insert benchmark and get new job_vacancy_id ---
        try:
            insert_sql = text("""
                INSERT INTO talent_benchmarks
                  (role_name, job_level, role_purpose, selected_talent_ids, weights_config, created_at)
                VALUES
                  (:role_name, :job_level, :role_purpose, :selected_ids, '{}'::jsonb, now())
                RETURNING job_vacancy_id;
            """)
            with engine.begin() as conn:
                new_id = conn.execute(
                    insert_sql,
                    {
                        "role_name": role_name,
                        "job_level": job_level,
                        "role_purpose": role_purpose,
                        "selected_ids": selected_ids,   # Python list -> Postgres text[]
                    }
                ).scalar()

            st.success(f"Benchmark saved. job_vacancy_id = {new_id}")
        except Exception as e:
            st.error(f"Insert failed: {e}")
            st.stop()

        # --- Run matching for this benchmark ---
        try:
            sql_rank = text("""
SELECT
  v.employee_id,
  e.fullname,
  dir.name  AS directorate,
  pos.name  AS role,
  grd.name  AS grade,
  v.tgv_name,
  v.tv_name,
  v.baseline_score,
  v.user_score,
  v.tv_match_rate,
  v.tgv_match_rate,
  v.final_match_rate
FROM v_benchmark_matching v
LEFT JOIN employees         e   ON e.employee_id     = v.employee_id
LEFT JOIN dim_directorates  dir ON dir.directorate_id = e.directorate_id
LEFT JOIN dim_positions     pos ON pos.position_id    = e.position_id
LEFT JOIN dim_grades        grd ON grd.grade_id       = e.grade_id
WHERE v.job_vacancy_id = :bench_id
ORDER BY v.final_match_rate DESC, v.employee_id
LIMIT 500;
""")
            ranked_df = pd.read_sql(sql_rank, engine, params={"bench_id": new_id})

            st.subheader("A) Ranked Talent List (top 50)")
            top_list = (
                ranked_df
                .groupby(["employee_id", "fullname", "directorate", "role", "grade"], as_index=False)
                .agg(final_match_rate=("final_match_rate", "max"))
                .sort_values("final_match_rate", ascending=False)
            )
            st.dataframe(top_list.head(50), use_container_width=True)
            
# --- Optional: CSV Download ---
if not ranked_df.empty:
    csv_bytes = ranked_df.to_csv(index=False).encode("utf-8")
    file_name = f"benchmark_{st.session_state.get('latest_bench_id', new_id)}.csv"
    st.download_button(
        "⬇️ Download full result (CSV)",
        data=csv_bytes,
        file_name=file_name,
        mime="text/csv"
    )

            st.subheader("B) Match-rate distribution (Top 100)")
            st.bar_chart(top_list.head(100).set_index("employee_id")["final_match_rate"])

            st.subheader("C) Compare a candidate to benchmark (by TV)")
            if not ranked_df.empty:
                pick_emp = st.selectbox(
                    "Pick a candidate to inspect",
                    options=ranked_df["employee_id"].unique().tolist()
                )
                cand = ranked_df[ranked_df["employee_id"] == pick_emp]
                show = cand[["tv_name", "baseline_score", "user_score", "tv_match_rate"]].sort_values("tv_name")
                st.dataframe(show, use_container_width=True)
        except Exception as e:
            st.error(f"Ranking query failed: {e}")

    # --- D) Summary — Strengths & Gaps by TGV -------------------------------
st.subheader("D) Summary — Strengths & Gaps by TGV")

# Only run if ranked_df exists and has rows
if "ranked_df" in locals() and not ranked_df.empty:
    # Build TGV summary table
    tgv_summary = (
        ranked_df.groupby("tgv_name", as_index=False)
        .agg(avg_tgv_match=("tgv_match_rate", "mean"))
        .sort_values("avg_tgv_match", ascending=False)
        .reset_index(drop=True)
    )

    st.dataframe(tgv_summary, use_container_width=True)

    if not tgv_summary.empty:
        best  = tgv_summary.loc[0, "tgv_name"]
        worst = tgv_summary.loc[tgv_summary.index[-1], "tgv_name"]
        st.markdown(
            f"""
            ✅ **Top Strength Area:** {best}  
            ⚠️ **Improvement Needed:** {worst}  
            _(Based on average match rates per TGV across all candidates)_
            """
        )
else:
    st.caption("No ranking data yet — create or re-run a benchmark above.")
