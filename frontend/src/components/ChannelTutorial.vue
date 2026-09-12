<template>
  <Teleport to="body">
    <div v-if="visible" class="tut-mask" @click.self="close">
      <div class="tut-dialog fade-up">
        <header>
          <div>
            <h3>📖 通道配置教程</h3>
            <p>每类通道都附图文步骤：注册地址 → 获取 Key → 填模型名。点左侧目录切换，照着填即可</p>
          </div>
          <button class="icon-btn" @click="close">✕</button>
        </header>

        <div class="tut-body">
          <!-- 左侧目录 -->
          <aside class="tut-nav">
            <div class="nav-group" v-for="g in groups" :key="g.label">
              <div class="nav-group-title">{{ g.label }}</div>
              <button v-for="t in g.items" :key="t.id"
                      class="nav-item" :class="{ active: activeId === t.id }"
                      @click="activeId = t.id">
                <span class="nav-ico">{{ t.icon }}</span>
                {{ t.label }}
              </button>
            </div>
          </aside>

          <!-- 右侧内容 -->
          <section class="tut-content">
            <div v-if="!active" class="empty">请从左侧选择一类通道查看教程</div>
            <template v-else>
              <div class="doc-head">
                <h2><span class="doc-ico">{{ active.icon }}</span>{{ active.label }}</h2>
                <p class="doc-tag">{{ active.tagline }}</p>
              </div>

              <!-- 步骤 -->
              <div class="step" v-for="(s, i) in active.steps" :key="i">
                <div class="step-no">{{ i + 1 }}</div>
                <div class="step-body">
                  <h4>{{ s.title }}</h4>
                  <p v-if="s.desc" class="step-desc">{{ s.desc }}</p>
                  <div v-if="s.code" class="code-line" @click="copy(s.code)">
                    <code>{{ s.code }}</code><span class="copy-hint">点击复制</span>
                  </div>
                  <a v-if="s.link" class="step-link" :href="s.link" target="_blank" rel="noopener">
                    🔗 {{ s.linkLabel || s.link }}
                  </a>
                  <div v-if="s.svg" class="fig" v-html="svgFigure(s.svg)"></div>
                  <div v-if="s.hint" class="hint-line">💡 {{ s.hint }}</div>
                </div>
              </div>

              <!-- 对照表 -->
              <div v-if="active.table" class="tbl-box">
                <h4>{{ active.table.title }}</h4>
                <table>
                  <thead><tr><th v-for="h in active.table.headers" :key="h">{{ h }}</th></tr></thead>
                  <tbody>
                    <tr v-for="(r, ri) in active.table.rows" :key="ri">
                      <td v-for="(c, ci) in r" :key="ci" v-html="hl(c)"></td>
                    </tr>
                  </tbody>
                </table>
              </div>

              <!-- 常见坑 -->
              <div v-if="active.tips?.length" class="tips-box">
                <h4>⚠️ 常见问题</h4>
                <ul>
                  <li v-for="(t, ti) in active.tips" :key="ti">{{ t }}</li>
                </ul>
              </div>
            </template>
          </section>
        </div>

        <footer>
          <span class="foot-note">截图均为界面示意图，实际以各平台当前页面为准</span>
          <div class="spacer"></div>
          <button class="btn" @click="close">知道了</button>
        </footer>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useToastStore } from '@/stores/toast'

const toast = useToastStore()
const visible = ref(false)
const activeId = ref('llm')

function open(kind, channel) {
  // 未选通道（空或 'env' 系统默认）时给一个默认定位：图片/视频默认火山即梦 CV，大模型默认 OpenAI 兼容
  const def = { image: 'volc_cv', video: 'volc_cv' }[kind] || ''
  const ch = (channel && channel !== 'env') ? channel : def
  const map = { llm: 'llm', image: imgTutOf(ch), video: vidTutOf(ch) }
  activeId.value = map[kind] || 'llm'
  visible.value = true
}
function imgTutOf(ch) { return ch === 'volc_cv' ? 'cv' : ch === 'volc_ark' ? 'ark' : ch === 'generic_http' ? 'http' : 'llm' }
function vidTutOf(ch) { return imgTutOf(ch) }
function close() { visible.value = false }

function copy(text) {
  const ta = document.createElement('textarea')
  ta.value = text
  document.body.appendChild(ta)
  ta.select()
  try { document.execCommand('copy') } catch { /* noop */ }
  document.body.removeChild(ta)
  toast.ok('已复制：' + text)
}

// 高亮表格中的 `` 代码片段
function hl(c) {
  return String(c).replace(/`([^`]+)`/g, '<code class="tbl-code">$1</code>')
}

/* ================= SVG 界面示意图 ================= */
const SVG = {
  // 通用窗口骨架
  frame(x, y, w, h, title, body) {
    const bar = 26
    return `<svg viewBox="0 0 ${w} ${h}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="界面示意图">
  <defs>
    <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#3b4bff" stop-opacity=".9"/>
      <stop offset="1" stop-color="#8b5cf6" stop-opacity=".9"/>
    </linearGradient>
  </defs>
  <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="12" fill="#0d1220" stroke="#2a3550" stroke-width="1.2"/>
  <rect x="${x}" y="${y}" width="${w}" height="${bar}" rx="12" fill="#161d33"/>
  <rect x="${x}" y="${y + bar / 2}" width="${w}" height="${bar / 2}" fill="#161d33"/>
  <circle cx="${x + 18}" cy="${y + 13}" r="4" fill="#ff5f57"/>
  <circle cx="${x + 32}" cy="${y + 13}" r="4" fill="#febc2e"/>
  <circle cx="${x + 46}" cy="${y + 13}" r="4" fill="#28c840"/>
  <rect x="${x + 66}" y="${y + 7}" width="${w - 84}" height="14" rx="7" fill="#0b0f1c" stroke="#26304a"/>
  <text x="${x + w / 2}" y="${y + 17.5}" text-anchor="middle" font-size="9" fill="#7c8db5" font-family="inherit">${title}</text>
  ${body}
</svg>`
  },
  // 左侧菜单条
  menu(x, y, h, items, activeIdx) {
    return items.map((m, i) => `
  <rect x="${x}" y="${y + i * 30}" width="120" height="24" rx="6" fill="${i === activeIdx ? '#2b3bff' : 'transparent'}" opacity="${i === activeIdx ? '.9' : '1'}"/>
  <text x="${x + 12}" y="${y + i * 30 + 16}" font-size="10.5" fill="${i === activeIdx ? '#fff' : '#8fa3c8'}" font-family="inherit">${m}</text>`).join('')
  },
  // 圆角按钮
  btn(x, y, w, h, label, fill = 'url(#g)') {
    return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="7" fill="${fill}"/><text x="${x + w / 2}" y="${y + h / 2 + 3.5}" text-anchor="middle" font-size="10" fill="#fff" font-family="inherit">${label}</text>`
  },
  // 文本行（可换色）
  line(x, y, label, w = 210, c = '#33415e', size = 10) {
    return `<rect x="${x}" y="${y}" width="${w}" height="16" rx="4" fill="${c}"/><text x="${x + 8}" y="${y + 11.5}" font-size="${size}" fill="#b9c7e6" font-family="inherit">${label}</text>`
  },
  label(x, y, text, c = '#7c8db5') {
    return `<text x="${x}" y="${y}" font-size="9.5" fill="${c}" font-family="inherit">${text}</text>`
  }
}

function svgFigure(name) {
  const W = 560, H = 300
  switch (name) {
    case 'llm': {
      // DeepSeek / OpenAI 兼容平台：API Keys 页
      const body = `
  ${SVG.menu(20, 52, 200, ['概览', 'API Keys', '用量', '账单'], 1)}
  <text x="180" y="80" font-size="13" font-weight="bold" fill="#e8eefc" font-family="inherit">API Keys</text>
  ${SVG.btn(440, 66, 96, 24, '+ 创建 Key')}
  ${SVG.line(180, 110, 'sk-9f2c...（已创建，只显示一次）', 330)}
  ${SVG.line(180, 136, 'sk-7a1d...', 330)}
  ${SVG.line(180, 162, 'sk-3b8e...', 330)}
  ${SVG.label(180, 200, '① 复制这一串 sk- 开头的 Key', '#8b9cff')}
  ${SVG.label(180, 220, '② BaseURL 填平台根地址，如 https://api.deepseek.com', '#8b9cff')}
  ${SVG.label(180, 240, '③ 模型名填 deepseek-chat 等平台提供的模型', '#8b9cff')}
  ${SVG.btn(180, 258, 180, 26, '填进「大模型」表单 → 连通测试')}`
      return SVG.frame(0, 0, W, H, '示意：OpenAI 兼容平台「API Keys」管理页', body)
    }
    case 'cv': {
      // 火山引擎 IAM 密钥管理页
      const body = `
  ${SVG.menu(20, 52, 200, ['访问控制 IAM', '用户', 'API 访问密钥', '角色'], 2)}
  <text x="180" y="80" font-size="13" font-weight="bold" fill="#e8eefc" font-family="inherit">API 访问密钥</text>
  ${SVG.btn(440, 66, 96, 24, '+ 创建密钥')}
  ${SVG.line(180, 110, 'AKLT****abcd   （AccessKey ID）', 330, '#26324f')}
  ${SVG.line(180, 136, '****保密  （Secret Access Key）', 330, '#26324f')}
  ${SVG.label(180, 196, '① AccessKey ID → 填「AccessKey」', '#8b9cff')}
  ${SVG.label(180, 216, '② Secret Key（仅创建时显示一次）→ 填「SecretKey」', '#8b9cff')}
  ${SVG.label(180, 236, '③ 模型名 req_key 填即梦模型，如 jimeng_high_aes_general_v21_L', '#8b9cff')}
  ${SVG.btn(180, 258, 200, 26, '填进「火山即梦 CV」表单')}`
      return SVG.frame(0, 0, W, H, '示意：火山引擎控制台「API 访问密钥」页', body)
    }
    case 'ark': {
      // 方舟：API Key 管理 + 模型广场
      const body = `
  ${SVG.menu(20, 52, 200, ['方舟控制台', 'API Key 管理', '模型广场', '在线推理'], 1)}
  <text x="180" y="80" font-size="13" font-weight="bold" fill="#e8eefc" font-family="inherit">API Key 管理</text>
  ${SVG.btn(440, 66, 96, 24, '+ 创建 API Key')}
  ${SVG.line(180, 110, 'volc-sk-4e2c...（只显示一次）', 330)}
  ${SVG.label(180, 142, '模型广场已开通（示例 Model ID）：', '#7c8db5')}
  <rect x="180" y="152" width="330" height="58" rx="8" fill="#101830" stroke="#2a3550"/>
  ${SVG.line(192, 164, '图片 doubao-seedream-5-0-260128', 306, '#1b2440')}
  ${SVG.line(192, 186, '视频 doubao-seedance-2-0-260128', 306, '#1b2440')}
  ${SVG.label(180, 236, '① Key 填 volc-sk-xxx；② 模型名填上面 Model ID（以控制台为准）', '#8b9cff')}
  ${SVG.btn(180, 258, 210, 26, '填进「火山方舟 ARK」表单')}`
      return SVG.frame(0, 0, W, H, '示意：火山方舟「API Key 管理 + 模型广场」页', body)
    }
    case 'http': {
      // 硅基流动 API 密钥页
      const body = `
  ${SVG.menu(20, 52, 200, ['控制台', 'API 密钥', '模型广场', '用量'], 1)}
  <text x="180" y="80" font-size="13" font-weight="bold" fill="#e8eefc" font-family="inherit">API 密钥</text>
  ${SVG.btn(440, 66, 96, 24, '+ 新建密钥')}
  ${SVG.line(180, 110, 'sk-xxxxxxxxxxxxxxxx（创建后复制）', 330)}
  ${SVG.label(180, 160, '模型广场复制完整模型名（带组织前缀）：', '#7c8db5')}
  <rect x="180" y="170" width="330" height="58" rx="8" fill="#101830" stroke="#2a3550"/>
  ${SVG.line(192, 182, '图片 Kwai-Kolors/Kolors', 306, '#1b2440')}
  ${SVG.line(192, 204, '视频 Wan-AI/Wan2.2-I2V-A14B', 306, '#1b2440')}
  ${SVG.label(180, 244, 'BaseURL 填 https://api.siliconflow.cn，Token 填 sk-xxx，模型名照抄', '#8b9cff')}
  ${SVG.btn(180, 260, 200, 26, '填进「通用 HTTP」表单')}`
      return SVG.frame(0, 0, W, H, '示意：硅基流动「API 密钥」页（其他平台同理）', body)
    }
  }
  return ''
}

/* ================= 教程内容 ================= */
const TUTS = {
  llm: {
    id: 'llm', icon: '🤖', label: '大模型 · OpenAI 兼容',
    tagline: '剧本生成与解析用。任何 OpenAI 兼容平台都行，以 DeepSeek 为例',
    steps: [
      { title: '注册平台并创建 API Key', desc: '以 DeepSeek（https://platform.deepseek.com）为例：注册登录 → 左侧「API Keys」→「创建 API Key」→ 复制 sk- 开头的密钥（只显示一次）。',
        link: 'https://platform.deepseek.com', linkLabel: '打开 DeepSeek 开放平台', svg: 'llm' },
      { title: '在弹窗中填写三项', desc: '大模型标签页选「OpenAI 兼容接口」，依次填写：',
        code: 'BaseURL：https://api.deepseek.com\nAPI Key：sk-你的密钥\n模型名：deepseek-chat',
        hint: '模型名以平台为准：DeepSeek 用 deepseek-chat；智谱用 glm-4-flash；OpenAI 用 gpt-4o-mini 等' },
      { title: '保存并连通测试', desc: '点「保存配置」→「连通测试」发真实请求验证。通过后侧栏会显示你配置的通道与模型。' }
    ],
    tips: [
      'BaseURL 只填根地址（https://api.deepseek.com），不要带 /chat/completions 路径',
      'Key 不要复制多余空格；掩码显示（__MASKED__）说明已配置，不修改留空即可',
      '模型名手动填写，可填任意最新模型，不受下拉限制'
    ]
  },
  cv: {
    id: 'cv', icon: '🖼️', label: '火山即梦 CV · AK/SK',
    tagline: '火山引擎视觉服务（即梦系列）。适合已有火山账号、要求不高的场景',
    steps: [
      { title: '注册火山引擎', desc: '打开 https://www.volcengine.com 注册并完成实名认证（个人即可）。', link: 'https://www.volcengine.com', linkLabel: '打开火山引擎' },
      { title: '创建 API 访问密钥（AK/SK）', desc: '控制台右上角头像 →「API 访问密钥」→「创建密钥」，得到一对 AccessKey ID + Secret Access Key（Secret 只显示一次）。', link: 'https://console.volcengine.com/iam/key/manage/', linkLabel: '直达密钥管理页', svg: 'cv' },
      { title: '开通视觉服务（即梦）', desc: '控制台搜索「视觉智能」→ 开通服务（免费，按调用计费）。' },
      { title: '填表单', desc: '图片/视频标签页选「火山即梦 CV」，模型 req_key 手动填写下表：',
        code: 'AccessKey：AKLT...\nSecretKey：你的 Secret Key\nreq_key：见下方对照表', hint: 'req_key 以控制台「视觉智能 → 模型列表」实际显示为准' }
    ],
    table: {
      title: 'req_key 常用对照',
      headers: ['能力', 'req_key'],
      rows: [
        ['图片（立绘/场景图）', '`jimeng_high_aes_general_v21_L`'],
        ['图片（图生图·黑夜）', '`jimeng_i2i_v30`（⚠️ 部分账号未开放）'],
        ['视频', '`jimeng_t2v_v30`']
      ]
    },
    tips: [
      'cv 通道不支持「白天图→黑夜图」图生图，黑夜图仅方舟/HTTP 通道稳定支持',
      'SecretKey 创建后只显示一次，丢了只能重新创建',
      '报 50200 参数错误 = req_key 与账号可用水位不符，换控制台显示的模型'
    ]
  },
  ark: {
    id: 'ark', icon: '🚀', label: '火山方舟 ARK · 推荐',
    tagline: 'Seedance + Seedream：角色/场景一致性强、黑夜图基于白天图、视频可原生带声音',
    steps: [
      { title: '开通方舟服务', desc: '用火山账号登录控制台 → 搜索「方舟」→ 立即开通（免费）。', link: 'https://console.volcengine.com', linkLabel: '打开火山引擎控制台' },
      { title: '模型广场开通模型', desc: '左侧「模型广场」搜索并开通 Seedream（图片）与 Seedance（视频），记下完整 Model ID。', svg: 'ark' },
      { title: '创建 API Key', desc: '「API Key 管理」→「创建 API Key」，复制 volc-sk- 开头的密钥（只显示一次）。' },
      { title: '填表单（图片/视频各填一份）', desc: '通道选「火山方舟」，同一个 Key 填两处，模型名用 Model ID：',
        code: 'API Key：volc-sk-你的密钥\n图片模型：doubao-seedream-5-0-260128\n视频模型：doubao-seedance-2-0-260128',
        hint: '视频还可选 720p / 9:16（竖屏短剧），并打开「原生音频」让视频自带台词人声' }
    ],
    tips: [
      '方舟 Key（volc-sk-）与即梦 AK/SK 不通用，是两套独立凭据',
      '报 403/未授权 = 模型没在「模型广场」开通，先开通再调用',
      'Model ID 以控制台实际显示为准，版本号会更新（如 seedream-4-0 / seedance-2-5）',
      '模型名随便填最新版本即可，不受下拉限制'
    ]
  },
  http: {
    id: 'http', icon: '🌐', label: '通用 HTTP · 硅基流动等',
    tagline: '任何 OpenAI 兼容平台都能接。系统按域名自动识别平台、补全路径，只需 3 项',
    steps: [
      { title: '注册硅基流动并创建 API Key', desc: 'https://cloud.siliconflow.cn 注册 → 「API 密钥」→ 新建密钥 → 复制 sk- 开头密钥。', link: 'https://cloud.siliconflow.cn', linkLabel: '打开硅基流动', svg: 'http' },
      { title: '从模型广场复制模型名', desc: '模型名必须完整（带组织前缀），直接在模型卡片上复制。' },
      { title: '填 3 项即可', desc: '图片/视频标签页选「通用 HTTP」：',
        code: '服务地址 BaseURL：https://api.siliconflow.cn\nBearer Token：sk-你的密钥\n模型名：见下方对照表',
        hint: '提交/轮询地址、参考图、状态枚举全部自动识别，不用填高级设置' }
    ],
    table: {
      title: '硅基流动常用模型名（其他平台照其文档填）',
      headers: ['能力', '模型名'],
      rows: [
        ['图片', '`Kwai-Kolors/Kolors`'],
        ['视频（图生，推荐）', '`Wan-AI/Wan2.2-I2V-A14B`'],
        ['视频（文生）', '`Wan-AI/Wan2.2-T2V-A14B`'],
        ['大模型', '`deepseek-ai/DeepSeek-V3`']
      ]
    },
    tips: [
      'BaseURL 只填根地址，不要带 /v1/... 路径；Token 注意别复制到空格',
      '内置预设：硅基流动、智谱 BigModel、OpenAI 官方自动识别；其他平台按 OpenAI 兼容处理',
      '平台返回结构特殊时再展开「高级设置」覆盖（提交/轮询 URL、字段路径等）',
      '视频竖屏自动配 720x1280；Wan2.2 固定约 5 秒，不支持指定时长属正常'
    ]
  }
}

const groups = [
  { label: '剧本（大模型）', items: [TUTS.llm] },
  { label: '图片 / 视频通道', items: [TUTS.cv, TUTS.ark, TUTS.http] }
]

const active = computed(() => {
  for (const g of groups) {
    const t = g.items.find((x) => x.id === activeId.value)
    if (t) return t
  }
  return null
})

defineExpose({ open })
</script>

<style scoped>
.tut-mask {
  position: fixed; inset: 0; background: rgba(4, 6, 12, .7); z-index: 1100;
  display: grid; place-items: center; backdrop-filter: blur(4px);
}
.tut-dialog {
  width: 880px; max-width: 96vw; height: 84vh; display: flex; flex-direction: column;
  background: var(--bg-card); border: 1px solid var(--border-strong);
  border-radius: 18px; box-shadow: 0 24px 80px rgba(0,0,0,.5); overflow: hidden;
}
header {
  display: flex; justify-content: space-between; align-items: flex-start;
  padding: 20px 24px 14px; border-bottom: 1px solid var(--border);
}
header h3 { font-size: 17px; }
header p { font-size: 12.5px; color: var(--text-3); margin-top: 3px; }
.icon-btn { background: none; border: none; color: var(--text-3); font-size: 16px; cursor: pointer; padding: 4px 8px; border-radius: 6px; }
.icon-btn:hover { background: var(--bg-hover); color: var(--text); }

.tut-body { flex: 1; display: flex; min-height: 0; }
/* 左侧目录 */
.tut-nav {
  width: 190px; flex-shrink: 0; padding: 16px 10px; overflow-y: auto;
  border-right: 1px solid var(--border); background: var(--bg-card-2);
}
.nav-group-title { font-size: 11px; color: var(--text-3); text-transform: uppercase; letter-spacing: .4px; padding: 4px 10px 8px; }
.nav-item {
  display: flex; align-items: center; gap: 8px; width: 100%; text-align: left;
  padding: 9px 10px; margin-bottom: 3px; border: none; border-radius: 9px;
  background: transparent; color: var(--text-2); font-size: 13px; cursor: pointer; font-family: inherit;
}
.nav-item:hover { background: var(--bg-hover); color: var(--text); }
.nav-item.active { background: var(--primary-soft); color: #dfe6ff; font-weight: 600; }
.nav-ico { font-size: 14px; }

/* 右侧内容 */
.tut-content { flex: 1; overflow-y: auto; padding: 24px 28px 36px; }
.empty { color: var(--text-3); font-size: 14px; margin-top: 40px; text-align: center; }
.doc-head { margin-bottom: 20px; }
.doc-head h2 { font-size: 19px; display: flex; align-items: center; gap: 10px; }
.doc-ico { font-size: 20px; }
.doc-tag { font-size: 13px; color: var(--text-2); margin-top: 6px; line-height: 1.7; }

.step { display: flex; gap: 14px; margin-bottom: 18px; }
.step-no {
  flex-shrink: 0; width: 26px; height: 26px; border-radius: 50%;
  background: var(--primary-soft); color: #cfd8ff; font-size: 13px; font-weight: 700;
  display: grid; place-items: center; margin-top: 2px;
}
.step-body { flex: 1; min-width: 0; }
.step-body h4 { font-size: 14px; margin-bottom: 5px; }
.step-desc { font-size: 13px; color: var(--text-2); line-height: 1.75; margin-bottom: 8px; }
.code-line {
  display: flex; justify-content: space-between; align-items: center; gap: 10px;
  background: #0a0f1e; border: 1px solid var(--border); border-radius: 10px;
  padding: 10px 14px; margin: 8px 0; cursor: pointer; white-space: pre-line;
}
.code-line code { font-size: 12.5px; color: #b9c7e6; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; }
.copy-hint { font-size: 11px; color: var(--text-3); flex-shrink: 0; }
.code-line:hover { border-color: var(--border-strong); }
.code-line:hover .copy-hint { color: var(--primary); }
.step-link { display: inline-block; font-size: 13px; color: var(--primary); text-decoration: none; margin-top: 4px; }
.step-link:hover { text-decoration: underline; }
.hint-line { font-size: 12.5px; color: var(--success); margin-top: 8px; line-height: 1.6; }
.fig { margin: 12px 0 4px; }
.fig :deep(svg) { width: 100%; height: auto; max-width: 560px; display: block; }

.tbl-box { margin: 20px 0; }
.tbl-box h4 { font-size: 14px; margin-bottom: 10px; }
table { width: 100%; border-collapse: collapse; font-size: 12.5px; }
th, td { text-align: left; padding: 9px 12px; border: 1px solid var(--border); }
th { background: var(--bg-card-2); color: var(--text-2); font-weight: 600; }
td { color: var(--text-2); }
.tbl-code {
  background: #0a0f1e; border: 1px solid var(--border); border-radius: 5px;
  padding: 1px 6px; font-family: ui-monospace, Consolas, monospace; font-size: 11.5px; color: #b9c7e6;
}
.tips-box { margin-top: 20px; }
.tips-box h4 { font-size: 14px; margin-bottom: 8px; color: #ffd58a; }
.tips-box ul { margin: 0; padding-left: 18px; }
.tips-box li { font-size: 12.5px; color: var(--text-2); line-height: 1.8; }

footer {
  display: flex; align-items: center; gap: 10px; padding: 12px 24px;
  border-top: 1px solid var(--border);
}
.foot-note { font-size: 11.5px; color: var(--text-3); }
.spacer { flex: 1; }
</style>
