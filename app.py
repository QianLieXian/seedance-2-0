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
}

INT_FIELDS = {
    "duration",
    "frames",
    "seed",
    "num_outputs",
    "fps",
}

STRING_FIELDS = {
    "resolution",
    "ratio",
    "webhook_url",
    "request_id",
    "negative_prompt",
}


def _headers(api_key: str) -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return headers


def _build_content(form: Dict[str, Any]) -> List[Dict[str, Any]]:
    content: List[Dict[str, Any]] = []

    text = form.get("text_prompt", "").strip()
    if text:
        content.append({"type": "text", "text": text})

    image_urls = [x.strip() for x in form.get("image_urls", "").splitlines() if x.strip()]
    for image_url in image_urls:
        content.append({"type": "image_url", "image_url": {"url": image_url}})

    video_urls = [x.strip() for x in form.get("video_urls", "").splitlines() if x.strip()]
    for video_url in video_urls:
        content.append({"type": "video_url", "video_url": {"url": video_url}})

    audio_urls = [x.strip() for x in form.get("audio_urls", "").splitlines() if x.strip()]
    for audio_url in audio_urls:
        content.append({"type": "audio_url", "audio_url": {"url": audio_url}})

    return content


def _optional_int(value: str) -> Any:
    value = (value or "").strip()
    if not value:
        return None
    return int(value)


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
        value = _optional_int(form.get(key, ""))
        if value is not None:
            payload[key] = value

    for key in BOOL_FIELDS:
        value = _optional_bool(form.get(key, ""))
        if value is not None:
            payload[key] = value

    reference_images = [x.strip() for x in form.get("reference_images", "").splitlines() if x.strip()]
    if reference_images:
        payload["reference_images"] = [{"url": u} for u in reference_images]

    reference_videos = [x.strip() for x in form.get("reference_videos", "").splitlines() if x.strip()]
    if reference_videos:
        payload["reference_videos"] = [{"url": u} for u in reference_videos]

    end_frame_url = form.get("end_frame_url", "").strip()
    if end_frame_url:
        payload["end_frame_url"] = end_frame_url

    extend_task_id = form.get("extend_task_id", "").strip()
    if extend_task_id:
        payload["extend_task_id"] = extend_task_id

    advanced_json = _parse_advanced_json(form.get("advanced_json", ""))
    payload.update(advanced_json)

    return payload


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

    if not payload.get("content") and not payload.get("extend_task_id"):
        return jsonify({"error": "至少需要填写文本/图片/视频/音频之一，或填写 extend_task_id。"}), 400

    response = requests.post(
        f"{BASE_URL}/contents/generations/tasks",
        headers=_headers(api_key),
        data=json.dumps(payload),
        timeout=120,
    )
    return jsonify({"status_code": response.status_code, "payload": payload, "result": response.json()})


@app.route("/api/task/<task_id>", methods=["POST"])
def query_task(task_id: str):
    data = request.json or {}
    api_key = (data.get("api_key") or "").strip()

    response = requests.get(
        f"{BASE_URL}/contents/generations/tasks/{task_id}",
        headers=_headers(api_key),
        timeout=120,
    )
    return jsonify({"status_code": response.status_code, "result": response.json()})


@app.route("/api/tasks", methods=["POST"])
def list_tasks():
    data = request.json or {}
    api_key = (data.get("api_key") or "").strip()

    page_size = data.get("page_size", "10")
    status = data.get("status", "")
    query = f"page_size={page_size}"
    if status:
        query += f"&filter.status={status}"

    response = requests.get(
        f"{BASE_URL}/contents/generations/tasks?{query}",
        headers=_headers(api_key),
        timeout=120,
    )
    return jsonify({"status_code": response.status_code, "result": response.json()})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5543, debug=True)
