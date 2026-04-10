import os
import json
from pathlib import Path
from typing import Any, Dict, List

import requests
from flask import Flask, jsonify, render_template, request, send_from_directory

BASE_URL = os.getenv("SEEDANCE_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")
API_KEY = os.getenv("ARK_API_KEY", "")

app = Flask(__name__)
app.config["UPLOAD_FOLDER"] = str(Path("uploads"))
Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)


def _headers() -> Dict[str, str]:
    if not API_KEY:
        return {"Content-Type": "application/json"}
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Content-Type": "application/json",
    }


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


def _compose_payload(form: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "model": form.get("model_id", "doubao-seedance-2-0-260128"),
        "content": _build_content(form),
    }

    mapping = {
        "resolution": form.get("resolution", "").strip(),
        "ratio": form.get("ratio", "").strip(),
        "duration": _optional_int(form.get("duration", "")),
        "frames": _optional_int(form.get("frames", "")),
        "seed": _optional_int(form.get("seed", "")),
        "camera_fixed": _optional_bool(form.get("camera_fixed", "")),
        "watermark": _optional_bool(form.get("watermark", "")),
        "generate_audio": _optional_bool(form.get("generate_audio", "")),
        "return_draft": _optional_bool(form.get("return_draft", "")),
        "num_outputs": _optional_int(form.get("num_outputs", "")),
        "webhook_url": form.get("webhook_url", "").strip(),
        "request_id": form.get("request_id", "").strip(),
    }

    for k, v in mapping.items():
        if v not in (None, ""):
            payload[k] = v

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

    return payload


@app.route("/")
def index():
    return render_template("index.html", default_model="doubao-seedance-2-0-260128")


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
    payload = _compose_payload(form)

    if not payload.get("content") and not payload.get("extend_task_id"):
        return jsonify({"error": "至少需要填写文本/图片/视频/音频之一，或填写 extend_task_id。"}), 400

    response = requests.post(
        f"{BASE_URL}/contents/generations/tasks",
        headers=_headers(),
        data=json.dumps(payload),
        timeout=120,
    )
    return jsonify({"status_code": response.status_code, "payload": payload, "result": response.json()})


@app.route("/api/task/<task_id>")
def query_task(task_id: str):
    response = requests.get(
        f"{BASE_URL}/contents/generations/tasks/{task_id}",
        headers=_headers(),
        timeout=120,
    )
    return jsonify({"status_code": response.status_code, "result": response.json()})


@app.route("/api/tasks")
def list_tasks():
    page_size = request.args.get("page_size", "10")
    status = request.args.get("status", "")
    query = f"page_size={page_size}"
    if status:
        query += f"&filter.status={status}"

    response = requests.get(
        f"{BASE_URL}/contents/generations/tasks?{query}",
        headers=_headers(),
        timeout=120,
    )
    return jsonify({"status_code": response.status_code, "result": response.json()})


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
