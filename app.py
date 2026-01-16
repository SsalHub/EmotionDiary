import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import google.generativeai as genai
from datetime import datetime, timedelta # ⭐ timedelta 추가
import hashlib
import json
import re
import uuid
import time
import random

# --- 1. 기본 설정 및 디자인 ---
st.set_page_config(
    page_title="마음의 쉼표 - AI 감정 일기장",
    page_icon="☁️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
    <style>
    .stApp { background-color: #F0F8FF; }
    .block-container { padding-top: 2rem; padding-bottom: 2rem; }
    
    div[data-testid="stForm"], div.stDataFrame, div.stExpander, div[data-testid="stChatInput"] {
        background-color: #FFFFFF;
        padding: 20px;
        border-radius: 20px;
        box-shadow: 0 4px 15px rgba(0,0,0,0.05);
        border: 1px solid #E1E8F0;
    }
    
    div.stButton > button[kind="primary"] {
        border-radius: 20px;
        background-color: #87CEEB;
        color: white;
        border: none;
        font-weight: bold;
        transition: all 0.3s;
    }
    div.stButton > button[kind="primary"]:hover {
        background-color: #00BFFF;
        transform: scale(1.02);
    }

    div.stButton > button[kind="secondary"] {
        border-radius: 20px;
        background-color: #E0E0E0;
        color: #555555;
        border: none;
        font-weight: bold;
        transition: all 0.3s;
    }
    div.stButton > button[kind="secondary"]:hover {
        background-color: #BDBDBD;
        color: #333333;
        transform: scale(1.02);
    }
    
    section[data-testid="stSidebar"] { background-color: #FFFFFF; border-right: 1px solid #E6E6E6; }
    
    .advice-box {
        background-color: #E3F2FD;
        border-left: 5px solid #2196F3;
        padding: 20px;
        border-radius: 15px;
        color: #333333;
        font-size: 1.1em;
        line-height: 1.6;
        margin-top: 20px;
        margin-bottom: 20px;
    }
    
    .chat-row { display: flex; margin-bottom: 15px; align-items: flex-end; }
    .chat-row.user { justify-content: flex-end; }
    .chat-row.model { justify-content: flex-start; }
    .chat-bubble { padding: 12px 18px; border-radius: 20px; max-width: 70%; font-size: 1em; line-height: 1.5; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
    .user-bubble { background-color: #87CEEB; color: white; border-bottom-right-radius: 2px; }
    .model-bubble { background-color: #F0F2F6; color: #333333; border-bottom-left-radius: 2px; }
    .chat-icon { font-size: 24px; margin: 0 10px; }
    
    /* 관리자 페이지용 스타일 */
    .admin-card {
        background-color: #FFF3E0;
        border: 1px solid #FFCC80;
        padding: 15px;
        border-radius: 10px;
        margin-bottom: 10px;
    }

    h1, h2, h3 { color: #2C3E50; font-family: 'Helvetica Neue', sans-serif; }
    </style>
    """, unsafe_allow_html=True)

MOOD_EMOJIS = {
    1: "☁️ 흐림 (매우 나쁨)",
    2: "🌦️ 비 (나쁨)",
    3: "⛅ 구름 조금 (괜찮음)",
    4: "☀️ 맑음 (좋음)",
    5: "🌈 무지개 (매우 좋음)"
}

# --- 2. 세션 초기화 ---
if 'is_logged_in' not in st.session_state:
    if "user" in st.query_params and "name" in st.query_params:
        st.session_state['is_logged_in'] = False
        st.session_state['user_info'] = None
    else:
        st.session_state['is_logged_in'] = False
        st.session_state['user_info'] = None

if 'auth_mode' not in st.session_state:
    st.session_state['auth_mode'] = 'login'

conn = st.connection("gsheets", type=GSheetsConnection)

try:
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    else:
        st.error("설정 오류: secrets.toml에 API 키가 없습니다.")
except Exception as e:
    st.error(f"오류: {e}")

# --- 3. 함수 정의 ---

def check_rate_limit(key, limit_sec=3):
    now = time.time()
    if key in st.session_state:
        elapsed = now - st.session_state[key]
        if elapsed < limit_sec:
            st.toast(f"🚫 너무 빠릅니다! {int(limit_sec - elapsed) + 1}초 뒤에 다시 시도해주세요.", icon="⏳")
            return False
    st.session_state[key] = now
    return True

def make_hashes(password):
    return hashlib.sha256(str(password).encode()).hexdigest()

def sanitize_for_sheets(text):
    if isinstance(text, str) and text.startswith(('=', '+', '-', '@')):
        return "'" + text
    return text

def login_check(username, password):
    try:
        users_df = conn.read(worksheet="users", ttl=0)
        users_df['password'] = users_df['password'].astype(str)
        input_hash = make_hashes(password)
        
        user_row = users_df[(users_df['username'] == username) & (users_df['password'] == input_hash)]
        
        if not user_row.empty:
            user_data = user_row.iloc[0].to_dict()
            if 'role' not in user_data or pd.isna(user_data['role']):
                user_data['role'] = 'user'
            return user_data
        return None
    except Exception: return None

def register_user(username, password, name):
    try:
        users_df = conn.read(worksheet="users", ttl=0)
        if username in users_df['username'].values:
            return False, "이미 존재하는 아이디입니다."
        
        while True:
            new_uuid = str(uuid.uuid4())
            if 'user_id' in users_df.columns and new_uuid in users_df['user_id'].values:
                continue
            else:
                break

        pw_hash = make_hashes(password)
        new_user = pd.DataFrame([{
            "user_id": new_uuid,
            "username": username,
            "password": pw_hash,
            "name": name,
            "role": "user"
        }])
        
        updated_df = pd.concat([users_df, new_user], ignore_index=True)
        conn.update(worksheet="users", data=updated_df)
        return True, "가입 성공"
    except Exception as e:
        return False, f"오류: {e}"

def update_user_info(target_uuid, new_name=None, new_password=None):
    try:
        users_df = conn.read(worksheet="users", ttl=0)
        idx_list = users_df.index[users_df['user_id'] == target_uuid].tolist()
        
        if not idx_list:
            return False, "사용자 정보를 찾을 수 없습니다."
        
        idx = idx_list[0]
        
        if new_name:
            users_df.at[idx, 'name'] = new_name
        if new_password:
            users_df.at[idx, 'password'] = make_hashes(new_password)
            
        conn.update(worksheet="users", data=users_df)
        return True, "정보가 성공적으로 수정되었습니다!"
    except Exception as e:
        return False, f"수정 중 오류 발생: {e}"

# ⭐ [신규] 최근 30일 일기 가져오는 함수
def get_past_diaries_text(user_id, days=30):
    """
    해당 유저의 최근 n일간 일기 내용을 문자열로 요약하여 반환
    """
    try:
        # 데이터 로드 (캐시 활용)
        df = conn.read(worksheet="diaries", ttl="10m")
        if df.empty: return "과거 기록 없음"
        
        # 날짜 형식 변환 및 필터링
        # user_id 컬럼이 있는지 확인 (구형 데이터 호환성)
        if 'user_id' not in df.columns:
            return "과거 기록을 불러올 수 없습니다 (DB 스키마 구형)."

        df['date'] = pd.to_datetime(df['date'])
        cutoff_date = datetime.now() - timedelta(days=days)
        
        # 내 아이디 + 최근 30일 + 날짜순 정렬
        my_history = df[
            (df['user_id'] == user_id) & 
            (df['date'] >= cutoff_date)
        ].sort_values('date')
        
        if my_history.empty:
            return "최근 작성된 과거 기록이 없습니다."
        
        # 문자열로 변환 (예: [2026-01-01] (3점) : 오늘은 힘들었다...)
        history_text = ""
        for _, row in my_history.iterrows():
            date_str = row['date'].strftime("%Y-%m-%d")
            score = row['emotion_tag']
            content = str(row['content'])[:200] # 너무 길면 200자 정도로 요약
            history_text += f"[{date_str}] (기분 {score}점): {content}\n"
            
        return history_text
        
    except Exception as e:
        return f"기록 불러오기 실패: {e}"

# ⭐ [수정] 프롬프트에 과거 기록(past_history) 반영
def get_ai_response(user_text, user_name, past_history=""):
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = f"""
        당신은 내담자({user_name}님)의 삶의 맥락을 깊이 이해하는 전담 심리 상담가입니다.
        단편적인 조언이 아니라, 과거의 흐름을 고려하여 통찰력 있는 답변을 해주세요.
        
        <context>
        아래는 {user_name}님이 최근 한 달 동안 작성한 일기 기록입니다.
        이 기록을 통해 내담자의 최근 감정 변화 추이, 반복되는 고민, 혹은 긍정적인 변화를 파악하세요.
        
        {past_history}
        </context>

        <diary>
        오늘의 일기:
        {user_text}
        </diary>
        
        <instructions>
        1. **맥락 연결:** 과거 기록과 오늘의 일기를 연결 지어 언급하세요. (예: "지난주에는 ~때문에 힘들어하셨는데, 오늘은 좀 나아지신 것 같아 다행이에요" 또는 "저번부터 계속 ~로 고민이 깊으시군요.")
        2. **호칭:** 반드시 '{user_name}님'이라고 부르세요.
        3. **분량:** 따뜻하고 구체적인 조언으로 3~4문장.
        4. **평가:** 작성자의 오늘 기분을 1~5점 사이의 정수로 평가 (숫자만 출력).
        
        [출력형식]
        조언 내용
        |||
        점수
        </instructions>
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 연결 실패: {e} ||| 3"

def get_chat_response(diary_content, chat_history, new_question, user_name):
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        history_text = ""
        for chat in chat_history:
            role = "상담사" if chat["role"] == "model" else "내담자"
            history_text += f"{role}: {chat['text']}\n"
            
        prompt = f"""
        당신은 전문 심리 상담가입니다. 
        <instructions>
        내담자의 이름은 '{user_name}'입니다. 대화할 때 '내담자'나 '회원님'이라는 호칭 대신, 반드시 '{user_name}님'이라고 다정하게 불러주세요.
        사용자의 일기(<diary>)와 이전 대화(<history>)를 바탕으로, 새로운 질문(<question>)에 답변하세요.
        따뜻하게 공감하는 태도를 유지하세요.
        </instructions>
        
        <diary>
        {diary_content}
        </diary>
        
        <history>
        {history_text}
        </history>
        
        <question>
        {new_question}
        </question>
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return "죄송해요, 잠시 연결이 불안정합니다."

@st.dialog("⚠️ 대화 내용 초기화")
def confirm_reset_dialog(row_id):
    st.write("정말로 대화 내용을 초기화하시겠습니까?")
    st.warning("이 작업은 되돌릴 수 없으며, 현재 일기의 모든 대화 내역이 삭제됩니다.")
    
    col_no, col_yes = st.columns([1, 1])
    with col_no:
        if st.button("취소", use_container_width=True):
            st.rerun()
    with col_yes:
        if st.button("확인 (삭제)", type="primary", use_container_width=True):
            try:
                all_diaries = conn.read(worksheet="diaries", ttl=0)
                all_diaries['id'] = pd.to_numeric(all_diaries['id'], errors='coerce')
                target_idx = all_diaries.index[all_diaries['id'] == pd.to_numeric(row_id, errors='coerce')].tolist()[0]
                all_diaries.at[target_idx, 'chat_history'] = "[]"
                conn.update(worksheet="diaries", data=all_diaries)
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.error(f"오류가 발생했습니다: {e}")

# --- 4. 화면 로직 ---

if not st.session_state['is_logged_in']:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        st.title("☁️ 마음의 쉼표")
        st.markdown("##### 당신의 하루를 따뜻하게 기록해드립니다.")
        
        if st.session_state['auth_mode'] == 'login':
            st.subheader("🔒 로그인")
            with st.form("login_form"):
                input_id = st.text_input("아이디")
                input_pw = st.text_input("비밀번호", type="password")
                submitted = st.form_submit_button("로그인", type="primary", use_container_width=True)
                if submitted:
                    if check_rate_limit("login_attempt", 3):
                        safe_id = sanitize_for_sheets(input_id)
                        user = login_check(safe_id, input_pw)
                        if user is not None:
                            st.session_state['is_logged_in'] = True
                            st.session_state['user_info'] = user
                            st.rerun()
                        else:
                            st.error("아이디 또는 비밀번호를 확인해주세요.")
            
            st.write("")
            col_msg, col_switch = st.columns([1.5, 2])
            with col_msg: st.write("아직 계정이 없으신가요?")
            with col_switch:
                if st.button("📝 회원가입 하러가기", type="secondary", use_container_width=True):
                    st.session_state['auth_mode'] = 'signup'
                    st.rerun()

        elif st.session_state['auth_mode'] == 'signup':
            st.subheader("📝 회원가입")
            st.info("💡 봇 가입 방지를 위해 간단한 산수 문제를 풀어주세요.")
            
            if 'captcha_num1' not in st.session_state:
                st.session_state['captcha_num1'] = random.randint(1, 10)
                st.session_state['captcha_num2'] = random.randint(1, 10)
            
            c_num1 = st.session_state['captcha_num1']
            c_num2 = st.session_state['captcha_num2']
            
            with st.form("signup_form"):
                new_id = st.text_input("사용할 아이디")
                new_pw = st.text_input("사용할 비밀번호", type="password")
                new_name = st.text_input("닉네임 (화면에 표시됩니다)")
                captcha_ans = st.text_input(f"{c_num1} + {c_num2} = ?", placeholder="정답을 숫자로 입력하세요")
                
                signup_submitted = st.form_submit_button("가입하기", type="primary", use_container_width=True)
                
                if signup_submitted:
                    if check_rate_limit("signup_attempt", 5):
                        if captcha_ans.strip() != str(c_num1 + c_num2):
                            st.error("산수 문제 정답이 틀렸습니다.")
                            st.session_state['captcha_num1'] = random.randint(1, 10)
                            st.session_state['captcha_num2'] = random.randint(1, 10)
                            time.sleep(0.5)
                            st.rerun() 
                        elif new_id and new_pw and new_name:
                            safe_new_id = sanitize_for_sheets(new_id)
                            safe_new_name = sanitize_for_sheets(new_name)
                            success, msg = register_user(safe_new_id, new_pw, safe_new_name)
                            if success:
                                st.session_state['auth_mode'] = 'login'
                                del st.session_state['captcha_num1']
                                del st.session_state['captcha_num2']
                                st.toast("✅ 회원가입 완료! 이제 로그인해주세요.", icon="🎉")
                                time.sleep(1)
                                st.rerun()
                            else:
                                st.error(msg)
                        else:
                            st.warning("모든 정보를 입력해주세요.")

            st.write("")
            col_msg, col_switch = st.columns([1.5, 2])
            with col_msg: st.write("이미 계정이 있으신가요?")
            with col_switch:
                if st.button("🔒 로그인 하러가기", type="secondary", use_container_width=True):
                    st.session_state['auth_mode'] = 'login'
                    st.rerun()

else:
    # 로그인 정보 가져오기
    current_user_id = st.session_state['user_info']['user_id']
    current_username = st.session_state['user_info']['username']
    current_name = st.session_state['user_info']['name']
    current_role = st.session_state['user_info'].get('role', 'user')

    with st.sidebar:
        st.title(f"{current_name}님의\n마음 기록 ☁️")
        
        if current_role == 'admin':
            st.markdown("### 👑 Administrator")
            
        st.write("")
        
        menu_options = ["📊 대시보드", "🖊️ 일기 쓰기", "⚙️ 내 정보 수정"]
        if current_role == 'admin':
            menu_options.insert(0, "👑 관리자 페이지")
            
        menu = st.radio("메뉴 이동", menu_options, index=1 if current_role == 'admin' else 0)
        
        st.write("")
        st.markdown("---")
        if st.button("로그아웃", type="secondary", use_container_width=True):
            st.session_state['is_logged_in'] = False
            st.query_params.clear()
            st.rerun()

    # === [메뉴 0] 관리자 페이지 ===
    if menu == "👑 관리자 페이지" and current_role == 'admin':
        st.header("👑 관리자 대시보드")
        
        try:
            all_users = conn.read(worksheet="users", ttl="10m")
            all_diaries = conn.read(worksheet="diaries", ttl="10m")
            
            c1, c2, c3 = st.columns(3)
            with c1: st.metric("총 가입자 수", f"{len(all_users)}명")
            with c2: st.metric("총 일기 수", f"{len(all_diaries)}개")
            with c3:
                avg_mood = all_diaries['emotion_tag'].mean() if not all_diaries.empty else 0
                st.metric("전체 평균 기분", f"{avg_mood:.1f}점")
            
            st.divider()
            admin_tab1, admin_tab2 = st.tabs(["👥 유저 관리", "📝 전체 일기 모니터링"])
            
            with admin_tab1:
                st.subheader("가입자 목록")
                st.dataframe(all_users[['username', 'name', 'role', 'user_id']], use_container_width=True)
            
            with admin_tab2:
                st.subheader("최신 작성 일기")
                if not all_diaries.empty:
                    merged_df = pd.merge(all_diaries, all_users[['user_id', 'name']], on='user_id', how='left')
                    merged_df['date'] = pd.to_datetime(merged_df['date'])
                    st.dataframe(
                        merged_df[['date', 'name', 'content', 'emotion_tag', 'ai_advice']].sort_values('date', ascending=False),
                        use_container_width=True, height=400
                    )
                else:
                    st.info("작성된 일기가 없습니다.")
        except Exception as e:
            st.error(f"관리자 데이터 로드 실패: {e}")

    # === [메뉴 1] 대시보드 ===
    elif menu == "📊 대시보드":
        st.header("📈 내 마음의 날씨 흐름")
        
        try:
            all_diaries = conn.read(worksheet="diaries", ttl="10m")
            if not all_diaries.empty:
                all_diaries['chat_history'] = all_diaries.get('chat_history', pd.Series()).fillna("[]").astype(str)

            if all_diaries.empty: my_data = pd.DataFrame()
            elif 'user_id' in all_diaries.columns:
                my_data = all_diaries[all_diaries['user_id'] == current_user_id].copy()
                my_data['date'] = pd.to_datetime(my_data['date'])
                my_data['emotion_tag'] = pd.to_numeric(my_data['emotion_tag'], errors='coerce')
            else: my_data = pd.DataFrame()
        except Exception:
            my_data = pd.DataFrame()

        if not my_data.empty:
            my_data['month_str'] = my_data['date'].dt.strftime('%Y-%m')
            available_months = sorted(my_data['month_str'].unique(), reverse=True)
            col_sel, _ = st.columns([1, 3])
            with col_sel:
                selected_month = st.selectbox("📅 월 선택", available_months)
            
            filtered_data = my_data[my_data['month_str'] == selected_month].sort_values('date')
            
            if not filtered_data.empty:
                st.markdown("##### 감정 변화 그래프")
                chart_data = filtered_data.set_index('date')['emotion_tag']
                st.line_chart(chart_data, color="#87CEEB")
                
                st.markdown("---")
                st.subheader(f"📋 {selected_month}의 기록들")
                display_df = filtered_data.sort_values(by="date", ascending=False)
                for _, row in display_df.iterrows():
                    try: score = int(row['emotion_tag'])
                    except: score = 3
                    with st.expander(f"{row['date'].strftime('%Y-%m-%d')} : {MOOD_EMOJIS.get(score, '')}"):
                        st.write(row['content'])
                        st.markdown(f"<div style='background-color:#F5F5F5; padding:10px; border-radius:10px; margin-top:10px;'>💌 <b>AI:</b> {row['ai_advice']}</div>", unsafe_allow_html=True)
            else: st.info("선택하신 달의 데이터가 없습니다.")
        else: st.info("아직 기록된 일기가 없습니다.")

    # === [메뉴 2] 일기 쓰기 ===
    elif menu == "🖊️ 일기 쓰기":
        st.header("오늘의 마음 기록하기 🖊️")
        
        try:
            all_diaries = conn.read(worksheet="diaries", ttl="10m")
            if not all_diaries.empty:
                all_diaries['chat_history'] = all_diaries.get('chat_history', pd.Series()).fillna("[]").astype(str)
                
            if all_diaries.empty: my_data = pd.DataFrame()
            elif 'user_id' in all_diaries.columns:
                my_data = all_diaries[all_diaries['user_id'] == current_user_id].copy()
                my_data['date'] = pd.to_datetime(my_data['date'])
                my_data['emotion_tag'] = pd.to_numeric(my_data['emotion_tag'], errors='coerce')
            else: my_data = pd.DataFrame()
        except Exception:
            all_diaries = pd.DataFrame()
            my_data = pd.DataFrame()

        selected_date = st.date_input("날짜를 선택하세요", datetime.now())
        selected_date_str = selected_date.strftime("%Y-%m-%d")
        
        current_day_entry = pd.DataFrame()
        if not my_data.empty:
            my_data['date_str_chk'] = my_data['date'].dt.strftime("%Y-%m-%d")
            current_day_entry = my_data[my_data['date_str_chk'] == selected_date_str]

        # --- [수정 모드] ---
        if not current_day_entry.empty:
            row = current_day_entry.iloc[0]
            
            with st.expander("📝 일기 내용 수정하기"):
                with st.form("edit_form"):
                    content = st.text_area("내용", value=row['content'], height=150)
                    if st.form_submit_button("수정 및 재분석 🔄", type="primary"):
                        if check_rate_limit("edit_diary", 5):
                            with st.spinner("분석 중..."):
                                safe_content = sanitize_for_sheets(content)
                                # 수정 모드에서는 기존 데이터만으로 분석 (과거 기록 연결은 선택사항이나 여기선 단순 유지)
                                full_res = get_ai_response(safe_content, current_name) 
                                if "|||" in full_res: advice, sc = full_res.split("|||"); score=int(sc.strip())
                                else: advice=full_res; score=3
                                
                                all_diaries_latest = conn.read(worksheet="diaries", ttl=0)
                                all_diaries_latest['id'] = pd.to_numeric(all_diaries_latest['id'], errors='coerce')
                                idx = all_diaries_latest.index[all_diaries_latest['id'] == pd.to_numeric(row['id'], errors='coerce')].tolist()[0]
                                all_diaries_latest.at[idx, 'content'] = safe_content
                                all_diaries_latest.at[idx, 'ai_advice'] = advice.strip()
                                all_diaries_latest.at[idx, 'emotion_tag'] = max(1, min(5, score))
                                all_diaries_latest.at[idx, 'chat_history'] = "[]"
                                
                                conn.update(worksheet="diaries", data=all_diaries_latest)
                                st.cache_data.clear()
                                st.rerun()

            st.markdown(f"""<div class="advice-box">{row['ai_advice']}</div>""", unsafe_allow_html=True)
            score_val = int(row['emotion_tag'])
            st.info(f"오늘의 마음 날씨: **{MOOD_EMOJIS.get(score_val, '')}**")

            st.markdown("---")

            col_title, col_btn = st.columns([8, 2])
            with col_title: st.subheader("💬 AI 선생님과 대화하기")
            with col_btn:
                if st.button("🗑️ 대화 초기화", type="secondary", use_container_width=True):
                    confirm_reset_dialog(row['id'])

            chat_history = []
            raw_history = str(row['chat_history'])
            if raw_history in ['nan', 'None', '', 'NaN']: chat_history = []
            else:
                try:
                    chat_history = json.loads(raw_history)
                    if not isinstance(chat_history, list): chat_history = []
                except: chat_history = []
            
            chat_container = st.container()
            with chat_container:
                for chat in chat_history:
                    if chat["role"] == "user":
                        st.markdown(f"""<div class="chat-row user"><div class="chat-bubble user-bubble">{chat['text']}</div><div class="chat-icon">👤</div></div>""", unsafe_allow_html=True)
                    else:
                        st.markdown(f"""<div class="chat-row model"><div class="chat-icon">🤖</div><div class="chat-bubble model-bubble">{chat['text']}</div></div>""", unsafe_allow_html=True)

            if user_input := st.chat_input("하고 싶은 말을 적어보세요..."):
                if check_rate_limit("chat_attempt", 2):
                    st.markdown(f"""<div class="chat-row user"><div class="chat-bubble user-bubble">{user_input}</div><div class="chat-icon">👤</div></div>""", unsafe_allow_html=True)
                    chat_history.append({"role": "user", "text": user_input})

                    with st.spinner("답변 작성 중..."):
                        ai_reply = get_chat_response(row['content'], chat_history, user_input, current_name)
                    
                    st.markdown(f"""<div class="chat-row model"><div class="chat-icon">🤖</div><div class="chat-bubble model-bubble">{ai_reply}</div></div>""", unsafe_allow_html=True)
                    chat_history.append({"role": "model", "text": ai_reply})

                    updated_history_json = json.dumps(chat_history, ensure_ascii=False)
                    
                    all_diaries_latest = conn.read(worksheet="diaries", ttl=0)
                    all_diaries_latest['id'] = pd.to_numeric(all_diaries_latest['id'], errors='coerce')
                    target_idx = all_diaries_latest.index[all_diaries_latest['id'] == pd.to_numeric(row['id'], errors='coerce')].tolist()[0]
                    all_diaries_latest.at[target_idx, 'chat_history'] = updated_history_json
                    conn.update(worksheet="diaries", data=all_diaries_latest)
                    st.cache_data.clear()

        # --- [신규 작성 모드] ---
        else:
            with st.form("new_diary_form"):
                content = st.text_area("오늘 하루는 어떠셨나요?", height=250, placeholder="이야기를 털어놓으세요.")
                if st.form_submit_button("기록 저장하고 조언 듣기 ✨", type="primary", use_container_width=True):
                    if check_rate_limit("new_diary", 5):
                        if content:
                            # ⭐ [수정] 멘트 변경
                            with st.spinner("과거의 기억을 되짚으며 분석 중..."):
                                safe_content = sanitize_for_sheets(content)
                                
                                # ⭐ [수정] 1. 과거 기록 가져오기
                                past_history = get_past_diaries_text(current_user_id)
                                
                                # ⭐ [수정] 2. AI에게 과거 기록과 함께 전달
                                full_res = get_ai_response(safe_content, current_name, past_history)
                                
                                if "|||" in full_res: advice, sc = full_res.split("|||"); score=int(sc.strip())
                                else: advice=full_res; score=3
                                
                                all_diaries_latest = conn.read(worksheet="diaries", ttl=0)
                                if all_diaries_latest.empty or 'id' not in all_diaries_latest.columns: new_id = 1
                                else: new_id = int(pd.to_numeric(all_diaries_latest['id'], errors='coerce').max()) + 1
                                
                                new_data = pd.DataFrame([{
                                    "id": new_id, 
                                    "user_id": current_user_id,
                                    "username": current_username,
                                    "date": selected_date_str,
                                    "content": safe_content, "ai_advice": advice.strip(), "emotion_tag": max(1, min(5, score)),
                                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                    "chat_history": "[]"
                                }])
                                updated = pd.concat([all_diaries_latest, new_data], ignore_index=True) if not all_diaries_latest.empty else new_data
                                conn.update(worksheet="diaries", data=updated)
                                st.cache_data.clear()
                                st.rerun()

    # === [메뉴 3] 내 정보 수정 ===
    elif menu == "⚙️ 내 정보 수정":
        st.header("⚙️ 내 정보 수정")
        st.info(f"현재 로그인된 아이디: **{current_username}**")
        
        with st.expander("👤 닉네임 변경", expanded=True):
            with st.form("change_name_form"):
                new_nickname = st.text_input("새로운 닉네임", value=current_name)
                btn_name = st.form_submit_button("닉네임 변경", type="primary")
                
                if btn_name:
                    if check_rate_limit("change_info", 3):
                        safe_name = sanitize_for_sheets(new_nickname)
                        success, msg = update_user_info(current_user_id, new_name=safe_name)
                        if success:
                            st.session_state['user_info']['name'] = safe_name
                            st.cache_data.clear()
                            st.toast(msg, icon="✅")
                            time.sleep(1)
                            st.rerun()
                        else:
                            st.error(msg)
                            
        with st.expander("🔐 비밀번호 변경", expanded=False):
            with st.form("change_pw_form"):
                cur_pw = st.text_input("현재 비밀번호", type="password")
                new_pw = st.text_input("새로운 비밀번호", type="password")
                chk_pw = st.text_input("새로운 비밀번호 확인", type="password")
                btn_pw = st.form_submit_button("비밀번호 변경", type="primary")
                
                if btn_pw:
                    if check_rate_limit("change_pw", 3):
                        user_data = login_check(current_username, cur_pw)
                        
                        if user_data is None:
                            st.error("현재 비밀번호가 일치하지 않습니다.")
                        elif new_pw != chk_pw:
                            st.error("새 비밀번호가 서로 일치하지 않습니다.")
                        elif not new_pw:
                            st.warning("새 비밀번호를 입력해주세요.")
                        else:
                            success, msg = update_user_info(current_user_id, new_password=new_pw)
                            if success:
                                st.cache_data.clear()
                                st.toast(msg, icon="✅")
                            else:
                                st.error(msg)