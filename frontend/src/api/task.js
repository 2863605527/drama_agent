import request from './request'

// JSON 类接口
export const taskApi = {
  submit: (user_prompt, style = 'anime') =>
    request.post('/api/task/submit', { user_prompt, style }),
  // 在指定一集后续写下一集（继承已有角色/场景资产）
  createEpisode: (parent_id, user_prompt, style = null) =>
    request.post(`/api/task/${parent_id}/episode`, { user_prompt, style }),
  list: () => request.get('/api/task/list'),
  detail: (id) => request.get(`/api/task/${id}`),
  review: (task_id, accept, modify_characters = null) =>
    request.post('/api/task/review', { task_id, accept, modify_characters }),
  // 图片/视频重绘是同步出图，第三方可能较慢，超时放宽到 5 分钟（全局默认 2 分钟会误取消）
  regenerate: (task_id, target_type, target_id) =>
    request.post(`/api/task/${task_id}/regenerate`, { task_id, target_type, target_id }, { timeout: 300000 }),
  clearImage: (task_id, target_type, target_id) =>
    request.post(`/api/task/${task_id}/clear_image`, { task_id, target_type, target_id }, { timeout: 60000 }),
  updateCharacter: (task_id, char_id, name, description) =>
    request.post(`/api/task/${task_id}/update_character`, { task_id, char_id, name, description }),
  updateScene: (task_id, scene_key, description) =>
    request.post(`/api/task/${task_id}/update_scene`, { task_id, scene_key, description }),
  updateShot: (task_id, shot_id, payload) =>
    request.post(`/api/task/${task_id}/update_shot`, { task_id, shot_id, ...payload }),
  updateScript: (task_id, title, raw_content) =>
    request.post(`/api/task/${task_id}/update_script`, { task_id, title, raw_content }),
  updateAudioMode: (task_id, audio_mode) =>
    request.post(`/api/task/${task_id}/update_audio_mode`, { task_id, audio_mode }),
  compose: (task_id) => request.post(`/api/task/${task_id}/compose_video`, { task_id }, { timeout: 600000 }),
  // 失败/完成任务整体重新开始（原地重跑）
  retry: (task_id) => request.post(`/api/task/${task_id}/retry`, {}, { timeout: 300000 }),
  // 删除整个任务
  remove: (task_id) => request.delete(`/api/task/${task_id}`)
}

// 表单类接口：上传本地图片替换形象图
// P2-14：10MB 级大图慢网下 120s 默认超时会被误取消，对齐长任务 300s
export async function uploadReplaceImage(taskId, targetType, targetId, file) {
  const fd = new FormData()
  fd.append('target_type', targetType)
  fd.append('target_id', targetId)
  fd.append('file', file)
  return request.post(`/api/task/${taskId}/replace_image`, fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 300000
  })
}

// 用 Authorization 头换取短时 stream token（P1-5：JWT 不再进 SSE URL query）
export async function fetchStreamToken(taskId) {
  const res = await request.post(`/api/task/${taskId}/stream_token`, {})
  return res?.token || ''
}

// SSE 进度流地址（EventSource 不支持自定义 header，用短时 stream token 走 query；
// token 60s 有效，前端在 onerror 时会重新签发重建连接）
export function streamUrl(taskId, token) {
  return `/api/task/stream/${taskId}?token=${encodeURIComponent(token)}`
}
