# 性能优化与并发改造方案：Live2D渲染与本地AI模型集成

基于对本项目核心源码（包括 `backend/ai-service/app/main.py`、`backend/ai-service/app/inference/service.py`、`backend/ai-service/app/rag/hybrid_retriever.py` 以及前端 `frontend/src/renderer/components/Live2DView/Live2DView.tsx` 等）的静态分析，本方案针对当前系统存在的**事件循环阻塞**、**内存常驻与单点膨胀**以及**Live2D 算力抢占**等严重内存瓶颈与多模块并发卡顿问题，提供五个核心维度的深度定制化工程级底层改造建议与落地代码。

---

## 维度一：AI 模型推理优化（解决同步阻塞与执行效率）

### 现状痛点
在 `app/inference/service.py` 中，当前直接在 `async def` 异步函数内调用 `_embedding_model.encode(text).tolist()` 和 `_rerank_model.predict(pairs).tolist()`。由于这些基于 PyTorch / SentenceTransformer 的原生操作是纯 CPU 密集型且为同步执行，在 CPU 模式下，单次推理耗时极高（几百毫秒甚至秒级）。这种调用会彻底冻结 FastAPI 所依赖的 asyncio 事件循环，导致其他并发请求（如 SSE 消息推送流、前端 UI 状态轮询）出现严重卡顿和断流。

### 落地改造：异步化与进程池隔离 + 模型量化
1. **进程隔离**：将重度 CPU 计算从主事件循环中剥离，移入独立的 `ProcessPoolExecutor` 进程池。
2. **ONNX 动态量化加速**（强烈建议）：后续彻底弃用原生 `SentenceTransformer` CPU 推理，将模型导出为 `ONNX` 格式并使用 `onnxruntime` 进行 INT8 动态量化推理，能将内存占用降低约 4 倍，同时 CPU 推理速度提升 2~3 倍。

### 代码重构指引 (`app/inference/service.py`)
```python
import asyncio
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Dict, List
from app.logger import logger

# 预先分配独立的进程池，避免每次请求临时创建进程带来的巨大开销
# 建议大小：根据设备核心数动态分配，保留部分核心给主进程和系统
import os
_process_pool = ProcessPoolExecutor(max_workers=max(1, os.cpu_count() // 2 - 1))

def _cpu_bound_embedding(text: str) -> List[float]:
    """隔离在子进程中执行的纯计算函数"""
    from app.main import _embedding_model
    if _embedding_model is None:
        raise RuntimeError("Embedding 模型未就绪")
    # 后续替换为 onnxruntime.InferenceSession 的 run 方法
    return _embedding_model.encode(text).tolist()

def _cpu_bound_rerank(query: str, documents: List[str]) -> List[float]:
    """隔离在子进程中执行的纯计算函数"""
    from app.main import _rerank_model
    if _rerank_model is None:
        raise RuntimeError("Rerank 模型未就绪")
    pairs = [[query, d] for d in documents]
    return _rerank_model.predict(pairs).tolist()

class InferenceService:
    """通用的推理服务接口实现（异步非阻塞版）"""
    async def get_embedding_vector(self, text: str) -> List[float]:
        if not text:
            raise ValueError("需要向量化的文本不能为空")
        
        loop = asyncio.get_running_loop()
        try:
            # 将阻塞调用推入进程池，彻底释放 FastAPI 主线程事件循环
            vec = await loop.run_in_executor(_process_pool, _cpu_bound_embedding, text)
            logger.info(f"Embedding 向量化完成, text_length={len(text)}, vector_dim={len(vec)}")
            return vec
        except Exception as e:
            logger.exception("Embedding 向量化失败")
            raise RuntimeError(f"Embedding 调用失败: {e}")

    async def rerank_documents(self, query: str, documents: List[str]) -> List[Dict[str, Any]]:
        if not query:
            raise ValueError("查询文本不能为空")
        if not documents:
            return []
            
        loop = asyncio.get_running_loop()
        try:
            scores = await loop.run_in_executor(_process_pool, _cpu_bound_rerank, query, documents)
            
            results = [{"index": i, "score": score} for i, score in enumerate(scores)]
            results.sort(key=lambda x: x["score"], reverse=True)
            logger.info(f"Rerank 重排完成 文档数={len(documents)}")
            return results
        except Exception as e:
            logger.exception("Rerank 重排失败")
            raise RuntimeError(f"Rerank 调用失败: {e}")
```

---

## 维度二：系统架构与并发调度（进程级隔离与IPC）

### 现状痛点
系统当前架构中，虽然前端（Electron）和后端（Python AI Service）从物理上实现了分离，但在 Python 侧，**大模型加载、Web 服务路由处理、核心任务状态机控制**被全部揉捏在一个单一的 Uvicorn/FastAPI 主进程中。当大体积的密集计算被触发时，系统的整体响应度被严重拖垮。在 Electron 主进程侧传递数据也存在直接的大块数据串行传递隐患。

### 落地改造
1. **微服务化路由拆分与 Worker 独立**：如果上述进程池（ProcessPoolExecutor）在实际落地中因为 Python 的 `multiprocessing` 上下文问题仍存在限制，建议启动独立的基于 `gRPC` 或 `ZeroMQ` 的本地 Worker 进程专职处理大模型相关计算，主进程仅作为“认知控制面”，通过异步 IPC 通信将任务投递给“计算面”。
2. **IPC 通信开销优化**：对于前端 UI，目前通过 HTTP / SSE 通信符合预期。但在 Electron 主进程和渲染进程之间若后续存在大体积二进制或图像/日志状态的同步，建议通过 `SharedArrayBuffer` 或是原生 Node.js 流直接对写，而非频繁调用 `ipcMain.invoke` 引发底层 V8 JSON 序列化带来的阻塞耗时。

---

## 维度三：内存与生命周期管理策略（按需加载与动态卸载）

### 现状痛点
在 `app/main.py` 中，`load_embedding_model` 和 `load_rerank_model` 会在服务初始化（Lifespan）时强制全量加载。这些模型即使在设备闲置（用户无问答交互、仅挂机状态）时也会长时间占据大量内存（可达 1GB~3GB）。对于主要面向普通桌面用户的个人产品，这导致了毫无意义的系统级内存单点膨胀。

### 落地改造：带 TTL（存活时间）的懒加载与自动卸载器
引入一套智能的生命周期管理器（`ModelManager`）。模型初次使用时进行懒加载（即冷启动），同时挂载后台守护线程定期检测；若超过指定闲置时间未调用，则彻底释放其对象引用，利用 `gc.collect()` 触发垃圾回收，把内存真正归还给操作系统。

### 代码重构指引 (`app/main.py` 片段)
```python
import time
import gc
import threading
from app.logger import logger

class ModelManager:
    """具备超时自动卸载机制的模型生命周期管理器"""
    def __init__(self, model_loader_func, ttl_seconds=600):
        self._loader = model_loader_func
        self._model = None
        self._ttl = ttl_seconds
        self._last_accessed = 0
        self._lock = threading.Lock()
        
        # 启动后台守护线程，用于定期清理超时未使用的内存模型
        self._cleanup_thread = threading.Thread(target=self._auto_unload, daemon=True)
        self._cleanup_thread.start()

    def get_model(self):
        with self._lock:
            self._last_accessed = time.time()
            if self._model is None:
                logger.info(f"触发内存加载 (冷启动): 准备加载模型，请耐心等待...")
                self._model = self._loader()
            return self._model

    def _auto_unload(self):
        while True:
            time.sleep(60) # 每 60 秒扫描一次状态
            with self._lock:
                if self._model is not None and (time.time() - self._last_accessed > self._ttl):
                    logger.info(f"模型已连续闲置超过 {self._ttl} 秒，执行彻底卸载并回收系统内存...")
                    del self._model
                    self._model = None
                    gc.collect() # 强制执行垃圾回收
                    
# 将全局的裸模型加载，替换为基于 TTL 机制的懒加载代理
# 例如，在 app/main.py 中的初始化逻辑替换为：
# embedding_manager = ModelManager(load_embedding_model, ttl_seconds=600)  # 10分钟不用自动卸载
```

---

## 维度四：硬件资源调度（异构计算与 CPU 限流防阻塞）

### 现状痛点
源码中可见强行注入了 `device="cpu"` 参数。当系统处于重负载检索（特别是 BM25 + 向量检索全开时），不仅 Python 的计算核心被打满，连带给系统 GUI 进程和 Electron WebGL 渲染流留下的资源也会被抢占，导致 Live2D 画面撕裂和电脑全局卡顿。

### 落地改造：CPU 算力硬限制边界与异构探测
对于必须运行在 CPU 上的 AI 计算，**必须严格限制底层库衍生出的工作线程数**，为 UI 交互流（Electron/React）保留至少 2-3 个独立的逻辑物理核算力。

### 代码注入点 (在 `app/main.py` 最顶端导入模块前注入)
```python
import os
import torch

# 计算可安全保留的线程数，为 UI 和操作系统的事件循环留出喘息空间（保留 2 线程）
safe_threads = max(1, os.cpu_count() - 2)

# 限制 PyTorch / OpenMP 的底层衍生线程数量，防止其默认的 CPU 抢占策略锁死宿主机
os.environ["OMP_NUM_THREADS"] = str(safe_threads)
os.environ["MKL_NUM_THREADS"] = str(safe_threads)
torch.set_num_threads(safe_threads)

# 如果未来引入 onnxruntime，也必须在 session_options 中设置相同的限流参数
# sess_options.intra_op_num_threads = safe_threads
```
此外，后续应使用 `torch.cuda.is_available()` 动态检测是否存在支持加速的异构单元，平滑将计算分配至 GPU 从而大幅缓解主板 CPU 负载。

---

## 维度五：Live2D 渲染层面的降本增效（动态帧率与休眠控制）

### 现状痛点
查看 `frontend/src/renderer/components/Live2DView/Live2DView.tsx`，Pixi.js 的帧率被静态锁定（`pixiApp.ticker.maxFPS = 60;`），且无论用户当前是否在交互、程序是否处于最小化阶段、亦或 AI 模型当前是否有情绪波动输出，画布都在疯狂执行全屏 `pointermove` 侦听并以 60 FPS 刷新骨骼蒙皮数据。

### 落地改造：动态 FPS (Dynamic FPS) 与非活跃挂起策略
针对 Live2D 引擎引入根据业务意图调整的降频逻辑：
1. **活跃状态** (60 FPS)：当存在用户交互（鼠标移动）或 AI 发出新情绪指令时触发。
2. **待机闲置状态** (15 FPS)：当经过几秒的无交互阶段，并且情绪为 `neutral` 时，自动降至 15 FPS。对于静态陪伴而言，肉眼观感几乎无损，却能释放大量运算。
3. **彻底休眠** (0 FPS)：当程序处于非激活的后台或最小化状态时，通过页面可见性 API （Visibility API）直接切断 `ticker`。

### 代码重构指引 (`Live2DView.tsx` 注入点)
在初始化好 PIXI Application 之后，插入以下用于动态帧频管控的 `useEffect`：

```tsx
  // ---------- 动态渲染挂起与帧率节流策略 ----------
  useEffect(() => {
    if (!app) return;

    let interactionTimeout: NodeJS.Timeout;
    const FPS_ACTIVE = 60;
    const FPS_IDLE = 15;  // 降低到 15 帧在无动画待机时节省大幅资源
    
    // 唤醒逻辑：恢复为 60 FPS，并刷新超时计时器
    const wakeUpRenderer = () => {
      app.ticker.maxFPS = FPS_ACTIVE;
      clearTimeout(interactionTimeout);
      
      interactionTimeout = setTimeout(() => {
        // 只有当没有任何活跃情绪输出且静默超过 5 秒时才进行节流降频
        if (!currentEmotion || currentEmotion === 'neutral') {
          app.ticker.maxFPS = FPS_IDLE;
        }
      }, 5000);
    };

    // 系统可见性侦听：应用在后台（被遮挡或最小化）时，彻底切断渲染引擎
    const handleVisibilityChange = () => {
      if (document.hidden) {
        app.ticker.stop();
        console.log("[Live2D] 应用转入后台，引擎渲染循环已挂起 (Sleep)");
      } else {
        app.ticker.start();
        wakeUpRenderer();
        console.log("[Live2D] 应用激活，渲染循环恢复");
      }
    };
    
    document.addEventListener("visibilitychange", handleVisibilityChange);
    // 监听全局交互以作为唤醒触发器
    window.addEventListener("pointermove", wakeUpRenderer);
    window.addEventListener("pointerdown", wakeUpRenderer);

    // 当情绪状态发生改变，立即唤醒动画渲染以保持流畅
    wakeUpRenderer();

    return () => {
      clearTimeout(interactionTimeout);
      document.removeEventListener("visibilitychange", handleVisibilityChange);
      window.removeEventListener("pointermove", wakeUpRenderer);
      window.removeEventListener("pointerdown", wakeUpRenderer);
    };
  }, [app, currentEmotion]); // 深度绑定当前情绪状态流
```

---

## 总结落地实施优先级
1. **P0 (最优先/见效快)**：在前端 `Live2DView.tsx` 中实施**动态 FPS 休眠与挂起策略**。能在即刻显著改善空闲状态下系统的整机发热和资源争抢问题。
2. **P0 (根本解决卡顿)**：在后端 `service.py` 实施 **ProcessPoolExecutor** 进行 Embedding 和 Rerank 的进程级隔离。消除 Web Socket / SSE 推送因为事件循环阻塞而断联的致命问题。
3. **P1 (优化内存结构)**：在 `main.py` 部署 **ModelManager 懒加载与 TTL 卸载器**，同时通过 `OS` 层限制 PyTorch 线程释放 CPU 吞吐红利。
4. **P2 (长效治理)**：未来考虑通过导出工具，将当前所用大模型切换至支持动态量化的 ONNX 或 C++ 后端部署的推理形式，实现端到端的模型计算加速。