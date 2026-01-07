"""
JSON 데이터를 Supabase DB로 마이그레이션하는 스크립트

사용법:
  export SUPABASE_URL="a"
  export SUPABASE_KEY="b"
  python migrate_to_supabase.py

옵션:
  --clear    모든 테이블 초기화 후 마이그레이션
  --check    현재 DB 상태 확인
  --settings 설정만 마이그레이션
  --margin   마진표만 마이그레이션
"""
import os
import sys
import json

# Supabase 연결
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_KEY = os.environ.get('SUPABASE_KEY', '')

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ 환경변수를 설정해주세요:")
    print("   export SUPABASE_URL='https://xxx.supabase.co'")
    print("   export SUPABASE_KEY='eyJhbGc...'")
    sys.exit(1)

try:
    from supabase import create_client, Client
    supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
    print("✅ Supabase 연결 성공")
except ImportError:
    print("❌ supabase 패키지가 필요합니다: pip install supabase")
    sys.exit(1)
except Exception as e:
    print(f"❌ Supabase 연결 실패: {e}")
    sys.exit(1)


def migrate_settings():
    """playauto_settings_v4.json → workers, worker_products 테이블"""
    print("\n📦 설정 데이터 마이그레이션 시작...")
    
    if not os.path.exists('playauto_settings_v4.json'):
        print("❌ playauto_settings_v4.json 파일이 없습니다")
        return False
    
    with open('playauto_settings_v4.json', 'r', encoding='utf-8') as f:
        settings = json.load(f)
    
    work_order = settings.get('work_order', [])
    work_config = settings.get('work_config', {})
    
    icons = {
        '송과장님': '🍧', '영재씨': '🍯', '효상': '🍜', '강민씨': '🍜',
        '부모님': '☕', '합배송': '📦', '복수주문': '📋', '분류실패': '❓'
    }
    
    print(f"  → {len(work_order)}명의 담당자 처리 중...")
    
    for sort_order, worker_name in enumerate(work_order):
        config = work_config.get(worker_name, {})
        
        worker_data = {
            'name': worker_name,
            'type': config.get('type', 'product_specific'),
            'description': config.get('description', ''),
            'icon': icons.get(worker_name, config.get('icon', '📋')),
            'enabled': config.get('enabled', True),
            'sort_order': sort_order,
            'auto_rule': config.get('auto_rule')
        }
        
        # 기존 데이터 확인 후 upsert
        try:
            existing = supabase.table('workers').select('id').eq('name', worker_name).execute()
            
            if existing.data:
                worker_id = existing.data[0]['id']
                supabase.table('workers').update(worker_data).eq('id', worker_id).execute()
                print(f"    ✓ {worker_name} 업데이트됨 (ID: {worker_id})")
            else:
                result = supabase.table('workers').insert(worker_data).execute()
                worker_id = result.data[0]['id']
                print(f"    ✓ {worker_name} 추가됨 (ID: {worker_id})")
            
            # 상품 규칙 삽입
            products = config.get('products', [])
            if products:
                # 기존 상품 규칙 삭제
                supabase.table('worker_products').delete().eq('worker_id', worker_id).execute()
                
                # 상품명으로 정렬 후 삽입
                sorted_products = sorted(products, key=lambda x: x.get('product_name', ''))
                
                for product in sorted_products:
                    product_data = {
                        'worker_id': worker_id,
                        'brand': product.get('brand', ''),
                        'product_name': product.get('product_name', ''),
                        'order_option': product.get('order_option', 'All')
                    }
                    supabase.table('worker_products').insert(product_data).execute()
                
                print(f"      → {len(products)}개 상품 규칙 추가됨")
        except Exception as e:
            print(f"    ❌ {worker_name} 처리 오류: {e}")
    
    # 시스템 설정 저장
    system_settings = [
        ('quantity_threshold', settings.get('quantity_threshold', 2)),
        ('auto_learn', settings.get('auto_learn', True)),
        ('min_confidence', settings.get('min_confidence', 1.0)),
        ('group_by_order', settings.get('group_by_order', True))
    ]
    
    for key, value in system_settings:
        try:
            supabase.table('system_settings').upsert({
                'key': key,
                'value': value
            }).execute()
        except Exception as e:
            print(f"  ⚠️ 설정 {key} 저장 실패: {e}")
    
    print("  ✅ 시스템 설정 저장 완료")
    print("✅ 설정 마이그레이션 완료!")
    return True


def migrate_margin_data():
    """margin_data.json → margin_products 테이블"""
    print("\n📦 원가 마진표 마이그레이션 시작...")
    
    if not os.path.exists('margin_data.json'):
        print("❌ margin_data.json 파일이 없습니다")
        return False
    
    with open('margin_data.json', 'r', encoding='utf-8') as f:
        margin_data = json.load(f)
    
    print(f"  → {len(margin_data)}개 상품 처리 중...")
    
    # 상품명으로 정렬
    sorted_data = sorted(margin_data, key=lambda x: x.get('상품명', ''))
    
    # 배치 삽입 (50개씩)
    batch_size = 50
    total_inserted = 0
    
    for i in range(0, len(sorted_data), batch_size):
        batch = sorted_data[i:i+batch_size]
        
        insert_data = []
        for item in batch:
            insert_data.append({
                '상품명': item.get('상품명', ''),
                '인상전_상품가': float(item.get('인상전 상품가', 0) or 0),
                '인상후_상품가': float(item.get('인상후 상품가', 0) or 0),
                '물량지원': float(item.get('물량지원', 1) or 1),
                '프로모션할인률': float(item.get('프로모션할인률', 0) or 0),
                '장려금률': float(item.get('장려금률', 0) or 0),
                '배송비': float(item.get('배송비', 0) or 0),
                '박스비': float(item.get('박스비', 0) or 0),
                '인상전_총_원가': float(item.get('인상전 총 원가', 0) or 0),
                '인상후_총_원가': float(item.get('인상후 총 원가', 0) or 0),
                '인상전_재고': str(item.get('인상전 재고', '')),
                '박스_최대_수량': str(item.get('1박스 최대 수량', '')),
                '기타사항': str(item.get('기타사항', ''))
            })
        
        try:
            supabase.table('margin_products').upsert(insert_data, on_conflict='상품명').execute()
            total_inserted += len(batch)
            print(f"    ✓ {total_inserted}/{len(sorted_data)} 완료")
        except Exception as e:
            print(f"    ❌ 배치 삽입 오류: {e}")
    
    print("✅ 원가 마진표 마이그레이션 완료!")
    return True


def clear_all_tables():
    """모든 테이블 초기화"""
    print("\n⚠️  모든 테이블 초기화 중...")
    
    tables = ['worker_products', 'workers', 'margin_products', 'system_settings']
    
    for table in tables:
        try:
            # neq 조건으로 모든 행 삭제
            if table == 'system_settings':
                supabase.table(table).delete().neq('key', '').execute()
            else:
                supabase.table(table).delete().neq('id', 0).execute()
            print(f"  ✓ {table} 초기화")
        except Exception as e:
            print(f"  ❌ {table} 오류: {e}")
    
    print("✅ 초기화 완료!")


def check_migration():
    """마이그레이션 결과 확인"""
    print("\n📊 DB 상태 확인...")
    
    try:
        workers = supabase.table('workers').select('*').execute()
        print(f"  • 담당자: {len(workers.data)}명")
        
        products = supabase.table('worker_products').select('*').execute()
        print(f"  • 상품 규칙: {len(products.data)}개")
        
        margin = supabase.table('margin_products').select('*').execute()
        print(f"  • 원가 마진표: {len(margin.data)}개 상품")
        
        settings = supabase.table('system_settings').select('*').execute()
        print(f"  • 시스템 설정: {len(settings.data)}개")
        
        if workers.data:
            print("\n  [담당자 목록]")
            for w in workers.data:
                print(f"    {w['icon']} {w['name']} (ID: {w['id']})")
    except Exception as e:
        print(f"❌ 확인 실패: {e}")


if __name__ == '__main__':
    print("=" * 50)
    print("효진유통 시스템 - Supabase 마이그레이션")
    print("=" * 50)
    
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg == '--clear':
            if input("정말 모든 데이터를 삭제하시겠습니까? (yes/no): ") == 'yes':
                clear_all_tables()
        elif arg == '--check':
            check_migration()
        elif arg == '--settings':
            migrate_settings()
        elif arg == '--margin':
            migrate_margin_data()
        else:
            print(f"알 수 없는 옵션: {arg}")
            print("사용법: python migrate_to_supabase.py [--clear|--check|--settings|--margin]")
    else:
        # 전체 마이그레이션
        migrate_settings()
        migrate_margin_data()
        check_migration()
        
        print("\n" + "=" * 50)
        print("✅ 전체 마이그레이션 완료!")
        print("=" * 50)
