"""本地滚动诊断日志，不记录账户或密钥返回值。"""
import logging,os,faulthandler,atexit
from pathlib import Path
from logging.handlers import RotatingFileHandler
from contextlib import contextmanager


def initialize(root):
    logger=logging.getLogger('ict.stability')
    if not logger.handlers:
        path=Path(root)/'data';path.mkdir(exist_ok=True)
        handler=RotatingFileHandler(path/'stability.log',maxBytes=2_000_000,backupCount=3,encoding='utf-8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(threadName)s %(message)s'))
        logger.addHandler(handler);logger.setLevel(logging.INFO)
        logger.info('服务诊断初始化 pid=%s',os.getpid())
        atexit.register(lambda:logger.info('Python正常退出 pid=%s',os.getpid()))
    return logger

@contextmanager
def panel(name):
    import streamlit as st
    try:yield
    except Exception:
        logging.getLogger('ict.stability').exception('页面模块失败 module=%s',name)
        st.error(name+'暂时不可用；其他区域可继续使用。详细错误已记录至数据诊断日志。')


class SafeStore:
    """只读失败时降级展示，阻止在读取不完整时覆盖用户记录。"""
    def __init__(self,store):
        import threading
        self.store=store;self.failed=set();self.lock=threading.Lock()

    def __getattr__(self,name):
        target=getattr(self.store,name)
        if not callable(target):return target
        def call(*args,**kwargs):
            import streamlit as st
            import pandas as pd
            import copy
            from .store import DEFAULTS
            read=name in {'settings','plans','plan_history','table','acknowledged'} or (name=='note' and len(args)<2 and 'body' not in kwargs)
            if not read:
                with self.lock:blocked=bool(self.failed)
                if blocked:raise ValueError('数据库读取尚未恢复，暂不覆盖任何备注或计划，请稍后重试。')
            try:
                result=target(*args,**kwargs)
                if read:
                    with self.lock:self.failed.discard(name)
                return result
            except Exception:
                logging.getLogger('ict.stability').exception('数据库操作失败 method=%s',name)
                if not read:raise
                with self.lock:self.failed.add(name)
                st.warning('本地数据库读取暂时失败；已保留原始记录，写入暂被保护，请查看诊断日志。')
                return copy.deepcopy(DEFAULTS) if name=='settings' else pd.DataFrame(columns=['symbol','kind']) if name=='table' else set() if name=='acknowledged' else '' if name=='note' else []
        return call
