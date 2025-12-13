import streamlit as st
from streamlit_gsheets import GSheetsConnection
import pandas as pd
import google.generativeai as genai
from datetime import datetime
import hashlib
import json

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
    div.stButton > button {
        border-radius: 20px;
        background-color: #87CEEB;
        color: white;
        border: none;
        font-weight: bold;
        transition: all 0.3s;
    }
    div.stButton > button:hover {
        background-color: #00BFFF;
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

# --- 2. 로그인 및 설정 ---
if 'is_logged_in' not in st.session_state:
    if "user" in st.query_params and "name" in st.query_params:
        st.session_state['is_logged_in'] = True
        st.session_state['user_info'] = {
            "username": st.query_params["user"],
            "name": st.query_params["name"]
        }
    else:
        st.session_state['is_logged_in'] = False
        st.session_state['user_info'] = None

conn = st.connection("gsheets", type=GSheetsConnection)

try:
    if "GOOGLE_API_KEY" in st.secrets:
        genai.configure(api_key=st.secrets["GOOGLE_API_KEY"])
    else:
        st.error("설정 오류: secrets.toml에 API 키가 없습니다.")
except Exception as e:
    st.error(f"오류: {e}")

# --- 3. 함수 정의 ---

def make_hashes(password):
    return hashlib.sha256(str(password).encode()).hexdigest()

def login_check(username, password):
    try:
        users_df = conn.read(worksheet="users", ttl=0)
        users_df['password'] = users_df['password'].astype(str)
        input_hash = make_hashes(password)
        user_row = users_df[(users_df['username'] == username) & (users_df['password'] == input_hash)]
        if not user_row.empty: return user_row.iloc[0]
        return None
    except Exception: return None

def get_ai_response(user_text):
    """일기 초기 분석용"""
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        prompt = f"""
        당신은 따뜻한 심리 상담가입니다. 아래 일기를 읽고 답변해주세요.
        
        [요청사항]
        1. 공감과 위로, 혹은 칭찬이 담긴 따뜻한 조언 (부드러운 말투로 3문장 이내)
        2. 작성자의 기분을 1~5점 사이의 정수로 평가 (숫자만 출력)
        
        [출력형식]
        조언 내용
        |||
        점수
        
        일기 내용: {user_text}
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI 연결 실패: {e} ||| 3"

def get_chat_response(diary_content, chat_history, new_question):
    """이어지는 대화용"""
    try:
        model = genai.GenerativeModel('gemini-2.5-flash')
        
        history_text = ""
        for chat in chat_history:
            role = "상담사" if chat["role"] == "model" else "내담자"
            history_text += f"{role}: {chat['text']}\n"
            
        prompt = f"""
        당신은 내담자의 일기를 바탕으로 상담을 진행 중인 전문 심리 상담가입니다.
        
        [일기 내용]
        {diary_content}
        
        [이전 대화 기록]
        {history_text}
        
        [내담자의 새로운 질문]
        {new_question}
        
        위 내용을 바탕으로 내담자의 마음에 공감하며 따뜻하게 답변해주세요.
        """
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return "죄송해요, 잠시 연결이 불안정합니다."

# --- 4. 화면 로직 ---

if not st.session_state['is_logged_in']:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        st.title("☁️ 마음의 쉼표")
        st.markdown("##### 당신의 하루를 따뜻하게 기록해드립니다.")
        with st.form("login_form"):
            input_id = st.text_input("아이디")
            input_pw = st.text_input("비밀번호", type="password")
            submitted = st.form_submit_button("로그인", use_container_width=True)
            if submitted:
                user = login_check(input_id, input_pw)
                if user is not None:
                    st.session_state['is_logged_in'] = True
                    st.session_state['user_info'] = user
                    st.query_params["user"] = user['username']
                    st.query_params["name"] = user['name']
                    st.rerun()
                else:
                    st.error("아이디 또는 비밀번호를 확인해주세요.")

else:
    current_user = st.session_state['user_info']['username']
    current_name = st.session_state['user_info']['name']

    with st.sidebar:
        st.title(f"{current_name}님의\n마음 기록 ☁️")
        st.write("")
        menu = st.radio("메뉴 이동", ["📊 대시보드", "🖊️ 일기 쓰기"], index=0)
        st.write("")
        st.markdown("---")
        if st.button("로그아웃", use_container_width=True):
            st.session_state['is_logged_in'] = False
            st.query_params.clear()
            st.rerun()

    # --- 데이터 로드 및 안전한 전처리 (핵심 수정) ---
    try:
        all_diaries = conn.read(worksheet="diaries", ttl=0)
        
        # 1. chat_history 컬럼이 없으면 생성
        if not all_diaries.empty and 'chat_history' not in all_diaries.columns:
            all_diaries['chat_history'] = "[]"
        
        # 2. NaN 값을 빈 리스트 문자열 "[]"로 일괄 채우기 (에러 방지 핵심!)
        if not all_diaries.empty:
            all_diaries['chat_history'] = all_diaries['chat_history'].fillna("[]")
            all_diaries['chat_history'] = all_diaries['chat_history'].astype(str)

        if all_diaries.empty:
            my_data = pd.DataFrame()
        elif 'username' in all_diaries.columns:
            my_data = all_diaries[all_diaries['username'] == current_user].copy()
            my_data['date'] = pd.to_datetime(my_data['date'])
            my_data['emotion_tag'] = pd.to_numeric(my_data['emotion_tag'], errors='coerce')
        else:
            my_data = pd.DataFrame()
    except Exception as e:
        st.error(f"데이터 로드 중 오류: {e}")
        all_diaries = pd.DataFrame()
        my_data = pd.DataFrame()

    # === [메뉴 1] 대시보드 ===
    if menu == "📊 대시보드":
        st.header("📈 내 마음의 날씨 흐름")
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

    # === [메뉴 2] 일기 쓰기 (대화 기능 포함) ===
    elif menu == "🖊️ 일기 쓰기":
        st.header("오늘의 마음 기록하기 🖊️")
        selected_date = st.date_input("날짜를 선택해 주세요", datetime.now())
        selected_date_str = selected_date.strftime("%Y-%m-%d")
        
        current_day_entry = pd.DataFrame()
        if not my_data.empty:
            my_data['date_str_chk'] = my_data['date'].dt.strftime("%Y-%m-%d")
            current_day_entry = my_data[my_data['date_str_chk'] == selected_date_str]

        # --- [상황 A: 일기가 이미 있을 때 (수정 + 채팅 모드)] ---
        if not current_day_entry.empty:
            row = current_day_entry.iloc[0]
            
            # 1. 일기 수정 섹션
            with st.expander("📝 일기 내용 수정하기"):
                with st.form("edit_form"):
                    content = st.text_area("내용", value=row['content'], height=150)
                    if st.form_submit_button("수정 및 재분석 🔄"):
                        with st.spinner("분석 중..."):
                            full_res = get_ai_response(content)
                            if "|||" in full_res: advice, sc = full_res.split("|||"); score=int(sc.strip())
                            else: advice=full_res; score=3
                            
                            all_diaries['id'] = pd.to_numeric(all_diaries['id'], errors='coerce')
                            idx = all_diaries.index[all_diaries['id'] == pd.to_numeric(row['id'], errors='coerce')].tolist()[0]
                            all_diaries.at[idx, 'content'] = content
                            all_diaries.at[idx, 'ai_advice'] = advice.strip()
                            all_diaries.at[idx, 'emotion_tag'] = max(1, min(5, score))
                            all_diaries.at[idx, 'chat_history'] = "[]" # 수정 시 채팅 초기화
                            
                            conn.update(worksheet="diaries", data=all_diaries)
                            st.cache_data.clear()
                            st.rerun()

            st.markdown(f"""<div class="advice-box">{row['ai_advice']}</div>""", unsafe_allow_html=True)
            score_val = int(row['emotion_tag'])
            st.info(f"오늘의 마음 날씨: **{MOOD_EMOJIS.get(score_val, '')}**")

            # --- 💬 2. AI 상담 채팅 기능 ---
            st.markdown("---")
            st.subheader("💬 AI 선생님과 대화하기")
            
            # (0) 채팅 기록 안전하게 불러오기 (에러 수정됨)
            chat_history = []
            raw_history = str(row['chat_history'])
            
            # "nan", "None", "" 등 비정상적인 값 처리
            if raw_history in ['nan', 'None', '', 'NaN']:
                chat_history = []
            else:
                try:
                    chat_history = json.loads(raw_history)
                    if not isinstance(chat_history, list): # 리스트가 아니면 초기화
                        chat_history = []
                except:
                    chat_history = []
            
            # (1) 대화 초기화 버튼 (요청하신 기능)
            col_clear, col_dummy = st.columns([1, 4])
            with col_clear:
                if st.button("🗑️ 대화 내용 지우기"):
                    all_diaries['id'] = pd.to_numeric(all_diaries['id'], errors='coerce')
                    target_idx = all_diaries.index[all_diaries['id'] == pd.to_numeric(row['id'], errors='coerce')].tolist()[0]
                    all_diaries.at[target_idx, 'chat_history'] = "[]"
                    conn.update(worksheet="diaries", data=all_diaries)
                    st.cache_data.clear()
                    st.rerun()

            # (2) 이전 대화 화면 표시
            for chat in chat_history:
                with st.chat_message(chat["role"]):
                    st.write(chat["text"])

            # (3) 사용자 입력 처리
            if user_input := st.chat_input("하고 싶은 말을 적어보세요..."):
                with st.chat_message("user"):
                    st.write(user_input)
                
                chat_history.append({"role": "user", "text": user_input})

                with st.spinner("답변 작성 중..."):
                    ai_reply = get_chat_response(row['content'], chat_history, user_input)
                
                with st.chat_message("model"):
                    st.write(ai_reply)
                
                chat_history.append({"role": "model", "text": ai_reply})

                # DB 업데이트
                updated_history_json = json.dumps(chat_history, ensure_ascii=False)
                all_diaries['id'] = pd.to_numeric(all_diaries['id'], errors='coerce')
                target_idx = all_diaries.index[all_diaries['id'] == pd.to_numeric(row['id'], errors='coerce')].tolist()[0]
                all_diaries.at[target_idx, 'chat_history'] = updated_history_json
                
                conn.update(worksheet="diaries", data=all_diaries)
                st.cache_data.clear()

        # --- [상황 B: 신규 작성 모드] ---
        else:
            with st.form("new_diary_form"):
                content = st.text_area("오늘 하루는 어떠셨나요?", height=250, placeholder="이야기를 털어놓으세요.")
                if st.form_submit_button("기록 저장하고 조언 듣기 ✨", use_container_width=True):
                    if content:
                        with st.spinner("분석 중..."):
                            full_res = get_ai_response(content)
                            if "|||" in full_res: advice, sc = full_res.split("|||"); score=int(sc.strip())
                            else: advice=full_res; score=3
                            
                            if all_diaries.empty or 'id' not in all_diaries.columns: new_id = 1
                            else: new_id = int(pd.to_numeric(all_diaries['id'], errors='coerce').max()) + 1
                            
                            new_data = pd.DataFrame([{
                                "id": new_id, "username": current_user, "date": selected_date_str,
                                "content": content, "ai_advice": advice.strip(), "emotion_tag": max(1, min(5, score)),
                                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                                "chat_history": "[]"
                            }])
                            updated = pd.concat([all_diaries, new_data], ignore_index=True) if not all_diaries.empty else new_data
                            conn.update(worksheet="diaries", data=updated)
                            st.cache_data.clear()
                            st.rerun()