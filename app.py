import json
import os
from pathlib import Path
from typing import Any, Dict, List

import requests
from flask import Flask, jsonify, render_template, request, send_from_directory

BASE_URL = os.getenv("SEEDANCE_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = str(Path("uploads"))
Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)


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


def _split_lines(text: str) -> List[str]:
    return [x.strip() for x in (text or "").splitlines() if x.strip()]


def _build_content(form: Dict[str, Any]) -> List[Dict[str, Any]]:
    content: List[Dict[str, Any]] = []

    text = form.get("text_prompt", "").strip()
    if text:
        content.append({"type": "text", "text": text})

    for image_url in _split_lines(form.get("image_urls", "")):
        content.append({"type": "image_url", "image_url": {"url": image_url}})

    for video_url in _split_lines(form.get("video_urls", "")):
        content.append({"type": "video_url", "video_url": {"url": video_url}})

    for audio_url in _split_lines(form.get("audio_urls", "")):
        content.append({"type": "audio_url", "audio_url": {"url": audio_url}})

    # 教程中的“参考图/参考视频”本质上也是多模态内容输入，统一追加到 content。
    for image_url in _split_lines(form.get("reference_images", "")):
        content.append({"type": "image_url", "image_url": {"url": image_url}})

    for video_url in _split_lines(form.get("reference_videos", "")):
        content.append({"type": "video_url", "video_url": {"url": video_url}})

    return content


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


def _compose_payload(form: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": form.get("model_id", "doubao-seedance-2-0-260128"),
        "content": _build_content(form),
    }

    for key in STRING_FIELDS:
        value = form.get(key, "").strip()
        if value:
            payload[key] = value

    for key in INT_FIELDS:
        value = _optional_int(form.get(key, ""), key)
        if value is not None:
            payload[key] = value

    # 兼容旧字段名
    legacy_outputs = _optional_int(form.get("num_outputs", ""), "num_outputs")
    if legacy_outputs is not None and "n" not in payload:
        payload["n"] = legacy_outputs

    for key in BOOL_FIELDS:
        value = _optional_bool(form.get(key, ""))
        if value is not None:
            payload[key] = value

    # 首尾帧模式支持：教程中字段名为 last_frame_image_url。
    end_frame_url = form.get("end_frame_url", "").strip()
    if end_frame_url:
        payload["last_frame_image_url"] = end_frame_url

    # 延长视频：填写上一个任务 ID。
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


@app.route("/")
def index():
    return render_template(
        "index.html",
        default_model="doubao-seedance-2-0-260128",
        models=["doubao-seedance-2-0-260128", "doubao-seedance-2-0-fast-260128"],
    )


@app.route("/upload", methods=["POST"])
def upload_file():
    if "file" not in request.files:
        return jsonify({"error": "No file part"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No selected file"}), 400

    save_path = Path(app.config["UPLOAD_FOLDER"]) / file.filename
    file.save(save_path)
    return jsonify(
        {
            "filename": file.filename,
            "download_url": f"/uploads/{file.filename}",
            "note": "如需提交给 Seedance API，请先将该文件上传到公网 URL（或对象存储），再填入下方 URL 输入框。",
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
        return jsonify({"error": "至少需要填写文本/图片/视频/音频之一，或填写 extend_task_id。"}), 400

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
