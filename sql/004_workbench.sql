-- Operational reference tables start empty; populate from confirmed evidence.
CREATE TABLE organizations (
 organization_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
 name TEXT NOT NULL,
 organization_type TEXT NOT NULL DEFAULT 'customer',
 notes TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE facilities (
 facility_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
 organization_id TEXT REFERENCES organizations(organization_id),
 name TEXT NOT NULL,
 street_address TEXT,
 city TEXT,
 state_province TEXT,
 postal_code TEXT,
 country TEXT,
 latitude REAL CHECK(latitude BETWEEN -90 AND 90),
 longitude REAL CHECK(longitude BETWEEN -180 AND 180),
 location_precision TEXT CHECK(location_precision IN ('facility','street','city','unknown')) DEFAULT 'unknown',
 evidence_note TEXT,
 verified INTEGER NOT NULL DEFAULT 0 CHECK(verified IN (0,1)),
 CHECK((latitude IS NULL)=(longitude IS NULL))
);
CREATE TABLE facility_codes (
 facility_code_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
 facility_id TEXT NOT NULL REFERENCES facilities(facility_id),
 namespace TEXT NOT NULL DEFAULT 'Prime',
 code TEXT NOT NULL,
 role TEXT NOT NULL CHECK(role IN ('shipper','receiver','bill_to','vendor','other')),
 valid_from TEXT,
 valid_to TEXT,
 evidence_note TEXT,
 CHECK(valid_from IS NULL OR valid_to IS NULL OR valid_to>=valid_from)
);
CREATE TABLE operating_periods (
 period_id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(16)))),
 start_date TEXT NOT NULL,
 end_date TEXT,
 owner_code TEXT,
 unit_code TEXT,
 business_mode TEXT NOT NULL CHECK(business_mode IN ('employee','lease','lease_purchase','owned','unknown')),
 trainer INTEGER CHECK(trainer IN (0,1)),
 evidence_note TEXT,
 CHECK(end_date IS NULL OR end_date>=start_date)
);
CREATE INDEX loads_by_parse ON load_leg_candidates(parse_id);
CREATE INDEX runs_by_job ON structured_runs(job_id,status,created_at);
CREATE INDEX routes_by_leg ON route_point_candidates(leg_id,sequence);
CREATE INDEX checks_by_parse ON reconciliation_checks(parse_id,status);
CREATE INDEX issues_by_parse ON structured_issues(parse_id,issue_kind);

-- Materialize the current version boundary once per statement, avoiding repeated
-- expansion of the OCR and parser history window functions in analytical joins.
CREATE VIEW v_workbench_statements AS
 WITH current AS MATERIALIZED (SELECT * FROM v_settlement_review) SELECT * FROM current;

-- Normalization is limited to numerical identifiers; raw IDs stay beside the keys.
CREATE VIEW v_postings_keyed AS
 WITH current AS MATERIALIZED (SELECT * FROM v_workbench_statements)
 SELECT s.original_filename,s.settlement_date,s.owner_code,s.unit_code,l.page_number,l.line_number,p.*,
 CASE WHEN trim(order_raw)<>'' AND replace(replace(replace(order_raw,'O','0'),'l','1'),'I','1') NOT GLOB '*[^0-9]*'
      THEN replace(replace(replace(order_raw,'O','0'),'l','1'),'I','1') ELSE order_raw END AS order_key,
 CASE WHEN trim(dispatch_raw)<>'' AND replace(replace(replace(dispatch_raw,'O','0'),'l','1'),'I','1') NOT GLOB '*[^0-9]*'
      THEN replace(replace(replace(dispatch_raw,'O','0'),'l','1'),'I','1') ELSE dispatch_raw END AS dispatch_key
 FROM current s JOIN settlement_posting_candidates p USING(parse_id)
 JOIN source_line_candidates l ON l.line_id=p.posting_id;
CREATE VIEW v_loads_keyed AS
 WITH postings AS MATERIALIZED (SELECT * FROM v_postings_keyed)
 SELECT p.original_filename,p.settlement_date,p.owner_code,p.unit_code,l.*,p.order_key,p.dispatch_key
 FROM load_leg_candidates l JOIN postings p ON p.posting_id=l.leg_id;
CREATE VIEW v_dispatch_revenue AS
 SELECT parse_id,order_key,dispatch_key,count(*) AS posting_count,
 count(*)-count(amount_cents) AS unknown_amounts,
 CASE WHEN count(*)=count(amount_cents) THEN sum(amount_cents) END AS revenue_cents
 FROM v_postings_keyed WHERE section='revenue' AND coalesce(order_key,'')<>''
 GROUP BY parse_id,order_key,dispatch_key;
CREATE VIEW v_dispatch_leg_counts AS
 SELECT parse_id,order_key,dispatch_key,count(*) AS leg_count FROM v_loads_keyed
 GROUP BY parse_id,order_key,dispatch_key;
CREATE VIEW v_unique_statement_totals AS
 SELECT parse_id,metric,unit,
 CASE WHEN count(*)=count(value_integer) AND min(value_integer)=max(value_integer)
      THEN min(value_integer) END AS value_integer
 FROM statement_total_candidates GROUP BY parse_id,metric,unit;
CREATE VIEW v_weekly_settlements AS
 WITH current AS MATERIALIZED (SELECT * FROM v_workbench_statements), amounts AS MATERIALIZED (
 SELECT parse_id,
 max(CASE WHEN metric='revenue_total' THEN value_integer END) AS revenue_cents,
 max(CASE WHEN metric='reimbursement_total' THEN value_integer END) AS reimbursement_cents,
 max(CASE WHEN metric='deduction_total' THEN value_integer END) AS deduction_cents,
 max(CASE WHEN metric='wage_expense_total' THEN value_integer END) AS wage_expense_cents,
 max(CASE WHEN metric='gross_due' THEN value_integer END) AS gross_due_cents,
 max(CASE WHEN metric='net_due' THEN value_integer END) AS net_due_cents,
 max(CASE WHEN metric='total_miles_total' THEN value_integer END) AS total_miles
 FROM v_unique_statement_totals GROUP BY parse_id
 )
 SELECT s.*,a.revenue_cents,a.reimbursement_cents,a.deduction_cents,a.wage_expense_cents,
 a.gross_due_cents,a.net_due_cents,a.total_miles,
 round(a.revenue_cents/100.0,2) AS revenue_dollars,
 CASE WHEN a.total_miles>0 THEN round(a.revenue_cents/100.0/a.total_miles,3) END AS revenue_per_total_mile,
 CASE WHEN s.mismatched_checks>0 THEN 'mismatch'
      WHEN s.incomplete_checks>0 OR a.revenue_cents IS NULL THEN 'incomplete'
      ELSE 'arithmetic_match_unverified' END AS arithmetic_status
 FROM current s LEFT JOIN amounts a USING(parse_id)
 WHERE s.document_kind IN ('owner_recap','employee_payroll');

CREATE VIEW v_route_endpoints AS
 SELECT l.leg_id,
 (SELECT r.city_raw FROM route_point_candidates r WHERE r.leg_id=l.leg_id AND r.following_segment_marker='L' ORDER BY sequence LIMIT 1) AS origin_city_raw,
 (SELECT r.state_raw FROM route_point_candidates r WHERE r.leg_id=l.leg_id AND r.following_segment_marker='L' ORDER BY sequence LIMIT 1) AS origin_state_raw,
 (SELECT r.city_raw FROM route_point_candidates r WHERE r.leg_id=l.leg_id ORDER BY sequence DESC LIMIT 1) AS destination_city_raw,
 (SELECT r.state_raw FROM route_point_candidates r WHERE r.leg_id=l.leg_id ORDER BY sequence DESC LIMIT 1) AS destination_state_raw,
 (SELECT count(*) FROM route_point_candidates r WHERE r.leg_id=l.leg_id) AS route_point_count
 FROM load_leg_candidates l;

CREATE VIEW v_load_economics AS
 WITH loads AS MATERIALIZED (SELECT * FROM v_loads_keyed),
 revenue AS MATERIALIZED (SELECT * FROM v_dispatch_revenue),
 counts AS MATERIALIZED (SELECT parse_id,order_key,dispatch_key,count(*) AS leg_count FROM loads GROUP BY parse_id,order_key,dispatch_key),
 joined AS (
 SELECT l.*,r.origin_city_raw,r.origin_state_raw,r.destination_city_raw,r.destination_state_raw,r.route_point_count,
 n.leg_count AS dispatch_leg_count,
 CASE WHEN n.leg_count=1 THEN d.revenue_cents END AS allocated_owner_revenue_cents,
 d.unknown_amounts,
 (SELECT status FROM reconciliation_checks c WHERE c.parse_id=l.parse_id AND c.check_name='revenue_sum') AS statement_revenue_check,
 count(*) OVER(PARTITION BY l.settlement_date,l.owner_code,l.unit_code,l.order_key,l.dispatch_key) AS possible_duplicate_legs
 FROM loads l
 LEFT JOIN v_route_endpoints r USING(leg_id)
 LEFT JOIN counts n USING(parse_id,order_key,dispatch_key)
 LEFT JOIN revenue d USING(parse_id,order_key,dispatch_key)
 ), classified AS (
 SELECT *,CASE WHEN allocated_owner_revenue_cents IS NULL OR total_miles IS NULL OR total_miles<=0
                    OR dispatch_leg_count<>1 THEN 'incomplete'
               WHEN mileage_check<>'match' OR statement_revenue_check<>'match'
                    OR statement_revenue_check IS NULL OR settlement_date IS NULL OR possible_duplicate_legs<>1
                    THEN 'needs_review'
               ELSE 'arithmetic_checked_unverified' END AS rate_quality
 FROM joined)
 SELECT *,round(allocated_owner_revenue_cents/100.0,2) AS allocated_owner_revenue_dollars,
 CASE WHEN total_miles>0 THEN round(allocated_owner_revenue_cents/100.0/total_miles,3) END AS owner_revenue_per_total_mile,
 CASE WHEN loaded_miles>0 THEN round(allocated_owner_revenue_cents/100.0/loaded_miles,3) END AS owner_revenue_per_loaded_mile
 FROM classified;

-- A candidate city is not a verified customer facility or a geocoded address.
CREATE VIEW v_location_history AS
 WITH loads AS MATERIALIZED (SELECT * FROM v_loads_keyed)
 SELECT r.city_raw,r.state_raw,count(*) AS route_mentions,count(DISTINCT r.leg_id) AS load_leg_visits,
 min(l.settlement_date) AS first_seen,max(l.settlement_date) AS last_seen,
 'unverified_ocr_location' AS location_status
 FROM route_point_candidates r JOIN loads l USING(leg_id)
 GROUP BY r.city_raw,r.state_raw;
CREATE VIEW v_lane_history AS
 SELECT origin_city_raw,origin_state_raw,destination_city_raw,destination_state_raw,
 count(*) AS candidate_load_legs,min(settlement_date) AS first_seen,max(settlement_date) AS last_seen,
 round(sum(allocated_owner_revenue_cents)/100.0,2) AS owner_revenue_dollars,
 sum(total_miles) AS total_miles,
 round(sum(allocated_owner_revenue_cents)/100.0/sum(total_miles),3) AS weighted_revenue_per_total_mile,
 'arithmetic_checked_unverified; historical records, not current freight offers' AS data_status
 FROM v_load_economics
 WHERE rate_quality='arithmetic_checked_unverified' AND origin_city_raw IS NOT NULL AND destination_city_raw IS NOT NULL
 GROUP BY origin_city_raw,origin_state_raw,destination_city_raw,destination_state_raw;
CREATE VIEW v_review_queue AS
 WITH current AS MATERIALIZED (SELECT * FROM v_workbench_statements)
 SELECT s.document_id,s.original_filename,s.settlement_date,c.parse_id,NULL AS page_number,
 'arithmetic_'||c.status AS issue_kind,c.check_name AS description,c.difference_integer,c.unit
 FROM reconciliation_checks c JOIN current s USING(parse_id) WHERE c.status<>'match'
 UNION ALL
 SELECT s.document_id,s.original_filename,s.settlement_date,i.parse_id,i.page_number,
 i.issue_kind,i.detail,NULL,NULL FROM structured_issues i JOIN current s USING(parse_id);
CREATE VIEW v_invoice_pages AS
 WITH current AS MATERIALIZED (SELECT * FROM v_workbench_statements)
 SELECT s.document_id,s.original_filename,s.settlement_date,p.page_number,p.page_kind,x.layout_text,
 'raw OCR; detailed party and invoice parsing pending' AS data_status
 FROM current s JOIN page_classifications p USING(parse_id)
 JOIN source_pages x ON x.job_id=s.job_id AND x.page_number=p.page_number
 WHERE p.page_kind IN ('freight_invoice','maintenance_or_vendor_invoice','toll_detail','fuel_tax_statement');
