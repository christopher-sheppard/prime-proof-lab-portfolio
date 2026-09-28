-- Candidate records only. No row in these tables is approved accounting data.
CREATE TABLE source_numeric_pages (
 job_id TEXT NOT NULL,
 page_number INTEGER NOT NULL,
 ocr_text TEXT NOT NULL,
 words_json TEXT NOT NULL,
 PRIMARY KEY(job_id,page_number),
 FOREIGN KEY(job_id,page_number) REFERENCES source_pages(job_id,page_number) ON DELETE CASCADE
);
CREATE TABLE structured_runs (
 parse_id TEXT PRIMARY KEY,
 job_id TEXT NOT NULL REFERENCES page_extraction_jobs(job_id),
 parser_version TEXT NOT NULL,
 parser_sha256 TEXT NOT NULL,
 created_at TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('complete','failed')),
 UNIQUE(job_id,parser_sha256)
);
CREATE TABLE statement_candidates (
 parse_id TEXT PRIMARY KEY REFERENCES structured_runs(parse_id),
 document_kind TEXT NOT NULL,
 settlement_date TEXT,
 owner_code TEXT,
 owner_name TEXT,
 unit_code TEXT,
 header_evidence_json TEXT NOT NULL,
 review_status TEXT NOT NULL DEFAULT 'unverified' CHECK(review_status='unverified')
);
CREATE TABLE page_classifications (
 parse_id TEXT NOT NULL REFERENCES structured_runs(parse_id),
 page_number INTEGER NOT NULL,
 page_kind TEXT NOT NULL,
 structured_support TEXT NOT NULL,
 PRIMARY KEY(parse_id,page_number)
);
CREATE TABLE source_line_candidates (
 line_id TEXT PRIMARY KEY,
 parse_id TEXT NOT NULL REFERENCES structured_runs(parse_id),
 page_number INTEGER NOT NULL,
 line_number INTEGER NOT NULL,
 page_kind TEXT NOT NULL,
 section TEXT,
 raw_text TEXT NOT NULL,
 words_json TEXT NOT NULL,
 row_role TEXT NOT NULL,
 UNIQUE(parse_id,page_number,line_number)
);
CREATE TABLE settlement_posting_candidates (
 posting_id TEXT PRIMARY KEY REFERENCES source_line_candidates(line_id),
 parse_id TEXT NOT NULL REFERENCES structured_runs(parse_id),
 section TEXT NOT NULL CHECK(section IN ('revenue','reimbursement','deduction','wage_expense')),
 code_raw TEXT,
 order_raw TEXT,
 dispatch_raw TEXT,
 sequence_raw TEXT,
 date_mmdd_raw TEXT,
 description_raw TEXT,
 amount_cents INTEGER,
 balance_cents INTEGER,
 fuel_discount_cents INTEGER,
 payout_effect_cents INTEGER,
 numeric_evidence_json TEXT NOT NULL,
 review_status TEXT NOT NULL DEFAULT 'unverified' CHECK(review_status='unverified')
);
CREATE TABLE load_leg_candidates (
 leg_id TEXT PRIMARY KEY REFERENCES settlement_posting_candidates(posting_id),
 parse_id TEXT NOT NULL REFERENCES structured_runs(parse_id),
 order_raw TEXT,
 dispatch_raw TEXT,
 load_miles INTEGER,
 load_revenue_cents INTEGER,
 loaded_miles INTEGER,
 empty_miles INTEGER,
 total_miles INTEGER,
 trip_revenue_cents INTEGER,
 owner_rate_millionths INTEGER,
 owner_revenue_cents INTEGER,
 solo_team_raw TEXT,
 mileage_check TEXT NOT NULL,
 allocation_note TEXT,
 numeric_evidence_json TEXT NOT NULL,
 review_status TEXT NOT NULL DEFAULT 'unverified' CHECK(review_status='unverified')
);
CREATE TABLE route_point_candidates (
 point_id TEXT PRIMARY KEY,
 leg_id TEXT NOT NULL REFERENCES load_leg_candidates(leg_id),
 line_id TEXT NOT NULL REFERENCES source_line_candidates(line_id),
 sequence INTEGER NOT NULL,
 city_raw TEXT NOT NULL,
 state_raw TEXT NOT NULL,
 following_segment_marker TEXT,
 review_status TEXT NOT NULL DEFAULT 'unverified' CHECK(review_status='unverified'),
 UNIQUE(leg_id,sequence)
);
CREATE TABLE statement_total_candidates (
 total_id TEXT PRIMARY KEY,
 parse_id TEXT NOT NULL REFERENCES structured_runs(parse_id),
 line_id TEXT NOT NULL REFERENCES source_line_candidates(line_id),
 metric TEXT NOT NULL,
 value_integer INTEGER,
 unit TEXT NOT NULL,
 numeric_evidence_json TEXT NOT NULL
);
CREATE TABLE operating_measure_candidates (
 measure_id TEXT PRIMARY KEY REFERENCES source_line_candidates(line_id),
 parse_id TEXT NOT NULL REFERENCES structured_runs(parse_id),
 label_raw TEXT NOT NULL,
 reported_unit TEXT NOT NULL,
 week_hundredths INTEGER,
 ytd_hundredths INTEGER,
 ltd_hundredths INTEGER,
 week_rate_thousandths INTEGER,
 ytd_rate_thousandths INTEGER,
 ltd_rate_thousandths INTEGER,
 numeric_evidence_json TEXT NOT NULL,
 review_status TEXT NOT NULL DEFAULT 'unverified' CHECK(review_status='unverified')
);
CREATE TABLE fuel_event_candidates (
 fuel_id TEXT PRIMARY KEY REFERENCES settlement_posting_candidates(posting_id),
 parse_id TEXT NOT NULL REFERENCES structured_runs(parse_id),
 product_raw TEXT NOT NULL,
 gallons_raw TEXT,
 gallons_thousandths INTEGER,
 description_raw TEXT NOT NULL,
 review_status TEXT NOT NULL DEFAULT 'unverified' CHECK(review_status='unverified')
);
CREATE TABLE reconciliation_checks (
 check_id TEXT PRIMARY KEY,
 parse_id TEXT NOT NULL REFERENCES structured_runs(parse_id),
 check_name TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('match','mismatch','incomplete','not_applicable')),
 calculated_integer INTEGER,
 reported_integer INTEGER,
 difference_integer INTEGER,
 unit TEXT NOT NULL,
 detail TEXT NOT NULL
);
CREATE TABLE structured_issues (
 issue_id TEXT PRIMARY KEY,
 parse_id TEXT NOT NULL REFERENCES structured_runs(parse_id),
 page_number INTEGER,
 line_id TEXT REFERENCES source_line_candidates(line_id),
 issue_kind TEXT NOT NULL,
 detail TEXT NOT NULL
);
CREATE INDEX posting_parse_section ON settlement_posting_candidates(parse_id,section);
CREATE INDEX lines_parse_page ON source_line_candidates(parse_id,page_number);
CREATE INDEX totals_parse_metric ON statement_total_candidates(parse_id,metric);
CREATE VIEW v_latest_structured_run AS
 SELECT parse_id,job_id FROM (
  SELECT r.*, row_number() OVER(PARTITION BY job_id ORDER BY created_at DESC,rowid DESC) AS n
  FROM structured_runs r WHERE status='complete'
 ) WHERE n=1;
CREATE VIEW v_settlement_review AS
 SELECT d.original_filename,d.document_id,d.job_id,s.*,
 (SELECT count(*) FROM settlement_posting_candidates p WHERE p.parse_id=s.parse_id) AS posting_rows,
 (SELECT count(*) FROM load_leg_candidates l WHERE l.parse_id=s.parse_id) AS load_leg_rows,
 (SELECT count(*) FROM reconciliation_checks c WHERE c.parse_id=s.parse_id AND status='mismatch') AS mismatched_checks,
 (SELECT count(*) FROM reconciliation_checks c WHERE c.parse_id=s.parse_id AND status='incomplete') AS incomplete_checks,
 (SELECT count(*) FROM structured_issues i WHERE i.parse_id=s.parse_id) AS review_issues
 FROM v_latest_document_extraction d
 JOIN v_latest_structured_run r ON r.job_id=d.job_id
 JOIN statement_candidates s USING(parse_id)
 WHERE d.job_status='complete';
CREATE VIEW v_candidate_transactions AS
 SELECT s.original_filename,s.settlement_date,s.owner_code,s.unit_code,l.page_number,l.line_number,p.*
 FROM v_settlement_review s JOIN settlement_posting_candidates p USING(parse_id)
 JOIN source_line_candidates l ON l.line_id=p.posting_id;
CREATE VIEW v_candidate_loads AS
 SELECT s.original_filename,s.settlement_date,s.owner_code,s.unit_code,l.*
 FROM v_settlement_review s JOIN load_leg_candidates l USING(parse_id);
CREATE VIEW v_parse_checks AS
 SELECT s.original_filename,s.settlement_date,c.*
 FROM v_settlement_review s JOIN reconciliation_checks c USING(parse_id);
CREATE VIEW v_candidate_operating_measures AS
 SELECT s.original_filename,s.settlement_date,s.owner_code,s.unit_code,m.*
 FROM v_settlement_review s JOIN operating_measure_candidates m USING(parse_id);
