"""
Excel 판매자 스타배송 필터 - 웹앱
"""

from flask import Flask, render_template, request, send_file, jsonify
from werkzeug.utils import secure_filename
import pandas as pd
from io import BytesIO
from datetime import datetime
import os

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB

ALLOWED_EXTENSIONS = {'xls', 'xlsx'}

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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
