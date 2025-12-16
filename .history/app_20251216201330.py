"""
Excel 판매자 스타배송 필터 & 송장 분류 - 웹앱
"""

from flask import Flask, render_template, request, send_file, jsonify, session
from werkzeug.utils import secure_filename
import pandas as pd
from io import BytesIO
from datetime import datetime
import os
import json
from collections import defaultdict
import numpy as np

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
app.secret_key = os.environ.get('SECRET_KEY', 'playauto-secret-key-2024')

ALLOWED_EXTENSIONS = {'xls', 'xlsx'}
SETTINGS_FILE = 'playauto_settings_v4.json'

# 기본 설정 로드
def load_settings():
    """설정 파일 로드"""
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return None

def save_settings(settings):
    """설정 파일 저장"""
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

# 초기 설정 로드
CURRENT_SETTINGS = load_settings()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health():
    """UptimeRobot 헬스체크용"""
    return 'OK', 200

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': '파일이 없습니다'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '파일을 선택해주세요'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': '.xls 또는 .xlsx 파일만 가능합니다'}), 400
    
    try:
        # 파일 읽기
        ext = file.filename.rsplit('.', 1)[1].lower()
        if ext == 'xls':
            df = pd.read_excel(file, engine='xlrd')
        else:
            df = pd.read_excel(file, engine='openpyxl')
        
        original_count = len(df)
        
        # 주의메세지 컬럼 찾기
        target_col = None
        for col in df.columns:
            if '주의' in str(col) and '메' in str(col):
                target_col = col
                break
        
        if target_col is None:
            return jsonify({'error': "'주의메세지' 컬럼을 찾을 수 없습니다"}), 400
        
        # 필터링
        mask = df[target_col].astype(str).str.startswith('판매자 스타배송', na=False)
        df_filtered = df[~mask]
        deleted_count = original_count - len(df_filtered)
        
        # 메모리에 저장
        output = BytesIO()
        df_filtered.to_excel(output, index=False, engine='openpyxl')
        output.seek(0)
        
        # 파일명 생성
        original_name = secure_filename(file.filename).rsplit('.', 1)[0]
        timestamp = datetime.now().strftime("%H%M%S")
        output_filename = f"{original_name}_filtered_{timestamp}.xlsx"
        
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


@app.route('/classify', methods=['POST'])
def classify_orders():
    """송장 분류 엔드포인트"""
    if 'file' not in request.files:
        return jsonify({'error': '파일이 없습니다'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '파일을 선택해주세요'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': '.xls 또는 .xlsx 파일만 가능합니다'}), 400
    
    # 설정 파일 확인
    if not CURRENT_SETTINGS:
        return jsonify({'error': '설정 파일을 먼저 업로드해주세요'}), 400
    
    try:
        # 파일 읽기
        ext = file.filename.rsplit('.', 1)[1].lower()
        if ext == 'xls':
            df = pd.read_excel(file, engine='xlrd')
        else:
            df = pd.read_excel(file, engine='openpyxl')
        
        # 분류 실행
        classifier = OrderClassifier(CURRENT_SETTINGS)
        classified_data = classifier.classify_orders(df)
        
        # 통계 계산
        stats = {}
        for work_name, orders in classified_data.items():
            stats[work_name] = len(orders)
        
        # 엑셀 파일 생성
        output = classifier.export_to_excel(classified_data)
        
        # 파일명 생성
        original_name = secure_filename(file.filename).rsplit('.', 1)[0]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_filename = f"{original_name}_classified_{timestamp}.xlsx"
        
        return send_file(
            output,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=output_filename
        ), 200, {
            'X-Stats': json.dumps(stats, ensure_ascii=False)
        }
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/settings', methods=['GET'])
def get_settings():
    """현재 설정 조회"""
    if CURRENT_SETTINGS:
        return jsonify({
            'status': 'loaded',
            'workers': list(CURRENT_SETTINGS.get('work_order', [])),
            'total_products': sum(
                len(cfg.get('products', [])) 
                for cfg in CURRENT_SETTINGS.get('work_config', {}).values()
            )
        })
    return jsonify({'status': 'not_loaded'})


@app.route('/settings/upload', methods=['POST'])
def upload_settings():
    """설정 파일 업로드"""
    if 'file' not in request.files:
        return jsonify({'error': '파일이 없습니다'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '파일을 선택해주세요'}), 400
    
    if not file.filename.endswith('.json'):
        return jsonify({'error': 'JSON 파일만 가능합니다'}), 400
    
    try:
        # JSON 파일 파싱
        settings_data = json.load(file)
        
        # 필수 키 확인
        required_keys = ['work_order', 'work_config']
        for key in required_keys:
            if key not in settings_data:
                return jsonify({'error': f"'{key}' 키가 없습니다"}), 400
        
        # 전역 설정 업데이트
        global CURRENT_SETTINGS
        CURRENT_SETTINGS = settings_data
        
        # 파일로 저장
        save_settings(settings_data)
        
        return jsonify({
            'success': True,
            'message': '설정 파일이 업로드되었습니다',
            'workers': len(settings_data['work_order'])
        })
        
    except json.JSONDecodeError:
        return jsonify({'error': 'JSON 형식이 올바르지 않습니다'}), 400
    except Exception as e:
        return jsonify({'error': str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)


# ==================== 송장 분류 시스템 ====================

class OrderClassifier:
    """주문 분류 엔진"""
    
    def __init__(self, settings):
        self.settings = settings
        self.work_order = settings.get('work_order', [])
        self.work_config = settings.get('work_config', {})
        
    def classify_orders(self, df, progress_callback=None):
        """주문 분류 실행"""
        try:
            # 필수 컬럼 확인
            required_cols = ['주문번호', '상품명', '수량']
            for col in required_cols:
                if col not in df.columns:
                    raise ValueError(f"필수 컬럼 '{col}' 없음")
            
            # 브랜드명 컬럼 찾기 (옵션)
            brand_col = None
            for col in df.columns:
                if '브랜드' in col or 'brand' in col.lower():
                    brand_col = col
                    break
            
            # 주문옵션 컬럼 찾기 (옵션)
            option_col = None
            for col in df.columns:
                if '옵션' in col or 'option' in col.lower():
                    option_col = col
                    break
            
            # 분류 결과 저장
            results = defaultdict(list)
            total = len(df)
            
            # 주문번호별 그룹화
            grouped = df.groupby('주문번호')
            
            for idx, (order_num, group) in enumerate(grouped):
                if progress_callback:
                    progress_callback(int((idx + 1) / len(grouped) * 100))
                
                # 단일 상품 vs 합배송 판단
                if len(group) > 1:
                    # 합배송
                    results['합배송'].extend(group.to_dict('records'))
                    continue
                
                row = group.iloc[0]
                product_name = str(row['상품명']).strip()
                brand = str(row[brand_col]).strip() if brand_col and brand_col in row.index else ''
                option = str(row[option_col]).strip() if option_col and option_col in row.index else 'All'
                quantity = int(row['수량']) if pd.notna(row['수량']) else 1
                
                # 복수주문 체크
                if quantity >= self.settings.get('quantity_threshold', 2):
                    results['복수주문'].append(row.to_dict())
                    continue
                
                # 상품 매칭
                matched = False
                for work_name in self.work_order:
                    if work_name in ['합배송', '복수주문', '분류실패']:
                        continue
                    
                    work_cfg = self.work_config.get(work_name, {})
                    if not work_cfg.get('enabled', True):
                        continue
                    
                    products = work_cfg.get('products', [])
                    
                    for prod in products:
                        if self._match_product(brand, product_name, option, prod):
                            results[work_name].append(row.to_dict())
                            matched = True
                            break
                    
                    if matched:
                        break
                
                # 미매칭
                if not matched:
                    results['분류실패'].append(row.to_dict())
            
            return dict(results)
            
        except Exception as e:
            raise Exception(f"분류 오류: {str(e)}")
    
    def _match_product(self, brand, product_name, option, rule):
        """상품 매칭 로직"""
        rule_brand = rule.get('brand', '').strip()
        rule_product = rule.get('product_name', '').strip()
        rule_option = rule.get('order_option', 'All').strip()
        
        # 브랜드 매칭
        if rule_brand and rule_brand != 'All':
            if rule_brand not in brand:
                return False
        
        # 상품명 매칭
        if rule_product == 'All':
            brand_match = rule_brand and rule_brand in brand
            return brand_match
        
        if rule_product not in product_name:
            return False
        
        # 옵션 매칭
        if rule_option != 'All' and option != 'All':
            if rule_option not in option:
                return False
        
        return True
    
    def export_to_excel(self, classified_data):
        """분류 결과를 엑셀로 내보내기"""
        output = BytesIO()
        
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            for work_name in self.work_order:
                if work_name in classified_data and len(classified_data[work_name]) > 0:
                    df_work = pd.DataFrame(classified_data[work_name])
                    # 시트 이름 길이 제한 (Excel: 31자)
                    sheet_name = work_name[:31]
                    df_work.to_excel(writer, sheet_name=sheet_name, index=False)
        
        output.seek(0)
        return output