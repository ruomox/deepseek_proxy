# deepseek_proxy

这是一个轻量级代理，用于处理本地的 Deepseek API 请求并转发到官方 API。  
最初设计目的是为了解决 Xcode 接入 Deepseek 的问题，  
但该脚本在任何支持 HTTP 请求的环境下都可以使用。  

A lightweight proxy for handling local Deepseek API requests and forwarding them to the official API.   
Originally designed to address Deepseek integration issues in Xcode,  
but this script can also be used in any environment that supports HTTP requests.  

在 Xcode 26 中，直接调用 DeepSeek API 可能会报错：  
"Invalid 'tools': empty array. Expected an array with minimum length 1, but got an empty array instead."  
使用本脚本即可解决此问题。只需在 Xcode 中添加本地模型，并使用脚本中设置的端口即可。  

In Xcode 26, directly accessing the DeepSeek API may trigger the error:  
"Invalid 'tools': empty array. Expected an array with minimum length 1, but got an empty array instead."  
This script resolves the issue. Simply add the local model in Xcode and use the port specified in the script.  

---

## 功能 Features
- 接收本地 HTTP 请求（默认 127.0.0.1:8080）  
- 删除请求与响应中空的 `tools: []`  
- 扁平化 `messages[].content` 为字符串  
- 合并默认请求参数（如 `temperature`, `max_tokens`）  
- 输出日志并计算处理时间
- Accepts local HTTP requests (default 127.0.0.1:8080)  
- Removes empty `tools: []` in requests and responses  
- Flattens `messages[].content` into strings  
- Merges default request parameters (e.g., `temperature`, `max_tokens`)  
- Logs requests and measures processing time  

---

## 使用方法 Usage

1. 安装依赖 / Install dependencies:

```bash
pip install flask requests
```

2. 填入你的 DeepSeek API Key / Replace with your DeepSeek API Key:

```bash
DEEPSEEK_KEY = "YOUR_DEEPSEEK_KEY_HERE"
```

3. 启动代理 / Run the proxy:

```bash
python3 deepseek_proxy.py
```

4. 在本地请求 DeepSeek API，例如 Xcode 或其他 HTTP 客户端 / Access DeepSeek API locally
