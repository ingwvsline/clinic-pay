import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
import itertools

st.set_page_config(page_title="병원 수납/정산 3-Way 대사 시스템", layout="wide")

st.title("📊 병원 수납/정산 3-Way 대사 시스템")
st.markdown("한솔페이(단말기), 일일마감(장부), 환자별집계(차트)를 모두 비교하여 누락을 찾아냅니다.")

# 화면 상단에 3개 파일 업로드 칸 만들기
col1, col2, col3 = st.columns(3)
with col1:
    file_hansol = st.file_uploader("📥 1. 한솔페이 내역", type=['csv', 'xlsx'])
with col2:
    file_daily = st.file_uploader("📥 2. 일일마감 장부", type=['csv', 'xlsx'])
with col3:
    file_patient = st.file_uploader("📥 3. 환자별집계 (차트)", type=['csv', 'xlsx'])

def load_data(file):
    if file.name.endswith('.csv'):
        return pd.read_csv(file)
    else:
        return pd.read_excel(file)

def clean_money(x):
    if pd.isna(x): return 0
    try: return int(float(str(x).replace(',', '').replace(' ', '')))
    except: return 0

if file_hansol and file_daily and file_patient:
    with st.spinner('3가지 데이터를 모두 분석 중입니다...'):
        
        # --- 데이터 로드 ---
        df_h = load_data(file_hansol)
        df_d = load_data(file_daily)
        df_p = load_data(file_patient)
        
        # --- 1. 일일마감(장부) 전처리 ---
        header_idx = df_d[df_d.apply(lambda x: x.astype(str).str.contains('내원').any(), axis=1)].index
        if len(header_idx) > 0:
            df_d.columns = df_d.iloc[header_idx[0]]
            df_d = df_d.iloc[header_idx[0]+1:].reset_index(drop=True)
        col_map = {str(col): str(col).replace('\n', '') for col in df_d.columns}
        df_d.rename(columns=col_map, inplace=True)
        df_d = df_d[df_d['성명'].notna() & ~df_d['성명'].astype(str).str.contains('합계')]
        
        # 주요 결제수단 금액화
        for col in ['카드', '현금', '이체', '강남언니', '여신티켓', '기타-지역화폐', '나만의닥터']:
            if col in df_d.columns:
                df_d[col] = df_d[col].apply(clean_money)
            else:
                df_d[col] = 0
                
        # 플랫폼 합산
        df_d['플랫폼합계(장부)'] = df_d['강남언니'] + df_d['여신티켓'] + df_d['기타-지역화폐'] + df_d['나만의닥터']
        df_d['총액(장부)'] = df_d['카드'] + df_d['현금'] + df_d['이체'] + df_d['플랫폼합계(장부)']
        
        # --- 2. 환자별집계(차트) 전처리 ---
        # 실제 결제 금액은 '비급여(과세총금액)' 또는 '본부금' 등에 나뉘어 있을 수 있으나, 보통 '결제수단'별 결제액이 존재함.
        # 여기서는 샘플 데이터 구조상 결제수단과 비급여(비과세/과세)를 합산하여 추정합니다.
        # 현장 데이터에 맞게 '총수납액' 컬럼을 사용하도록 세팅 (없으면 임시로 본부금+비과세 합산)
        calc_cols = [c for c in ['비급여(과세총금액)', '비급여(비과세)', '본부금'] if c in df_p.columns]
        for c in calc_cols:
            df_p[c] = df_p[c].apply(clean_money)
        df_p['총수납액(차트)'] = df_p[calc_cols].sum(axis=1)
        
        # 환자명 기준으로 그룹화 (동명이인/여러번 결제 합산)
        df_p_grouped = df_p.groupby(['이름', '결제수단'])['총수납액(차트)'].sum().reset_index()
        
        # 플랫폼(기타)과 기타 결제수단 분리 추정
        p_pivot = df_p_grouped.pivot_table(index='이름', columns='결제수단', values='총수납액(차트)', aggfunc='sum').fillna(0)
        p_pivot['총액(차트)'] = p_pivot.sum(axis=1)
        if '기타(기타)' not in p_pivot.columns: p_pivot['기타(기타)'] = 0
        
        # --- 3. 한솔페이 전처리 ---
        if 'K/S' in df_h.columns: df_h = df_h[df_h['K/S'] == 'S'].copy()
        df_h['금액'] = df_h['금액'].astype(str).str.replace(',', '').astype(float).fillna(0).astype(int)
        df_h = df_h.drop_duplicates(subset=['승인번호'], keep='first').reset_index(drop=True)
        df_h['시간'] = df_h['시간'].astype(str).str.zfill(6)
        
        # === 탭(Tab)으로 화면 나누기 ===
        tab1, tab2 = st.tabs(["💳 한솔페이 vs 일일마감 (카드 대사)", "📊 차트 vs 일일마감 (플랫폼/총액 대사)"])
        
        with tab1:
            st.subheader("카드 결제 누락 및 불일치 확인")
            # 기존 한솔페이 매칭 로직 (생략 없이 동일하게 작동)
            df_d_card = df_d[df_d['카드'] > 0].reset_index()
            matches = []
            matched_h, matched_d = set(), set()
            df_h['Hansol_ID'] = df_h.index

            # 1:1 매칭
            h_counts, d_counts = df_h['금액'].value_counts(), df_d_card['카드'].value_counts()
            common_unique = set(h_counts[h_counts==1].index).intersection(d_counts[d_counts==1].index)
            for amt in common_unique:
                h_row, d_row = df_h[df_h['금액']==amt].iloc[0], df_d_card[df_d_card['카드']==amt].iloc[0]
                matched_h.add(h_row['Hansol_ID']); matched_d.add(d_row['index'])
                matches.append({'상태': '✅ 매칭완료', '환자명': d_row['성명'], '장부금액': d_row['카드'], '승인금액': h_row['금액'], '승인번호': str(h_row['승인번호'])})
            
            # 순서 매칭
            rem_h, rem_d = df_h[~df_h['Hansol_ID'].isin(matched_h)], df_d_card[~df_d_card['index'].isin(matched_d)]
            for amt in set(rem_h['금액']).intersection(set(rem_d['카드'])):
                h_sub, d_sub = rem_h[rem_h['금액']==amt], rem_d[rem_d['카드']==amt]
                for i in range(min(len(h_sub), len(d_sub))):
                    matched_h.add(h_sub.iloc[i]['Hansol_ID']); matched_d.add(d_sub.iloc[i]['index'])
                    matches.append({'상태': '✅ 매칭완료(순서)', '환자명': d_sub.iloc[i]['성명'], '장부금액': d_sub.iloc[i]['카드'], '승인금액': h_sub.iloc[i]['금액'], '승인번호': str(h_sub.iloc[i]['승인번호'])})
            
            # 미매칭 처리
            for _, row in df_d_card[~df_d_card['index'].isin(matched_d)].iterrows():
                matches.append({'상태': '🚨 장부만 있음(승인누락/분할)', '환자명': row['성명'], '장부금액': row['카드'], '승인금액': 0, '승인번호': '-'})
            for _, row in df_h[~df_h['Hansol_
