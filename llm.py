# llm.py

import os
import json
import re
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, SystemMessage
from schema import TABLE_SCHEMA

load_dotenv()

# ── Initialize Groq LLM ──────────────────────────────────────────────────────
def get_llm():
    return ChatGroq(
        model="llama-3.3-70b-versatile",
        groq_api_key=os.getenv("GROQ_API_KEY"),
        temperature=0,        # 0 = most deterministic for SQL generation
        max_tokens=1024
    )


# ── LLM Call 1: Natural Language → SQL ──────────────────────────────────────
def generate_sql(user_question: str, conversation_history: list) -> dict:
    """
    Converts plain English question into Snowflake SQL.
    Returns: { "sql": "...", "explanation": "..." }
    """

    system_prompt = f"""
You are an expert SQL engineer working with Snowflake databases.
Your ONLY job is to convert user questions into valid Snowflake SQL queries.

{TABLE_SCHEMA}

RESPONSE FORMAT — respond ONLY with this exact JSON structure, nothing else:
{{
  "sql": "SELECT ... FROM EMPLOYEES ...",
  "explanation": "One line explaining what this query does"
}}

IMPORTANT:
- Return raw JSON only — no markdown, no code blocks, no extra text
- If the question cannot be answered with the available tables, return:
  {{"sql": "INVALID", "explanation": "Reason why the question cannot be answered"}}
"""

    # Build messages with conversation history
    messages = [SystemMessage(content=system_prompt)]

    # Add last 6 turns of history for follow-up support
    for turn in conversation_history[-6:]:
        messages.append(HumanMessage(content=turn["question"]))
        messages.append(SystemMessage(content=turn["sql"]))

    # Add current question
    messages.append(HumanMessage(content=user_question))

    llm      = get_llm()
    response = llm.invoke(messages)
    raw      = response.content.strip()

    # Parse JSON response
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r'\{.*\}', raw, re.DOTALL)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass
        return {"sql": "INVALID", "explanation": "Failed to parse LLM response"}


# ── LLM Call 2: Raw Results → Natural Language ───────────────────────────────
def explain_results(
    user_question: str,
    sql_query: str,
    columns: list,
    rows: list
) -> str:
    """
    Converts raw Snowflake results into a natural language answer.
    """

    # Format results for LLM
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

We ran this SQL query:
{sql_query}

The database returned:
{data_str}

Write a clear, concise natural language answer based on these results.
Rules:
- Speak directly to the user
- Be conversational but precise  
- Include key numbers and names from results
- If no results, say so clearly
- Keep it to 2-4 sentences max
"""

    llm      = get_llm()
    response = llm.invoke([HumanMessage(content=prompt)])
    return response.content.strip()