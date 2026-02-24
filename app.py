from flask import Flask, render_template, request, send_file, jsonify, session, redirect, url_for, make_response
from werkzeug.utils import secure_filename
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from werkzeug.security import generate_password_hash, check_password_hash
import pandas as pd
from io import BytesIO
from datetime import datetime, date, time as dt_time, timedelta, timezone
import calendar
import os
import json
from collections import defaultdict, OrderedDict
import numpy as np
import time
import secrets
from functools import wraps

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
app.secret_key = os.environ.get('SECRET_KEY', 'playauto-secret-key-2024')

# ==================== Rate Limiting 설정 ====================
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=["200 per minute"],
    storage_uri="memory://"
)

# ==================== Supabase 설정 (선택적) ====================
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')

supabase = None
DB_CONNECTED = False

# Supabase 연결 시도 (실패해도 앱은 정상 작동)
if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client, Client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        # 연결 테스트
        supabase.table('workers').select('id').limit(1).execute()
        DB_CONNECTED = True
        print("✅ Supabase 연결 성공 - DB 모드로 작동")
    except Exception as e:
        print(f"⚠️  Supabase 연결 실패 ({e}) - JSON 파일 모드로 작동")
        supabase = None
        DB_CONNECTED = False
else:
    print("ℹ️  Supabase 환경변수 없음 - JSON 파일 모드로 작동")

# ==================== 로그인 설정 ====================
LOGIN_ID = os.environ.get('LOGIN_ID', 'abc')
LOGIN_PW = os.environ.get('LOGIN_PW', '1234')
ADMIN_ID = os.environ.get('ADMIN_ID', LOGIN_ID)
ADMIN_PW = os.environ.get('ADMIN_PW', LOGIN_PW)

# [수정됨] 한국 시간(KST) 기준 오늘 날짜 구하기
def get_kst_today():
    return datetime.now(timezone(timedelta(hours=9))).date()

def login_required(f):
    """로그인 필수 데코레이터"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """관리자 전용 데코레이터"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        if session.get('user_role') != 'admin':
            return jsonify({'error': '관리자 권한이 필요합니다'}), 403
        return f(*args, **kwargs)
    return decorated_function

ALLOWED_EXTENSIONS = {'xls', 'xlsx'}
SETTINGS_FILE = 'playauto_settings_v4.json'
MARGIN_DATA_FILE = 'margin_data.json'

# 임시 저장소 (세션별 분류 결과)
TEMP_RESULTS = {}

def cleanup_old_sessions(max_age_hours=1):
    """오래된 세션 자동 정리 (메모리 누수 방지)"""
    now = datetime.now()
    expired_sessions = []
    for session_id, data in TEMP_RESULTS.items():
        created_at = data.get('created_at')
        if created_at:
            if isinstance(created_at, datetime):
                age_seconds = (now - created_at).total_seconds()
            else:
                age_seconds = time.time() - created_at
            if age_seconds > max_age_hours * 3600:
                expired_sessions.append(session_id)
    for session_id in expired_sessions:
        del TEMP_RESULTS[session_id]
    if expired_sessions:
        print(f"🧹 만료된 세션 {len(expired_sessions)}개 정리됨")

# ==================== 판매처별 수수료율 ====================
PLATFORM_FEES = {
    '쿠팡': 0.12,           # 12%
    '스마트스토어': 0.067,   # 6.7%
    '11번가': 0.18,         # 18%
    'G마켓': 0.15,          # 15%
    '옥션': 0.15,           # 15%
    '위메프': 0.15,         # 15%
    '티몬': 0.15,           # 15%
    '토스쇼핑': 0.12,       # 12%
    '기타': 0.10            # 10%
}

# ==================== 설정 관리 (기존 방식 유지) ====================

def load_settings_from_file():
    """JSON 파일에서 설정 로드"""
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def save_settings_to_file(settings):
    """JSON 파일에 설정 저장"""
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

def load_settings():
    """설정 로드 (기존 방식 유지)"""
    return load_settings_from_file()

def save_settings(settings):
    """설정 저장 (기존 방식 유지)"""
    save_settings_to_file(settings)

# 초기 설정 로드
try:
    CURRENT_SETTINGS = load_settings()
    if not CURRENT_SETTINGS:
        print("⚠️  경고: playauto_settings_v4.json 파일이 없습니다")
        CURRENT_SETTINGS = {
            "work_order": ["송과장님", "영재씨", "강민씨", "부모님", "합배송", "복수주문", "분류실패"],
            "work_config": {
                "송과장님": {"type": "product_specific", "products": [], "enabled": True},
                "영재씨": {"type": "product_specific", "products": [], "enabled": True},
                "강민씨": {"type": "product_specific", "products": [], "enabled": True},
                "부모님": {"type": "product_specific", "products": [], "enabled": True},
                "합배송": {"type": "mixed_products", "products": [], "enabled": True},
                "복수주문": {"type": "multiple_quantity", "products": [], "enabled": True},
                "분류실패": {"type": "failed", "products": [], "enabled": True}
            },
            "quantity_threshold": 2,
            "auto_learn": True,
            "min_confidence": 1.0
        }
    else:
        print(f"✅ 설정 로드 완료: {len(CURRENT_SETTINGS.get('work_order', []))}명의 담당자")
except Exception as e:
    print(f"❌ 설정 로드 오류: {e}")
    CURRENT_SETTINGS = None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ==================== 원가 마진표 (기존 방식 유지) ====================

MARGIN_DATA = []

def load_margin_data():
    """원가 마진표 데이터 로드 (JSON 파일)"""
    global MARGIN_DATA
    if os.path.exists(MARGIN_DATA_FILE):
        with open(MARGIN_DATA_FILE, 'r', encoding='utf-8') as f:
            MARGIN_DATA = json.load(f)
        print(f"✅ 원가 마진표 로드 완료: {len(MARGIN_DATA)}개 상품")
    else:
        print("⚠️  경고: margin_data.json 파일이 없습니다")

def save_margin_data():
    """원가 마진표 JSON 파일 저장"""
    with open(MARGIN_DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(MARGIN_DATA, f, ensure_ascii=False, indent=2)

# 시작 시 로드
load_margin_data()

# ==================== 원가 매칭 및 수수료 계산 함수 ====================

def find_matching_cost(product_name):
    """상품명으로 원가 찾기 (Fuzzy Matching)"""
    if not product_name or not MARGIN_DATA:
        return 0

    product_name = str(product_name).strip()

    # 1. 정확히 일치
    for item in MARGIN_DATA:
        if item.get('상품명') == product_name:
            return item.get('인상후_총_원가') or item.get('인상후 총 원가', 0)

    # 2. 포함 검색 (긴 것 우선)
    matches = []
    for item in MARGIN_DATA:
        margin_name = item.get('상품명', '')
        if margin_name in product_name or product_name in margin_name:
            matches.append((item, len(margin_name)))

    if matches:
        matches.sort(key=lambda x: x[1], reverse=True)
        return matches[0][0].get('인상후_총_원가') or matches[0][0].get('인상후 총 원가', 0)

    # 3. 핵심 단어 매칭 (공백 기준 첫 2-3단어)
    keywords = product_name.split()[:3]
    for item in MARGIN_DATA:
        margin_name = item.get('상품명', '')
        if len(keywords) >= 2 and all(kw in margin_name for kw in keywords[:2]):
            return item.get('인상후_총_원가') or item.get('인상후 총 원가', 0)

    return 0


def get_platform_fee_rate(site_name):
    """판매처별 수수료율 반환"""
    if not site_name:
        return PLATFORM_FEES['기타']

    site_name = str(site_name)
    for platform, rate in PLATFORM_FEES.items():
        if platform in site_name:
            return rate
    return PLATFORM_FEES['기타']

# ==================== 면세 자료 정리 함수 ====================

def process_tax_free_files(files):
    """쿠팡 매출자료에서 면세(FREE) 데이터 추출 (중복 파일 체크 포함)"""
    import hashlib
    
    all_free_data = []
    monthly_stats = {}
    monthly_files = {}
    file_hashes = {}
    duplicate_files = []
    processed_files = []
    
    sales_cols = ['신용카드(판매)', '현금(판매)', '기타(판매)']
    refund_cols = ['신용카드(환불)', '현금(환불)', '기타(환불)']
    
    for file in files:
        try:
            file_content = file.read()
            file.seek(0)
            
            file_hash = hashlib.md5(file_content).hexdigest()
            
            if file_hash in file_hashes:
                duplicate_files.append({
                    'filename': file.filename,
                    'duplicate_of': file_hashes[file_hash]
                })
                continue
            
            file_hashes[file_hash] = file.filename
            
            from io import BytesIO
            if file.filename.endswith('.xlsx'):
                df = pd.read_excel(BytesIO(file_content), engine='openpyxl')
            else:
                df = pd.read_excel(BytesIO(file_content), engine='xlrd')
            
            if '과세유형' not in df.columns or '매출인식일' not in df.columns:
                continue
            
            # 원본 날짜 보존을 위해 별도 컬럼으로 날짜 파싱
            df['_parsed_date'] = pd.to_datetime(df['매출인식일'])
            file_months = df['_parsed_date'].dt.to_period('M').unique()
            
            file_month = str(file_months[0]) if len(file_months) > 0 else None
            
            if file_month:
                if file_month in monthly_files:
                    duplicate_files.append({
                        'filename': file.filename,
                        'duplicate_of': monthly_files[file_month][0],
                        'month': file_month
                    })
                    continue
                
                monthly_files[file_month] = [file.filename]
            
            processed_files.append(file.filename)
            
            for col in sales_cols + refund_cols:
                if col not in df.columns:
                    df[col] = 0
            
            df['총매출'] = df[sales_cols].sum(axis=1) - df[refund_cols].sum(axis=1)
            
            # 벡터화 연산으로 월별 통계 계산 (성능 최적화)
            df['_month_key'] = df['_parsed_date'].dt.to_period('M').astype(str)
            df['_is_free'] = df['과세유형'].astype(str).str.strip().str.upper() == 'FREE'
            
            for month_key in df['_month_key'].unique():
                month_df = df[df['_month_key'] == month_key]
                
                if month_key not in monthly_stats:
                    monthly_stats[month_key] = {
                        'free_count': 0, 'free_sales': 0,
                        'total_count': 0, 'total_sales': 0,
                        'file_count': 0, 'files': []
                    }
                
                monthly_stats[month_key]['total_count'] += int(len(month_df))
                monthly_stats[month_key]['total_sales'] += float(month_df['총매출'].sum())
                
                free_df_month = month_df[month_df['_is_free']]
                monthly_stats[month_key]['free_count'] += int(len(free_df_month))
                monthly_stats[month_key]['free_sales'] += float(free_df_month['총매출'].sum())
            
            if file_month and file_month in monthly_stats:
                if file.filename not in monthly_stats[file_month]['files']:
                    monthly_stats[file_month]['files'].append(file.filename)
                    monthly_stats[file_month]['file_count'] = len(monthly_stats[file_month]['files'])
            
            free_mask = df['과세유형'].astype(str).str.strip().str.upper() == 'FREE'
            free_df = df[free_mask].copy()
            
            # 임시 컬럼들 제거
            temp_cols = ['_parsed_date', '_month_key', '_is_free']
            free_df = free_df.drop(columns=[c for c in temp_cols if c in free_df.columns])
            
            if len(free_df) > 0:
                all_free_data.append(free_df)
                
        except Exception as e:
            print(f"파일 처리 오류 ({file.filename}): {e}")
            import traceback
            traceback.print_exc()
            continue
    
    combined_df = pd.concat(all_free_data, ignore_index=True) if all_free_data else pd.DataFrame()
    
    # Unnamed 컬럼명을 빈 문자열로 변경
    if not combined_df.empty:
        combined_df.columns = ['' if 'Unnamed' in str(col) else col for col in combined_df.columns]
    
    for month_key in monthly_stats:
        if month_key in monthly_files:
            monthly_stats[month_key]['files'] = monthly_files[month_key]
            monthly_stats[month_key]['file_count'] = len(monthly_files[month_key])
    
    return combined_df, monthly_stats, duplicate_files, processed_files


# ==================== 스타배송 필터 함수 ====================

def check_star_delivery(df):
    """스타배송 주문 존재 여부 확인"""
    target_col = None
    for col in df.columns:
        if '주의' in str(col) and '메' in str(col):
            target_col = col
            break
    
    if target_col is None:
        return {'has_column': False, 'star_count': 0}
    
    mask = df[target_col].astype(str).str.startswith('판매자 스타배송', na=False)
    star_count = int(mask.sum())
    
    return {'has_column': True, 'star_count': star_count, 'column': target_col, 'mask': mask}

def filter_star_delivery(df):
    """스타배송 주문 필터링 (제거)"""
    result = check_star_delivery(df)
    
    if not result['has_column']:
        return df, 0
    
    filtered_df = df[~result['mask']]
    deleted_count = int(result['star_count'])
    
    return filtered_df, deleted_count

# ==================== 기존 라우트 (100% 유지) ====================

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("5 per minute", methods=["POST"])
def login():
    """로그인 페이지"""
    if request.method == 'POST':
        data = request.get_json()
        user_id = data.get('id', '')
        user_pw = data.get('pw', '')
        
        # 1. DB에서 사용자 확인 (출퇴근 시스템용)
        if DB_CONNECTED and supabase:
            try:
                response = supabase.table('users').select('*').eq('username', user_id).eq('enabled', True).execute()
                if response.data:
                    user = response.data[0]
                    stored_pw = user['password']
                    pw_valid = False

                    # 해시 여부 확인 후 검증
                    if stored_pw.startswith('pbkdf2:') or stored_pw.startswith('scrypt:'):
                        pw_valid = check_password_hash(stored_pw, user_pw)
                    else:
                        # 평문 저장된 기존 계정 - 검증 후 자동 해시 마이그레이션
                        pw_valid = (stored_pw == user_pw)
                        if pw_valid:
                            supabase.table('users').update({
                                'password': generate_password_hash(user_pw)
                            }).eq('id', user['id']).execute()

                    if pw_valid:
                        session['logged_in'] = True
                        session['user_id'] = user['id']
                        session['user_role'] = user['role']
                        session['user_name'] = user['name']
                        session['username'] = user['username']
                        return jsonify({'success': True, 'role': user['role']})
            except Exception as e:
                print(f"DB 로그인 확인 오류: {e}")
        
        # 2. 기존 환경변수 관리자 계정 (하위 호환)
        if user_id == LOGIN_ID and user_pw == LOGIN_PW:
            session['logged_in'] = True
            session['user_id'] = 0
            session['user_role'] = 'admin'
            session['user_name'] = '관리자'
            session['username'] = user_id
            return jsonify({'success': True, 'role': 'admin'})
        
        # 3. ADMIN_ID/ADMIN_PW 확인
        if user_id == ADMIN_ID and user_pw == ADMIN_PW:
            session['logged_in'] = True
            session['user_id'] = 0
            session['user_role'] = 'admin'
            session['user_name'] = '관리자'
            session['username'] = user_id
            return jsonify({'success': True, 'role': 'admin'})
        
        return jsonify({'success': False, 'error': '아이디 또는 비밀번호가 틀렸습니다'})
    
    if session.get('logged_in'):
        return redirect(url_for('index'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """로그아웃"""
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    # 알바생은 출퇴근 페이지로
    if session.get('user_role') == 'parttime':
        return render_template('parttime.html')
    return render_template('index.html')

@app.route('/api/session')
@login_required
def get_session_info():
    """현재 세션 정보"""
    return jsonify({
        'user_id': session.get('user_id'),
        'user_role': session.get('user_role'),
        'user_name': session.get('user_name'),
        'username': session.get('username')
    })

@app.route('/health')
def health():
    """UptimeRobot 헬스체크용"""
    return 'OK', 200

# ==================== 기존 /settings 라우트 (유지) ====================

@app.route('/settings', methods=['GET'])
@login_required
def get_settings_legacy():
    """현재 설정 조회 (기존 방식 - 하위 호환)"""
    if CURRENT_SETTINGS:
        total_products = sum(
            len(cfg.get('products', [])) 
            for cfg in CURRENT_SETTINGS.get('work_config', {}).values()
        )
        
        has_file = os.path.exists(SETTINGS_FILE)
        
        return jsonify({
            'status': 'loaded',
            'workers': list(CURRENT_SETTINGS.get('work_order', [])),
            'total_products': total_products,
            'source': 'file' if has_file else 'default',
            'db_connected': DB_CONNECTED
        })
    return jsonify({
        'status': 'not_loaded', 
        'error': '설정을 불러올 수 없습니다',
        'db_connected': DB_CONNECTED
    })

# ==================== 기존 /api/margin 라우트 (유지 + 확장) ====================

@app.route('/api/margin', methods=['GET'])
@login_required
def get_margin_data():
    """원가 마진표 데이터 조회"""
    search = request.args.get('search', '').strip()
    
    # DB 모드: Supabase에서 조회
    if DB_CONNECTED and supabase:
        try:
            query = supabase.table('margin_products').select('*')
            if search:
                query = query.ilike('상품명', f'%{search}%')
            response = query.order('상품명').execute()
            
            # DB 컬럼명 → JSON 형식 변환
            data = []
            for item in response.data:
                data.append({
                    'id': item['id'],
                    '상품명': item['상품명'],
                    '인상전 상품가': item.get('인상전_상품가', 0),
                    '인상후 상품가': item.get('인상후_상품가', 0),
                    '물량지원': item.get('물량지원', 1),
                    '프로모션할인률': item.get('프로모션할인률', 0),
                    '장려금률': item.get('장려금률', 0),
                    '배송비': item.get('배송비', 0),
                    '박스비': item.get('박스비', 0),
                    '인상전 총 원가': item.get('인상전_총_원가', 0),
                    '인상후 총 원가': item.get('인상후_총_원가', 0),
                    '인상전 재고': item.get('인상전_재고', ''),
                    '1박스 최대 수량': item.get('박스_최대_수량', ''),
                    '기타사항': item.get('기타사항', '')
                })
            return jsonify({'data': data, 'total': len(data), 'source': 'db'})
        except Exception as e:
            print(f"DB 조회 실패, JSON 폴백: {e}")
    
    # JSON 모드: 파일에서 조회 (기존 방식)
    if search:
        filtered = [item for item in MARGIN_DATA if search.lower() in item['상품명'].lower()]
        return jsonify({'data': filtered, 'total': len(filtered), 'source': 'file'})
    
    return jsonify({'data': MARGIN_DATA, 'total': len(MARGIN_DATA), 'source': 'file'})

@app.route('/api/margin', methods=['POST'])
@login_required
def create_margin_product():
    """원가 마진표 상품 추가 (DB 모드만)"""
    if not DB_CONNECTED or not supabase:
        return jsonify({'error': 'DB 연결이 필요합니다', 'db_connected': False}), 400
    
    data = request.get_json()
    
    try:
        new_product = {
            '상품명': data.get('상품명', ''),
            '인상전_상품가': float(data.get('인상전 상품가', 0) or 0),
            '인상후_상품가': float(data.get('인상후 상품가', 0) or 0),
            '물량지원': float(data.get('물량지원', 1) or 1),
            '프로모션할인률': float(data.get('프로모션할인률', 0) or 0),
            '장려금률': float(data.get('장려금률', 0) or 0),
            '배송비': float(data.get('배송비', 0) or 0),
            '박스비': float(data.get('박스비', 0) or 0),
            '인상전_총_원가': float(data.get('인상전 총 원가', 0) or 0),
            '인상후_총_원가': float(data.get('인상후 총 원가', 0) or 0),
            '인상전_재고': str(data.get('인상전 재고', '')),
            '박스_최대_수량': str(data.get('1박스 최대 수량', '')),
            '기타사항': str(data.get('기타사항', ''))
        }
        
        response = supabase.table('margin_products').insert(new_product).execute()
        return jsonify({'success': True, 'data': response.data[0]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/margin/<int:product_id>', methods=['PUT'])
@login_required
def update_margin_product(product_id):
    """원가 마진표 상품 수정 (DB 모드만)"""
    if not DB_CONNECTED or not supabase:
        return jsonify({'error': 'DB 연결이 필요합니다', 'db_connected': False}), 400
    
    data = request.get_json()
    
    try:
        update_data = {
            '상품명': data.get('상품명', ''),
            '인상전_상품가': float(data.get('인상전 상품가', 0) or 0),
            '인상후_상품가': float(data.get('인상후 상품가', 0) or 0),
            '물량지원': float(data.get('물량지원', 1) or 1),
            '프로모션할인률': float(data.get('프로모션할인률', 0) or 0),
            '장려금률': float(data.get('장려금률', 0) or 0),
            '배송비': float(data.get('배송비', 0) or 0),
            '박스비': float(data.get('박스비', 0) or 0),
            '인상전_총_원가': float(data.get('인상전 총 원가', 0) or 0),
            '인상후_총_원가': float(data.get('인상후 총 원가', 0) or 0),
            '인상전_재고': str(data.get('인상전 재고', '')),
            '박스_최대_수량': str(data.get('1박스 최대 수량', '')),
            '기타사항': str(data.get('기타사항', '')),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        response = supabase.table('margin_products').update(update_data).eq('id', product_id).execute()
        return jsonify({'success': True, 'data': response.data[0] if response.data else None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/margin/<int:product_id>', methods=['DELETE'])
@login_required
def delete_margin_product(product_id):
    """원가 마진표 상품 삭제 (DB 모드만)"""
    if not DB_CONNECTED or not supabase:
        return jsonify({'error': 'DB 연결이 필요합니다', 'db_connected': False}), 400
    
    try:
        supabase.table('margin_products').delete().eq('id', product_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== 담당자 API (새로 추가) ====================

@app.route('/api/workers', methods=['GET'])
@login_required
def get_workers():
    """담당자 목록 조회"""
    # DB 모드
    if DB_CONNECTED and supabase:
        try:
            response = supabase.table('workers').select('*').order('sort_order').execute()
            workers = response.data
            
            # 각 담당자별 상품 개수 추가
            for worker in workers:
                products_resp = supabase.table('worker_products').select('id').eq('worker_id', worker['id']).execute()
                worker['product_count'] = len(products_resp.data)
            
            return jsonify({'data': workers, 'source': 'db', 'db_connected': True})
        except Exception as e:
            print(f"담당자 DB 조회 실패: {e}")
    
    # JSON 모드 (폴백)
    if CURRENT_SETTINGS:
        workers = []
        icons = {
            '송과장님': '🍧', '영재씨': '🍯', '효상': '🍜', '강민씨': '🍜',
            '부모님': '☕', '합배송': '📦', '복수주문': '📋', '분류실패': '❓'
        }
        descriptions = {
            '송과장님': '팥빙수재료 및 특정 상품 담당',
            '영재씨': '미에로화이바, 꿀차, 파우치음료 담당',
            '효상': '백제 쌀국수, 떡국 담당',
            '강민씨': '백제 브랜드 모든 상품 담당',
            '부모님': '쟈뎅, 부국, 린저, 카페재료 담당',
            '합배송': '한 주문번호에 여러 다른 상품',
            '복수주문': '한 상품을 2개 이상 주문',
            '분류실패': '매칭되지 않은 상품 (수동 검토 필요)'
        }
        
        for i, name in enumerate(CURRENT_SETTINGS.get('work_order', [])):
            config = CURRENT_SETTINGS.get('work_config', {}).get(name, {})
            workers.append({
                'id': i + 1,
                'name': name,
                'type': config.get('type', 'product_specific'),
                'description': descriptions.get(name, config.get('description', '')),
                'icon': icons.get(name, config.get('icon', '📋')),
                'enabled': config.get('enabled', True),
                'product_count': len(config.get('products', []))
            })
        return jsonify({'data': workers, 'source': 'file', 'db_connected': False})
    
    return jsonify({'data': [], 'source': 'none', 'db_connected': False})

@app.route('/api/workers/<int:worker_id>/products', methods=['GET'])
@login_required
def get_worker_products(worker_id):
    """담당자별 상품 규칙 조회"""
    # DB 모드
    if DB_CONNECTED and supabase:
        try:
            response = supabase.table('worker_products').select('*').eq('worker_id', worker_id).order('product_name').execute()
            return jsonify({'data': response.data, 'source': 'db', 'db_connected': True})
        except Exception as e:
            print(f"상품 규칙 DB 조회 실패: {e}")
    
    # JSON 모드 (폴백)
    if CURRENT_SETTINGS:
        work_order = CURRENT_SETTINGS.get('work_order', [])
        if 0 < worker_id <= len(work_order):
            worker_name = work_order[worker_id - 1]
            config = CURRENT_SETTINGS.get('work_config', {}).get(worker_name, {})
            products = config.get('products', [])
            
            # 상품명으로 정렬
            sorted_products = sorted(products, key=lambda x: x.get('product_name', ''))
            
            # ID 추가 (인덱스 기반)
            result = []
            for i, p in enumerate(sorted_products):
                result.append({
                    'id': i + 1,
                    'worker_id': worker_id,
                    'brand': p.get('brand', ''),
                    'product_name': p.get('product_name', ''),
                    'order_option': p.get('order_option', 'All')
                })
            return jsonify({'data': result, 'source': 'file', 'db_connected': False})
    
    return jsonify({'data': [], 'source': 'none', 'db_connected': False})

@app.route('/api/workers/<int:worker_id>/products', methods=['POST'])
@login_required
def create_worker_product(worker_id):
    """담당자 상품 규칙 추가 (DB 모드만)"""
    if not DB_CONNECTED or not supabase:
        return jsonify({'error': 'DB 연결이 필요합니다', 'db_connected': False}), 400
    
    data = request.get_json()
    
    try:
        new_product = {
            'worker_id': worker_id,
            'brand': data.get('brand', ''),
            'product_name': data.get('product_name', ''),
            'order_option': data.get('order_option', 'All')
        }
        
        response = supabase.table('worker_products').insert(new_product).execute()
        return jsonify({'success': True, 'data': response.data[0]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/workers/<int:worker_id>/products/<int:product_id>', methods=['PUT'])
@login_required
def update_worker_product(worker_id, product_id):
    """담당자 상품 규칙 수정 (DB 모드만)"""
    if not DB_CONNECTED or not supabase:
        return jsonify({'error': 'DB 연결이 필요합니다', 'db_connected': False}), 400
    
    data = request.get_json()
    
    try:
        update_data = {
            'brand': data.get('brand', ''),
            'product_name': data.get('product_name', ''),
            'order_option': data.get('order_option', 'All'),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        response = supabase.table('worker_products').update(update_data).eq('id', product_id).execute()
        return jsonify({'success': True, 'data': response.data[0] if response.data else None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/workers/<int:worker_id>/products/<int:product_id>', methods=['DELETE'])
@login_required
def delete_worker_product(worker_id, product_id):
    """담당자 상품 규칙 삭제 (DB 모드만)"""
    if not DB_CONNECTED or not supabase:
        return jsonify({'error': 'DB 연결이 필요합니다', 'db_connected': False}), 400
    
    try:
        supabase.table('worker_products').delete().eq('id', product_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== DB 상태 확인 API ====================

@app.route('/api/db-status', methods=['GET'])
@login_required
def get_db_status():
    """DB 연결 상태 확인"""
    return jsonify({
        'db_connected': DB_CONNECTED,
        'mode': 'db' if DB_CONNECTED else 'file'
    })

# ==================== 기존 스타배송 필터 (100% 유지) ====================

@app.route('/upload', methods=['POST'])
@login_required
def upload_file():
    """스타배송 필터"""
    if 'file' not in request.files:
        return jsonify({'error': '파일이 없습니다'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '파일을 선택해주세요'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': '.xls 또는 .xlsx 파일만 가능합니다'}), 400
    
    try:
        ext = file.filename.rsplit('.', 1)[1].lower()
        if ext == 'xls':
            df = pd.read_excel(file, engine='xlrd')
        else:
            df = pd.read_excel(file, engine='openpyxl')
        
        original_count = len(df)
        
        target_col = None
        for col in df.columns:
            if '주의' in str(col) and '메' in str(col):
                target_col = col
                break
        
        if target_col is None:
            return jsonify({'error': "'주의메세지' 컬럼을 찾을 수 없습니다"}), 400
        
        mask = df[target_col].astype(str).str.startswith('판매자 스타배송', na=False)
        df_filtered = df[~mask]
        deleted_count = original_count - len(df_filtered)
        
        output = BytesIO()
        df_filtered.to_excel(output, index=False, engine='openpyxl')
        output.seek(0)
        
        original_name = secure_filename(file.filename).rsplit('.', 1)[0]
        output_filename = f"{original_name}_final.xlsx"
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=output_filename
        ), 200, {
            'X-Deleted-Count': str(deleted_count),
            'X-Original-Count': str(original_count)
        }
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== 기존 송장 분류 (100% 유지) ====================

@app.route('/classify', methods=['POST'])
@login_required
def classify_orders():
    """송장 분류 - 통계와 함께 결과 반환 + DB 저장"""
    cleanup_old_sessions()  # 오래된 세션 정리
    if 'file' not in request.files:
        return jsonify({'error': '파일이 없습니다'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '파일을 선택해주세요'}), 400

    if not allowed_file(file.filename):
        return jsonify({'error': '.xls 또는 .xlsx 파일만 가능합니다'}), 400

    if not CURRENT_SETTINGS:
        return jsonify({'error': '설정 파일을 먼저 로드해주세요'}), 400

    filter_star = request.form.get('filter_star', 'false').lower() == 'true'

    try:
        ext = file.filename.rsplit('.', 1)[1].lower()
        if ext == 'xls':
            df = pd.read_excel(file, engine='xlrd')
        else:
            df = pd.read_excel(file, engine='openpyxl')

        # 데이터 분석용 DB 저장 (체크박스로 제어)
        collect_analytics = request.form.get('collect_analytics', 'false').lower() == 'true'
        
        if DB_CONNECTED and collect_analytics:
            try:
                df_copy = df.copy()
                saved_count = save_sales_data_to_db(df_copy)
                print(f"✅ 판매 데이터 {saved_count}건 저장 완료")
            except Exception as e:
                import traceback
                print(f"⚠️ 판매 데이터 저장 실패: {e}")
                traceback.print_exc()

        star_deleted = 0
        if filter_star:
            df, star_deleted = filter_star_delivery(df)

        classifier = OrderClassifierV41(CURRENT_SETTINGS)
        result_df = classifier.classify_orders_optimized(df)
        stats = classifier.get_classification_stats(result_df)

        # 스타배송 필터링 체크한 경우 항상 정보 추가 (0건이어도)
        if filter_star:
            stats['summary']['star_filtered'] = True
            stats['summary']['star_deleted'] = star_deleted
        else:
            stats['summary']['star_filtered'] = False

        session_id = secrets.token_urlsafe(16)
        TEMP_RESULTS[session_id] = {
            'df': result_df,
            'stats': stats,
            'filename': file.filename,
            'created_at': datetime.now()
        }

        return jsonify({
            'success': True,
            'session_id': session_id,
            'stats': stats
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/download/<session_id>')
@login_required
def download_result(session_id):
    """분류 결과 다운로드"""
    if session_id not in TEMP_RESULTS:
        return jsonify({'error': '결과를 찾을 수 없습니다'}), 404
    
    result = TEMP_RESULTS[session_id]
    df = result['df']
    
    classifier = OrderClassifierV41(CURRENT_SETTINGS)
    output = classifier.export_single_sheet(df)
    
    original_name = result['filename'].rsplit('.', 1)[0]
    output_filename = f"{original_name}_분류완료.xlsx"
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=output_filename
    )

# ==================== 분류 엔진 (원본 100% 유지) ====================

class OrderClassifierV41:
    """
    플레이오토 주문 분류 엔진 v4.1
    원본 데스크톱 앱의 모든 로직 100% 재현
    """
    
    def __init__(self, settings):
        self.settings = settings
        self.work_order = settings.get('work_order', [])
        self.work_config = settings.get('work_config', {})
        self.quantity_threshold = settings.get('quantity_threshold', 2)
        self.auto_learn = settings.get('auto_learn', True)
        self.min_confidence = settings.get('min_confidence', 1.0)
        
    def classify_orders_optimized(self, df):
        """최적화된 주문 분류 (원본 로직)"""
        df = df.copy()
        
        # 전처리
        df = self._preprocess_data_optimized(df)
        
        # 분류 실패 담당자명 찾기
        failed_work = self._get_failed_work_name()
        
        # 초기값 설정
        df['담당자'] = failed_work
        df['분류근거'] = '매칭 없음'
        df['신뢰도'] = 0.0
        
        # 1. 합배송 처리 (우선순위 1)
        if '주문고유번호' in df.columns:
            order_counts = df['주문고유번호'].value_counts()
            multi_orders = order_counts[order_counts >= 2].index
            is_multi_order = df['주문고유번호'].isin(multi_orders)
            
            combined_work = self._get_combined_work_name()
            if combined_work:
                df.loc[is_multi_order, '담당자'] = combined_work
                df.loc[is_multi_order, '분류근거'] = '합배송'
                df.loc[is_multi_order, '신뢰도'] = 1.0
        
        # 2. 복수주문 처리 (우선순위 2)
        multiple_work = self._get_multiple_work_name()
        if multiple_work:
            is_multiple = (df['주문수량'] >= self.quantity_threshold) & (df['담당자'] == failed_work)
            df.loc[is_multiple, '담당자'] = multiple_work
            df.loc[is_multiple, '분류근거'] = '복수주문'
            df.loc[is_multiple, '신뢰도'] = 1.0
        
        # 3. 상품별 매칭 (미분류만 대상)
        unmatched_mask = df['담당자'] == failed_work
        unmatched_indices = df[unmatched_mask].index
        
        if len(unmatched_indices) > 0:
            compiled_rules = self._compile_matching_rules()
            self._classify_batch(df, unmatched_indices, compiled_rules)
        
        # 4. 결과 정렬
        df = self._sort_results_optimized(df)
        
        return df
    
    def _preprocess_data_optimized(self, df):
        """데이터 전처리"""
        # 상품명 처리
        if '상품명' in df.columns:
            df['상품명'] = df['상품명'].fillna('').astype(str)
        else:
            raise ValueError("필수 컬럼 '상품명' 없음")
        
        # 주문수량 처리
        if '주문수량' in df.columns:
            df['주문수량'] = pd.to_numeric(df['주문수량'], errors='coerce').fillna(0).astype(int)
        else:
            df['주문수량'] = 1
        
        # 주문선택사항 처리
        if '주문선택사항' in df.columns:
            df['주문선택사항'] = df['주문선택사항'].fillna('').astype(str)
            df['full_product_name'] = df['상품명'] + ' ' + df['주문선택사항']
        else:
            df['주문선택사항'] = ''
            df['full_product_name'] = df['상품명']
        
        # 브랜드 추출
        df['brand'] = df['상품명'].str.split(n=1, expand=True)[0].fillna('')
        
        # 주문고유번호 처리
        if '주문고유번호' in df.columns:
            df['주문고유번호'] = df['주문고유번호'].fillna('').astype(str)
        elif '주문번호' in df.columns:
            df['주문고유번호'] = df['주문번호'].fillna('').astype(str)
        else:
            df['주문고유번호'] = np.arange(len(df)).astype(str)
        
        return df
    
    def _compile_matching_rules(self):
        """매칭 규칙 컴파일"""
        rules = []
        for work_name in self.work_order:
            work_config = self.work_config.get(work_name, {})
            if work_config.get('type') != 'product_specific':
                continue
            
            for product in work_config.get('products', []):
                rules.append({
                    'work_name': work_name,
                    'brand': product.get('brand', ''),
                    'product_name': product.get('product_name', ''),
                    'order_option': product.get('order_option', 'All')
                })
        return rules
    
    def _classify_batch(self, df, indices, rules):
        """배치 분류"""
        for idx in indices:
            row = df.loc[idx]
            
            for rule in rules:
                if self._match_rule(row, rule):
                    df.at[idx, '담당자'] = rule['work_name']
                    df.at[idx, '분류근거'] = f"매칭: {rule['brand']} {rule['product_name']}"
                    df.at[idx, '신뢰도'] = 1.0
                    break
    
    def _match_rule(self, row, rule):
        """규칙 매칭"""
        # 브랜드 체크
        if rule['brand'] and rule['brand'] != 'All':
            if rule['brand'] not in row['brand']:
                return False
        
        # 상품명 체크
        if rule['product_name'] != 'All':
            if rule['product_name'] not in row['상품명']:
                return False
        
        # 주문선택사항 체크
        if rule['order_option'] != 'All':
            if rule['order_option'] not in row['주문선택사항']:
                return False
        
        return True
    
    def _sort_results_optimized(self, df):
        """결과 정렬"""
        priority_map = {name: i for i, name in enumerate(self.work_order)}
        df['priority'] = df['담당자'].map(priority_map)
        
        combined_work = self._get_combined_work_name()
        
        sorted_groups = []
        for work_name in self.work_order:
            work_df = df[df['담당자'] == work_name].copy()
            
            if len(work_df) == 0:
                continue
            
            if work_name == combined_work:
                work_df = work_df.sort_values(['주문고유번호'])
            else:
                work_df = work_df.sort_values(['full_product_name'])
            
            sorted_groups.append(work_df)
        
        if sorted_groups:
            sorted_df = pd.concat(sorted_groups, ignore_index=True)
            sorted_df = sorted_df.drop(['priority'], axis=1)
        else:
            sorted_df = df
        
        return sorted_df
    
    def get_classification_stats(self, df):
        """분류 통계 계산"""
        total_orders = len(df)
        stats = {
            'workers': [],
            'summary': {}
        }
        
        current_row = 1
        
        for work_name in self.work_order:
            work_data = df[df['담당자'] == work_name]
            count = len(work_data)
            
            config = self.work_config.get(work_name, {})
            icon = config.get('icon', '📋')
            
            if count > 0:
                start_row = current_row
                end_row = current_row + count - 1
                row_range = f"{start_row} ~ {end_row}"
                current_row = end_row + 1
            else:
                row_range = "-"
            
            stats['workers'].append({
                'name': work_name,
                'count': count,
                'percentage': round(count / total_orders * 100, 1) if total_orders > 0 else 0,
                'icon': icon,
                'range': row_range
            })
        
        # 요약 통계
        failed_work = self._get_failed_work_name()
        unmatched_count = len(df[df['담당자'] == failed_work])
        success_count = total_orders - unmatched_count
        auto_rate = round(success_count / total_orders * 100, 1) if total_orders > 0 else 0
        
        stats['summary'] = {
            'total_orders': total_orders,
            'success_count': success_count,
            'failed_count': unmatched_count,
            'auto_classification_rate': auto_rate
        }
        
        return stats
    
    def export_single_sheet(self, df):
        """단일 시트 엑셀 내보내기"""
        output = BytesIO()
        
        export_df = df.copy()
        temp_cols = ['full_product_name', 'brand', 'priority', '담당자', '분류근거', '신뢰도']
        for col in temp_cols:
            if col in export_df.columns:
                export_df = export_df.drop(columns=[col])
        
        export_df.to_excel(output, sheet_name='분류결과', index=False, engine='openpyxl')
        
        output.seek(0)
        return output
    
    def _get_failed_work_name(self):
        """분류실패 담당자명"""
        for work_name, config in self.work_config.items():
            if config.get('type') == 'failed':
                return work_name
        return '분류실패'
    
    def _get_combined_work_name(self):
        """합배송 담당자명"""
        for work_name, config in self.work_config.items():
            if config.get('type') == 'mixed_products':
                return work_name
        return None
    
    def _get_multiple_work_name(self):
        """복수주문 담당자명"""
        for work_name, config in self.work_config.items():
            if config.get('type') == 'multiple_quantity':
                return work_name
        return None

# ==================== 면세 자료 정리 API ====================

@app.route('/api/tax-free/process', methods=['POST'])
@admin_required
def process_tax_free():
    """면세 자료 처리"""
    cleanup_old_sessions()  # 오래된 세션 정리
    if 'files' not in request.files:
        return jsonify({'error': '파일이 없습니다'}), 400
    
    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'error': '파일을 선택해주세요'}), 400
    
    try:
        combined_df, monthly_stats, duplicate_files, processed_files = process_tax_free_files(files)
        
        if combined_df.empty:
            return jsonify({'error': '면세(FREE) 데이터가 없습니다'}), 400
        
        session_id = secrets.token_urlsafe(16)
        
        output = BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            combined_df.to_excel(writer, index=False, sheet_name='면세자료')
        output.seek(0)
        
        TEMP_RESULTS[session_id] = {
            'data': output.getvalue(),
            'stats': monthly_stats,
            'row_count': len(combined_df),
            'created_at': datetime.now()
        }
        
        yearly_free_count = sum(s['free_count'] for s in monthly_stats.values())
        yearly_free_sales = sum(s['free_sales'] for s in monthly_stats.values())
        yearly_total_count = sum(s['total_count'] for s in monthly_stats.values())
        yearly_total_sales = sum(s['total_sales'] for s in monthly_stats.values())
        
        return jsonify({
            'success': True,
            'session_id': session_id,
            'row_count': len(combined_df),
            'monthly_stats': monthly_stats,
            'yearly_summary': {
                'free_count': yearly_free_count,
                'free_sales': yearly_free_sales,
                'total_count': yearly_total_count,
                'total_sales': yearly_total_sales
            },
            'file_info': {
                'total_uploaded': len(files),
                'processed': len(processed_files),
                'duplicates': duplicate_files,
                'processed_files': processed_files,
                'total_months': len(monthly_stats)
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/tax-free/download/<session_id>')
@admin_required
def download_tax_free(session_id):
    """면세 자료 다운로드"""
    if session_id not in TEMP_RESULTS:
        return jsonify({'error': '세션이 만료되었습니다'}), 404
    
    result = TEMP_RESULTS[session_id]
    output = BytesIO(result['data'])
    
    filename = f"면세자료_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


# ==================== 출퇴근 관리 API (신규) ====================

@app.route('/api/employees', methods=['GET'])
@admin_required
def get_employees():
    """직원 목록 조회 (관리자용)"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    try:
        response = supabase.table('users').select('*').eq('role', 'parttime').order('created_at').execute()
        employees = []
        for emp in response.data:
            employees.append({
                'id': emp['id'],
                'username': emp['username'],
                'name': emp['name'],
                'hourly_wage': emp['hourly_wage'],
                'full_attendance_bonus': emp.get('full_attendance_bonus', 100000),
                'scheduled_days': emp.get('scheduled_days', '1,2,3,4,5'),
                'enabled': emp['enabled'],
                'created_at': emp['created_at']
            })
        return jsonify({'success': True, 'data': employees})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/employees', methods=['POST'])
@admin_required
def create_employee():
    """직원 생성"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    data = request.get_json()
    try:
        existing = supabase.table('users').select('id').eq('username', data.get('username')).execute()
        if existing.data:
            return jsonify({'error': '이미 존재하는 아이디입니다'}), 400
        
        new_emp = {
            'username': data.get('username'),
            'password': generate_password_hash(data.get('password')),
            'name': data.get('name'),
            'role': 'parttime',
            'hourly_wage': int(data.get('hourly_wage', 10700)),
            'full_attendance_bonus': int(data.get('full_attendance_bonus', 100000)),
            'scheduled_days': data.get('scheduled_days', '1,2,3,4,5'),
            'enabled': True
        }
        response = supabase.table('users').insert(new_emp).execute()
        
        supabase.table('wage_history').insert({
            'employee_id': response.data[0]['id'],
            'hourly_wage': new_emp['hourly_wage'],
            'effective_date': date.today().isoformat()
        }).execute()
        
        return jsonify({'success': True, 'data': response.data[0]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/employees/<int:emp_id>', methods=['PUT'])
@admin_required
def update_employee(emp_id):
    """직원 정보 수정"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    data = request.get_json()
    try:
        old_emp = supabase.table('users').select('*').eq('id', emp_id).execute()
        if not old_emp.data:
            return jsonify({'error': '직원을 찾을 수 없습니다'}), 404
        
        old_data = old_emp.data[0]
        old_wage = old_data.get('hourly_wage', 0)
        new_wage = int(data.get('hourly_wage', old_wage))
        
        update_data = {
            'name': data.get('name', old_data.get('name')),
            'hourly_wage': new_wage,
            'full_attendance_bonus': int(data.get('full_attendance_bonus', old_data.get('full_attendance_bonus', 100000))),
            'scheduled_days': data.get('scheduled_days', old_data.get('scheduled_days', '1,2,3,4,5')),
            'enabled': data.get('enabled', old_data.get('enabled', True)),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        if data.get('password'):
            update_data['password'] = generate_password_hash(data.get('password'))
        
        supabase.table('users').update(update_data).eq('id', emp_id).execute()
        
        if new_wage != old_wage:
            supabase.table('wage_history').insert({
                'employee_id': emp_id,
                'hourly_wage': new_wage,
                'effective_date': date.today().isoformat()
            }).execute()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/employees/<int:emp_id>', methods=['DELETE'])
@admin_required
def delete_employee(emp_id):
    """직원 비활성화"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    try:
        supabase.table('users').update({'enabled': False, 'updated_at': datetime.utcnow().isoformat()}).eq('id', emp_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/holidays', methods=['GET'])
@login_required
def get_holidays():
    """공휴일 목록"""
    year = request.args.get('year', date.today().year)
    month = request.args.get('month', date.today().month)
    
    if not DB_CONNECTED:
        return jsonify({'data': []})
    
    try:
        start_date = f"{year}-{int(month):02d}-01"
        _, last_day = calendar.monthrange(int(year), int(month))
        end_date = f"{year}-{int(month):02d}-{last_day}"
        
        response = supabase.table('holidays').select('*').gte('holiday_date', start_date).lte('holiday_date', end_date).order('holiday_date').execute()
        return jsonify({'success': True, 'data': response.data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/holidays', methods=['POST'])
@admin_required
def create_holiday():
    """공휴일 추가"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    data = request.get_json()
    try:
        response = supabase.table('holidays').insert({
            'holiday_date': data.get('date'),
            'name': data.get('name', '공휴일')
        }).execute()
        return jsonify({'success': True, 'data': response.data[0]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/holidays/<int:holiday_id>', methods=['DELETE'])
@admin_required
def delete_holiday(holiday_id):
    """공휴일 삭제"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    try:
        supabase.table('holidays').delete().eq('id', holiday_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/attendance', methods=['GET'])
@login_required
def get_attendance():
    """출퇴근 기록 조회"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    year = int(request.args.get('year', date.today().year))
    month = int(request.args.get('month', date.today().month))
    emp_id = request.args.get('employee_id')
    
    if session.get('user_role') == 'parttime':
        emp_id = session.get('user_id')
    elif not emp_id:
        return jsonify({'error': '직원 ID 필요'}), 400
    
    try:
        start_date = f"{year}-{month:02d}-01"
        _, last_day = calendar.monthrange(year, month)
        end_date = f"{year}-{month:02d}-{last_day}"
        
        response = supabase.table('attendance_logs').select('*').eq('employee_id', emp_id).gte('work_date', start_date).lte('work_date', end_date).order('work_date').execute()
        
        holidays_resp = supabase.table('holidays').select('holiday_date').gte('holiday_date', start_date).lte('holiday_date', end_date).execute()
        holidays = [h['holiday_date'] for h in holidays_resp.data]
        
        emp_resp = supabase.table('users').select('name, hourly_wage, full_attendance_bonus, scheduled_days').eq('id', emp_id).execute()
        emp_info = emp_resp.data[0] if emp_resp.data else {}
        
        approvals_resp = supabase.table('edit_approvals').select('approved_date, used').eq('employee_id', emp_id).execute()
        approvals = {a['approved_date']: not a['used'] for a in approvals_resp.data}
        
        confirm_resp = supabase.table('salary_confirmations').select('*').eq('employee_id', emp_id).eq('year_month', f"{year}-{month:02d}").execute()
        is_confirmed = len(confirm_resp.data) > 0
        confirmation_data = confirm_resp.data[0] if is_confirmed else None
        
        records = []
        # [수정됨] KST 기준 오늘 날짜 계산
        kst_today = get_kst_today().isoformat()

        for log in response.data:
            work_date = log['work_date']
            is_editable = work_date == kst_today or approvals.get(work_date, False)
            records.append({
                'id': log['id'],
                'work_date': work_date,
                'clock_in': log['clock_in'],
                'clock_out': log['clock_out'],
                'is_holiday_work': log.get('is_holiday_work', False),
                'is_editable': is_editable and not is_confirmed,
                'status': 'complete' if log['clock_in'] and log['clock_out'] else 'incomplete'
            })
        
        return jsonify({
            'success': True,
            'employee_id': emp_id,
            'employee_name': emp_info.get('name', ''),
            'hourly_wage': emp_info.get('hourly_wage', 10700),
            'full_attendance_bonus': emp_info.get('full_attendance_bonus', 100000),
            'scheduled_days': emp_info.get('scheduled_days', '1,2,3,4,5'),
            'year_month': f"{year}-{month:02d}",
            'records': records,
            'holidays': holidays,
            'is_confirmed': is_confirmed,
            'confirmation_data': confirmation_data
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/attendance', methods=['POST'])
@login_required
def create_attendance():
    """출퇴근 기록 생성/수정"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    data = request.get_json()
    work_date = data.get('work_date')
    clock_in = data.get('clock_in')
    clock_out = data.get('clock_out')
    
    if session.get('user_role') == 'parttime':
        emp_id = session.get('user_id')
    else:
        emp_id = data.get('employee_id')
    
    if not emp_id or not work_date:
        return jsonify({'error': '필수 정보 누락'}), 400
    
    # [수정됨] UTC 대신 KST(한국시간) 기준으로 오늘 날짜 계산
    today = get_kst_today().isoformat()

    if work_date != today and session.get('user_role') == 'parttime':
        approval = supabase.table('edit_approvals').select('id, used').eq('employee_id', emp_id).eq('approved_date', work_date).execute()
        if not approval.data or approval.data[0]['used']:
            return jsonify({'error': '수정 권한이 없습니다. 관리자 승인이 필요합니다.'}), 403
        supabase.table('edit_approvals').update({'used': True}).eq('id', approval.data[0]['id']).execute()
    
    try:
        existing = supabase.table('attendance_logs').select('id').eq('employee_id', emp_id).eq('work_date', work_date).execute()
        
        work_date_obj = date.fromisoformat(work_date)
        is_weekend = work_date_obj.weekday() >= 5
        holiday_check = supabase.table('holidays').select('id').eq('holiday_date', work_date).execute()
        is_holiday = len(holiday_check.data) > 0
        
        record_data = {
            'employee_id': emp_id,
            'work_date': work_date,
            'clock_in': clock_in,
            'clock_out': clock_out,
            'is_holiday_work': is_weekend or is_holiday,
            'updated_at': datetime.utcnow().isoformat()
        }
        
        if existing.data:
            supabase.table('attendance_logs').update(record_data).eq('id', existing.data[0]['id']).execute()
        else:
            supabase.table('attendance_logs').insert(record_data).execute()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/edit-approval', methods=['POST'])
@admin_required
def approve_edit():
    """특정 날짜 수정 승인"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    data = request.get_json()
    emp_id = data.get('employee_id')
    approved_date = data.get('date')
    
    if not emp_id or not approved_date:
        return jsonify({'error': '필수 정보 누락'}), 400
    
    try:
        existing = supabase.table('edit_approvals').select('id').eq('employee_id', emp_id).eq('approved_date', approved_date).execute()
        
        if existing.data:
            supabase.table('edit_approvals').update({'used': False, 'approved_at': datetime.utcnow().isoformat()}).eq('id', existing.data[0]['id']).execute()
        else:
            supabase.table('edit_approvals').insert({
                'employee_id': emp_id,
                'approved_date': approved_date,
                'used': False
            }).execute()
        
        return jsonify({'success': True, 'message': f'{approved_date} 수정 승인 완료'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/salary/calculate', methods=['GET'])
@login_required
def calculate_salary():
    """월급 계산"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    year = int(request.args.get('year', date.today().year))
    month = int(request.args.get('month', date.today().month))
    emp_id = request.args.get('employee_id')
    
    if session.get('user_role') == 'parttime':
        emp_id = session.get('user_id')
    elif not emp_id:
        return jsonify({'error': '직원 ID 필요'}), 400
    
    try:
        result = _calculate_monthly_salary(int(emp_id), year, month)
        return jsonify(result)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

def _calculate_monthly_salary(emp_id, year, month):
    """월급 계산 로직"""
    start_date = f"{year}-{month:02d}-01"
    _, last_day = calendar.monthrange(year, month)
    end_date = f"{year}-{month:02d}-{last_day}"
    
    emp_resp = supabase.table('users').select('*').eq('id', emp_id).execute()
    if not emp_resp.data:
        return {'error': '직원 정보 없음'}
    emp = emp_resp.data[0]
    hourly_wage = emp['hourly_wage']
    full_bonus = emp.get('full_attendance_bonus', 100000)
    scheduled_days = emp.get('scheduled_days', '1,2,3,4,5')  # 소정근로일 (0=일,1=월,...,6=토)
    scheduled_days_set = set(int(d) for d in scheduled_days.split(',') if d.strip())
    
    wage_history = supabase.table('wage_history').select('*').eq('employee_id', emp_id).lte('effective_date', end_date).order('effective_date', desc=True).execute()
    
    attendance_resp = supabase.table('attendance_logs').select('*').eq('employee_id', emp_id).gte('work_date', start_date).lte('work_date', end_date).order('work_date').execute()
    records = attendance_resp.data
    
    holidays_resp = supabase.table('holidays').select('holiday_date').gte('holiday_date', start_date).lte('holiday_date', end_date).execute()
    holidays = set(h['holiday_date'] for h in holidays_resp.data)
    
    incomplete_dates = []
    for r in records:
        if not r['clock_in'] or not r['clock_out']:
            incomplete_dates.append(r['work_date'])
    
    if incomplete_dates:
        return {
            'success': False,
            'error': 'INCOMPLETE_RECORDS',
            'message': '출퇴근 기록이 불완전합니다.',
            'incomplete_dates': incomplete_dates
        }
    
    base_pay = 0
    overtime_pay = 0
    total_hours = 0
    total_regular_hours = 0
    total_overtime_hours = 0
    work_days = len(records)
    details = []
    
    for r in records:
        work_date = r['work_date']
        clock_in = r['clock_in']
        clock_out = r['clock_out']
        
        applicable_wage = hourly_wage
        for wh in wage_history.data:
            if wh['effective_date'] <= work_date:
                applicable_wage = wh['hourly_wage']
                break
        
        regular_hrs, overtime_hrs = _calculate_daily_hours(clock_in, clock_out)
        total_daily = regular_hrs + overtime_hrs
        total_hours += total_daily
        total_regular_hours += regular_hrs
        total_overtime_hours += overtime_hrs
        
        is_special = r.get('is_holiday_work', False)
        multiplier = 1.5 if is_special else 1.0
        
        day_base = int(regular_hrs * applicable_wage * multiplier)
        day_overtime = int(overtime_hrs * applicable_wage * 1.5 * multiplier)
        
        base_pay += day_base
        overtime_pay += day_overtime
        
        details.append({
            'date': work_date,
            'clock_in': clock_in,
            'clock_out': clock_out,
            'hours': round(total_daily, 2),
            'regular_hours': round(regular_hrs, 2),
            'overtime_hours': round(overtime_hrs, 2),
            'wage': applicable_wage,
            'is_special': is_special,
            'base': day_base,
            'overtime': day_overtime
        })
    
    # 주휴수당: 해당 주의 일요일이 속한 달에 귀속
    weekly_holiday_pay = 0
    weekly_details = []
    
    # 해당 월의 모든 일요일 찾기
    sundays_in_month = []
    for day in range(1, last_day + 1):
        d = date(year, month, day)
        if d.weekday() == 6:
            sundays_in_month.append(d)
    
    # 각 일요일 기준으로 그 주(월~일) 전체 근무시간 계산
    for sunday in sundays_in_month:
        monday = sunday - timedelta(days=6)
        week_start = monday.isoformat()
        week_end = sunday.isoformat()
        
        week_attendance = supabase.table('attendance_logs').select('work_date, clock_in, clock_out').eq('employee_id', emp_id).gte('work_date', week_start).lte('work_date', week_end).execute()
        
        # 해당 주의 공휴일 조회 (월 경계 주에서도 정확히 체크)
        week_holidays_resp = supabase.table('holidays').select('holiday_date').gte('holiday_date', week_start).lte('holiday_date', week_end).execute()
        week_holidays = set(h['holiday_date'] for h in week_holidays_resp.data)
        
        week_total_hours = 0
        worked_dates = set()
        week_work_days = 0
        for rec in week_attendance.data:
            if rec['clock_in'] and rec['clock_out']:
                reg, ot = _calculate_daily_hours(rec['clock_in'], rec['clock_out'])
                week_total_hours += reg + ot
                worked_dates.add(rec['work_date'])
                week_work_days += 1
        
        # 소정근로일 계산
        required_work_dates = set()
        for i in range(7):
            d = monday + timedelta(days=i)
            # d.weekday(): 월=0, 화=1, ..., 일=6 → scheduled_days는 0=일, 1=월, ..., 6=토
            # 변환: (d.weekday() + 1) % 7 → 월=1, 화=2, ..., 일=0
            day_num = (d.weekday() + 1) % 7
            if day_num in scheduled_days_set and d.isoformat() not in week_holidays:
                required_work_dates.add(d.isoformat())
        
        # 주휴수당 조건: 15시간 이상 + 소정근로일 개근
        is_full_week_attendance = required_work_dates <= worked_dates
        is_eligible = week_total_hours >= 15 and is_full_week_attendance
        week_holiday_pay = int((week_total_hours / 5) * hourly_wage) if is_eligible else 0
        
        if is_eligible:
            weekly_holiday_pay += week_holiday_pay
        
        # 주휴수당 상세 내역 저장
        weekly_details.append({
            'week_start': week_start,
            'week_end': week_end,
            'sunday': sunday.isoformat(),
            'total_hours': round(week_total_hours, 2),
            'work_days': week_work_days,
            'required_days': len(required_work_dates),
            'is_full_attendance': is_full_week_attendance,
            'is_eligible': is_eligible,
            'holiday_pay': week_holiday_pay,
            'reason': '' if is_eligible else ('15시간 미만' if week_total_hours < 15 else '개근 미충족')
        })
    
    # 만근수당 계산 (소정근로일 기준)
    required_days = []
    for day in range(1, last_day + 1):
        d = date(year, month, day)
        # d.weekday(): 월=0, 화=1, ..., 일=6 → scheduled_days는 0=일, 1=월, ..., 6=토
        day_num = (d.weekday() + 1) % 7
        if day_num in scheduled_days_set and d.isoformat() not in holidays:
            required_days.append(d.isoformat())
    
    worked_days = set(r['work_date'] for r in records if r['clock_in'] and r['clock_out'])
    is_full_attendance = set(required_days) <= worked_days
    full_attendance_bonus = full_bonus if is_full_attendance else 0
    
    total_pay = base_pay + overtime_pay + weekly_holiday_pay + full_attendance_bonus
    
    return {
        'success': True,
        'employee_id': emp_id,
        'employee_name': emp['name'],
        'year_month': f"{year}-{month:02d}",
        'breakdown': {
            'base_pay': base_pay,
            'overtime_pay': overtime_pay,
            'weekly_holiday_pay': weekly_holiday_pay,
            'full_attendance_bonus': full_attendance_bonus,
            'total_pay': total_pay,
            'total_hours': round(total_hours, 2),
            'total_regular_hours': round(total_regular_hours, 2),
            'total_overtime_hours': round(total_overtime_hours, 2),
            'work_days': work_days,
            'is_full_attendance': is_full_attendance,
            'hourly_wage': hourly_wage
        },
        'details': details,
        'weekly_details': weekly_details,
        'required_days': len(required_days),
        'worked_days': len(worked_days)
    }

def _calculate_daily_hours(clock_in_str, clock_out_str):
    """일일 근무시간 계산"""
    if not clock_in_str or not clock_out_str:
        return 0.0, 0.0
    
    def time_to_minutes(t_str):
        parts = t_str.split(':')
        return int(parts[0]) * 60 + int(parts[1])
    
    start_min = time_to_minutes(clock_in_str)
    end_min = time_to_minutes(clock_out_str)
    
    if end_min <= start_min:
        return 0.0, 0.0
    
    total_min = end_min - start_min
    
    lunch_start = 12 * 60
    lunch_end = 13 * 60
    if start_min < lunch_end and end_min > lunch_start:
        overlap_start = max(start_min, lunch_start)
        overlap_end = min(end_min, lunch_end)
        total_min -= max(0, overlap_end - overlap_start)
    
    work_start = 9 * 60
    work_end = 18 * 60
    
    regular_start = max(start_min, work_start)
    regular_end = min(end_min, work_end)
    regular_min = max(0, regular_end - regular_start)
    
    if regular_start < lunch_end and regular_end > lunch_start:
        overlap_start = max(regular_start, lunch_start)
        overlap_end = min(regular_end, lunch_end)
        regular_min -= max(0, overlap_end - overlap_start)
    
    overtime_min = total_min - regular_min
    
    return regular_min / 60, max(0, overtime_min) / 60

@app.route('/api/salary/confirm', methods=['POST'])
@login_required
def confirm_salary():
    """월급 확정"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    data = request.get_json()
    year = int(data.get('year', date.today().year))
    month = int(data.get('month', date.today().month))
    
    emp_id = session.get('user_id') if session.get('user_role') == 'parttime' else data.get('employee_id')
    
    try:
        result = _calculate_monthly_salary(emp_id, year, month)
        if not result.get('success'):
            return jsonify(result), 400
        
        breakdown = result['breakdown']
        supabase.table('salary_confirmations').upsert({
            'employee_id': emp_id,
            'year_month': f"{year}-{month:02d}",
            'total_hours': breakdown['total_hours'],
            'base_pay': breakdown['base_pay'],
            'overtime_pay': breakdown['overtime_pay'],
            'weekly_holiday_pay': breakdown['weekly_holiday_pay'],
            'full_attendance_bonus': breakdown['full_attendance_bonus'],
            'total_amount': breakdown['total_pay'],
            'confirmed_at': datetime.utcnow().isoformat()
        }, on_conflict='employee_id,year_month').execute()
        
        return jsonify({'success': True, 'message': '월급 확정 완료', 'breakdown': breakdown})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/salary/confirmations', methods=['GET'])
@admin_required
def get_confirmations():
    """월급 확정 목록 조회"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    year = request.args.get('year', date.today().year)
    month = request.args.get('month', date.today().month)
    year_month = f"{year}-{int(month):02d}"
    
    try:
        response = supabase.table('salary_confirmations').select('*, users(name)').eq('year_month', year_month).execute()
        return jsonify({'success': True, 'data': response.data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/admin/attendance', methods=['GET'])
@admin_required
def admin_get_attendance():
    """모든 직원 출퇴근 조회"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    year = int(request.args.get('year', date.today().year))
    month = int(request.args.get('month', date.today().month))
    
    try:
        start_date = f"{year}-{month:02d}-01"
        _, last_day = calendar.monthrange(year, month)
        end_date = f"{year}-{month:02d}-{last_day}"
        
        employees = supabase.table('users').select('*').eq('role', 'parttime').eq('enabled', True).execute()
        
        result = []
        for emp in employees.data:
            attendance = supabase.table('attendance_logs').select('*').eq('employee_id', emp['id']).gte('work_date', start_date).lte('work_date', end_date).order('work_date').execute()
            confirmation = supabase.table('salary_confirmations').select('*').eq('employee_id', emp['id']).eq('year_month', f"{year}-{month:02d}").execute()
            
            # 급여 계산 결과 가져오기
            salary_calc = _calculate_monthly_salary(emp['id'], year, month)
            salary_breakdown = salary_calc.get('breakdown') if salary_calc.get('success') else None
            
            result.append({
                'employee': {
                    'id': emp['id'],
                    'name': emp['name'],
                    'hourly_wage': emp['hourly_wage']
                },
                'records': attendance.data,
                'is_confirmed': len(confirmation.data) > 0,
                'confirmation': confirmation.data[0] if confirmation.data else None,
                'salary_breakdown': salary_breakdown
            })
        
        return jsonify({'success': True, 'data': result, 'year_month': f"{year}-{month:02d}"})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== 출퇴근 수정 요청 API ====================

@app.route('/api/attendance-edit-request', methods=['POST'])
@login_required
def create_edit_request():
    """출퇴근 수정 요청 생성 (직원용)"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    if session.get('user_role') != 'parttime':
        return jsonify({'error': '직원만 요청할 수 있습니다'}), 403
    
    data = request.get_json()
    request_date = data.get('request_date')
    new_clock_in = data.get('new_clock_in')
    new_clock_out = data.get('new_clock_out')
    reason = data.get('reason', '').strip()
    
    if not request_date or not reason:
        return jsonify({'error': '날짜와 수정 사유는 필수입니다'}), 400
    
    emp_id = session.get('user_id')
    today = date.today()
    req_date = date.fromisoformat(request_date)
    
    # 이전 달 수정 불가 (단, 현재 달 첫째 주에 속하는 이전 달 날짜는 허용)
    if req_date.year < today.year or (req_date.year == today.year and req_date.month < today.month):
        # 현재 달의 첫 번째 일요일 찾기
        first_day_of_month = date(today.year, today.month, 1)
        days_until_sunday = (6 - first_day_of_month.weekday()) % 7
        if days_until_sunday == 0 and first_day_of_month.weekday() != 6:
            days_until_sunday = 7
        first_sunday = first_day_of_month + timedelta(days=days_until_sunday)
        
        # 첫째 주의 월요일 (일요일 - 6일)
        first_week_monday = first_sunday - timedelta(days=6)
        
        # 요청 날짜가 첫째 주 월요일 이전이면 거절
        if req_date < first_week_monday:
            return jsonify({'error': '이전 달의 기록은 수정 요청할 수 없습니다'}), 400
    
    # 미래 날짜 수정 불가
    if req_date > today:
        return jsonify({'error': '미래 날짜는 수정 요청할 수 없습니다'}), 400
    
    # 오늘 날짜는 직접 수정 가능하므로 요청 불필요
    if req_date == today:
        return jsonify({'error': '오늘 날짜는 직접 수정할 수 있습니다'}), 400
    
    try:
        # 기존 pending 요청 확인
        existing = supabase.table('attendance_edit_requests').select('id').eq('employee_id', emp_id).eq('request_date', request_date).eq('status', 'pending').execute()
        if existing.data:
            return jsonify({'error': '이미 해당 날짜에 대기 중인 요청이 있습니다'}), 400
        
        # 기존 출퇴근 기록 조회
        old_record = supabase.table('attendance_logs').select('clock_in, clock_out').eq('employee_id', emp_id).eq('work_date', request_date).execute()
        old_clock_in = old_record.data[0]['clock_in'] if old_record.data else None
        old_clock_out = old_record.data[0]['clock_out'] if old_record.data else None
        
        # 요청 생성
        supabase.table('attendance_edit_requests').insert({
            'employee_id': emp_id,
            'request_date': request_date,
            'old_clock_in': old_clock_in,
            'old_clock_out': old_clock_out,
            'new_clock_in': new_clock_in,
            'new_clock_out': new_clock_out,
            'reason': reason,
            'status': 'pending'
        }).execute()
        
        return jsonify({'success': True, 'message': '수정 요청이 전송되었습니다'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/attendance-edit-requests', methods=['GET'])
@admin_required
def get_edit_requests():
    """수정 요청 목록 조회 (관리자용)"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    status = request.args.get('status', 'pending')
    
    try:
        response = supabase.table('attendance_edit_requests').select('*, users(name)').eq('status', status).order('created_at', desc=True).execute()
        return jsonify({'success': True, 'data': response.data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/attendance-edit-request/<int:request_id>/approve', methods=['POST'])
@admin_required
def approve_edit_request(request_id):
    """수정 요청 승인 (관리자용)"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    try:
        # 요청 정보 조회
        req_resp = supabase.table('attendance_edit_requests').select('*').eq('id', request_id).execute()
        if not req_resp.data:
            return jsonify({'error': '요청을 찾을 수 없습니다'}), 404
        
        req = req_resp.data[0]
        if req['status'] != 'pending':
            return jsonify({'error': '이미 처리된 요청입니다'}), 400
        
        emp_id = req['employee_id']
        work_date = str(req['request_date'])[:10]  # YYYY-MM-DD 형식만 추출
        
        # 시간 값 안전하게 처리 (HH:MM:SS 형식으로 변환)
        def safe_time(val):
            if not val or str(val) in ('None', 'null', ''):
                return None
            s = str(val)
            # HH:MM:SS+00 또는 HH:MM:SS 형식에서 HH:MM:SS만 추출
            if '+' in s:
                s = s.split('+')[0]
            if len(s) >= 8:
                return s[:8]
            if len(s) == 5:  # HH:MM 형식이면 :00 추가
                return s + ':00'
            return s
        
        new_clock_in = safe_time(req.get('new_clock_in'))
        new_clock_out = safe_time(req.get('new_clock_out'))
        
        # 같은 날짜의 기존 approved/rejected 요청 삭제 (UNIQUE 제약 회피)
        supabase.table('attendance_edit_requests').delete().eq('employee_id', emp_id).eq('request_date', work_date).neq('id', request_id).neq('status', 'pending').execute()
        
        # 출퇴근 기록 업데이트
        work_date_obj = date.fromisoformat(work_date)
        is_weekend = work_date_obj.weekday() >= 5
        holiday_check = supabase.table('holidays').select('id').eq('holiday_date', work_date).execute()
        is_holiday = len(holiday_check.data) > 0
        
        existing = supabase.table('attendance_logs').select('id').eq('employee_id', emp_id).eq('work_date', work_date).execute()
        
        record_data = {
            'employee_id': emp_id,
            'work_date': work_date,
            'clock_in': new_clock_in,
            'clock_out': new_clock_out,
            'is_holiday_work': is_weekend or is_holiday,
            'updated_at': datetime.utcnow().isoformat()
        }
        
        if existing.data:
            supabase.table('attendance_logs').update(record_data).eq('id', existing.data[0]['id']).execute()
        else:
            supabase.table('attendance_logs').insert(record_data).execute()
        
        # 요청 상태 업데이트
        supabase.table('attendance_edit_requests').update({
            'status': 'approved',
            'processed_at': datetime.utcnow().isoformat()
        }).eq('id', request_id).execute()
        
        return jsonify({'success': True, 'message': '수정 요청이 승인되었습니다'})
    except Exception as e:
        import traceback
        print(f"[승인 오류] request_id={request_id}, error={str(e)}")
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/attendance-edit-request/<int:request_id>/reject', methods=['POST'])
@admin_required
def reject_edit_request(request_id):
    """수정 요청 거절 (관리자용)"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    data = request.get_json()
    reject_reason = data.get('reject_reason', '').strip()
    
    if not reject_reason:
        return jsonify({'error': '거절 사유를 입력해주세요'}), 400
    
    try:
        req_resp = supabase.table('attendance_edit_requests').select('status').eq('id', request_id).execute()
        if not req_resp.data:
            return jsonify({'error': '요청을 찾을 수 없습니다'}), 404
        
        if req_resp.data[0]['status'] != 'pending':
            return jsonify({'error': '이미 처리된 요청입니다'}), 400
        
        supabase.table('attendance_edit_requests').update({
            'status': 'rejected',
            'reject_reason': reject_reason,
            'viewed_rejection': False,
            'processed_at': datetime.utcnow().isoformat()
        }).eq('id', request_id).execute()
        
        return jsonify({'success': True, 'message': '수정 요청이 거절되었습니다'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/attendance-edit-requests/my', methods=['GET'])
@login_required
def get_my_edit_requests():
    """내 수정 요청 목록 조회 (직원용)"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    emp_id = session.get('user_id')
    
    try:
        # 미확인 거절 요청 조회
        rejected = supabase.table('attendance_edit_requests').select('*').eq('employee_id', emp_id).eq('status', 'rejected').eq('viewed_rejection', False).execute()
        
        # 대기 중인 요청 조회
        pending = supabase.table('attendance_edit_requests').select('*').eq('employee_id', emp_id).eq('status', 'pending').execute()
        
        return jsonify({
            'success': True,
            'rejected_unviewed': rejected.data,
            'pending': pending.data
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/attendance-edit-request/<int:request_id>/viewed', methods=['POST'])
@login_required
def mark_rejection_viewed(request_id):
    """거절 사유 확인 처리 (직원용)"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    emp_id = session.get('user_id')
    
    try:
        supabase.table('attendance_edit_requests').update({
            'viewed_rejection': True
        }).eq('id', request_id).eq('employee_id', emp_id).execute()
        
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== 메모장 API ====================

@app.route('/api/memos', methods=['GET'])
@admin_required
def get_memos():
    """메모 목록 조회"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    try:
        response = supabase.table('memos').select('*').order('is_pinned', desc=True).order('updated_at', desc=True).execute()
        return jsonify({'success': True, 'data': response.data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/memos', methods=['POST'])
@admin_required
def create_memo():
    """메모 생성"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    data = request.get_json()
    try:
        new_memo = {
            'title': data.get('title', '').strip() or '제목 없음',
            'content': data.get('content', ''),
            'is_pinned': data.get('is_pinned', False)
        }
        response = supabase.table('memos').insert(new_memo).execute()
        return jsonify({'success': True, 'data': response.data[0]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/memos/<int:memo_id>', methods=['PUT'])
@admin_required
def update_memo(memo_id):
    """메모 수정"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    data = request.get_json()
    try:
        update_data = {
            'title': data.get('title', '').strip() or '제목 없음',
            'content': data.get('content', ''),
            'is_pinned': data.get('is_pinned', False),
            'updated_at': datetime.utcnow().isoformat()
        }
        response = supabase.table('memos').update(update_data).eq('id', memo_id).execute()
        return jsonify({'success': True, 'data': response.data[0] if response.data else None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/memos/<int:memo_id>', methods=['DELETE'])
@admin_required
def delete_memo(memo_id):
    """메모 삭제"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    try:
        supabase.table('memos').delete().eq('id', memo_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/memos/<int:memo_id>/pin', methods=['POST'])
@admin_required
def toggle_memo_pin(memo_id):
    """메모 고정/해제"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    try:
        current = supabase.table('memos').select('is_pinned').eq('id', memo_id).execute()
        if not current.data:
            return jsonify({'error': '메모를 찾을 수 없습니다'}), 404
        new_pinned = not current.data[0]['is_pinned']
        supabase.table('memos').update({'is_pinned': new_pinned, 'updated_at': datetime.utcnow().isoformat()}).eq('id', memo_id).execute()
        return jsonify({'success': True, 'is_pinned': new_pinned})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== 품절상품 API ====================

@app.route('/api/out-of-stock', methods=['GET'])
@admin_required
def get_out_of_stock():
    """품절상품 목록 조회"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    try:
        show_restocked = request.args.get('show_restocked', 'false').lower() == 'true'
        query = supabase.table('out_of_stock').select('*')
        if not show_restocked:
            query = query.eq('is_restocked', False)
        response = query.order('out_date', desc=True).execute()
        return jsonify({'success': True, 'data': response.data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/out-of-stock', methods=['POST'])
@admin_required
def create_out_of_stock():
    """품절상품 등록"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    data = request.get_json()
    try:
        new_item = {
            'product_name': data.get('product_name', '').strip(),
            'out_date': data.get('out_date') or date.today().isoformat(),
            'restock_date': data.get('restock_date') or None,
            'notes': data.get('notes', ''),
            'is_restocked': False
        }
        if not new_item['product_name']:
            return jsonify({'error': '상품명은 필수입니다'}), 400
        response = supabase.table('out_of_stock').insert(new_item).execute()
        return jsonify({'success': True, 'data': response.data[0]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/out-of-stock/<int:item_id>', methods=['PUT'])
@admin_required
def update_out_of_stock(item_id):
    """품절상품 수정"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    data = request.get_json()
    try:
        update_data = {
            'product_name': data.get('product_name', '').strip(),
            'out_date': data.get('out_date'),
            'restock_date': data.get('restock_date') or None,
            'notes': data.get('notes', ''),
            'is_restocked': data.get('is_restocked', False),
            'updated_at': datetime.utcnow().isoformat()
        }
        if not update_data['product_name']:
            return jsonify({'error': '상품명은 필수입니다'}), 400
        response = supabase.table('out_of_stock').update(update_data).eq('id', item_id).execute()
        return jsonify({'success': True, 'data': response.data[0] if response.data else None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/out-of-stock/<int:item_id>', methods=['DELETE'])
@admin_required
def delete_out_of_stock(item_id):
    """품절상품 삭제"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    try:
        supabase.table('out_of_stock').delete().eq('id', item_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/out-of-stock/<int:item_id>/restock', methods=['POST'])
@admin_required
def mark_restocked(item_id):
    """재입고 완료 처리"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    try:
        supabase.table('out_of_stock').update({
            'is_restocked': True,
            'restock_date': date.today().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }).eq('id', item_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== 도착보장 입고내역서 API ====================

@app.route('/api/arrival-products', methods=['GET'])
@admin_required
def get_arrival_products():
    """도착보장 상품 목록 조회"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    try:
        response = supabase.table('arrival_guarantee_products').select('*').order('product_name').execute()
        return jsonify({'success': True, 'data': response.data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/arrival-products', methods=['POST'])
@admin_required
def create_arrival_product():
    """도착보장 상품 등록"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    data = request.get_json()
    try:
        new_product = {
            'product_name': data.get('product_name', '').strip(),
            'barcode': data.get('barcode', '').strip()
        }
        if not new_product['product_name'] or not new_product['barcode']:
            return jsonify({'error': '상품명과 바코드는 필수입니다'}), 400
        response = supabase.table('arrival_guarantee_products').insert(new_product).execute()
        return jsonify({'success': True, 'data': response.data[0]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/arrival-products/<int:product_id>', methods=['PUT'])
@admin_required
def update_arrival_product(product_id):
    """도착보장 상품 수정"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    data = request.get_json()
    try:
        update_data = {
            'product_name': data.get('product_name', '').strip(),
            'barcode': data.get('barcode', '').strip(),
            'updated_at': datetime.utcnow().isoformat()
        }
        if not update_data['product_name'] or not update_data['barcode']:
            return jsonify({'error': '상품명과 바코드는 필수입니다'}), 400
        response = supabase.table('arrival_guarantee_products').update(update_data).eq('id', product_id).execute()
        return jsonify({'success': True, 'data': response.data[0] if response.data else None})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/arrival-products/<int:product_id>', methods=['DELETE'])
@admin_required
def delete_arrival_product(product_id):
    """도착보장 상품 삭제"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    try:
        supabase.table('arrival_guarantee_products').delete().eq('id', product_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/arrival-customer-id', methods=['GET'])
@admin_required
def get_arrival_customer_id():
    """고객ID 조회"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    try:
        response = supabase.table('system_settings').select('value').eq('key', 'arrival_customer_id').execute()
        customer_id = response.data[0]['value'] if response.data else ''
        return jsonify({'success': True, 'customer_id': customer_id})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/arrival-customer-id', methods=['POST'])
@admin_required
def save_arrival_customer_id():
    """고객ID 저장"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    data = request.get_json()
    customer_id = data.get('customer_id', '').strip()
    try:
        existing = supabase.table('system_settings').select('key').eq('key', 'arrival_customer_id').execute()
        if existing.data:
            supabase.table('system_settings').update({
                'value': customer_id,
                'updated_at': datetime.utcnow().isoformat()
            }).eq('key', 'arrival_customer_id').execute()
        else:
            supabase.table('system_settings').insert({
                'key': 'arrival_customer_id',
                'value': customer_id
            }).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/arrival-invoice/generate', methods=['POST'])
@admin_required
def generate_arrival_invoice():
    """입고내역서 PDF 생성 (로컬 폰트 파일 직접 사용)"""
    from weasyprint import HTML
    from weasyprint.text.fonts import FontConfiguration
    from urllib.parse import quote
    import zipfile
    import os
    
    data = request.get_json()
    items = data.get('items', [])
    delivery_type = data.get('delivery_type', '화물')
    generate_separate = data.get('generate_separate', False)
    
    if not items:
        return jsonify({'error': '상품 정보가 없습니다'}), 400
    
    # [수정됨] 프로젝트 내부의 fonts 폴더 경로를 찾습니다.
    # 현재 app.py가 있는 위치를 기준으로 fonts/NanumGothic.ttf를 찾습니다.
    base_dir = os.path.dirname(os.path.abspath(__file__))
    font_path = os.path.join(base_dir, 'fonts', 'NanumGothic.ttf')
    
    # 혹시 모를 경로 오류 방지를 위해 절대 경로로 변환
    if not os.path.exists(font_path):
        print(f"⚠️ 경고: 폰트 파일을 찾을 수 없습니다: {font_path}")
        # 파일이 없으면 시스템 폰트로 폴백되도록 경로를 비워둡니다 (에러 방지)
        font_url = ""
    else:
        # WeasyPrint는 file:// 프로토콜을 좋아합니다.
        font_url = f"file://{font_path}"

    def create_pdf(item_list, doc_type):
        rows_html = ""
        for idx, item in enumerate(item_list, 1):
            rows_html += f"""
            <tr>
                <td>{idx}</td>
                <td>{item.get('customer_id', '')}</td>
                <td>{item.get('arrival_date', '')}</td>
                <td>{item.get('product_name', '')}</td>
                <td>{item.get('barcode', '')}</td>
                <td>{item.get('quantity', '')}</td>
                <td>{item.get('note', '')}</td>
            </tr>
            """
        
        for idx in range(len(item_list) + 1, 11):
            rows_html += f"""
            <tr>
                <td>{idx}</td>
                <td></td>
                <td></td>
                <td></td>
                <td></td>
                <td></td>
                <td></td>
            </tr>
            """
        
        # [수정됨] CSS에서 로컬 파일 경로를 직접 src로 지정합니다.
        html_content = f"""
        <!DOCTYPE html>
        <html lang="ko">
        <head>
            <meta charset="UTF-8">
            <style>
                /* 여기서 로컬 폰트를 정의합니다 */
                @font-face {{
                    font-family: 'MyNanum';
                    src: url('{font_url}') format('truetype');
                }}
                
                @page {{
                    size: A4 landscape;
                    margin: 15mm;
                }}
                body {{
                    /* 정의한 'MyNanum' 폰트를 우선 적용 */
                    font-family: 'MyNanum', 'NanumGothic', sans-serif;
                    margin: 0;
                    padding: 0;
                    word-break: keep-all;
                }}
                h1 {{
                    text-align: center;
                    font-size: 24px;
                    margin-bottom: 20px;
                    font-weight: bold;
                }}
                table {{
                    width: 100%;
                    border-collapse: collapse;
                    font-size: 11px;
                }}
                th, td {{
                    border: 1px solid #000;
                    padding: 8px 5px;
                    text-align: center;
                    vertical-align: middle;
                }}
                th {{
                    background-color: #e0e0e0;
                    font-weight: bold;
                    font-size: 12px;
                }}
                tr {{
                    height: 28px;
                }}
            </style>
        </head>
        <body>
            <h1>입고 내역서({doc_type})</h1>
            <table>
                <thead>
                    <tr>
                        <th style="width: 5%;">No.</th>
                        <th style="width: 12%;">고객ID</th>
                        <th style="width: 12%;">입고예정일</th>
                        <th style="width: 30%;">상품명</th>
                        <th style="width: 18%;">상품바코드</th>
                        <th style="width: 10%;">수량(EA)</th>
                        <th style="width: 13%;">특이사항</th>
                    </tr>
                </thead>
                <tbody>
                    {rows_html}
                </tbody>
            </table>
        </body>
        </html>
        """
        
        font_config = FontConfiguration()
        pdf_buffer = BytesIO()
        HTML(string=html_content).write_pdf(pdf_buffer, font_config=font_config)
        pdf_buffer.seek(0)
        return pdf_buffer
    
    # ... (파일명 생성 및 다운로드 로직은 기존과 동일) ...
    def get_filename(item_list):
        if item_list:
            arrival_date = item_list[0].get('arrival_date', '')
            if len(arrival_date) >= 8:
                mmdd = arrival_date[4:8]
            else:
                mmdd = datetime.now().strftime('%m%d')
            
            if len(item_list) == 1:
                product_name = item_list[0].get('product_name', '상품').replace(' ', '')
            else:
                product_name = f"{len(item_list)}개상품"
            
            return f"{mmdd}입고내역서_{product_name}.pdf"
        return "입고내역서.pdf"
    
    def send_pdf_response(buffer, filename):
        buffer.seek(0)
        response = make_response(buffer.read())
        response.headers['Content-Type'] = 'application/pdf'
        encoded_filename = quote(filename)
        response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{encoded_filename}"
        return response
    
    def send_zip_response(buffer, filename):
        buffer.seek(0)
        response = make_response(buffer.read())
        response.headers['Content-Type'] = 'application/zip'
        encoded_filename = quote(filename)
        response.headers['Content-Disposition'] = f"attachment; filename*=UTF-8''{encoded_filename}"
        return response
    
    try:
        if generate_separate and len(items) > 1:
            zip_buffer = BytesIO()
            with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                for item in items:
                    pdf_buffer = create_pdf([item], delivery_type)
                    filename = get_filename([item])
                    zip_file.writestr(filename, pdf_buffer.getvalue())
            
            arrival_date = items[0].get('arrival_date', '')
            mmdd = arrival_date[4:8] if len(arrival_date) >= 8 else datetime.now().strftime('%m%d')
            zip_filename = f"{mmdd}입고내역서_{len(items)}개상품.zip"
            
            return send_zip_response(zip_buffer, zip_filename)
        else:
            pdf_buffer = create_pdf(items, delivery_type)
            filename = get_filename(items)
            return send_pdf_response(pdf_buffer, filename)
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# ==================== 박스 재고 관리 API ====================

@app.route('/api/box-inventory', methods=['GET'])
@login_required
def get_box_inventory():
    """박스 재고 목록 조회"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    try:
        response = supabase.table('box_inventory').select('*').order('id').execute()
        return jsonify({'success': True, 'data': response.data})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/box-inventory', methods=['POST'])
@login_required
def save_box_inventory():
    """박스 재고 저장 (Upsert)"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    data = request.get_json()
    items = data.get('items', [])
    
    if not items:
        return jsonify({'error': '저장할 데이터가 없습니다'}), 400
    
    try:
        saved_count = 0
        for item in items:
            record = {
                'name_cj': item.get('name_cj', ''),
                'name_box4u': item.get('name_box4u', ''),
                'name_official': item.get('name_official', ''),
                'spec': item.get('spec', ''),
                'material': item.get('material', ''),
                'strength': item.get('strength', ''),
                'print_type': item.get('print_type', '무지'),
                'price': int(item.get('price', 0) or 0),
                'vendor': item.get('vendor', 'CJ'),
                'moq_pallet': int(item.get('moq_pallet', 0) or 0),
                'moq_piece': int(item.get('moq_piece', 0) or 0),
                'stock_cj': float(item.get('stock_cj', 0) or 0),
                'stock_hyojin': float(item.get('stock_hyojin', 0) or 0),
                'purpose': item.get('purpose', ''),
                'updated_at': datetime.utcnow().isoformat()
            }
            
            item_id = item.get('id')
            if item_id and str(item_id).isdigit():
                supabase.table('box_inventory').update(record).eq('id', int(item_id)).execute()
            else:
                supabase.table('box_inventory').insert(record).execute()
            saved_count += 1
        
        return jsonify({'success': True, 'message': f'{saved_count}개 항목 저장 완료'})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/api/box-inventory/<int:item_id>', methods=['DELETE'])
@login_required
def delete_box_inventory(item_id):
    """박스 재고 삭제"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    try:
        supabase.table('box_inventory').delete().eq('id', item_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ==================== 데이터 분석 기능 ====================

def save_sales_data_to_db(df):
    """엑셀 데이터를 DB에 저장 (배치 처리로 최적화)"""
    if not DB_CONNECTED or not supabase:
        return 0

    column_mapping = {
        '판매사이트명': ['판매사이트명', '판매사이트', '판매처', '채널', '쇼핑몰명', '쇼핑몰', '마켓'],
        '수집일': ['수집일', '수집일자'],
        '주문일': ['주문일', '주문일시', '주문일자', '주문 일시', '결제완료일'],
        '결제일': ['결제일', '결제일시', '결제일자', '결제 일시'],
        '상품명': ['상품명', '상품명-홍보', '상품명(옵션포함)', '쇼핑몰 상품명', '주문상품명', '상품', '품명'],
        '주문선택사항': ['주문선택사항', '옵션', '옵션정보', '옵션명', '선택옵션'],
        '판매가': ['판매가', '총판매가', '상품금액', '결제금액', '판매단가', '단가', '금액', '상품 금액'],
        '주문수량': ['주문수량', '총주문수량', '수량', '주문 수량'],
        '배송비금액': ['배송비금액', '총배송비금액', '배송비', '배송비 금액'],
        '구매자ID': ['구매자ID', '구매자아이디', '구매자 아이디', '주문자ID', '주문자아이디'],
        '구매자명': ['구매자명', '주문자명', '주문자', '구매자', '구매자 이름'],
        '구매자휴대폰번호': ['구매자휴대폰번호', '구매자휴대폰', '구매자연락처', '주문자연락처', '주문자휴대폰', '구매자 연락처'],
        '수령자명': ['수령자명', '받는분', '수취인', '수취인명', '받는분 이름', '수령자'],
        '수령자휴대폰번호': ['수령자휴대폰번호', '수령자휴대폰', '수령자연락처', '받는분연락처', '수취인휴대폰', '받는분 연락처', '수령자 연락처'],
        '배송지주소': ['배송지주소', '배송지', '주소', '배송주소', '받는분 주소', '수령자주소'],
        '주문번호': ['주문번호', '주문고유번호', '주문ID', '주문No', '쇼핑몰 주문번호', '쇼핑몰주문번호', '주문 번호']
    }

    def find_column(df_cols, possible_names):
        for name in possible_names:
            if name in df_cols:
                return name
        return None

    batch_id = datetime.now().strftime('%Y%m%d%H%M%S')
    sales_records = []
    customer_data = {}  # phone -> {구매자명, 구매자ID, 주문수, 총금액, 선물수, 주소}
    df_cols = df.columns.tolist()

    # 디버깅: 엑셀 컬럼 출력
    print(f"📋 엑셀 컬럼 목록: {df_cols}")

    # 매핑된 컬럼 확인
    mapped_cols = {}
    for target_col, source_cols in column_mapping.items():
        source_col = find_column(df_cols, source_cols)
        mapped_cols[target_col] = source_col
    print(f"📋 컬럼 매핑 결과: {mapped_cols}")

    # 필수 컬럼 체크
    if not mapped_cols.get('상품명'):
        print("⚠️ 상품명 컬럼을 찾을 수 없습니다!")
    if not mapped_cols.get('판매가'):
        print("⚠️ 판매가 컬럼을 찾을 수 없습니다!")

    # 1단계: 판매 데이터 준비 + 고객 데이터 집계 (DB 호출 없음)
    for _, row in df.iterrows():
        record = {'upload_batch_id': batch_id}

        for target_col, source_cols in column_mapping.items():
            source_col = find_column(df_cols, source_cols)
            if source_col:
                value = row.get(source_col)
                if pd.isna(value):
                    value = None
                elif target_col in ['판매가', '배송비금액']:
                    value = float(value) if value else 0
                elif target_col == '주문수량':
                    value = int(value) if value else 1
                elif target_col in ['주문일', '결제일', '수집일']:
                    if value:
                        try:
                            # Excel datetime, Timestamp, 문자열 모두 처리
                            if isinstance(value, datetime):
                                value = value.isoformat()
                            elif hasattr(value, 'isoformat'):
                                value = value.isoformat()
                            else:
                                # 한국어 오전/오후 형식 처리 (예: "2026-01-23 오전 1:58:36")
                                str_value = str(value)
                                if '오전' in str_value or '오후' in str_value:
                                    import re
                                    # "2026-01-23 오전 1:58:36" 또는 "2026-01-23 오후 1:58:36"
                                    match = re.match(r'(\d{4}-\d{2}-\d{2})\s*(오전|오후)\s*(\d{1,2}):(\d{2}):?(\d{2})?', str_value)
                                    if match:
                                        date_part = match.group(1)
                                        ampm = match.group(2)
                                        hour = int(match.group(3))
                                        minute = match.group(4)
                                        second = match.group(5) or '00'

                                        # 오후이고 12시가 아니면 +12, 오전 12시면 0시로
                                        if ampm == '오후' and hour != 12:
                                            hour += 12
                                        elif ampm == '오전' and hour == 12:
                                            hour = 0

                                        value = f"{date_part}T{hour:02d}:{minute}:{second}"
                                    else:
                                        value = None
                                else:
                                    parsed = pd.to_datetime(value, errors='coerce')
                                    if pd.notna(parsed):
                                        value = parsed.isoformat()
                                    else:
                                        value = None
                        except Exception as date_err:
                            print(f"날짜 파싱 오류: {date_err}, 원본값: {value}")
                            value = None
                else:
                    value = str(value) if value else None
                record[target_col] = value

        product_name = record.get('상품명', '')
        selling_price = record.get('판매가', 0) or 0
        quantity = record.get('주문수량', 1) or 1
        site_name = record.get('판매사이트명', '')

        cost = find_matching_cost(product_name)
        fee_rate = get_platform_fee_rate(site_name)
        fee = selling_price * fee_rate
        profit = (selling_price - cost - fee) * quantity

        record['원가'] = cost
        record['수수료'] = round(fee, 2)
        record['순이익'] = round(profit, 2)

        buyer = (record.get('구매자명') or '').strip()
        recipient = (record.get('수령자명') or '').strip()
        record['is_gift'] = buyer != recipient if (buyer and recipient) else False

        # 고객 데이터 집계
        phone = record.get('구매자휴대폰번호')
        order_number = record.get('주문번호')
        if phone:
            if phone not in customer_data:
                customer_data[phone] = {
                    '구매자명': record.get('구매자명'),
                    '구매자ID': record.get('구매자ID'),
                    '주문수': 0,
                    '총금액': 0,
                    '선물수': 0,
                    '주소': record.get('배송지주소'),
                    '주문일': record.get('주문일'),
                    '처리된_주문번호': set()  # 주문번호 중복 체크용
                }
            # 주문번호 기준으로 주문수 카운트 (같은 주문번호는 1회로)
            if order_number and order_number not in customer_data[phone]['처리된_주문번호']:
                customer_data[phone]['주문수'] += 1
                customer_data[phone]['처리된_주문번호'].add(order_number)
            elif not order_number:
                # 주문번호가 없는 경우 기존 방식으로 카운트
                customer_data[phone]['주문수'] += 1
            # 총금액: 판매가 + 배송비
            shipping_fee = record.get('배송비금액', 0) or 0
            customer_data[phone]['총금액'] += selling_price + shipping_fee
            if record['is_gift']:
                customer_data[phone]['선물수'] += 1

        sales_records.append(record)

    # 2단계: 기존 고객 한번에 조회 (1번 쿼리)
    existing_customers = {}
    if customer_data:
        try:
            phones = list(customer_data.keys())
            response = supabase.table('customers').select('*').in_('휴대폰번호', phones).execute()
            for c in (response.data or []):
                existing_customers[c['휴대폰번호']] = c
        except Exception as e:
            print(f"고객 조회 오류: {e}")

    # 3단계: 고객 데이터 처리 (upsert 방식으로 최적화)
    upsert_customers = []
    
    for phone, data in customer_data.items():
        if phone not in existing_customers:
            # 신규 고객
            upsert_customers.append({
                '휴대폰번호': phone,
                '구매자명': data['구매자명'],
                '구매자ID': data['구매자ID'],
                '첫구매일': data['주문일'],
                '최근구매일': data['주문일'],
                '총주문횟수': data['주문수'],
                '총구매금액': data['총금액'],
                '선물발송횟수': data['선물수'],
                '주요배송지': data['주소']
            })
        else:
            # 기존 고객 - 누적 값으로 upsert
            existing = existing_customers[phone]
            upsert_customers.append({
                '휴대폰번호': phone,
                '구매자명': data['구매자명'] or existing.get('구매자명'),
                '구매자ID': data['구매자ID'] or existing.get('구매자ID'),
                '첫구매일': existing.get('첫구매일'),  # 기존 값 유지
                '최근구매일': data['주문일'],
                '총주문횟수': (existing.get('총주문횟수') or 0) + data['주문수'],
                '총구매금액': (existing.get('총구매금액') or 0) + data['총금액'],
                '선물발송횟수': (existing.get('선물발송횟수') or 0) + data['선물수'],
                '주요배송지': data['주소'] or existing.get('주요배송지')
            })

    # 배치 upsert (1번 쿼리로 처리)
    if upsert_customers:
        try:
            supabase.table('customers').upsert(upsert_customers, on_conflict='휴대폰번호').execute()
            print(f"👥 고객 데이터 {len(upsert_customers)}건 upsert 완료")
        except Exception as e:
            print(f"고객 upsert 오류: {e}")

    # 4단계: 중복 체크 및 판매 데이터 저장
    try:
        if not sales_records:
            return 0
            
        # 주문번호 기반 중복 체크 (최근 7일 데이터만)
        order_nums = list(set([r.get('주문번호') for r in sales_records if r.get('주문번호')]))
        existing_orders = set()
        
        if order_nums:
            try:
                week_ago = (datetime.now() - timedelta(days=7)).isoformat()
                # 500개씩 나눠서 조회 (Supabase 제한)
                for i in range(0, len(order_nums), 500):
                    batch_nums = order_nums[i:i+500]
                    response = supabase.table('sales_data').select('주문번호').gte('주문일', week_ago).in_('주문번호', batch_nums).execute()
                    for d in (response.data or []):
                        if d.get('주문번호'):
                            existing_orders.add(d['주문번호'])
            except Exception as e:
                print(f"중복 체크 오류 (무시하고 진행): {e}")

        # 중복 제거
        if existing_orders:
            original_count = len(sales_records)
            sales_records = [r for r in sales_records if r.get('주문번호') not in existing_orders]
            skipped = original_count - len(sales_records)
            if skipped > 0:
                print(f"⚠️ 중복 주문 {skipped}건 스킵")

        if not sales_records:
            print("ℹ️ 저장할 새 데이터 없음 (모두 중복)")
            return 0

        print(f"📊 판매 데이터 {len(sales_records)}건 저장 시도...")
        if sales_records:
            sample = sales_records[0]
            print(f"   샘플: 상품명={str(sample.get('상품명', 'N/A'))[:30]}, 주문일={sample.get('주문일', 'N/A')}")
        
        # 500건씩 배치 처리
        batch_size = 500
        for i in range(0, len(sales_records), batch_size):
            batch = sales_records[i:i+batch_size]
            supabase.table('sales_data').insert(batch).execute()
        
        print(f"✅ 판매 데이터 {len(sales_records)}건 DB 저장 성공!")
        return len(sales_records)
    except Exception as e:
        import traceback
        print(f"❌ 판매 데이터 저장 오류: {e}")
        traceback.print_exc()
        return 0


@app.route('/api/analytics/summary', methods=['GET'])
@admin_required
def get_analytics_summary():
    """KPI 요약 데이터 (프리셋 또는 커스텀 날짜 범위)"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400

    period = request.args.get('period', 'month')
    custom_start = request.args.get('start_date')  # YYYY-MM-DD
    custom_end = request.args.get('end_date')      # YYYY-MM-DD

    try:
        today = get_kst_today()
        start_date = None
        end_date = None
        
        # 커스텀 날짜 범위가 있으면 사용
        if custom_start:
            start_date = datetime.strptime(custom_start, '%Y-%m-%d').date()
        elif period == 'day':
            start_date = today
        elif period == 'week':
            start_date = today - timedelta(days=7)
        elif period == 'month':
            start_date = today - timedelta(days=30)
        elif period == 'quarter':
            start_date = today - timedelta(days=90)
        elif period == 'half':
            start_date = today - timedelta(days=180)
        elif period == 'year':
            start_date = today - timedelta(days=365)
        # period == 'all' 이면 start_date = None
        
        if custom_end:
            end_date = datetime.strptime(custom_end, '%Y-%m-%d').date()

        query = supabase.table('sales_data').select('판매가, 주문수량, 순이익, 주문일, 주문번호, 배송비금액')
        if start_date:
            query = query.gte('주문일', start_date.isoformat())
        if end_date:
            # end_date의 다음날 00:00 이전까지
            end_date_next = end_date + timedelta(days=1)
            query = query.lt('주문일', end_date_next.isoformat())

        response = query.execute()
        data = response.data or []

        # 매출: 각 row의 (판매가 + 배송비) 합산
        total_revenue = sum(
            float(d.get('판매가', 0) or 0) + float(d.get('배송비금액', 0) or 0)
            for d in data
        )
        total_profit = sum(float(d.get('순이익', 0) or 0) for d in data)
        # 주문 수: 주문번호 기준 고유 개수 (같은 주문의 여러 상품 중복 제거)
        unique_order_numbers = set(d.get('주문번호') for d in data if d.get('주문번호'))
        total_orders = len(unique_order_numbers) if unique_order_numbers else len(data)
        aov = total_revenue / total_orders if total_orders > 0 else 0
        margin_rate = (total_profit / total_revenue * 100) if total_revenue > 0 else 0

        return jsonify({
            'success': True,
            'data': {
                'total_revenue': round(total_revenue, 0),
                'total_profit': round(total_profit, 0),
                'total_orders': total_orders,
                'aov': round(aov, 0),
                'margin_rate': round(margin_rate, 1)
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/analytics/platform', methods=['GET'])
@admin_required
def get_analytics_platform():
    """플랫폼별 매출/순이익 비교"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400

    try:
        response = supabase.table('sales_data').select('판매사이트명, 판매가, 주문수량, 순이익, 주문번호, 배송비금액').execute()
        data = response.data or []

        platform_stats = {}
        platform_orders = {}  # 플랫폼별 고유 주문번호 추적
        for d in data:
            site = d.get('판매사이트명') or '기타'
            if site not in platform_stats:
                platform_stats[site] = {'revenue': 0, 'profit': 0, 'orders': 0}
                platform_orders[site] = set()

            # 매출: 각 row의 (판매가 + 배송비) 합산
            revenue = float(d.get('판매가', 0) or 0) + float(d.get('배송비금액', 0) or 0)
            profit = float(d.get('순이익', 0) or 0)

            platform_stats[site]['revenue'] += revenue
            platform_stats[site]['profit'] += profit

            # 주문 수: 주문번호 기준 고유 개수
            order_number = d.get('주문번호')
            if order_number and order_number not in platform_orders[site]:
                platform_orders[site].add(order_number)
                platform_stats[site]['orders'] += 1
            elif not order_number:
                platform_stats[site]['orders'] += 1

        result = [{'platform': k, **v} for k, v in platform_stats.items()]
        result.sort(key=lambda x: x['revenue'], reverse=True)

        return jsonify({'success': True, 'data': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/analytics/time-heatmap', methods=['GET'])
@admin_required
def get_analytics_time_heatmap():
    """요일/시간대별 주문량"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400

    try:
        response = supabase.table('sales_data').select('주문일').execute()
        data = response.data or []

        heatmap = {}
        days = ['월', '화', '수', '목', '금', '토', '일']

        for d in data:
            order_date = d.get('주문일')
            if order_date:
                try:
                    dt = datetime.fromisoformat(order_date.replace('Z', '+00:00'))
                    day = days[dt.weekday()]
                    hour = dt.hour

                    if day not in heatmap:
                        heatmap[day] = {}
                    if hour not in heatmap[day]:
                        heatmap[day][hour] = 0
                    heatmap[day][hour] += 1
                except:
                    pass

        return jsonify({'success': True, 'data': heatmap})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/analytics/repurchase', methods=['GET'])
@admin_required
def get_analytics_repurchase():
    """재구매율 분석 (sales_data 기반)"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400

    try:
        response = supabase.table('sales_data').select('구매자휴대폰번호, 주문번호').execute()
        data = response.data or []

        # 휴대폰번호별 고유 주문 횟수 집계 (주문번호 기준 중복 제거)
        phone_orders = {}  # {phone: set(order_numbers)}
        for d in data:
            phone = d.get('구매자휴대폰번호')
            order_number = d.get('주문번호')
            if phone:
                if phone not in phone_orders:
                    phone_orders[phone] = set()
                if order_number:
                    phone_orders[phone].add(order_number)
                else:
                    # 주문번호가 없으면 row 단위로 카운트
                    phone_orders[phone].add(f"__no_order_{len(phone_orders[phone])}")

        # 고유 주문 수 기준으로 계산
        phone_counts = {phone: len(orders) for phone, orders in phone_orders.items()}

        new_customers = sum(1 for count in phone_counts.values() if count == 1)
        repeat_customers = sum(1 for count in phone_counts.values() if count > 1)

        total = new_customers + repeat_customers
        return jsonify({
            'success': True,
            'data': {
                'new_customers': new_customers,
                'repeat_customers': repeat_customers,
                'repeat_rate': round(repeat_customers / total * 100, 1) if total > 0 else 0
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/analytics/gift', methods=['GET'])
@admin_required
def get_analytics_gift():
    """선물하기 비율 분석"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400

    try:
        response = supabase.table('sales_data').select('is_gift, 주문번호').execute()
        data = response.data or []

        # 주문번호 기준 중복 제거하여 집계
        self_orders = set()
        gift_orders = set()
        self_count_no_order = 0
        gift_count_no_order = 0

        for d in data:
            order_number = d.get('주문번호')
            is_gift = d.get('is_gift')

            if order_number:
                if is_gift:
                    gift_orders.add(order_number)
                else:
                    self_orders.add(order_number)
            else:
                # 주문번호가 없으면 row 단위로 카운트
                if is_gift:
                    gift_count_no_order += 1
                else:
                    self_count_no_order += 1

        self_purchase = len(self_orders) + self_count_no_order
        gift_purchase = len(gift_orders) + gift_count_no_order

        total = self_purchase + gift_purchase
        return jsonify({
            'success': True,
            'data': {
                'self_purchase': self_purchase,
                'gift_purchase': gift_purchase,
                'gift_rate': round(gift_purchase / total * 100, 1) if total > 0 else 0
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/analytics/top-products', methods=['GET'])
@admin_required
def get_analytics_top_products():
    """상품+옵션 분석 (상세/전체, 페이지네이션)"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400

    mode = request.args.get('mode', 'all')  # 'all' or 'detail'
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 10))

    try:
        response = supabase.table('sales_data').select('상품명, 주문선택사항, 주문수량, 판매가, 판매사이트명, 배송비금액').execute()
        data = response.data or []

        if mode == 'detail':
            # 상세: 플랫폼별로 구분
            product_stats = {}
            for d in data:
                product = d.get('상품명') or '알 수 없음'
                option = d.get('주문선택사항') or ''
                platform = d.get('판매사이트명') or '기타'

                # 플랫폼 간소화
                if '쿠팡' in platform:
                    platform = '쿠팡'
                elif '스마트스토어' in platform or '네이버' in platform:
                    platform = '스마트스토어'
                elif '11번가' in platform:
                    platform = '11번가'
                elif 'ESM' in platform or 'G마켓' in platform or '옥션' in platform:
                    platform = 'ESM'
                else:
                    platform = '기타'

                key = f"{product}|{option}|{platform}"
                qty = int(d.get('주문수량', 1) or 1)
                # 매출: 판매가 + 배송비
                price = float(d.get('판매가', 0) or 0)
                shipping = float(d.get('배송비금액', 0) or 0)
                revenue = price + shipping

                if key not in product_stats:
                    product_stats[key] = {
                        'product': f"{product} | {option}" if option else product,
                        'platform': platform,
                        'quantity': 0,
                        'revenue': 0
                    }
                product_stats[key]['quantity'] += qty
                product_stats[key]['revenue'] += revenue

            sorted_products = sorted(product_stats.values(), key=lambda x: x['quantity'], reverse=True)
        else:
            # 전체: 플랫폼 구분 없이
            product_stats = {}
            for d in data:
                product = d.get('상품명') or '알 수 없음'
                option = d.get('주문선택사항') or ''
                key = f"{product} | {option}" if option else product
                qty = int(d.get('주문수량', 1) or 1)
                # 매출: 판매가 + 배송비
                price = float(d.get('판매가', 0) or 0)
                shipping = float(d.get('배송비금액', 0) or 0)
                revenue = price + shipping

                if key not in product_stats:
                    product_stats[key] = {'product': key, 'quantity': 0, 'revenue': 0}
                product_stats[key]['quantity'] += qty
                product_stats[key]['revenue'] += revenue

            sorted_products = sorted(product_stats.values(), key=lambda x: x['quantity'], reverse=True)

        # 페이지네이션
        total = len(sorted_products)
        total_pages = (total + per_page - 1) // per_page
        start = (page - 1) * per_page
        end = start + per_page
        paginated = sorted_products[start:end]

        # 순위 추가
        result = []
        for i, item in enumerate(paginated):
            item['rank'] = start + i + 1
            item['revenue'] = round(item['revenue'], 0)
            result.append(item)

        return jsonify({
            'success': True,
            'data': result,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': total_pages
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/analytics/regions', methods=['GET'])
@admin_required
def get_analytics_regions():
    """지역별 현황 (순위, 지역, 판매량, 매출)"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400

    try:
        response = supabase.table('sales_data').select('배송지주소, 주문수량, 판매가, 배송비금액').execute()
        data = response.data or []

        region_stats = {}
        for d in data:
            address = d.get('배송지주소') or ''
            parts = address.split()
            if len(parts) >= 2:
                region = f"{parts[0]} {parts[1]}"
            elif len(parts) == 1:
                region = parts[0]
            else:
                region = '기타'

            qty = int(d.get('주문수량', 1) or 1)
            # 매출: 판매가 + 배송비
            price = float(d.get('판매가', 0) or 0)
            shipping = float(d.get('배송비금액', 0) or 0)
            revenue = price + shipping

            if region not in region_stats:
                region_stats[region] = {'quantity': 0, 'revenue': 0}
            region_stats[region]['quantity'] += qty
            region_stats[region]['revenue'] += revenue

        sorted_regions = sorted(region_stats.items(), key=lambda x: x[1]['quantity'], reverse=True)[:10]
        result = [{'rank': i+1, 'region': k, 'quantity': v['quantity'], 'revenue': round(v['revenue'], 0)} for i, (k, v) in enumerate(sorted_regions)]

        return jsonify({'success': True, 'data': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/analytics/hourly', methods=['GET'])
@admin_required
def get_analytics_hourly():
    """시간대별 현황 (순위, 시간대, 판매량, 매출)"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400

    try:
        response = supabase.table('sales_data').select('주문일, 주문수량, 판매가, 배송비금액').execute()
        data = response.data or []

        hourly_stats = {}
        for d in data:
            order_date = d.get('주문일')
            if order_date:
                try:
                    dt = datetime.fromisoformat(order_date.replace('Z', '+00:00'))
                    hour = dt.hour
                    hour_key = f"{hour:02d}:00~{hour:02d}:59"

                    qty = int(d.get('주문수량', 1) or 1)
                    # 매출: 판매가 + 배송비
                    price = float(d.get('판매가', 0) or 0)
                    shipping = float(d.get('배송비금액', 0) or 0)
                    revenue = price + shipping

                    if hour_key not in hourly_stats:
                        hourly_stats[hour_key] = {'hour': hour, 'quantity': 0, 'revenue': 0}
                    hourly_stats[hour_key]['quantity'] += qty
                    hourly_stats[hour_key]['revenue'] += revenue
                except:
                    pass

        sorted_hourly = sorted(hourly_stats.items(), key=lambda x: x[1]['quantity'], reverse=True)[:10]
        result = [{'rank': i+1, 'hour': k, 'quantity': v['quantity'], 'revenue': round(v['revenue'], 0)} for i, (k, v) in enumerate(sorted_hourly)]

        return jsonify({'success': True, 'data': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/analytics/customers', methods=['GET'])
@admin_required
def get_analytics_customers():
    """고객 목록 조회 (검색, 정렬, 페이지네이션)"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400

    search = request.args.get('search', '').strip()
    sort_by = request.args.get('sort_by', '총주문횟수')
    sort_order = request.args.get('sort_order', 'desc')
    page = int(request.args.get('page', 1))
    per_page = int(request.args.get('per_page', 50))

    try:
        # 기본 쿼리
        query = supabase.table('customers').select('*')
        
        # 검색 (휴대폰번호, 구매자명, 주요배송지)
        if search:
            # Supabase에서 or 필터링 (주소 검색 추가)
            query = query.or_(f"휴대폰번호.ilike.%{search}%,구매자명.ilike.%{search}%,주요배송지.ilike.%{search}%")
        
        # 정렬
        is_desc = sort_order == 'desc'
        query = query.order(sort_by, desc=is_desc)
        
        response = query.execute()
        all_data = response.data or []
        
        # 페이지네이션
        total = len(all_data)
        total_pages = (total + per_page - 1) // per_page
        start = (page - 1) * per_page
        end = start + per_page
        paginated = all_data[start:end]
        
        return jsonify({
            'success': True,
            'data': paginated,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total': total,
                'total_pages': total_pages
            }
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

# ==================== 데이터 관리 (초기화/롤백) API [신규 추가] ====================

@app.route('/api/analytics/batches', methods=['GET'])
@admin_required
def get_analytics_batches():
    """업로드된 데이터 배치 목록 조회 (최근 5000건 데이터 기준 집계)"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400

    try:
        # Supabase에서 최근 데이터의 배치 ID만 가져와서 파이썬에서 그룹화 (GROUP BY 제약 회피)
        response = supabase.table('sales_data').select('upload_batch_id, created_at').order('created_at', desc=True).limit(5000).execute()
        data = response.data or []

        batch_map = {}
        for row in data:
            batch_id = row.get('upload_batch_id')
            if not batch_id: continue
            
            if batch_id not in batch_map:
                batch_map[batch_id] = {
                    'batch_id': batch_id,
                    'created_at': row.get('created_at'),
                    'count': 0
                }
            batch_map[batch_id]['count'] += 1

        # 리스트로 변환 및 정렬 (최신순)
        result = list(batch_map.values())
        result.sort(key=lambda x: x['batch_id'], reverse=True)

        return jsonify({'success': True, 'data': result})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/analytics/batches/<batch_id>', methods=['DELETE'])
@admin_required
def delete_analytics_batch(batch_id):
    """특정 업로드 배치 데이터 삭제"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400

    try:
        # 1. 판매 데이터 삭제
        supabase.table('sales_data').delete().eq('upload_batch_id', batch_id).execute()

        # 2. 남은 판매 데이터 확인
        remaining = supabase.table('sales_data').select('id').limit(1).execute()

        # 3. 판매 데이터가 모두 삭제되었으면 고객 데이터도 초기화
        if not remaining.data:
            supabase.table('customers').delete().neq('id', 0).execute()
        else:
            # 4. 판매 데이터가 남아있으면 고객 통계 재계산
            recalculate_customer_stats()

        return jsonify({'success': True, 'message': '선택한 업로드 데이터가 삭제되었습니다.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def recalculate_customer_stats():
    """남은 sales_data 기반으로 고객 통계 재계산"""
    if not DB_CONNECTED or not supabase:
        return

    try:
        # 1. 모든 판매 데이터 조회
        sales_response = supabase.table('sales_data').select('*').execute()
        sales_data = sales_response.data or []

        if not sales_data:
            return

        # 2. 고객별 통계 집계 (주문번호 기준 중복 제거)
        customer_stats = {}
        for sale in sales_data:
            phone = sale.get('구매자휴대폰번호')
            if not phone:
                continue

            order_number = sale.get('주문번호')

            if phone not in customer_stats:
                customer_stats[phone] = {
                    '구매자명': sale.get('구매자명'),
                    '구매자ID': sale.get('구매자ID'),
                    '총주문횟수': 0,
                    '총구매금액': 0,
                    '선물발송횟수': 0,
                    '최근구매일': None,
                    '주요배송지': sale.get('배송지주소'),
                    '첫구매일': sale.get('주문일'),
                    '처리된_주문번호': set()
                }

            # 주문번호 기준 중복 제거
            if order_number:
                if order_number not in customer_stats[phone]['처리된_주문번호']:
                    customer_stats[phone]['총주문횟수'] += 1
                    customer_stats[phone]['처리된_주문번호'].add(order_number)
            else:
                customer_stats[phone]['총주문횟수'] += 1

            # 금액 합산 (판매가 + 배송비)
            price = float(sale.get('판매가') or 0)
            shipping = float(sale.get('배송비금액') or 0)
            customer_stats[phone]['총구매금액'] += price + shipping

            # 선물 횟수
            if sale.get('is_gift'):
                customer_stats[phone]['선물발송횟수'] += 1

            # 최근/첫 구매일 업데이트
            order_date = sale.get('주문일')
            if order_date:
                if not customer_stats[phone]['최근구매일'] or order_date > customer_stats[phone]['최근구매일']:
                    customer_stats[phone]['최근구매일'] = order_date
                    customer_stats[phone]['주요배송지'] = sale.get('배송지주소')
                if not customer_stats[phone]['첫구매일'] or order_date < customer_stats[phone]['첫구매일']:
                    customer_stats[phone]['첫구매일'] = order_date

        # 3. 기존 고객 중 sales_data에 없는 고객 삭제
        existing_response = supabase.table('customers').select('휴대폰번호').execute()
        existing_phones = {c['휴대폰번호'] for c in (existing_response.data or [])}
        phones_to_delete = existing_phones - set(customer_stats.keys())

        for phone in phones_to_delete:
            supabase.table('customers').delete().eq('휴대폰번호', phone).execute()

        # 4. 고객 통계 업데이트
        for phone, stats in customer_stats.items():
            update_data = {
                '휴대폰번호': phone,
                '구매자명': stats['구매자명'],
                '구매자ID': stats['구매자ID'],
                '총주문횟수': stats['총주문횟수'],
                '총구매금액': stats['총구매금액'],
                '선물발송횟수': stats['선물발송횟수'],
                '최근구매일': stats['최근구매일'],
                '첫구매일': stats['첫구매일'],
                '주요배송지': stats['주요배송지']
            }
            supabase.table('customers').upsert(update_data, on_conflict='휴대폰번호').execute()

        print(f"✅ 고객 통계 재계산 완료: {len(customer_stats)}명")

    except Exception as e:
        print(f"❌ 고객 통계 재계산 오류: {e}")
    
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)