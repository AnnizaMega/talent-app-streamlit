import json
import requests
import pandas as pd
import streamlit as st
import os
os.environ["STREAMLIT_WATCH_FILE_SYSTEM"] = "false"
from sqlalchemy import create_engine, text

# -----------------------------
# App & DB setup
# -----------------------------
st.set_page_config(page_title="Talent Benchmark Matching", layout="wide")
st.title("Talent App • Connectivity Check")

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
# --- Persisted state so Section C survives reruns ---
if "latest_ranked_df" not in st.session_state:
    st.session_state["latest_ranked_df"] = pd.DataFrame()
if "latest_bench_id" not in st.session_state:
    st.session_state["latest_bench_id"] = None
# -----------------------------
# 1) Connectivity check
# -----------------------------
st.subheader("1) Quick ping to database")
try:
    with engine.connect() as con:
        version = con.execute(text("select version()")).scalar()
    st.success("Connected ✔")
    st.code(version)
except Exception as e:
    st.error(f"DB connection failed: {e}")
    st.stop()

# -----------------------------
# 2) Sample data peek (isolated)
# -----------------------------
st.subheader("2) Sample data preview")
peek_option = st.selectbox(
    "Choose source to peek",
    ["v_benchmark_matching (if created)", "employees"],
    key="peek_source"
)
peek_sql = "SELECT * FROM employees LIMIT 10" if "employees" in peek_option else "SELECT * FROM v_benchmark_matching LIMIT 10"
try:
    with engine.connect() as con:
        df_peek = pd.read_sql(text(peek_sql), con)
    st.dataframe(df_peek, use_container_width=True)
except Exception as e:
    st.warning(f"Query failed (this is OK if the view doesn't exist yet): {e}")

# =====================================================================
# Helper: run matching for a benchmark id and persist to session_state
# =====================================================================
def run_matching(bench_id: int):
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
        LEFT JOIN employees         e   ON e.employee_id      = v.employee_id
        LEFT JOIN dim_directorates  dir ON dir.directorate_id = e.directorate_id
        LEFT JOIN dim_positions     pos ON pos.position_id    = e.position_id
        LEFT JOIN dim_grades        grd ON grd.grade_id       = e.grade_id
        WHERE v.job_vacancy_id = :bench_id
        ORDER BY v.final_match_rate DESC, v.employee_id
        LIMIT 500;
    """)
    ranked_df = pd.read_sql(sql_rank, engine, params={"bench_id": bench_id})
    st.session_state["latest_ranked_df"] = ranked_df
    st.session_state["latest_bench_id"] = bench_id
    return ranked_df

# =====================================================================
# 3) Create & run / Re-run benchmark
# =====================================================================
st.header("3) Create a new Job Benchmark")

# --- 3A) Re-run an existing benchmark ---
st.subheader("🔎 Re-run an existing benchmark")
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
    if st.button("Run matching for selected benchmark", key="run_existing"):
        try:
            ranked_df_saved = run_matching(pick_id)
            if ranked_df_saved.empty:
                st.warning("No results for this benchmark. Ensure selected IDs have data.")
            else:
                st.success(f"Loaded benchmark id = {pick_id}")
        except Exception as e:
            st.error(f"Failed to load benchmark {pick_id}: {e}")

# --- 3B) Create a new benchmark ---
# Get employees for selection
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
        max_selections=3,
        key="select_bench_emps",
    )
    submitted = st.form_submit_button("Save benchmark & run matching")

if submitted:
    if not role_name or not job_level or not role_purpose or len(selected_people) == 0:
        st.error("Please fill all fields and select at least 1 benchmark employee.")
    else:
        try:
            selected_ids = [emp_options[k] for k in selected_people]
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
                        "selected_ids": selected_ids,
                    }
                ).scalar()
            st.success(f"Benchmark saved. job_vacancy_id = {new_id}")

            # run & persist
            ranked_df = run_matching(new_id)

            # Section A – ranked list
            st.subheader("A) Ranked Talent List (top 50)")
            top_list = (
                ranked_df
                .groupby(["employee_id", "fullname", "directorate", "role", "grade"], as_index=False)
                .agg(final_match_rate=("final_match_rate", "max"))
                .sort_values("final_match_rate", ascending=False)
            )
            st.dataframe(top_list.head(50), use_container_width=True)

            # Optional CSV download
            if not ranked_df.empty:
                csv_bytes = ranked_df.to_csv(index=False).encode("utf-8")
                file_name = f"benchmark_{st.session_state.get('latest_bench_id', new_id)}.csv"
                st.download_button(
                    "⬇️ Download full result (CSV)",
                    data=csv_bytes,
                    file_name=file_name,
                    mime="text/csv",
                    key="dl_csv_new",
                )

            # Section B – distribution
            st.subheader("B) Match-rate distribution (Top 100)")
            st.bar_chart(top_list.head(100).set_index("employee_id")["final_match_rate"])

        except Exception as e:
            st.error(f"Ranking query failed: {e}")
            # =====================================================================
# =====================================================================
# 3C–5) Dashboard Overview (Enhanced Layout + Insights)
# =====================================================================

st.divider()
st.header("📊 Talent Benchmark Dashboard")

ranked_df = st.session_state.get("latest_ranked_df", pd.DataFrame())
latest_bench_id = st.session_state.get("latest_bench_id")

if ranked_df.empty:
    st.info("No benchmark results loaded yet. Create or re-run a benchmark above.")
else:
    # ===============================================================
    # A & B — Overview Section (Top 10 + Distribution)
    # ===============================================================
    st.subheader("A) Top 10 Ranked Candidates")
    top_list = (
        ranked_df
        .groupby(["employee_id", "fullname", "directorate", "role", "grade"], as_index=False)
        .agg(final_match_rate=("final_match_rate", "max"))
        .sort_values("final_match_rate", ascending=False)
    )

    colA, colB = st.columns([1.3, 1])

    with colA:
        st.dataframe(top_list.head(10), use_container_width=True, height=350)

        csv_bytes = ranked_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Download full result (CSV)",
            data=csv_bytes,
            file_name=f"benchmark_{latest_bench_id}.csv",
            mime="text/csv",
            key="dl_csv_persist",
        )

    with colB:
        st.subheader("B) Match-rate Distribution (Top 100)")
        st.bar_chart(
            top_list.head(100).set_index("employee_id")["final_match_rate"],
            use_container_width=True,
            height=300,
        )

    st.divider()

    # ===============================================================
    # C — Candidate Detail + Radar Chart
    # ===============================================================
    st.subheader("C) Candidate Detail & TGV Radar")
    colC, colD = st.columns([1, 1.3])

    with colC:
        emp_list = ranked_df["employee_id"].unique().tolist()
        default_emp = st.session_state.get("pick_emp", emp_list[0] if emp_list else None)

        with st.form("compare_candidate_form", clear_on_submit=False):
            pick_emp = st.selectbox(
                "Select candidate to inspect",
                options=emp_list,
                index=emp_list.index(default_emp) if default_emp in emp_list else 0,
                key="pick_emp_form",
            )
            view_btn = st.form_submit_button("🔍 View Candidate")

        if view_btn or st.session_state.get("pick_emp"):
            st.session_state["pick_emp"] = pick_emp if view_btn else st.session_state["pick_emp"]
            chosen_emp = st.session_state["pick_emp"]

            cand = ranked_df[ranked_df["employee_id"] == chosen_emp]
            if not cand.empty:
                # ============= Dynamic color-scale =============
                def color_scale(value):
                    if value >= 90:
                        return "background-color: #28a745; color:white"
                    elif value >= 70:
                        return "background-color: #ffc107"
                    else:
                        return "background-color: #dc3545; color:white"

                styled = cand[["tv_name", "baseline_score", "user_score", "tv_match_rate"]] \
                    .sort_values("tv_name") \
                    .style.applymap(color_scale, subset=["tv_match_rate"])

                st.dataframe(styled, use_container_width=True, height=350)

                cand_csv = cand.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "⬇️ Download candidate TVs (CSV)",
                    data=cand_csv,
                    file_name=f"candidate_{chosen_emp}_tvs.csv",
                    mime="text/csv",
                    key="dl_csv_cand",
                )
            else:
                st.warning("No data found for this candidate.")

    with colD:
        # ================= Radar Chart =================
        import plotly.graph_objects as go

        chosen_emp = st.session_state.get("pick_emp")
        if chosen_emp:
            try:
                cand_tgv = (
                    ranked_df[ranked_df["employee_id"] == chosen_emp]
                    .groupby("tgv_name", as_index=False)
                    .agg(tgv_match_rate=("tgv_match_rate", "mean"))
                    .sort_values("tgv_name")
                )

                if not cand_tgv.empty:
                    cand_tgv["benchmark_rate"] = 100

                    fig = go.Figure()
                    fig.add_trace(
                        go.Scatterpolar(
                            r=cand_tgv["tgv_match_rate"],
                            theta=cand_tgv["tgv_name"],
                            fill="toself",
                            name="Candidate Match Rate",
                            line_color="mediumseagreen",
                            hovertemplate="<b>%{theta}</b><br>Match Rate: %{r:.1f}%<extra></extra>"
                        )
                    )
                    fig.add_trace(
                        go.Scatterpolar(
                            r=cand_tgv["benchmark_rate"],
                            theta=cand_tgv["tgv_name"],
                            fill="toself",
                            name="Benchmark (100%)",
                            line_color="royalblue",
                            line=dict(dash="dot"),
                        )
                    )

                    fig.update_layout(
                        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
                        showlegend=True,
                        height=400,
                        margin=dict(l=30, r=30, t=40, b=30),
                    )
                    st.plotly_chart(fig, use_container_width=True)

                    # ============ Insight Summary ============
                    avg_tgv = cand_tgv.set_index("tgv_name")["tgv_match_rate"]
                    best_tgv = avg_tgv.idxmax()
                    worst_tgv = avg_tgv.idxmin()
                    strong = avg_tgv[avg_tgv >= 85].index.tolist()
                    weak = avg_tgv[avg_tgv <= 70].index.tolist()

                    st.markdown(f"""
                    **🧠 Insight Summary**
                    - 🟢 Strength: **{best_tgv}**
                    - 🔴 Area to Improve: **{worst_tgv}**
                    - 💬 Strong in: {', '.join(strong) if strong else '—'}
                    - ⚠️ Needs improvement in: {', '.join(weak) if weak else '—'}
                    """)
                else:
                    st.info("No TGV data available for this candidate.")
            except Exception as e_plot:
                st.warning(f"Radar chart skipped due to: {e_plot}")
        else:
            st.info("Select a candidate to view radar analysis.")

    # ===============================================================
    # D — AI Generated Job Profile (Full Width)
    # ===============================================================
    st.divider()
    st.subheader("D) AI-Generated Job Profile")

    try:
        tgv_summary = (
            ranked_df.groupby("tgv_name", as_index=False)
            .agg(avg_tgv_match=("tgv_match_rate", "mean"))
            .sort_values("avg_tgv_match", ascending=False)
        )

        if tgv_summary.empty:
            st.info("No TGV summary available for this benchmark yet.")
        else:
            best = tgv_summary.iloc[0]["tgv_name"]
            worst = tgv_summary.iloc[-1]["tgv_name"]

            st.markdown(
                f"""
**Top Strength Area:** `{best}`  
**Improvement Needed:** `{worst}`  
_Based on average match rates per TGV across all candidates._
                """
            )

api_key = st.secrets.get("OPENROUTER_API_KEY", "")
model = st.secrets.get("LLM_MODEL", "gpt-4o-mini")  # gunakan model yang pasti valid

if api_key and pick_emp:
    cand_rows = ranked_df[ranked_df["employee_id"] == pick_emp]
    if not cand_rows.empty:
        top_tvs = (
            cand_rows.sort_values("tv_match_rate", ascending=False)
            .head(5)[["tv_name", "tv_match_rate"]]
            .to_dict("records")
        )
        low_tvs = (
            cand_rows.sort_values("tv_match_rate", ascending=True)
            .head(5)[["tv_name", "tv_match_rate"]]
            .to_dict("records")
        )

        prompt = {
            "job_vacancy_id": latest_bench_id,
            "tgv_best": best,
            "tgv_gap": worst,
            "candidate_id": pick_emp,
            "candidate_top_tvs": top_tvs,
            "candidate_low_tvs": low_tvs,
        }

        messages = [
            {
                "role": "system",
                "content": (
                    "You are an experienced HR analytics assistant who writes structured, "
                    "business-focused summaries for talent benchmarking."
                ),
            },
            {
                "role": "user",
                "content": (
                    "Generate a professional job profile using this JSON data. Include:\n"
                    "1. Job purpose (1–2 sentences)\n"
                    "2. Key competencies / strengths\n"
                    "3. Must-have TVs\n"
                    "4. Development areas\n"
                    "5. Red flags\n"
                    "6. Suggested development actions\n\n"
                    f"Data:\n{json.dumps(prompt, ensure_ascii=False)}"
                ),
            },
        ]

        with st.spinner("Generating AI job profile…"):
            resp = requests.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "HTTP-Referer": "https://your-app-name.streamlit.app",
                    "X-Title": "Talent Benchmark App",
                    "Content-Type": "application/json",
                },
                json={  # <-- GANTI dari data= ke json= agar format dikirim valid
                    "model": model,
                    "messages": messages,
                    "temperature": 0.3,
                },
                timeout=60,
            )

        if resp.ok:
            st.markdown(resp.json()["choices"][0]["message"]["content"])
        else:
            st.warning(
                f"AI call failed ({resp.status_code}): {resp.text[:200]}... Showing fallback summary above."
            )
            elif not api_key:
                st.info("Tip: set `OPENROUTER_API_KEY` in Streamlit Secrets to enable AI generation.")
    except Exception as e_d:
        st.warning(f"AI Profile section skipped due to: {e_d}")


