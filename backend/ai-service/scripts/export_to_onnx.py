"""
Luna AI 性能优化工具：PyTorch 模型转 ONNX 与 INT8 动态量化脚本

做什么：
将 SentenceTransformer (Embedding) 和 CrossEncoder (Rerank) 模型导出为 ONNX 格式，
并执行 INT8 动态量化，以大幅降低推理时的内存占用并提升 CPU 推理速度。

前置准备：
1. 确保已安装必要的依赖：
   pip install torch transformers sentence-transformers onnx onnxruntime optimum[onnxruntime]
2. 确保模型路径正确

使用方法：
直接运行此脚本：
python export_to_onnx.py

运行成功后，会在原模型目录下生成 'onnx/' 文件夹，包含量化后的 model_quantized.onnx 文件。
"""

import os
import shutil
import logging
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def check_dependencies():
    """检查是否安装了必要的库"""
    required_packages = ["torch", "transformers", "onnx", "onnxruntime", "optimum"]
    missing = []
    
    for pkg in required_packages:
        try:
            if pkg == "optimum":
                import optimum.onnxruntime
            else:
                __import__(pkg)
        except ImportError:
            missing.append(pkg)
            
    if missing:
        logger.error(f"缺少必要的依赖库: {', '.join(missing)}")
        logger.error("请运行以下命令安装：\n pip install torch transformers sentence-transformers onnx onnxruntime optimum[onnxruntime]")
        return False
    return True

def export_embedding_model(model_path: str):
    """
    导出 Embedding 模型为 ONNX 并量化
    使用 Hugging Face Optimum 库以最简单的方式完成转换
    """
    logger.info(f"========== 开始处理 Embedding 模型: {model_path} ==========")
    if not os.path.exists(model_path):
        logger.error(f"路径不存在: {model_path}")
        return False
        
    try:
        from optimum.onnxruntime import ORTModelForFeatureExtraction
        from optimum.onnxruntime.configuration import AutoQuantizationConfig
        from optimum.onnxruntime import ORTQuantizer
        from transformers import AutoTokenizer
        
        output_dir = Path(model_path) / "onnx"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # 1. 导出为未量化的 ONNX
        logger.info("步骤 1/3: 正在导出原始 ONNX 模型 (可能需要几分钟)...")
        # ORTModelForFeatureExtraction 自动处理 ONNX 导出
        model = ORTModelForFeatureExtraction.from_pretrained(model_path, export=True, local_files_only=True)
        tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        
        model.save_pretrained(output_dir)
        tokenizer.save_pretrained(output_dir)
        logger.info(f"原始 ONNX 导出成功: {output_dir}")
        
        # 2. INT8 动态量化
        logger.info("步骤 2/3: 正在执行 INT8 动态量化以压缩体积并提速...")
        quantizer = ORTQuantizer.from_pretrained(output_dir)
        # 动态量化配置，针对 CPU 推理优化，移除针对特定硬件的指令集要求
        dqconfig = AutoQuantizationConfig.avx2(is_static=False, per_channel=False)
        
        # 执行量化
        quantizer.quantize(
            save_dir=output_dir,
            quantization_config=dqconfig,
        )
        
        # 3. 清理：为了节省空间，可选择删除未量化的原始 ONNX 文件，只保留量化版
        logger.info("步骤 3/3: 转换完成。")
        logger.info(f"最终的 ONNX 模型和 Tokenizer 位于: {output_dir}")
        logger.info(f"请检查是否存在 'model_quantized.onnx' 文件")
        
        return True
    except Exception as e:
        logger.exception(f"导出 Embedding 模型失败: {e}")
        return False

def export_rerank_model(model_path: str):
    """
    导出 Rerank 模型 (CrossEncoder，本质上是 SequenceClassification)
    """
    logger.info(f"========== 开始处理 Rerank 模型: {model_path} ==========")
    if not os.path.exists(model_path):
        logger.error(f"路径不存在: {model_path}")
        return False
        
    try:
        from optimum.onnxruntime import ORTModelForSequenceClassification
        from optimum.onnxruntime.configuration import AutoQuantizationConfig
        from optimum.onnxruntime import ORTQuantizer
        from transformers import AutoTokenizer
        
        output_dir = Path(model_path) / "onnx"
        output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("步骤 1/3: 正在导出原始 ONNX 模型...")
        model = ORTModelForSequenceClassification.from_pretrained(model_path, export=True, local_files_only=True)
        tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        
        model.save_pretrained(output_dir)
        tokenizer.save_pretrained(output_dir)
        
        logger.info("步骤 2/3: 正在执行 INT8 动态量化...")
        quantizer = ORTQuantizer.from_pretrained(output_dir)
        dqconfig = AutoQuantizationConfig.avx2(is_static=False, per_channel=False)
        
        quantizer.quantize(
            save_dir=output_dir,
            quantization_config=dqconfig,
        )
        
        logger.info("步骤 3/3: 转换完成。")
        logger.info(f"最终模型位于: {output_dir}")
        return True
    except Exception as e:
        logger.exception(f"导出 Rerank 模型失败: {e}")
        return False

if __name__ == "__main__":
    logger.info("Luna AI 模型 ONNX 转换工具启动")
    
    if not check_dependencies():
        exit(1)
        
    # TODO: 请确认这里的路径与您实际的模型路径一致
    # 也可以通过命令行参数传入，这里为了方便直接硬编码
    EMBEDDING_PATH = "D:/AI_Models/bge-base-zh-v1.5-model"
    RERANK_PATH = "D:/AI_Models/bge-reranker-v2-m3"
    
    # 尝试处理 Embedding 模型
    export_embedding_model(EMBEDDING_PATH)
    
    print("\n" + "="*50 + "\n")
    
    # 尝试处理 Rerank 模型
    export_rerank_model(RERANK_PATH)
    
    logger.info("所有导出任务执行完毕！")
    logger.info("转换完成后，我们需要修改 app/inference/service.py 和 app/main.py 来使用 Optimum 加载模型。")
