"""
Excel 판매자 스타배송 필터 & 송장 분류 - 웹앱
원본 데스크톱 앱의 모든 분류 로직 100% 재현
"""

from flask import Flask, render_template, request, send_file, jsonify, session
from werkzeug.utils import secure_filename
import pandas as pd
from io import BytesIO
from datetime import datetime
import os
import json
from collections import defaultdict, OrderedDict
import numpy as np
import time

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB
app.secret_key = os.environ.get('SECRET_KEY', 'playauto-secret-key-2024')

ALLOWED_EXTENSIONS = {'xls', 'xlsx'}
SETTINGS_FILE = 'playauto_settings_v4.json'

# ==================== 설정 관리 ====================

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

# ==================== 라우트 ====================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/health')
def health():
    """UptimeRobot 헬스체크용"""
    return 'OK', 200

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
    """송장 분류 - 원본 로직 100% 재현"""
    if 'file' not in request.files:
        return jsonify({'error': '파일이 없습니다'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': '파일을 선택해주세요'}), 400
    
    if not allowed_file(file.filename):
        return jsonify({'error': '.xls 또는 .xlsx 파일만 가능합니다'}), 400
    
    if not CURRENT_SETTINGS:
        return jsonify({'error': '설정 파일을 먼저 로드해주세요'}), 400
    
    try:
        ext = file.filename.rsplit('.', 1)[1].lower()
        if ext == 'xls':
            df = pd.read_excel(file, engine='xlrd')
        else:
            df = pd.read_excel(file, engine='openpyxl')
        
        # 원본 분류 엔진 사용
        classifier = OrderClassifierV41(CURRENT_SETTINGS)
        classified_df = classifier.classify_orders_optimized(df)
        
        # 통계 계산
        stats = classifier.calculate_statistics(classified_df)
        
        # 엑셀 파일 생성
        output = classifier.export_to_excel(classified_df)
        
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
        total_products = sum(
            len(cfg.get('products', [])) 
            for cfg in CURRENT_SETTINGS.get('work_config', {}).values()
        )
        
        has_file = os.path.exists(SETTINGS_FILE)
        
        return jsonify({
            'status': 'loaded',
            'workers': list(CURRENT_SETTINGS.get('work_order', [])),
            'total_products': total_products,
            'source': 'file' if has_file else 'default'
        })
    return jsonify({
        'status': 'not_loaded', 
        'error': '설정을 불러올 수 없습니다'
    })


# ==================== 분류 엔진 (원본 100% 재현) ====================

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
        
        # 기본값 설정
        failed_work = self._get_failed_work_name()
        df['담당자'] = failed_work
        df['분류근거'] = '매칭 없음'
        df['신뢰도'] = 0.0
        
        # 1. 합배송 판별
        if '주문고유번호' in df.columns:
            order_counts = df['주문고유번호'].value_counts()
            multi_orders = order_counts[order_counts >= 2].index
            is_multi_order = df['주문고유번호'].isin(multi_orders)
            
            combined_work = self._get_combined_work_name()
            if combined_work:
                df.loc[is_multi_order, '담당자'] = combined_work
                df.loc[is_multi_order, '분류근거'] = '합배송'
                df.loc[is_multi_order, '신뢰도'] = 1.0
        
        # 2. 복수주문 판별
        multiple_work = self._get_multiple_work_name()
        if multiple_work:
            is_multiple = (df['주문수량'] >= self.quantity_threshold) & (df['담당자'] == failed_work)
            df.loc[is_multiple, '담당자'] = multiple_work
            df.loc[is_multiple, '분류근거'] = '복수주문'
            df.loc[is_multiple, '신뢰도'] = 1.0
        
        # 3. 상품별 매칭
        unmatched_mask = df['담당자'] == failed_work
        unmatched_indices = df[unmatched_mask].index
        
        if len(unmatched_indices) > 0:
            compiled_rules = self._compile_matching_rules()
            self._classify_batch(df, unmatched_indices, compiled_rules)
        
        # 4. 정렬
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
        
        # 주문번호 처리
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
            work_config = self.work_config[work_name]
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
        """규칙 매칭 (원본 로직)"""
        # 브랜드 체크
        if rule['brand'] and rule['brand'] != 'All':
            if rule['brand'] not in row['brand']:
                return False
        
        # 상품명 체크
        if rule['product_name'] != 'All':
            if rule['product_name'] not in row['상품명']:
                return False
        
        # 옵션 체크
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
            work_df = df[df['담당자'] == work_name]
            
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
    
    def calculate_statistics(self, df):
        """통계 계산"""
        total_orders = len(df)
        stats = {}
        
        for work_name in self.work_order:
            work_data = df[df['담당자'] == work_name]
            count = len(work_data)
            
            if count > 0:
                stats[work_name] = {
                    'count': count,
                    'percentage': round(count / total_orders * 100, 1)
                }
        
        failed_work = self._get_failed_work_name()
        unmatched_count = len(df[df['담당자'] == failed_work])
        auto_rate = round((total_orders - unmatched_count) / total_orders * 100, 1)
        
        stats['_summary'] = {
            'total_orders': total_orders,
            'auto_classification_rate': auto_rate,
            'unmatched_count': unmatched_count
        }
        
        return stats
    
    def export_to_excel(self, df):
        """엑셀 내보내기"""
        output = BytesIO()
        
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            for work_name in self.work_order:
                work_df = df[df['담당자'] == work_name]
                
                if len(work_df) > 0:
                    sheet_name = work_name[:31]
                    work_df.to_excel(writer, sheet_name=sheet_name, index=False)
        
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