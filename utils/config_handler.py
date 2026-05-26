import yaml
from dotenv import load_dotenv
from utils.path_tool import get_abs_path

# 在首次 import 配置时自动加载项目根目录下的 .env 文件
load_dotenv(dotenv_path=get_abs_path(".env"))


def load_rag_config(config_path: str = get_abs_path("config/rag.yaml"), encoding: str = "utf-8"):
    """读取模型相关配置。"""
    with open(config_path, encoding=encoding) as f:
        return yaml.safe_load(f)

def load_chroma_config(config_path: str = get_abs_path("config/chroma.yaml"), encoding: str = "utf-8"):
    """读取向量库与切块相关配置。"""
    with open(config_path, encoding=encoding) as f:
        return yaml.safe_load(f)

def load_prompts_config(config_path: str = get_abs_path("config/prompt.yaml"), encoding: str = "utf-8"):
    """读取提示词路径配置。"""
    with open(config_path, encoding=encoding) as f:
        return yaml.safe_load(f)

def load_agent_config(config_path: str = get_abs_path("config/agent.yaml"), encoding: str = "utf-8"):
    """读取 Agent 业务配置。"""
    with open(config_path, encoding=encoding) as f:
        return yaml.safe_load(f)

def load_memory_config(config_path: str = get_abs_path("config/memory.yaml"), encoding: str = "utf-8"):
    """读取会话记忆配置。"""
    with open(config_path, encoding=encoding) as f:
        return yaml.safe_load(f)


# 配置在 import 阶段加载成全局对象，便于各模块直接使用。
rag_conf = load_rag_config()
chroma_conf = load_chroma_config()
prompts_conf = load_prompts_config()
agent_conf = load_agent_config()
memory_conf = load_memory_config()
if __name__ == '__main__':
    print(rag_conf['chat_model_name'])
