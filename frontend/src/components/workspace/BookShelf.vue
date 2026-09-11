<template>
  <section class="card shelf-card" @click.self="playLatestFinal">
    <div class="shelf-head">
      <div class="shelf-title">
        <h3>📚 {{ name }}</h3>
        <p class="sub">
          共 {{ family.length }} 集 · 已完成 <b>{{ doneCount }}</b> 集 ·
          点击书册翻开该集流程详情
        </p>
      </div>
      <button class="btn btn-primary btn-sm" @click="$emit('new-episode')">＋ 续写下一集</button>
    </div>

    <div class="shelf-row">
      <button v-for="ep in family" :key="ep.task_id"
              class="book" :class="bookClass(ep)"
              :title="bodyTip(ep)"
              @click="onBodyClick(ep)">
        <span class="spine-edge"></span>
        <span class="spine-txt">{{ epNo(ep) }}</span>
        <span class="book-name">{{ epTitle(ep) }}</span>
        <span class="book-status">
          <i class="dot"></i>{{ statusText(ep.status) }}
        </span>
        <!-- 翻开区：点这里进流程详情（阻止冒泡，不触发书体播视频） -->
        <span class="book-open" @click.stop="onOpenClick(ep)">翻开 ▸</span>
      </button>

      <!-- 续写占位书 -->
      <button class="book ghost" @click="$emit('new-episode')">
        <span class="ghost-plus">＋</span>
        <span class="ghost-txt">续写第{{ episodeCn(nextNo) }}集</span>
      </button>
    </div>
    <!-- 书架隔板：点击空白处播放系列最新成片 -->
    <div class="plank" title="点击播放合成成片" @click="playLatestFinal"></div>

    <!-- 成片播放弹窗：点已完成的书体直接看这一集 -->
    <Teleport to="body">
      <div v-if="playing" class="vp-mask" @click.self="closePlayer">
        <div class="vp-box">
          <div class="vp-head">
            <h4>🎬 {{ playing.title }}</h4>
            <button class="vp-close" @click="closePlayer">✕</button>
          </div>
          <video v-if="playing.url" :src="playing.url" controls autoplay preload="metadata"></video>
          <p v-else class="vp-missing">该集成片地址缺失，请翻开详情后在合成面板查看。</p>
        </div>
      </div>
    </Teleport>
  </section>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useTaskStore } from '@/stores/task'
import { seriesFamily, seriesName, taskTitle, statusText, episodeCn } from '@/utils/format'

const emit = defineEmits(['open', 'new-episode'])

const taskStore = useTaskStore()

// 成片播放弹窗：{ title, url }
const playing = ref(null)

const family = computed(() => seriesFamily(taskStore.tasks, taskStore.current))
const name = computed(() => seriesName(taskStore.current))
const doneCount = computed(() => family.value.filter((t) => t.status === 'done').length)
// 续写挂在最新一集下面（ episode 链式继承前情 ）
const latest = computed(() => family.value[family.value.length - 1] || taskStore.current)
const nextNo = computed(() => (latest.value?.episode_no || 1) + 1)

const epNo = (ep) => `第${episodeCn(ep.episode_no || 1)}集`
const epTitle = (ep) => {
  const base = ep.script?.title || (ep.user_prompt || '').slice(0, 14) || '未命名'
  return base === name.value ? '' : base
}
const bookClass = (ep) => {
  if (ep.status === 'done') return 'st-done'
  if (ep.status === 'failed') return 'st-failed'
  return 'st-running'
}
const bodyTip = (ep) => ep.status === 'done'
  ? `${epTitle(ep) || name.value}（已完成）· 点书体看本集成片，点「翻开」看流程详情`
  : `${epTitle(ep) || name.value}（${statusText(ep.status)}）· 点击进入流程详情`

// 书体点击：已完成 → 播放本集成片；其余 → 进流程详情
function onBodyClick(ep) {
  if (ep.status === 'done' && ep.final_video_url) {
    playing.value = { title: `${name.value} · ${epNo(ep)}`, url: ep.final_video_url }
    return
  }
  emit('open', ep.task_id)
}

// 「翻开」区点击：始终进流程详情
function onOpenClick(ep) {
  emit('open', ep.task_id)
}

// 点击书架空白处（隔板等）：播放「系列最新完成集」的合成成片
function playLatestFinal() {
  const doneEps = family.value.filter((t) => t.status === 'done' && t.final_video_url)
  const ep = doneEps[doneEps.length - 1]
  if (!ep) {
    // 无成片：兜底提示（不打断操作）
    playing.value = { title: `${name.value} · 暂无成片`, url: '' }
    return
  }
  playing.value = { title: `${name.value} · 第${episodeCn(ep.episode_no || 1)}集成片`, url: ep.final_video_url }
}

function closePlayer() {
  playing.value = null
}
</script>

<style scoped>
.shelf-card { padding: 22px 26px 26px; }

.shelf-head {
  display: flex; justify-content: space-between; align-items: flex-start;
  margin-bottom: 26px;
}
.shelf-title h3 { font-size: 18px; margin: 0 0 6px; }
.sub { margin: 0; font-size: 12.5px; color: var(--text-3); }
.sub b { color: var(--success); }

/* 书架：横向排列的一排书 */
.shelf-row {
  display: flex; align-items: flex-end; gap: 18px; flex-wrap: wrap;
  padding: 6px 4px 0;
}

/* 书册：竖排书脊样式 */
.book {
  position: relative; width: 108px; height: 280px;
  border: none; border-radius: 6px 10px 10px 6px; cursor: pointer;
  display: flex; flex-direction: column; align-items: center;
  padding: 18px 0 14px; font-family: inherit;
  background: linear-gradient(168deg, #b03a2e 0%, #8e2418 48%, #57120b 100%);
  box-shadow: 0 10px 22px rgba(0,0,0,.45), inset 0 1px 0 rgba(255,255,255,.14);
  transition: transform .22s ease, box-shadow .22s ease;
  color: #f5ddd6;
  overflow: hidden;
}
.book:hover { transform: translateY(-10px); box-shadow: 0 22px 34px rgba(0,0,0,.55); }

/* 左侧书脊高光 + 右侧书页纹 */
.spine-edge {
  position: absolute; left: 0; top: 0; bottom: 0; width: 10px;
  background: linear-gradient(90deg, rgba(255,255,255,.28), rgba(255,255,255,.05) 70%, rgba(0,0,0,.25));
}
.book::after {
  content: ''; position: absolute; right: 0; top: 4px; bottom: 4px; width: 6px;
  background: repeating-linear-gradient(180deg, rgba(255,255,255,.5) 0 2px, rgba(0,0,0,.12) 2px 4px);
  border-radius: 0 3px 3px 0; opacity: .35;
}

/* 竖排集数 */
.spine-txt {
  writing-mode: vertical-rl; text-orientation: upright;
  font-size: 26px; font-weight: 700; letter-spacing: 10px;
  color: #fff; text-shadow: 0 2px 6px rgba(0,0,0,.5);
  flex: 1; display: flex; align-items: flex-start; margin-top: 6px;
}
.book-name {
  writing-mode: vertical-rl; text-orientation: upright;
  font-size: 11px; letter-spacing: 3px; color: rgba(255,235,228,.8);
  max-height: 120px; overflow: hidden; margin-bottom: 8px;
}
.book-status {
  display: flex; align-items: center; gap: 5px;
  font-size: 10.5px; color: rgba(255,235,228,.85);
  background: rgba(0,0,0,.28); padding: 3px 8px; border-radius: 20px;
}
.dot { width: 6px; height: 6px; border-radius: 50%; background: var(--success); }
.st-running .dot { background: var(--warning); animation: pulse 1.2s infinite; }
.st-failed .dot { background: var(--danger); }
@keyframes pulse { 50% { opacity: .3; } }

.book-open {
  position: absolute; bottom: 46px; left: 0; right: 0; text-align: center;
  font-size: 11px; color: #fff; opacity: 0; transition: opacity .2s;
  background: rgba(0,0,0,.35); margin: 0 10px; padding: 4px 0; border-radius: 12px;
  cursor: pointer;
}
.book:hover .book-open { opacity: .95; }
.book-open:hover { background: rgba(0,0,0,.55); }

/* ===== 成片播放弹窗 ===== */
.vp-mask {
  position: fixed; inset: 0; z-index: 200;
  background: rgba(0,0,0,.72); backdrop-filter: blur(4px);
  display: grid; place-items: center; padding: 30px;
}
.vp-box {
  width: min(860px, 94vw); background: var(--bg-card);
  border: 1px solid var(--border); border-radius: 14px;
  padding: 14px 16px 16px; box-shadow: 0 24px 60px rgba(0,0,0,.6);
}
.vp-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; }
.vp-head h4 { margin: 0; font-size: 15px; }
.vp-close {
  border: none; background: var(--bg-hover); color: var(--text-2);
  width: 28px; height: 28px; border-radius: 8px; cursor: pointer; font-size: 13px;
}
.vp-close:hover { color: var(--text); background: var(--border); }
.vp-box video { width: 100%; max-height: 70vh; border-radius: 8px; background: #000; display: block; }
.vp-missing { font-size: 13px; color: var(--text-2); text-align: center; padding: 30px 0; }

/* 进行中 / 失败 的书变体 */
.st-running { background: linear-gradient(168deg, #6d5b2c 0%, #54471f 50%, #2e2712 100%); color: #f2e8c9; }
.st-failed  { background: linear-gradient(168deg, #4a4048 0%, #38313a 50%, #201c22 100%); color: #d8d2dc; }

/* 续写占位书（虚线 ghost） */
.book.ghost {
  background: none; border: 1.5px dashed var(--border-strong);
  box-shadow: none; justify-content: center; gap: 10px;
  color: var(--text-3);
}
.book.ghost:hover { border-color: var(--primary); color: var(--text); transform: translateY(-6px); }
.ghost-plus { font-size: 30px; line-height: 1; }
.ghost-txt { writing-mode: vertical-rl; text-orientation: upright; font-size: 12px; letter-spacing: 4px; }

/* 书架隔板 */
.plank {
  margin-top: 18px; height: 10px; border-radius: 3px;
  background: linear-gradient(180deg, #3a3126 0%, #241f18 70%, #17130e 100%);
  box-shadow: 0 6px 14px rgba(0,0,0,.5);
}
</style>
