# 효진유통 업무 관리 시스템

PlayAuto 업무 자동화 통합 플랫폼 - 주문 관리, 출퇴근 기록, 급여 계산

---

## 🎯 주요 기능

### 1️⃣ 송장 분류 시스템
- 주문 엑셀을 담당자별로 자동 분류
- 설정 파일 기반 상품 매칭 규칙
- 합배송, 복수주문 자동 감지
- 분류 실패 건 별도 관리
- 드래그 앤 드롭 파일 업로드

### 2️⃣ 스타배송 필터
- "판매자 스타배송"으로 시작하는 행 자동 삭제
- 실시간 통계 표시
- 드래그 앤 드롭 지원

### 3️⃣ 원가 마진표 관리
- 상품별 원가, 판매가, 마진율 추적
- 프로모션 가격 관리
- CRUD 작업 지원 (생성, 조회, 수정, 삭제)
- 담당자별 상품 배정

### 4️⃣ 출퇴근 일지
- 직원 출퇴근 시간 기록
- 휴가 및 결근 관리
- 근무 시간 자동 계산
- 일일 예상 지급액 표시
- 출퇴근 수정 요청 기능

### 5️⃣ 급여 계산
- 시급 기반 급여 자동 계산
- 근무 시간, 주휴수당 반영
- 공제액 관리 (식비, 세금 등)
- 월별 급여 집계
- 급여 확정 및 이력 관리

### 6️⃣ 면세 자료 정리
- 쿠팡 판매 리포트에서 면세 자료 추출
- 엑셀 파일 자동 처리
- 정리된 데이터 다운로드

---

## 🛠 기술 스택

### Backend
- **Flask 3.0** - Python 웹 프레임워크
- **Python 3.11** - 주요 개발 언어
- **Pandas 2.0+** - 데이터 처리 및 Excel/CSV 조작
- **OpenPyXL 3.1+** - XLSX 파일 읽기/쓰기
- **xlrd 2.0+** - XLS 파일 읽기
- **NumPy 1.21+** - 수치 연산

### Database
- **Supabase 2.0+** - 클라우드 PostgreSQL 데이터베이스
- JSON 파일 백업 모드 지원 (DB 미사용 시)

### Frontend
- **Vanilla JavaScript** - 프레임워크 없이 순수 JS
- **HTML5 + CSS3** - 다크 테마 UI
- 드래그 앤 드롭 파일 업로드
- 실시간 진행률 표시
- 모바일 반응형 디자인

### 배포 및 운영
- **Gunicorn 21.2** - 프로덕션 WSGI HTTP 서버
- **Render** - 클라우드 호스팅 플랫폼
- **UptimeRobot** - 무료 모니터링 (5분 간격)

---

## 🚀 빠른 시작

### 로컬 실행

```bash
# 의존성 설치
pip install -r requirements.txt

# 환경 변수 설정 (선택사항)
# .env 파일 생성 또는 환경 변수 직접 설정
export ADMIN_ID=admin
export ADMIN_PASSWORD=yourpassword

# 서버 실행
python app.py

# 브라우저에서 열기
# http://localhost:5000
```

### 프로덕션 실행

```bash
gunicorn app:app --bind 0.0.0.0:5000
```

---

## 📂 프로젝트 구조

```
hyojin/
├── app.py                          # Flask 메인 애플리케이션 (2,083줄)
├── requirements.txt                # Python 의존성
├── render.yaml                     # Render 배포 설정
├── playauto_settings_v4.json      # 송장 분류 설정 파일
├── margin_data.json               # 원가 마진 데이터
├── README.md                       # 프로젝트 문서
├── templates/
│   ├── index.html                 # 관리자 대시보드
│   ├── login.html                 # 로그인 페이지
│   └── parttime.html              # 직원 출퇴근 페이지
└── static/
    └── (CSS/JS 파일들)
```

---

## 🔑 주요 엔드포인트

### 인증
- `GET /login` - 로그인 페이지
- `POST /login` - 로그인 처리
- `GET /logout` - 로그아웃
- `GET /api/session` - 세션 정보 조회

### 대시보드
- `GET /` - 관리자 대시보드 (메인 페이지)
- `GET /parttime` - 직원 출퇴근 페이지

### 송장 분류
- `POST /upload` - 설정 파일 업로드
- `POST /classify` - 주문 분류 실행
- `GET /download/<session_id>` - 분류된 파일 다운로드

### 원가 마진표
- `GET /api/margin` - 전체 데이터 조회
- `POST /api/margin` - 데이터 생성
- `PUT /api/margin/<id>` - 데이터 수정
- `DELETE /api/margin/<id>` - 데이터 삭제
- `GET /api/workers/<id>/products` - 담당자별 상품 조회

### 직원 관리
- `GET /api/employees` - 직원 목록 조회
- `POST /api/employees` - 직원 추가
- `PUT /api/employees/<id>` - 직원 정보 수정
- `DELETE /api/employees/<id>` - 직원 삭제

### 휴가 관리
- `GET /api/holidays` - 휴가 목록 조회
- `POST /api/holidays` - 휴가 추가
- `DELETE /api/holidays/<id>` - 휴가 삭제

### 출퇴근 기록
- `GET /api/attendance` - 출퇴근 기록 조회
- `POST /api/attendance` - 출퇴근 기록 (체크인/체크아웃)
- `POST /api/attendance-edit-request` - 출퇴근 시간 수정 요청

### 급여 계산
- `POST /api/salary/calculate` - 급여 계산
- `POST /api/salary/confirm` - 급여 확정
- `GET /api/salary/history` - 급여 이력 조회

### 면세 자료
- `POST /api/tax-free/process` - 면세 자료 처리
- `GET /api/tax-free/download` - 처리된 파일 다운로드

### 모니터링
- `GET /health` - 헬스 체크 (UptimeRobot용)

---

## ⚙️ 설정 파일

### playauto_settings_v4.json

담당자별 상품 분류 규칙을 정의합니다.

```json
{
  "work_order": [
    "송과장님",
    "영재씨",
    "강민씨",
    "부모님",
    "합배송",
    "복수주문",
    "분류실패"
  ],
  "work_config": {
    "송과장님": {
      "products": [
        {
          "brand": "꽃샘",
          "product_name": "밤 티라미수",
          "order_option": "All"
        }
      ]
    },
    "영재씨": {
      "products": [
        {
          "brand": "브랜드명",
          "product_name": "상품명",
          "order_option": "옵션명"
        }
      ]
    }
  }
}
```

### margin_data.json

원가 및 마진 정보를 저장합니다.

```json
{
  "data": [
    {
      "id": 1,
      "worker": "송과장님",
      "brand": "꽃샘",
      "product_name": "밤 티라미수",
      "cost": 5000,
      "sale_price": 7000,
      "margin": 2000,
      "margin_rate": 28.57,
      "promotion_price": 6500
    }
  ]
}
```

---

## 🔐 인증 시스템

### 이중 인증 모드

1. **환경 변수 기반 관리자 계정**
   - `ADMIN_ID` 및 `ADMIN_PASSWORD` 환경 변수 사용
   - 빠른 관리자 로그인용

2. **데이터베이스 기반 사용자 계정**
   - Supabase `users` 테이블 사용
   - 역할 기반 접근 제어 (admin, parttime)
   - 일반 직원 계정용

### 역할 권한

- **admin**: 전체 기능 접근 가능 (관리자 대시보드)
- **parttime**: 출퇴근 기록만 가능 (직원 페이지)

---

## 📊 데이터 저장 방식

### 이중 저장 모드

1. **Supabase 모드** (기본)
   - PostgreSQL 데이터베이스 사용
   - 실시간 동기화
   - 다중 사용자 지원

2. **JSON 파일 모드** (백업)
   - Supabase 미사용 시 자동 전환
   - 로컬 파일 시스템 사용
   - 단일 사용자 환경용

---

## 🚢 Render 배포 가이드

### 1단계: GitHub 레포지토리 준비

```bash
git init
git add .
git commit -m "Initial commit: 효진유통 업무 관리 시스템"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/hyojin.git
git push -u origin main
```

### 2단계: Render 설정

1. [render.com](https://render.com) 가입 (GitHub 연동)
2. Dashboard → **New +** → **Web Service**
3. GitHub 레포지토리 연결
4. 설정값 입력:
   - **Name**: `hyojin-distribution`
   - **Runtime**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
5. 환경 변수 추가 (선택사항):
   - `ADMIN_ID`: 관리자 아이디
   - `ADMIN_PASSWORD`: 관리자 비밀번호
   - `SUPABASE_URL`: Supabase 프로젝트 URL
   - `SUPABASE_KEY`: Supabase API 키
6. **Create Web Service** 클릭

배포 완료 후 URL: `https://hyojin-distribution.onrender.com`

---

## ⏰ 24시간 가동 설정 (UptimeRobot)

Render 무료 플랜은 15분 비활성 시 슬립 모드로 전환됩니다. UptimeRobot으로 자동 깨우기:

1. [uptimerobot.com](https://uptimerobot.com) 가입 (무료)
2. **Add New Monitor** 클릭
3. 설정:
   - **Monitor Type**: HTTP(s)
   - **Friendly Name**: 효진유통 시스템
   - **URL**: `https://YOUR-APP.onrender.com/health`
   - **Monitoring Interval**: 5분
4. **Create Monitor** 저장

---

## 💰 비용 구조

| 서비스           | 플랜      | 비용   |
| ---------------- | --------- | ------ |
| Render           | 무료 티어 | $0     |
| Supabase         | 무료 티어 | $0     |
| UptimeRobot      | 무료 플랜 | $0     |
| **총 운영 비용** |           | **$0** |

---

## 🎨 UI/UX 특징

- **다크 테마** - 눈의 피로 감소
- **네온 컬러 강조** - 주요 버튼 및 상태 표시
- **드래그 앤 드롭** - 파일 업로드 간편화
- **실시간 진행률** - 작업 진행 상황 표시
- **모바일 반응형** - 스마트폰에서도 사용 가능
- **탭 기반 네비게이션** - 기능별 구분된 인터페이스

---

## 📋 송장 분류 알고리즘

`OrderClassifierV41` 클래스는 다음 우선순위로 주문을 분류합니다:

1. **합배송 감지** - 동일 주문번호에 여러 상품
2. **복수주문 감지** - 동일 상품 수량 2개 이상
3. **상품명 매칭** - 설정 파일의 규칙 기반
4. **분류 실패** - 매칭되지 않은 주문

### 처리 플로우

```
주문 파일 업로드
    ↓
설정 파일 로드
    ↓
주문번호별 그룹화
    ↓
우선순위 규칙 적용
    ↓
담당자별 시트 생성
    ↓
엑셀 파일 다운로드
```

---

## 🧪 급여 계산 로직

### 계산 공식

```python
# 기본 급여
총 근무시간 = 출근일수 × 일일 근무시간
기본급여 = 총 근무시간 × 시급

# 주휴수당 (주 15시간 이상 근무 시)
주휴수당 = (총 근무시간 / 40시간) × 8시간 × 시급

# 공제액
총 공제액 = 식비 + 세금 + 기타 공제

# 최종 지급액
실수령액 = 기본급여 + 주휴수당 - 총 공제액
```

---

## 📖 사용 가이드

### 송장 분류 사용법

1. 관리자 로그인
2. "송장 분류" 탭 선택
3. `playauto_settings_v4.json` 업로드 (최초 1회)
4. 주문 엑셀 파일 드래그 앤 드롭
5. "분류 시작" 버튼 클릭
6. 완료 후 "다운로드" 버튼으로 결과 저장

### 출퇴근 기록 사용법

1. 직원 계정 로그인
2. "출근" 버튼 클릭 (근무 시작 시)
3. "퇴근" 버튼 클릭 (근무 종료 시)
4. 시간 수정 필요 시 "수정 요청" 기능 사용

### 급여 계산 사용법

1. 관리자 로그인
2. "급여 계산" 탭 선택
3. 조회 기간 설정 (월별)
4. "급여 계산" 버튼 클릭
5. 내역 확인 후 "급여 확정" 클릭
6. 확정된 급여는 이력에서 조회 가능

---

## 🐛 문제 해결

### 파일 업로드 실패
- 파일 형식 확인 (xlsx, xls, csv 지원)
- 파일 크기 제한 확인 (최대 16MB)
- 필수 컬럼 존재 여부 확인

### 분류 실패 건 과다
- `playauto_settings_v4.json` 설정 재확인
- 상품명, 브랜드명 정확히 입력
- 특수문자 및 공백 일치 여부 확인

### 로그인 불가
- 환경 변수 설정 확인
- Supabase 연결 상태 확인
- 계정 role 권한 확인

### Render 슬립 모드
- UptimeRobot 모니터링 설정 확인
- `/health` 엔드포인트 응답 확인
- 모니터링 간격 5분 유지

---

## 📝 업데이트 로그

### v4.1 (2025-01-17)
- 면세 자료 정리 기능 에러 수정
- 관리자 화면 출퇴근일지 예상지급액 오류 해결

### v4.0 (2024-12-XX)
- 면세 자료 정리 기능 추가
- 출퇴근일지 시스템 통합
- 급여 계산 모듈 구현
- 원가 마진표 관리 기능

### v1.0 (2024-12-16)
- 스타배송 필터 기능
- 송장 분류 시스템 통합
- 웹 UI 구현
- Render 배포 설정

---

## 📄 라이선스

Private Use Only - 효진유통 내부 사용

---

## 👨‍💻 개발자

PlayAuto Team

---

## 🙏 기여

현재 내부 프로젝트로 외부 기여를 받지 않습니다.
