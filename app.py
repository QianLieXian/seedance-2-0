import base64
import json
import mimetypes
import os
import re
import secrets
from pathlib import Path
from typing import Any, Dict, List, Tuple

import requests
from flask import Flask, jsonify, render_template, request, send_from_directory

BASE_URL = os.getenv("SEEDANCE_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = str(Path("uploads"))
Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)

# 依据 Seedance 2.0 文档/教程常见能力配置（2026-04）：
# - 多模态参考：最多 9 图、3 视频、3 音频
# - 示例里常见媒体大小限制约 30MB
MEDIA_LIMITS = {
    "image": {"prefix": "t", "max_count": 9, "max_size_mb": 30, "accept": {"image/png", "image/jpeg", "image/webp"}},
    "video": {"prefix": "s", "max_count": 3, "max_size_mb": 30, "accept": {"video/mp4", "video/webm", "video/quicktime"}},
    "audio": {"prefix": "a", "max_count": 3, "max_size_mb": 30, "accept": {"audio/mpeg", "audio/wav", "audio/mp4", "audio/x-m4a"}},
    "ref_image": {"prefix": "rt", "max_count": 4, "max_size_mb": 30, "accept": {"image/png", "image/jpeg", "image/webp"}},
    "ref_video": {"prefix": "rs", "max_count": 3, "max_size_mb": 30, "accept": {"video/mp4", "video/webm", "video/quicktime"}},
    "last_frame": {"prefix": "l", "max_count": 1, "max_size_mb": 30, "accept": {"image/png", "image/jpeg", "image/webp"}},
}

UPLOAD_REGISTRY: Dict[str, Dict[str, Any]] = {}

BOOL_FIELDS = {
    "camera_fixed",
    "watermark",
    "generate_audio",
    "return_draft",
    "return_last_frame",
}

INT_FIELDS = {
    "duration",
    "frames",
    "seed",
    "n",
    "fps",
}

STRING_FIELDS = {
    "resolution",
    "ratio",
    "webhook_url",
    "request_id",
    "negative_prompt",
    "draft_task_id",
}


def _headers(api_key: str) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _optional_int(value: str, field_name: str) -> Any:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} 必须是整数") from exc


def _optional_bool(value: str) -> Any:
    value = (value or "").strip().lower()
    if not value:
        return None
    return value in {"1", "true", "yes", "on"}


def _parse_advanced_json(raw: str) -> Dict[str, Any]:
    raw = (raw or "").strip()
    if not raw:
        return {}
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise ValueError("advanced_json 必须是 JSON Object")
    return parsed


def _token_sort_key(token: str) -> Tuple[int, str]:
    m = re.search(r"(\d+)$", token)
    n = int(m.group(1)) if m else 10**9
    return n, token


def _build_data_url(file_path: str, mime_type: str) -> str:
    with open(file_path, "rb") as fp:
        data = base64.b64encode(fp.read()).decode("utf-8")
    return f"data:{mime_type};base64,{data}"


def _resolve_uploaded_tokens(form: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
    token_groups = form.get("selected_tokens") or {}
    if not isinstance(token_groups, dict):
        raise ValueError("selected_tokens 必须是对象")

    resolved: Dict[str, List[Dict[str, Any]]] = {}
    for media_type, tokens in token_groups.items():
        if media_type not in MEDIA_LIMITS:
            continue
        if not isinstance(tokens, list):
            raise ValueError(f"{media_type} token 列表格式错误")
        resolved_items: List[Dict[str, Any]] = []
        for token in sorted(set(tokens), key=_token_sort_key):
            item = UPLOAD_REGISTRY.get(token)
            if not item:
                raise ValueError(f"未找到上传资源: {token}")
            if item["media_type"] != media_type:
                raise ValueError(f"资源类型不匹配: {token}")
            resolved_items.append(item)
        limit = MEDIA_LIMITS[media_type]["max_count"]
        if len(resolved_items) > limit:
            raise ValueError(f"{media_type} 最多仅支持 {limit} 个")
        resolved[media_type] = resolved_items

    return resolved


def _build_content(form: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], List[str]]:
    content: List[Dict[str, Any]] = []
    token_notes: List[str] = []

    text = form.get("text_prompt", "").strip()
    if text:
        content.append({"type": "text", "text": text})

    token_assets = _resolve_uploaded_tokens(form)

    def append_with_notes(media_type: str, content_type: str, data_key: str) -> None:
        for item in token_assets.get(media_type, []):
            data_url = _build_data_url(item["file_path"], item["mime_type"])
            content.append({"type": content_type, data_key: {"url": data_url}})
            token_notes.append(f"{item['token']}={item['original_filename']}")

    append_with_notes("image", "image_url", "image_url")
    append_with_notes("video", "video_url", "video_url")
    append_with_notes("audio", "audio_url", "audio_url")
    append_with_notes("ref_image", "image_url", "image_url")
    append_with_notes("ref_video", "video_url", "video_url")

    return content, token_notes


def _compose_payload(form: Dict[str, Any]) -> Dict[str, Any]:
    content, token_notes = _build_content(form)
    text_prompt = (form.get("text_prompt") or "").strip()

    if token_notes and text_prompt:
        content[0]["text"] = f"{text_prompt}\n\n[资源别名映射: {', '.join(token_notes)}]"

    payload: Dict[str, Any] = {
        "model": form.get("model_id", "doubao-seedance-2-0-260128"),
        "content": content,
    }

    for key in STRING_FIELDS:
        value = form.get(key, "").strip()
        if value:
            payload[key] = value

    for key in INT_FIELDS:
        value = _optional_int(form.get(key, ""), key)
        if value is not None:
            payload[key] = value

    legacy_outputs = _optional_int(form.get("num_outputs", ""), "num_outputs")
    if legacy_outputs is not None and "n" not in payload:
        payload["n"] = legacy_outputs

    for key in BOOL_FIELDS:
        value = _optional_bool(form.get(key, ""))
        if value is not None:
            payload[key] = value

    last_frame_tokens = (form.get("selected_tokens") or {}).get("last_frame") or []
    if last_frame_tokens:
        item = UPLOAD_REGISTRY.get(last_frame_tokens[0])
        if item:
            payload["last_frame_image_url"] = _build_data_url(item["file_path"], item["mime_type"])

    extend_task_id = form.get("extend_task_id", "").strip()
    if extend_task_id:
        payload["task_id"] = extend_task_id

    advanced_json = _parse_advanced_json(form.get("advanced_json", ""))
    payload.update(advanced_json)
    return payload


def _safe_json_response(resp: requests.Response) -> Dict[str, Any]:
    try:
        body = resp.json()
    except ValueError:
        body = {"raw": resp.text}
    return {"status_code": resp.status_code, "result": body}


def _detect_mime(file_name: str, fallback: str = "application/octet-stream") -> str:
    guessed, _ = mimetypes.guess_type(file_name)
    return guessed or fallback


@app.route("/")
def index():
    return render_template(
        "index.html",
        default_model="doubao-seedance-2-0-260128",
        models=["doubao-seedance-2-0-260128", "doubao-seedance-2-0-fast-260128"],
        media_limits=MEDIA_LIMITS,
    )


@app.route("/upload-media", methods=["POST"])
def upload_media():
    media_type = (request.form.get("media_type") or "").strip()
    if media_type not in MEDIA_LIMITS:
        return jsonify({"error": "不支持的媒体类型"}), 400

    files = request.files.getlist("files")
    if not files:
        return jsonify({"error": "请选择要上传的文件"}), 400

    limit = MEDIA_LIMITS[media_type]
    if len(files) > limit["max_count"]:
        return jsonify({"error": f"{media_type} 一次最多上传 {limit['max_count']} 个文件"}), 400

    uploaded = []
    for i, file in enumerate(files, start=1):
        if not file or not file.filename:
            continue
        data = file.read()
        size = len(data)
        max_size = limit["max_size_mb"] * 1024 * 1024
        if size > max_size:
            return jsonify({"error": f"{file.filename} 超出 {limit['max_size_mb']}MB 限制"}), 400

        mime_type = _detect_mime(file.filename)
        if mime_type not in limit["accept"]:
            return jsonify({"error": f"{file.filename} 文件类型不支持: {mime_type}"}), 400

        token = f"{limit['prefix']}{i}"
        random_prefix = secrets.token_hex(4)
        save_name = f"{random_prefix}_{file.filename}"
        save_path = Path(app.config["UPLOAD_FOLDER"]) / save_name
        with open(save_path, "wb") as fp:
            fp.write(data)

        UPLOAD_REGISTRY[token] = {
            "token": token,
            "media_type": media_type,
            "file_path": str(save_path),
            "mime_type": mime_type,
            "original_filename": file.filename,
            "download_url": f"/uploads/{save_name}",
        }
        uploaded.append(UPLOAD_REGISTRY[token])

    return jsonify(
        {
            "media_type": media_type,
            "uploaded": uploaded,
            "tips": f"你可以在提示词中使用 @{limit['prefix']}1 等别名，例如：基于@t1将@s1进行更改。",
        }
    )


@app.route("/uploads/<path:filename>")
def download_uploaded_file(filename: str):
    return send_from_directory(app.config["UPLOAD_FOLDER"], filename, as_attachment=True)


@app.route("/api/create-task", methods=["POST"])
def create_task():
    form = request.json or {}
    api_key = (form.get("api_key") or "").strip()

    try:
        payload = _compose_payload(form)
    except (ValueError, json.JSONDecodeError) as exc:
        return jsonify({"error": f"参数错误: {exc}"}), 400

    if not payload.get("content") and not payload.get("task_id"):
        return jsonify({"error": "至少需要填写文本或上传媒体，或填写 extend_task_id。"}), 400

    response = requests.post(
        f"{BASE_URL}/contents/generations/tasks",
        headers=_headers(api_key),
        data=json.dumps(payload),
        timeout=120,
    )
    body = _safe_json_response(response)
    body["payload"] = payload
    return jsonify(body)


@app.route("/api/task/<task_id>", methods=["POST"])
def query_task(task_id: str):
    data = request.json or {}
    api_key = (data.get("api_key") or "").strip()

    response = requests.get(
        f"{BASE_URL}/contents/generations/tasks/{task_id}",
        headers=_headers(api_key),
        timeout=120,
    )
    return jsonify(_safe_json_response(response))


@app.route("/api/task/<task_id>", methods=["DELETE"])
def delete_task(task_id: str):
    data = request.json or {}
    api_key = (data.get("api_key") or "").strip()

    response = requests.delete(
        f"{BASE_URL}/contents/generations/tasks/{task_id}",
        headers=_headers(api_key),
        timeout=120,
    )
    return jsonify(_safe_json_response(response))


@app.route("/api/tasks", methods=["POST"])
def list_tasks():
    data = request.json or {}
    api_key = (data.get("api_key") or "").strip()

    page_size = (data.get("page_size") or "10").strip()
    status = (data.get("status") or "").strip()
    query = f"page_size={page_size}"
    if status:
        query += f"&filter.status={status}"

    response = requests.get(
        f"{BASE_URL}/contents/generations/tasks?{query}",
        headers=_headers(api_key),
        timeout=120,
    )
    return jsonify(_safe_json_response(response))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5543, debug=True)
