from flask import Flask, render_template, request, send_file, jsonify, session, redirect, url_for
from werkzeug.utils import secure_filename
import pandas as pd
from io import BytesIO
from datetime import datetime, date, time, timedelta
import os
import json
from collections import defaultdict, OrderedDict
import numpy as np
import calendar
from functools import wraps
from decimal import Decimal, ROUND_HALF_UP

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
app.secret_key = os.environ.get('SECRET_KEY', 'playauto-secret-key-2024')

# ==================== Supabase 설정 ====================
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')

supabase = None
DB_CONNECTED = False

if SUPABASE_URL and SUPABASE_KEY:
    try:
        from supabase import create_client, Client
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        supabase.table('workers').select('id').limit(1).execute()
        DB_CONNECTED = True
        print("✅ Supabase 연결 성공")
    except Exception as e:
        print(f"⚠️  Supabase 연결 실패 ({e})")
        supabase = None
        DB_CONNECTED = False
else:
    print("ℹ️  Supabase 환경변수 없음")

# ==================== 폴백용 환경변수 (DB 없을 때) ====================
ADMIN_ID = os.environ.get('ADMIN_ID', os.environ.get('LOGIN_ID', 'admin'))
ADMIN_PW = os.environ.get('ADMIN_PW', os.environ.get('LOGIN_PW', 'admin123'))

# ==================== 인증 데코레이터 ====================

def login_required(f):
    """로그인 필수"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """관리자 전용"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        if session.get('user_role') != 'admin':
            return jsonify({'error': '관리자 권한이 필요합니다'}), 403
        return f(*args, **kwargs)
    return decorated_function

# ==================== 설정 파일 ====================
ALLOWED_EXTENSIONS = {'xls', 'xlsx'}
SETTINGS_FILE = 'playauto_settings_v4.json'
MARGIN_DATA_FILE = 'margin_data.json'
TEMP_RESULTS = {}

def load_settings_from_file():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def save_settings_to_file(settings):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

def load_settings():
    return load_settings_from_file()

def save_settings(settings):
    save_settings_to_file(settings)

try:
    CURRENT_SETTINGS = load_settings()
    if not CURRENT_SETTINGS:
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
except Exception as e:
    print(f"❌ 설정 로드 오류: {e}")
    CURRENT_SETTINGS = None

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ==================== 원가 마진표 ====================
MARGIN_DATA = []

def load_margin_data():
    global MARGIN_DATA
    if os.path.exists(MARGIN_DATA_FILE):
        with open(MARGIN_DATA_FILE, 'r', encoding='utf-8') as f:
            MARGIN_DATA = json.load(f)
        print(f"✅ 원가 마진표 로드: {len(MARGIN_DATA)}개")

load_margin_data()

# ==================== 스타배송 필터 ====================

def check_star_delivery(df):
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
    result = check_star_delivery(df)
    if not result['has_column']:
        return df, 0
    filtered_df = df[~result['mask']]
    return filtered_df, int(result['star_count'])

# ==================== 로그인/로그아웃 ====================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        data = request.get_json()
        user_id = data.get('id', '')
        user_pw = data.get('pw', '')
        
        # DB에서 사용자 확인
        if DB_CONNECTED and supabase:
            try:
                response = supabase.table('users').select('*').eq('username', user_id).eq('password', user_pw).eq('enabled', True).execute()
                if response.data:
                    user = response.data[0]
                    session['logged_in'] = True
                    session['user_id'] = user['id']
                    session['user_role'] = user['role']
                    session['user_name'] = user['name']
                    session['username'] = user['username']
                    return jsonify({'success': True, 'role': user['role']})
            except Exception as e:
                print(f"DB 로그인 오류: {e}")
        
        # 폴백: 환경변수 관리자 계정
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
    session.clear()
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    if session.get('user_role') == 'parttime':
        return render_template('parttime.html')
    return render_template('index.html')

@app.route('/health')
def health():
    return 'OK', 200

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

# ==================== 기존 /settings (유지) ====================

@app.route('/settings', methods=['GET'])
def get_settings_legacy():
    if CURRENT_SETTINGS:
        total_products = sum(
            len(cfg.get('products', [])) 
            for cfg in CURRENT_SETTINGS.get('work_config', {}).values()
        )
        return jsonify({
            'status': 'loaded',
            'workers': list(CURRENT_SETTINGS.get('work_order', [])),
            'total_products': total_products,
            'source': 'file',
            'db_connected': DB_CONNECTED
        })
    return jsonify({'status': 'not_loaded', 'error': '설정 불러오기 실패'})

# ==================== 원가 마진표 API (기존 유지) ====================

@app.route('/api/margin', methods=['GET'])
@login_required
def get_margin_data():
    search = request.args.get('search', '').strip()
    
    if DB_CONNECTED and supabase:
        try:
            query = supabase.table('margin_products').select('*')
            if search:
                query = query.ilike('상품명', f'%{search}%')
            response = query.order('상품명').execute()
            
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
            print(f"DB 조회 실패: {e}")
    
    if search:
        filtered = [item for item in MARGIN_DATA if search.lower() in item['상품명'].lower()]
        return jsonify({'data': filtered, 'total': len(filtered), 'source': 'file'})
    return jsonify({'data': MARGIN_DATA, 'total': len(MARGIN_DATA), 'source': 'file'})

@app.route('/api/margin', methods=['POST'])
@admin_required
def create_margin_product():
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
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
@admin_required
def update_margin_product(product_id):
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
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
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/margin/<int:product_id>', methods=['DELETE'])
@admin_required
def delete_margin_product(product_id):
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    try:
        supabase.table('margin_products').delete().eq('id', product_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== 담당자 API (기존 유지) ====================

@app.route('/api/workers', methods=['GET'])
@login_required
def get_workers():
    if DB_CONNECTED and supabase:
        try:
            response = supabase.table('workers').select('*').order('sort_order').execute()
            workers = response.data
            for worker in workers:
                products_resp = supabase.table('worker_products').select('id').eq('worker_id', worker['id']).execute()
                worker['product_count'] = len(products_resp.data)
            return jsonify({'data': workers, 'source': 'db', 'db_connected': True})
        except Exception as e:
            print(f"담당자 조회 실패: {e}")
    
    if CURRENT_SETTINGS:
        workers = []
        icons = {'송과장님': '🍧', '영재씨': '🍯', '효상': '🍜', '강민씨': '🍜', '부모님': '☕', '합배송': '📦', '복수주문': '📋', '분류실패': '❓'}
        descriptions = {'송과장님': '팥빙수재료 담당', '영재씨': '미에로화이바 담당', '강민씨': '백제 브랜드 담당', '부모님': '쟈뎅, 카페재료 담당', '합배송': '여러 상품 주문', '복수주문': '2개 이상 주문', '분류실패': '매칭 안됨'}
        for i, name in enumerate(CURRENT_SETTINGS.get('work_order', [])):
            config = CURRENT_SETTINGS.get('work_config', {}).get(name, {})
            workers.append({
                'id': i + 1, 'name': name, 'type': config.get('type', 'product_specific'),
                'description': descriptions.get(name, ''), 'icon': icons.get(name, '📋'),
                'enabled': config.get('enabled', True), 'product_count': len(config.get('products', []))
            })
        return jsonify({'data': workers, 'source': 'file', 'db_connected': False})
    return jsonify({'data': [], 'source': 'none'})

@app.route('/api/workers/<int:worker_id>/products', methods=['GET'])
@login_required
def get_worker_products(worker_id):
    if DB_CONNECTED and supabase:
        try:
            response = supabase.table('worker_products').select('*').eq('worker_id', worker_id).order('product_name').execute()
            return jsonify({'data': response.data, 'source': 'db', 'db_connected': True})
        except Exception as e:
            print(f"상품 규칙 조회 실패: {e}")
    
    if CURRENT_SETTINGS:
        work_order = CURRENT_SETTINGS.get('work_order', [])
        if 0 < worker_id <= len(work_order):
            worker_name = work_order[worker_id - 1]
            config = CURRENT_SETTINGS.get('work_config', {}).get(worker_name, {})
            products = sorted(config.get('products', []), key=lambda x: x.get('product_name', ''))
            result = [{'id': i+1, 'worker_id': worker_id, 'brand': p.get('brand', ''), 'product_name': p.get('product_name', ''), 'order_option': p.get('order_option', 'All')} for i, p in enumerate(products)]
            return jsonify({'data': result, 'source': 'file', 'db_connected': False})
    return jsonify({'data': []})

@app.route('/api/workers/<int:worker_id>/products', methods=['POST'])
@admin_required
def create_worker_product(worker_id):
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    data = request.get_json()
    try:
        new_product = {'worker_id': worker_id, 'brand': data.get('brand', ''), 'product_name': data.get('product_name', ''), 'order_option': data.get('order_option', 'All')}
        response = supabase.table('worker_products').insert(new_product).execute()
        return jsonify({'success': True, 'data': response.data[0]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/workers/<int:worker_id>/products/<int:product_id>', methods=['PUT'])
@admin_required
def update_worker_product(worker_id, product_id):
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    data = request.get_json()
    try:
        update_data = {'brand': data.get('brand', ''), 'product_name': data.get('product_name', ''), 'order_option': data.get('order_option', 'All'), 'updated_at': datetime.utcnow().isoformat()}
        supabase.table('worker_products').update(update_data).eq('id', product_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/workers/<int:worker_id>/products/<int:product_id>', methods=['DELETE'])
@admin_required
def delete_worker_product(worker_id, product_id):
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    try:
        supabase.table('worker_products').delete().eq('id', product_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/db-status')
@login_required
def get_db_status():
    return jsonify({'db_connected': DB_CONNECTED, 'mode': 'db' if DB_CONNECTED else 'file'})

# ==================== 스타배송 필터 / 송장 분류 (기존 유지) ====================

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': '파일 없음'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '파일 선택 필요'}), 400
    if not allowed_file(file.filename):
        return jsonify({'error': '.xls/.xlsx만 가능'}), 400
    
    try:
        ext = file.filename.rsplit('.', 1)[1].lower()
        df = pd.read_excel(file, engine='xlrd' if ext == 'xls' else 'openpyxl')
        original_count = len(df)
        
        target_col = None
        for col in df.columns:
            if '주의' in str(col) and '메' in str(col):
                target_col = col
                break
        if target_col is None:
            return jsonify({'error': "'주의메세지' 컬럼 없음"}), 400
        
        mask = df[target_col].astype(str).str.startswith('판매자 스타배송', na=False)
        df_filtered = df[~mask]
        deleted_count = original_count - len(df_filtered)
        
        output = BytesIO()
        df_filtered.to_excel(output, index=False, engine='openpyxl')
        output.seek(0)
        
        output_filename = f"{secure_filename(file.filename).rsplit('.', 1)[0]}_final.xlsx"
        return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=output_filename), 200, {'X-Deleted-Count': str(deleted_count), 'X-Original-Count': str(original_count)}
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/classify', methods=['POST'])
def classify_orders():
    if 'file' not in request.files:
        return jsonify({'error': '파일 없음'}), 400
    file = request.files['file']
    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({'error': '파일 오류'}), 400
    if not CURRENT_SETTINGS:
        return jsonify({'error': '설정 없음'}), 400
    
    filter_star = request.form.get('filter_star', 'false').lower() == 'true'
    
    try:
        ext = file.filename.rsplit('.', 1)[1].lower()
        df = pd.read_excel(file, engine='xlrd' if ext == 'xls' else 'openpyxl')
        
        star_deleted = 0
        if filter_star:
            df, star_deleted = filter_star_delivery(df)
        
        classifier = OrderClassifierV41(CURRENT_SETTINGS)
        result_df = classifier.classify_orders_optimized(df)
        stats = classifier.get_classification_stats(result_df)
        
        if filter_star:
            stats['summary']['star_filtered'] = True
            stats['summary']['star_deleted'] = star_deleted
        else:
            stats['summary']['star_filtered'] = False
        
        session_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{id(result_df)}"
        TEMP_RESULTS[session_id] = {'df': result_df, 'stats': stats, 'filename': file.filename, 'created_at': datetime.now()}
        
        return jsonify({'success': True, 'session_id': session_id, 'stats': stats})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/download/<session_id>')
def download_result(session_id):
    if session_id not in TEMP_RESULTS:
        return jsonify({'error': '결과 없음'}), 404
    result = TEMP_RESULTS[session_id]
    classifier = OrderClassifierV41(CURRENT_SETTINGS)
    output = classifier.export_single_sheet(result['df'])
    output_filename = f"{result['filename'].rsplit('.', 1)[0]}_분류완료.xlsx"
    return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', as_attachment=True, download_name=output_filename)

# ==================== 직원 관리 API (신규) ====================

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
        # 중복 확인
        existing = supabase.table('users').select('id').eq('username', data.get('username')).execute()
        if existing.data:
            return jsonify({'error': '이미 존재하는 아이디입니다'}), 400
        
        new_emp = {
            'username': data.get('username'),
            'password': data.get('password'),
            'name': data.get('name'),
            'role': 'parttime',
            'hourly_wage': int(data.get('hourly_wage', 10700)),
            'full_attendance_bonus': int(data.get('full_attendance_bonus', 100000)),
            'enabled': True
        }
        response = supabase.table('users').insert(new_emp).execute()
        
        # 시급 이력 기록
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
        # 기존 시급 조회
        old_emp = supabase.table('users').select('hourly_wage').eq('id', emp_id).execute()
        old_wage = old_emp.data[0]['hourly_wage'] if old_emp.data else 0
        new_wage = int(data.get('hourly_wage', old_wage))
        
        update_data = {
            'name': data.get('name'),
            'hourly_wage': new_wage,
            'full_attendance_bonus': int(data.get('full_attendance_bonus', 100000)),
            'enabled': data.get('enabled', True),
            'updated_at': datetime.utcnow().isoformat()
        }
        
        # 비밀번호 변경 시에만
        if data.get('password'):
            update_data['password'] = data.get('password')
        
        supabase.table('users').update(update_data).eq('id', emp_id).execute()
        
        # 시급 변경 시 이력 기록
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
    """직원 삭제 (비활성화)"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    try:
        supabase.table('users').update({'enabled': False, 'updated_at': datetime.utcnow().isoformat()}).eq('id', emp_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== 공휴일 관리 API ====================

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

# ==================== 출퇴근 기록 API ====================

@app.route('/api/attendance', methods=['GET'])
@login_required
def get_attendance():
    """출퇴근 기록 조회"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    year = int(request.args.get('year', date.today().year))
    month = int(request.args.get('month', date.today().month))
    emp_id = request.args.get('employee_id')
    
    # 알바생은 본인만 조회
    if session.get('user_role') == 'parttime':
        emp_id = session.get('user_id')
    elif not emp_id:
        return jsonify({'error': '직원 ID 필요'}), 400
    
    try:
        start_date = f"{year}-{month:02d}-01"
        _, last_day = calendar.monthrange(year, month)
        end_date = f"{year}-{month:02d}-{last_day}"
        
        # 출퇴근 기록
        response = supabase.table('attendance_logs').select('*').eq('employee_id', emp_id).gte('work_date', start_date).lte('work_date', end_date).order('work_date').execute()
        
        # 공휴일 목록
        holidays_resp = supabase.table('holidays').select('holiday_date').gte('holiday_date', start_date).lte('holiday_date', end_date).execute()
        holidays = [h['holiday_date'] for h in holidays_resp.data]
        
        # 직원 정보
        emp_resp = supabase.table('users').select('name, hourly_wage, full_attendance_bonus').eq('id', emp_id).execute()
        emp_info = emp_resp.data[0] if emp_resp.data else {}
        
        # 수정 승인 목록
        approvals_resp = supabase.table('edit_approvals').select('approved_date, used').eq('employee_id', emp_id).execute()
        approvals = {a['approved_date']: not a['used'] for a in approvals_resp.data}
        
        # 월급 확정 여부
        confirm_resp = supabase.table('salary_confirmations').select('*').eq('employee_id', emp_id).eq('year_month', f"{year}-{month:02d}").execute()
        is_confirmed = len(confirm_resp.data) > 0
        confirmation_data = confirm_resp.data[0] if is_confirmed else None
        
        # 데이터 가공
        records = []
        for log in response.data:
            work_date = log['work_date']
            is_editable = work_date == date.today().isoformat() or approvals.get(work_date, False)
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
    
    # 알바생은 본인만
    if session.get('user_role') == 'parttime':
        emp_id = session.get('user_id')
    else:
        emp_id = data.get('employee_id')
    
    if not emp_id or not work_date:
        return jsonify({'error': '필수 정보 누락'}), 400
    
    # 수정 가능 여부 확인 (오늘 또는 승인된 날짜)
    today = date.today().isoformat()
    if work_date != today and session.get('user_role') == 'parttime':
        # 승인 확인
        approval = supabase.table('edit_approvals').select('id, used').eq('employee_id', emp_id).eq('approved_date', work_date).execute()
        if not approval.data or approval.data[0]['used']:
            return jsonify({'error': '수정 권한이 없습니다. 관리자 승인이 필요합니다.'}), 403
        # 승인 사용 처리
        supabase.table('edit_approvals').update({'used': True}).eq('id', approval.data[0]['id']).execute()
    
    try:
        # 기존 기록 확인
        existing = supabase.table('attendance_logs').select('id').eq('employee_id', emp_id).eq('work_date', work_date).execute()
        
        # 공휴일/주말 여부 확인
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

# ==================== 수정 승인 API (관리자용) ====================

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
        # 기존 승인 확인 및 재활성화
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

# ==================== 급여 계산 API ====================

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
    
    # 직원 정보
    emp_resp = supabase.table('users').select('*').eq('id', emp_id).execute()
    if not emp_resp.data:
        return {'error': '직원 정보 없음'}
    emp = emp_resp.data[0]
    hourly_wage = emp['hourly_wage']
    full_bonus = emp.get('full_attendance_bonus', 100000)
    
    # 시급 변경 이력 조회
    wage_history = supabase.table('wage_history').select('*').eq('employee_id', emp_id).lte('effective_date', end_date).order('effective_date', desc=True).execute()
    
    # 출퇴근 기록
    attendance_resp = supabase.table('attendance_logs').select('*').eq('employee_id', emp_id).gte('work_date', start_date).lte('work_date', end_date).order('work_date').execute()
    records = attendance_resp.data
    
    # 공휴일
    holidays_resp = supabase.table('holidays').select('holiday_date').gte('holiday_date', start_date).lte('holiday_date', end_date).execute()
    holidays = set(h['holiday_date'] for h in holidays_resp.data)
    
    # 불완전 기록 체크
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
    
    # 급여 계산
    base_pay = 0
    overtime_pay = 0
    weekly_hours = defaultdict(float)
    total_hours = 0
    work_days = len(records)
    details = []
    
    for r in records:
        work_date = r['work_date']
        clock_in = r['clock_in']
        clock_out = r['clock_out']
        
        # 해당 날짜의 시급 찾기
        applicable_wage = hourly_wage
        for wh in wage_history.data:
            if wh['effective_date'] <= work_date:
                applicable_wage = wh['hourly_wage']
                break
        
        # 시간 계산
        regular_hrs, overtime_hrs = _calculate_daily_hours(clock_in, clock_out)
        total_daily = regular_hrs + overtime_hrs
        total_hours += total_daily
        
        # 주차별 시간 집계
        work_date_obj = date.fromisoformat(work_date)
        week_num = work_date_obj.isocalendar()[1]
        weekly_hours[week_num] += total_daily
        
        # 공휴일/주말 근무 시 1.5배
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
            'wage': applicable_wage,
            'is_special': is_special,
            'base': day_base,
            'overtime': day_overtime
        })
    
    # 주휴수당 계산 (주 15시간 이상)
    weekly_holiday_pay = 0
    for week, hours in weekly_hours.items():
        if hours >= 15:
            pay = int((hours / 5) * hourly_wage)
            weekly_holiday_pay += pay
    
    # 만근수당 체크
    required_days = []
    for day in range(1, last_day + 1):
        d = date(year, month, day)
        if d.weekday() < 5 and d.isoformat() not in holidays:
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
            'work_days': work_days,
            'is_full_attendance': is_full_attendance
        },
        'details': details,
        'required_days': len(required_days),
        'worked_days': len(worked_days)
    }

def _calculate_daily_hours(clock_in_str, clock_out_str):
    """일일 근무시간 계산 (정규/초과 분리)"""
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
    
    # 점심시간 공제 (12:00~13:00)
    lunch_start = 12 * 60
    lunch_end = 13 * 60
    if start_min < lunch_end and end_min > lunch_start:
        overlap_start = max(start_min, lunch_start)
        overlap_end = min(end_min, lunch_end)
        total_min -= max(0, overlap_end - overlap_start)
    
    # 정규시간 (09:00~18:00)
    work_start = 9 * 60
    work_end = 18 * 60
    
    regular_start = max(start_min, work_start)
    regular_end = min(end_min, work_end)
    regular_min = max(0, regular_end - regular_start)
    
    # 점심시간 공제 (정규시간 내)
    if regular_start < lunch_end and regular_end > lunch_start:
        overlap_start = max(regular_start, lunch_start)
        overlap_end = min(regular_end, lunch_end)
        regular_min -= max(0, overlap_end - overlap_start)
    
    overtime_min = total_min - regular_min
    
    return regular_min / 60, max(0, overtime_min) / 60

# ==================== 월급 확정 API ====================

@app.route('/api/salary/confirm', methods=['POST'])
@login_required
def confirm_salary():
    """월급 확정 (알바생 동의)"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    data = request.get_json()
    year = int(data.get('year', date.today().year))
    month = int(data.get('month', date.today().month))
    
    emp_id = session.get('user_id') if session.get('user_role') == 'parttime' else data.get('employee_id')
    
    try:
        # 급여 계산
        result = _calculate_monthly_salary(emp_id, year, month)
        if not result.get('success'):
            return jsonify(result), 400
        
        # 확정 저장
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
    """월급 확정 목록 조회 (관리자용)"""
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

# ==================== 관리자용 출퇴근 조회 ====================

@app.route('/api/admin/attendance', methods=['GET'])
@admin_required
def admin_get_attendance():
    """모든 직원 출퇴근 조회 (관리자용)"""
    if not DB_CONNECTED:
        return jsonify({'error': 'DB 연결 필요'}), 400
    
    year = int(request.args.get('year', date.today().year))
    month = int(request.args.get('month', date.today().month))
    
    try:
        start_date = f"{year}-{month:02d}-01"
        _, last_day = calendar.monthrange(year, month)
        end_date = f"{year}-{month:02d}-{last_day}"
        
        # 모든 활성 직원
        employees = supabase.table('users').select('*').eq('role', 'parttime').eq('enabled', True).execute()
        
        result = []
        for emp in employees.data:
            # 출퇴근 기록
            attendance = supabase.table('attendance_logs').select('*').eq('employee_id', emp['id']).gte('work_date', start_date).lte('work_date', end_date).order('work_date').execute()
            
            # 월급 확정 여부
            confirmation = supabase.table('salary_confirmations').select('*').eq('employee_id', emp['id']).eq('year_month', f"{year}-{month:02d}").execute()
            
            result.append({
                'employee': {
                    'id': emp['id'],
                    'name': emp['name'],
                    'hourly_wage': emp['hourly_wage']
                },
                'records': attendance.data,
                'is_confirmed': len(confirmation.data) > 0,
                'confirmation': confirmation.data[0] if confirmation.data else None
            })
        
        return jsonify({'success': True, 'data': result, 'year_month': f"{year}-{month:02d}"})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ==================== 분류 엔진 (기존 100% 유지) ====================

class OrderClassifierV41:
    def __init__(self, settings):
        self.settings = settings
        self.work_order = settings.get('work_order', [])
        self.work_config = settings.get('work_config', {})
        self.quantity_threshold = settings.get('quantity_threshold', 2)
    
    def classify_orders_optimized(self, df):
        df = df.copy()
        df = self._preprocess_data_optimized(df)
        failed_work = self._get_failed_work_name()
        df['담당자'] = failed_work
        df['분류근거'] = '매칭 없음'
        df['신뢰도'] = 0.0
        
        if '주문고유번호' in df.columns:
            order_counts = df['주문고유번호'].value_counts()
            multi_orders = order_counts[order_counts >= 2].index
            is_multi_order = df['주문고유번호'].isin(multi_orders)
            combined_work = self._get_combined_work_name()
            if combined_work:
                df.loc[is_multi_order, '담당자'] = combined_work
                df.loc[is_multi_order, '분류근거'] = '합배송'
                df.loc[is_multi_order, '신뢰도'] = 1.0
        
        multiple_work = self._get_multiple_work_name()
        if multiple_work:
            is_multiple = (df['주문수량'] >= self.quantity_threshold) & (df['담당자'] == failed_work)
            df.loc[is_multiple, '담당자'] = multiple_work
            df.loc[is_multiple, '분류근거'] = '복수주문'
            df.loc[is_multiple, '신뢰도'] = 1.0
        
        unmatched_mask = df['담당자'] == failed_work
        unmatched_indices = df[unmatched_mask].index
        if len(unmatched_indices) > 0:
            compiled_rules = self._compile_matching_rules()
            self._classify_batch(df, unmatched_indices, compiled_rules)
        
        return self._sort_results_optimized(df)
    
    def _preprocess_data_optimized(self, df):
        if '상품명' in df.columns:
            df['상품명'] = df['상품명'].fillna('').astype(str)
        else:
            raise ValueError("'상품명' 컬럼 없음")
        
        df['주문수량'] = pd.to_numeric(df.get('주문수량', 1), errors='coerce').fillna(1).astype(int)
        df['주문선택사항'] = df.get('주문선택사항', '').fillna('').astype(str)
        df['full_product_name'] = df['상품명'] + ' ' + df['주문선택사항']
        df['brand'] = df['상품명'].str.split(n=1, expand=True)[0].fillna('')
        
        if '주문고유번호' in df.columns:
            df['주문고유번호'] = df['주문고유번호'].fillna('').astype(str)
        elif '주문번호' in df.columns:
            df['주문고유번호'] = df['주문번호'].fillna('').astype(str)
        else:
            df['주문고유번호'] = np.arange(len(df)).astype(str)
        return df
    
    def _compile_matching_rules(self):
        rules = []
        for work_name in self.work_order:
            config = self.work_config.get(work_name, {})
            if config.get('type') != 'product_specific':
                continue
            for product in config.get('products', []):
                rules.append({'work_name': work_name, 'brand': product.get('brand', ''), 'product_name': product.get('product_name', ''), 'order_option': product.get('order_option', 'All')})
        return rules
    
    def _classify_batch(self, df, indices, rules):
        for idx in indices:
            row = df.loc[idx]
            for rule in rules:
                if self._match_rule(row, rule):
                    df.at[idx, '담당자'] = rule['work_name']
                    df.at[idx, '분류근거'] = f"매칭: {rule['brand']} {rule['product_name']}"
                    df.at[idx, '신뢰도'] = 1.0
                    break
    
    def _match_rule(self, row, rule):
        if rule['brand'] and rule['brand'] != 'All' and rule['brand'] not in row['brand']:
            return False
        if rule['product_name'] != 'All' and rule['product_name'] not in row['상품명']:
            return False
        if rule['order_option'] != 'All' and rule['order_option'] not in row['주문선택사항']:
            return False
        return True
    
    def _sort_results_optimized(self, df):
        priority_map = {name: i for i, name in enumerate(self.work_order)}
        df['priority'] = df['담당자'].map(priority_map)
        combined_work = self._get_combined_work_name()
        sorted_groups = []
        for work_name in self.work_order:
            work_df = df[df['담당자'] == work_name].copy()
            if len(work_df) == 0:
                continue
            work_df = work_df.sort_values(['주문고유번호'] if work_name == combined_work else ['full_product_name'])
            sorted_groups.append(work_df)
        if sorted_groups:
            return pd.concat(sorted_groups, ignore_index=True).drop(['priority'], axis=1)
        return df
    
    def get_classification_stats(self, df):
        total = len(df)
        stats = {'workers': [], 'summary': {}}
        current_row = 1
        for work_name in self.work_order:
            work_data = df[df['담당자'] == work_name]
            count = len(work_data)
            config = self.work_config.get(work_name, {})
            if count > 0:
                row_range = f"{current_row} ~ {current_row + count - 1}"
                current_row += count
            else:
                row_range = "-"
            stats['workers'].append({'name': work_name, 'count': count, 'percentage': round(count/total*100, 1) if total > 0 else 0, 'icon': config.get('icon', '📋'), 'range': row_range})
        
        failed_work = self._get_failed_work_name()
        unmatched = len(df[df['담당자'] == failed_work])
        success = total - unmatched
        stats['summary'] = {'total_orders': total, 'success_count': success, 'failed_count': unmatched, 'auto_classification_rate': round(success/total*100, 1) if total > 0 else 0}
        return stats
    
    def export_single_sheet(self, df):
        output = BytesIO()
        export_df = df.drop(columns=[c for c in ['full_product_name', 'brand', 'priority', '담당자', '분류근거', '신뢰도'] if c in df.columns], errors='ignore')
        export_df.to_excel(output, sheet_name='분류결과', index=False, engine='openpyxl')
        output.seek(0)
        return output
    
    def _get_failed_work_name(self):
        for name, config in self.work_config.items():
            if config.get('type') == 'failed':
                return name
        return '분류실패'
    
    def _get_combined_work_name(self):
        for name, config in self.work_config.items():
            if config.get('type') == 'mixed_products':
                return name
        return None
    
    def _get_multiple_work_name(self):
        for name, config in self.work_config.items():
            if config.get('type') == 'multiple_quantity':
                return name
        return None


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)