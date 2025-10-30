-- View: v_benchmark_matching  (benchmark-aware + job_vacancy_id carried through)
CREATE OR REPLACE VIEW v_benchmark_matching AS
WITH params AS (
  -- ambil SEMUA benchmark; app akan memfilter berdasarkan job_vacancy_id
  SELECT tb.job_vacancy_id, tb.role_name, tb.job_level, tb.role_purpose, tb.selected_talent_ids
  FROM talent_benchmarks tb
),
latest AS (
  SELECT employee_id, MAX(year) AS latest_year
  FROM performance_yearly
  GROUP BY 1
),
tv_all AS (
  -- All area TV + tgv for each employee (score user_score is numeric)
  SELECT c.employee_id,
         'Competencies' AS tgv_name,
         p.pillar_label  AS tv_name,
         c.score::numeric AS user_score,
         'higher' AS direction
  FROM competencies_yearly c
  JOIN dim_competency_pillars p ON p.pillar_code = c.pillar_code
  JOIN latest ly ON ly.employee_id = c.employee_id AND ly.latest_year = c.year

  UNION ALL
  SELECT pr.employee_id, 'Cognitive','IQ',  pr.iq::numeric,  'higher'
  FROM profiles_psych pr

  UNION ALL
  SELECT pr.employee_id, 'Cognitive','GTQ', pr.gtq::numeric, 'higher'
  FROM profiles_psych pr

  -- adding: TIKI included to TGV Cognitive
  UNION ALL
  SELECT pr.employee_id, 'Cognitive','TIKI', pr.tiki::numeric, 'higher'
  FROM profiles_psych pr

  UNION ALL
  SELECT ps.employee_id, 'PersonalityPAPI', ps.scale_code, ps.score::numeric, 'higher'
  FROM papi_scores ps

  UNION ALL
  SELECT y.employee_id, 'Context','PerformanceRating', y.rating::numeric, 'higher'
  FROM performance_yearly y
  JOIN latest ly ON ly.employee_id = y.employee_id AND ly.latest_year = y.year

  UNION ALL
  SELECT s.employee_id, 'BehaviorStrengths','StrengthsRankAvg', AVG(s.rank)::numeric, 'lower'
  FROM strengths s
  GROUP BY s.employee_id
),
bench_ids AS (
  -- unnest text[] -> row per employee_id for each job_vacancy_id
  SELECT p.job_vacancy_id,
         UNNEST(p.selected_talent_ids) AS employee_id
  FROM params p
),
bench_tv AS (
  -- score TV from benchmark for each job_vacancy_id
  SELECT b.job_vacancy_id,
         t.tgv_name,
         t.tv_name,
         t.user_score
  FROM tv_all t
  JOIN bench_ids b ON b.employee_id = t.employee_id
),
baseline AS (
  -- median (50th percentile) per job_vacancy_id × TGV × TV
  SELECT job_vacancy_id,
         tgv_name,
         tv_name,
         PERCENTILE_DISC(0.5) WITHIN GROUP (ORDER BY user_score) AS baseline_score
  FROM bench_tv
  GROUP BY 1,2,3
),
tv_match AS (
  -- match rate per employee × TV × job_vacancy_id
  SELECT t.employee_id,
         b.job_vacancy_id,
         t.tgv_name,
         t.tv_name,
         b.baseline_score,
         t.user_score,
         CASE
           WHEN b.baseline_score IS NULL OR b.baseline_score = 0 THEN NULL
           WHEN t.direction = 'higher'
                THEN LEAST(100.0, 100.0 * (t.user_score / b.baseline_score))
           WHEN t.direction = 'lower'
                THEN GREATEST(0.0, LEAST(100.0, 100.0 * ((2*b.baseline_score - t.user_score) / b.baseline_score)))
         END::numeric AS tv_match_rate
  FROM tv_all t
  LEFT JOIN baseline b
    ON b.tgv_name = t.tgv_name
   AND b.tv_name  = t.tv_name
),
tgv_match AS (
  -- avg TV match in each TGV per employee × job_vacancy_id
  SELECT employee_id,
         job_vacancy_id,
         tgv_name,
         AVG(tv_match_rate)::numeric AS tgv_match_rate
  FROM tv_match
  GROUP BY 1,2,3
),
final_match AS (
  -- formula TGV → final match per employee × job_vacancy_id
  SELECT employee_id,
         job_vacancy_id,
         ROUND(
           0.40*COALESCE(MAX(CASE WHEN tgv_name='Competencies'      THEN tgv_match_rate END),0) +
           0.30*COALESCE(MAX(CASE WHEN tgv_name='Cognitive'         THEN tgv_match_rate END),0) +
           0.15*COALESCE(MAX(CASE WHEN tgv_name='PersonalityPAPI'   THEN tgv_match_rate END),0) +
           0.10*COALESCE(MAX(CASE WHEN tgv_name='Context'           THEN tgv_match_rate END),0) +
           0.05*COALESCE(MAX(CASE WHEN tgv_name='BehaviorStrengths' THEN tgv_match_rate END),0)
         ,2)::numeric AS final_match_rate
  FROM tgv_match
  GROUP BY 1,2
)
SELECT
  fm.job_vacancy_id,                  
  e.employee_id,
  dir.name AS directorate,
  pos.name AS role,
  gr.name  AS grade,
  tm.tgv_name,
  tm.tv_name,
  ROUND(tm.baseline_score, 2)::numeric AS baseline_score,
  ROUND(tm.user_score, 2)::numeric      AS user_score,
  ROUND(tm.tv_match_rate, 2)::numeric   AS tv_match_rate,
  ROUND(tg.tgv_match_rate, 2)::numeric  AS tgv_match_rate,
  ROUND(fm.final_match_rate, 2)::numeric AS final_match_rate
FROM tv_match tm
LEFT JOIN tgv_match      tg  ON tg.employee_id     = tm.employee_id
                            AND tg.tgv_name        = tm.tgv_name
                            AND tg.job_vacancy_id  = tm.job_vacancy_id
LEFT JOIN final_match    fm  ON fm.employee_id     = tm.employee_id
                            AND fm.job_vacancy_id  = tm.job_vacancy_id
JOIN employees           e   ON e.employee_id      = tm.employee_id
LEFT JOIN dim_directorates dir ON dir.directorate_id = e.directorate_id
LEFT JOIN dim_positions    pos ON pos.position_id    = e.position_id
LEFT JOIN dim_grades       gr  ON gr.grade_id        = e.grade_id
ORDER BY fm.job_vacancy_id, fm.final_match_rate DESC NULLS LAST, e.employee_id, tm.tgv_name, tm.tv_name;
