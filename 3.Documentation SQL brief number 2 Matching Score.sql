--Documentation SQL brief number 2 
Create Dummy table for talent benchmark
CREATE TABLE IF NOT EXISTS talent_benchmarks (
  job_vacancy_id SERIAL PRIMARY KEY,
  role_name TEXT,
  job_level TEXT,
  role_purpose TEXT,
  selected_talent_ids TEXT[],
  weights_config JSONB
);

INSERT INTO talent_benchmarks (role_name, job_level, role_purpose, selected_talent_ids, weights_config)
VALUES (
  'Data Analyst',
  'Grade III',
  'Analyze data patterns and support decision-making.',
  ARRAY['EMP001', 'EMP002', 'EMP003'],  -- ganti ID sesuai data real di tabel employees
  '{"tgv":{"Competencies":0.4,"Cognitive":0.3,"PersonalityPAPI":0.15,"Context":0.1,"BehaviorStrengths":0.05}}'
);


--Talent Bechmark scoring 
WITH ly AS (
  SELECT employee_id, MAX(year) AS latest_year
  FROM performance_yearly
  GROUP BY 1
)
SELECT y.employee_id
FROM performance_yearly y
JOIN ly ON ly.employee_id = y.employee_id AND ly.latest_year = y.year
WHERE y.rating = 5
ORDER BY y.employee_id
LIMIT 20;

-- Set selected_talent_ids untuk benchmark id=1 memakai karyawan rating=5 (latest year)
WITH ly AS (
  SELECT employee_id, MAX(year) AS latest_year
  FROM performance_yearly
  GROUP BY 1
),
hp AS (
  SELECT y.employee_id
  FROM performance_yearly y
  JOIN ly ON ly.employee_id = y.employee_id AND ly.latest_year = y.year
  WHERE y.rating = 5
  ORDER BY y.employee_id
  LIMIT 50      -- boleh ubah jumlahnya
)
UPDATE talent_benchmarks
SET selected_talent_ids = ARRAY(SELECT employee_id FROM hp)
WHERE job_vacancy_id = 1;

--Output Talent Benchmarking rates
-- STEP 2: Operationalize Logic in SQL (Simplified Benchmark)
-- ==========================================================

WITH params AS (
  SELECT
    tb.job_vacancy_id,
    tb.role_name,
    tb.job_level,
    tb.role_purpose,
    tb.selected_talent_ids
  FROM talent_benchmarks tb
  WHERE tb.job_vacancy_id = 1
),

latest AS (
  SELECT employee_id, MAX(year) AS latest_year
  FROM performance_yearly
  GROUP BY 1
),

tv_all AS (
  -- Competencies
  SELECT c.employee_id, 'Competencies' AS tgv_name, p.pillar_label AS tv_name,
         c.score::numeric AS user_score, 'higher' AS direction
  FROM competencies_yearly c
  JOIN dim_competency_pillars p ON p.pillar_code = c.pillar_code
  JOIN latest ly ON ly.employee_id = c.employee_id AND ly.latest_year = c.year

  UNION ALL
  -- Cognitive
  SELECT pr.employee_id, 'Cognitive', 'IQ', pr.iq::numeric, 'higher' FROM profiles_psych pr
  UNION ALL
  SELECT pr.employee_id, 'Cognitive', 'GTQ', pr.gtq::numeric, 'higher' FROM profiles_psych pr

  UNION ALL
  -- PAPI
  SELECT ps.employee_id, 'PersonalityPAPI', ps.scale_code, ps.score::numeric, 'higher'
  FROM papi_scores ps

  UNION ALL
  -- Context
  SELECT y.employee_id, 'Context', 'PerformanceRating', y.rating::numeric, 'higher'
  FROM performance_yearly y
  JOIN latest ly ON ly.employee_id = y.employee_id AND ly.latest_year = y.year

  UNION ALL
  -- Strengths (lower is better)
  SELECT s.employee_id, 'BehaviorStrengths', 'StrengthsRankAvg', AVG(s.rank)::numeric, 'lower'
  FROM strengths s
  GROUP BY s.employee_id
),

-- benchmark (median dari selected_talent_ids)
bench_ids AS (
  SELECT UNNEST(p.selected_talent_ids) AS employee_id FROM params p
),
bench_tv AS (
  SELECT t.tgv_name, t.tv_name, t.user_score
  FROM tv_all t
  JOIN bench_ids b ON b.employee_id = t.employee_id
),
baseline AS (
  SELECT tgv_name, tv_name,
         PERCENTILE_DISC(0.5) WITHIN GROUP (ORDER BY user_score) AS baseline_score
  FROM bench_tv
  GROUP BY 1,2
),

-- hitung match rate
tv_match AS (
  SELECT
    t.employee_id,
    t.tgv_name,
    t.tv_name,
    b.baseline_score,
    t.user_score,
    CASE
      WHEN b.baseline_score IS NULL OR b.baseline_score = 0 THEN NULL
      WHEN t.direction = 'higher' THEN LEAST(100.0, 100.0 * (t.user_score / b.baseline_score))
      WHEN t.direction = 'lower'  THEN GREATEST(0.0, LEAST(100.0, 100.0 * ((2*b.baseline_score - t.user_score) / b.baseline_score)))
    END AS tv_match_rate
  FROM tv_all t
  LEFT JOIN baseline b USING (tgv_name, tv_name)
),

-- agregasi ke TGV
tgv_match AS (
  SELECT employee_id, tgv_name, AVG(tv_match_rate) AS tgv_match_rate
  FROM tv_match
  GROUP BY 1,2
),

-- final weighted
final_match AS (
  SELECT
    employee_id,
    ROUND(
      0.40 * COALESCE(MAX(CASE WHEN tgv_name='Competencies' THEN tgv_match_rate END),0) +
      0.30 * COALESCE(MAX(CASE WHEN tgv_name='Cognitive' THEN tgv_match_rate END),0) +
      0.15 * COALESCE(MAX(CASE WHEN tgv_name='PersonalityPAPI' THEN tgv_match_rate END),0) +
      0.10 * COALESCE(MAX(CASE WHEN tgv_name='Context' THEN tgv_match_rate END),0) +
      0.05 * COALESCE(MAX(CASE WHEN tgv_name='BehaviorStrengths' THEN tgv_match_rate END),0)
    ,2) AS final_match_rate
  FROM tgv_match
  GROUP BY 1
)



