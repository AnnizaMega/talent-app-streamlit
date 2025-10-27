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
                # ---------------------------
# D) AI-Generated Job Profile (with OpenRouter or fallback)
# ---------------------------
import os, json, requests

st.subheader("D) AI-Generated Job Profile")

def generate_job_profile(role_name, job_level, role_purpose, tgv_summary, api_key=None, model=None):
    """
    Return dict: {requirements, description, competencies}
    If api_key is None, returns a clean fallback (no API call).
    """
    # Fallback (tanpa API)
    if not api_key:
        requirements = [
            "SQL (Window, CTE, analitik), performance basics",
            "Python/R untuk analisis (pandas/tidyverse), statistik dasar",
            "BI (Tableau/Power BI/Looker), data modeling dasar (star schema)",
            "Data storytelling & visual best practices",
            "Analytical thinking, bias awareness, komunikasi EN & ID"
        ]
        description = (
            f"You will turn business questions into data-driven answers for the {role_name} role "
            f"(grade {job_level}). Own the analysis lifecycle end-to-end: scoping, shaping clean datasets, "
            f"building clear dashboards, and crafting narratives that drive decisions."
        )
        competencies = [
            "SQL (Postgres/BigQuery/Snowflake)",
            "Python (pandas/numpy) or R (tidyverse)",
            "Tableau/Power BI/Looker; Excel/Sheets",
            "Git/DBT (nice), Airflow (nice)",
            "Stakeholder management; bias-aware judgement"
        ]
        return {
            "requirements": requirements,
            "description": description,
            "competencies": competencies
        }

    # Kalau ada API key → panggil OpenRouter
    endpoint = "https://openrouter.ai/api/v1/chat/completions"
    model = model or "openrouter/auto"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    sys_prompt = (
        "You are an expert data hiring partner. Create a concise, practical job profile in JSON with keys: "
        "requirements (list), description (string), competencies (list). Keep it business-ready and avoid fluff."
    )
    user_prompt = f"""
Role name: {role_name}
Job level / grade: {job_level}
Role purpose: {role_purpose}

Observed strengths & gaps by TGV (from current benchmark):
{tgv_summary}

Constraints:
- Indonesian/English mix OK, but keep it concise and clear.
- Make requirements concrete and verifiable (e.g., 'Window functions & CTEs', not 'SQL guru').
- 5–8 bullets for requirements and 5–8 for competencies is enough.
Return ONLY valid JSON.
"""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": user_prompt}
        ],
        "temperature": 0.3
    }

    try:
        resp = requests.post(endpoint, headers=headers, data=json.dumps(payload), timeout=60)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        # Coba parse JSON langsung (banyak model mengembalikan JSON murni)
        data = json.loads(content)
        return {
            "requirements": data.get("requirements", []),
            "description": data.get("description", ""),
            "competencies": data.get("competencies", [])
        }
    except Exception as e:
        # fallback supaya app tidak putus
        return {
            "requirements": [
                "Advanced SQL (joins, windows, CTE, agg), query tuning basics",
                "Python/R for analysis & prototyping (pandas / tidyverse)",
                "BI dashboards (Tableau/Power BI/Looker), metrics hygiene",
                "Data modeling fundamentals; version control (Git)",
                "Clear communication & stakeholder management"
            ],
            "description": (
                "Own end-to-end analytics: translate questions into datasets, build clear dashboards, "
                "and communicate insights that influence decisions."
            ),
            "competencies": [
                "SQL (Postgres/BigQuery/Snowflake)",
                "Python (pandas) / R (tidyverse)",
                "Tableau/Power BI/Looker",
                "Git/DBT (nice to have), Airflow (nice to have)"
            ]
        }

# rangkum Strengths & Gaps dari blok sebelumnya (kalau ada ranked_df)
tgv_summary_text = ""
try:
    if 'ranked_df' in locals() and not ranked_df.empty:
        tgv_summary = (
            ranked_df
            .groupby("tgv_name", as_index=False)
            .agg(avg_tgv_match=("tgv_match_rate", "mean"))
            .sort_values("avg_tgv_match", ascending=False)
        )
        # buat ringkasan singkat
        top = tgv_summary.head(1)["tgv_name"].values[0] if len(tgv_summary) else "-"
        bottom = tgv_summary.tail(1)["tgv_name"].values[0] if len(tgv_summary) else "-"
        tgv_summary_text = f"Top strength: {top}. Improvement needed: {bottom}."
except Exception:
    tgv_summary_text = ""

# ambil secret (kalau ada)
openrouter_key = st.secrets.get("OPENROUTER_API_KEY", None)
llm_model = st.secrets.get("LLM_MODEL", "openrouter/auto")

with st.spinner("Generating job profile…"):
    ai = generate_job_profile(
        role_name=role_name if 'role_name' in locals() else "",
        job_level=job_level if 'job_level' in locals() else "",
        role_purpose=role_purpose if 'role_purpose' in locals() else "",
        tgv_summary=tgv_summary_text,
        api_key=openrouter_key,
        model=llm_model
    )

# Tampilkan hasil
st.write("**Job description**")
st.write(ai.get("description", ""))

colA, colB = st.columns(2)
with colA:
    st.write("**Job requirements**")
    for x in ai.get("requirements", []):
        st.markdown(f"- {x}")
with colB:
    st.write("**Key competencies**")
    for x in ai.get("competencies", []):
        st.markdown(f"- {x}")
        except Exception as e:
            st.error(f"Ranking query failed: {e}")



    
