import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
import itertools

st.set_page_config(page_title="병원 수납/정산 대사 프로그램", layout="wide")

st.title("📊 일일마감 - 한솔페이 자동 매칭 시스템")
st.markdown("그날의 **한솔페이 내역**과 **일일마감 장부**를 업로드하면 자동으로 대사하여 누락 건을 찾아냅니다.")

st.info("👇 아래 두 곳에 각각 알맞은 엑셀 파일을 마우스로 끌어다 놓아주세요.")

# 메인 화면에 파일 업로드 2개 나란히 배치 (찾기 쉽게!)
col1, col2 = st.columns(2)
with col1:
    file_hansol = st.file_uploader("📥 1. 한솔페이 내역", type=['csv', 'xlsx'])
with col2:
    file_daily = st.file_uploader("📥 2. 일일마감 장부", type=['csv', 'xlsx'])

def load_data(file):
    if file.name.endswith('.csv'):
        return pd.read_csv(file)
    else:
        return pd.read_excel(file)

def process_matching(df_h, df_d):
    # --- 1. 한솔페이 전처리 ---
    if 'K/S' in df_h.columns:
        df_h = df_h[df_h['K/S'] == 'S'].copy()
    
    df_h['시간'] = df_h['시간'].astype(str).str.zfill(6)
    df_h['거래일'] = df_h['거래일'].astype(str).apply(lambda x: '20'+x if len(x)==6 else x)
    df_h['FullTime'] = pd.to_datetime(df_h['거래일'] + df_h['시간'], format='%Y%m%d%H%M%S', errors='coerce')
    
    df_h['금액'] = df_h['금액'].astype(str).str.replace(',', '').astype(float).fillna(0).astype(int)
    df_h = df_h.sort_values('FullTime').reset_index(drop=True)
    
    # 중복 승인번호 제거 (허수 데이터 방지)
    df_h = df_h.drop_duplicates(subset=['승인번호'], keep='first').reset_index(drop=True)
    df_h['Hansol_ID'] = df_h.index

    # --- 2. 일일마감 전처리 ---
    header_idx = df_d[df_d.apply(lambda x: x.astype(str).str.contains('내원').any(), axis=1)].index
    if len(header_idx) > 0:
        df_d.columns = df_d.iloc[header_idx[0]]
        df_d = df_d.iloc[header_idx[0]+1:].reset_index(drop=True)
    
    col_map = {str(col): str(col).replace('\n', '') for col in df_d.columns}
    df_d.rename(columns=col_map, inplace=True)
    
    df_d = df_d[df_d['성명'].notna()]
    df_d = df_d[~df_d['성명'].astype(str).str.contains('합계')]
    
    def clean_money(x):
        if pd.isna(x): return 0
        try: return int(float(str(x).replace(',', '').replace(' ', '')))
        except: return 0

    if '카드' in df_d.columns:
        df_d['Card_Amount'] = df_d['카드'].apply(clean_money)
    else:
        st.error("일일마감 파일에 '카드' 컬럼이 없습니다.")
        return pd.DataFrame(), 0, 0

    df_d_card = df_d[df_d['Card_Amount'] > 0].reset_index()

    # --- 3. 매칭 로직 ---
    matches = []
    matched_h = set()
    matched_d = set()

    # (1) 1:1 유일 금액 매칭
    h_counts = df_h['금액'].value_counts()
    d_counts = df_d_card['Card_Amount'].value_counts()
    common_unique = set(h_counts[h_counts==1].index).intersection(d_counts[d_counts==1].index)
    
    for amt in common_unique:
        h_row = df_h[df_h['금액']==amt].iloc[0]
        d_row = df_d_card[df_d_card['Card_Amount']==amt].iloc[0]
        matched_h.add(h_row['Hansol_ID'])
        matched_d.add(d_row['index'])
        matches.append({'상태': '✅ 매칭완료', '매칭유형': '1:1 금액일치', '환자명': d_row['성명'], '장부금액': d_row['Card_Amount'], '승인금액': h_row['금액'], '승인시간': h_row['시간'], '승인번호': str(h_row['승인번호'])})

    # (2) 1:1 순차 매칭
    rem_h = df_h[~df_h['Hansol_ID'].isin(matched_h)]
    rem_d = df_d_card[~df_d_card['index'].isin(matched_d)]
    common_amts = set(rem_h['금액']).intersection(set(rem_d['Card_Amount']))
    
    for amt in common_amts:
        h_sub = rem_h[rem_h['금액']==amt].sort_values('FullTime')
        d_sub = rem_d[rem_d['Card_Amount']==amt].sort_values('index')
        for i in range(min(len(h_sub), len(d_sub))):
            h_row = h_sub.iloc[i]
            d_row = d_sub.iloc[i]
            matched_h.add(h_row['Hansol_ID'])
            matched_d.add(d_row['index'])
            matches.append({'상태': '✅ 매칭완료', '매칭유형': '순서추정', '환자명': d_row['성명'], '장부금액': d_row['Card_Amount'], '승인금액': h_row['금액'], '승인시간': h_row['시간'], '승인번호': str(h_row['승인번호'])})

    # (3) 분할 결제 합산 매칭 (2건 합산)
    rem_h = df_h[~df_h['Hansol_ID'].isin(matched_h)]
    rem_d = df_d_card[~df_d_card['index'].isin(matched_d)]
    h_pool = rem_h.to_dict('records')
    
    for _, d_row in rem_d.iterrows():
        target = d_row['Card_Amount']
        for combo in itertools.combinations(h_pool, 2):
            if sum(c['금액'] for c in combo) == target:
                ids = [c['Hansol_ID'] for c in combo]
                if any(x in matched_h for x in ids): continue
                
                for hid in ids: matched_h.add(hid)
                matched_d.add(d_row['index'])
                
                승인시간들 = ", ".join([str(c['시간']) for c in combo])
                승인번호들 = ", ".join([str(c['승인번호']) for c in combo])
                matches.append({'상태': '✅ 매칭완료', '매칭유형': '2건 분할합산', '환자명': d_row['성명'], '장부금액': target, '승인금액': target, '승인시간': 승인시간들, '승인번호': 승인번호들})
                break

    # --- 4. 미매칭 건 정리 ---
    unmatched_d = df_d_card[~df_d_card['index'].isin(matched_d)]
    for _, row in unmatched_d.iterrows():
        matches.append({'상태': '🚨 장부만 있음(승인누락)', '매칭유형': '-', '환자명': row['성명'], '장부금액': row['Card_Amount'], '승인금액': 0, '승인시간': '-', '승인번호': '-'})

    unmatched_h = df_h[~df_h['Hansol_ID'].isin(matched_h)]
    for _, row in unmatched_h.iterrows():
        matches.append({'상태': '⚠️ 승인만 있음(장부누락)', '매칭유형': '-', '환자명': '누군지 모름', '장부금액': 0, '승인금액': row['금액'], '승인시간': row['시간'], '승인번호': str(row['승인번호'])})

    df_final = pd.DataFrame(matches)
    if not df_final.empty:
        df_final = df_final.sort_values(by=['상태', '승인시간'], ascending=[True, True])
        
    return df_final, df_h['금액'].sum(), df_d_card['Card_Amount'].sum()

# 실행 및 화면 출력 부분
if file_hansol and file_daily:
    with st.spinner('데이터를 분석 중입니다...'):
        df_h = load_data(file_hansol)
        df_d = load_data(file_daily)
        
        result_df, total_h, total_d = process_matching(df_h, df_d)
        
        if not result_df.empty:
            col1, col2, col3 = st.columns(3)
            col1.metric("한솔페이 총 카드승인액", f"{total_h:,}원")
            col2.metric("일일마감 총 카드매출액", f"{total_d:,}원")
            col3.metric("차액 (장부 - 승인)", f"{total_d - total_h:,}원")
            
            st.divider()
            
            st.subheader("🚨 집중 확인 필요 (누락 또는 불일치 건)")
            issue_df = result_df[result_df['상태'] != '✅ 매칭완료']
            if not issue_df.empty:
                st.dataframe(issue_df, use_container_width=True)
            else:
                st.success("완벽합니다! 누락된 결제나 장부 오기재가 없습니다.")
                
            st.divider()
            st.subheader("✅ 전체 대사 결과")
            st.dataframe(result_df, use_container_width=True)
