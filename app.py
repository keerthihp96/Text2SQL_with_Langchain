# app.py

import os
import streamlit as st
from dotenv import load_dotenv
from database import execute_query, test_connection
from langchain_core.chat_history import InMemoryChatMessageHistory

from llm import (
    generate_sql,
    explain_results,
    validate_sql,
    suggest_questions,
    create_memory
)

load_dotenv()

# ── Page Config ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Text to SQL",
    page_icon="🔍",
    layout="centered"
)

st.title("🔍 Text to SQL AI Assistant")
st.caption("Powered by Groq LLaMA 3.3 + LangChain v1 + Snowflake")


# ── Session State ────────────────────────────────────────────────────────────
if "messages" not in st.session_state:
    st.session_state.messages = []

if "memory" not in st.session_state:
    # Feature: LangChain conversation memory
    st.session_state.memory = create_memory()

if "suggested_questions" not in st.session_state:
    # Feature: Cached LLM suggestions
    with st.spinner("💡 Loading suggestions..."):
        st.session_state.suggested_questions = suggest_questions()


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

    # Feature toggles
    show_sql      = st.toggle("🔍 Show SQL Query",      value=True)
    show_table    = st.toggle("📊 Show Raw Results",     value=True)
    show_validate = st.toggle("✅ Validate SQL",         value=True)
    enable_stream = st.toggle("⚡ Stream Response",      value=True)

    st.divider()

    # Clear chat + memory
    if st.button("🗑️ Clear Chat + Memory"):
        st.session_state.messages = []
        st.session_state.memory   = create_memory()  # reset memory
        st.rerun()

    st.divider()

    # AI suggested questions (cached)
    st.markdown("**💡 Suggested Questions:**")
    for question in st.session_state.suggested_questions:
        if st.button(question, use_container_width=True):
            st.session_state.example_question = question
            st.rerun()

    st.divider()
    st.markdown("**🚀 Features Active:**")
    st.markdown("- ✅ Conversation Memory")
    st.markdown("- ✅ Auto Retry on Rate Limit")
    st.markdown("- ✅ LLM Fallback Model")
    st.markdown("- ✅ Response Caching")
    st.markdown("- ✅ Callback Logging")
    st.markdown("- ✅ SQL Validation")
    st.markdown("- ✅ Streaming Responses")


# ── Render Past Messages ─────────────────────────────────────────────────────
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

        if msg["role"] == "assistant":
            if show_sql and msg.get("sql") and msg["sql"] != "INVALID":
                with st.expander("🔍 SQL Query"):
                    st.code(msg["sql"], language="sql")
                    if msg.get("sql_explanation"):
                        st.caption(msg["sql_explanation"])
                    if msg.get("validation"):
                        v = msg["validation"]
                        if v.get("is_valid"):
                            st.success("✅ SQL validated successfully")
                        else:
                            st.warning(f"⚠️ {v.get('issues')}")

            if show_table and msg.get("rows") and msg.get("columns"):
                with st.expander(
                    f"📊 Raw Results ({len(msg['rows'])} rows)"
                ):
                    st.dataframe(
                        [dict(zip(msg["columns"], row))
                         for row in msg["rows"]],
                        use_container_width=True
                    )


# ── Handle Example Question ───────────────────────────────────────────────────
user_input = st.session_state.pop("example_question", None)
typed      = st.chat_input("Ask anything about your data...")
if typed:
    user_input = typed

# ── Main Pipeline ─────────────────────────────────────────────────────────────
if user_input:

    # Show user message
    with st.chat_message("user"):
        st.markdown(user_input)
    st.session_state.messages.append({
        "role":    "user",
        "content": user_input
    })

    with st.chat_message("assistant"):

        # ── Step 1: Generate SQL (with memory) ───────────────────────────────
        with st.spinner("⚡ Generating SQL..."):
            llm_response = generate_sql(
                user_input,
                st.session_state.memory     # ← LangChain memory passed in
            )

        sql         = llm_response.get("sql")
        sql_explain = llm_response.get("explanation")

        # Handle invalid question
        if sql == "INVALID":
            answer = f"❌ {sql_explain}"
            st.error(answer)
            st.session_state.messages.append({
                "role":    "assistant",
                "content": answer,
                "sql":     "INVALID"
            })

        else:
            # ── Step 2: Validate SQL ──────────────────────────────────────────
            validation = None
            if show_validate:
                with st.spinner("✅ Validating SQL..."):
                    validation = validate_sql(sql)

                if not validation.get("is_valid"):
                    st.warning(f"⚠️ SQL Issue: {validation.get('issues')}")

            # ── Step 3: Execute SQL ───────────────────────────────────────────
            with st.spinner("🔄 Running on Snowflake..."):
                columns, rows, error = execute_query(sql)

            # Handle DB error
            if error:
                answer = f"❌ Database error: {error}"
                st.error(answer)
                st.session_state.messages.append({
                    "role":    "assistant",
                    "content": answer,
                    "sql":     sql
                })

            else:
                # ── Step 4: Stream or normal response ────────────────────────
                if enable_stream:
                    # Feature: Streaming — show response word by word
                    answer_placeholder = st.empty()
                    full_answer        = ""

                    llm_stream = explain_results(
                        user_input, sql, columns, rows,
                        stream=True
                    )

                    # Stream each chunk
                    for chunk in llm_stream:
                        if hasattr(chunk, "content"):
                            full_answer += chunk.content
                            answer_placeholder.markdown(
                                full_answer + "▌"   # typing cursor
                            )

                    # Final answer without cursor
                    answer_placeholder.markdown(full_answer)
                    answer = full_answer

                else:
                    # Normal response
                    with st.spinner("💬 Generating answer..."):
                        answer = explain_results(
                            user_input, sql, columns, rows,
                            stream=False
                        )
                    st.markdown(answer)

                # Show SQL
                if show_sql:
                    with st.expander("🔍 SQL Query"):
                        st.code(sql, language="sql")
                        if sql_explain:
                            st.caption(sql_explain)
                        if validation:
                            if validation.get("is_valid"):
                                st.success("✅ SQL validated")
                            else:
                                st.warning(
                                    f"⚠️ {validation.get('issues')}"
                                )

                # Show results table
                if show_table and rows:
                    with st.expander(
                        f"📊 Raw Results ({len(rows)} rows)"
                    ):
                        st.dataframe(
                            [dict(zip(columns, row)) for row in rows],
                            use_container_width=True
                        )

                # Save to display history
                st.session_state.messages.append({
                    "role":            "assistant",
                    "content":         answer,
                    "sql":             sql,
                    "sql_explanation": sql_explain,
                    "columns":         columns,
                    "rows":            rows,
                    "validation":      validation
                })