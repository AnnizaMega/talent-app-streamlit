-- Documentation Logic SQL 
--Normalisasi komponen (TGV 0–1) untuk Talent Readiness
--Digunakan membangun v_tgv_final dan seluruh ringkasan readiness.
-- (a) Competencies (0–5 → 0–1)
CREATE OR REPLACE VIEW v_tgv_competencies AS
SELECT c.employee_id, ly.latest_year AS year,
       ROUND(AVG(c.score)::numeric, 2) AS comp_avg,
       ROUND((AVG(c.score) / 5.0)::numeric, 4) AS tgv_competencies
FROM competencies_yearly c
JOIN v_latest_year ly ON ly.employee_id = c.employee_id AND ly.latest_year = c.year
GROUP BY c.employee_id, ly.latest_year;

-- (b) Cognitive: min–max normalize IQ & GTQ → lalu average
CREATE OR REPLACE VIEW v_tgv_cognitive AS
WITH src AS (
  SELECT ps.employee_id, ps.iq::numeric AS iq, ps.gtq::numeric AS gtq FROM profiles_psych ps
),
bd AS (
  SELECT MIN(iq) AS min_iq, MAX(iq) AS max_iq, MIN(gtq) AS min_gtq, MAX(gtq) AS max_gtq FROM src
)
SELECT s.employee_id, ly.latest_year AS year,
       ROUND(( (s.iq - b.min_iq)  / NULLIF(b.max_iq  - b.min_iq ,0) 
             + (s.gtq - b.min_gtq)/ NULLIF(b.max_gtq - b.min_gtq,0) )/2, 4) AS tgv_cognitive
FROM src s CROSS JOIN bd b
JOIN v_latest_year ly ON ly.employee_id = s.employee_id;

-- (c) Personality (PAPI): min–max per scale → rata-rata
CREATE OR REPLACE VIEW v_tgv_personalitypapi AS
WITH by_scale AS (
  SELECT scale_code,
         MIN(score::numeric) AS min_s, MAX(score::numeric) AS max_s
  FROM papi_scores GROUP BY 1
),
norm AS (
  SELECT p.employee_id, p.scale_code,
         (p.score::numeric - b.min_s)/NULLIF(b.max_s - b.min_s,0) AS z
  FROM papi_scores p JOIN by_scale b USING (scale_code)
)
SELECT n.employee_id, ly.latest_year AS year,
       ROUND(AVG(n.z)::numeric, 4) AS tgv_personalitypapi
FROM norm n
JOIN v_latest_year ly ON ly.employee_id = n.employee_id
GROUP BY n.employee_id, ly.latest_year;

-- (d) Context (performance rating 1–5 → 0–1)
CREATE OR REPLACE VIEW v_tgv_context AS
SELECT p.employee_id, p.year,
       ROUND((p.rating::numeric / 5.0), 4) AS tgv_context
FROM performance_yearly p
JOIN v_latest_year ly ON ly.employee_id = p.employee_id AND ly.latest_year = p.year;

-- (e) BehaviorStrengths: rank lebih kecil = lebih baik → ubah ke 0–1
CREATE OR REPLACE VIEW v_tgv_behaviorstrengths AS
WITH r AS (
  SELECT employee_id, AVG(rank)::numeric AS avg_rank FROM strengths GROUP BY 1
),
bd AS (
  SELECT MIN(avg_rank) AS min_r, MAX(avg_rank) AS max_r FROM r
)
SELECT r.employee_id, ly.latest_year AS year,
       ROUND(1 - ((r.avg_rank - b.min_r)/NULLIF(b.max_r - b.min_r,0)), 4) AS tgv_behaviorstrengths
FROM r CROSS JOIN bd b
JOIN v_latest_year ly ON ly.employee_id = r.employee_id;


--Gabungkan ke FinalMatch (0–1) + versi persentase + kategori + ranking
-- v_tgv_final: gabungan TGV dengan bobot
CREATE OR REPLACE VIEW v_tgv_final AS
SELECT
  e.employee_id,
  ly.latest_year AS year,
  ROUND( 0.40*tc.tgv_competencies
       + 0.30*cg.tgv_cognitive
       + 0.15*pp.tgv_personalitypapi
       + 0.10*cx.tgv_context
       + 0.05*bs.tgv_behaviorstrengths, 4) AS finalmatch,
  ROUND(100 * ( 0.40*tc.tgv_competencies
              + 0.30*cg.tgv_cognitive
              + 0.15*pp.tgv_personalitypapi
              + 0.10*cx.tgv_context
              + 0.05*bs.tgv_behaviorstrengths ), 2) AS finalmatch_pct,
  tc.tgv_competencies, cg.tgv_cognitive, pp.tgv_personalitypapi, cx.tgv_context, bs.tgv_behaviorstrengths
FROM employees e
JOIN v_latest_year ly ON ly.employee_id = e.employee_id
LEFT JOIN v_tgv_competencies     tc USING (employee_id, year)
LEFT JOIN v_tgv_cognitive        cg USING (employee_id, year)
LEFT JOIN v_tgv_personalitypapi  pp USING (employee_id, year)
LEFT JOIN v_tgv_context          cx USING (employee_id, year)
LEFT JOIN v_tgv_behaviorstrengths bs USING (employee_id, year);

-- v_tgv_final_ranked: kategori & ranking tahunan
CREATE OR REPLACE VIEW v_tgv_final_ranked AS
SELECT
  f.*,
  CASE WHEN f.finalmatch_pct >= 80 THEN 'Fast Track'
       WHEN f.finalmatch_pct >= 65 THEN 'Ready'
       WHEN f.finalmatch_pct >= 50 THEN 'Watchlist'
       ELSE 'Develop' END AS readiness_category,
  DENSE_RANK() OVER (PARTITION BY f.year ORDER BY f.finalmatch DESC) AS rank_in_year,
  ROUND((100 * CUME_DIST() OVER (PARTITION BY f.year ORDER BY f.finalmatch))::numeric, 2) AS percentile_in_year
FROM v_tgv_final f;

--Ringkasan untuk Dashboard
-- Top 3 per divisi (tahun terbaru)
CREATE OR REPLACE VIEW v_shortlist_top3_by_division AS
WITH ranked AS (
  SELECT e.division_id, d.name AS division_name, f.employee_id, f.year, f.finalmatch_pct,
         f.readiness_category,
         ROW_NUMBER() OVER (PARTITION BY e.division_id, f.year ORDER BY f.finalmatch DESC) AS rn
  FROM v_tgv_final_ranked f
  JOIN employees e ON e.employee_id = f.employee_id
  JOIN dim_divisions d ON d.division_id = e.division_id
)
SELECT division_name, employee_id, year, finalmatch_pct, readiness_category, rn AS rank_in_division
FROM ranked
WHERE rn <= 3
ORDER BY division_name, rn;
-- Summary latest year
CREATE OR REPLACE VIEW v_readiness_summary_latest AS
WITH latest AS (SELECT MAX(year) AS year FROM v_tgv_final_ranked)
SELECT f.year, f.readiness_category, COUNT(*) AS n_employees,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (), 2) AS pct_of_total
FROM v_tgv_final_ranked f
JOIN latest l ON l.year = f.year
GROUP BY f.year, f.readiness_category
ORDER BY f.readiness_category;
-- Trend by year
CREATE OR REPLACE VIEW v_readiness_summary_by_year AS
SELECT year, readiness_category, COUNT(*) AS n_employees,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY year), 2) AS pct_of_total
FROM v_tgv_final_ranked
GROUP BY year, readiness_category
ORDER BY year, readiness_category;
-- Summary per division (tahun terbaru)
CREATE OR REPLACE VIEW v_readiness_summary_by_division AS
WITH latest AS (SELECT MAX(year) AS year FROM v_tgv_final_ranked)
SELECT d.name AS division_name, f.readiness_category, COUNT(*) AS n_employees,
       ROUND(100.0 * COUNT(*) / SUM(COUNT(*)) OVER (PARTITION BY d.name), 2) AS pct_within_division
FROM v_tgv_final_ranked f
JOIN employees e ON e.employee_id = f.employee_id
JOIN dim_divisions d ON d.division_id = e.division_id
JOIN latest l ON l.year = f.year
GROUP BY d.name, f.readiness_category
ORDER BY d.name, f.readiness_category;

