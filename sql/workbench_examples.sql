-- Select ONE query in DBeaver and press Ctrl+Enter.
-- These are source-derived candidates. Arithmetic matches do not verify OCR.

-- 1. Recent weekly statements. One row is one document, not necessarily one week.
SELECT settlement_date, owner_code, unit_code, revenue_dollars,
       total_miles, revenue_per_total_mile, arithmetic_status
FROM v_weekly_settlements
ORDER BY settlement_date DESC
LIMIT 25;

-- 2. Recent loads: owner compensation includes matched dispatch revenue lines.
SELECT settlement_date, order_key, dispatch_key,
       origin_city_raw, origin_state_raw, destination_city_raw, destination_state_raw,
       loaded_miles, empty_miles, total_miles,
       allocated_owner_revenue_dollars, owner_revenue_per_total_mile, rate_quality
FROM v_load_economics
ORDER BY settlement_date DESC
LIMIT 50;

-- 3. Repeated historical lanes. Change dates/regions to compare relevant eras.
-- A long-run average is not a current quote or guaranteed reload opportunity.
SELECT origin_city_raw, origin_state_raw, destination_city_raw, destination_state_raw,
       COUNT(*) AS load_legs,
       ROUND(SUM(allocated_owner_revenue_cents)/100.0/SUM(total_miles),3) AS dollars_per_total_mile,
       MIN(settlement_date) AS first_seen, MAX(settlement_date) AS last_seen
FROM v_load_economics
WHERE rate_quality='arithmetic_checked_unverified'
  AND settlement_date >= '2024-01-01'
  AND origin_city_raw IS NOT NULL AND destination_city_raw IS NOT NULL
GROUP BY origin_city_raw, origin_state_raw, destination_city_raw, destination_state_raw
HAVING COUNT(*) >= 3
ORDER BY dollars_per_total_mile DESC;

-- 4. Most frequent raw location labels. Similar OCR spellings may need merging.
SELECT * FROM v_location_history
ORDER BY load_leg_visits DESC LIMIT 40;

-- 5. Concrete arithmetic differences needing source review (cents or miles).
SELECT settlement_date, original_filename, description, difference_integer, unit
FROM v_review_queue WHERE issue_kind='arithmetic_mismatch'
ORDER BY settlement_date;

-- 6. All payment lines for a particular order, with source page/line.
-- Replace DEMO_ORDER with a value shown by query 2; leave quotes in place.
SELECT settlement_date, section, code_raw, description_raw,
       amount_cents/100.0 AS amount_dollars, page_number, line_number,
       original_filename
FROM v_postings_keyed WHERE order_key='DEMO_ORDER'
ORDER BY settlement_date, page_number, line_number;

-- 7. Unknown values remain NULL, never silently converted into zero expenses.
SELECT section, COUNT(*) AS lines,
       COUNT(*)-COUNT(amount_cents) AS unresolved_amounts
FROM v_postings_keyed GROUP BY section;

-- 8. Source invoice text for later customer/facility extraction.
SELECT original_filename, page_number, page_kind, layout_text
FROM v_invoice_pages WHERE page_kind='freight_invoice' LIMIT 5;
