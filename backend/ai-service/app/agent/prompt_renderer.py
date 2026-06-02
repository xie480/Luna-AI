
from jinja2 import Environment, StrictUndefined, TemplateError

from app.api.communication_pb2 import PromptSlot
from app.logger import logger

class PromptRenderer:
    """
    Jinja2 提示词渲染器
    
    做什么：接收 Go 传来的 PromptSlot 数组和变量字典，使用 Jinja2 逐个渲染槽位。
    为什么这样做：实现 Prompt 的动态装配，消除硬编码。
    """
    def __init__(self):
        self.env = Environment(undefined=StrictUndefined)

    def render_slot(self, slot: PromptSlot, variables: dict[str, str]) -> str | None:
        """
        渲染单个槽位
        """
        try:
            template = self.env.from_string(slot.template_content)
            return template.render(**variables)
        except TemplateError as e:
            logger.error(f"渲染槽位 {slot.slot_name} 失败: {e}")
            if slot.is_required:
                raise ValueError(f"必须的槽位 {slot.slot_name} 渲染失败: {e}")
            else:
                logger.warning(f"跳过非必须槽位 {slot.slot_name}")
                return None

    def render_slots(self, slots: list[PromptSlot], variables: dict[str, str]) -> dict[str, str]:
        """
        渲染所有槽位，返回按 slot_name 组织的字典
        """
        rendered_slots = {}
        for slot in slots:
            rendered = self.render_slot(slot, variables)
            if rendered is not None:
                rendered_slots[slot.slot_name] = rendered
        return rendered_slots

prompt_renderer = PromptRenderer()
