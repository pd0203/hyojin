# CLAUDE.md

이 프로젝트는 한국어 기반 업무 자동화 웹앱 (Flask)입니다.

## 작업 규칙

### 코드 스타일
- 커밋 메시지: 한국어로 작성 (예: "기능 추가: 박스 재고 관리")
- 주석/변수명: 기존 코드 스타일 유지 (영어 변수명, 한국어 주석 혼용)
- API 응답: 항상 `{"success": true/false}` 또는 `{"error": "메시지"}` 형식 유지

### 시간 처리
- 모든 시간은 KST (UTC+9) 기준
- `get_kst_today()` 함수 사용할 것

### 새 API 엔드포인트 추가 시
- `@login_required` 또는 `@admin_required` 데코레이터 필수
- app.py 내 기존 패턴 따를 것

## 절대 하지 말 것

- `margin_data.json`, `playauto_settings_v4.json` 직접 수정 금지 → API 통해 수정
- 환경변수 (SECRET_KEY, SUPABASE_KEY 등) 코드에 하드코딩 금지
- `templates/*.html` 파일의 기존 JavaScript 로직 임의 변경 금지

## 자주 쓰는 명령어

```bash
# 로컬 실행
python app.py

# 의존성 설치
pip install -r requirements.txt

# 서버: http://localhost:5000
```

## 프로젝트 구조 (참고용)

- `app.py`: 메인 Flask 앱 (모든 라우트 포함)
- `templates/index.html`: 메인 UI
- `templates/parttime.html`: 알바 전용 출퇴근 인터페이스
- `schema_attendance.sql`: Supabase 테이블 스키마

## 데이터베이스

- Supabase 사용 (환경변수 없으면 JSON 파일 모드로 폴백)
- JSON 파일들: `margin_data.json`, `playauto_settings_v4.json`
