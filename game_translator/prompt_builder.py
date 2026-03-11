"""
prompt_builder.py - 构建 LLM 翻译 Prompt
支持基础翻译提示词 + 术语注入
"""

from terminology_manager import load_terminology


BASE_SYSTEM_PROMPT = (
    "You are a professional game translator.\n"
    "Translate the following game text into {target_lang}.\n"
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
    terms, background_info = load_terminology()

    import config
    system_prompt = BASE_SYSTEM_PROMPT.format(target_lang=config.TARGET_LANG)
    
    if background_info:
        system_prompt += f"\n\nCONTEXT / GAME BACKGROUND:\n{background_info}"

    if terms:
        # 注入术语表
        term_lines = []
        for en, data in terms.items():
            line = f"  {en} → {data['translation']}"
            if data.get("context"):
                line += f" (Condition/Context: {data['context']})"
            term_lines.append(line)
        
        system_prompt += (
            f"\n\nPlease follow these terminology rules strictly (pay attention to context if provided):\n" + "\n".join(term_lines)
        )

    return system_prompt, text


def build_batch_prompt(texts: list[str]) -> tuple[str, str]:
    """
    构建批量翻译 Prompt。
    使用 JSON 格式确保输出与输入对应。

    :param texts: 待翻译的原文列表
    :return: (system_prompt, user_message)
    """
    terms, background_info = load_terminology()

    import config
    system_prompt = (
        f"You are a professional game translator translating to {config.TARGET_LANG}.\n"
        "Keep translations short and natural for game UI.\n"
        "CRITICAL RULES:\n"
        "1. ONLY output the translated text within the requested JSON format.\n"
        "2. If an item cannot be translated (URL/symbols), return the original.\n"
        "3. Provide the translations as a JSON array of strings in the EXACT same order as input.\n"
        "Example output format: [\"Translation 1\", \"Translation 2\"]\n"
    )

    if background_info:
        system_prompt += f"\nCONTEXT / GAME BACKGROUND:\n{background_info}"

    if terms:
        term_lines = [f"  {en} → {data['translation']}" for en, data in terms.items()]
        system_prompt += "\nTerminology rules (follow strictly):\n" + "\n".join(term_lines)

    user_message = "Translate the following strings and return a JSON array:\n" + "\n".join(
        [f"{i+1}. {t}" for i, t in enumerate(texts)]
    )

    return system_prompt, user_message
