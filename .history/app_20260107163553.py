from flask import Flask, render_template, request, send_file, jsonify, session, redirect, url_for
from werkzeug.utils import secure_filename
import pandas as pd
from io import BytesIO
from datetime import datetime
import os
import json
from collections import defaultdict, OrderedDict
import numpy as np
import time
from functools import wraps

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
app.secret_key = os.environ.get('SECRET_KEY', 'playauto-secret-key-2024')

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

def login_required(f):
    """로그인 필수 데코레이터"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

ALLOWED_EXTENSIONS = {'xls', 'xlsx'}
SETTINGS_FILE = 'playauto_settings_v4.json'
MARGIN_DATA_FILE = 'margin_data.json'

# 임시 저장소 (세션별 분류 결과)
TEMP_RESULTS = {}

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
def login():
    """로그인 페이지"""
    if request.method == 'POST':
        data = request.get_json()
        user_id = data.get('id', '')
        user_pw = data.get('pw', '')
        
        if user_id == LOGIN_ID and user_pw == LOGIN_PW:
            session['logged_in'] = True
            return jsonify({'success': True})
        else:
            return jsonify({'success': False, 'error': '아이디 또는 비밀번호가 틀렸습니다'})
    
    if session.get('logged_in'):
        return redirect(url_for('index'))
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    """로그아웃"""
    session.pop('logged_in', None)
    return redirect(url_for('login'))

@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/health')
def health():
    """UptimeRobot 헬스체크용"""
    return 'OK', 200

# ==================== 기존 /settings 라우트 (유지) ====================

@app.route('/settings', methods=['GET'])
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
def classify_orders():
    """송장 분류 - 통계와 함께 결과 반환"""
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
        
        star_deleted = 0
        if filter_star:
            df, star_deleted = filter_star_delivery(df)
        
        classifier = OrderClassifierV41(CURRENT_SETTINGS)
        result_df = classifier.classify_orders_optimized(df)
        stats = classifier.get_classification_stats(result_df)
        
        if star_deleted > 0:
            stats['summary']['star_deleted'] = star_deleted
        
        session_id = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{id(result_df)}"
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


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)