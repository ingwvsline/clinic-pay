import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
import itertools

st.set_page_config(page_title="병원 수납/정산 3-Way 대사 시스템", layout="wide")

st.title("📊 병원 수납/정산 3-Way 대사 시스템")
st.markdown("한솔페이(단말기), 일일마감(장부), 환자별집계(차트)를 모두 비교하여 누락을 찾아냅니다.")

st.info("👇 3개의 파일을 모두 업로드한 후, 나타나는 **[분석 시작]** 버튼을 눌러주세요.")

# 화면 상단에 3개 파일 업로드 칸 만들기
col1, col2, col3 = st.columns(3)
with col1:
    file_hansol = st.file_uploader("📥 1. 한솔페이 내역", type=['csv', 'xlsx', 'xls'])
with col2:
    file_daily = st.file_uploader("📥 2. 일일마감 장부", type=['csv', 'xlsx', 'xls'])
with col3:
    file_patient = st.file_uploader("📥 3. 환자별집계 (차트)", type=['csv', 'xlsx', 'xls'])

# 한글 CSV 파일도 깨지지 않게 읽어오는 강력한 함수
def load_data(file):
    if file.name.lower().endswith('.csv'):
        try:
            return pd.read_csv(file, encoding='utf-8')
        except UnicodeDecodeError:
            file.seek(0)
            return pd.read_csv(file, encoding='cp949') # 한국어 엑셀 호환
    else:
        return pd.read_excel(file)

def clean_money(x):
    if pd.isna(x): return 0
    try: return int(float(str(x).replace(',', '').replace(' ', '')))
    except: return 0

# 3개 파일이 모두 올라오면 버튼이 나타남
if file_hansol and file_daily and file_patient:
    
    if st.button("🚀 정산 데이터 분석 시작하기", type="primary"):
        with st.spinner('데이터를 맞춰보는 중입니다. 잠시만 기다려주세요...'):
            
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
            
            if '성명' in df_d.columns:
                df_d = df_d[df_d['성명'].notna() & ~df_d['성명'].astype(str).str.contains('합계')]
            
            for col in ['카드', '현금', '이체', '강남언니', '여신티켓', '기타-지역화폐', '나만의닥터']:
                if col in df_d.columns:
                    df_d[col] = df_d[col].apply(clean_money)
                else:
                    df_d[col] = 0
                    
            df_d['플랫폼합계(장부)'] = df_d['강남언니'] + df_d['여신티켓'] + df_d['기타-지역화폐'] + df_d['나만의닥터']
            df_d['총액(장부)'] = df_d['카드'] + df_d['현금'] + df_d['이체'] + df_d['플랫폼합계(장부)']
            
            # --- 2. 환자별집계(차트) 전처리 ---
            calc_cols = [c for c in ['비급여(과세총금액)', '비급여(비과세)', '본부금'] if c in df_p.columns]
            for c in calc_cols:
                df_p[c] = df_p[c].apply(clean_money)
            df_p['총수납액(차트)'] = df_p[calc_cols].sum(axis=1) if calc_cols else 0
            
            if '이름' in df_p.columns and '결제수단' in df_p.columns:
                df_p_grouped = df_p.groupby(['이름', '결제수단'])['총수납액(차트)'].sum().reset_index()
                p_pivot = df_p_grouped.pivot_table(index='이름', columns='결제수단', values='총수납액(차트)', aggfunc='sum').fillna(0)
                p_pivot['총액(차트)'] = p_pivot.sum(axis=1)
                if '기타(기타)' not in p_pivot.columns: p_pivot['기타(기타)'] = 0
            else:
                p_pivot = pd.DataFrame(columns=['총액(차트)', '기타(기타)'])
            
            # --- 3. 한솔페이 전처리 ---
            if 'K/S' in df_h.columns: df_h = df_h[df_h['K/S'] == 'S'].copy()
            if '금액' in df_h.columns:
                df_h['금액'] = df_h['금액'].astype(str).str.replace(',', '').astype(float).fillna(0).astype(int)
            if '승인번호' in df_h.columns:
                df_h = df_h.drop_duplicates(subset=['승인번호'], keep='first').reset_index(drop=True)
            if '시간' in df_h.columns:
                df_h['시간'] = df_h['시간'].astype(str).str.zfill(6)
            
            # === 화면 출력 ===
            tab1, tab2 = st.tabs(["💳 한솔페이 vs 일일마감 (카드 대사)", "📊 차트 vs 일일마감 (플랫폼/총액 대사)"])
            
            with tab1:
                st.subheader("카드 결제 누락 및 불일치 확인")
                if '카드' in df_d.columns and '금액' in df_h.columns:
                    df_d_card = df_d[df_d['카드'] > 0].reset_index()
                    matches = []
                    matched_h, matched_d = set(), set()
                    df_h['Hansol_ID'] = df_h.index

                    h_counts, d_counts = df_h['금액'].value_counts(), df_d_card['카드'].value_counts()
                    common_unique = set(h_counts[h_counts==1].index).intersection(d_counts[d_counts==1].index)
                    for amt in common_unique:
                        h_row, d_row = df_h[df_h['금액']==amt].iloc[0], df_d_card[df_d_card['카드']==amt].iloc[0]
                        matched_h.add(h_row['Hansol_ID']); matched_d.add(d_row['index'])
                        matches.append({'상태': '✅ 매칭완료', '환자명': d_row.get('성명', ''), '장부금액': d_row['카드'], '승인금액': h_row['금액'], '승인번호': str(h_row.get('승인번호', ''))})
                    
                    rem_h, rem_d = df_h[~df_h['Hansol_ID'].isin(matched_h)], df_d_card[~df_d_card['index'].isin(matched_d)]
                    for amt in set(rem_h['금액']).intersection(set(rem_d['카드'])):
                        h_sub, d_sub = rem_h[rem_h['금액']==amt], rem_d[rem_d['카드']==amt]
                        for i in range(min(len(h_sub), len(d_sub))):
                            matched_h.add(h_sub.iloc[i]['Hansol_ID']); matched_d.add(d_sub.iloc[i]['index'])
                            matches.append({'상태': '✅ 매칭완료(순서)', '환자명': d_sub.iloc[i].get('성명', ''), '장부금액': d_sub.iloc[i]['카드'], '승인금액': h_sub.iloc[i]['금액'], '승인번호': str(h_sub.iloc[i].get('승인번호', ''))})
                    
                    for _, row in df_d_card[~df_d_card['index'].isin(matched_d)].iterrows():
                        matches.append({'상태': '🚨 장부만 있음(승인누락)', '환자명': row.get('성명', ''), '장부금액': row['카드'], '승인금액': 0, '승인번호': '-'})
                    for _, row in df_h[~df_h['Hansol_ID'].isin(matched_h)].iterrows():
                        matches.append({'상태': '⚠️ 승인만 있음(장부누락)', '환자명': '누군지모름', '장부금액': 0, '승인금액': row['금액'], '승인번호': str(row.get('승인번호', ''))})
                    
                    df_card_res = pd.DataFrame(matches).sort_values('상태')
                    
                    col_a, col_b, col_c = st.columns(3)
                    col_a.metric("한솔페이 총액", f"{df_h['금액'].sum():,}원")
                    col_b.metric("장부 카드 총액", f"{df_d['카드'].sum():,}원")
                    col_c.metric("차액", f"{df_d['카드'].sum() - df_h['금액'].sum():,}원")
                    
                    st.dataframe(df_card_res[df_card_res['상태'] != '✅ 매칭완료'], use_container_width=True)
                else:
                    st.error("데이터 양식이 맞지 않아 카드 대사를 진행할 수 없습니다.")

            with tab2:
                st.subheader("일일마감(장부) vs 환자별집계(차트) 총액 비교")
                if '성명' in df_d.columns:
                    df_d_grouped = df_d.groupby('성명')[['총액(장부)', '플랫폼합계(장부)']].sum().reset_index()
                    merged_df = pd.merge(df_d_grouped, p_pivot.reset_index(), left_on='성명', right_on='이름', how='outer').fillna(0)
                    
                    merged_df['차트이름'] = merged_df['이름'].where(merged_df['이름'] != 0, merged_df['성명'])
                    merged_df['총액차이'] = merged_df['총액(장부)'] - merged_df['총액(차트)']
                    merged_df['플랫폼차이'] = merged_df['플랫폼합계(장부)'] - merged_df['기타(기타)']
                    
                    diff_df = merged_df[(merged_df['총액차이'] != 0) | (merged_df['플랫폼차이'] != 0)][['차트이름', '총액(장부)', '총액(차트)', '총액차이', '플랫폼합계(장부)', '기타(기타)', '플랫폼차이']]
                    
                    if diff_df.empty:
                        st.success("완벽합니다! 차트와 일일마감 장부 간의 불일치 건이 없습니다.")
                    else:
                        st.warning(f"장부와 차트의 금액이 다른 환자가 {len(diff_df)}명 있습니다. 아래 표를 확인하세요.")
                        st.dataframe(diff_df.style.format({
                            '총액(장부)': '{:,.0f}', '총액(차트)': '{:,.0f}', '총액차이': '{:,.0f}',
                            '플랫폼합계(장부)': '{:,.0f}', '기타(기타)': '{:,.0f}', '플랫폼차이': '{:,.0f}'
                        }), use_container_width=True)
                else:
                    st.error("일일마감 장부에서 환자 '성명'을 찾을 수 없습니다.")
