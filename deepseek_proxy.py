#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
# deepseek_proxy.py
# Copyright (c) 2025 Mox ZaZa
# Licensed under CC BY-NC-SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/
#
# You may share and adapt this code for non-commercial purposes,
# provided you give appropriate credit and distribute any derivatives
# under the same license.
"""
轻量本地转发器：
- 接受本机 HTTP 请求（默认 127.0.0.1:8080）
- 删除空 "tools": []（请求与响应）
- 扁平化 messages[].content（如果是数组或结构化）
- 转发到 https://api.deepseek.com/... 并把响应返回给客户端

环境配置：
  1. pip install flask requests

使用：
  1. 将 DEEPSEEK_KEY = "YOUR_DEEPSEEK_KEY_HERE" 替换为你自己的 DEEPSEEK_API_KEY
  2. 终端运行：python3 deepseek_proxy.py

可配置项见下方说明
"""
import os
import json
from typing import Any
from flask import Flask, request, Response
import requests
import logging
import time

# ---- 配置 ----
LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = int(os.environ.get("PROXY_PORT", "8080"))     # 可更改监听端口
DEEPSEEK_KEY = "YOUR_DEEPSEEK_KEY_HERE"     # 必填 填入自己的deepseek-api-key
# 目标 upstream（真实 DeepSeek API）
DEEPSEEK_UPSTREAM = os.environ.get("DEEPSEEK_UPSTREAM", "https://api.deepseek.com")
# 是否在响应里也删除空 tools（一般是要的）
CLEAN_RESPONSE_TOOLS = True

# ---- 默认请求参数 ----
DEFAULT_PARAMS = {
    "temperature": 0.7,
    "max_tokens": 1024,
    # 你可以继续添加其他全局参数，比如 top_p, frequency_penalty, presence_penalty 等
}

# 允许的路径前缀转发（只处理 deepseek 的 API 路径，避免误转发）
ALLOWED_PREFIXES = [
    "/v1/chat/completions",
    "/v1/completions",
    "/v1/models",
    "/v1/*"
]

if not DEEPSEEK_KEY:
    raise SystemExit("ERROR: 请先填入 DEEPSEEK_KEY，再运行脚本。比如：DEEPSEEK_KEY='sk-xxx'")

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)


# ---------- JSON 修正工具 ----------
def remove_empty_tools_in_obj(obj: Any) -> bool:
    """
    递归删除对象中出现的空 "tools": [] 条目。
    返回是否做了修改。
    """
    modified = False
    if isinstance(obj, dict):
        # 顶层直接删除
        if "tools" in obj and isinstance(obj["tools"], list) and len(obj["tools"]) == 0:
            del obj["tools"]
            modified = True
        # choices[].message.tools / choices[].tools
        if "choices" in obj and isinstance(obj["choices"], list):
            for choice in obj["choices"]:
                if isinstance(choice, dict):
                    msg = choice.get("message")
                    if isinstance(msg, dict):
                        if "tools" in msg and isinstance(msg["tools"], list) and len(msg["tools"]) == 0:
                            del msg["tools"]
                            choice["message"] = msg
                            modified = True
                    if "tools" in choice and isinstance(choice["tools"], list) and len(choice["tools"]) == 0:
                        del choice["tools"]
                        modified = True
        # 递归检查子项
        for k, v in list(obj.items()):
            if isinstance(v, (dict, list)):
                if remove_empty_tools_in_obj(v):
                    modified = True
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (dict, list)):
                if remove_empty_tools_in_obj(item):
                    modified = True
    return modified


def flatten_message_content_in_messages(obj: Any) -> bool:
    """
    将 obj['messages'] 中每个 message 的 content 扁平化为字符串（如果 content 为数组或复杂结构）。
    返回是否做了修改。
    """
    modified = False
    if not isinstance(obj, dict):
        return False

    messages = obj.get("messages")
    if not isinstance(messages, list):
        return False

    for i, msg in enumerate(messages):
        if not isinstance(msg, dict):
            continue
        content = msg.get("content")
        # content 为 list -> 拼接
        if isinstance(content, list) and len(content) > 0:
            parts = []
            for part in content:
                if isinstance(part, dict):
                    # 优先取 text / content / value 字段
                    if "text" in part and isinstance(part["text"], str):
                        parts.append(part["text"])
                    elif "content" in part and isinstance(part["content"], str):
                        parts.append(part["content"])
                    elif "value" in part and isinstance(part["value"], str):
                        parts.append(part["value"])
                    else:
                        try:
                            parts.append(json.dumps(part, ensure_ascii=False))
                        except TypeError:
                            parts.append(str(part))
                elif isinstance(part, str):
                    parts.append(part)
                else:
                    try:
                        parts.append(json.dumps(part, ensure_ascii=False))
                    except TypeError:
                        parts.append(str(part))
            new_content = "\n".join(p for p in parts if p is not None)
            messages[i]["content"] = new_content
            modified = True
        # content 是 dict，包含 parts/items/segments -> 拼接
        elif isinstance(content, dict):
            for key in ("parts", "items", "segments"):
                if key in content and isinstance(content[key], list) and len(content[key]) > 0:
                    parts = []
                    for part in content[key]:
                        if isinstance(part, dict) and "text" in part and isinstance(part["text"], str):
                            parts.append(part["text"])
                        elif isinstance(part, str):
                            parts.append(part)
                        else:
                            try:
                                parts.append(json.dumps(part, ensure_ascii=False))
                            except TypeError:
                                parts.append(str(part))
                    if parts:
                        messages[i]["content"] = "\n".join(parts)
                        modified = True
                        break

    if modified:
        obj["messages"] = messages
    return modified


# ---------- 代理逻辑 ----------
def should_handle_path(path: str) -> bool:
    # 简单检查 path 是否以某个 allowed prefix 开头
    for p in ALLOWED_PREFIXES:
        if p.endswith("*"):
            base = p[:-1]
            if path.startswith(base):
                return True
        else:
            if path == p or path.startswith(p):
                return True
    return False


@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
def proxy(path):
    # 完整请求路径
    full_path = "/" + path
    logging.info(f"Incoming {request.method} {full_path}")

    # 仅处理深度学习相关路径，避免误转发
    if not should_handle_path(full_path):
        return Response("Not handled by deepseek proxy", status=404)

    # 读取客户端请求体（可能为空）
    req_body = None
    content_type = request.headers.get("Content-Type", "")
    if request.data:
        try:
            if "json" in content_type:
                req_body = request.get_json(force=True)
            else:
                # 尝试解析为 JSON，容错
                try:
                    req_body = json.loads(request.data.decode("utf-8"))
                except TypeError:
                    req_body = None
        except TypeError:
            req_body = None

    modified = False
    # ====== 计时开始：本地请求体处理 ======
    start_local_processing = time.time()
    if isinstance(req_body, (dict, list)):
        # 删除空 tools
        if remove_empty_tools_in_obj(req_body):
            modified = True
        # 扁平化 messages[].content
        if flatten_message_content_in_messages(req_body):
            modified = True
        # 设置默认参数，直接覆盖
        if isinstance(req_body, dict):
            # 合并默认参数，覆盖已有值
            for k, v in DEFAULT_PARAMS.items():
                req_body[k] = v

            # 这句作用是在每次转发时输出请求体，方便测试
            # logging.info(f"Modified request body: {json.dumps(req_body, ensure_ascii=False)}")

    local_processing_time = time.time() - start_local_processing
    # ====== 计时结束：本地请求体处理 ======

    if modified:
        logging.info(f"Request body patched for {full_path}")

    # 转发到真实 upstream
    upstream_url = DEEPSEEK_UPSTREAM.rstrip("/") + full_path
    headers = {}
    # 只复制必要的 header，避免污染（但保留 User-Agent 等）
    for hk, hv in request.headers.items():
        if hk.lower() in ("host", "content-length", "content-encoding"):
            continue
        headers[hk] = hv
    # 强制使用 DEEPSEEK_KEY 做身份验证
    headers["Authorization"] = f"Bearer {DEEPSEEK_KEY}"

    # ====== 计时开始：请求 upstream API ======
    start_upstream = time.time()
    # 发起请求
    try:
        if req_body is not None:
            resp = requests.request(request.method, upstream_url, headers=headers, json=req_body, timeout=60)
        else:
            resp = requests.request(request.method, upstream_url, headers=headers, data=request.get_data(), timeout=60)
    except Exception as e:
        logging.exception("Upstream request failed")
        return Response(f"Upstream request failed: {e}", status=502)
    upstream_time = time.time() - start_upstream
    # ====== 计时结束：请求 upstream API ======

    # ====== 计时开始：本地响应处理 ======
    start_response_processing = time.time()
    # 处理响应 body：删除空 tools（若是 JSON）
    resp_content_type = resp.headers.get("Content-Type", "")
    resp_text = resp.content
    try:
        if (CLEAN_RESPONSE_TOOLS
                and resp_text
                and (
                        (resp_content_type and "json" in resp_content_type.lower())
                        or resp_text.strip().startswith(b"{")
                        or resp_text.strip().startswith(b"[")
                )):
            data = resp.json()
            if remove_empty_tools_in_obj(data):
                logging.info("Removed empty 'tools' from upstream response")
                resp_text = json.dumps(data, ensure_ascii=False).encode("utf-8")
    except TypeError:
        # 忽略解析错误，直接返回原始响应
        pass
    response_processing_time = time.time() - start_response_processing
    # ====== 计时结束：本地响应处理 ======

    # 构造返回给客户端的响应
    excluded_headers = ["content-encoding", "transfer-encoding", "content-length", "connection"]
    response_headers = [(k, v) for k, v in resp.headers.items() if k.lower() not in excluded_headers]
    response = Response(resp_text, status=resp.status_code)
    for k, v in response_headers:
        response.headers[k] = v
    # ====== 总时计算 ======
    total_time = local_processing_time + upstream_time + response_processing_time
    logging.info(f"Request {full_path} processed in {total_time:.3f}s "
                 f"(local={local_processing_time:.3f}s, upstream={upstream_time:.3f}s, response={response_processing_time:.3f}s)")
    return response


if __name__ == "__main__":
    logging.info(f"Starting deepseek proxy on http://{LISTEN_HOST}:{LISTEN_PORT} -> upstream {DEEPSEEK_UPSTREAM}")
    app.run(host=LISTEN_HOST, port=LISTEN_PORT, debug=False)
