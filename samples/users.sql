-- Sample SQL dump: single-table INSERT statements.
-- Phase 3 target format (not yet parsed by the Phase 1 MVP).

CREATE TABLE IF NOT EXISTS users (
  user_id       VARCHAR(16) PRIMARY KEY,
  email         VARCHAR(255) NOT NULL,
  phone         VARCHAR(32),
  full_name     VARCHAR(128),
  date_of_birth DATE,
  zip_code      VARCHAR(16),
  signup_date   DATE,
  plan          VARCHAR(16)
);

INSERT INTO users (user_id, email, phone, full_name, date_of_birth, zip_code, signup_date, plan) VALUES
  ('U000001', 'alice.johnson@acme.example', '+14155552671', 'Alice Johnson', '1990-03-14', '94103', '2024-06-01', 'pro'),
  ('U000002', 'bob.smith@acme.example',     '+14155552672', 'Bob Smith',     '1985-07-22', '94103', '2024-07-15', 'free'),
  ('U000003', 'carol.davis@acme.example',   '+14155552673', 'Carol Davis',   '1992-11-05', '94103', '2024-08-10', 'pro'),
  ('U000004', 'david.lee@acme.example',     '+14155552674', 'David Lee',     '1988-01-30', '94103', '2024-09-20', 'enterprise'),
  ('U000005', 'eve.martinez@acme.example',  '+14155552675', 'Eve Martinez',  '1995-06-18', '94103', '2024-10-07', 'free'),
  ('U000006', 'frank.turner@acme.example',  '+14155552676', 'Frank Turner',  '1980-09-12', '94107', '2024-11-14', 'pro'),
  ('U000007', 'grace.park@acme.example',    '+14155552677', 'Grace Park',    '1987-12-02', '94107', '2024-12-19', 'free'),
  ('U000008', 'henry.wilson@acme.example',  '+14155552678', 'Henry Wilson',  '1991-04-25', '94107', '2025-01-11', 'pro'),
  ('U000009', 'irene.chen@acme.example',    '+14155552679', 'Irene Chen',    '1983-10-08', '94107', '2025-02-03', 'enterprise'),
  ('U000010', 'jack.brown@acme.example',    '+14155552680', 'Jack Brown',    '1993-02-14', '94107', '2025-03-22', 'free');
