"""
Luna AI 提示词模板管理器模块

做什么：集中管理系统中的所有 .j2 模板文件，提供加载、缓存和渲染能力。
        支持 Jinja2（优先）和纯文本替换（回退）两种模式。
为什么这样做：将所有提示词模板外部化为 .j2 文件，实现模板与代码的彻底解耦，
         方便非开发人员修改提示词内容。符合 agent.md 中禁止硬编码魔法字符串的规范。
输入输出：
    - TemplateManager: 单例类，提供 render() 方法加载并渲染模板
    - get_template_manager(): 获取单例实例的工厂函数
边界条件：
    - Jinja2 库可用时使用 Jinja2 渲染引擎，否则使用正则替换回退
    - 模板文件修改后可通过 invalidate_cache() 手动刷新缓存
    - 模板目录不存在时使用空字符串回退，不阻止系统启动
异常行为：
    - 模板文件不存在时记录警告并返回空字符串
    - 模板渲染失败时记录错误并返回原始模板内容（带未替换的占位符）
"""

import re
from pathlib import Path
from typing import Any, Optional

from app.logger import logger

# ============================================================
# 模板目录路径
# ============================================================

# 当前文件所在目录 → app/templates/prompt/（存放所有 .j2 提示词模板文件）
_TEMPLATES_DIR: Path = Path(__file__).resolve().parent / "prompt"

# ============================================================
# Jinja2 可选导入
# ============================================================

try:
    from jinja2 import Environment, FileSystemLoader, TemplateNotFound, UndefinedError

    _HAS_JINJA2: bool = True
except ImportError:
    _HAS_JINJA2: bool = False
    logger.warning(
        "Jinja2 库未安装，使用正则替换回退模式渲染模板。"
        "建议安装：pip install jinja2"
    )

# ============================================================
# 模板缓存
# ============================================================

# 全局模板缓存，key=模板名（不含.j2后缀），value=原始模板内容
_TEMPLATE_CACHE: dict[str, str] = {}


# ============================================================
# 回退渲染器（无 Jinja2 时的简单实现）
# ============================================================

# 匹配 {{ VARIABLE_NAME }} 或 {{ VARIABLE_NAME }} 格式的占位符
_PLACEHOLDER_PATTERN: re.Pattern = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _render_fallback(template_content: str, **kwargs: Any) -> str:
    """
    使用正则替换实现简单的模板渲染（无需 Jinja2）

    做什么：将模板中的 {{ KEY }} 替换为 kwargs 中对应的值。
    输入输出：
        - 输入：template_content 模板内容，kwargs 变量键值对
        - 输出：渲染后的文本
    边界条件：未提供对应值的占位符保留原样。
    """
    def _replace_match(match: re.Match) -> str:
        key = match.group(1)
        value = kwargs.get(key)
        if value is None:
            logger.warning(f"模板占位符 '{{{key}}}' 未找到对应参数，保留原样")
            return match.group(0)
        return str(value)

    return _PLACEHOLDER_PATTERN.sub(_replace_match, template_content)


# ============================================================
# TemplateManager 类
# ============================================================

class TemplateManager:
    """
    提示词模板管理器（单例模式）

    做什么：负责加载、缓存和渲染 templates/ 目录下的 .j2 模板文件。
    为什么这样做：集中管理所有提示词模板，实现代码与内容的分离。

    用法示例：
        tm = get_template_manager()
        # 加载无变量的模板
        system_prompt = tm.render("system")
        # 加载带变量的模板（runtime.j2 仅需要 CURRENT_MESSAGE）
        runtime_prompt = tm.render("runtime", CURRENT_MESSAGE="你好")
    """

    _instance: Optional["TemplateManager"] = None

    def __new__(cls) -> "TemplateManager":
        """单例模式：全局只创建一个实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        """初始化模板管理器（仅执行一次）"""
        if self._initialized:
            return
        self._initialized = True

        # 模板目录
        self._templates_dir: Path = _TEMPLATES_DIR

        # Jinja2 环境（如果可用）
        self._jinja2_env: Any = None
        if _HAS_JINJA2:
            self._jinja2_env = Environment(
                loader=FileSystemLoader(str(self._templates_dir)),
                autoescape=False,  # 提示词模板不需要转义
                trim_blocks=True,
                lstrip_blocks=True,
            )

        # 确保模板目录存在
        if not self._templates_dir.exists():
            logger.warning(
                f"模板目录不存在: {self._templates_dir}，请创建该目录并放入 .j2 模板文件"
            )
            self._templates_dir.mkdir(parents=True, exist_ok=True)

        # 记录可用模板列表
        self._available_templates: list[str] = self._scan_templates()
        logger.info(
            f"TemplateManager 初始化完成，"
            f"模板目录: {self._templates_dir}, "
            f"可用模板数: {len(self._available_templates)}, "
            f"渲染引擎: {'Jinja2' if _HAS_JINJA2 else 'Fallback Regex'}"
        )

    # ----------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------

    def _scan_templates(self) -> list[str]:
        """扫描模板目录，返回所有 .j2 文件的文件名（不含后缀）"""
        if not self._templates_dir.exists():
            return []
        return sorted([
            f.stem  # 去掉 .j2 后缀
            for f in self._templates_dir.iterdir()
            if f.is_file() and f.suffix == ".j2"
        ])

    def _load_template(self, name: str) -> str:
        """
        从文件系统加载模板内容

        做什么：读取 .j2 文件内容，返回原始字符串。
        输入输出：
            - 输入：name 模板名称（不含 .j2 后缀）
            - 输出：模板原始内容
        边界条件：文件不存在时返回空字符串。
        """
        # 检查缓存
        if name in _TEMPLATE_CACHE:
            return _TEMPLATE_CACHE[name]

        # 从文件加载
        template_path: Path = self._templates_dir / f"{name}.j2"
        if not template_path.exists():
            logger.error(f"模板文件不存在: {template_path}")
            return ""

        try:
            content: str = template_path.read_text(encoding="utf-8")
            # 写入缓存
            _TEMPLATE_CACHE[name] = content
            logger.debug(f"加载模板: {name}.j2 ({len(content)} 字符)")
            return content
        except Exception as e:
            logger.error(f"读取模板文件失败 {template_path}: {e}")
            return ""

    # ----------------------------------------------------------
    # 公共方法
    # ----------------------------------------------------------

    def render(self, name: str, **kwargs: Any) -> str:
        """
        渲染指定名称的模板

        做什么：加载并渲染模板，返回最终字符串。
        输入输出：
            - 输入：name 模板名称，kwargs 模板变量
            - 输出：渲染后的字符串
        边界条件：
            - 变量不足时：Jinja2 模式抛出 UndefinedError 并回退
            - 文件不存在时返回空字符串
        异常行为：渲染失败时记录错误并返回原始模板内容（带未替换的占位符）。

        用法：
            # 无变量模板
            system = tm.render("system")

            # 带变量模板（runtime.j2 仅需要 CURRENT_MESSAGE）
            runtime = tm.render("runtime", CURRENT_MESSAGE="你好")
        """
        # Jinja2 模式
        if _HAS_JINJA2 and self._jinja2_env is not None:
            try:
                template = self._jinja2_env.get_template(f"{name}.j2")
                return template.render(**kwargs)
            except TemplateNotFound:
                logger.error(f"Jinja2 找不到模板: {name}.j2")
                return ""
            except UndefinedError as e:
                logger.error(f"Jinja2 渲染模板 '{name}' 时缺少变量: {e}")
                # 回退到非 Jinja2 模式
                raw = self._load_template(name)
                return _render_fallback(raw, **kwargs)
            except Exception as e:
                logger.error(f"Jinja2 渲染模板 '{name}' 失败: {e}")
                return self._load_template(name)

        # 回退模式（纯文本替换）
        raw = self._load_template(name)
        if not raw:
            return ""
        return _render_fallback(raw, **kwargs)

    def list_templates(self) -> list[str]:
        """返回所有可用模板的名称列表"""
        return self._available_templates.copy()

    def invalidate_cache(self, name: str | None = None) -> None:
        """
        清除模板缓存

        做什么：清除指定模板或全部模板的缓存，下次 render 时重新从文件加载。
        输入输出：
            - 输入：name 可选，指定模板名称；为 None 时清除全部缓存
        边界条件：无。
        """
        if name:
            _TEMPLATE_CACHE.pop(name, None)
            logger.info(f"已清除模板缓存: {name}")
        else:
            _TEMPLATE_CACHE.clear()
            self._available_templates = self._scan_templates()
            logger.info("已清除全部模板缓存")

    @property
    def templates_dir(self) -> Path:
        """模板目录路径"""
        return self._templates_dir

    @property
    def has_jinja2(self) -> bool:
        """是否使用 Jinja2 引擎"""
        return _HAS_JINJA2


# ============================================================
# 工厂函数
# ============================================================

# 全局单例
_template_manager_instance: TemplateManager | None = None


def get_template_manager() -> TemplateManager:
    """
    获取 TemplateManager 单例实例

    做什么：返回全局唯一的 TemplateManager 实例。
    为什么这样做：避免多次初始化 Jinja2 环境和重复扫描模板目录。
    输入输出：
        - 输出：TemplateManager 实例
    """
    global _template_manager_instance
    if _template_manager_instance is None:
        _template_manager_instance = TemplateManager()
    return _template_manager_instance
