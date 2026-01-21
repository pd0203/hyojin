"""
효진유통 시스템 - Supabase 마이그레이션 스크립트

사용법:
  export SUPABASE_URL="https://xxx.supabase.co"
  export SUPABASE_KEY="eyJhbGc..."
  python migrate_to_supabase.py

옵션:
  --check     DB 상태 확인
  --clear     모든 테이블 초기화
  --settings  설정만 마이그레이션
  --margin    마진표만 마이그레이션
  --users     사용자 테이블 초기화
  --sample    테스트용 알바생 추가
  --all       전체 마이그레이션
"""
import os
import sys
import json
from datetime import date
from dotenv import load_dotenv

load_dotenv()

SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')
ADMIN_ID = os.environ.get('ADMIN_ID', 'admin')
ADMIN_PW = os.environ.get('ADMIN_PW', 'admin123')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ 환경변수 설정 필요:")
    print("   export SUPABASE_URL='https://xxx.supabase.co'")
    print("   export SUPABASE_KEY='eyJhbGc...'")
    sys.exit(1)

try:
    from supabase import create_client, Client
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Supabase 연결 성공")
except ImportError:
    print("❌ pip install supabase 필요")
    sys.exit(1)
except Exception as e:
    print(f"❌ 연결 실패: {e}")
    sys.exit(1)


def safe_float(value, default=0):
    """문자열이나 None을 안전하게 float로 변환"""
    try:
        if value in ('', 'x', 'X', None):
            return default
        return float(value)
    except (ValueError, TypeError):
        return default


def migrate_settings():
    print("\n📦 설정 마이그레이션...")
    if not os.path.exists('playauto_settings_v4.json'):
        print("❌ playauto_settings_v4.json 없음")
        return False
    
    with open('playauto_settings_v4.json', 'r', encoding='utf-8') as f:
        settings = json.load(f)
    
    work_order = settings.get('work_order', [])
    work_config = settings.get('work_config', {})
    icons = {'송과장님': '🍧', '영재씨': '🍯', '효상': '🍜', '강민씨': '🍜', '부모님': '☕', '합배송': '📦', '복수주문': '📋', '분류실패': '❓'}
    
    for i, name in enumerate(work_order):
        cfg = work_config.get(name, {})
        data = {'name': name, 'type': cfg.get('type', 'product_specific'), 'description': cfg.get('description', ''), 'icon': icons.get(name, '📋'), 'enabled': cfg.get('enabled', True), 'sort_order': i}
        try:
            ex = supabase.table('workers').select('id').eq('name', name).execute()
            if ex.data:
                wid = ex.data[0]['id']
                supabase.table('workers').update(data).eq('id', wid).execute()
            else:
                res = supabase.table('workers').insert(data).execute()
                wid = res.data[0]['id']
            
            products = cfg.get('products', [])
            if products:
                supabase.table('worker_products').delete().eq('worker_id', wid).execute()
                for p in sorted(products, key=lambda x: x.get('product_name', '')):
                    supabase.table('worker_products').insert({'worker_id': wid, 'brand': p.get('brand', ''), 'product_name': p.get('product_name', ''), 'order_option': p.get('order_option', 'All')}).execute()
            print(f"  ✓ {name} ({len(products)}개)")
        except Exception as e:
            print(f"  ❌ {name}: {e}")
    print("✅ 설정 완료!")
    return True


def migrate_margin_data():
    print("\n📦 마진표 마이그레이션...")
    if not os.path.exists('margin_data.json'):
        print("❌ margin_data.json 없음")
        return False
    
    with open('margin_data.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    sorted_data = sorted(data, key=lambda x: x.get('상품명', ''))
    total = 0
    
    for i in range(0, len(sorted_data), 50):
        batch = sorted_data[i:i+50]
        items = [{'상품명': it.get('상품명', ''), '인상전_상품가': safe_float(it.get('인상전 상품가')), '인상후_상품가': safe_float(it.get('인상후 상품가')), '물량지원': safe_float(it.get('물량지원'), 1), '프로모션할인률': safe_float(it.get('프로모션할인률')), '장려금률': safe_float(it.get('장려금률')), '배송비': safe_float(it.get('배송비')), '박스비': safe_float(it.get('박스비')), '인상전_총_원가': safe_float(it.get('인상전 총 원가')), '인상후_총_원가': safe_float(it.get('인상후 총 원가')), '인상전_재고': str(it.get('인상전 재고', '')), '박스_최대_수량': str(it.get('1박스 최대 수량', '')), '기타사항': str(it.get('기타사항', ''))} for it in batch]
        try:
            supabase.table('margin_products').upsert(items, on_conflict='상품명').execute()
            total += len(batch)
            print(f"  ✓ {total}/{len(sorted_data)}")
        except Exception as e:
            print(f"  ❌ {e}")
    print("✅ 마진표 완료!")
    return True


def init_users():
    print("\n👤 사용자 초기화...")
    try:
        ex = supabase.table('users').select('id').eq('username', ADMIN_ID).execute()
        admin = {'username': ADMIN_ID, 'password': ADMIN_PW, 'name': '관리자', 'role': 'admin', 'hourly_wage': 0, 'full_attendance_bonus': 0, 'enabled': True}
        if ex.data:
            supabase.table('users').update(admin).eq('id', ex.data[0]['id']).execute()
            print(f"  ✓ 관리자 업데이트 ({ADMIN_ID})")
        else:
            supabase.table('users').insert(admin).execute()
            print(f"  ✓ 관리자 생성 ({ADMIN_ID})")
        print("✅ 사용자 완료!")
        return True
    except Exception as e:
        print(f"❌ {e}")
        return False


def add_sample_employee():
    print("\n🧪 샘플 알바생 추가...")
    try:
        ex = supabase.table('users').select('id').eq('username', 'alba1').execute()
        if ex.data:
            print("  ⚠️ 이미 존재")
            return
        res = supabase.table('users').insert({'username': 'alba1', 'password': '1234', 'name': '테스트알바', 'role': 'parttime', 'hourly_wage': 10700, 'full_attendance_bonus': 100000, 'enabled': True}).execute()
        supabase.table('wage_history').insert({'employee_id': res.data[0]['id'], 'hourly_wage': 10700, 'effective_date': date.today().isoformat()}).execute()
        print("  ✓ alba1 / 1234 추가됨")
        print("✅ 샘플 완료!")
    except Exception as e:
        print(f"❌ {e}")


def check_migration():
    print("\n📊 DB 상태...")
    try:
        print(f"  • 담당자: {len(supabase.table('workers').select('id').execute().data)}명")
        print(f"  • 상품규칙: {len(supabase.table('worker_products').select('id').execute().data)}개")
        print(f"  • 마진표: {len(supabase.table('margin_products').select('id').execute().data)}개")
        users = supabase.table('users').select('*').execute().data
        print(f"  • 사용자: {len(users)}명")
        for u in users:
            r = "👑" if u['role'] == 'admin' else "👤"
            s = "✅" if u['enabled'] else "❌"
            w = f"시급{u['hourly_wage']:,}원" if u['role'] == 'parttime' else ""
            print(f"    {r} {u['name']}({u['username']}) {s} {w}")
        print(f"  • 출퇴근: {len(supabase.table('attendance_logs').select('id').execute().data)}건")
        print(f"  • 공휴일: {len(supabase.table('holidays').select('id').execute().data)}개")
    except Exception as e:
        print(f"❌ {e}")


def clear_all_tables():
    print("\n⚠️ 테이블 초기화...")
    for t in ['salary_confirmations', 'edit_approvals', 'wage_history', 'attendance_logs', 'worker_products', 'workers', 'margin_products', 'system_settings', 'holidays', 'users']:
        try:
            supabase.table(t).delete().neq('id', 0).execute() if t != 'system_settings' else supabase.table(t).delete().neq('key', '').execute()
            print(f"  ✓ {t}")
        except:
            pass
    print("✅ 초기화 완료!")


if __name__ == '__main__':
    print("=" * 50)
    print("효진유통 - Supabase 마이그레이션")
    print("=" * 50)
    
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == '--clear':
            if input("모든 데이터 삭제? (yes/no): ") == 'yes':
                clear_all_tables()
        elif arg == '--check': check_migration()
        elif arg == '--settings': migrate_settings()
        elif arg == '--margin': migrate_margin_data()
        elif arg == '--users': init_users()
        elif arg == '--sample': add_sample_employee()
        elif arg == '--all':
            migrate_settings()
            migrate_margin_data()
            init_users()
            check_migration()
        else:
            print(f"옵션: --check | --clear | --settings | --margin | --users | --sample | --all")
    else:
        migrate_settings()
        migrate_margin_data()
        init_users()
        check_migration()
        print("\n✅ 완료! 테스트 알바생: python migrate_to_supabase.py --sample")