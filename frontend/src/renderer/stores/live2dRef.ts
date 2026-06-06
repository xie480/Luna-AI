/**
 * Live2D 模型引用共享模块
 * 用于在 Live2DView（加载模型）和 ClothingPanel（应用服装配置）之间共享模型实例
 * 注意：这是一个模块级单例引用，不是 Zustand store，因为 PIXI 对象不可序列化
 */

/** 当前加载的 Live2D 模型实例 */
let _model: unknown = null;

/** 所有已注册的表达式名称列表 */
let _expressionNames: string[] = [];

/**
 * 获取当前模型实例
 */
export function getLive2dModel(): unknown {
  return _model;
}

/**
 * 设置模型实例
 */
export function setLive2dModel(model: unknown): void {
  _model = model;
}

/**
 * 获取已注册的表达式名称列表
 */
export function getExpressionNames(): string[] {
  return _expressionNames;
}

/**
 * 设置表达式名称列表
 */
export function setExpressionNames(names: string[]): void {
  _expressionNames = names;
}

/**
 * 清空模型引用
 */
export function clearLive2dModel(): void {
  if (_model) {
    _model = null;
  }
  _expressionNames = [];
}
