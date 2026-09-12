<template>
  <router-view />
  <div class="toast-wrap">
    <div v-for="t in toastStore.list" :key="t.id" class="toast" :class="`toast-${t.type}`">
      {{ t.msg }}
    </div>
  </div>
  <!-- P1-4 全局错误边界：渲染异常时兜底提示，避免整页白屏无反馈 -->
  <div v-if="fatal" class="fatal-overlay">
    <div class="fatal-card">
      <h3>页面出了点问题</h3>
      <p>界面渲染发生异常，已自动拦截。任务数据保存在服务器，刷新后不受影响。</p>
      <button @click="recover">刷新页面</button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch, onErrorCaptured } from 'vue'
import { useRouter } from 'vue-router'
import { useToastStore } from '@/stores/toast'
import { useAuthStore } from '@/stores/auth'
import { useTaskStore } from '@/stores/task'
import { useChannelStore } from '@/stores/channel'

const toastStore = useToastStore()
const auth = useAuthStore()
const taskStore = useTaskStore()
const channel = useChannelStore()
const router = useRouter()

// P1-4：组件渲染错误统一兜底：连续报错才整页兜底；单次小错仅提示，不打断使用
const fatal = ref(false)
let errorCount = 0
let errorTimer = null
onErrorCaptured((err, instance, info) => {
  console.error('[AppErrorCaptured]', err, info)
  errorCount += 1
  toastStore.push('界面渲染异常：' + (err?.message || '未知错误'), 'err')
  clearTimeout(errorTimer)
  errorTimer = setTimeout(() => { errorCount = 0 }, 8000)
  if (errorCount >= 3) {
    fatal.value = true
    errorCount = 0
  }
  return false // 阻止错误继续向上冒泡（避免重复触发）
})

function recover() {
  window.location.reload()
}

// 登出 / token 失效（401）时统一清空当前用户会话数据，
// 避免切换账号后残留上一账号的任务列表、流程图与执行日志
watch(() => auth.isLogin, (v) => {
  if (!v) {
    taskStore.reset()
    channel.reset()
  }
})
</script>

<style scoped>
.fatal-overlay {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(15, 17, 26, 0.72);
  backdrop-filter: blur(6px);
}
.fatal-card {
  max-width: 380px;
  padding: 28px 32px;
  border-radius: 16px;
  background: #fff;
  box-shadow: 0 16px 48px rgba(0, 0, 0, 0.25);
  text-align: center;
}
.fatal-card h3 { margin: 0 0 10px; font-size: 18px; color: #1f2329; }
.fatal-card p { margin: 0 0 18px; font-size: 14px; line-height: 1.7; color: #646a73; }
.fatal-card button {
  padding: 8px 26px;
  border: none;
  border-radius: 8px;
  background: #3370ff;
  color: #fff;
  font-size: 14px;
  cursor: pointer;
}
.fatal-card button:hover { background: #2a5ce6; }
</style>
