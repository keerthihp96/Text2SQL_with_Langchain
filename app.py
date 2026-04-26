# app.py

import os
import streamlit as st
from dotenv import load_dotenv
from database import execute_query, test_connection
from llm import generate_sql, explain_results

load_dotenv()

# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Text to SQL",
    page_icon="🔍",
    layout="centered"
)

st.title("🔍 Text to SQL AI Assistant")
st.caption("Ask questions about your data in plain English — powered by Groq + Snowflake")


# ── Session State ────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

if "conversation_history" not in st.session_state:
    st.session_state.conversation_history = []


# ── Sidebar ──────────────────────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Settings")

    # Test Snowflake connection
    if st.button("🔌 Test Snowflake Connection"):
        with st.spinner("Connecting..."):
            success, message = test_connection()
        if success:
            st.success(f"✅ {message}")
        else:
            st.error(f"❌ {message}")

    st.divider()

    # Show/hide SQL toggle
    show_sql = st.toggle("🔍 Show SQL Query", value=True)

    # Show/hide raw results toggle
    show_table = st.toggle("📊 Show Raw Results", value=True)

    st.divider()

    # Clear chat
    if st.button("🗑️ Clear Chat"):
        st.session_state.messages = []
        st.session_state.conversation_history = []
        st.rerun()

    st.divider()

    # Example questions
    st.markdown("**💡 Example Questions:**")
    examples = [
        "Who are the top 5 highest paid employees?",
        "How many employees are in each department?",
        "List all active projects with their budgets",
        "Which employees work on the AI Integration project?",
        "What is the total salary cost per department?",
        "Who manages the Engineering department?",
    ]
    for example in examples:
        if st.button(example, use_container_width=True):
            st.session_state.example_question = example
            st.rerun()

    st.divider()
    st.markdown("**🆓 Free Stack:**")
    st.markdown("- LLM: Groq LLaMA 3.3 70B")
    st.markdown("- DB: Snowflake")
    st.markdown("- Framework: LangChain v1")


# ── Render Past Messages ─────────────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

        if msg["role"] == "assistant":
            if show_sql and msg.get("sql") and msg["sql"] != "INVALID":
                with st.expander("🔍 View SQL Query"):
                    st.code(msg["sql"], language="sql")
                    if msg.get("sql_explanation"):
                        st.caption(msg["sql_explanation"])

            if show_table and msg.get("rows") and msg.get("columns"):
                with st.expander(f"📊 Raw Results ({len(msg['rows'])} rows)"):
                    st.dataframe(
                        [dict(zip(msg["columns"], row))
                         for row in msg["rows"]],
                        use_container_width=True
                    )


# ── Handle Example Question Click ────────────────────────────────────────────
if "example_question" in st.session_state:
    user_input = st.session_state.pop("example_question")
else:
    user_input = None


# ── Chat Input ───────────────────────────────────────────────────────────────
typed_input = st.chat_input("Ask anything about your data...")
if typed_input:
    user_input = typed_input

if user_input:

    # Show user message
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.messages.append({
        "role":    "user",
        "content": user_input
    })

    # Process and respond
    with st.chat_message("assistant"):

        # Step 1 — Generate SQL
        with st.spinner("⚡ Generating SQL..."):
            llm_response = generate_sql(
                user_input,
                st.session_state.conversation_history
            )

        sql         = llm_response.get("sql")
        sql_explain = llm_response.get("explanation")

        # Handle invalid questions
        if sql == "INVALID":
            answer = f"❌ {sql_explain}"
            st.error(answer)
            st.session_state.messages.append({
                "role":    "assistant",
                "content": answer,
                "sql":     "INVALID"
            })

        else:
            # Step 2 — Execute SQL
            with st.spinner("🔄 Running query on Snowflake..."):
                columns, rows, error = execute_query(sql)

            # Handle DB errors
            if error:
                answer = f"❌ Database error: {error}"
                st.error(answer)
                st.session_state.messages.append({
                    "role":    "assistant",
                    "content": answer,
                    "sql":     sql
                })

            else:
                # Step 3 — Explain results
                with st.spinner("💬 Generating answer..."):
                    answer = explain_results(
                        user_input, sql, columns, rows
                    )

                st.markdown(answer)

                # Show SQL
                if show_sql:
                    with st.expander("🔍 View SQL Query"):
                        st.code(sql, language="sql")
                        if sql_explain:
                            st.caption(sql_explain)

                # Show raw results table
                if show_table and rows:
                    with st.expander(
                        f"📊 Raw Results ({len(rows)} rows)"
                    ):
                        st.dataframe(
                            [dict(zip(columns, row)) for row in rows],
                            use_container_width=True
                        )

                # Save to conversation history
                st.session_state.conversation_history.append({
                    "question": user_input,
                    "sql":      sql,
                    "answer":   answer
                })

                # Save to display history
                st.session_state.messages.append({
                    "role":        "assistant",
                    "content":     answer,
                    "sql":         sql,
                    "sql_explanation": sql_explain,
                    "columns":     columns,
                    "rows":        rows
                })