-- =============================================
-- 출퇴근 수정 요청 테이블 추가 마이그레이션
-- 기존 DB에 이 테이블만 추가할 때 사용
-- =============================================

-- 출퇴근 수정 요청 테이블
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
    processed_at TIMESTAMPTZ              -- 처리 일시
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_edit_requests_employee ON attendance_edit_requests(employee_id);
CREATE INDEX IF NOT EXISTS idx_edit_requests_status ON attendance_edit_requests(status);

-- RLS 활성화
ALTER TABLE attendance_edit_requests ENABLE ROW LEVEL SECURITY;

-- 모든 접근 허용 정책
DROP POLICY IF EXISTS "Allow all for attendance_edit_requests" ON attendance_edit_requests;
CREATE POLICY "Allow all for attendance_edit_requests" ON attendance_edit_requests FOR ALL USING (true) WITH CHECK (true);
