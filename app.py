import streamlit as st
import pandas as pd
import numpy as np
from io import BytesIO
import itertools

st.set_page_config(page_title="병원 정산 3-Way 대사 시스템", layout="wide")

st.title("📊 병원 정산 3-Way 대사 시스템")
st.markdown("한솔페이, 일일마감, 차트마감을 모두 비교하여 누락 및 의심 거래를 구체적으로 추정합니다.")

st.info("👇 3개의 파일을 모두 업로드한 후, 나타나는 **[분석 시작]** 버튼을 눌러주세요.")

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

if file_hansol and file_daily and file_patient:
    
    if st.button("🚀 정산 데이터 분석 시작하기", type="primary"):
        with st.spinner('데이터를 맞춰보는 중입니다. 잠시만 기다려주세요...'):
            
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
            
            for col in ['카드', '현금', '이체', '강남언니', '여신티켓', '기타-지역화폐', '나만의닥터']:
                if col in df_d.columns: df_d[col] = df_d[col].apply(clean_money)
                else: df_d[col] = 0
                    
            df_d['[일마] 플랫폼합계'] = df_d['강남언니'] + df_d['여신티켓'] + df_d['기타-지역화폐'] + df_d['나만의닥터']
            df_d['[일마] 총액'] = df_d['카드'] + df_d['현금'] + df_d['이체'] + df_d['[일마] 플랫폼합계']
            
            # --- 2. [차트] 전처리 ---
            calc_cols = [c for c in ['비급여(과세총금액)', '비급여(비과세)', '본부금'] if c in df_p.columns]
            for c in calc_cols: df_p[c] = df_p[c].apply(clean_money)
            df_p['[차트] 총수납액'] = df_p[calc_cols].sum(axis=1) if calc_cols else 0
            
            if '이름' in df_p.columns and '결제수단' in df_p.columns:
                df_p_grouped = df_p.groupby(['이름', '결제수단'])['[차트] 총수납액'].sum().reset_index()
                p_pivot = df_p_grouped.pivot_table(index='이름', columns='결제수단', values='[차트] 총수납액', aggfunc='sum').fillna(0)
                p_pivot['[차트] 총액'] = p_pivot.sum(axis=1)
                if '기타(기타)' not in p_pivot.columns: p_pivot['기타(기타)'] = 0
                p_pivot.rename(columns={'기타(기타)': '[차트] 플랫폼(기타)'}, inplace=True)
            else:
                p_pivot = pd.DataFrame(columns=['[차트] 총액', '[차트] 플랫폼(기타)'])
            
            # --- 3. [한솔] 전처리 ---
            if 'K/S' in df_h.columns: df_h = df_h[df_h['K/S'] == 'S'].copy()
            if '금액' in df_h.columns: df_h['금액'] = df_h['금액'].astype(str).str.replace(',', '').astype(float).fillna(0).astype(int)
            if '승인번호' in df_h.columns: df_h = df_h.drop_duplicates(subset=['승인번호'], keep='first').reset_index(drop=True)
            if '시간' in df_h.columns: df_h['시간'] = df_h['시간'].astype(str).str.zfill(6)
            
            # === 화면 출력 ===
            tab1, tab2 = st.tabs(["💳 [한솔] vs [일마] (카드 대사)", "📊 [차트] vs [일마] (플랫폼/총액 대사)"])
            
            with tab1:
                st.subheader("카드 결제 누락 및 분할결제 통합 확인")
                if '카드' in df_d.columns and '금액' in df_h.columns:
                    df_d_card = df_d[df_d['카드'] > 0].reset_index()
                    matches = []
                    matched_h, matched_d = set(), set()
                    df_h['Hansol_ID'] = df_h.index

                    # 1. 1:1 확정 매칭
                    h_counts, d_counts = df_h['금액'].value_counts(), df_d_card['카드'].value_counts()
                    common_unique = set(h_counts[h_counts==1].index).intersection(d_counts[d_counts==1].index)
                    for amt in common_unique:
                        h_row, d_row = df_h[df_h['금액']==amt].iloc[0], df_d_card[df_d_card['카드']==amt].iloc[0]
                        matched_h.add(h_row['Hansol_ID']); matched_d.add(d_row['index'])
                        matches.append({'상태': '✅ 매칭완료', '[일마] 환자명': d_row.get('성명', ''), '[일마] 장부금액': d_row['카드'], '[한솔] 승인금액': h_row['금액'], '[한솔] 승인번호': str(h_row.get('승인번호', '')), '💡의심추정/비고': '1:1 금액 일치'})
                    
                    # 2. 순서 매칭
                    rem_h, rem_d = df_h[~df_h['Hansol_ID'].isin(matched_h)], df_d_card[~df_d_card['index'].isin(matched_d)]
                    for amt in set(rem_h['금액']).intersection(set(rem_d['카드'])):
                        h_sub, d_sub = rem_h[rem_h['금액']==amt], rem_d[rem_d['카드']==amt]
                        for i in range(min(len(h_sub), len(d_sub))):
                            matched_h.add(h_sub.iloc[i]['Hansol_ID']); matched_d.add(d_sub.iloc[i]['index'])
                            matches.append({'상태': '✅ 매칭완료', '[일마] 환자명': d_sub.iloc[i].get('성명', ''), '[일마] 장부금액': d_sub.iloc[i]['카드'], '[한솔] 승인금액': h_sub.iloc[i]['금액'], '[한솔] 승인번호': str(h_sub.iloc[i].get('승인번호', '')), '💡의심추정/비고': '동일 금액 순차 매칭'})

                    # 3. 분할 결제 합산 (한솔 2~3건 묶음 -> 일마 1건)
                    rem_h = df_h[~df_h['Hansol_ID'].isin(matched_h)]
                    rem_d = df_d_card[~df_d_card['index'].isin(matched_d)]
                    h_pool = rem_h.to_dict('records')
                    
                    for _, d_row in rem_d.iterrows():
                        target = d_row['카드']
                        found = False
                        for r in [2, 3]: # 2~3건 분할결제 탐색
                            if found: break
                            for combo in itertools.combinations(h_pool, r):
                                if sum(c['금액'] for c in combo) == target:
                                    ids = [c['Hansol_ID'] for c in combo]
                                    if any(x in matched_h for x in ids): continue
                                    for hid in ids: matched_h.add(hid)
                                    matched_d.add(d_row['index'])
                                    승인번호묶음 = ", ".join([str(c.get('승인번호','')) for c in combo])
                                    matches.append({'상태': '🔄 분할통합완료', '[일마] 환자명': d_row.get('성명', ''), '[일마] 장부금액': target, '[한솔] 승인금액': target, '[한솔] 승인번호': 승인번호묶음, '💡의심추정/비고': f'[한솔] {r}건 분할결제가 하나로 통합됨'})
                                    found = True
                                    break

                    # 4. 미매칭 건 구체적 의심 사유 추론
                    unmatched_d = df_d_card[~df_d_card['index'].isin(matched_d)]
                    
                    # [일마]에 동일인물 여러줄 적은 것 통합 (예: 배수미 150만 2줄 -> 300만)
                    ud_grouped = unmatched_d.groupby('성명')['카드'].sum().reset_index()
                    uh_pool = df_h[~df_h['Hansol_ID'].isin(matched_h)].to_dict('records')
                    
                    for _, row in ud_grouped.iterrows():
                        name, amt = row['성명'], row['카드']
                        
                        # 장부 합산액이 한솔페이 단건과 일치하는지 재확인
                        matched_by_group = False
                        for c in uh_pool:
                            if c['금액'] == amt and c['Hansol_ID'] not in matched_h:
                                matched_h.add(c['Hansol_ID'])
                                matches.append({'상태': '🔄 장부통합완료', '[일마] 환자명': name, '[일마] 장부금액': amt, '[한솔] 승인금액': amt, '[한솔] 승인번호': str(c.get('승인번호', '')), '💡의심추정/비고': '[일마]에 여러 줄 적힌 것을 환자 1명으로 묶음'})
                                matched_by_group = True
                                break
                        
                        if not matched_by_group:
                            # [차트] 교차 검증을 통한 진단
                            chart_methods = ""
                            if '이름' in df_p.columns:
                                pt_info = df_p[df_p['이름'] == name]
                                if not pt_info.empty: chart_methods = ", ".join(pt_info['결제수단'].unique())
                            
                            reason = "실제 승인 누락 또는 현금/이체를 카드로 오기재"
                            if chart_methods and "카드" not in chart_methods:
                                reason = f"⚠️ [차트]에는 '{chart_methods}'로 수납됨! 장부 오기재 99% 의심"

                            matches.append({'상태': '🚨 [일마]만 있음', '[일마] 환자명': name, '[일마] 장부금액': amt, '[한솔] 승인금액': 0, '[한솔] 승인번호': '-', '💡의심추정/비고': reason})
                    
                    for _, row in df_h[~df_h['Hansol_ID'].isin(matched_h)].iterrows():
                        matches.append({'상태': '⚠️ [한솔]만 있음', '[일마] 환자명': '-', '[일마] 장부금액': 0, '[한솔] 승인금액': row['금액'], '[한솔] 승인번호': str(row.get('승인번호', '')), '💡의심추정/비고': '장부 작성 누락, 또는 타인 이름에 얹어서 기재되었을 수 있음'})
                    
                    df_card_res = pd.DataFrame(matches).sort_values('상태', ascending=False)
                    
                    col_a, col_b, col_c = st.columns(3)
                    col_a.metric("[한솔] 총 승인액", f"{df_h['금액'].sum():,}원")
                    col_b.metric("[일마] 총 카드매출액", f"{df_d['카드'].sum():,}원")
                    col_c.metric("차액", f"{df_d['카드'].sum() - df_h['금액'].sum():,}원")
                    
                    st.dataframe(df_card_res, use_container_width=True)

            with tab2:
                st.subheader("[차트] vs [일마] 총액 및 플랫폼 매출 비교")
                if '성명' in df_d.columns:
                    df_d_grouped = df_d.groupby('성명')[['[일마] 총액', '[일마] 플랫폼합계']].sum().reset_index()
                    merged_df = pd.merge(df_d_grouped, p_pivot.reset_index(), left_on='성명', right_on='이름', how='outer').fillna(0)
                    
                    merged_df['환자명'] = merged_df['이름'].where(merged_df['이름'] != 0, merged_df['성명'])
                    merged_df['총액차이'] = merged_df['[일마] 총액'] - merged_df['[차트] 총액']
                    merged_df['플랫폼차이'] = merged_df['[일마] 플랫폼합계'] - merged_df['[차트] 플랫폼(기타)']
                    
                    def estimate_chart_issue(row):
                        if row['[차트] 총액'] == 0 and row['[일마] 총액'] > 0: return "⚠️ [차트] 수납(마감) 누락 의심"
                        if row['[일마] 총액'] == 0 and row['[차트] 총액'] > 0: return "⚠️ [일마] 장부 기재 누락 의심"
                        if row['플랫폼차이'] != 0: return "강남언니, 여신티켓 등 플랫폼 금액 엇갈림"
                        return "할인, 부가세 등으로 인한 단순 금액 오차"

                    merged_df['💡의심추정/비고'] = merged_df.apply(estimate_chart_issue, axis=1)

                    diff_df = merged_df[(merged_df['총액차이'] != 0) | (merged_df['플랫폼차이'] != 0)][
                        ['환자명', '[일마] 총액', '[차트] 총액', '총액차이', '[일마] 플랫폼합계', '[차트] 플랫폼(기타)', '플랫폼차이', '💡의심추정/비고']
                    ]
                    
                    if diff_df.empty:
                        st.success("완벽합니다! [차트]와 [일마] 간의 불일치 건이 없습니다.")
                    else:
                        st.warning(f"금액이 엇갈리는 환자가 {len(diff_df)}명 있습니다. 아래 사유를 확인하세요.")
                        st.dataframe(diff_df.style.format({
                            '[일마] 총액': '{:,.0f}', '[차트] 총액': '{:,.0f}', '총액차이': '{:,.0f}',
                            '[일마] 플랫폼합계': '{:,.0f}', '[차트] 플랫폼(기타)': '{:,.0f}', '플랫폼차이': '{:,.0f}'
                        }), use_container_width=True)
