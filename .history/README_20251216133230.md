# Excel 스타배송 필터 웹앱

"판매자 스타배송"으로 시작하는 행을 자동 삭제하는 웹앱

## 🚀 Render 배포 (무료)

### 1. GitHub 레포지토리 생성
```bash
git init
git add .
git commit -m "Initial commit"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/excel-filter.git
git push -u origin main
```

### 2. Render 배포
1. [render.com](https://render.com) 가입 (GitHub 연동)
2. Dashboard → **New +** → **Web Service**
3. GitHub 레포 연결
4. 설정:
   - **Name**: `excel-filter` (원하는 이름)
   - **Runtime**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn app:app`
5. **Create Web Service** 클릭

배포 완료 후 URL: `https://excel-filter.onrender.com`

---

## ⏰ UptimeRobot 설정 (24시간 유지)

Render 무료 티어는 15분 무활동 시 슬립 → UptimeRobot으로 해결

1. [uptimerobot.com](https://uptimerobot.com) 가입
2. **Add New Monitor**
3. 설정:
   - **Monitor Type**: HTTP(s)
   - **Friendly Name**: Excel Filter
   - **URL**: `https://YOUR-APP.onrender.com/health`
   - **Monitoring Interval**: 5 minutes
4. **Create Monitor**

---

## 💾 데이터베이스

**불필요!** 이 앱은 파일을 업로드 → 처리 → 즉시 반환하므로 저장할 데이터가 없음.

---

## 💰 비용

| 서비스 | 요금 |
|--------|------|
| Render 무료 티어 | $0 |
| UptimeRobot 무료 | $0 |
| **총 비용** | **$0** |

---

## 📁 파일 구조

```
excel-filter-web/
├── app.py              # Flask 서버
├── requirements.txt    # 의존성
├── render.yaml         # Render 설정
└── templates/
    └── index.html      # 프론트엔드
```
