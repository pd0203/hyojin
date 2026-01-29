-- =============================================
-- 효진유통 시스템 - 전체 스키마 (신규 데이터베이스 구축 / 초기화 후 복구시에 사용할 용도)
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
    scheduled_days TEXT DEFAULT '1,2,3,4,5', -- 소정근로일 (0=일,1=월,2=화,3=수,4=목,5=금,6=토)
    enabled BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 기존 테이블에 scheduled_days 컬럼 추가 (이미 테이블이 있는 경우)
-- ALTER TABLE users ADD COLUMN IF NOT EXISTS scheduled_days TEXT DEFAULT '1,2,3,4,5';

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

-- 7. 출퇴근 수정 요청 테이블
CREATE TABLE IF NOT EXISTS attendance_edit_requests (
    id SERIAL PRIMARY KEY,
    employee_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    request_date DATE NOT NULL,           -- 수정 요청하는 날짜
    old_clock_in TIME,                    -- 기존 출근 시간
    old_clock_out TIME,                   -- 기존 퇴근 시간
    new_clock_in TIME,                    -- 수정 요청 출근 시간
    new_clock_out TIME,                   -- 수정 요청 퇴근 시간
    reason TEXT NOT NULL,                 -- 수정 사유
    status TEXT DEFAULT 'pending',        -- pending, approved, rejected
    reject_reason TEXT,                   -- 거절 사유 (거절 시)
    viewed_rejection BOOLEAN DEFAULT false, -- 직원이 거절 사유 확인 여부
    created_at TIMESTAMPTZ DEFAULT NOW(),
    processed_at TIMESTAMPTZ,             -- 처리 일시
    UNIQUE(employee_id, request_date, status)
);

-- 8. 메모장 테이블 (관리자용)
CREATE TABLE IF NOT EXISTS memos (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    content TEXT,
    is_pinned BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 9. 품절상품 테이블
CREATE TABLE IF NOT EXISTS out_of_stock (
    id SERIAL PRIMARY KEY,
    product_name TEXT NOT NULL,
    out_date DATE NOT NULL,
    restock_date DATE,
    notes TEXT,
    is_restocked BOOLEAN DEFAULT false,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 도착보장 상품 마스터 테이블
CREATE TABLE IF NOT EXISTS arrival_guarantee_products (
    id SERIAL PRIMARY KEY,
    product_name TEXT NOT NULL,
    barcode TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 시스템 설정 테이블 (고객ID 등 저장용)
CREATE TABLE IF NOT EXISTS system_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 인덱스
CREATE INDEX IF NOT EXISTS idx_arrival_products_name ON arrival_guarantee_products(product_name);

-- RLS 정책
ALTER TABLE arrival_guarantee_products ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_settings ENABLE ROW LEVEL SECURITY;

CREATE POLICY "Allow all for arrival_guarantee_products" ON arrival_guarantee_products FOR ALL USING (true);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_attendance_employee_date ON attendance_logs(employee_id, work_date);
CREATE INDEX IF NOT EXISTS idx_attendance_work_date ON attendance_logs(work_date);
CREATE INDEX IF NOT EXISTS idx_holidays_date ON holidays(holiday_date);
CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
CREATE INDEX IF NOT EXISTS idx_users_enabled ON users(enabled);
CREATE INDEX IF NOT EXISTS idx_edit_approvals_employee ON edit_approvals(employee_id);
CREATE INDEX IF NOT EXISTS idx_salary_confirmations_employee ON salary_confirmations(employee_id);
CREATE INDEX IF NOT EXISTS idx_wage_history_employee ON wage_history(employee_id);
CREATE INDEX IF NOT EXISTS idx_edit_requests_employee ON attendance_edit_requests(employee_id);
CREATE INDEX IF NOT EXISTS idx_edit_requests_status ON attendance_edit_requests(status);

-- RLS 정책
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE attendance_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE holidays ENABLE ROW LEVEL SECURITY;
ALTER TABLE edit_approvals ENABLE ROW LEVEL SECURITY;
ALTER TABLE salary_confirmations ENABLE ROW LEVEL SECURITY;
ALTER TABLE wage_history ENABLE ROW LEVEL SECURITY;
ALTER TABLE attendance_edit_requests ENABLE ROW LEVEL SECURITY;

-- 모든 접근 허용 (service_role key 사용)
DROP POLICY IF EXISTS "Allow all for users" ON users;
DROP POLICY IF EXISTS "Allow all for attendance_logs" ON attendance_logs;
DROP POLICY IF EXISTS "Allow all for holidays" ON holidays;
DROP POLICY IF EXISTS "Allow all for edit_approvals" ON edit_approvals;
DROP POLICY IF EXISTS "Allow all for salary_confirmations" ON salary_confirmations;
DROP POLICY IF EXISTS "Allow all for wage_history" ON wage_history;
DROP POLICY IF EXISTS "Allow all for attendance_edit_requests" ON attendance_edit_requests;

CREATE POLICY "Allow all for users" ON users FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for attendance_logs" ON attendance_logs FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for holidays" ON holidays FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for edit_approvals" ON edit_approvals FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for salary_confirmations" ON salary_confirmations FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for wage_history" ON wage_history FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all for attendance_edit_requests" ON attendance_edit_requests FOR ALL USING (true) WITH CHECK (true);

-- =============================================
-- 박스 재고 관리 테이블
-- =============================================

CREATE TABLE IF NOT EXISTS box_inventory (
    id SERIAL PRIMARY KEY,
    name_cj TEXT,                    -- 박스명(CJ)
    name_box4u TEXT,                 -- 박스명(박스포유)
    name_official TEXT,              -- 박스명(기타)
    spec TEXT,                       -- 박스규격 (예: 300x200x100)
    material TEXT,                   -- 재질 (예: A골, B골)
    strength TEXT,                   -- 강도 (예: 강함, 보통)
    print_type TEXT DEFAULT '무지',   -- 인쇄 (무지/취급주의/로고)
    price INTEGER DEFAULT 0,         -- 단가
    vendor TEXT DEFAULT 'CJ',        -- 구매처 (CJ/박스포유/기타)
    moq_pallet INTEGER DEFAULT 0,    -- MOQ(팔레트)
    moq_piece INTEGER DEFAULT 0,     -- MOQ(낱개)
    stock_cj NUMERIC(6,1) DEFAULT 0, -- 재고(CJ창고) - 소수점 1자리
    stock_hyojin NUMERIC(6,1) DEFAULT 0, -- 재고(효진유통) - 소수점 1자리
    purpose TEXT,                    -- 박스 용도
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 박스 재고 인덱스
CREATE INDEX IF NOT EXISTS idx_box_inventory_name_cj ON box_inventory(name_cj);
CREATE INDEX IF NOT EXISTS idx_box_inventory_vendor ON box_inventory(vendor);

-- 박스 재고 RLS 정책
ALTER TABLE box_inventory ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow all for box_inventory" ON box_inventory;
CREATE POLICY "Allow all for box_inventory" ON box_inventory FOR ALL USING (true) WITH CHECK (true);

-- =============================================
-- 데이터 분석 테이블
-- =============================================

-- 10. 고객 테이블
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    휴대폰번호 TEXT UNIQUE NOT NULL,
    구매자명 TEXT,
    구매자ID TEXT,
    첫구매일 TIMESTAMPTZ,
    최근구매일 TIMESTAMPTZ,
    총주문횟수 INTEGER DEFAULT 0,
    총구매금액 DECIMAL(15,2) DEFAULT 0,
    선물발송횟수 INTEGER DEFAULT 0,
    주요배송지 TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_customers_휴대폰번호 ON customers(휴대폰번호);
CREATE INDEX IF NOT EXISTS idx_customers_총주문횟수 ON customers(총주문횟수);

ALTER TABLE customers ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow all for customers" ON customers;
CREATE POLICY "Allow all for customers" ON customers FOR ALL USING (true) WITH CHECK (true);

-- 11. 판매 데이터 테이블
CREATE TABLE IF NOT EXISTS sales_data (
    id SERIAL PRIMARY KEY,
    판매사이트명 TEXT,
    수집일 DATE,
    주문일 TIMESTAMPTZ,
    결제일 TIMESTAMPTZ,
    상품명 TEXT,
    주문선택사항 TEXT,
    판매가 DECIMAL(12,2) DEFAULT 0,
    주문수량 INTEGER DEFAULT 1,
    배송비금액 DECIMAL(10,2) DEFAULT 0,
    구매자ID TEXT,
    구매자명 TEXT,
    구매자휴대폰번호 TEXT,
    수령자명 TEXT,
    수령자휴대폰번호 TEXT,
    배송지주소 TEXT,
    주문번호 TEXT,
    원가 DECIMAL(12,2) DEFAULT 0,
    수수료 DECIMAL(12,2) DEFAULT 0,
    순이익 DECIMAL(12,2) DEFAULT 0,
    is_gift BOOLEAN DEFAULT FALSE,
    is_repeat_customer BOOLEAN DEFAULT FALSE,
    customer_id INTEGER REFERENCES customers(id),
    upload_batch_id TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sales_data_주문일 ON sales_data(주문일);
CREATE INDEX IF NOT EXISTS idx_sales_data_판매사이트명 ON sales_data(판매사이트명);
CREATE INDEX IF NOT EXISTS idx_sales_data_주문번호 ON sales_data(주문번호);
CREATE INDEX IF NOT EXISTS idx_sales_data_상품명 ON sales_data(상품명);
CREATE INDEX IF NOT EXISTS idx_sales_data_customer_id ON sales_data(customer_id);

ALTER TABLE sales_data ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Allow all for sales_data" ON sales_data;
CREATE POLICY "Allow all for sales_data" ON sales_data FOR ALL USING (true) WITH CHECK (true);

-- 주문번호 컬럼 추가
ALTER TABLE sales_data ADD COLUMN IF NOT EXISTS 주문번호 TEXT;

-- 인덱스 추가 (중복 체크 성능 향상)
CREATE INDEX IF NOT EXISTS idx_sales_data_주문번호 ON sales_data(주문번호);
