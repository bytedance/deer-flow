from markitdown import MarkItDown

md = MarkItDown(enable_plugins=False) # Set to True to enable plugins
result = md.convert("/mnt/afs/yaotiankuo/agents/data/xhx_returnData/小浣熊任务规划用户query+分类.xlsx")
print(result.text_content)