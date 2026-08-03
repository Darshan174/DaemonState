-- Promote the production waitlist from its original email-only shape to a
-- versioned lifecycle record. The first CREATE preserves compatibility with
-- databases initialized by the previous request-time bootstrap.
CREATE TABLE IF NOT EXISTS waitlist_signups (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  source TEXT NOT NULL DEFAULT 'landing',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE waitlist_signups_v2 (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE COLLATE NOCASE,
  name TEXT,
  role TEXT,
  company TEXT,
  team_size TEXT,
  primary_tools TEXT,
  main_problem TEXT,
  source TEXT NOT NULL DEFAULT 'landing',
  referrer TEXT,
  utm_source TEXT,
  utm_medium TEXT,
  utm_campaign TEXT,
  utm_term TEXT,
  utm_content TEXT,
  status TEXT NOT NULL DEFAULT 'new'
    CHECK (status IN (
      'new',
      'qualified',
      'interview_requested',
      'invited',
      'activated',
      'feedback_received',
      'converted',
      'archived'
    )),
  priority_score INTEGER NOT NULL DEFAULT 0
    CHECK (priority_score BETWEEN 0 AND 100),
  notes TEXT,
  consent_at TEXT,
  consent_version TEXT,
  invited_at TEXT,
  activated_at TEXT,
  last_contacted_at TEXT,
  email_sync_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (email_sync_status IN ('pending', 'synced', 'failed')),
  email_synced_at TEXT,
  email_sync_error TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

INSERT INTO waitlist_signups_v2 (
  id,
  email,
  source,
  created_at,
  updated_at
)
SELECT
  id,
  lower(trim(email)),
  source,
  created_at,
  created_at
FROM waitlist_signups;

DROP TABLE waitlist_signups;
ALTER TABLE waitlist_signups_v2 RENAME TO waitlist_signups;

CREATE INDEX ix_waitlist_signups_created_at
  ON waitlist_signups (created_at);
CREATE INDEX ix_waitlist_signups_status_created_at
  ON waitlist_signups (status, created_at);
CREATE INDEX ix_waitlist_signups_email_sync_status
  ON waitlist_signups (email_sync_status, created_at);
