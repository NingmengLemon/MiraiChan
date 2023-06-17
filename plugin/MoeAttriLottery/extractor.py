import random
import time
import json
import os
#from loguru import logging
import logging

moe_attrs_path = './data/moe_attrs.json'
#moe_attrs_path = './test.json'
# 阅读更多：萌属性（https://zh.moegirl.org.cn/%E8%90%8C%E5%B1%9E%E6%80%A7 ）
# 本文引自萌娘百科(https://zh.moegirl.org.cn )，文字内容默认使用《知识共享 署名-非商业性使用-相同方式共享 3.0 中国大陆》协议。
moe_attrs = {}
detailed_moe_attrs = {}
def load_attrs(path=moe_attrs_path):
    global moe_attrs
    global detailed_moe_attrs
    if os.path.exists(path):
        data = json.load(open(path,'r',encoding='utf-8',errors='ignore'))
        moe_attrs = data['moe_attrs']
        if 'detailed_moe_attrs' in data:
            detailed_moe_attrs = data['detailed_moe_attrs']
        else:
            detailed_moe_attrs = {}
        logging.debug('MoeAttrs Data File loaded from '+path)
    else:
        raise RuntimeError('MoeAttrs Data File not found.')
load_attrs()

# https://www.jb51.net/article/268877.htm
def random_with_weight(data_dict):
    sum_wt = sum(data_dict.values())     # 计算权重和 sum_wt 
    ra_wt = random.uniform(0, sum_wt)    # 随机获取 0-sum_wt 之间的一个浮点数 ra_wt 
    cur_wt = 0
    for key in data_dict.keys():
        cur_wt += data_dict[key]        # 遍历并累加当前权重值
        if ra_wt <= cur_wt:             # 当随机数 <= 当前权重和时，返回权重对应的key
            return key

def generate():
    res = {}
    for attr_type in moe_attrs.keys():
        res[attr_type] = random_with_weight(moe_attrs[attr_type])
    for attr_type in detailed_moe_attrs.keys():
        for req_attr in detailed_moe_attrs[attr_type].keys():
            if req_attr in res.values():
                res[attr_type] = random_with_weight(detailed_moe_attrs[attr_type][req_attr])
    res["time"] = time.time()
    return res
