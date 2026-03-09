"""
prompt_builder.py - 构建 LLM 翻译 Prompt
支持基础翻译提示词 + 术语注入
"""

from terminology_manager import load_terminology


BASE_SYSTEM_PROMPT = (
    "You are a professional game translator.\n"
    "Translate the following English game text into Chinese.\n"
    "Keep the translation short and natural, suitable for game UI.\n"
    "CRITICAL RULES:\n"
    "1. ONLY output the translated text. Do NOT add ANY explanations, conversational fillers, or warnings.\n"
    "2. If the text is a URL, random characters, or symbols (e.g. '0.', '+Δ.', 'H9O'), just output it exactly as is if it cannot be meaningfully translated.\n"
    "3. NEVER apologize or state that you cannot access external links. Just translate or return the original text.\n"
    "4. Do NOT wrap the translation in quotes."
)


def build_prompt(text: str) -> tuple[str, str]:
    """
    构建翻译 Prompt。

    :param text: 待翻译的英文文本
    :return: (system_prompt, user_message)
    """
    terms = load_terminology()

    system_prompt = BASE_SYSTEM_PROMPT

    if terms:
        # 注入术语表
        term_lines = "\n".join(f"  {en} → {zh}" for en, zh in terms.items())
        system_prompt += (
            f"\n\nPlease follow these terminology rules:\n{term_lines}"
        )

    return system_prompt, text
