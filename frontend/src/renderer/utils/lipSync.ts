/**
 * LipSync 处理器
 * 基于 Web Audio API 实时分析音频流的 RMS（均方根音量），将其映射到 Live2D 的 ParamMouthOpenY 参数
 */

export class LipSyncProcessor {
  private audioContext: AudioContext;
  private analyser: AnalyserNode;
  private dataArray: Uint8Array;
  private source: MediaElementAudioSourceNode | null = null;
  private isProcessing = false;

  constructor() {
    this.audioContext = new (window.AudioContext || (window as any).webkitAudioContext)();
    this.analyser = this.audioContext.createAnalyser();
    this.analyser.fftSize = 256;
    this.dataArray = new Uint8Array(this.analyser.frequencyBinCount);
  }

  connect(audioElement: HTMLAudioElement) {
    // 确保 AudioContext 处于 running 状态 (可能被浏览器自动播放策略挂起)
    if (this.audioContext.state === 'suspended') {
      this.audioContext.resume();
    }
    
    if (this.source) {
      this.source.disconnect();
    }
    
    // 注意：如果是同一个 audioElement，createMediaElementSource 只能调用一次，
    // 所以如果是复用的 audioElement，需要额外处理，这里简化处理，假设每次传入新的
    try {
        this.source = this.audioContext.createMediaElementSource(audioElement);
    } catch (e) {
        // 如果已经创建过，会有 InvalidStateError，这里直接忽略，不影响使用
        console.warn('AudioElement is already connected to an audio context source', e);
    }
    
    if (this.source) {
        this.source.connect(this.analyser);
        this.analyser.connect(this.audioContext.destination);
    }
  }

  start(live2dModel: any, multiplier: number = 1.5, smoothing: number = 0.5) {
    if (!live2dModel || !live2dModel.internalModel || !live2dModel.internalModel.coreModel) {
      console.warn('LipSyncProcessor: invalid live2d model provided');
      return;
    }

    this.isProcessing = true;
    let lastVolume = 0;

    const processFrame = () => {
      if (!this.isProcessing) return;

      this.analyser.getByteFrequencyData(this.dataArray);
      let sum = 0;
      // 提取前 50% 频段能量，避免受极高频噪音干扰
      for (let i = 0; i < this.dataArray.length / 2; i++) {
        sum += this.dataArray[i];
      }
      const average = sum / (this.dataArray.length / 2);
      let volume = average / 255.0; // 0.0 ~ 1.0

      // 低通滤波平滑处理
      volume = (lastVolume * smoothing) + (volume * (1 - smoothing));
      lastVolume = volume;

      const mouthOpen = Math.min(1.0, volume * multiplier);

      // 【关键】强制覆写模型张嘴参数
      try {
        live2dModel.internalModel.coreModel.setParameterValueById('ParamMouthOpenY', mouthOpen);
      } catch (e) {
        // 模型可能被销毁或没有该参数
      }

      requestAnimationFrame(processFrame);
    };

    processFrame();
  }

  stop() {
    this.isProcessing = false;
  }
}

// 导出全局单例供服务使用
export const lipSyncProcessor = new LipSyncProcessor();
