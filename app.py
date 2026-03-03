import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
import itertools
import re

st.set_page_config(page_title="병원 정산 3-Way 대사 시스템", layout="wide")

st.title("📊 병원 정산 3-Way 대사 시스템")
st.markdown("한솔페이, 일일마감, 차트마감을 비교하여 **결제수단별 상세 차이**를 분석합니다.")

st.info("👇 3개의 파일을 업로드한 후 **[분석 시작]** 버튼을 눌러주세요.")

col1, col2, col3 = st.columns(3)
with col1:
    file_hansol = st.file_uploader("📥 1. [한솔] 한솔페이 내역", type=['csv', 'xlsx', 'xls'])
with col2:
    file_daily = st.file_uploader("📥 2. [일마] 일일마감 장부", type=['csv', 'xlsx', 'xls'])
with col3:
    file_patient = st.file_uploader("📥 3. [차트] 차트마감 데이터", type=['csv', 'xlsx', 'xls'])

def load_data(file):
    if file.name.lower().endswith('.csv'):
        try:
            return pd.read_csv(file, encoding='utf-8')
        except UnicodeDecodeError:
            file.seek(0)
            return pd.read_csv(file, encoding='cp949')
    else:
        return pd.read_excel(file)

def clean_money(x):
    if pd.isna(x): return 0
    try: return int(float(str(x).replace(',', '').replace(' ', '')))
    except: return 0

def clean_no(x):
    """차트번호, 승인번호 등 소수점 제거"""
    if pd.isna(x) or str(x).strip() == '' or str(x).lower() == 'nan': return '-'
    try:
        val = str(x).split('.')[0] # 소수점 앞자리만 취함
        return re.sub(r'\D', '', val) # 숫자만 남김
    except: return str(x).strip()

def extract_appr_numbers(text):
    if pd.isna(text): return []
    return re.findall(r'\b\d{8}\b', str(text))

def chart_similarity(a, b):
    """차트번호 유사도(0~1)."""
    a, b = clean_no(a), clean_no(b)
    if a == '-' or b == '-':
        return 0.0
    if a == b:
        return 1.0
    max_len = max(len(a), len(b))
    if max_len == 0:
        return 0.0
    # 앞/뒤가 같고 일부 숫자만 다른 오기 가능성에 가중치
    common_prefix = len(list(itertools.takewhile(lambda x: x[0] == x[1], zip(a, b))))
    common_suffix = len(list(itertools.takewhile(lambda x: x[0] == x[1], zip(a[::-1], b[::-1]))))
    return min(1.0, (common_prefix + common_suffix) / max_len)

def normalize_name(x):
    if pd.isna(x):
        return ''
    return re.sub(r'\s+', '', str(x)).strip()

if file_hansol and file_daily and file_patient:
    
    if st.button("🚀 정산 데이터 분석 시작하기", type="primary"):
        with st.spinner('결제수단별로 데이터를 꼼꼼하게 분류 중입니다...'):
            
            df_h = load_data(file_hansol)
            df_d = load_data(file_daily)
            df_p = load_data(file_patient)
            
            # --- 1. [일마] 전처리 ---
            header_idx = df_d[df_d.apply(lambda x: x.astype(str).str.contains('내원').any(), axis=1)].index
            if len(header_idx) > 0:
                df_d.columns = df_d.iloc[header_idx[0]]
                df_d = df_d.iloc[header_idx[0]+1:].reset_index(drop=True)
            col_map = {str(col): str(col).replace('\n', '') for col in df_d.columns}
            df_d.rename(columns=col_map, inplace=True)
            
            if '성명' in df_d.columns:
                df_d = df_d[df_d['성명'].notna() & ~df_d['성명'].astype(str).str.contains('합계')]
            
            df_d['차트번호'] = df_d['차트번호'].apply(clean_no)

            for col in ['카드', '현금', '이체', '강남언니', '여신티켓', '기타-지역화폐', '나만의닥터']:
                if col in df_d.columns: df_d[col] = df_d[col].apply(clean_money)
                else: df_d[col] = 0
                    
            df_d['[일마] 플랫폼합계'] = df_d['강남언니'] + df_d['여신티켓'] + df_d['기타-지역화폐'] + df_d['나만의닥터']
            df_d['[일마] 총액'] = df_d['카드'] + df_d['현금'] + df_d['이체'] + df_d['[일마] 플랫폼합계']
            
            # --- 2. [차트] 전처리 ---
            df_p['차트번호'] = df_p['차트번호'].apply(clean_no)
            calc_cols = [c for c in ['비급여(과세총금액)', '비급여(비과세)', '본부금'] if c in df_p.columns]
            for c in calc_cols: df_p[c] = df_p[c].apply(clean_money)
            df_p['[차트] 총수납액'] = df_p[calc_cols].sum(axis=1) if calc_cols else 0
            
            # 결제수단별 분류 (카드/현금/이체/플랫폼)
            df_p['분류'] = '기타'
            df_p.loc[df_p['결제수단'].astype(str).str.contains('카드'), '분류'] = '카드'
            df_p.loc[df_p['결제수단'].astype(str).str.contains('현금'), '분류'] = '현금'
            df_p.loc[df_p['결제수단'].astype(str).str.contains('통장|이체'), '분류'] = '이체'
            df_p.loc[df_p['결제수단'].astype(str).str.contains('기타|강남|여신|닥터'), '분류'] = '플랫폼'

            # 승인번호 추출
            df_p['추출된_승인번호리스트'] = [[] for _ in range(len(df_p))]
            if '승인번호' in df_p.columns:
                df_p['추출된_승인번호리스트'] = df_p['승인번호'].apply(lambda x: [clean_no(i) for i in str(x).replace(' ', '').split(',') if clean_no(i) != '-'])
            elif '결제메모' in df_p.columns:
                df_p['추출된_승인번호리스트'] = df_p['결제메모'].apply(extract_appr_numbers)

            appr_to_chart = {}
            for _, row in df_p.iterrows():
                for appr in row['추출된_승인번호리스트']: appr_to_chart[appr] = row['차트번호']

            # 차트 데이터 피벗 (환자별 결제수단 금액 합계)
            p_pivot = df_p.pivot_table(index=['차트번호', '이름'], columns='분류', values='[차트] 총수납액', aggfunc='sum').fillna(0).reset_index()
            for c in ['카드', '현금', '이체', '플랫폼']:
                if c not in p_pivot.columns: p_pivot[c] = 0
            p_pivot.columns = [f'[차트] {c}' if c in ['카드', '현금', '이체', '플랫폼'] else c for c in p_pivot.columns]
            p_pivot['[차트] 총액'] = p_pivot.filter(like='[차트]').sum(axis=1)

            # --- 3. [한솔] 전처리 ---
            if 'K/S' in df_h.columns: df_h = df_h[df_h['K/S'] == 'S'].copy()
            df_h['금액'] = df_h['금액'].apply(clean_money)
            df_h['승인번호'] = df_h['승인번호'].apply(clean_no)
            df_h = df_h.drop_duplicates(subset=['승인번호'], keep='first').reset_index(drop=True)
            df_h['Hansol_ID'] = df_h.index

            # === [매칭 로직] ===
            df_d_card = df_d[df_d['카드'] > 0].reset_index()
            matches = []
            matched_h, matched_d = set(), set()
            h_to_chart = {}
            df_d_card['정규이름'] = df_d_card['성명'].apply(normalize_name)

            # 승인번호 Direct 매칭
            for idx, h_row in df_h.iterrows():
                appr_no = h_row['승인번호']
                if appr_no in appr_to_chart:
                    c_no = appr_to_chart[appr_no]
                    d_cands = df_d_card[(df_d_card['차트번호'] == c_no) & (~df_d_card['index'].isin(matched_d))]
                    if not d_cands.empty:
                        d_target = d_cands.iloc[0]
                        matched_h.add(h_row['Hansol_ID']); matched_d.add(d_target['index']); h_to_chart[h_row['Hansol_ID']] = c_no
                        matches.append({'상태': '🔗 Direct 승인매칭', '차트번호': c_no, '환자명': d_target['성명'], '[일마]금액': d_target['카드'], '[한솔]금액': h_row['금액'], '비고': '승인번호 일치'})

            # 나머지 금액 매칭 (간략화)
            rem_h = df_h[~df_h['Hansol_ID'].isin(matched_h)]
            rem_d = df_d_card[~df_d_card['index'].isin(matched_d)]
            for amt in set(rem_h['금액']).intersection(set(rem_d['카드'])):
                h_sub, d_sub = rem_h[rem_h['금액']==amt], rem_d[rem_d['카드']==amt]
                for i in range(min(len(h_sub), len(d_sub))):
                    matched_h.add(h_sub.iloc[i]['Hansol_ID']); matched_d.add(d_sub.iloc[i]['index'])
                    h_to_chart[h_sub.iloc[i]['Hansol_ID']] = d_sub.iloc[i]['차트번호']
                    matches.append({'상태': '✅ 금액매칭', '차트번호': d_sub.iloc[i]['차트번호'], '환자명': d_sub.iloc[i]['성명'], '[일마]금액': amt, '[한솔]금액': amt, '비고': '금액 일치'})

            # 이름 동일 + 차트번호 유사 -> 차트번호 오기 의심 매칭
            rem_h = df_h[~df_h['Hansol_ID'].isin(matched_h)]
            rem_d = df_d_card[~df_d_card['index'].isin(matched_d)].copy()
            for _, d_row in rem_d.iterrows():
                d_name = d_row['정규이름']
                if not d_name:
                    continue
                h_cands = rem_h[rem_h['금액'] == d_row['카드']]
                if h_cands.empty:
                    continue
                name_cols = [c for c in ['구매자명', '고객명', '이름', '성명'] if c in df_h.columns]
                for _, h_row in h_cands.iterrows():
                    if name_cols:
                        h_name = normalize_name(h_row[name_cols[0]])
                        if h_name and h_name != d_name:
                            continue
                    # 한솔 메모/가맹점명 등에서 차트번호 단서 추출
                    text_blob = ' '.join([str(h_row.get(c, '')) for c in ['구매자명', '거래내용', '가맹점명', '비고'] if c in df_h.columns])
                    nums = re.findall(r'\d{4,}', text_blob)
                    if not nums:
                        continue
                    sim = max([chart_similarity(d_row['차트번호'], n) for n in nums], default=0)
                    if sim >= 0.6:
                        matched_h.add(h_row['Hansol_ID']); matched_d.add(d_row['index'])
                        h_to_chart[h_row['Hansol_ID']] = d_row['차트번호']
                        matches.append({
                            '상태': '⚠️ 차트번호 오기 의심(추정매칭)',
                            '차트번호': d_row['차트번호'],
                            '환자명': d_row['성명'],
                            '[일마]금액': d_row['카드'],
                            '[한솔]금액': h_row['금액'],
                            '비고': f'이름 동일 + 차트번호 유사도 {sim:.2f}'
                        })
                        break

            # 일마 입력 순서와 한솔 시간 순서를 이용한 추정 매칭
            rem_h = df_h[~df_h['Hansol_ID'].isin(matched_h)].copy()
            rem_d = df_d_card[~df_d_card['index'].isin(matched_d)].copy()
            time_cols = [c for c in ['거래일시', '승인일시', '결제일시', '시간'] if c in rem_h.columns]
            if time_cols:
                rem_h['_sort_ts'] = pd.to_datetime(rem_h[time_cols[0]], errors='coerce')
                rem_h = rem_h.sort_values(['_sort_ts', 'Hansol_ID']).reset_index(drop=True)
            else:
                rem_h = rem_h.sort_values('Hansol_ID').reset_index(drop=True)
            rem_d = rem_d.sort_values('index').reset_index(drop=True)

            i, j = 0, 0
            while i < len(rem_h) and j < len(rem_d):
                h_row = rem_h.iloc[i]
                d_row = rem_d.iloc[j]
                if h_row['금액'] == d_row['카드']:
                    matched_h.add(h_row['Hansol_ID']); matched_d.add(d_row['index'])
                    h_to_chart[h_row['Hansol_ID']] = d_row['차트번호']
                    matches.append({
                        '상태': '🟡 순서기반 추정매칭',
                        '차트번호': d_row['차트번호'],
                        '환자명': d_row['성명'],
                        '[일마]금액': d_row['카드'],
                        '[한솔]금액': h_row['금액'],
                        '비고': '일마 입력순서 ↔ 한솔 시간순서 기반'
                    })
                    i += 1
                    j += 1
                elif h_row['금액'] < d_row['카드']:
                    i += 1
                else:
                    j += 1

            match_df = pd.DataFrame(matches)

            # === 탭 구성 ===
            tab1, tab2, tab3 = st.tabs(["💳 [한솔] vs [일마]", "🏥 [차트] vs [한솔] (다이렉트)", "📊 [차트] vs [일마] (수단별 분석)"])
            
            with tab1:
                st.subheader("카드 승인 대사 (의심 거래)")
                st.caption("추정매칭(차트번호 오기 의심/순서기반)은 승인번호 직접매칭보다 신뢰도가 낮습니다.")
                if not match_df.empty:
                    st.dataframe(match_df.sort_values(['상태', '차트번호']))
                else:
                    st.success("매칭 결과가 없습니다.")

            with tab2:
                st.subheader("🏥 [차트] 카드수납액 vs [한솔] 실제승인액")
                df_h['연결차트'] = df_h['Hansol_ID'].map(h_to_chart).fillna(0)
                h_sum = df_h.groupby('연결차트')['금액'].sum().reset_index()
                p_card = df_p[df_p['분류'] == '카드'].groupby('차트번호')['[차트] 총수납액'].sum().reset_index()
                
                direct_merge = pd.merge(p_card, h_sum, left_on='차트번호', right_on='연결차트', how='outer').fillna(0)
                direct_merge['차액'] = direct_merge['[차트] 총수납액'] - direct_merge['금액']
                
                st.dataframe(direct_merge[direct_merge['차액'] != 0])

            with tab3:
                st.subheader("📊 [차트] vs [일마] 결제수단별 상세 비교")
                d_grouped = df_d.groupby(['차트번호', '성명'])[['카드', '현금', '이체', '[일마] 플랫폼합계']].sum().reset_index()
                d_grouped.columns = ['차트번호', '성명', '[일마] 카드', '[일마] 현금', '[일마] 이체', '[일마] 플랫폼']
                
                final_merge = pd.merge(d_grouped, p_pivot, on='차트번호', how='outer').fillna(0)
                
                # 수단별 차이 계산
                final_merge['카드차이'] = final_merge['[일마] 카드'] - final_merge['[차트] 카드']
                final_merge['현금차이'] = final_merge['[일마] 현금'] - final_merge['[차트] 현금']
                final_merge['이체차이'] = final_merge['[일마] 이체'] - final_merge['[차트] 이체']
                final_merge['플랫폼차이'] = final_merge['[일마] 플랫폼'] - final_merge['[차트] 플랫폼']
                
                # 구체적 분석 메시지
                def get_detail_reason(row):
                    reasons = []
                    if row['카드차이'] != 0: reasons.append(f"💳 카드({row['카드차이']:,})")
                    if row['현금차이'] != 0: reasons.append(f"💵 현금({row['현금차이']:,})")
                    if row['이체차이'] != 0: reasons.append(f"🏦 이체({row['이체차이']:,})")
                    if row['플랫폼차이'] != 0: reasons.append(f"📱 플랫폼({row['플랫폼차이']:,})")
                    return " / ".join(reasons) if reasons else "✅ 일치"

                final_merge['💡 상세 불일치 수단'] = final_merge.apply(get_detail_reason, axis=1)
                
                st.dataframe(final_merge[final_merge['💡 상세 불일치 수단'] != "✅ 일치"][
                    ['차트번호', '성명', '💡 상세 불일치 수단', '[일마] 카드', '[차트] 카드', '[일마] 현금', '[차트] 현금', '[일마] 이체', '[차트] 이체']
                ])
