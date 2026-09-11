import request from './request'

export const channelApi = {
  // 通道与模型预设元数据
  meta: () => request.get('/api/channels/meta'),
  // 当前用户配置（敏感字段为掩码）
  get: () => request.get('/api/user/channel-config'),
  // 保存配置
  save: (config) => request.put('/api/user/channel-config', config),
  // 连通性测试：kind=llm/image/video
  test: (kind, profile) => request.post('/api/user/channel-test', { kind, profile })
}
