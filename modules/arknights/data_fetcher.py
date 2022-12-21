#from .. import requester
import requester
import json
import time
import asyncio
from loguru import logger
import lxml.etree
import re

def get_all_operators():
    url = 'https://wiki.biligame.com/arknights/%E5%B9%B2%E5%91%98%E6%95%B0%E6%8D%AE%E8%A1%A8'
    table_xpath = '//*[@id="CardSelectTr"]/tbody/*'
    
    source_code = requester.get_content_bytes(url)
    html = lxml.etree.HTML(source_code)
    table = html.xpath(table_xpath)
    table_head = [item.text.strip() for item in table[0].getchildren()]
    table_head[0] = '头像'
    table_body = []
    for item in table[1:]:
        a = item.getchildren()[0].getchildren()[0].getchildren()[0].getchildren()[0].getchildren()[0]
        if a.getchildren():
            row = [
                ('https://wiki.biligame.com/'+a.attrib['href'],a.getchildren()[0].attrib['src'])
                ]
            row.append()
        else: #网页异常处理
            continue
        table_body.append(row)
    return table_head,table_body
            
            
        
    
        
    
    
