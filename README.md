# seedance-2-0

基于火山方舟 Seedance 文档制作的 **Python + HTML** 示例项目。

## 功能

- 前端上传/下载媒体文件（视频、图片、文本通过表单输入）。
- 覆盖 Seedance 2.0 教程中的常见能力开关：
  - 文本生视频
  - 首帧图生视频
  - 首尾帧生视频
  - 多模态参考生视频
  - 编辑视频
  - 延长视频
- 覆盖输出控制参数：`resolution`、`ratio`、`duration`、`frames`、`seed`、`camera_fixed`、`watermark`、`num_outputs`、`generate_audio`、`return_draft` 等。
- 后端封装常见 API：创建任务、查询任务、查询任务列表。

## 环境变量

- `ARK_API_KEY`：方舟 API Key（必填）
- `SEEDANCE_BASE_URL`：默认 `https://ark.cn-beijing.volces.com/api/v3`

## 启动

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export ARK_API_KEY="你的Key"
python app.py
```

访问：<http://127.0.0.1:8000>

## 说明

本项目根据以下文档整理参数与能力：

- <https://www.volcengine.com/docs/82379/2291680?lang=zh>
- <https://www.volcengine.com/docs/82379/2222480?lang=zh>
- <https://www.volcengine.com/docs/82379/2298881?lang=zh>

由于不同模型版本可用参数存在差异，若参数不兼容，接口可能忽略参数或直接报错，请以控制台实时文档为准。
