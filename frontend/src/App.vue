<template>
  <router-view />
  <div class="toast-wrap">
    <div v-for="t in toastStore.list" :key="t.id" class="toast" :class="`toast-${t.type}`">
      {{ t.msg }}
    </div>
  </div>
</template>

<script setup>
import { useToastStore } from '@/stores/toast'
const toastStore = useToastStore()
</script>
