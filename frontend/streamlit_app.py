"""Minimal chat frontend for the weather-advisory bot.

Run with: streamlit run frontend/streamlit_app.py
"""
import os
import sys
import uuid

import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv()

from app.graph import build_graph, run_turn  # noqa: E402

st.set_page_config(page_title="Weather-Advisory Support Bot", page_icon="⛅")
st.title("⛅ Weather-Advisory Support Bot")
st.caption(
    "Ask about outdoor activity safety (cycling, picnics, walking the dog, travel...). "
    "Every answer is grounded in live Open-Meteo data and a specific written SOP -- "
    "if nothing covers your question, it'll say so instead of guessing."
)

if "graph" not in st.session_state:
    st.session_state.graph = build_graph()
if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "history" not in st.session_state:
    st.session_state.history = []

for role, content in st.session_state.history:
    with st.chat_message(role):
        st.markdown(content)

user_text = st.chat_input("e.g. Is it safe to bike to work today in Bhopal?")
if user_text:
    st.session_state.history.append(("user", user_text))
    with st.chat_message("user"):
        st.markdown(user_text)

    with st.chat_message("assistant"):
        with st.spinner("Checking live weather and matching policy..."):
            try:
                result = run_turn(st.session_state.graph, st.session_state.thread_id, user_text)
                answer = result["final_answer"]
            except Exception as exc:  # noqa: BLE001
                answer = (
                    "Something went wrong on my end while processing that "
                    f"(not a weather-data issue): `{exc}`"
                )
        st.markdown(answer)
    st.session_state.history.append(("assistant", answer))

with st.sidebar:
    st.subheader("Session")
    st.caption(f"thread_id: `{st.session_state.thread_id}`")
    if st.button("New session"):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.history = []
        st.rerun()
    st.divider()
    st.caption(
        "Policies live in `sops.yaml` and are reloaded on every request -- "
        "editing that file changes bot behavior with no code change or restart."
    )
