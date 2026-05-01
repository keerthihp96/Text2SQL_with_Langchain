import os
import json
import re
from dotenv import load_dotenv

# ── LangChain imports ─────────────────────────────────────────────────────────
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.caches import InMemoryCache
from langchain_core.globals import set_llm_cache
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_groq import ChatGroq
from schema import TABLE_SCHEMA


# ── Memory — try langchain_community first, fall back to langchain_core ───────
try:
    from langchain_community.memory import ConversationBufferMemory
except ImportError:
    try:
        from langchain.memory import ConversationBufferMemory
    except ImportError:
        from langchain_core.chat_history import InMemoryChatMessageHistory
        ConversationBufferMemory = None

load_dotenv()

# ── Feature: Caching ──────────────────────────────────────────────────────────
set_llm_cache(InMemoryCache())


# ── Feature: Callbacks ────────────────────────────────────────────────────────
class SQLCallbackHandler(BaseCallbackHandler):

    def on_llm_start(self, serialized, prompts, **kwargs):
        print("\n📡 LLM Call Started...")

    def on_llm_end(self, response, **kwargs):
        tokens = response.llm_output.get("token_usage", {})
        print(f"✅ LLM Call Completed")
        print(f"   Prompt tokens    : {tokens.get('prompt_tokens', 'N/A')}")
        print(f"   Completion tokens: {tokens.get('completion_tokens', 'N/A')}")
        print(f"   Total tokens     : {tokens.get('total_tokens', 'N/A')}")

    def on_llm_error(self, error, **kwargs):
        print(f"❌ LLM Error: {error}")


callback_handler = SQLCallbackHandler()


# ── Feature: LLM with retries + fallback ─────────────────────────────────────
def get_llm(streaming: bool = False):
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0,
        max_tokens=1024,
        max_retries=3,
        streaming=streaming,
        callbacks=[callback_handler]
    )


def get_llm_with_fallback():
    primary = ChatGroq(
        model="llama-3.3-70b-versatile",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0,
        max_tokens=1024,
        max_retries=3,
        callbacks=[callback_handler]
    )
    fallback = ChatGroq(
        model="mixtral-8x7b-32768",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0,
        max_tokens=1024,
        max_retries=2,
        callbacks=[callback_handler]
    )
    return primary.with_fallbacks([fallback])


# ── Feature: Memory using langchain_core (no external dependency) ─────────────
def create_memory() -> InMemoryChatMessageHistory:
    """Creates fresh chat history — works on all LangChain versions."""
    return InMemoryChatMessageHistory()


# ── LLM Call 1: Natural Language → SQL ───────────────────────────────────────
def generate_sql(
    user_question: str,
    memory: InMemoryChatMessageHistory
) -> dict:

    system_prompt = f"""
You are an expert SQL engineer working with Snowflake databases.
Your ONLY job is to convert user questions into valid Snowflake SQL queries.

{TABLE_SCHEMA}

RESPONSE FORMAT — respond ONLY with this exact JSON:
{{
  "sql": "SELECT ... FROM EMPLOYEES ...",
  "explanation": "One line explaining what this query does"
}}

IMPORTANT:
- Return raw JSON only — no markdown, no code blocks, no extra text
- If the question cannot be answered, return:
  {{"sql": "INVALID", "explanation": "Reason why"}}
"""

    # Build messages list — system + history + current question
    messages = [SystemMessage(content=system_prompt)]

    # Add conversation history from memory
    for msg in memory.messages[-6:]:    # last 6 messages max
        messages.append(msg)

    # Add current question
    messages.append(HumanMessage(content=user_question))

    llm      = get_llm_with_fallback()
    response = llm.invoke(messages)
    raw      = response.content.strip()

    # Parse JSON
    try:
        result = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                result = json.loads(match.group())
            except json.JSONDecodeError:
                result = {
                    "sql":         "INVALID",
                    "explanation": "Failed to parse LLM response"
                }
        else:
            result = {
                "sql":         "INVALID",
                "explanation": "Failed to parse LLM response"
            }

    # Save to memory if valid
    if result.get("sql") != "INVALID":
        memory.add_user_message(user_question)
        memory.add_ai_message(result.get("sql", ""))

    return result


# ── LLM Call 2: Results → Natural Language ────────────────────────────────────
def explain_results(
    user_question: str,
    sql_query: str,
    columns: list,
    rows: list,
    stream: bool = False
):
    if not rows:
        data_str = "The query returned no results."
    else:
        header    = " | ".join(columns)
        separator = "-" * len(header)
        data_rows = "\n".join([
            " | ".join(str(v) for v in row)
            for row in rows[:20]
        ])
        data_str = f"{header}\n{separator}\n{data_rows}"
        if len(rows) > 20:
            data_str += f"\n... and {len(rows) - 20} more rows"

    prompt = f"""
The user asked: "{user_question}"

We ran this SQL:
{sql_query}

Results:
{data_str}

Write a clear, concise natural language answer.
Rules:
- Speak directly to the user
- Be conversational but precise
- Include key numbers and names
- If no results, say so clearly
- Keep it to 2-4 sentences max
"""

    llm      = get_llm(streaming=stream)
    response = llm.invoke([HumanMessage(content=prompt)])
    return response.content.strip()


# ── Feature: SQL Validation ───────────────────────────────────────────────────
def validate_sql(sql: str) -> dict:
    prompt = f"""
You are a Snowflake SQL validator.
Review this SQL query and check for errors:

{sql}

Respond ONLY with this JSON:
{{
  "is_valid": true or false,
  "issues": "describe any issues, or 'none' if valid"
}}
"""
    llm      = get_llm()
    response = llm.invoke([HumanMessage(content=prompt)])
    raw      = response.content.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"is_valid": True, "issues": "none"}


# ── Feature: Suggest Questions ────────────────────────────────────────────────
def suggest_questions() -> list:
    prompt = f"""
Based on this database schema:
{TABLE_SCHEMA}

Suggest 6 interesting questions a business user might ask.
Respond ONLY with a JSON array of strings:
["question 1", "question 2", "question 3", "question 4", "question 5", "question 6"]
"""
    llm      = get_llm()
    response = llm.invoke([HumanMessage(content=prompt)])
    raw      = response.content.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return [
            "Who are the top 5 highest paid employees?",
            "How many employees are in each department?",
            "List all active projects with their budgets",
            "Which employees work on the AI Integration project?",
            "What is the total salary cost per department?",
            "Who manages the Engineering department?"
        ]