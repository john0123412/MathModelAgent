"""变量快照模块，支持内核变量的保存与恢复。"""

import os
import pickle
import logging
from typing import Any

logger = logging.getLogger(__name__)


class VariableSnapshot:
    """Jupyter 内核变量快照管理器。
    
    支持：
    - 保存内核变量到磁盘
    - 从磁盘恢复变量
    - 检测快照是否存在
    """
    
    def __init__(self, work_dir: str):
        """初始化快照管理器。
        
        Args:
            work_dir: 任务工作目录
        """
        self.work_dir = work_dir
        self.snapshot_path = os.path.join(work_dir, "variable_snapshot.pkl")
        self.meta_path = os.path.join(work_dir, "variable_snapshot_meta.json")
    
    async def save(self, kernel_client) -> bool:
        """保存内核变量到磁盘。
        
        Args:
            kernel_client: Jupyter 内核客户端
            
        Returns:
            是否保存成功
        """
        try:
            # 获取内核中的所有用户变量
            code = """
import pickle
import sys

# 获取所有用户定义的变量（排除内置和私有变量）
user_vars = {}
for name, obj in list(globals().items()):
    if name.startswith('_'):
        continue
    if callable(obj) and not hasattr(obj, '__call__'):
        continue
    # 跳过模块和类
    if hasattr(obj, '__module__') and obj.__module__ != '__main__':
        continue
    try:
        # 测试是否可序列化
        pickle.dumps(obj)
        user_vars[name] = obj
    except (pickle.PicklingError, TypeError, AttributeError, RecursionError):
        # 不可序列化的变量跳过
        pass

# 保存到临时文件
with open('/tmp/variable_snapshot.pkl', 'wb') as f:
    pickle.dump(user_vars, f)

print(f'SNAPSHOT_COUNT:{len(user_vars)}')
"""
            # 执行代码
            msg_id = kernel_client.execute(code)
            
            # 等待执行完成
            while True:
                msg = kernel_client.get_iopub_msg(timeout=30)
                msg_type = msg.get('msg_type', '')
                content = msg.get('content', {})
                
                if msg_type == 'stream':
                    text = content.get('text', '')
                    if 'SNAPSHOT_COUNT:' in text:
                        count = int(text.split(':')[1])
                        logger.info(f"变量快照: 捕获 {count} 个变量")
                        break
                elif msg_type == 'error':
                    logger.error(f"变量快照保存失败: {content.get('ename', 'unknown')}")
                    return False
            
            # 从容器复制快照文件
            # 注意：这里需要通过代码执行来读取文件内容
            read_code = """
import base64
with open('/tmp/variable_snapshot.pkl', 'rb') as f:
    data = f.read()
print('SNAPSHOT_DATA:' + base64.b64encode(data).decode())
"""
            msg_id = kernel_client.execute(read_code)
            
            snapshot_data = None
            while True:
                msg = kernel_client.get_iopub_msg(timeout=30)
                msg_type = msg.get('msg_type', '')
                content = msg.get('content', {})
                
                if msg_type == 'stream':
                    text = content.get('text', '')
                    if 'SNAPSHOT_DATA:' in text:
                        b64_data = text.split(':', 1)[1].strip()
                        snapshot_data = base64.b64decode(b64_data)
                        break
                elif msg_type == 'error':
                    logger.error(f"读取快照数据失败")
                    return False
            
            if snapshot_data:
                with open(self.snapshot_path, 'wb') as f:
                    f.write(snapshot_data)
                logger.info(f"变量快照已保存: {self.snapshot_path}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"变量快照保存异常: {e}")
            return False
    
    async def load(self, kernel_client) -> bool:
        """从磁盘恢复变量到内核。
        
        Args:
            kernel_client: Jupyter 内核客户端
            
        Returns:
            是否恢复成功
        """
        if not os.path.exists(self.snapshot_path):
            logger.info("未找到变量快照文件")
            return False
        
        try:
            # 读取快照文件
            with open(self.snapshot_path, 'rb') as f:
                snapshot_data = f.read()
            
            import base64
            b64_data = base64.b64encode(snapshot_data).decode()
            
            # 通过代码恢复变量
            code = f"""
import pickle
import base64

# 从 base64 数据恢复
data = base64.b64decode('{b64_data}')
variables = pickle.loads(data)
globals().update(variables)
print(f'RESTORED_COUNT:{len(variables)}')
"""
            msg_id = kernel_client.execute(code)
            
            # 等待执行完成
            while True:
                msg = kernel_client.get_iopub_msg(timeout=60)
                msg_type = msg.get('msg_type', '')
                content = msg.get('content', {})
                
                if msg_type == 'stream':
                    text = content.get('text', '')
                    if 'RESTORED_COUNT:' in text:
                        count = int(text.split(':')[1])
                        logger.info(f"变量快照已恢复: {count} 个变量")
                        return True
                elif msg_type == 'error':
                    logger.error(f"变量快照恢复失败: {content.get('ename', 'unknown')}")
                    return False
            
        except Exception as e:
            logger.error(f"变量快照恢复异常: {e}")
            return False
    
    def exists(self) -> bool:
        """检查快照文件是否存在。"""
        return os.path.exists(self.snapshot_path)
    
    def delete(self) -> bool:
        """删除快照文件。"""
        try:
            if os.path.exists(self.snapshot_path):
                os.remove(self.snapshot_path)
            if os.path.exists(self.meta_path):
                os.remove(self.meta_path)
            logger.info("变量快照已删除")
            return True
        except Exception as e:
            logger.error(f"删除快照失败: {e}")
            return False
    
    def get_size(self) -> int:
        """获取快照文件大小（字节）。"""
        if os.path.exists(self.snapshot_path):
            return os.path.getsize(self.snapshot_path)
        return 0
