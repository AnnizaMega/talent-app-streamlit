--Documentation SQL Number 1 
--Discover the Pattern of Success

--Latest Year per Employee
-- View untuk mendeteksi tahun terakhir tiap karyawan
CREATE OR REPLACE VIEW v_latest_year AS
SELECT employee_id, MAX(year) AS latest_year
FROM performance_yearly
GROUP BY 1;

--Jumlah High Performers per Tahun
SELECT year, COUNT(*) AS total_high_performers
FROM performance_yearly
WHERE rating = 5
GROUP BY year
ORDER BY year;

--High Performers per Grade
SELECT g.name AS grade_name, COUNT(*) AS total_high_performers
FROM performance_yearly p
JOIN employees e ON e.employee_id = p.employee_id
JOIN dim_grades g ON g.grade_id = e.grade_id
WHERE p.rating = 5
GROUP BY g.name
ORDER BY total_high_performers DESC;

--High Performers per Division
SELECT d.name AS division_name, COUNT(*) AS total_high_performers
FROM performance_yearly p
JOIN employees e ON e.employee_id = p.employee_id
JOIN dim_divisions d ON d.division_id = e.division_id
WHERE p.rating = 5
GROUP BY d.name
ORDER BY total_high_performers DESC;

--High Performers per Education Level
SELECT edu.name AS education_level, COUNT(*) AS total_high_performers
FROM performance_yearly p
JOIN employees e ON e.employee_id = p.employee_id
JOIN dim_education edu ON edu.education_id = e.education_id
WHERE p.rating = 5
GROUP BY edu.name
ORDER BY total_high_performers DESC;

--DISC Profiles
SELECT ps.disc_word AS disc_profile, COUNT(*) AS total_high_performers
FROM performance_yearly p
JOIN profiles_psych ps ON ps.employee_id = p.employee_id
WHERE p.rating = 5
GROUP BY ps.disc_word
ORDER BY total_high_performers DESC;

--MBTI Distribution
SELECT COALESCE(NULLIF(TRIM(ps.mbti), ''), 'Unknown') AS mbti,
       COUNT(*) AS total_high_performers
FROM performance_yearly p
JOIN profiles_psych ps ON ps.employee_id = p.employee_id
WHERE p.rating = 5
GROUP BY COALESCE(NULLIF(TRIM(ps.mbti), ''), 'Unknown')
ORDER BY total_high_performers DESC;

--IQ / GTQ Summary
SELECT
  ROUND(AVG(ps.iq)::numeric, 2)  AS avg_iq,
  ROUND(AVG(ps.gtq)::numeric, 2) AS avg_gtq,
  MIN(ps.iq)  AS min_iq,  MAX(ps.iq)  AS max_iq,
  MIN(ps.gtq) AS min_gtq, MAX(ps.gtq) AS max_gtq
FROM profiles_psych ps;

--TIKI Summary
SELECT
  ROUND(AVG(ps.tiki)::numeric, 2) AS avg_tiki,
  MIN(ps.tiki) AS min_tiki, MAX(ps.tiki) AS max_tiki
FROM profiles_psych ps;

--Average Competency per Pillar
CREATE OR REPLACE VIEW v_pillar_avg_latest AS
SELECT p.pillar_code, dcp.pillar_label,
       ROUND(AVG(p.score)::numeric, 2) AS avg_score
FROM competencies_yearly p
JOIN v_latest_year ly ON ly.employee_id = p.employee_id AND ly.latest_year = p.year
JOIN dim_competency_pillars dcp ON dcp.pillar_code = p.pillar_code
GROUP BY p.pillar_code, dcp.pillar_label
ORDER BY avg_score DESC;

--Korelasi Pilar vs Performance
SELECT dcp.pillar_label,
       ROUND(AVG(c.score)::numeric, 2) AS avg_competency_score,
       ROUND(AVG(py.rating)::numeric, 2) AS avg_performance_rating
FROM competencies_yearly c
JOIN v_latest_year ly ON ly.employee_id = c.employee_id AND ly.latest_year = c.year
JOIN dim_competency_pillars dcp ON dcp.pillar_code = c.pillar_code
JOIN performance_yearly py ON py.employee_id = c.employee_id AND py.year = ly.latest_year
GROUP BY dcp.pillar_label
ORDER BY avg_competency_score DESC;