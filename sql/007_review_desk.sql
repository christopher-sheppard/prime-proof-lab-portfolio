CREATE TABLE desk_applied_changes (
 decision_id TEXT PRIMARY KEY,
 record_id TEXT NOT NULL,
 expected_revision TEXT NOT NULL,
 action TEXT NOT NULL,
 proposed_json TEXT NOT NULL,
 validation_json TEXT NOT NULL,
 created_at TEXT NOT NULL
);
CREATE INDEX desk_changes_record ON desk_applied_changes(record_id,created_at);
CREATE TABLE desk_classification_versions (
 decision_id TEXT PRIMARY KEY REFERENCES desk_applied_changes(decision_id),
 record_id TEXT NOT NULL,
 document_id TEXT NOT NULL REFERENCES source_documents(document_id),
 page_number INTEGER,
 category TEXT NOT NULL,
 disposition TEXT NOT NULL CHECK(disposition IN ('confirmed','rejected')),
 evidence TEXT NOT NULL
);
CREATE TABLE desk_facility_mapping_versions (
 decision_id TEXT PRIMARY KEY REFERENCES desk_applied_changes(decision_id),
 record_id TEXT NOT NULL,
 document_id TEXT NOT NULL REFERENCES source_documents(document_id),
 organization_id TEXT NOT NULL REFERENCES organizations(organization_id),
 facility_id TEXT NOT NULL REFERENCES facilities(facility_id),
 role TEXT NOT NULL CHECK(role IN ('shipper','receiver','bill_to','vendor','other')),
 raw_code TEXT,
 evidence TEXT NOT NULL
);
CREATE TRIGGER desk_changes_no_update BEFORE UPDATE ON desk_applied_changes
 BEGIN SELECT RAISE(ABORT,'Applied decisions are append-only'); END;
CREATE TRIGGER desk_changes_no_delete BEFORE DELETE ON desk_applied_changes
 BEGIN SELECT RAISE(ABORT,'Applied decisions are append-only'); END;
