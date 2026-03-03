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
        calc_cols = [c for c in ['비급여(과세총금액)', '비급여(비과세)', '본부금'] if c in df_p.columns]
        for c in calc_cols:
            df_p[c] = df_p[c].apply(clean_money)
        df_p['총수납액(차트)'] = df_p[calc_cols].sum(axis=1)
        
        # 환자명 기준으로 그룹화
        df_p_grouped = df_p.groupby(['이름', '결제수단'])['총수납액(차트)'].sum().reset_index()
        
        # 결제수단 분리 추정
        p_pivot = df_p_grouped.pivot_table(index='이름', columns='결제수단', values='총수납액(차트)', aggfunc='sum').fillna(0)
        p_pivot['총액(차트)'] = p_pivot.sum(axis=1)
        if '기타(기타)' not in p_pivot.columns: p_pivot['기타(기타)'] = 0
        
        # --- 3. 한솔페이 전처리 ---
        if 'K/S' in df_h.columns: df_h = df_h[df_h['K/S'] == 'S'].copy()
        df_h['금액'] = df_h['금액'].astype(str).str.replace(',', '').astype
