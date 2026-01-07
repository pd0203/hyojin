-- =============================================
-- 효진유통 시스템 - 출퇴근 관리 스키마
-- 기존 schema.sql 실행 후 이 파일 실행
-- =============================================

-- 1. 사용자 테이블 (관리자 + 알바생)
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password TEXT NOT NULL,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'parttime',  -- 'admin' or 'parttime'
    hourly_wage INTEGER DEFAULT 10700,       -- 시급 (알바생용)
    full_attendance_bonus INTEGER DEFAULT 100000,  -- 만근수당
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. 출퇴근 기록 테이블
CREATE TABLE IF NOT EXISTS attendance_logs (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    work_date DATE NOT NULL,
    clock_in TIME,
    clock_out TIME,
    is_holiday_work BOOLEAN DEFAULT false,  -- 공휴일/주말 근무 여부
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(employee_id, work_date)
);

-- 3. 공휴일 테이블
CREATE TABLE IF NOT EXISTS holidays (
    id SERIAL PRIMARY KEY,
    holiday_date DATE UNIQUE NOT NULL,
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 4. 수정 승인 테이블 (특정 날짜별)
CREATE TABLE IF NOT EXISTS edit_approvals (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    approved_date DATE NOT NULL,
    used BOOLEAN DEFAULT false,  -- 사용 여부 (한번 수정하면 true)
    approved_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(employee_id, approved_date)
);

-- 5. 월급 확정 테이블
CREATE TABLE IF NOT EXISTS salary_confirmations (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    year_month TEXT NOT NULL,  -- '2025-01' 형식
    total_hours NUMERIC,
    base_pay INTEGER,
    overtime_pay INTEGER,
    weekly_holiday_pay INTEGER,
    full_attendance_bonus INTEGER,
    total_amount INTEGER,
    confirmed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(employee_id, year_month)
);

-- 6. 시급 변경 이력 테이블 (시급 변경 추적용)
CREATE TABLE IF NOT EXISTS wage_history (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    hourly_wage INTEGER NOT NULL,
    effective_date DATE NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_attendance_employee_date ON attendance_logs(employee_id, work_date);
CREATE INDEX IF NOT EXISTS idx_attendance_work_date ON attendance_logs(work_date);
CREATE INDEX IF NOT EXISTS idx_holidays_date ON holidays(holiday_date);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_enabled ON users(enabled);
CREATE INDEX IF NOT EXISTS idx_edit_approvals_employee ON edit_approvals(employee_id);
CREATE INDEX IF NOT EXISTS idx_salary_confirmations_employee ON salary_confirmations(employee_id);
CREATE INDEX IF NOT EXISTS idx_wage_history_employee ON wage_history(employee_id);

-- RLS 정책
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE attendance_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE holidays ENABLE ROW LEVEL SECURITY;
ALTER TABLE edit_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE salary_confirmations ENABLE ROW LEVEL SECURITY;
ALTER TABLE wage_history ENABLE ROW LEVEL SECURITY;

-- 모든 접근 허용 (service_role key 사용)
DROP POLICY IF EXISTS "Allow all for users" ON users;
DROP POLICY IF EXISTS "Allow all for attendance_logs" ON attendance_logs;
DROP POLICY IF EXISTS "Allow all for holidays" ON holidays;
DROP POLICY IF EXISTS "Allow all for edit_approvals" ON edit_approvals;
DROP POLICY IF EXISTS "Allow all for salary_confirmations" ON salary_confirmations;
DROP POLICY IF EXISTS "Allow all for wage_history" ON wage_history;

CREATE POLICY "Allow all for users" ON users FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for attendance_logs" ON attendance_logs FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for holidays" ON holidays FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for edit_approvals" ON edit_approvals FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for salary_confirmations" ON salary_confirmations FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for wage_history" ON wage_history FOR ALL USING (true) WITH CHECK (true);

-- 초기 관리자 계정 생성 (환경변수의 ADMIN_ID, ADMIN_PW 사용)
-- 실제 배포 시 migrate 스크립트에서 처리
