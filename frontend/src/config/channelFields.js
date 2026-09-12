// 模型通道配置字段元数据（P2-8 拆分：从 ChannelConfigDialog.vue 抽出，降低单文件复杂度）
// 结构：FIELD_SCHEMA[kind][channel] = [{ key, label, type, required, placeholder, ... }]
// kind: llm / image / video；channel: openai / volc_cv / volc_ark / generic_http

export const FIELD_SCHEMA = {
  llm: {
    openai: [
      { key: 'api_url', label: '接口地址 BaseURL', type: 'text', required: true, placeholder: '如 https://api.deepseek.com（无需 /chat/completions）' },
      { key: 'api_key', label: 'API Key', type: 'password', required: true },
      { key: 'model', label: '模型名', type: 'text', required: true, placeholder: '如 deepseek-chat', list: 'llm-models' },
      { key: 'temperature', label: '采样温度（可空）', type: 'text', placeholder: '0~1，留空用默认 0.7' }
    ]
  },
  image: {
    volc_cv: [
      { key: 'access_key', label: 'AccessKey', type: 'password', required: true },
      { key: 'secret_key', label: 'SecretKey', type: 'password', required: true },
      { key: 'req_key', label: '图片模型 req_key（手动填写）', type: 'text', required: true, optionsKey: 'volc_cv', list: 'dl-image-volc_cv', placeholder: '即梦文生图模型，如 jimeng_t2i_v40 / jimeng_high_aes_general_v21_L；可手填最新模型' }
    ],
    volc_ark: [
      { key: 'api_key', label: 'API Key（volc-sk-）', type: 'password', required: true },
      { key: 'model', label: '图片模型（手动填写）', type: 'text', required: true, optionsKey: 'volc_ark', list: 'dl-image-volc_ark', placeholder: '方舟 Seedream 模型，如 doubao-seedream-4-0-250828；可手填最新版本' },
      { key: 'api_url', label: '接口地址（可空用官方）', type: 'text', placeholder: '默认 https://ark.cn-beijing.volces.com/api/v3' }
    ],
    generic_http: [
      { key: 'base_url', label: '服务地址 BaseURL', type: 'text', required: true, placeholder: '只填根地址即可，如 https://api.siliconflow.cn（后端按域名自动识别平台、补全路径）' },
      { key: 'token', label: 'Bearer Token', type: 'password', required: true, placeholder: '第三方平台的 API Key（sk-...）' },
      { key: 'model', label: '图片模型名（手动填写）', type: 'text', required: true, placeholder: '硅基如 Kwai-Kolors/Kolors；按供应商文档填写，可填任意最新模型' },
      { key: 'endpoint', label: '图片生成接口 URL（高级）', type: 'text', advanced: true, placeholder: '留空自动拼；特殊平台才需手填完整 URL' },
      { key: 'size_field', label: '尺寸字段名（高级）', type: 'text', advanced: true, placeholder: '留空自动识别（硅基 image_size、OpenAI 兼容 size）' },
      { key: 'image_field', label: '图生图参考字段名（高级）', type: 'text', advanced: true, placeholder: '留空自动识别，默认 image' },
      { key: 'result_path', label: '结果图片 URL 路径（高级）', type: 'text', advanced: true, placeholder: '留空自动识别（硅基 images[0].url、兼容 data[0].url）' },
      { key: 'extra_fields', label: '附加请求字段 JSON（高级）', type: 'text', advanced: true, placeholder: '如 {"batch_size": 1}，不需要留空' }
    ]
  },
  video: {
    volc_cv: [
      { key: 'access_key', label: 'AccessKey', type: 'password', required: true },
      { key: 'secret_key', label: 'SecretKey', type: 'password', required: true },
      { key: 'req_key', label: '视频模型 req_key（手动填写）', type: 'text', required: true, optionsKey: 'volc_cv', list: 'dl-video-volc_cv', placeholder: '即梦图生视频模型，如 jimeng_i2v_first_v30_1080；可手填最新模型' },
      { key: 'resolution', label: '分辨率', type: 'select', optionsKey: '__resolution__' }
    ],
    volc_ark: [
      { key: 'api_key', label: 'API Key（volc-sk-）', type: 'password', required: true },
      { key: 'model', label: '视频模型（手动填写）', type: 'text', required: true, optionsKey: 'volc_ark', list: 'dl-video-volc_ark', placeholder: '方舟 Seedance 模型，如 doubao-seedance-1-0-pro-250528；可手填最新版本' },
      { key: 'resolution', label: '分辨率', type: 'select', optionsKey: '__resolution__' },
      { key: 'ratio', label: '宽高比', type: 'select', optionsKey: '__ratio__' },
      { key: 'generate_audio', label: '原生音频', type: 'switch' },
      { key: 'api_url', label: '接口地址（可空用官方）', type: 'text' }
    ],
    generic_http: [
      { key: 'base_url', label: '服务地址 BaseURL', type: 'text', required: true, placeholder: '只填根地址即可，如 https://api.siliconflow.cn（提交/轮询地址自动补全）' },
      { key: 'token', label: 'Bearer Token', type: 'password', required: true, placeholder: '第三方平台的 API Key（sk-...）' },
      { key: 'model', label: '视频模型名（手动填写）', type: 'text', required: true, placeholder: '硅基图生视频 Wan-AI/Wan2.2-I2V-A14B、文生 Wan-AI/Wan2.2-T2V-A14B' },
      { key: 'submit_url', label: '提交任务 URL（高级）', type: 'text', advanced: true, placeholder: '留空自动拼；特殊平台才手填' },
      { key: 'poll_url', label: '轮询 URL（高级，支持 {task_id}）', type: 'text', advanced: true, placeholder: '留空自动拼' },
      { key: 'poll_method', label: '轮询方式（高级）', type: 'select', advanced: true, options: [{ value: 'get', label: 'GET（默认）' }, { value: 'post', label: 'POST' }] },
      { key: 'poll_body', label: 'POST 轮询请求体 JSON（高级）', type: 'text', advanced: true, placeholder: '留空自动识别；如 {"requestId": "{task_id}"}' },
      { key: 'extra_fields', label: '提交附加字段 JSON（高级）', type: 'text', advanced: true, placeholder: '如 {"image_size": "1280x720"}，不需要留空' },
      { key: 'image_field', label: '参考图字段名（高级）', type: 'text', advanced: true, placeholder: '留空自动识别，默认 image' },
      { key: 'omit_fields', label: '剔除默认字段（高级，逗号分隔）', type: 'text', advanced: true, placeholder: '如 duration（硅基不收该字段，已自动剔除）' },
      { key: 'task_id_path', label: '任务ID路径（高级）', type: 'text', advanced: true, placeholder: '留空自动识别（硅基 requestId）' },
      { key: 'status_path', label: '状态路径（高级）', type: 'text', advanced: true, placeholder: '留空自动识别' },
      { key: 'success_status', label: '成功状态值（高级）', type: 'text', advanced: true, placeholder: '留空自动识别（硅基 Succeed）' },
      { key: 'video_url_path', label: '视频URL路径（高级）', type: 'text', advanced: true, placeholder: '留空自动识别（硅基 results.videos[0].url）' },
      { key: 'native_audio', label: '平台原生带音频（高级）', type: 'text', advanced: true, placeholder: '该平台生成的视频自带音轨填 1/true；留空=默认无音轨，走 TTS 配音' }
    ]
  }
}

// 敏感字段：保存/回显时脱敏（*号），不改则不覆盖
export const SENSITIVE_KEYS = ['api_key', 'access_key', 'secret_key', 'token']

// 通道展示名称（配置弹窗 tab 内使用）
export const KIND_LABELS = [
  { key: 'llm', label: '大模型' },
  { key: 'image', label: '图片' },
  { key: 'video', label: '视频' }
]
