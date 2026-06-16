"""TTS 情绪映射模块。"""

# 将外部情绪标签映射到服务端实际支持的 emotion 名称
# 每种情绪直接映射到自身首字母大写的单词，不再归类分组
EMOTION_MAP = {
    "annoyed": "Annoyed",
    "irritated": "Irritated",
    "angry": "Angry",
    "sad": "Sad",
    "lonely": "Lonely",
    "despair": "Despair",
    "broken": "Broken",
    "uneasy": "Uneasy",
    "anxious": "Anxious",
    "fearful": "Fearful",
    "shocked": "Shocked",
    "confused": "Confused",
    "flustered": "Flustered",
    "frustrated": "Frustrated",
    "disappointed": "Disappointed",
    "embarrassed": "Embarrassed",
    "tired": "Tired",
    "bored": "Bored",
    "soft": "Soft",
    "smile": "Smile",
    "affectionate": "Affectionate",
    "shy": "Shy",
    "grateful": "Grateful",
    "relieved": "Relieved",
    "hopeful": "Hopeful",
    "proud": "Proud",
    "determined": "Determined",
    "solemn": "Solemn",
    "resigned": "Resigned",
    "clingy": "Clingy",
    "teasing": "Teasing",
    "tsundere": "Tsundere",
    "yandere": "Yandere",
}

def map_emotion(emotion: str, default: str = "default") -> str:
    """归一化情绪标签。

    将外部情绪标签映射到服务端实际支持的 emotion 名称。
    若 emotion 为空或不在映射表中，返回 default。

    参数：
        emotion: 外部情绪标签（不区分大小写）
        default: 默认情绪值

    返回：
        首字母大写的情绪名称
    """
    if not emotion:
        return default
    return EMOTION_MAP.get(emotion.lower(), default)
