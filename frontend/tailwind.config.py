import streamlit as st
import requests
import time

# Настройка страницы (должна быть первой строкой Streamlit)
st.set_page_config(
    page_title="Росатом • MCP 3D/5D",
    page_icon="⚛️",
    layout="wide",
)

# Кастомные стили, чтобы сайт выглядел футуристично под Росатом (темная тема)
st.markdown("""
    <style>
    .main { background-color: #030712; color: #f8fafc; }
    .stTextInput input { background-color: #0f172a; color: #38bdf8; border: 1px solid #1e293b; }
    .stSelectbox select { background-color: #0f172a; color: #38bdf8; }
    </style>
""", unsafe_allow_html=True)

# Инициализация истории чата в сессии Python
if "messages" not in st.session_state:
    st.session_state.messages = [
        {"role": "assistant",
         "content": "Система Росатом MCP готова к работе. Загрузите STL-модель и опишите задачу для 3D/5D печати."}
    ]

# Основной макет: три колонки (как у тебя в задумке)
col_chat, col_viewer, col_fleet = st.columns([1, 1, 1], gap="medium")

# --- ЛЕВАЯ КОЛОНКА: Чат и загрузка ---
with col_chat:
    st.markdown("### 💬 Росатом • MCP Core")

    # Выбор материала
    material = st.selectbox(
        "Материал печати:",
        ["PEEK (Авиакосмический)", "PA12-CF (Углеволокно)", "ABS", "PLA"]
    )

    # Контейнер для чата с фиксированной высотой
    chat_container = st.container(height=400)
    with chat_container:
        for msg in st.session_state.messages:
            if msg["role"] == "user":
                st.markdown(f"👤 **Инженер:** {msg['content']}")
            else:
                st.markdown(f"🤖 **MCP Agent:** {msg['content']}")

    # Загрузка файла
    uploaded_file = st.file_uploader("Загрузить STL модель", type=["stl"])
    if uploaded_file:
        st.success(f"Файл принят: {uploaded_file.name}")

    # Форма ввода сообщения
    with st.form("chat_form", clear_on_submit=True):
        user_input = st.text_input("Введите запрос или требование к прочности...")
        submitted = st.form_submit_button("Пуск 🚀")

        if submitted and (user_input or uploaded_file):
            prompt_text = user_input if user_input else f"Запустить анализ для материала {material}"
            st.session_state.messages.append({"role": "user", "content": prompt_text})

            # Имитация ответа MCP-агента Росатома
            with st.spinner("Агент анализирует геометрию и генерирует 5D G-код..."):
                time.sleep(1.5)
                ai_response = f"✅ Геометрия проверена. Параметры для {material} подобраны. 5D G-код успешно сгенерирован и отправлен на принтер ROS-5D-02."
                st.session_state.messages.append({"role": "assistant", "content": ai_response})
            st.rerun()

# --- ЦЕНТРАЛЬНАЯ КОЛОНКА: 3D Инспектор и G-код ---
with col_viewer:
    st.markdown("### 🧊 3D STL Inspector")

    # Визуализатор-заглушка или информация о файле
    if uploaded_file:
        st.info(f"📁 Модель загружена в буфер памяти: **{uploaded_file.name}**")
        st.markdown("*(Тут отображается предпросмотр геометрии)*")
    else:
        st.warning("⚠️ Ожидание загрузки STL-файла...")

    st.markdown("### 📜 Генерация траектории G-code")
    st.code("""
G28 ; Home all axes
G1 Z15.0 F6000 ; Move Z
M104 S380 ; Set PEEK Extruder
G5 P1 ; Enable 5D kinematics
G1 X50 Y50 A15.0 E10 F1500 ; Print layer 1
    """, language="gcode")

# --- ПРАВАЯ КОЛОНКА: Мониторинг флота принтеров ---
with col_fleet:
    st.markdown("### 🏭 Парк принтеров Росатом")

    # Попытка получить данные с бэкенда Python, если он запущен, иначе демо-данные
    try:
        response = requests.get("http://localhost:8000/api/v1/fleet", timeout=1)
        printers = response.json().get("printers", [])
    except:
        printers = [
            {"id": "ROS-3D-01", "status": "printing", "nozzle_temp": 239.5, "progress": 64},
            {"id": "ROS-5D-02", "status": "idle", "nozzle_temp": 22.0, "progress": 0},
            {"id": "ROS-5D-03", "status": "maintenance", "nozzle_temp": 25.0, "progress": 0}
        ]

    for p in printers:
        status_color = "🟢" if p["status"] == "printing" else ("🟡" if p["status"] == "idle" else "🔴")
        with st.container():
            st.markdown(f"""
            **{status_color} {p['id']}** — *Статус: {p['status']}*
            - Температура сопла: `{p['nozzle_temp']}°C`
            - Прогресс задачи:
            """)
            st.progress(p["progress"] / 100)
            st.divider()