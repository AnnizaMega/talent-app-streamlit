# Talent Match Intelligence (Streamlit + Postgres + OpenRouter)

An interactive app for **benchmark-based talent matching**.
It lets HR select benchmark employees, computes **TV → TGV → Final match** scores in SQL, and generates **AI job profiles** using GPT-4o-mini via OpenRouter.

## Features

* Create & re-run **job benchmarks** (role, level, purpose, selected employees)
* Ranked candidate list + **match-rate distribution**
* Candidate inspector with **TV table** and **TGV radar**
* **AI-Generated Job Profile** (English, HR-style: requirements, description, competencies, insights)
* CSV exports for full results and per-candidate TVs

---

## Architecture

* **Frontend**: Streamlit
* **DB**: PostgreSQL (e.g., Supabase)
* **AI**: OpenRouter → `openai/gpt-4o-mini`
* **SQL Views/Functions**: `v_benchmark_matching`, optional RPC for convenience

---

## Prerequisites

* Python 3.10+
* PostgreSQL (or Supabase)
* OpenRouter account + API key
* (Optional) Streamlit Cloud account for deployment

---

## Quickstart (Local)

```bash
# 1) Clone
git clone https://github.com/AnnizaMega/talent-app-streamlit.git
cd talent-app-streamlit

# 2) Create venv
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# 3) Install deps
pip install -r requirements.txt

# 4) Create Streamlit secrets (local)
mkdir -p .streamlit
```

Create `.streamlit/secrets.toml`:

```toml
# --- Database (Postgres/Supabase) ---
DB_HOST = "YOUR_DB_HOST"
DB_PORT = "5432"
DB_NAME = "YOUR_DB_NAME"
DB_USER = "YOUR_DB_USER"
DB_PASSWORD = "YOUR_DB_PASSWORD"

# --- OpenRouter ---
OPENROUTER_API_KEY = "YOUR_OPENROUTER_KEY"
LLM_MODEL = "gpt-4o-mini"  # used as fallback name; code requests "openai/gpt-4o-mini"

# --- Optional: Streamlit --
# Prevent watchdog CPU spikes on Streamlit Cloud
# (the app also sets this via os.environ at runtime)
```

Run:

```bash
streamlit run app.py
```

Open the URL shown in your terminal.

---

## Database Objects You Need

> Names may vary with your schema; below is the **minimum** your app expects.

### Required Tables (simplified)

* `employees(employee_id, fullname, directorate_id, position_id, grade_id, ...)`
* `dim_directorates(directorate_id, name)`
* `dim_positions(position_id, name)`
* `dim_grades(grade_id, name)`
* `talent_benchmarks(job_vacancy_id, role_name, job_level, role_purpose, selected_talent_ids jsonb, weights_config jsonb, created_at timestamptz)`

### Required View

`v_benchmark_matching` should return **one row per employee × TV** with precomputed matches:

```sql
-- minimal column contract
-- employee-level metadata can be joined in the app
SELECT
  job_vacancy_id,
  employee_id,
  tgv_name,
  tv_name,
  baseline_score::numeric,
  user_score::numeric,
  tv_match_rate::numeric,
  tgv_match_rate::numeric,
  final_match_rate::numeric
FROM your_logic_here;
```

> Your existing CTE pipeline should populate these columns (TV → TGV → weighted final match).
> The app joins employees + dims for display.

### Optional RPC (if you want a DB-side entry point)

```sql
-- Supabase Postgres function example (optional convenience)
create or replace function get_talent_match_results()
returns table (
  job_vacancy_id int,
  employee_id text,
  tgv_name text,
  tv_name text,
  baseline_score numeric,
  user_score numeric,
  tv_match_rate numeric,
  tgv_match_rate numeric,
  final_match_rate numeric
)
language sql as $$
  select job_vacancy_id, employee_id, tgv_name, tv_name,
         baseline_score, user_score, tv_match_rate, tgv_match_rate, final_match_rate
  from v_benchmark_matching;
$$;
```

---

## How the App Uses Secrets

The Streamlit app reads credentials via `st.secrets`:

* `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`
* `OPENROUTER_API_KEY`
* `LLM_MODEL` (optional; app calls `openai/gpt-4o-mini` via OpenRouter)

> On **Streamlit Cloud**, set these in **Settings → Secrets**.
> Locally, store them in `.streamlit/secrets.toml` (as shown above).

---

## Deployment (Streamlit Cloud)

1. Push your repo to GitHub.
2. In Streamlit Cloud, create a new app from this repo.
3. Add **Secrets** (same keys as above).
4. Set **Python version** to 3.10+ and point to your `requirements.txt`.
5. (Optional) Add environment var:

   * `STREAMLIT_WATCH_FILE_SYSTEM=false` to reduce CPU usage.

---

## Usage

1. **Re-run an existing benchmark** (pick an ID) or **Create a new benchmark**:

   * Fill *Role name*, *Job level*, *Role purpose*
   * Select up to 3 benchmark employees
2. See **Top 10** candidates + **Distribution** chart
3. Inspect any candidate:

   * **TV table** with color-coded match
   * **TGV radar** vs. 100% benchmark
4. Generate **AI Job Profile** (English) with:

   * Job Requirements, Job Description, Key Competencies
   * Candidate insights (strengths & growth areas)
5. Export CSVs as needed

---

## Troubleshooting

* **`No benchmark results yet…`**
  You haven’t created or re-run a benchmark. Create one in Section 3.

* **`Failed to process TGV summary: 'tgv_name'`**
  Your `v_benchmark_matching` doesn’t include `tgv_name`, or `ranked_df` is empty.
  Ensure your view returns `tgv_name` and you’ve run a benchmark.

* **`AI Profile section skipped due to: name 'pick_emp' is not defined`**
  Fixed in code: we now guard for missing selection. Select a candidate in Section C.

* **OpenRouter error / 401**
  Check `OPENROUTER_API_KEY` in secrets; ensure the model name is available.
  The app requests `"openai/gpt-4o-mini"`.

* **High CPU on Streamlit Cloud**
  Keep `STREAMLIT_WATCH_FILE_SYSTEM=false` (already set in code) and avoid large auto-refresh loops.

---

## Security Notes

* Do **not** hardcode secrets; always use `st.secrets`.
* Limit DB roles to **read-only** for app queries where possible.
* Sanitize/validate any parameters that could hit SQL.

---

## Tech Stack & Versions (suggested)

* python: 3.10+
* streamlit: ^1.37
* pandas, sqlalchemy, psycopg2-binary
* plotly
* requests

Example `requirements.txt`:

```txt
streamlit>=1.37
pandas>=2.2
sqlalchemy>=2.0
psycopg2-binary>=2.9
plotly>=5.20
requests>=2.31
```

---

## License

MIT 

---

## Acknowledgments

* OpenRouter for model routing to **GPT-4o-mini**
* Streamlit for rapid data app development
* PostgreSQL / Supabase for managed Postgres

---
