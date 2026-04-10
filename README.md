# seedance-2-0

基于火山方舟 Seedance 文档制作的 **Python + HTML** 示例项目（上传 Token 交互版）。

## 功能

- 前端上传媒体并生成可引用 Token：
  - 图片 `t1...`
  - 视频 `s1...`
  - 音频 `a1...`
  - 参考图片 `rt1...`
  - 参考视频 `rs1...`
  - 首尾帧模式末帧 `l1`
- 提示词支持直接引用 Token，例如：`基于@t1将@s1进行更改`。
- 前端覆盖 Seedance 2.0 常见模式：
  - 文本生视频
  - 首帧图生视频
  - 首尾帧生视频（`last_frame_image_url`）
  - 多模态参考生视频
  - 编辑视频
  - 延长视频（`extend_task_id` -> `task_id`）
- 模式联动：不适用的上传区域自动置灰。
- 默认参数已按你的要求设置：
  - `n=1`
  - `resolution=720p`
  - `ratio=9:16`
  - `duration=15`
  - `fps=24`
  - `watermark=false`
  - `return_draft=false`
  - `camera_fixed=true`
  - `generate_audio=true`
  - `frames` 留空（默认）
- API Key 在浏览器内临时填写，后端不保存。

## 运行

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python app.py
```

访问：<http://127.0.0.1:5543>

## 说明

- 后端会把上传媒体转为 data URL 写入请求（避免“本地上传后外网不可访问”导致无法调用 API 的问题）。
- 如官方后续更新参数，可继续通过 `advanced_json` 透传。
