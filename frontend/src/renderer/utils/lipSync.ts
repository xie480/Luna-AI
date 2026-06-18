/**
 * LipSync 处理器
 *
 * 基于 Web Audio API 实时分析音频流的音量振幅（均方根 RMS），
 * 将其平滑映射到 Live2D 模型的 ParamMouthOpenY 参数，实现高质量口型同步。
 *
 * 核心设计原则：
 * 1. 严格生命周期管理：音频播放时启动更新循环，结束时自动停止并重置嘴部为闭合。
 * 2. 动态音量映射：提取中低频段音频能量，映射到 0.0 ~ 1.0 的张嘴参数。
 * 3. 精准静音阈值检测（Noise Gate）：低于阈值的音量强制归零，避免呼吸/底噪造成嘴巴微颤。
 * 4. 帧间平滑插值（低通滤波）：用上一帧音量与当前帧加权混合，防止口型突变抖动。
 */

export class LipSyncProcessor {
  private audioContext: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private dataArray: Uint8Array | null = null;
  
  // 记录已被连接过的 audioElement 及其对应的 source 节点，防止重复创建报错或泄露
  private sourcesMap: WeakMap<HTMLAudioElement, MediaElementAudioSourceNode> = new WeakMap();
  private currentSource: MediaElementAudioSourceNode | null = null;

  private animationFrameId: number | null = null;
  private isProcessing = false;

  /** 存储最后一次 start() 传入的模型引用，供 stop() 重置嘴部参数使用。 */
  private currentModel: unknown = null;

  /** 上一帧计算出的音量值（0.0 ~ 1.0），用于帧间平滑。 */
  private lastVolume = 0;

  /**
   * 构造 LipSyncProcessor，延迟初始化 AudioContext（直到首次连接时）。
   */
  constructor() {
    // AudioContext 在用户首次交互前可能被浏览器阻止创建，
    // 因此在实际 connect() 时再初始化。
  }

  /**
   * 获取或创建 AudioContext 与分析器节点。
   *
   * 做什么：确保 audioContext 和 analyser 已经创建。
   * 为什么这样做：AudioContext 不能在构造函数中提前创建，
   * 因为浏览器自动播放策略要求它必须在用户手势后创建才能处于 running 状态。
   * 边界条件：无。
   * 异常行为：如果浏览器不支持 AudioContext，将静默失败。
   */
  private ensureAudioContext(): boolean {
    if (this.audioContext && this.analyser && this.dataArray) {
      return true;
    }

    try {
      const AudioContextClass =
        window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (!AudioContextClass) {
        console.warn('[LipSync] 浏览器不支持 AudioContext，口型同步不可用');
        return false;
      }

      this.audioContext = new AudioContextClass();
      this.analyser = this.audioContext.createAnalyser();

      // fftSize = 256 提供 128 个频率块，对人声口型分析足够且计算开销低。
      // smoothingTimeConstant 让 Analyser 自带一次硬件平滑，减少帧间噪声抖动。
      this.analyser.fftSize = 256;
      this.analyser.smoothingTimeConstant = 0.8;

      this.dataArray = new Uint8Array(this.analyser.frequencyBinCount);
      return true;
    } catch (e) {
      console.warn('[LipSync] AudioContext 初始化失败:', e);
      return false;
    }
  }

  /**
   * 将指定的音频元素连接到内部分析节点。
   *
   * 做什么：把 HTMLAudioElement 的音频流接入 AnalyserNode。
   * 为什么这样做：通过 AudioNode 链路才能实时读取音频频域数据。
   * 输入输出：
   *   - 输入：audioElement —— 待播放的 <audio> 元素
   *   - 输出：无（副作用）
   * 边界条件：
   *   - 同一个 audioElement 只能调用一次 createMediaElementSource，
   *     重复调用会抛出 InvalidStateError，此处通过 try-catch 静默兼容。
   *   - 如果 AudioContext 处于 suspended 状态（自动播放策略），尝试 resume。
   * 异常行为：无。
   */
  public connect(audioElement: HTMLAudioElement): void {
    if (!this.ensureAudioContext()) return;
    if (!this.audioContext || !this.analyser) return;

    // 尝试唤醒被浏览器挂起的 AudioContext
    if (this.audioContext.state === 'suspended') {
      this.audioContext.resume().catch((e) => {
        console.warn('[LipSync] AudioContext resume 失败:', e);
      });
    }

    // 如果之前有连接过其他 source 到 analyser，先断开，避免多个音频流混合
    if (this.currentSource) {
      try {
        this.currentSource.disconnect();
      } catch (e) {
        // ignore
      }
    }

    let source = this.sourcesMap.get(audioElement);
    
    if (!source) {
      try {
        source = this.audioContext.createMediaElementSource(audioElement);
        this.sourcesMap.set(audioElement, source);
      } catch (e) {
        console.warn('[LipSync] createMediaElementSource 失败 (可能已被其它 Context 占用):', e);
        return;
      }
    }

    this.currentSource = source;

    if (this.currentSource) {
      try {
        this.currentSource.connect(this.analyser);
        // 必须将 AnalyserNode 连接到 destination，否则音频不会播放出声。
        this.analyser.connect(this.audioContext.destination);
      } catch (e) {
        console.warn('[LipSync] 分析节点连接失败:', e);
      }
    }
  }

  /**
   * 开始驱动 Live2D 模型的口型同步。
   *
   * 做什么：启动 requestAnimationFrame 循环，每帧读取音频频域能量，
   *         经过静音阈值过滤 + 帧间平滑插值后，赋值到模型 ParamMouthOpenY。
   * 为什么这样做：用 rAF 循环驱动，能保证与浏览器渲染帧同步，避免 UI 卡顿。
   * 输入输出：
   *   - 输入：
   *       live2dModel —— Live2D 模型实例（必须包含 internalModel.coreModel）
   *       multiplier —— 音量放大乘数（默认 1.8，声音小时可调大）
   *       smoothing —— 帧间平滑系数（0 ~ 1，越大越平滑但延迟越高，推荐 0.4 ~ 0.6）
   *       noiseGateThreshold —— 噪音门限（0 ~ 1，低于此值的音量视为静音强制闭嘴）
   *   - 输出：无（副作用）
   * 边界条件：
   *   - 如果 live2dModel 无效，直接返回不启动循环。
   *   - 如果已在运行中，先调用 stop() 重置再重新启动。
   * 异常行为：模型参数赋值失败时仅打印警告，不中断循环。
   */
  public start(
    live2dModel: unknown,
    multiplier: number = 1.8,
    smoothing: number = 0.5,
    noiseGateThreshold: number = 0.05,
  ): void {
    // 校验模型有效性
    if (!live2dModel) {
      console.error('[LipSync] start 失败：live2dModel 为空');
      return;
    }

    const model = live2dModel as Record<string, unknown>;
    const internalModel = model.internalModel as Record<string, unknown> | undefined;
    if (!internalModel || !internalModel.coreModel) {
      console.error('[LipSync] start 失败：live2dModel.internalModel.coreModel 不可用');
      return;
    }

    if (!this.analyser || !this.dataArray) {
      console.warn('[LipSync] start 失败：Analyser 未初始化，请先调用 connect()');
      return;
    }

    // 如果已有循环在运行，先清理干净
    if (this.isProcessing) {
      this.stop();
    }

    // 存储模型引用，供 stop() 重置嘴部参数时使用
    this.currentModel = live2dModel;
    this.isProcessing = true;
    this.lastVolume = 0;

    // 缓存 coreModel 引用避免每次解引用开销
    const coreModel = internalModel.coreModel as {
      setParameterValueById?: (id: string, value: number) => void;
    };

    const processFrame = (): void => {
      if (!this.isProcessing || !this.analyser || !this.dataArray) return;

      // ---- 第1步：读取频域数据 ----
      this.dataArray = new Uint8Array(this.analyser.frequencyBinCount);

      // ---- 第2步：提取人声主要频段能量 ----
      // 人声基频约在 85Hz ~ 255Hz，泛音能量集中在较低频率范围。
      // 取前 40% 的频段（低频+中低频），有效避开齿音、咝音等高音高频噪音。
      const vocalRangeEnd = Math.floor(this.dataArray.length * 0.4);
      let sum = 0;
      for (let i = 0; i < vocalRangeEnd; i++) {
        sum += this.dataArray[i];
      }
      const average = sum / vocalRangeEnd;
      let rawVolume = average / 255.0; // 归一化到 0.0 ~ 1.0

      // ---- 第3步：静音阈值过滤（Noise Gate） ----
      // 当音量低于门限时，说明当前处于发音间隙或换气停顿，
      // 必须强制置零，防止底噪造成嘴巴微颤。
      if (rawVolume < noiseGateThreshold) {
        rawVolume = 0;
      }

      // ---- 第4步：帧间平滑插值（低通滤波 / Lerp） ----
      // 使用上一帧音量与当前帧进行加权混合，防止音量跳变导致嘴部抽搐。
      // 公式：current = (last * smoothing) + (raw * (1 - smoothing))
      const currentVolume = this.lastVolume * smoothing + rawVolume * (1 - smoothing);
      this.lastVolume = currentVolume;

      // ---- 第5步：放大并钳位到有效范围 ----
      // 原始音量可能偏小，用 multiplier 放大张嘴幅度。
      // 使用 Math.min 确保不会超过 1.0（Live2D ParamMouthOpenY 通常是 0 ~ 1）。
      const mouthOpenY = Math.min(1.0, currentVolume * multiplier);

      // ---- 第6步：赋值给 Live2D 模型参数 ----
      try {
        if (coreModel.setParameterValueById) {
          coreModel.setParameterValueById('ParamMouthOpenY', mouthOpenY);
        }
      } catch (e) {
        // 模型可能在切换或销毁过程中，不要抛出异常打断主循环
        console.warn('[LipSync] 模型参数赋值失败:', e);
      }

      // ---- 第7步：请求下一帧 ----
      this.animationFrameId = requestAnimationFrame(processFrame);
    };

    processFrame();
  }

  /**
   * 停止口型同步，并强制将模型嘴部参数重置为闭合（0）。
   *
   * 做什么：停止 rAF 循环，重置内部状态，将 Live2D 模型的 ParamMouthOpenY 设为 0。
   * 为什么这样做：音频结束后如果不重置，模型嘴巴会停留在最后的状态，看起来不自然。
   * 输入输出：
   *   - 输入：无（使用内部存储的 currentModel）
   *   - 输出：无（副作用）
   * 边界条件：无论当前是否在运行中，调用 stop() 都是安全的。
   * 异常行为：模型已被销毁时的参数赋值失败会静默忽略。
   */
  public stop(): void {
    this.isProcessing = false;

    // 取消下一帧请求
    if (this.animationFrameId !== null) {
      cancelAnimationFrame(this.animationFrameId);
      this.animationFrameId = null;
    }

    // 重置平滑状态
    this.lastVolume = 0;

    // 将模型嘴部参数强制重置为闭合
    if (this.currentModel) {
      try {
        const model = this.currentModel as Record<string, unknown>;
        const internalModel = model.internalModel as Record<string, unknown> | undefined;
        if (internalModel?.coreModel) {
          const coreModel = internalModel.coreModel as {
            setParameterValueById?: (id: string, value: number) => void;
          };
          if (coreModel.setParameterValueById) {
            coreModel.setParameterValueById('ParamMouthOpenY', 0);
          }
        }
      } catch (e) {
        // 模型可能已被销毁，静默忽略
      }
    }

    this.currentModel = null;
  }

  /**
   * 销毁所有 AudioContext 资源，释放内存。
   *
   * 做什么：停止同步、断开节点、关闭 AudioContext。
   * 为什么这样做：用于组件卸载时的彻底清理。
   * 输入输出：无。
   * 边界条件：可多次调用，幂等。
   * 异常行为：无。
   */
  public destroy(): void {
    this.stop();

    if (this.currentSource) {
      try {
        this.currentSource.disconnect();
      } catch (e) {
        // 忽略
      }
      this.currentSource = null;
    }

    if (this.analyser) {
      try {
        this.analyser.disconnect();
      } catch (e) {
        // 忽略
      }
      this.analyser = null;
    }

    if (this.audioContext) {
      this.audioContext.close().catch(() => {
        // 忽略
      });
      this.audioContext = null;
    }

    this.dataArray = null;
  }
}

/** 全局单例，供整个前端应用复用同一个音频分析链路。 */
export const lipSyncProcessor = new LipSyncProcessor();
