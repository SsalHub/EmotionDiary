import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import google.generativeai as genai
from datetime import datetime

# --- 1. 기본 설정 및 상수 ---
st.set_page_config(
    page_title="AI 감정 일기장",
    page_icon="📝",
    layout="wide"
)

# 감정 점수와 이모티콘 매핑
MOOD_EMOJIS = {
    1: "😫 매우 나쁨 (1점)",
    2: "😟 나쁨 (2점)",
    3: "😐 괜찮음 (3점)",
    4: "🙂 좋음 (4점)",
    5: "🥰 매우 좋음 (5점)"
}

# --- 2. 로그인 유지 로직 (새로고침 대응) ---
# URL에 사용자 정보가 남아있다면 자동으로 로그인 처리
if 'is_logged_in' not in st.session_state:
    # URL 쿼리 파라미터 확인
    if "user" in st.query_params and "name" in st.query_params:
        st.session_state['is_logged_in'] = True
        st.session_state['user_info'] = {
            "username": st.query_params["user"],
            "name": st.query_params["name"]
        }
    else:
        st.session_state['is_logged_in'] = False
        st.session_state['user_info'] = None

# --- 3. 연결 및 AI 설정 ---
conn = st.connection("gsheets", type=GSheetsConnection)

try:
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    else:
        st.error("secrets.toml에 GOOGLE_API_KEY가 없습니다.")
except Exception as e:
    st.error(f"API 설정 오류: {e}")

# --- 4. 핵심 함수들 ---

def login_check(username, password):
    """users 시트에서 사용자 확인"""
    try:
        users_df = conn.read(worksheet="users", ttl=0)
        users_df['password'] = users_df['password'].astype(str)
        input_password = str(password)
        
        user_row = users_df[
            (users_df['username'] == username) & 
            (users_df['password'] == input_password)
        ]
        
        if not user_row.empty:
            return user_row.iloc[0]
        return None
    except Exception as e:
        st.error(f"로그인 확인 중 오류 발생: {e}")
        return None

def get_ai_response(user_text):
    """Gemini에게 조언과 점수를 요청"""
    try:
        model = genai.GenerativeModel('gemini-2.5-flash') 
        prompt = f"""
        당신은 따뜻하고 통찰력 있는 심리 상담가입니다. 사용자의 일기를 읽고 분석해주세요.
        
        [요청사항]
        1. 공감과 위로, 혹은 칭찬이 담긴 따뜻한 조언 (3문장 이내)
        2. 작성자의 기분을 1~5점 사이의 정수로 평가 (숫자만 출력)
           (1:매우나쁨, 2:나쁨, 3:괜찮음, 4:좋음, 5:매우좋음)
        
        [출력형식]
        조언 내용 텍스트
        |||
        점수(숫자만)

        일기 내용: {user_text}
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 분석 실패: {e} ||| 3"

# --- 5. 메인 화면 로직 ---

# [화면 A] 로그인 전
if not st.session_state['is_logged_in']:
    st.title("🔐 AI 감정 일기장 로그인")
    
    col1, col2 = st.columns([1, 2])
    with col1:
        st.info("로그인이 필요합니다.")
    with col2:
        with st.form("login_form"):
            input_id = st.text_input("아이디")
            input_pw = st.text_input("비밀번호", type="password")
            submit_login = st.form_submit_button("로그인")
            
            if submit_login:
                user = login_check(input_id, input_pw)
                if user is not None:
                    # 세션 상태 업데이트
                    st.session_state['is_logged_in'] = True
                    st.session_state['user_info'] = user
                    
                    # ⭐ 로그인 유지: URL에 사용자 정보 저장 (새로고침 방지용)
                    st.query_params["user"] = user['username']
                    st.query_params["name"] = user['name']
                    
                    st.toast(f"{user['name']}님 환영합니다!", icon="👋")
                    st.rerun()
                else:
                    st.error("아이디 또는 비밀번호가 일치하지 않습니다.")

# [화면 B] 로그인 후 (메인 앱)
else:
    current_user = st.session_state['user_info']['username']
    current_name = st.session_state['user_info']['name']

    # 사이드바
    with st.sidebar:
        st.header(f"반가워요, {current_name}님! 🍀")
        if st.button("로그아웃"):
            # 로그아웃 시 세션 및 URL 정보 모두 삭제
            st.session_state['is_logged_in'] = False
            st.query_params.clear()
            st.rerun()

    st.title(f"📖 {current_name}의 감정 일기장")

    # === 데이터 로딩 (공통 사용) ===
    try:
        all_diaries = conn.read(worksheet="diaries", ttl=0)
        if all_diaries.empty:
            my_data = pd.DataFrame()
        elif 'username' in all_diaries.columns:
            my_data = all_diaries[all_diaries['username'] == current_user].copy()
            my_data['date'] = pd.to_datetime(my_data['date'])
            my_data['emotion_tag'] = pd.to_numeric(my_data['emotion_tag'], errors='coerce')
        else:
            my_data = pd.DataFrame()
    except Exception:
        all_diaries = pd.DataFrame()
        my_data = pd.DataFrame()

    # === 탭 구성 ===
    tab_dashboard, tab_write = st.tabs(["📊 대시보드 (기록 & 그래프)", "🖊️ 일기 쓰기"])

    # ---------------------------------------------------------
    # 탭 1: 대시보드 (월별 그래프 + 목록)
    # ---------------------------------------------------------
    with tab_dashboard:
        st.subheader("📈 내 기분 흐름과 지난 이야기")
        
        if not my_data.empty:
            # ⭐ 월별 필터 기능 추가
            # 1. 'YYYY-MM' 형식의 컬럼 생성
            my_data['month_str'] = my_data['date'].dt.strftime('%Y-%m')
            
            # 2. 존재하는 월 목록 추출 (최신순)
            available_months = sorted(my_data['month_str'].unique(), reverse=True)
            
            # 3. 선택 박스 (그래프 바로 위)
            col_filter, col_empty = st.columns([1, 3])
            with col_filter:
                selected_month = st.selectbox("조회할 월을 선택하세요", available_months)
            
            # 4. 데이터 필터링
            filtered_data = my_data[my_data['month_str'] == selected_month].sort_values('date')
            
            if not filtered_data.empty:
                # 5. 그래프 그리기 (필터링된 데이터 사용)
                chart_data = filtered_data.set_index('date')['emotion_tag']
                st.line_chart(chart_data)
                
                avg_mood = filtered_data['emotion_tag'].mean()
                st.caption(f"💡 {selected_month}의 평균 기분 점수는 **{avg_mood:.1f}점**입니다.")
            else:
                st.info("선택한 월에 데이터가 없습니다.")
            
            st.divider()
            
            # 6. 하단: 지난 기록 리스트 (필터링된 월 데이터만 보여줌)
            st.subheader(f"📋 {selected_month} 일기 목록")
            # 최신순 정렬
            display_df = filtered_data.sort_values(by="date", ascending=False)
            
            for index, row in display_df.iterrows():
                try: score_val = int(row['emotion_tag'])
                except: score_val = 3
                
                with st.expander(f"{row['date'].strftime('%Y-%m-%d')} - {MOOD_EMOJIS.get(score_val, '알수없음')}"):
                    st.write(f"**📝 내용:** {row['content']}")
                    # 조언은 info 박스로 깔끔하게
                    st.info(f"**💌 AI 조언:** {row['ai_advice']}")
        else:
            st.info("아직 데이터가 없습니다. '일기 쓰기' 탭에서 첫 기록을 남겨보세요!")

    # ---------------------------------------------------------
    # 탭 2: 일기 쓰기
    # ---------------------------------------------------------
    with tab_write:
        st.subheader("오늘의 마음 기록")
        
        selected_date = st.date_input("날짜 선택", datetime.now())
        selected_date_str = selected_date.strftime("%Y-%m-%d")
        
        current_day_entry = pd.DataFrame()
        if not my_data.empty:
            my_data['date_str_check'] = my_data['date'].dt.strftime("%Y-%m-%d")
            current_day_entry = my_data[my_data['date_str_check'] == selected_date_str]

        # === [상황 A: 수정 모드] ===
        if not current_day_entry.empty:
            st.success(f"✅ {selected_date_str}의 일기가 저장되었습니다! 오늘의 조언을 확인해보세요.")
            
            existing_row = current_day_entry.iloc[0]
            existing_id = existing_row['id']
            existing_content = existing_row['content']
            existing_advice = existing_row['ai_advice']
            existing_score = int(existing_row['emotion_tag'])

            with st.form("edit_form"):
                content = st.text_area("내용 수정하기", value=existing_content, height=150)
                submit_update = st.form_submit_button("수정 및 AI 재분석 🔄")

                if submit_update and content:
                    with st.spinner("수정된 내용을 다시 분석 중입니다..."):
                        full_response = get_ai_response(content)
                        if "|||" in full_response:
                            ai_advice, score_text = full_response.split("|||")
                            try:
                                score = int(score_text.strip())
                                score = max(1, min(5, score))
                            except: score = 3
                        else:
                            ai_advice = full_response; score = 3
                        
                        all_diaries = conn.read(worksheet="diaries", ttl=0)
                        all_diaries['id'] = pd.to_numeric(all_diaries['id'], errors='coerce')
                        
                        row_idx = all_diaries.index[all_diaries['id'] == pd.to_numeric(existing_id, errors='coerce')].tolist()
                        
                        if row_idx:
                            idx = row_idx[0]
                            all_diaries.at[idx, 'content'] = content
                            all_diaries.at[idx, 'ai_advice'] = ai_advice.strip()
                            all_diaries.at[idx, 'emotion_tag'] = score
                            all_diaries.at[idx, 'timestamp'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                            
                            conn.update(worksheet="diaries", data=all_diaries)
                            st.cache_data.clear()
                            st.rerun()
                        else:
                            st.error("데이터 오류: 수정할 대상을 찾지 못했습니다.")

            # ⭐ 디자인 변경 요청 반영: 검정 배경 + 흰색 글씨
            st.divider()
            st.subheader("💌 오늘의 AI 조언")
            
            st.markdown(f"""
            <div style="
                background-color: #000000; 
                color: #ffffff; 
                padding: 20px; 
                border-radius: 10px; 
                line-height: 1.6;
                font-size: 1.1em;
                box-shadow: 0 4px 6px rgba(0,0,0,0.1);">
                {existing_advice}
            </div>
            """, unsafe_allow_html=True)
            
            st.write("")
            st.info(f"오늘의 기분 점수: **{existing_score}점** {MOOD_EMOJIS.get(existing_score, '')}")

        # === [상황 B: 신규 작성 모드] ===
        else:
            with st.form("diary_form"):
                content = st.text_area("내용", height=200, placeholder=f"{selected_date_str}의 일기를 작성해보세요.")
                submit_diary = st.form_submit_button("AI 조언 받기 및 저장 ✨")

                if submit_diary and content:
                    with st.spinner("AI 분석 및 저장 중..."):
                        full_response = get_ai_response(content)
                        if "|||" in full_response:
                            ai_advice, score_text = full_response.split("|||")
                            try:
                                score = int(score_text.strip())
                                score = max(1, min(5, score))
                            except: score = 3
                        else:
                            ai_advice = full_response; score = 3

                        all_diaries = conn.read(worksheet="diaries", ttl=0)
                        if all_diaries.empty or 'id' not in all_diaries.columns:
                            new_id = 1
                        else:
                            max_id = pd.to_numeric(all_diaries['id'], errors='coerce').max()
                            new_id = 1 if pd.isna(max_id) else int(max_id) + 1

                        new_data = pd.DataFrame([{
                            "id": new_id,
                            "username": current_user,
                            "date": selected_date_str,
                            "content": content,
                            "ai_advice": ai_advice.strip(),
                            "emotion_tag": score,
                            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        }])
                        
                        if all_diaries.empty:
                            updated_df = new_data
                        else:
                            updated_df = pd.concat([all_diaries, new_data], ignore_index=True)
                        
                        conn.update(worksheet="diaries", data=updated_df)
                        st.cache_data.clear()
                        st.rerun()