<template>
  <router-view />
  <div class="toast-wrap">
    <div v-for="t in toastStore.list" :key="t.id" class="toast" :class="`toast-${t.type}`">
      {{ t.msg }}
    </div>
  </div>
</template>

<script setup>
import { watch } from 'vue'
import { useToastStore } from '@/stores/toast'
import { useAuthStore } from '@/stores/auth'
import { useTaskStore } from '@/stores/task'
import { useChannelStore } from '@/stores/channel'

const toastStore = useToastStore()
const auth = useAuthStore()
const taskStore = useTaskStore()
const channel = useChannelStore()

// 登出 / token 失效（401）时统一清空当前用户会话数据，
// 避免切换账号后残留上一账号的任务列表、流程图与执行日志
watch(() => auth.isLogin, (v) => {
  if (!v) {
    taskStore.reset()
    channel.reset()
  }
})
</script>
