"""
플레이오토 주문 분류 시스템 - 웹앱 v4.1 Ultra
원본 데스크톱 앱(main_optimized.py)의 모든 기능 100% 웹 통합
"""

from flask import Flask, render_template_string, request, send_file, jsonify
from werkzeug.utils import secure_filename
import pandas as pd
from io import BytesIO
from datetime import datetime
import os
import json
import numpy as np
import time

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.secret_key = os.environ.get('SECRET_KEY', 'playauto-secret-key-2024')

ALLOWED_EXTENSIONS = {'xls', 'xlsx'}
SETTINGS_FILE = 'playauto_settings_v4.json'

def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return get_default_settings()

def save_settings(settings):
    with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)

def get_default_settings():
    return {
        "work_order": ["송과장님", "영재씨", "효상", "강민씨", "부모님", "합배송", "복수주문", "분류실패"],
        "work_config": {
            "송과장님": {"type": "product_specific", "products": [], "description": "팥빙수재료 담당", "icon": "🍧", "enabled": True},
            "영재씨": {"type": "product_specific", "products": [], "description": "미에로화이바, 꿀차 담당", "icon": "🍯", "enabled": True},
            "효상": {"type": "product_specific", "products": [], "description": "백제 쌀국수 담당", "icon": "🍜", "enabled": True},
            "강민씨": {"type": "product_specific", "products": [], "description": "백제 브랜드 담당", "icon": "🍜", "enabled": True},
            "부모님": {"type": "product_specific", "products": [], "description": "쟈뎅, 부국, 린저 담당", "icon": "☕", "enabled": True},
            "합배송": {"type": "mixed_products", "products": [], "description": "여러 상품 합배송", "icon": "📦", "enabled": True},
            "복수주문": {"type": "multiple_quantity", "products": [], "description": "2개 이상 주문", "icon": "📋", "enabled": True},
            "분류실패": {"type": "failed", "products": [], "description": "매칭 실패", "icon": "❓", "enabled": True}
        },
        "quantity_threshold": 2, "auto_learn": True, "min_confidence": 1.0
    }

try:
    CURRENT_SETTINGS = load_settings()
    print(f"✅ 설정 로드 완료")
except:
    CURRENT_SETTINGS = get_default_settings()

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


class OrderClassifierV41:
    def __init__(self, settings):
        self.settings = settings
        self.work_order = settings.get('work_order', [])
        self.work_config = settings.get('work_config', {})
        self.quantity_threshold = settings.get('quantity_threshold', 2)
        self.work_ranges = {}
        self.accuracy_metrics = {}
        
    def classify_orders_optimized(self, df):
        df = df.copy()
        df = self._preprocess_data_optimized(df)
        
        failed_work = self._get_failed_work_name()
        df['담당자'] = failed_work
        df['분류근거'] = '매칭 없음'
        df['신뢰도'] = 0.0
        
        # 합배송 판별
        if '주문고유번호' in df.columns:
            order_counts = df['주문고유번호'].value_counts()
            multi_orders = order_counts[order_counts >= 2].index
            is_multi_order = df['주문고유번호'].isin(multi_orders)
            combined_work = self._get_combined_work_name()
            if combined_work:
                df.loc[is_multi_order, '담당자'] = combined_work
                df.loc[is_multi_order, '분류근거'] = '합배송'
                df.loc[is_multi_order, '신뢰도'] = 1.0
        
        # 복수주문 판별
        multiple_work = self._get_multiple_work_name()
        if multiple_work:
            is_multiple = (df['주문수량'] >= self.quantity_threshold) & (df['담당자'] == failed_work)
            df.loc[is_multiple, '담당자'] = multiple_work
            df.loc[is_multiple, '분류근거'] = '복수주문'
            df.loc[is_multiple, '신뢰도'] = 1.0
        
        # 상품별 매칭
        unmatched_mask = df['담당자'] == failed_work
        unmatched_indices = df[unmatched_mask].index
        if len(unmatched_indices) > 0:
            compiled_rules = self._compile_matching_rules()
            self._classify_batch(df, unmatched_indices, compiled_rules)
        
        df = self._sort_results_optimized(df)
        return df
    
    def _preprocess_data_optimized(self, df):
        if '상품명' in df.columns:
            df['상품명'] = df['상품명'].fillna('').astype(str)
        else:
            raise ValueError("필수 컬럼 '상품명'이 없습니다")
        
        if '주문수량' in df.columns:
            df['주문수량'] = pd.to_numeric(df['주문수량'], errors='coerce').fillna(0).astype(int)
        else:
            df['주문수량'] = 1
        
        if '주문선택사항' in df.columns:
            df['주문선택사항'] = df['주문선택사항'].fillna('').astype(str)
            df['full_product_name'] = df['상품명'] + ' ' + df['주문선택사항']
        else:
            df['주문선택사항'] = ''
            df['full_product_name'] = df['상품명']
        
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
        for idx in indices:
            row = df.loc[idx]
            for rule in rules:
                if self._match_rule(row, rule):
                    df.at[idx, '담당자'] = rule['work_name']
                    df.at[idx, '분류근거'] = f"매칭: {rule['brand']} {rule['product_name']}"
                    df.at[idx, '신뢰도'] = 1.0
                    break
    
    def _match_rule(self, row, rule):
        if rule['brand'] and rule['brand'] != 'All':
            if rule['brand'] not in row['brand'] and rule['brand'] not in row['상품명']:
                return False
        if rule['product_name'] != 'All':
            if rule['product_name'] not in row['상품명']:
                return False
        if rule['order_option'] != 'All':
            if rule['order_option'] not in row['주문선택사항']:
                return False
        return True
    
    def _sort_results_optimized(self, df):
        priority_map = {name: i for i, name in enumerate(self.work_order)}
        df['priority'] = df['담당자'].map(priority_map).fillna(len(self.work_order))
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
            cols_to_drop = ['priority', 'brand', 'full_product_name']
            sorted_df = sorted_df.drop([c for c in cols_to_drop if c in sorted_df.columns], axis=1, errors='ignore')
        else:
            sorted_df = df
        return sorted_df
    
    def calculate_statistics(self, df):
        total_orders = len(df)
        self.work_ranges = {}
        work_stats = {}
        current_row = 2
        
        for work_name in self.work_order:
            work_data = df[df['담당자'] == work_name]
            count = len(work_data)
            if count > 0:
                self.work_ranges[work_name] = {
                    'start': current_row, 'end': current_row + count - 1, 'count': count,
                    'icon': self.work_config.get(work_name, {}).get('icon', '📦')
                }
                work_stats[work_name] = {
                    'count': count,
                    'percentage': round(count / total_orders * 100, 1),
                    'avg_confidence': round(work_data['신뢰도'].mean() * 100, 1)
                }
                current_row += count
        
        failed_work = self._get_failed_work_name()
        unmatched_count = len(df[df['담당자'] == failed_work])
        auto_rate = round((total_orders - unmatched_count) / total_orders * 100, 1) if total_orders > 0 else 0
        
        self.accuracy_metrics = {
            'total_orders': total_orders, 'auto_classification_rate': auto_rate,
            'unmatched_count': unmatched_count, 'work_stats': work_stats, 'work_ranges': self.work_ranges
        }
        return self.accuracy_metrics
    
    def export_to_excel(self, df, separate_sheets=True):
        output = BytesIO()
        if separate_sheets:
            with pd.ExcelWriter(output, engine='openpyxl') as writer:
                df.to_excel(writer, sheet_name='전체', index=False)
                for work_name in self.work_order:
                    work_df = df[df['담당자'] == work_name]
                    if len(work_df) > 0:
                        work_df.to_excel(writer, sheet_name=work_name[:31], index=False)
        else:
            df.to_excel(output, index=False, engine='openpyxl')
        output.seek(0)
        return output
    
    def _get_failed_work_name(self):
        for n, c in self.work_config.items():
            if c.get('type') == 'failed': return n
        return '분류실패'
    
    def _get_combined_work_name(self):
        for n, c in self.work_config.items():
            if c.get('type') == 'mixed_products': return n
        return None
    
    def _get_multiple_work_name(self):
        for n, c in self.work_config.items():
            if c.get('type') == 'multiple_quantity': return n
        return None


# 라우트
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/health')
def health():
    return 'OK', 200

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': '파일이 없습니다'}), 400
    file = request.files['file']
    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({'error': '올바른 파일을 선택해주세요'}), 400
    
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
            return jsonify({'error': "'주의메세지' 컬럼을 찾을 수 없습니다"}), 400
        
        mask = df[target_col].astype(str).str.startswith('판매자 스타배송', na=False)
        df_filtered = df[~mask]
        deleted_count = original_count - len(df_filtered)
        
        output = BytesIO()
        df_filtered.to_excel(output, index=False, engine='openpyxl')
        output.seek(0)
        
        return send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True, download_name=f"filtered_{datetime.now().strftime('%H%M%S')}.xlsx"
        ), 200, {'X-Deleted-Count': str(deleted_count), 'X-Original-Count': str(original_count)}
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/classify', methods=['POST'])
def classify_orders():
    global CURRENT_SETTINGS
    if 'file' not in request.files:
        return jsonify({'error': '파일이 없습니다'}), 400
    file = request.files['file']
    if file.filename == '' or not allowed_file(file.filename):
        return jsonify({'error': '올바른 파일을 선택해주세요'}), 400
    
    CURRENT_SETTINGS = load_settings()
    
    try:
        start_time = time.time()
        ext = file.filename.rsplit('.', 1)[1].lower()
        df = pd.read_excel(file, engine='xlrd' if ext == 'xls' else 'openpyxl')
        
        classifier = OrderClassifierV41(CURRENT_SETTINGS)
        classified_df = classifier.classify_orders_optimized(df)
        stats = classifier.calculate_statistics(classified_df)
        
        separate_sheets = request.form.get('separate_sheets', 'true').lower() == 'true'
        output = classifier.export_to_excel(classified_df, separate_sheets=separate_sheets)
        
        stats['processing_time'] = round(time.time() - start_time, 2)
        
        response = send_file(output, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True, download_name=f"classified_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx")
        response.headers['X-Stats'] = json.dumps(stats, ensure_ascii=False)
        return response
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route('/settings', methods=['GET'])
def get_settings():
    global CURRENT_SETTINGS
    CURRENT_SETTINGS = load_settings()
    total_products = sum(len(c.get('products', [])) for c in CURRENT_SETTINGS.get('work_config', {}).values())
    return jsonify({'status': 'loaded', 'settings': CURRENT_SETTINGS, 
                   'workers': list(CURRENT_SETTINGS.get('work_order', [])), 'total_products': total_products})


@app.route('/settings', methods=['POST'])
def update_settings():
    global CURRENT_SETTINGS
    try:
        data = request.get_json()
        if 'work_order' in data: CURRENT_SETTINGS['work_order'] = data['work_order']
        if 'work_config' in data: CURRENT_SETTINGS['work_config'] = data['work_config']
        if 'quantity_threshold' in data: CURRENT_SETTINGS['quantity_threshold'] = int(data['quantity_threshold'])
        save_settings(CURRENT_SETTINGS)
        return jsonify({'status': 'success', 'message': '설정이 저장되었습니다'})
    except Exception as e:
        return jsonify({'status': 'error', 'error': str(e)}), 500


@app.route('/workers', methods=['GET'])
def get_workers():
    global CURRENT_SETTINGS
    CURRENT_SETTINGS = load_settings()
    workers = []
    for name in CURRENT_SETTINGS.get('work_order', []):
        c = CURRENT_SETTINGS['work_config'].get(name, {})
        workers.append({'name': name, 'type': c.get('type', 'product_specific'), 'icon': c.get('icon', '📦'),
                       'description': c.get('description', ''), 'enabled': c.get('enabled', True),
                       'products_count': len(c.get('products', []))})
    return jsonify({'workers': workers})


@app.route('/workers', methods=['POST'])
def add_worker():
    global CURRENT_SETTINGS
    try:
        data = request.get_json()
        name = data.get('name', '').strip()
        if not name: return jsonify({'error': '담당자 이름을 입력해주세요'}), 400
        if name in CURRENT_SETTINGS['work_config']: return jsonify({'error': '이미 존재하는 담당자입니다'}), 400
        
        failed_idx = -1
        for i, n in enumerate(CURRENT_SETTINGS['work_order']):
            if CURRENT_SETTINGS['work_config'].get(n, {}).get('type') == 'failed':
                failed_idx = i
                break
        
        if failed_idx >= 0: CURRENT_SETTINGS['work_order'].insert(failed_idx, name)
        else: CURRENT_SETTINGS['work_order'].append(name)
        
        CURRENT_SETTINGS['work_config'][name] = {
            "type": "product_specific", "products": [], "description": data.get('description', f"{name} 담당"),
            "icon": data.get('icon', '👤'), "enabled": True
        }
        save_settings(CURRENT_SETTINGS)
        return jsonify({'status': 'success', 'message': f'{name} 담당자가 추가되었습니다'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/workers/<name>', methods=['PUT'])
def update_worker(name):
    global CURRENT_SETTINGS
    try:
        if name not in CURRENT_SETTINGS['work_config']: return jsonify({'error': '존재하지 않는 담당자입니다'}), 404
        data = request.get_json()
        c = CURRENT_SETTINGS['work_config'][name]
        if 'icon' in data: c['icon'] = data['icon']
        if 'description' in data: c['description'] = data['description']
        if 'enabled' in data: c['enabled'] = data['enabled']
        
        if 'new_name' in data and data['new_name'] != name:
            new_name = data['new_name'].strip()
            if new_name in CURRENT_SETTINGS['work_config']: return jsonify({'error': '이미 존재하는 이름입니다'}), 400
            idx = CURRENT_SETTINGS['work_order'].index(name)
            CURRENT_SETTINGS['work_order'][idx] = new_name
            CURRENT_SETTINGS['work_config'][new_name] = CURRENT_SETTINGS['work_config'].pop(name)
        
        save_settings(CURRENT_SETTINGS)
        return jsonify({'status': 'success', 'message': '담당자 정보가 수정되었습니다'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/workers/<name>', methods=['DELETE'])
def delete_worker(name):
    global CURRENT_SETTINGS
    try:
        if name not in CURRENT_SETTINGS['work_config']: return jsonify({'error': '존재하지 않는 담당자입니다'}), 404
        if CURRENT_SETTINGS['work_config'][name].get('type') in ['mixed_products', 'multiple_quantity', 'failed']:
            return jsonify({'error': '시스템 담당자는 삭제할 수 없습니다'}), 400
        CURRENT_SETTINGS['work_order'].remove(name)
        del CURRENT_SETTINGS['work_config'][name]
        save_settings(CURRENT_SETTINGS)
        return jsonify({'status': 'success', 'message': f'{name} 담당자가 삭제되었습니다'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/products/<worker_name>', methods=['GET'])
def get_products(worker_name):
    global CURRENT_SETTINGS
    CURRENT_SETTINGS = load_settings()
    if worker_name not in CURRENT_SETTINGS['work_config']: return jsonify({'error': '존재하지 않는 담당자입니다'}), 404
    products = CURRENT_SETTINGS['work_config'][worker_name].get('products', [])
    return jsonify({'worker_name': worker_name, 'products': products, 'count': len(products)})


@app.route('/products/<worker_name>', methods=['POST'])
def add_product(worker_name):
    global CURRENT_SETTINGS
    try:
        if worker_name not in CURRENT_SETTINGS['work_config']: return jsonify({'error': '존재하지 않는 담당자입니다'}), 404
        data = request.get_json()
        new_product = {'brand': data.get('brand', '').strip(), 'product_name': data.get('product_name', '').strip(),
                      'order_option': data.get('order_option', 'All').strip() or 'All'}
        if not new_product['product_name']: return jsonify({'error': '상품명은 필수입니다'}), 400
        CURRENT_SETTINGS['work_config'][worker_name]['products'].append(new_product)
        save_settings(CURRENT_SETTINGS)
        return jsonify({'status': 'success', 'message': '상품 규칙이 추가되었습니다'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/products/<worker_name>/<int:index>', methods=['PUT'])
def update_product(worker_name, index):
    global CURRENT_SETTINGS
    try:
        if worker_name not in CURRENT_SETTINGS['work_config']: return jsonify({'error': '존재하지 않는 담당자입니다'}), 404
        products = CURRENT_SETTINGS['work_config'][worker_name].get('products', [])
        if index < 0 or index >= len(products): return jsonify({'error': '잘못된 인덱스입니다'}), 404
        data = request.get_json()
        products[index] = {'brand': data.get('brand', '').strip(), 'product_name': data.get('product_name', '').strip(),
                          'order_option': data.get('order_option', 'All').strip() or 'All'}
        save_settings(CURRENT_SETTINGS)
        return jsonify({'status': 'success', 'message': '상품 규칙이 수정되었습니다'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/products/<worker_name>/<int:index>', methods=['DELETE'])
def delete_product(worker_name, index):
    global CURRENT_SETTINGS
    try:
        if worker_name not in CURRENT_SETTINGS['work_config']: return jsonify({'error': '존재하지 않는 담당자입니다'}), 404
        products = CURRENT_SETTINGS['work_config'][worker_name].get('products', [])
        if index < 0 or index >= len(products): return jsonify({'error': '잘못된 인덱스입니다'}), 404
        products.pop(index)
        save_settings(CURRENT_SETTINGS)
        return jsonify({'status': 'success', 'message': '상품 규칙이 삭제되었습니다'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/settings/upload', methods=['POST'])
def upload_settings():
    global CURRENT_SETTINGS
    if 'file' not in request.files: return jsonify({'error': '파일이 없습니다'}), 400
    file = request.files['file']
    try:
        new_settings = json.loads(file.read().decode('utf-8'))
        if 'work_order' not in new_settings or 'work_config' not in new_settings:
            return jsonify({'error': '유효하지 않은 설정 파일입니다'}), 400
        CURRENT_SETTINGS = new_settings
        save_settings(CURRENT_SETTINGS)
        return jsonify({'status': 'success', 'message': '설정 파일이 업로드되었습니다'})
    except:
        return jsonify({'error': 'JSON 형식이 올바르지 않습니다'}), 400


@app.route('/settings/download', methods=['GET'])
def download_settings():
    global CURRENT_SETTINGS
    CURRENT_SETTINGS = load_settings()
    output = BytesIO()
    output.write(json.dumps(CURRENT_SETTINGS, ensure_ascii=False, indent=2).encode('utf-8'))
    output.seek(0)
    return send_file(output, mimetype='application/json', as_attachment=True,
                    download_name=f'playauto_settings_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json')


HTML_TEMPLATE = '''<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>플레이오토 송장 분류 시스템 v4.1</title>
<link href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css" rel="stylesheet">
<style>
:root{--bg:#0a0a0a;--bg2:#111;--card:#1a1a1a;--hover:#252525;--border:#2a2a2a;--text:#fff;--text2:#888;--text3:#555;--green:#00ff88;--blue:#0088ff;--pink:#ff0088;--yellow:#ffdd00}
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
.app{display:flex;min-height:100vh}
.sidebar{width:260px;background:var(--bg2);border-right:1px solid var(--border);position:fixed;height:100vh;z-index:100}
.logo{padding:20px;border-bottom:1px solid var(--border)}
.logo h1{font-size:18px;color:var(--green);display:flex;align-items:center;gap:8px}
.logo span{font-size:11px;color:var(--text2);display:block;margin-top:4px}
.nav{padding:16px}
.nav-section{margin-bottom:20px}
.nav-title{font-size:10px;color:var(--text3);text-transform:uppercase;letter-spacing:1px;padding:8px 12px}
.nav-item{display:flex;align-items:center;gap:10px;padding:10px 14px;border-radius:8px;cursor:pointer;color:var(--text2);text-decoration:none;transition:.2s}
.nav-item:hover{background:var(--hover);color:var(--text)}
.nav-item.active{background:linear-gradient(135deg,rgba(0,255,136,.1),rgba(0,136,255,.1));color:var(--green);border:1px solid rgba(0,255,136,.2)}
.nav-item i{width:18px;text-align:center}
.main{flex:1;margin-left:260px;padding:20px;min-height:100vh}
.page{display:none}.page.active{display:block}
.page-header{margin-bottom:20px}
.page-header h2{font-size:24px;margin-bottom:6px}
.page-header p{color:var(--text2);font-size:14px}
.card{background:var(--card);border-radius:10px;border:1px solid var(--border);padding:20px;margin-bottom:16px}
.card-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:16px}
.card-title{font-size:16px;font-weight:600;display:flex;align-items:center;gap:8px}
.drop-zone{border:2px dashed var(--blue);border-radius:10px;padding:50px 30px;text-align:center;cursor:pointer;transition:.3s;background:rgba(0,136,255,.05)}
.drop-zone:hover,.drop-zone.dragover{border-color:var(--green);background:rgba(0,255,136,.1)}
.drop-zone i{font-size:40px;color:var(--blue);margin-bottom:12px}
.drop-zone h3{font-size:16px;margin-bottom:6px}
.drop-zone p{color:var(--text2);font-size:13px}
.btn{display:inline-flex;align-items:center;gap:6px;padding:10px 20px;border-radius:6px;font-size:13px;font-weight:500;cursor:pointer;transition:.2s;border:none}
.btn-primary{background:var(--green);color:var(--bg)}
.btn-primary:hover{box-shadow:0 0 16px rgba(0,255,136,.4)}
.btn-primary:disabled{opacity:.5;cursor:not-allowed}
.btn-secondary{background:var(--hover);color:var(--text);border:1px solid var(--border)}
.btn-danger{background:var(--pink);color:#fff}
.btn-small{padding:6px 12px;font-size:11px}
.form-group{margin-bottom:14px}
.form-label{display:block;font-size:12px;color:var(--text2);margin-bottom:4px}
.form-input{width:100%;padding:10px 14px;background:var(--bg2);border:1px solid var(--border);border-radius:6px;color:var(--text);font-size:13px}
.form-input:focus{outline:none;border-color:var(--blue)}
table{width:100%;border-collapse:collapse}
th,td{padding:12px 14px;text-align:left;border-bottom:1px solid var(--border)}
th{font-size:11px;text-transform:uppercase;color:var(--text2);font-weight:600}
tr:hover{background:var(--hover)}
.stats-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:14px;margin-bottom:20px}
.stat-card{background:var(--card);border-radius:10px;padding:16px;border:1px solid var(--border)}
.stat-card h4{font-size:12px;color:var(--text2);margin-bottom:6px}
.stat-card .value{font-size:28px;font-weight:700;color:var(--green)}
.stat-card .label{font-size:11px;color:var(--text3);margin-top:2px}
.result-panel{background:var(--bg2);border-radius:10px;padding:16px;margin-top:16px}
.result-item{display:flex;justify-content:space-between;align-items:center;padding:10px 0;border-bottom:1px solid var(--border)}
.result-item:last-child{border-bottom:none}
.result-item .icon{font-size:20px;margin-right:10px}
.result-item .info{flex:1}
.result-item .name{font-weight:500}
.result-item .meta{font-size:11px;color:var(--text2)}
.result-item .count{font-size:18px;font-weight:700;color:var(--green)}
.progress-container{display:none;margin:16px 0}
.progress-bar{height:6px;background:var(--bg2);border-radius:3px;overflow:hidden}
.progress-fill{height:100%;background:linear-gradient(90deg,var(--green),var(--blue));width:0%;transition:width .3s}
.progress-text{text-align:center;margin-top:6px;font-size:13px;color:var(--text2)}
.modal{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,.8);z-index:1000;align-items:center;justify-content:center}
.modal.active{display:flex}
.modal-content{background:var(--card);border-radius:12px;padding:24px;max-width:460px;width:90%;max-height:80vh;overflow-y:auto}
.modal-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:20px}
.modal-header h3{font-size:18px}
.modal-close{background:none;border:none;color:var(--text2);font-size:20px;cursor:pointer}
.modal-footer{display:flex;gap:10px;justify-content:flex-end;margin-top:20px}
.toast-container{position:fixed;top:20px;right:20px;z-index:2000}
.toast{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:14px 18px;margin-bottom:10px;display:flex;align-items:center;gap:10px;animation:slideIn .3s;min-width:280px}
.toast.success{border-color:var(--green)}
.toast.error{border-color:var(--pink)}
@keyframes slideIn{from{transform:translateX(100%);opacity:0}to{transform:translateX(0);opacity:1}}
.worker-list{max-height:360px;overflow-y:auto}
.worker-item{display:flex;align-items:center;padding:14px;border-bottom:1px solid var(--border);cursor:pointer;transition:.2s}
.worker-item:hover{background:var(--hover)}
.worker-item.selected{background:rgba(0,255,136,.1);border-left:3px solid var(--green)}
.worker-icon{font-size:24px;margin-right:14px}
.worker-info{flex:1}
.worker-name{font-weight:600;margin-bottom:2px}
.worker-desc{font-size:11px;color:var(--text2)}
.worker-badge{background:var(--bg2);padding:3px 10px;border-radius:16px;font-size:11px;color:var(--green)}
.product-list{max-height:440px;overflow-y:auto}
.product-item{display:flex;align-items:center;padding:10px 14px;border-bottom:1px solid var(--border)}
.product-item:hover{background:var(--hover)}
.product-info{flex:1}
.product-brand{font-size:11px;color:var(--blue);margin-bottom:2px}
.product-name{font-weight:500}
.product-option{font-size:11px;color:var(--text2)}
.product-actions{display:flex;gap:6px}
.product-actions button{background:none;border:none;color:var(--text2);cursor:pointer;padding:4px;border-radius:4px}
.product-actions button:hover{background:var(--bg2);color:var(--text)}
.settings-grid{display:grid;grid-template-columns:repeat(2,1fr);gap:20px}
@media(max-width:1200px){.settings-grid{grid-template-columns:1fr}}
.empty-state{text-align:center;padding:50px 16px;color:var(--text2)}
.empty-state i{font-size:40px;margin-bottom:12px;color:var(--text3)}
.alert{padding:14px 18px;border-radius:6px;margin-bottom:16px;display:flex;align-items:center;gap:10px}
.alert.success{background:rgba(0,255,136,.1);border:1px solid var(--green);color:var(--green)}
@media(max-width:768px){.sidebar{transform:translateX(-100%)}.main{margin-left:0}}
</style>
</head>
<body>
<div class="app">
<aside class="sidebar">
<div class="logo"><h1>⚡ PlayAuto</h1><span>v4.1 Ultra Performance Edition</span></div>
<nav class="nav">
<div class="nav-section">
<div class="nav-title">메인</div>
<a class="nav-item active" data-page="home"><i class="fas fa-home"></i><span>홈</span></a>
<a class="nav-item" data-page="filter"><i class="fas fa-filter"></i><span>스타배송 필터</span></a>
<a class="nav-item" data-page="classify"><i class="fas fa-tags"></i><span>송장 분류</span></a>
</div>
<div class="nav-section">
<div class="nav-title">설정</div>
<a class="nav-item" data-page="workers"><i class="fas fa-users"></i><span>담당자 관리</span></a>
<a class="nav-item" data-page="products"><i class="fas fa-box"></i><span>상품 규칙</span></a>
<a class="nav-item" data-page="settings"><i class="fas fa-cog"></i><span>환경 설정</span></a>
</div>
</nav>
</aside>
<main class="main">
<div id="page-home" class="page active">
<div class="page-header"><h2>대시보드</h2><p>플레이오토 주문 분류 시스템</p></div>
<div class="stats-grid" id="home-stats">
<div class="stat-card"><h4>등록된 담당자</h4><div class="value" id="stat-workers">-</div><div class="label">명</div></div>
<div class="stat-card"><h4>상품 규칙</h4><div class="value" id="stat-products">-</div><div class="label">개</div></div>
<div class="stat-card"><h4>복수주문 기준</h4><div class="value" id="stat-threshold">-</div><div class="label">개 이상</div></div>
<div class="stat-card"><h4>시스템 상태</h4><div class="value" style="color:var(--green)">●</div><div class="label">정상 작동</div></div>
</div>
<div class="card"><div class="card-header"><div class="card-title"><i class="fas fa-list"></i>담당자별 현황</div></div>
<table id="workers-summary-table"><thead><tr><th>순서</th><th>담당자</th><th>유형</th><th>상품 규칙</th><th>설명</th></tr></thead><tbody></tbody></table>
</div>
</div>

<div id="page-filter" class="page">
<div class="page-header"><h2>스타배송 필터</h2><p>"판매자 스타배송" 행을 자동 제거</p></div>
<div class="card">
<div class="drop-zone" id="filter-dropzone"><i class="fas fa-cloud-upload-alt"></i><h3>엑셀 파일을 드래그하거나 클릭</h3><p>.xlsx, .xls 파일 지원</p></div>
<input type="file" id="filter-file" accept=".xlsx,.xls" style="display:none">
<div class="progress-container" id="filter-progress"><div class="progress-bar"><div class="progress-fill"></div></div><div class="progress-text">처리 중...</div></div>
<div id="filter-result" style="display:none;margin-top:16px"><div class="alert success"><i class="fas fa-check-circle"></i><span id="filter-result-text"></span></div></div>
</div>
</div>

<div id="page-classify" class="page">
<div class="page-header"><h2>송장 분류</h2><p>주문 데이터를 담당자별로 자동 분류</p></div>
<div class="card">
<div class="drop-zone" id="classify-dropzone"><i class="fas fa-tags"></i><h3>주문 엑셀 파일 업로드</h3><p>상품명, 주문수량, 주문고유번호 컬럼 필요</p></div>
<input type="file" id="classify-file" accept=".xlsx,.xls" style="display:none">
<div style="margin-top:12px"><label style="display:flex;align-items:center;gap:6px;cursor:pointer"><input type="checkbox" id="separate-sheets" checked><span>담당자별 시트 분리</span></label></div>
<div class="progress-container" id="classify-progress"><div class="progress-bar"><div class="progress-fill"></div></div><div class="progress-text">분류 중...</div></div>
</div>
<div id="classify-result" style="display:none">
<div class="stats-grid">
<div class="stat-card"><h4>전체 주문</h4><div class="value" id="result-total">0</div><div class="label">건</div></div>
<div class="stat-card"><h4>자동 분류율</h4><div class="value" id="result-rate">0</div><div class="label">%</div></div>
<div class="stat-card"><h4>미분류</h4><div class="value" id="result-unmatched" style="color:var(--yellow)">0</div><div class="label">건</div></div>
<div class="stat-card"><h4>처리 시간</h4><div class="value" id="result-time">0</div><div class="label">초</div></div>
</div>
<div class="card"><div class="card-header"><div class="card-title"><i class="fas fa-chart-bar"></i>담당자별 분류 결과</div></div><div class="result-panel" id="classify-details"></div></div>
</div>
</div>

<div id="page-workers" class="page">
<div class="page-header"><h2>담당자 관리</h2><p>담당자 추가, 수정, 삭제 및 우선순위 관리</p></div>
<div class="settings-grid">
<div class="card"><div class="card-header"><div class="card-title"><i class="fas fa-users"></i>담당자 목록</div><button class="btn btn-primary btn-small" onclick="showAddWorkerModal()"><i class="fas fa-plus"></i> 추가</button></div><div class="worker-list" id="worker-list"></div></div>
<div class="card"><div class="card-header"><div class="card-title"><i class="fas fa-edit"></i>담당자 정보</div></div><div id="worker-detail"><div class="empty-state"><i class="fas fa-user-circle"></i><p>왼쪽에서 담당자를 선택하세요</p></div></div></div>
</div>
</div>

<div id="page-products" class="page">
<div class="page-header"><h2>상품 규칙 설정</h2><p>담당자별 상품 매칭 규칙 관리</p></div>
<div class="card"><div class="card-header"><div class="card-title"><i class="fas fa-user"></i>담당자 선택</div></div><select class="form-input" id="product-worker-select" style="max-width:280px"><option value="">담당자를 선택하세요</option></select></div>
<div id="product-rules-container" style="display:none"><div class="card"><div class="card-header"><div class="card-title"><i class="fas fa-box"></i><span id="selected-worker-name">상품 규칙</span><span class="worker-badge" id="product-count">0개</span></div><button class="btn btn-primary btn-small" onclick="showAddProductModal()"><i class="fas fa-plus"></i> 규칙 추가</button></div><div class="product-list" id="product-list"></div></div></div>
</div>

<div id="page-settings" class="page">
<div class="page-header"><h2>환경 설정</h2><p>시스템 설정 및 데이터 관리</p></div>
<div class="settings-grid">
<div class="card"><div class="card-header"><div class="card-title"><i class="fas fa-sliders-h"></i>기본 설정</div></div><div class="form-group"><label class="form-label">복수주문 기준 수량</label><input type="number" class="form-input" id="quantity-threshold" value="2" min="2" max="100"><small style="color:var(--text2)">이 수량 이상 주문 시 '복수주문'으로 분류</small></div><button class="btn btn-primary" onclick="saveGeneralSettings()"><i class="fas fa-save"></i> 저장</button></div>
<div class="card"><div class="card-header"><div class="card-title"><i class="fas fa-database"></i>데이터 관리</div></div><div style="display:flex;flex-direction:column;gap:10px"><button class="btn btn-secondary" onclick="downloadSettings()"><i class="fas fa-download"></i> 설정 다운로드</button><input type="file" id="settings-upload" accept=".json" style="display:none"><button class="btn btn-secondary" onclick="document.getElementById('settings-upload').click()"><i class="fas fa-upload"></i> 설정 업로드</button></div></div>
</div>
</div>
</main>
</div>

<div class="toast-container" id="toast-container"></div>

<div class="modal" id="add-worker-modal"><div class="modal-content"><div class="modal-header"><h3>담당자 추가</h3><button class="modal-close" onclick="closeModal('add-worker-modal')">&times;</button></div><div class="form-group"><label class="form-label">담당자 이름 *</label><input type="text" class="form-input" id="new-worker-name" placeholder="예: 홍길동"></div><div class="form-group"><label class="form-label">아이콘</label><input type="text" class="form-input" id="new-worker-icon" value="👤"></div><div class="form-group"><label class="form-label">설명</label><input type="text" class="form-input" id="new-worker-desc" placeholder="담당 업무"></div><div class="modal-footer"><button class="btn btn-secondary" onclick="closeModal('add-worker-modal')">취소</button><button class="btn btn-primary" onclick="addWorker()">추가</button></div></div></div>

<div class="modal" id="add-product-modal"><div class="modal-content"><div class="modal-header"><h3>상품 규칙 추가</h3><button class="modal-close" onclick="closeModal('add-product-modal')">&times;</button></div><div class="form-group"><label class="form-label">브랜드</label><input type="text" class="form-input" id="new-product-brand" placeholder="예: 꽃샘"></div><div class="form-group"><label class="form-label">상품명 *</label><input type="text" class="form-input" id="new-product-name" placeholder="예: 꿀유자차S"></div><div class="form-group"><label class="form-label">주문옵션</label><input type="text" class="form-input" id="new-product-option" value="All"></div><div class="modal-footer"><button class="btn btn-secondary" onclick="closeModal('add-product-modal')">취소</button><button class="btn btn-primary" onclick="addProduct()">추가</button></div></div></div>

<div class="modal" id="edit-product-modal"><div class="modal-content"><div class="modal-header"><h3>상품 규칙 수정</h3><button class="modal-close" onclick="closeModal('edit-product-modal')">&times;</button></div><input type="hidden" id="edit-product-index"><div class="form-group"><label class="form-label">브랜드</label><input type="text" class="form-input" id="edit-product-brand"></div><div class="form-group"><label class="form-label">상품명 *</label><input type="text" class="form-input" id="edit-product-name"></div><div class="form-group"><label class="form-label">주문옵션</label><input type="text" class="form-input" id="edit-product-option"></div><div class="modal-footer"><button class="btn btn-secondary" onclick="closeModal('edit-product-modal')">취소</button><button class="btn btn-primary" onclick="updateProduct()">저장</button></div></div></div>

<script>
let currentSettings=null,selectedWorker=null,selectedProductWorker=null;
document.querySelectorAll('.nav-item').forEach(item=>{item.addEventListener('click',e=>{e.preventDefault();const page=item.dataset.page;document.querySelectorAll('.nav-item').forEach(i=>i.classList.remove('active'));item.classList.add('active');document.querySelectorAll('.page').forEach(p=>p.classList.remove('active'));document.getElementById('page-'+page).classList.add('active');if(page==='home')loadHomeData();if(page==='workers')loadWorkers();if(page==='products')loadProductWorkers();if(page==='settings')loadSettings()})});
function showToast(msg,type='success'){const c=document.getElementById('toast-container'),t=document.createElement('div');t.className='toast '+type;t.innerHTML='<i class="fas fa-'+(type==='success'?'check':'exclamation')+'-circle"></i><span>'+msg+'</span>';c.appendChild(t);setTimeout(()=>t.remove(),3000)}
function showModal(id){document.getElementById(id).classList.add('active')}
function closeModal(id){document.getElementById(id).classList.remove('active')}
function getTypeLabel(t){return{product_specific:'상품 매칭',mixed_products:'합배송',multiple_quantity:'복수주문',failed:'분류실패'}[t]||t}

async function loadHomeData(){try{const r=await fetch('/settings'),d=await r.json();if(d.status==='loaded'){currentSettings=d.settings;document.getElementById('stat-workers').textContent=d.workers.length;document.getElementById('stat-products').textContent=d.total_products;document.getElementById('stat-threshold').textContent=d.settings.quantity_threshold||2;const tbody=document.querySelector('#workers-summary-table tbody');tbody.innerHTML='';d.workers.forEach((n,i)=>{const c=d.settings.work_config[n],row=document.createElement('tr');row.innerHTML='<td>'+(i+1)+'</td><td>'+(c.icon||'📦')+' '+n+'</td><td>'+getTypeLabel(c.type)+'</td><td>'+(c.products?c.products.length:0)+'개</td><td style="color:var(--text2)">'+(c.description||'-')+'</td>';tbody.appendChild(row)})}}catch(e){console.error(e)}}

const filterDZ=document.getElementById('filter-dropzone'),filterF=document.getElementById('filter-file');
filterDZ.addEventListener('click',()=>filterF.click());filterDZ.addEventListener('dragover',e=>{e.preventDefault();filterDZ.classList.add('dragover')});filterDZ.addEventListener('dragleave',()=>filterDZ.classList.remove('dragover'));filterDZ.addEventListener('drop',e=>{e.preventDefault();filterDZ.classList.remove('dragover');if(e.dataTransfer.files.length)processFilterFile(e.dataTransfer.files[0])});filterF.addEventListener('change',e=>{if(e.target.files.length)processFilterFile(e.target.files[0])});
async function processFilterFile(file){const prog=document.getElementById('filter-progress'),res=document.getElementById('filter-result');prog.style.display='block';res.style.display='none';const fd=new FormData();fd.append('file',file);try{const r=await fetch('/upload',{method:'POST',body:fd});if(r.ok){const del=r.headers.get('X-Deleted-Count'),org=r.headers.get('X-Original-Count'),blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='filtered.xlsx';a.click();document.getElementById('filter-result-text').textContent='완료! '+org+'건 중 '+del+'건 삭제';res.style.display='block';showToast('필터 완료!')}else{const e=await r.json();showToast(e.error,'error')}}catch(e){showToast('오류 발생','error')}finally{prog.style.display='none'}}

const classifyDZ=document.getElementById('classify-dropzone'),classifyF=document.getElementById('classify-file');
classifyDZ.addEventListener('click',()=>classifyF.click());classifyDZ.addEventListener('dragover',e=>{e.preventDefault();classifyDZ.classList.add('dragover')});classifyDZ.addEventListener('dragleave',()=>classifyDZ.classList.remove('dragover'));classifyDZ.addEventListener('drop',e=>{e.preventDefault();classifyDZ.classList.remove('dragover');if(e.dataTransfer.files.length)processClassifyFile(e.dataTransfer.files[0])});classifyF.addEventListener('change',e=>{if(e.target.files.length)processClassifyFile(e.target.files[0])});
async function processClassifyFile(file){const prog=document.getElementById('classify-progress'),res=document.getElementById('classify-result');prog.style.display='block';res.style.display='none';const fd=new FormData();fd.append('file',file);fd.append('separate_sheets',document.getElementById('separate-sheets').checked);try{const r=await fetch('/classify',{method:'POST',body:fd});if(r.ok){const sh=r.headers.get('X-Stats'),stats=sh?JSON.parse(sh):{},blob=await r.blob(),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='classified.xlsx';a.click();document.getElementById('result-total').textContent=stats.total_orders||0;document.getElementById('result-rate').textContent=stats.auto_classification_rate||0;document.getElementById('result-unmatched').textContent=stats.unmatched_count||0;document.getElementById('result-time').textContent=stats.processing_time||0;const det=document.getElementById('classify-details');det.innerHTML='';if(stats.work_ranges){for(const[n,rng]of Object.entries(stats.work_ranges)){const it=document.createElement('div');it.className='result-item';it.innerHTML='<span class="icon">'+rng.icon+'</span><div class="info"><div class="name">'+n+'</div><div class="meta">행 '+rng.start+' ~ '+rng.end+'</div></div><div class="count">'+rng.count+'건</div>';det.appendChild(it)}}res.style.display='block';showToast('분류 완료!');if(stats.auto_classification_rate===100)showToast('🎉 100% 완벽!')}else{const e=await r.json();showToast(e.error,'error')}}catch(e){showToast('오류 발생','error')}finally{prog.style.display='none'}}

async function loadWorkers(){try{const r=await fetch('/workers'),d=await r.json(),list=document.getElementById('worker-list');list.innerHTML='';d.workers.forEach(w=>{const it=document.createElement('div');it.className='worker-item'+(selectedWorker===w.name?' selected':'');it.innerHTML='<span class="worker-icon">'+w.icon+'</span><div class="worker-info"><div class="worker-name">'+w.name+'</div><div class="worker-desc">'+(w.description||'-')+'</div></div><span class="worker-badge">'+w.products_count+'개</span>';it.addEventListener('click',()=>selectWorker(w,it));list.appendChild(it)})}catch(e){console.error(e)}}
function selectWorker(w,el){selectedWorker=w.name;document.querySelectorAll('.worker-item').forEach(i=>i.classList.remove('selected'));el.classList.add('selected');const det=document.getElementById('worker-detail'),isSys=['mixed_products','multiple_quantity','failed'].includes(w.type);det.innerHTML='<div class="form-group"><label class="form-label">이름</label><input type="text" class="form-input" id="edit-worker-name" value="'+w.name+'" '+(isSys?'disabled':'')+'></div><div class="form-group"><label class="form-label">아이콘</label><input type="text" class="form-input" id="edit-worker-icon" value="'+w.icon+'"></div><div class="form-group"><label class="form-label">설명</label><input type="text" class="form-input" id="edit-worker-desc" value="'+(w.description||'')+'"></div><div class="form-group"><label class="form-label">유형</label><input type="text" class="form-input" value="'+getTypeLabel(w.type)+'" disabled></div><div style="display:flex;gap:10px;margin-top:20px"><button class="btn btn-primary" onclick="saveWorker(\''+w.name+'\')"><i class="fas fa-save"></i> 저장</button>'+(isSys?'':'<button class="btn btn-danger" onclick="deleteWorker(\''+w.name+'\')"><i class="fas fa-trash"></i> 삭제</button>')+'</div>'}
function showAddWorkerModal(){document.getElementById('new-worker-name').value='';document.getElementById('new-worker-icon').value='👤';document.getElementById('new-worker-desc').value='';showModal('add-worker-modal')}
async function addWorker(){const n=document.getElementById('new-worker-name').value.trim(),ic=document.getElementById('new-worker-icon').value.trim()||'👤',desc=document.getElementById('new-worker-desc').value.trim();if(!n){showToast('이름 입력 필요','error');return}try{const r=await fetch('/workers',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:n,icon:ic,description:desc})}),d=await r.json();if(r.ok){showToast(d.message);closeModal('add-worker-modal');loadWorkers();loadHomeData()}else showToast(d.error,'error')}catch(e){showToast('오류','error')}}
async function saveWorker(orig){const nn=document.getElementById('edit-worker-name').value.trim(),ic=document.getElementById('edit-worker-icon').value.trim(),desc=document.getElementById('edit-worker-desc').value.trim();try{const r=await fetch('/workers/'+encodeURIComponent(orig),{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({new_name:nn!==orig?nn:undefined,icon:ic,description:desc})}),d=await r.json();if(r.ok){showToast(d.message);selectedWorker=nn||orig;loadWorkers();loadHomeData()}else showToast(d.error,'error')}catch(e){showToast('오류','error')}}
async function deleteWorker(n){if(!confirm("'"+n+"' 삭제?"))return;try{const r=await fetch('/workers/'+encodeURIComponent(n),{method:'DELETE'}),d=await r.json();if(r.ok){showToast(d.message);selectedWorker=null;document.getElementById('worker-detail').innerHTML='<div class="empty-state"><i class="fas fa-user-circle"></i><p>담당자 선택</p></div>';loadWorkers();loadHomeData()}else showToast(d.error,'error')}catch(e){showToast('오류','error')}}

async function loadProductWorkers(){try{const r=await fetch('/workers'),d=await r.json(),sel=document.getElementById('product-worker-select');sel.innerHTML='<option value="">담당자 선택</option>';d.workers.forEach(w=>{if(w.type==='product_specific'){const o=document.createElement('option');o.value=w.name;o.textContent=w.icon+' '+w.name+' ('+w.products_count+'개)';if(selectedProductWorker===w.name)o.selected=true;sel.appendChild(o)}});if(selectedProductWorker)loadProducts(selectedProductWorker)}catch(e){console.error(e)}}
document.getElementById('product-worker-select').addEventListener('change',e=>{selectedProductWorker=e.target.value;if(selectedProductWorker)loadProducts(selectedProductWorker);else document.getElementById('product-rules-container').style.display='none'});
async function loadProducts(wn){try{const r=await fetch('/products/'+encodeURIComponent(wn)),d=await r.json();document.getElementById('product-rules-container').style.display='block';document.getElementById('selected-worker-name').textContent=wn+' 상품 규칙';document.getElementById('product-count').textContent=d.count+'개';const list=document.getElementById('product-list');list.innerHTML='';if(d.products.length===0){list.innerHTML='<div class="empty-state"><i class="fas fa-box-open"></i><p>등록된 규칙 없음</p></div>';return}d.products.forEach((p,i)=>{const it=document.createElement('div');it.className='product-item';it.innerHTML='<div class="product-info"><div class="product-brand">'+(p.brand||'(브랜드 없음)')+'</div><div class="product-name">'+p.product_name+'</div><div class="product-option">옵션: '+p.order_option+'</div></div><div class="product-actions"><button onclick="showEditProductModal('+i+',\''+esc(p.brand)+'\',\''+esc(p.product_name)+'\',\''+esc(p.order_option)+'\')"><i class="fas fa-edit"></i></button><button onclick="deleteProduct('+i+')"><i class="fas fa-trash"></i></button></div>';list.appendChild(it)})}catch(e){console.error(e)}}
function esc(s){return s?s.replace(/'/g,"\\'").replace(/"/g,'\\"'):''}
function showAddProductModal(){document.getElementById('new-product-brand').value='';document.getElementById('new-product-name').value='';document.getElementById('new-product-option').value='All';showModal('add-product-modal')}
async function addProduct(){const b=document.getElementById('new-product-brand').value.trim(),pn=document.getElementById('new-product-name').value.trim(),o=document.getElementById('new-product-option').value.trim()||'All';if(!pn){showToast('상품명 필요','error');return}try{const r=await fetch('/products/'+encodeURIComponent(selectedProductWorker),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({brand:b,product_name:pn,order_option:o})}),d=await r.json();if(r.ok){showToast(d.message);closeModal('add-product-modal');loadProducts(selectedProductWorker);loadProductWorkers();loadHomeData()}else showToast(d.error,'error')}catch(e){showToast('오류','error')}}
function showEditProductModal(i,b,pn,o){document.getElementById('edit-product-index').value=i;document.getElementById('edit-product-brand').value=b;document.getElementById('edit-product-name').value=pn;document.getElementById('edit-product-option').value=o;showModal('edit-product-modal')}
async function updateProduct(){const i=document.getElementById('edit-product-index').value,b=document.getElementById('edit-product-brand').value.trim(),pn=document.getElementById('edit-product-name').value.trim(),o=document.getElementById('edit-product-option').value.trim()||'All';if(!pn){showToast('상품명 필요','error');return}try{const r=await fetch('/products/'+encodeURIComponent(selectedProductWorker)+'/'+i,{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({brand:b,product_name:pn,order_option:o})}),d=await r.json();if(r.ok){showToast(d.message);closeModal('edit-product-modal');loadProducts(selectedProductWorker)}else showToast(d.error,'error')}catch(e){showToast('오류','error')}}
async function deleteProduct(i){if(!confirm('삭제?'))return;try{const r=await fetch('/products/'+encodeURIComponent(selectedProductWorker)+'/'+i,{method:'DELETE'}),d=await r.json();if(r.ok){showToast(d.message);loadProducts(selectedProductWorker);loadProductWorkers();loadHomeData()}else showToast(d.error,'error')}catch(e){showToast('오류','error')}}

async function loadSettings(){try{const r=await fetch('/settings'),d=await r.json();if(d.status==='loaded')document.getElementById('quantity-threshold').value=d.settings.quantity_threshold||2}catch(e){console.error(e)}}
async function saveGeneralSettings(){const th=parseInt(document.getElementById('quantity-threshold').value)||2;try{const r=await fetch('/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({quantity_threshold:th})}),d=await r.json();if(r.ok){showToast(d.message);loadHomeData()}else showToast(d.error,'error')}catch(e){showToast('오류','error')}}
function downloadSettings(){window.location.href='/settings/download'}
document.getElementById('settings-upload').addEventListener('change',async e=>{if(!e.target.files.length)return;const fd=new FormData();fd.append('file',e.target.files[0]);try{const r=await fetch('/settings/upload',{method:'POST',body:fd}),d=await r.json();if(r.ok){showToast(d.message);loadHomeData();loadSettings()}else showToast(d.error,'error')}catch(e){showToast('오류','error')}e.target.value=''});

loadHomeData();
</script>
</body>
</html>'''

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=True)