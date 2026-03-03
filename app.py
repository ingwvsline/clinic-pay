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

def clean_appr_no(x):
    if pd.isna(x) or str(x).strip() == '' or str(x).lower() == 'nan': return '-'
    try: return str(int(float(x))) # 소수점(.0) 제거 후 문자로 변환
    except: return str(x)

if file_hansol and file_daily and file_patient:
    
    if st.button("🚀 정산 데이터 분석 시작하기", type="primary"):
        with st.spinner('차트번호를 기준으로 3-Way 데이터를 교차 분석 중입니다...'):
            
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
            
            if '차트번호' in df_d.columns:
                df_d['차트번호'] = df_d['차트번호'].astype(str).str.replace(r'\D', '', regex=True).replace('', '0').astype(int)
            else:
                df_d['차트번호'] = 0

            for col in ['카드', '현금', '이체', '강남언니', '여신티켓', '기타-지역화폐', '나만의닥터']:
                if col in df_d.columns: df_d[col] = df_d[col].apply(clean_money)
                else: df_d[col] = 0
                    
            df_d['[일마] 플랫폼합계'] = df_d['강남언니'] + df_d['여신티켓'] + df_d['기타-지역화폐'] + df_d['나만의닥터']
            df_d['[일마] 총액'] = df_d['카드'] + df_d['현금'] + df_d['이체'] + df_d['[일마] 플랫폼합계']
            
            # --- 2. [차트] 전처리 ---
            if '차트번호' in df_p.columns:
                df_p['차트번호'] = df_p['차트번호'].astype(str).str.replace(r'\D', '', regex=True).replace('', '0').astype(int)
            else:
                df_p['차트번호'] = 0

            calc_cols = [c for c in ['비급여(과세총금액)', '비급여(비과세)', '본부금'] if c in df_p.columns]
            for c in calc_cols: df_p[c] = df_p[c].apply(clean_money)
            df_p['[차트] 총수납액'] = df_p[calc_cols].sum(axis=1) if calc_cols else 0
            
            # 카드 결제액만 따로 뽑기 (다이렉트 비교용)
            df_p['[차트] 카드결제액'] = np.where(df_p['결제수단'].astype(str).str.contains('카드'), df_p['[차트] 총수납액'], 0)
            
            if '이름' in df_p.columns and '결제수단' in df_p.columns:
                df_p_grouped = df_p.groupby(['차트번호', '이름', '결제수단'])['[차트] 총수납액'].sum().reset_index()
                p_pivot = df_p_grouped.pivot_table(index=['차트번호', '이름'], columns='결제수단', values='[차트] 총수납액', aggfunc='sum').fillna(0).reset_index()
                p_pivot['[차트] 총액'] = p_pivot.select_dtypes(include='number').drop(columns=['차트번호'], errors='ignore').sum(axis=1)
                if '기타(기타)' not in p_pivot.columns: p_pivot['기타(기타)'] = 0
                p_pivot.rename(columns={'기타(기타)': '[차트] 플랫폼(기타)'}, inplace=True)
                
                # 차트 카드 총액
                p_card_grouped = df_p.groupby(['차트번호', '이름'])['[차트] 카드결제액'].sum().reset_index()
            else:
                p_pivot = pd.DataFrame(columns=['차트번호', '이름', '[차트] 총액', '[차트] 플랫폼(기타)'])
                p_card_grouped = pd.DataFrame(columns=['차트번호', '이름', '[차트] 카드결제액'])
            
            # --- 3. [한솔] 전처리 ---
            if 'K/S' in df_h.columns: df_h = df_h[df_h['K/S'] == 'S'].copy()
            if '금액' in df_h.columns: df_h['금액'] = df_h['금액'].astype(str).str.replace(',', '').astype(float).fillna(0).astype(int)
            if '승인번호' in df_h.columns: 
                df_h['승인번호_원본'] = df_h['승인번호']
                df_h['승인번호'] = df_h['승인번호'].apply(clean_appr_no)
                df_h = df_h.drop_duplicates(subset=['승인번호'], keep='first').reset_index(drop=True)
            if '시간' in df_h.columns: df_h['시간'] = df_h['시간'].astype(str).str.zfill(6)
            
            # === [핵심 로직] 한솔-일마 매칭 수행 및 차트번호 연결 ===
            df_d_card = df_d[df_d['카드'] > 0].reset_index()
            matches = []
            matched_h, matched_d = set(), set()
            h_to_chart = {} # 한솔페이 ID -> 차트번호 연결 딕셔너리
            df_h['Hansol_ID'] = df_h.index

            # 1. 1:1 확정 매칭
            h_counts, d_counts = df_h['금액'].value_counts(), df_d_card['카드'].value_counts()
            common_unique = set(h_counts[h_counts==1].index).intersection(d_counts[d_counts==1].index)
            for amt in common_unique:
                h_row, d_row = df_h[df_h['금액']==amt].iloc[0], df_d_card[df_d_card['카드']==amt].iloc[0]
                matched_h.add(h_row['Hansol_ID']); matched_d.add(d_row['index'])
                h_to_chart[h_row['Hansol_ID']] = d_row['차트번호']
                matches.append({'상태': '✅ 매칭완료', '[일마] 차트번호': str(d_row['차트번호']), '[일마] 환자명': d_row.get('성명', ''), '[일마] 장부금액': d_row['카드'], '[한솔] 승인금액': h_row['금액'], '[한솔] 승인번호': h_row.get('승인번호', '-'), '💡의심추정/비고': '1:1 금액 일치'})
            
            # 2. 순서 매칭
            rem_h, rem_d = df_h[~df_h['Hansol_ID'].isin(matched_h)], df_d_card[~df_d_card['index'].isin(matched_d)]
            for amt in set(rem_h['금액']).intersection(set(rem_d['카드'])):
                h_sub, d_sub = rem_h[rem_h['금액']==amt], rem_d[rem_d['카드']==amt]
                for i in range(min(len(h_sub), len(d_sub))):
                    matched_h.add(h_sub.iloc[i]['Hansol_ID']); matched_d.add(d_sub.iloc[i]['index'])
                    h_to_chart[h_sub.iloc[i]['Hansol_ID']] = d_sub.iloc[i]['차트번호']
                    matches.append({'상태': '✅ 매칭완료', '[일마] 차트번호': str(d_sub.iloc[i]['차트번호']), '[일마] 환자명': d_sub.iloc[i].get('성명', ''), '[일마] 장부금액': d_sub.iloc[i]['카드'], '[한솔] 승인금액': h_sub.iloc[i]['금액'], '[한솔] 승인번호': h_sub.iloc[i].get('승인번호', '-'), '💡의심추정/비고': '동일 금액 순차 매칭'})

            # 3. 분할 결제 합산
            rem_h = df_h[~df_h['Hansol_ID'].isin(matched_h)]
            rem_d = df_d_card[~df_d_card['index'].isin(matched_d)]
            h_pool = rem_h.to_dict('records')
            
            for _, d_row in rem_d.iterrows():
                target = d_row['카드']
                found = False
                for r in [2, 3]: 
                    if found: break
                    for combo in itertools.combinations(h_pool, r):
                        if sum(c['금액'] for c in combo) == target:
                            ids = [c['Hansol_ID'] for c in combo]
                            if any(x in matched_h for x in ids): continue
                            for hid in ids: 
                                matched_h.add(hid)
                                h_to_chart[hid] = d_row['차트번호'] # 분할결제도 모두 해당 차트번호로 연결!
                            matched_d.add(d_row['index'])
                            승인번호묶음 = ", ".join([str(c.get('승인번호','-')) for c in combo])
                            matches.append({'상태': '🔄 분할통합완료', '[일마] 차트번호': str(d_row['차트번호']), '[일마] 환자명': d_row.get('성명', ''), '[일마] 장부금액': target, '[한솔] 승인금액': target, '[한솔] 승인번호': 승인번호묶음, '💡의심추정/비고': f'[한솔] {r}건 분할결제가 하나로 통합됨'})
                            found = True
                            break

            # 4. 미매칭 건 (의심 거래)
            unmatched_d = df_d_card[~df_d_card['index'].isin(matched_d)]
            ud_grouped = unmatched_d.groupby(['차트번호', '성명'])['카드'].sum().reset_index()
            uh_pool = df_h[~df_h['Hansol_ID'].isin(matched_h)].to_dict('records')
            
            for _, row in ud_grouped.iterrows():
                chart_no, name, amt = row['차트번호'], row['성명'], row['카드']
                matched_by_group = False
                for c in uh_pool:
                    if c['금액'] == amt and c['Hansol_ID'] not in matched_h:
                        matched_h.add(c['Hansol_ID'])
                        h_to_chart[c['Hansol_ID']] = chart_no
                        matches.append({'상태': '🔄 분할통합완료', '[일마] 차트번호': str(chart_no), '[일마] 환자명': name, '[일마] 장부금액': amt, '[한솔] 승인금액': amt, '[한솔] 승인번호': str(c.get('승인번호', '-')), '💡의심추정/비고': '[일마]에 여러 줄 적힌 것을 환자 1명으로 묶음'})
                        matched_by_group = True
                        break
                
                if not matched_by_group:
                    reason = "🚨 [일마] 장부 오기재 의심 (단말기 승인내역 없음)"
                    if '차트번호' in df_p.columns:
                        pt_info = df_p[df_p['차트번호'] == chart_no]
                        if not pt_info.empty: 
                            chart_methods = ", ".join(pt_info['결제수단'].unique())
                            if "카드" not in chart_methods:
                                reason = f"⚠️ [차트]에는 '{chart_methods}'로 수납됨! 장부 오기재 99% 확정"
                    matches.append({'상태': '❌ [일마]만 있음', '[일마] 차트번호': str(chart_no), '[일마] 환자명': name, '[일마] 장부금액': amt, '[한솔] 승인금액': 0, '[한솔] 승인번호': '-', '💡의심추정/비고': reason})
            
            for _, row in df_h[~df_h['Hansol_ID'].isin(matched_h)].iterrows():
                matches.append({'상태': '❌ [한솔]만 있음', '[일마] 차트번호': '-', '[일마] 환자명': '누락의심', '[일마] 장부금액': 0, '[한솔] 승인금액': row['금액'], '[한솔] 승인번호': row.get('승인번호', '-'), '💡의심추정/비고': '장부 작성 누락, 또는 타인 이름에 얹어서 기재됨'})
            
            df_card_res = pd.DataFrame(matches)
            
            # --- 결과 분리 (정상 vs 의심) ---
            df_success = df_card_res[df_card_res['상태'].isin(['✅ 매칭완료', '🔄 분할통합완료'])]
            df_suspect = df_card_res[~df_card_res['상태'].isin(['✅ 매칭완료', '🔄 분할통합완료'])]

            # === 화면 출력 ===
            tab1, tab2, tab3 = st.tabs(["💳 [한솔] vs [일마]", "🏥 [차트] vs [한솔] (다이렉트)", "📊 [차트] vs [일마]"])
            
            with tab1:
                col_a, col_b, col_c = st.columns(3)
                col_a.metric("[한솔] 총 승인액", f"{df_h['금액'].sum():,}원")
                col_b.metric("[일마] 총 카드매출액", f"{df_d['카드'].sum():,}원")
                col_c.metric("차액", f"{df_d['카드'].sum() - df_h['금액'].sum():,}원")
                
                st.subheader("🚨 집중 확인 필요 (의심 거래만 추출)")
                if df_suspect.empty:
                    st.success("완벽합니다! 카드 결제 누락이나 불일치 건이 없습니다.")
                else:
                    st.dataframe(df_suspect.style.applymap(lambda x: 'background-color: #ffcccc' if x==0 else ''), use_container_width=True)
                
                with st.expander(f"✅ 정상 매칭/통합 완료 건 요약 보기 (총 {len(df_success)}건) - 클릭하여 펼치기"):
                    st.dataframe(df_success, use_container_width=True)

            with tab2: # NEW! 차트 vs 한솔 다이렉트 비교
                st.subheader("🏥 [차트] 카드수납액 vs [한솔] 실제승인액 다이렉트 비교")
                st.markdown("장부(일마)를 거치지 않고, **차트 기록과 실제 단말기 승인액이 일치하는지** 직접 검증합니다.")
                
                # 한솔페이 데이터를 차트번호 기준으로 집계
                df_h['연결된차트번호'] = df_h['Hansol_ID'].map(h_to_chart).fillna(0).astype(int)
                h_grouped = df_h[df_h['연결된차트번호'] != 0].groupby('연결된차트번호')['금액'].sum().reset_index()
                h_grouped.rename(columns={'금액': '[한솔] 실제승인액'}, inplace=True)
                
                # 차트 카드결제액과 병합
                direct_df = pd.merge(p_card_grouped, h_grouped, left_on='차트번호', right_on='연결된차트번호', how='outer').fillna(0)
                direct_df['차트번호'] = direct_df['차트번호'].where(direct_df['차트번호'] != 0, direct_df['연결된차트번호'])
                
                # 이름 복원
                name_map = p_card_grouped.set_index('차트번호')['이름'].to_dict()
                direct_df['이름'] = direct_df['차트번호'].map(name_map).fillna('장부기재오류환자')
                
                direct_df['카드차액'] = direct_df['[차트] 카드결제액'] - direct_df['[한솔] 실제승인액']
                
                def direct_issue_reason(row):
                    if row['카드차액'] == 0: return ""
                    if row['[한솔] 실제승인액'] == 0: return "🚨 [차트]엔 카드결제로 잡혔으나, 단말기 승인 내역이 아예 없음!"
                    if row['[차트] 카드결제액'] == 0: return "🚨 실제 카드결제는 되었으나, [차트] 수납이 다른 수단으로 잡힘!"
                    return "⚠️ 부분결제, 할부오차 또는 분할기재 실수"

                direct_df['💡의심추정/비고'] = direct_df.apply(direct_issue_reason, axis=1)
                
                direct_diff_df = direct_df[direct_df['카드차액'] != 0][['차트번호', '이름', '[차트] 카드결제액', '[한솔] 실제승인액', '카드차액', '💡의심추정/비고']]
                direct_diff_df['차트번호'] = direct_diff_df['차트번호'].astype(str).replace('0', '-')
                
                if direct_diff_df.empty:
                    st.success("완벽합니다! 차트에 적힌 카드 결제액과 단말기 실제 승인액이 100% 일치합니다.")
                else:
                    st.error(f"차트 기록과 실제 단말기 승인액이 다른 환자가 {len(direct_diff_df)}명 있습니다!")
                    st.dataframe(direct_diff_df.style.format({
                        '[차트] 카드결제액': '{:,.0f}', '[한솔] 실제승인액': '{:,.0f}', '카드차액': '{:,.0f}'
                    }), use_container_width=True)

            with tab3:
                st.subheader("📊 [차트] vs [일마] 총액 및 플랫폼 매출 비교 (오타 검출)")
                if '성명' in df_d.columns:
                    df_d_grouped = df_d.groupby(['차트번호', '성명'])[['[일마] 총액', '[일마] 플랫폼합계']].sum().reset_index()
                    valid_d = df_d_grouped[df_d_grouped['차트번호'] != 0]
                    valid_p = p_pivot[p_pivot['차트번호'] != 0]
                    merged_valid = pd.merge(valid_d, valid_p, on='차트번호', how='outer')
                    
                    invalid_d = df_d_grouped[df_d_grouped['차트번호'] == 0]
                    invalid_p = p_pivot[p_pivot['차트번호'] == 0]
                    merged_invalid = pd.merge(invalid_d, invalid_p, left_on='성명', right_on='이름', how='outer')
                    
                    merged_df = pd.concat([merged_valid, merged_invalid], ignore_index=True)
                    for c in ['[일마] 총액', '[일마] 플랫폼합계', '[차트] 총액', '[차트] 플랫폼(기타)']:
                        if c in merged_df.columns: merged_df[c] = merged_df[c].fillna(0)
                            
                    merged_df['총액차이'] = merged_df['[일마] 총액'] - merged_df['[차트] 총액']
                    merged_df['플랫폼차이'] = merged_df['[일마] 플랫폼합계'] - merged_df['[차트] 플랫폼(기타)']
                    
                    def get_display_name(row):
                        nd = str(row.get('성명', '')).strip()
                        np_name = str(row.get('이름', '')).strip()
                        if nd == 'nan': nd = ''
                        if np_name == 'nan': np_name = ''
                        if nd and np_name and nd != np_name: return f"{nd} (차트명: {np_name})"
                        return nd if nd else np_name

                    merged_df['환자명'] = merged_df.apply(get_display_name, axis=1)
                    
                    def estimate_chart_issue(row):
                        msgs = []
                        nd, np_name = str(row.get('성명', '')).strip(), str(row.get('이름', '')).strip()
                        if nd != 'nan' and np_name != 'nan' and nd and np_name and nd != np_name: msgs.append(f"✍️ 이름 오타 의심 ([일마]: {nd} / [차트]: {np_name})")
                        if row['[차트] 총액'] == 0 and row['[일마] 총액'] > 0: msgs.append("⚠️ [차트] 수납(마감) 누락 의심")
                        elif row['[일마] 총액'] == 0 and row['[차트] 총액'] > 0: msgs.append("⚠️ [일마] 장부 기재 누락 의심")
                        elif row['플랫폼차이'] != 0: msgs.append("강남언니, 여신티켓 등 플랫폼 금액 엇갈림")
                        elif row['총액차이'] != 0: msgs.append("할인, 부가세 등으로 인한 단순 금액 오차")
                        return " / ".join(msgs) if msgs else "✅ 정상"

                    merged_df['💡의심추정/비고'] = merged_df.apply(estimate_chart_issue, axis=1)

                    diff_df = merged_df[(merged_df['총액차이'] != 0) | (merged_df['플랫폼차이'] != 0) | (merged_df['💡의심추정/비고'].str.contains('오타'))][
                        ['차트번호', '환자명', '[일마] 총액', '[차트] 총액', '총액차이', '[일마] 플랫폼합계', '[차트] 플랫폼(기타)', '플랫폼차이', '💡의심추정/비고']
                    ]
                    diff_df['차트번호'] = diff_df['차트번호'].astype(str).replace('0', '-')

                    if diff_df.empty: st.success("완벽합니다! [차트]와 [일마] 간의 불일치 건이나 오타가 없습니다.")
                    else:
                        st.warning(f"금액 불일치 또는 이름 오타가 확인된 환자가 {len(diff_df)}명 있습니다.")
                        st.dataframe(diff_df.style.format({'[일마] 총액': '{:,.0f}', '[차트] 총액': '{:,.0f}', '총액차이': '{:,.0f}', '[일마] 플랫폼합계': '{:,.0f}', '[차트] 플랫폼(기타)': '{:,.0f}', '플랫폼차이': '{:,.0f}'}), use_container_width=True)
